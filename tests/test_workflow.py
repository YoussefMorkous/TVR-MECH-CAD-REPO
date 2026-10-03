import contextlib
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

SOURCE = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, SOURCE / 'tools' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cad = load('cad')
validator = load('validate')


class WorkflowTests(unittest.TestCase):
    def test_shared_status_and_overdue_boundary_without_local_session(self):
        now = datetime(2026, 10, 3, 16, tzinfo=timezone.utc)
        locks = [{'id': '1', 'path': cad.LOCK, 'owner': {'name': 'Engineer'},
                  'locked_at': '2026-10-02T16:00:00Z'}]
        status = cad.active_edit_status(locks, now)
        self.assertEqual(status['owner'], 'Engineer')
        self.assertEqual(status['age_hours'], 24)
        self.assertTrue(status['overdue'])
        self.assertIn('Viewing/downloads are available', cad.status_text(status))
        self.assertFalse(cad.active_edit_status([], now)['active'])
        with patch.object(cad, 'lock_list', return_value=locks), contextlib.redirect_stdout(__import__('io').StringIO()) as output:
            cad.show_status()
        self.assertNotIn('local', json.loads(output.getvalue()))

    def test_missing_timestamp_and_orphan_locks_are_not_reported_as_free(self):
        status = cad.active_edit_status([{'id': '1', 'path': cad.LOCK}])
        self.assertIsNone(status['age_hours'])
        self.assertFalse(status['overdue'])
        status = cad.active_edit_status([{'id': '2', 'path': 'cad/Mount.SLDPRT'}])
        self.assertIn('Leftover CAD locks', cad.status_text(status))

    def test_current_and_older_lock_json_formats(self):
        lock = {'id': '123', 'path': 'cad/.edit-lock'}
        self.assertEqual(cad.lock_result(json.dumps(lock)), lock)
        self.assertEqual(cad.lock_result(json.dumps([lock])), lock)
        self.assertEqual(cad.lock_result(json.dumps({'lock': lock})), lock)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'repo'
        self.root.mkdir()
        self.root_patch = patch.object(cad, 'ROOT', self.root)
        self.root_patch.start()
        self.g('init', '-b', 'main')
        self.g('config', 'user.name', 'Test Engineer')
        self.g('config', 'user.email', 'engineer@example.com')
        self.g('lfs', 'install', '--local')
        shutil.copyfile(SOURCE / '.gitattributes', self.root / '.gitattributes')
        shutil.copyfile(SOURCE / '.gitignore', self.root / '.gitignore')
        shutil.copytree(SOURCE / 'tools', self.root / 'tools', ignore=shutil.ignore_patterns('__pycache__'))
        (self.root / 'cad').mkdir()
        (self.root / 'cad/.edit-lock').write_text('initial lock\n')
        (self.root / 'cad/Main.SLDASM').write_bytes(b'original assembly geometry')
        (self.root / 'cad/Mount.SLDPRT').write_bytes(b'original mount geometry')
        (self.root / 'cad/Ring.sldprt').write_bytes(b'original ring geometry')
        self.g('add', '.')
        self.g('commit', '-m', 'Initial assembly')
        self.base = self.g('rev-parse', 'HEAD')
        self.before = cad.inventory()
        self.origin = Path(self.tmp.name) / 'origin.git'
        subprocess.run(['git', 'init', '--bare', str(self.origin)], check=True, capture_output=True)
        self.g('remote', 'add', 'origin', str(self.origin))
        # Disable the pre-push LFS upload; all tests use local cached objects.
        self.g('-c', 'core.hooksPath=/dev/null', 'push', '-u', 'origin', 'main')

    def tearDown(self):
        self.root_patch.stop()
        self.tmp.cleanup()

    def g(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.root, stderr=subprocess.DEVNULL).decode().strip()

    def validate(self, staged=True, base=None):
        def local_git(*args):
            return subprocess.check_output(['git', *args], cwd=self.root)
        with patch.object(validator, 'git', local_git):
            return validator.validate(base or self.base, staged=staged)

    def stage_change(self, allowed=None, mbase=None):
        (self.root / 'cad/Mount.SLDPRT').write_bytes(b'new mount geometry')
        (self.root / 'cad/.edit-lock').write_text('new session\n')
        manifest = dict(id='a' * 32, base=mbase or self.base, reason='Motor clearance',
                        allowed=allowed if allowed is not None else ['cad/Mount.SLDPRT'],
                        changes={'cad/Mount.SLDPRT': 'modified'})
        (self.root / 'changes').mkdir(exist_ok=True)
        (self.root / ('changes/' + 'a' * 32 + '.json')).write_text(json.dumps(manifest))
        self.g('add', '.')

    def test_snapshot_restores_entire_original_tree(self):
        self.stage_change()
        self.validate()
        self.g('commit', '-m', 'Modify mount')
        changed = cad.inventory()
        self.assertNotEqual(changed['cad/Mount.SLDPRT'], self.before['cad/Mount.SLDPRT'])
        self.g('checkout', '--detach', self.base)
        self.assertEqual(cad.inventory(), self.before)
        output = Path(self.tmp.name) / 'old.zip'
        cad.export_zip(output)
        with zipfile.ZipFile(output) as z:
            self.assertEqual(z.read('cad/Mount.SLDPRT'), b'original mount geometry')
            self.assertEqual(z.read('cad/Main.SLDASM'), b'original assembly geometry')

    def test_changed_files_only(self):
        self.stage_change()
        self.assertEqual(cad.diff(self.before, cad.inventory()), {'cad/Mount.SLDPRT': 'modified'})
        self.assertEqual(self.g('show', ':cad/Ring.sldprt'), self.g('show', self.base + ':cad/Ring.sldprt'))
        self.validate()

    def test_unexpected_change_rejected(self):
        self.stage_change(allowed=['cad/Ring.sldprt'])
        with self.assertRaisesRegex(ValueError, 'outside requested scope'):
            self.validate()

    def test_stale_snapshot_rejected(self):
        self.stage_change(mbase='b' * 40)
        with self.assertRaisesRegex(ValueError, 'Stale snapshot'):
            self.validate()

    def test_raw_native_binary_rejected(self):
        self.stage_change()
        oid = self.g('hash-object', '-w', '--no-filters', 'cad/Mount.SLDPRT')
        self.g('update-index', '--cacheinfo', '100644', oid, 'cad/Mount.SLDPRT')
        with self.assertRaisesRegex(ValueError, 'Git LFS'):
            self.validate()

    def test_tool_changes_cannot_be_hidden_in_cad_pr(self):
        self.stage_change()
        (self.root / 'tools/evil.py').write_text('raise SystemExit()')
        self.g('add', 'tools/evil.py')
        with self.assertRaisesRegex(ValueError, 'separate PR'):
            self.validate()

    def test_zip_traversal_is_rejected_before_write(self):
        archive = Path(self.tmp.name) / 'bad.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('cad/../../outside.SLDPRT', b'bad')
        with patch.object(cad, 'session', return_value={'phase': 'editing'}):
            with self.assertRaisesRegex(RuntimeError, 'safe path'):
                cad.import_zip(archive)
        self.assertEqual(cad.inventory(), self.before)

    def test_zip_unexpected_modification_preserves_workspace(self):
        archive = Path(self.tmp.name) / 'bad.zip'
        cad.export_zip(archive)
        with zipfile.ZipFile(archive, 'a') as z:
            z.writestr('cad/New.SLDPRT', b'new')
        s = {'phase': 'editing', 'baseline': self.before, 'allowed': ['cad/Mount.SLDPRT']}
        with patch.object(cad, 'session', return_value=s):
            with self.assertRaisesRegex(RuntimeError, 'outside the selected scope'):
                cad.import_zip(archive)
        self.assertEqual(cad.inventory(), self.before)

    def test_lfs_pointer_is_never_exported_as_cad(self):
        (self.root / 'cad/Mount.SLDPRT').write_text(self.g('show', 'HEAD:cad/Mount.SLDPRT'))
        with self.assertRaisesRegex(RuntimeError, 'LFS pointer'):
            cad.export_zip(Path(self.tmp.name) / 'broken.zip')

    def test_lock_acquisition_rolls_back_on_failure(self):
        actual = cad.git
        acquired, released = [], []
        def server(*args, **kwargs):
            if args[:2] == ('lfs', 'pull'):
                return ''
            if args[:2] == ('lfs', 'lock'):
                if acquired:
                    raise RuntimeError('Component already locked')
                acquired.append(args[-1])
                return json.dumps({'id': '123', 'path': args[-1]})
            if args[:2] == ('lfs', 'unlock'):
                released.append(args[-1])
                return ''
            return actual(*args, **kwargs)
        with patch.object(cad, 'git', server):
            with self.assertRaisesRegex(RuntimeError, 'already locked'):
                cad.start(['cad/Mount.SLDPRT'], 'Fit motor')
        self.assertEqual(acquired, ['cad/.edit-lock'])
        self.assertEqual(released, ['123'])
        self.assertFalse(cad.state_file().exists())

    def test_lost_lock_blocks_submit(self):
        with patch.object(cad, 'git', return_value=json.dumps({'ours': [], 'theirs': []})):
            with self.assertRaisesRegex(RuntimeError, 'lock was lost'):
                cad.check_locks({'locks': [{'id': '1', 'path': 'cad/.edit-lock'}]})

    def test_separate_tooling_pr_is_allowed(self):
        (self.root / 'tools/new.py').write_text('print("updated helper")')
        self.g('add', 'tools/new.py')
        self.assertEqual(self.validate(), 'No CAD changes.')

    def test_session_includes_parent_assemblies(self):
        actual = cad.git
        locks = []
        def server(*args, **kwargs):
            if args[:2] == ('lfs', 'pull'):
                return ''
            if args[:2] == ('lfs', 'lock'):
                locks.append(args[-1])
                return json.dumps({'id': str(len(locks)), 'path': args[-1]})
            return actual(*args, **kwargs)
        with patch.object(cad, 'git', server):
            cad.start(['cad/Mount.SLDPRT'], 'Fit motor')
        s = cad.session()
        self.assertEqual(s['allowed'], ['cad/Main.SLDASM', 'cad/Mount.SLDPRT'])
        self.assertEqual(locks, ['cad/.edit-lock', 'cad/Main.SLDASM', 'cad/Mount.SLDPRT'])
        self.assertEqual(s['base'], self.base)

    def test_submit_retry_reuses_commit_and_releases_after_merge(self):
        actual_git, actual_run = cad.git, cad.run
        owned = []
        def server(*args, **kwargs):
            if args[:2] == ('lfs', 'pull') or args[0] == 'push':
                return ''
            if args[:2] == ('lfs', 'lock'):
                lock = {'id': str(len(owned) + 1), 'path': args[-1]}
                owned.append(lock)
                return json.dumps(lock)
            if args[:2] == ('lfs', 'locks'):
                return json.dumps({'ours': owned, 'theirs': []})
            if args[:2] == ('lfs', 'unlock'):
                owned[:] = [x for x in owned if x['id'] != args[-1]]
                return ''
            return actual_git(*args, **kwargs)
        def cli(*args, **kwargs):
            if args[:3] == ('gh', 'pr', 'list'):
                return json.dumps([{'state': 'MERGED', 'url': 'https://example.com/pr/1'}]) if '--state' in args else '[]'
            if args[:3] == ('gh', 'pr', 'create'):
                return 'https://example.com/pr/1'
            return actual_run(*args, **kwargs)
        with patch.object(cad, 'git', server), patch.object(cad, 'run', cli):
            cad.start(['cad/Mount.SLDPRT'], 'Fit motor')
            (self.root / 'cad/Mount.SLDPRT').write_bytes(b'updated motor fit')
            cad.submit()
            first = self.g('rev-parse', 'HEAD')
            cad.submit()
            self.assertEqual(first, self.g('rev-parse', 'HEAD'))
            self.validate(staged=False)
            cad.finish()
        self.assertEqual(owned, [])
        self.assertFalse(cad.state_file().exists())

    def cancellation_session(self, phase='editing'):
        self.g('switch', '-c', 'cad/edit-canceltest')
        state = dict(id='c' * 32, branch='cad/edit-canceltest', base=self.base,
                     reason='Test cancellation', baseline=self.before, phase=phase,
                     allowed=['cad/Mount.SLDPRT'],
                     locks=[{'id': 'global', 'path': cad.LOCK},
                            {'id': 'part', 'path': 'cad/Mount.SLDPRT'}])
        cad.save(state)
        return state

    def test_cancel_preserves_staged_and_untracked_work_before_unlocking(self):
        self.cancellation_session()
        (self.root / 'cad/Mount.SLDPRT').write_bytes(b'unfinished motor fit')
        (self.root / 'cad/New.SLDPRT').write_bytes(b'untracked part')
        (self.root / 'notes.txt').write_text('Keep these notes')
        self.g('add', 'cad/Mount.SLDPRT')
        actual = cad.git
        released = []
        def server(*args, **kwargs):
            if args[:2] == ('lfs', 'unlock'):
                self.assertEqual(self.g('status', '--porcelain'), '')
                self.assertTrue(list((self.root / 'exports').glob('*.zip')))
                released.append(args[-1])
                return ''
            return actual(*args, **kwargs)
        actual_run = cad.run
        def cli(*args, **kwargs):
            return '[]' if args[:3] == ('gh', 'pr', 'list') else actual_run(*args, **kwargs)
        with patch.object(cad, 'git', server), patch.object(cad, 'run', cli):
            cad.cancel()
        self.assertEqual(released, ['part', 'global'])
        self.assertFalse(cad.state_file().exists())
        with zipfile.ZipFile(next((self.root / 'exports').glob('*.zip'))) as z:
            self.assertEqual(z.read('cad/Mount.SLDPRT'), b'unfinished motor fit')
            self.assertEqual(z.read('cad/New.SLDPRT'), b'untracked part')
        journal = json.loads(next((self.root / 'exports').glob('*recovery.json')).read_text())
        stash = next(entry['stash'] for entry in journal['recovery'] if 'stash' in entry)
        self.g('stash', 'apply', '--index', stash)
        self.assertEqual((self.root / 'notes.txt').read_text(), 'Keep these notes')
        self.assertEqual((self.root / 'cad/New.SLDPRT').read_bytes(), b'untracked part')
        self.assertIn('M  cad/Mount.SLDPRT', self.g('status', '--porcelain'))

    def test_cancel_unlock_failure_keeps_global_lock_and_retries_safely(self):
        self.cancellation_session()
        (self.root / 'cad/Mount.SLDPRT').write_bytes(b'preserve work through network failure')
        actual_git, actual_run = cad.git, cad.run
        released = []
        fail = [True]
        def server(*args, **kwargs):
            if args[:2] == ('lfs', 'unlock'):
                if fail[0]:
                    raise RuntimeError('Network unavailable')
                released.append(args[-1])
                return ''
            return actual_git(*args, **kwargs)
        def cli(*args, **kwargs):
            return '[]' if args[:3] == ('gh', 'pr', 'list') else actual_run(*args, **kwargs)
        with patch.object(cad, 'git', server), patch.object(cad, 'run', cli):
            with self.assertRaisesRegex(RuntimeError, 'Network unavailable'):
                cad.cancel()
            self.assertEqual(released, [])
            self.assertEqual(cad.session()['phase'], 'canceling')
            self.assertEqual(len(cad.session()['locks']), 2)
            with self.assertRaisesRegex(RuntimeError, 'retry Cancel'):
                cad.submit()
            fail[0] = False
            cad.cancel()
        self.assertEqual(released, ['part', 'global'])
        self.assertFalse(cad.state_file().exists())

    def test_cancel_cannot_release_locks_while_pr_is_still_open(self):
        self.cancellation_session(phase='submitted')
        actual_run = cad.run
        calls = []
        def cli(*args, **kwargs):
            if args[:2] == ('gh', 'pr'):
                calls.append(args)
                return json.dumps([{'state': 'OPEN', 'number': 7, 'url': 'https://example.com/pr/7'}]) if args[2] == 'list' else ''
            return actual_run(*args, **kwargs)
        with patch.object(cad, 'run', cli), patch.object(cad, 'release_locks') as release:
            with self.assertRaisesRegex(RuntimeError, 'still open'):
                cad.cancel()
        release.assert_not_called()
        self.assertIn(('gh', 'pr', 'close', '7'), calls)
        self.assertEqual(cad.session()['phase'], 'canceling')

    def test_partial_unlock_retains_only_remaining_ids(self):
        state = self.cancellation_session()
        state['locks'].append({'id': 'second', 'path': 'cad/Ring.sldprt'})
        cad.save(state)
        attempted = []
        actual = cad.git
        def server(*args, **kwargs):
            if args[:2] != ('lfs', 'unlock'):
                return actual(*args, **kwargs)
            attempted.append(args[-1])
            if args[-1] == 'part':
                raise RuntimeError('Server unavailable')
            return ''
        with patch.object(cad, 'git', server):
            with self.assertRaisesRegex(RuntimeError, 'Server unavailable'):
                cad.release_locks(state)
        self.assertEqual(attempted, ['second', 'part'])
        self.assertEqual([lock['id'] for lock in cad.session()['locks']], ['global', 'part'])


if __name__ == '__main__':
    unittest.main()
