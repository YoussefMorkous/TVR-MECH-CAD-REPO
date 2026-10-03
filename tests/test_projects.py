"""Project isolation against real Git/LFS repositories; only GitHub services are mocked."""
import contextlib
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
import zipfile

import test_workflow as workflow

cad = workflow.cad


class ProjectTests(unittest.TestCase):
    setUp = workflow.WorkflowTests.setUp
    tearDown = workflow.WorkflowTests.tearDown
    g = workflow.WorkflowTests.g
    validate = workflow.WorkflowTests.validate

    def add_projects(self):
        for identifier, name in [('v2', 'V2'), ('cage-testing', 'Cage testing frames')]:
            folder = self.root / cad.project_root(identifier)
            folder.mkdir(parents=True)
            (folder / cad.PROJECT_META).write_text(json.dumps(dict(schema=1, id=identifier, name=name)))
            (folder / '.edit-lock').write_text('initial\n')
            (folder / 'Main.SLDASM').write_bytes(identifier.encode() + b' assembly')
            (folder / 'Part.SLDPRT').write_bytes(identifier.encode() + b' part')
        self.g('add', 'cad')
        self.g('commit', '-m', 'Import two projects')
        self.g('-c', 'core.hooksPath=/dev/null', 'push', 'origin', 'main')
        self.base = self.g('rev-parse', 'HEAD')
        self.before = cad.inventory()

    @contextlib.contextmanager
    def server(self, locks=None):
        owned = [] if locks is None else locks
        actual_git, actual_run = cad.git, cad.run
        def git(*args, **kwargs):
            if args[:2] == ('lfs', 'pull') or args[0] == 'push':
                return ''
            if args[:2] == ('lfs', 'locks'):
                return json.dumps({'ours': owned, 'theirs': []} if '--verify' in args else {'locks': owned})
            if args[:2] == ('lfs', 'lock'):
                if any(lock['path'] == args[-1] for lock in owned):
                    raise RuntimeError('Project already locked')
                lock = {'id': 'lock-' + args[-1], 'path': args[-1]}
                owned.append(lock)
                return json.dumps(lock)
            if args[:2] == ('lfs', 'unlock'):
                owned[:] = [lock for lock in owned if lock['id'] != args[-1]]
                return ''
            return actual_git(*args, **kwargs)
        def run(*args, **kwargs):
            if args[:3] == ('gh', 'pr', 'list'):
                return '[]'
            if args[:3] == ('gh', 'pr', 'create'):
                return 'https://example.com/pr/6'
            return actual_run(*args, **kwargs)
        with patch.object(cad, 'git', git), patch.object(cad, 'run', run):
            yield owned

    def advance_main(self, path):
        work = Path(self.tmp.name) / 'other-member'
        self.g('worktree', 'add', str(work), 'main')
        def git(*args):
            return subprocess.check_output(['git', *args], cwd=work, stderr=subprocess.DEVNULL).decode().strip()
        try:
            (work / path).chmod(0o644)
            (work / path).write_bytes(b'other member changed geometry')
            git('add', path)
            git('commit', '-m', 'Other project update')
            git('-c', 'core.hooksPath=/dev/null', 'push', 'origin', 'main')
            return git('rev-parse', 'HEAD')
        finally:
            self.g('worktree', 'remove', str(work))

    def test_catalog_and_downloads_keep_legacy_separate(self):
        self.add_projects()
        self.assertEqual(cad.projects()['cage-testing'], 'Cage testing frames')
        self.assertNotIn('cad/projects/v2/Main.SLDASM', cad.inventory(project=cad.LEGACY))
        for project in [cad.LEGACY, 'v2', 'cage-testing']:
            dest = Path(self.tmp.name) / (project + '.zip')
            cad.export_zip(dest, project=project)
            with zipfile.ZipFile(dest) as archive:
                self.assertTrue(all(cad.in_project(p, project) for p in archive.namelist()))
                self.assertFalse(any(p.endswith('.edit-lock') for p in archive.namelist()))

    def test_project_scope_and_parent_assemblies_are_isolated(self):
        self.add_projects()
        with self.server() as locks:
            cad.start(['cad/projects/v2/Part.SLDPRT'], 'V2 bracket', project='v2')
            self.assertEqual([lock['path'] for lock in locks], [
                'cad/projects/v2/.edit-lock', 'cad/projects/v2/Main.SLDASM', 'cad/projects/v2/Part.SLDPRT'])
            with self.assertRaisesRegex(RuntimeError, 'another project'):
                cad.allow(['cad/projects/cage-testing/Part.SLDPRT'])
            with self.assertRaisesRegex(RuntimeError, 'managed by the helper'):
                cad.allow(['cad/projects/v2/_project.json'])
            with self.assertRaisesRegex(RuntimeError, 'current edit'):
                cad.refresh_projects()

    def test_legacy_session_excludes_new_project_assemblies(self):
        self.add_projects()
        with self.server():
            cad.start(['cad/Mount.SLDPRT'], 'Rocket bracket')
        self.assertEqual(cad.session()['allowed'], ['cad/Main.SLDASM', 'cad/Mount.SLDPRT'])

    def test_new_project_import_submits_without_changing_existing_cad(self):
        source = Path(self.tmp.name) / 'pack-and-go'
        (source / 'parts').mkdir(parents=True)
        (source / 'Main.SLDASM').write_bytes(b'new complete assembly')
        (source / 'parts/Bracket.SLDPRT').write_bytes(b'new bracket')
        with self.server():
            cad.seed(source, project='v2', name='V2')
            self.assertEqual(cad.projects()['v2'], 'V2')
            self.assertEqual(cad.inventory(project=cad.LEGACY), self.before)
            cad.submit()
        self.validate(staged=False)
        manifest = json.loads((self.root / 'changes' / (cad.session()['id'] + '.json')).read_text())
        self.assertEqual(manifest['project'], 'v2')
        self.assertEqual(set(manifest['changes']), {
            'cad/projects/v2/_project.json', 'cad/projects/v2/Main.SLDASM', 'cad/projects/v2/parts/Bracket.SLDPRT'})

    def test_duplicate_project_id_and_same_project_lock_are_rejected(self):
        self.add_projects()
        source = Path(self.tmp.name) / 'pack'
        source.mkdir()
        (source / 'Main.SLDASM').write_bytes(b'assembly')
        with self.assertRaisesRegex(RuntimeError, 'empty project'):
            cad.seed(source, project='v2', name='Other V2')
        other_lock = {'id': 'other', 'path': 'cad/projects/v2/.edit-lock'}
        with self.server([other_lock]):
            with self.assertRaisesRegex(RuntimeError, 'already locked'):
                cad.start(['cad/projects/v2/Part.SLDPRT'], 'Change V2', project='v2')
        self.assertFalse(cad.state_file().exists())
        self.assertEqual(cad.inventory(), self.before)

    def test_invalid_project_ids_and_incomplete_packages_do_not_start_sessions(self):
        for identifier in ['../v2', 'V2', 'con', '', 'a' * 49]:
            with self.assertRaises(RuntimeError):
                cad.project_root(identifier)
        source = Path(self.tmp.name) / 'parts-only'
        source.mkdir()
        (source / 'Part.SLDPRT').write_bytes(b'part')
        with self.assertRaisesRegex(RuntimeError, 'containing an assembly'):
            cad.seed(source, project='v2', name='V2')
        self.assertFalse(cad.state_file().exists())

    def test_returned_zip_from_other_project_is_rejected_without_writes(self):
        self.add_projects()
        archive = Path(self.tmp.name) / 'cage.zip'
        cad.export_zip(archive, project='cage-testing')
        with self.server():
            cad.start(['cad/projects/v2/Part.SLDPRT'], 'V2 changes', project='v2')
            with self.assertRaisesRegex(RuntimeError, 'another project'):
                cad.import_zip(archive)
        self.assertEqual(cad.inventory(), self.before)

    def test_returned_project_zip_preserves_other_projects(self):
        self.add_projects()
        with self.server():
            cad.start(['cad/projects/v2/Part.SLDPRT'], 'V2 changes', project='v2')
            archive = Path(self.tmp.name) / 'v2.zip'
            cad.export_zip(archive, project='v2', editable=True)
            edited = Path(self.tmp.name) / 'edited.zip'
            with zipfile.ZipFile(archive) as original, zipfile.ZipFile(edited, 'w') as result:
                for name in original.namelist():
                    result.writestr(name, b'edited bracket' if name.endswith('Part.SLDPRT') else original.read(name))
            cad.import_zip(edited)
        self.assertEqual(cad.inventory(project='cage-testing'), cad.project_files(self.before, 'cage-testing'))
        self.assertEqual(cad.inventory(project=cad.LEGACY), cad.project_files(self.before, cad.LEGACY))

    def test_returned_zip_restores_baseline_bytes_over_local_edits(self):
        self.add_projects()
        part = 'cad/projects/v2/Part.SLDPRT'
        with self.server():
            cad.start([part], 'Review returned V2', project='v2')
            archive = Path(self.tmp.name) / 'original-v2.zip'
            cad.export_zip(archive, project='v2', editable=True)
            (self.root / part).write_bytes(b'local draft to replace')
            cad.import_zip(archive)
        self.assertEqual((self.root / part).read_bytes(), b'v2 part')
        with zipfile.ZipFile(next((self.root / 'exports').glob('before-import-*.zip'))) as backup:
            self.assertEqual(backup.read(part), b'local draft to replace')

    def test_returned_zip_does_not_restore_out_of_scope_local_edits(self):
        self.add_projects()
        part = 'cad/projects/v2/Part.SLDPRT'
        other = 'cad/projects/v2/Other.SLDPRT'
        (self.root / other).write_bytes(b'original other')
        self.g('add', other)
        self.g('commit', '-m', 'Add unrelated component')
        self.g('-c', 'core.hooksPath=/dev/null', 'push', 'origin', 'main')
        with self.server():
            cad.start([part], 'Review returned V2', project='v2')
            archive = Path(self.tmp.name) / 'original-v2.zip'
            cad.export_zip(archive, project='v2', editable=True)
            (self.root / other).chmod(0o644)
            (self.root / other).write_bytes(b'out of scope local draft')
            with self.assertRaisesRegex(RuntimeError, 'outside the selected scope'):
                cad.import_zip(archive)
        self.assertEqual((self.root / other).read_bytes(), b'out of scope local draft')

    def test_validator_rejects_cross_project_changes_even_if_allowed(self):
        self.add_projects()
        with self.server():
            cad.start(['cad/projects/v2/Part.SLDPRT'], 'V2 changes', project='v2')
            (self.root / 'cad/projects/v2/Part.SLDPRT').write_bytes(b'new V2')
            cad.submit()
        other = 'cad/projects/cage-testing/Part.SLDPRT'
        (self.root / other).chmod(0o644)
        (self.root / other).write_bytes(b'bad cross-project edit')
        manifest_path = self.root / 'changes' / (cad.session()['id'] + '.json')
        manifest = json.loads(manifest_path.read_text())
        manifest['allowed'].append(other)
        manifest['changes'][other] = 'modified'
        manifest_path.write_text(json.dumps(manifest))
        self.g('add', '.')
        with self.assertRaisesRegex(ValueError, 'outside selected project'):
            self.validate()

    def test_unrelated_project_merge_updates_review_base_and_retry_reuses_commit(self):
        self.add_projects()
        with self.server():
            cad.start(['cad/projects/v2/Part.SLDPRT'], 'V2 changes', project='v2')
            (self.root / 'cad/projects/v2/Part.SLDPRT').write_bytes(b'new V2')
            latest = self.advance_main('cad/projects/cage-testing/Part.SLDPRT')
            cad.submit()
            self.assertEqual(cad.session()['base'], latest)
            self.validate(staged=False, base=latest)
            head = self.g('rev-parse', 'HEAD')
            cad.submit()
            self.assertEqual(self.g('rev-parse', 'HEAD'), head)
            self.assertEqual((self.root / 'cad/projects/cage-testing/Part.SLDPRT').read_bytes(), b'other member changed geometry')

    def test_same_project_main_change_blocks_submission_and_keeps_work(self):
        self.add_projects()
        with self.server():
            cad.start(['cad/projects/v2/Part.SLDPRT'], 'V2 changes', project='v2')
            (self.root / 'cad/projects/v2/Part.SLDPRT').write_bytes(b'keep my work')
            self.advance_main('cad/projects/v2/Part.SLDPRT')
            with self.assertRaisesRegex(RuntimeError, 'This project changed'):
                cad.submit()
        self.assertTrue(cad.session()['locks'])
        self.assertEqual((self.root / 'cad/projects/v2/Part.SLDPRT').read_bytes(), b'keep my work')

    def test_interrupted_review_base_update_can_be_retried_without_losing_locks(self):
        self.add_projects()
        with self.server():
            cad.start(['cad/projects/v2/Part.SLDPRT'], 'V2 changes', project='v2')
            (self.root / 'cad/projects/v2/Part.SLDPRT').write_bytes(b'new V2')
            latest = self.advance_main('cad/projects/cage-testing/Part.SLDPRT')
            original = cad.validate_staged
            def interrupted(base):
                if base == latest:
                    raise RuntimeError('Interrupted before committing new review base')
                return original(base)
            with patch.object(cad, 'validate_staged', interrupted):
                with self.assertRaisesRegex(RuntimeError, 'Interrupted'):
                    cad.submit()
            self.assertEqual(cad.session()['phase'], 'syncing')
            self.assertTrue(cad.session()['locks'])
            with self.assertRaisesRegex(RuntimeError, 'in progress'):
                cad.finish()
            cad.submit()
            self.assertEqual(cad.session()['base'], latest)
            self.assertEqual(cad.session()['phase'], 'submitted')
            self.validate(staged=False, base=latest)

    def test_other_project_lock_does_not_block_edit_or_get_released_by_cancel(self):
        self.add_projects()
        other = {'id': 'other-member', 'path': 'cad/projects/cage-testing/.edit-lock'}
        with self.server([other]) as locks:
            cad.start(['cad/projects/v2/Part.SLDPRT'], 'V2 changes', project='v2')
            (self.root / 'cad/projects/v2/Part.SLDPRT').write_bytes(b'keep canceled V2')
            cad.cancel()
            self.assertEqual(locks, [other])
            with zipfile.ZipFile(next((self.root / 'exports').glob('*.zip'))) as archive:
                self.assertTrue(all(cad.in_project(path, 'v2') for path in archive.namelist()))
                self.assertEqual(archive.read('cad/projects/v2/Part.SLDPRT'), b'keep canceled V2')

    def test_project_status_ignores_another_projects_locks(self):
        now = datetime(2026, 10, 3, 16, tzinfo=timezone.utc)
        locks = [{'id': '1', 'path': 'cad/projects/v2/.edit-lock', 'owner': {'name': 'Editor'},
                  'locked_at': '2026-10-02T16:00:00Z'}]
        self.assertTrue(cad.active_edit_status(locks, now, 'v2')['active'])
        self.assertFalse(cad.active_edit_status(locks, now, 'cage-testing')['active'])
        self.assertFalse(cad.active_edit_status(locks, now)['leftover_locks'])
        self.assertEqual(list(cad.all_edit_status(locks, now)), ['v2'])


if __name__ == '__main__':
    unittest.main()
