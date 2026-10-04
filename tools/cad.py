"""Small, dependency-free TVR CAD client. Git, Git LFS and gh are required."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
NATIVE = {'.sldprt', '.sldasm', '.slddrw'}
LOCK = 'cad/.edit-lock'
OVERDUE_HOURS = 24
LEGACY = 'legacy'
PROJECT_META = '_project.json'


def project_root(project=LEGACY):
    if project == LEGACY:
        return 'cad'
    if not isinstance(project, str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', project) or len(project) > 48:
        raise RuntimeError('Project ID must use lowercase letters, numbers and single hyphens (maximum 48 characters).')
    safe_path('cad/projects/' + project)
    return 'cad/projects/' + project


def project_lock(project=LEGACY):
    return project_root(project) + '/.edit-lock'


def in_project(path, project):
    prefix = project_root(project) + '/'
    return path.startswith(prefix) and (project != LEGACY or not path.startswith('cad/projects/'))


def project_files(files, project):
    return {p: value for p, value in files.items() if in_project(p, project)}


def require_project_path(path, project, metadata=False):
    safe_path(path)
    if not in_project(path, project):
        raise RuntimeError('File belongs to another project: ' + path)
    if Path(path).name == PROJECT_META and not metadata:
        raise RuntimeError('Project details are managed by the helper.')


def projects(root=None):
    root = ROOT if root is None else root
    result = {LEGACY: 'TVR Rocket (existing assembly)'}
    folder = root / 'cad/projects'
    if folder.exists():
        for path in sorted(folder.iterdir()):
            if path.is_symlink():
                raise RuntimeError('Project folders cannot be symlinks.')
            if not path.is_dir():
                raise RuntimeError('Unexpected file in cad/projects: ' + path.name)
            project_root(path.name)
            if path.name == LEGACY:
                raise RuntimeError('The project ID legacy is reserved.')
            data = json.loads((path / PROJECT_META).read_text(encoding='utf-8'))
            name = data.get('name')
            if data.get('id') != path.name or data.get('schema') != 1 or not isinstance(name, str) or not name.strip() or len(name) > 100:
                raise RuntimeError('Invalid project details: ' + str(path))
            result[path.name] = name
    return result


def refresh_projects():
    if state_file().exists():
        raise RuntimeError('Finish or cancel your current edit before updating projects.')
    ensure_clean()
    git('fetch', 'origin', 'main')
    git('switch', '--detach', 'origin/main')
    git('lfs', 'pull')
    return 'Project list updated from the approved main branch.'


def run(*args, cwd=None, env=None, timeout=None):
    try:
        p = subprocess.run(args, cwd=cwd or ROOT, env=env, capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError('Server check timed out. Try again when the connection is available.') from e
    if p.returncode:
        raise RuntimeError(p.stderr.strip() or p.stdout.strip() or 'Command failed')
    return p.stdout.strip()


def git(*args, cwd=None, timeout=None):
    return run('git', *args, cwd=cwd, timeout=timeout)


def state_file():
    return ROOT / git('rev-parse', '--git-path', 'tvr-session.json')


def session():
    p = state_file()
    if not p.exists():
        raise RuntimeError('No active session. Start an edit first.')
    return json.loads(p.read_text(encoding='utf-8'))


def save(s):
    state_file().write_text(json.dumps(s, indent=2), encoding='utf-8')


def lock_result(output):
    obj = json.loads(output)
    if isinstance(obj, list):
        if len(obj) != 1:
            raise RuntimeError('Expected exactly one file lock.')
        obj = obj[0]
    lock = obj.get('lock', obj)
    if not lock.get('id'):
        raise RuntimeError('Lock server did not return an ID.')
    return lock


def lock_list():
    obj = json.loads(git('lfs', 'locks', '--json', timeout=15))
    locks = obj if isinstance(obj, list) else obj.get('locks')
    if not isinstance(locks, list) or any(not isinstance(lock, dict) or not lock.get('id')
                                         or not isinstance(lock.get('path'), str) for lock in locks):
        raise RuntimeError('Lock server returned an unexpected response.')
    return locks


def active_edit_status(locks=None, now=None, project=LEGACY):
    locks = lock_list() if locks is None else locks
    now = now or datetime.now(timezone.utc)
    active = [lock for lock in locks if lock.get('path') == project_lock(project)]
    if len(active) > 1:
        raise RuntimeError('Multiple assembly locks reported. Ask the lead to investigate.')
    if not active:
        leftovers = [lock for lock in locks if in_project(lock.get('path', ''), project)]
        return {'active': False, 'leftover_locks': leftovers}
    lock = active[0]
    age = None
    try:
        started = datetime.fromisoformat(lock['locked_at'].replace('Z', '+00:00'))
        if started.tzinfo is not None:
            age = max(0, (now - started).total_seconds() / 3600)
    except (KeyError, TypeError, ValueError):
        pass
    return {'active': True, 'lock_id': str(lock['id']),
            'owner': (lock.get('owner') or {}).get('name') or 'Unknown editor',
            'locked_at': lock.get('locked_at'), 'age_hours': age,
            'overdue': age is not None and age >= OVERDUE_HOURS}


def all_edit_status(locks, now=None):
    identifiers = {LEGACY} if any(lock.get('path') == LOCK for lock in locks) else set()
    for lock in locks:
        match = re.fullmatch(r'cad/projects/([a-z0-9]+(?:-[a-z0-9]+)*)/\.edit-lock', lock.get('path', ''))
        if match:
            project_root(match[1])
            if match[1] == LEGACY:
                raise RuntimeError('Invalid reserved project lock.')
            identifiers.add(match[1])
    return {project: active_edit_status(locks, now, project) for project in sorted(identifiers)}


def status_text(status):
    if not status['active']:
        if status.get('leftover_locks'):
            return 'Leftover CAD locks remain. Ask the lead to check. Viewing/downloads are available.'
        return 'No active edit. Viewing/downloads are available.'
    age = status['age_hours']
    elapsed = f'{age:.1f} hours' if age is not None else 'start time unknown'
    text = f"Currently being edited by {status['owner']} ({elapsed}). Viewing/downloads are available."
    if status['overdue']:
        text += ' Overdue: finish or cancel your session, or contact the lead.'
    return text


def show_status():
    locks = lock_list()
    result = {'shared': active_edit_status(locks), 'projects': all_edit_status(locks)}
    if state_file().exists():
        s = session()
        result['local'] = {'project': s.get('project', LEGACY), 'branch': s['branch'], 'phase': s['phase'],
                           'changes': diff(s['baseline'], inventory()),
                           'recovery': s.get('recovery', [])}
    print(json.dumps(result, indent=2))


def inventory(root=None, project=None):
    root = ROOT if root is None else root
    result = {}
    for p in sorted((root / 'cad').rglob('*')):
        if project is not None and not in_project(p.relative_to(root).as_posix(), project):
            continue
        if p.is_symlink():
            raise RuntimeError('Symlinks are not allowed in CAD packages.')
        if p.is_file() and p.name != '.edit-lock':
            if p.name.startswith('~$') or p.suffix.lower() in {'.sldbak', '.tmp', '.swp'}:
                continue
            h = hashlib.sha256()
            with p.open('rb') as f:
                for block in iter(lambda: f.read(1024 * 1024), b''):
                    h.update(block)
            result[p.relative_to(root).as_posix()] = h.hexdigest()
    return result


def diff(before, after):
    return {p: ('added' if p not in before else 'deleted' if p not in after else 'modified')
            for p in sorted(before.keys() | after.keys()) if before.get(p) != after.get(p)}


def safe_path(value):
    p = PurePosixPath(value)
    if ('\\' in value or ':' in value or p.is_absolute() or
            '..' in p.parts or not p.parts or p.parts[0] != 'cad' or
            any(part.startswith('.') for part in p.parts[1:]) or
            any(part.endswith((' ', '.')) for part in p.parts)):
        raise RuntimeError('Expected a safe path below cad/: ' + value)
    reserved = {'CON', 'PRN', 'AUX', 'NUL'} | {f'{s}{n}' for s in ('COM', 'LPT') for n in range(1, 10)}
    if any(part.split('.')[0].upper() in reserved for part in p.parts):
        raise RuntimeError('Windows reserved filename: ' + value)
    return p


def ensure_clean():
    if git('status', '--porcelain'):
        raise RuntimeError('Workspace has changes. Finish/back up the current work first.')


def setup():
    run('gh', 'auth', 'status')
    run('gh', 'auth', 'setup-git')
    git('lfs', 'install', '--local')
    git('config', 'lfs.https://github.com/.locksverify', 'true')
    git('config', 'core.longpaths', 'true')
    git('lfs', 'pull')
    print('Ready. Keep this clone outside OneDrive and other sync folders.')


def start(paths, reason, initial=False, project=LEGACY):
    ensure_clean()
    if state_file().exists():
        raise RuntimeError('Finish the existing edit session first.')
    git('fetch', 'origin', 'main')
    git('switch', '--detach', 'origin/main')
    git('lfs', 'pull')
    baseline = inventory()
    existing = projects()
    if project not in existing and not initial:
        raise RuntimeError('Project not found. Refresh projects first.')
    project_root(project)
    owned_files = project_files(baseline, project)
    if initial and owned_files:
        raise RuntimeError('This project already contains files. Start a normal edit instead.')
    if not owned_files and not initial:
        raise RuntimeError('No CAD files yet. Import the initial Pack and Go first.')
    requested = sorted(set(paths))
    for p in requested:
        require_project_path(p, project)
        if p not in owned_files:
            raise RuntimeError('Select an existing file: ' + p)
    if not requested and not initial:
        raise RuntimeError('Select at least one component.')
    # Every parent assembly can require a save after a component change.
    allowed = sorted(set(requested) | {p for p in owned_files if Path(p).suffix.lower() == '.sldasm'})
    identifier = uuid.uuid4().hex
    s = dict(id=identifier, base=git('rev-parse', 'HEAD'), branch='cad/edit-' + identifier[:12],
             project=project, reason=reason, allowed=allowed, baseline=baseline, locks=[], phase='editing')
    try:
        # Each project serializes its own complete assembly edits.
        for p in [project_lock(project)] + [p for p in allowed if Path(p).suffix.lower() in NATIVE]:
            lock = lock_result(git('lfs', 'lock', '--json', p))
            s['locks'].append({'path': p, 'id': str(lock['id'])})
            save(s)  # Keep recovery information even if a later command fails.
        git('switch', '-c', s['branch'])
        marker = ROOT / project_lock(project)
        marker.parent.mkdir(parents=True, exist_ok=True)
        if marker.exists():
            marker.chmod(marker.stat().st_mode | stat.S_IWUSR)
        marker.write_text(identifier + '\n', encoding='utf-8')
        for p in allowed:
            fp = ROOT / p
            fp.chmod(fp.stat().st_mode | stat.S_IWUSR)
        save(s)
    except Exception:
        # Do not lose lock IDs when cleanup cannot reach the server.
        s['phase'] = 'cleanup'
        save(s)
        try:
            release_locks(s)
        except RuntimeError:
            pass  # Preserve the original failure; Finish can retry remaining IDs.
        raise
    print('Edit session started: ' + s['branch'])


def check_locks(s):
    obj = json.loads(git('lfs', 'locks', '--verify', '--json'))
    ours = {str(x['id']) for x in obj.get('ours', [])}
    if not {x['id'] for x in s['locks']} <= ours:
        raise RuntimeError('A required lock was lost. Contact the lead before submitting.')


def allow(paths, metadata=False):
    s = session()
    if s['phase'] != 'editing':
        raise RuntimeError('This session is already submitted; finish it first.')
    for p in paths:
        require_project_path(p, s.get('project', LEGACY), metadata=metadata)
        if p not in s['allowed']:
            if p in s['baseline'] and Path(p).suffix.lower() in NATIVE:
                lock = lock_result(git('lfs', 'lock', '--json', p))
                s['locks'].append({'path': p, 'id': str(lock['id'])})
            s['allowed'].append(p)
            save(s)
            if (ROOT / p).exists():
                fp = ROOT / p
                fp.chmod(fp.stat().st_mode | stat.S_IWUSR)
    print('Edit scope updated.')


def project_specs(project):
    return [project_root(project)] + ([':(exclude)cad/projects'] if project == LEGACY else [])


def validate_staged(base):
    # Reuse this interpreter on every platform, including Python.org installs
    # and virtual environments where a separate `python`/`py` is unavailable.
    run(sys.executable, str(ROOT / 'tools/validate.py'), '--base', base, '--staged')


def sync_review_base(s, target):
    # Use ordinary merge commits so already published edit branches never need force pushes.
    # Journal first; retrying Submit completes an interrupted merge/manifest update.
    if s['phase'] != 'syncing':
        s['resume_phase'] = s['phase']
        s['pending_base'] = target
        s['phase'] = 'syncing'
        save(s)
    if (ROOT / git('rev-parse', '--git-path', 'MERGE_HEAD')).exists():
        raise RuntimeError('A merge is unfinished. Keep your work and ask the lead to resolve it before retrying Submit.')
    git('merge', '--no-edit', target)
    path = ROOT / 'changes' / (s['id'] + '.json')
    manifest = json.loads(path.read_text(encoding='utf-8'))
    manifest['base'] = target
    path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    git('add', '--', path.relative_to(ROOT).as_posix())
    validate_staged(target)
    if git('diff', '--cached', '--name-only', 'HEAD'):
        git('commit', '-m', 'CAD: refresh review base for ' + s.get('project', LEGACY))
    s['base'] = target
    s['phase'] = s.pop('resume_phase')
    s.pop('pending_base')
    save(s)


def submit():
    s = session()
    if s['phase'] in ('cleanup', 'canceling'):
        raise RuntimeError('Finish cleanup or retry Cancel edit before submitting.')
    if git('branch', '--show-current') != s['branch']:
        raise RuntimeError('Return to your edit branch before submitting.')
    check_locks(s)
    if s['phase'] == 'syncing':
        sync_review_base(s, s['pending_base'])
    git('fetch', 'origin', 'main')
    target = git('rev-parse', 'origin/main')
    project = s.get('project', LEGACY)
    if target != s['base'] and git('diff', '--name-only', s['base'], target, '--', *project_specs(project)):
        raise RuntimeError('This project changed on main. If your PR was merged, click Finish after merge / closure. '
                           'Otherwise keep your files and ask the lead to reconcile this project.')
    if s['phase'] == 'editing':
        changes = diff(s['baseline'], inventory())
        unexpected = sorted(set(changes) - set(s['allowed']))
        if unexpected:
            raise RuntimeError('Unexpected changes. Extend scope or restore them:\n' + '\n'.join(unexpected))
        if not changes:
            raise RuntimeError('No CAD changes to submit.')
        for p in changes:
            safe_path(p)
        manifest = {k: s[k] for k in ('id', 'base', 'reason', 'allowed')}
        manifest['project'] = project
        manifest['changes'] = changes
        path = 'changes/' + s['id'] + '.json'
        (ROOT / 'changes').mkdir(exist_ok=True)
        (ROOT / path).write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
        git('add', '--', path, *project_specs(project))
        # Run the same validator used by CI before making a commit.
        validate_staged(s['base'])
        git('commit', '-m', 'CAD: ' + s['reason'].replace('\n', ' ')[:160])
        s['phase'] = 'committed'
        save(s)
    ensure_clean()
    if target != s['base']:
        sync_review_base(s, target)
    git('push', '-u', 'origin', s['branch'])
    if s.get('pr'):
        print(s['pr'])
        return
    existing = json.loads(run('gh', 'pr', 'list', '--head', s['branch'], '--json', 'url'))
    if existing:
        s['pr'] = existing[0]['url']
    else:
        body = ('Project: `' + project + '`\n\nPurpose: ' + s['reason'] + '\n\nBase snapshot: `' + s['base'] + '`\n\n'
                'Change manifest: `changes/' + s['id'] + '.json`\n\n'
                'Lead: review the full SOLIDWORKS assembly, references, mates, interference, '
                'mass, and target configuration before merging.\n\n'
                'Locks remain held until the session owner finishes after merge or closure.')
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / 'pr.md'
            f.write_text(body, encoding='utf-8')
            s['pr'] = run('gh', 'pr', 'create', '--base', 'main', '--head', s['branch'],
                          '--title', 'CAD: ' + s['reason'].replace('\n', ' ')[:160], '--body-file', str(f))
    s['phase'] = 'submitted'
    save(s)
    print('Submitted for review: ' + s['pr'])


def release_locks(s):
    # Selected files first; the global assembly lock is released LAST.
    while s['locks']:
        lock = s['locks'][-1]
        try:
            git('lfs', 'unlock', '--id', lock['id'])
        except RuntimeError as e:
            save(s)
            raise RuntimeError('Locks remain. Retry the same Finish / Cancel action.\n' + str(e)) from e
        s['locks'].pop()
        save(s)
    state_file().unlink()


def finish():
    s = session()
    if s['phase'] in ('canceling', 'syncing'):
        if s['phase'] == 'syncing':
            raise RuntimeError('Review base update is in progress. Retry Submit or Cancel edit.')
        raise RuntimeError('Cancellation is in progress. Retry Cancel edit.')
    if s['phase'] in ('submitted', 'committed'):
        prs = json.loads(run('gh', 'pr', 'list', '--head', s['branch'], '--state', 'all', '--json', 'state,url'))
        if not prs or any(p['state'] == 'OPEN' for p in prs):
            raise RuntimeError('Merge or close the pull request before releasing locks.')
    ensure_clean()
    release_locks(s)
    print('Locks released. Your edit branch is retained locally.')


def cancel():
    s = session()
    if s['phase'] == 'cleanup':
        finish()
        return 'Failed session cleanup finished.'
    if git('branch', '--show-current') != s['branch']:
        raise RuntimeError('Return to your edit branch before canceling.')
    s['phase'] = 'canceling'
    s.setdefault('recovery', [])
    save(s)
    folder = ROOT / 'exports'
    folder.mkdir(exist_ok=True)
    journal = folder / ('cancel-' + s['id'] + '-recovery.json')
    def record(item=None):
        if item:
            s['recovery'].append(item)
        save(s)
        journal.write_text(json.dumps({'branch': s['branch'], 'base': s['base'],
                                      'head': git('rev-parse', 'HEAD'),
                                      'recovery': s['recovery']}, indent=2), encoding='utf-8')
    # Preserve actual CAD bytes before stashing anything (including untracked work).
    if inventory(project=s.get('project', LEGACY)):
        archive = folder / ('cancel-' + s['id'] + '-' + uuid.uuid4().hex[:8] + '.zip')
        export_zip(archive, editable=True, project=s.get('project', LEGACY))
        record({'zip': str(archive)})
    if git('status', '--porcelain'):
        git('stash', 'push', '--include-untracked', '-m', 'TVR canceled edit ' + s['id'])
        record({'stash': git('rev-parse', 'refs/stash')})
    ensure_clean()
    # Close only PRs for this edit branch. If the server is unavailable, keep locks.
    prs = json.loads(run('gh', 'pr', 'list', '--head', s['branch'], '--state', 'all',
                         '--json', 'number,state,url'))
    for pr in prs:
        if pr['state'] == 'OPEN':
            run('gh', 'pr', 'close', str(pr['number']))
    # Recheck closure: a failed or incomplete close must not open another edit session.
    prs = json.loads(run('gh', 'pr', 'list', '--head', s['branch'], '--state', 'all',
                         '--json', 'number,state,url'))
    if any(pr['state'] == 'OPEN' for pr in prs):
        raise RuntimeError('The edit PR is still open. Retry Cancel edit after closing it.')
    record()
    release_locks(s)
    message = ('Edit canceled; locks released. Your branch and backups are retained.\n'
               'Recovery details: ' + str(journal) + '\n'
               'Start a new edit from current main before using any recovered changes.')
    print(message)
    return message


def export_zip(destination, root=None, editable=False, project=None):
    root = ROOT if root is None else root
    files = inventory(root, project=project)
    if not files:
        raise RuntimeError('This snapshot contains no CAD files.')
    for p in files:
        with (root / p).open('rb') as f:
            if f.read(80).startswith(b'version https://git-lfs.github.com/spec/v1'):
                raise RuntimeError('LFS pointer found instead of CAD bytes: ' + p)
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in files:
            info = zipfile.ZipInfo(p)
            info.create_system = 3
            info.external_attr = ((stat.S_IFREG | (0o644 if editable else 0o444)) << 16)
            info.compress_type = zipfile.ZIP_DEFLATED
            with (root / p).open('rb') as src, z.open(info, 'w', force_zip64=True) as dst:
                shutil.copyfileobj(src, dst)
    print('Exported: ' + str(destination))


def export_ref(ref, destination, project=None):
    git('fetch', 'origin', '--tags')
    sha = git('rev-parse', '--verify', ref + '^{commit}')
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / 'snapshot'
        git('worktree', 'add', '--detach', str(work), sha)
        try:
            git('lfs', 'pull', cwd=work)
            export_zip(destination, work, project=project)
        finally:
            git('worktree', 'remove', '--force', str(work))


def import_zip(source):
    s = session()
    if s['phase'] != 'editing':
        raise RuntimeError('Start a fresh edit session before importing.')
    # Validate every member before changing the workspace. No scripts or links get extracted.
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(source) as z:
        names = set()
        for info in z.infolist():
            if info.is_dir():
                continue
            p = safe_path(info.filename)
            require_project_path(str(p), s.get('project', LEGACY), metadata=True)
            normalized = str(p)
            if normalized != info.filename or normalized.lower() in names:
                raise RuntimeError('Duplicate or non-canonical ZIP path: ' + info.filename)
            names.add(normalized.lower())
            if stat.S_ISLNK(info.external_attr >> 16):
                raise RuntimeError('ZIP symlinks are not allowed.')
            target = Path(tmp) / p
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, target.open('wb') as dst:
                shutil.copyfileobj(src, dst)
        if not names:
            raise RuntimeError('Empty ZIP.')
        staged = inventory(Path(tmp))
        meta = project_root(s.get('project', LEGACY)) + '/' + PROJECT_META
        current = inventory(project=s.get('project', LEGACY))
        if meta in current and staged.get(meta) != current[meta]:
            raise RuntimeError('Keep the project details unchanged in the returned ZIP.')
        proposed = diff(project_files(s['baseline'], s.get('project', LEGACY)), staged)
        # Apply the returned snapshot against actual workspace bytes, including
        # restorations to baseline and files locally added/deleted since export.
        changes = diff(current, staged)
        unexpected = sorted((set(proposed) | set(changes)) - set(s['allowed']))
        if unexpected:
            raise RuntimeError('ZIP changes outside the selected scope:\n' + '\n'.join(unexpected))
        # Keep a complete pre-import copy; never overwrite the only copy of member work.
        backup = ROOT / 'exports' / ('before-import-' + uuid.uuid4().hex[:12] + '.zip')
        backup.parent.mkdir(exist_ok=True)
        export_zip(backup, editable=True, project=s.get('project', LEGACY))
        for p, change in changes.items():
            target = ROOT / p
            if target.exists():
                target.chmod(target.stat().st_mode | stat.S_IWUSR)
            if change == 'deleted':
                target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(Path(tmp) / p, target)
    print('Imported. Rebuild the complete assembly before Submit.')


def seed(source, project=LEGACY, name=None):
    project_root(project)
    if state_file().exists():
        raise RuntimeError('Finish or cancel your current edit before importing a project.')
    if inventory(project=project):
        raise RuntimeError('Initial import is only available for an empty project.')
    if project != LEGACY and (not isinstance(name, str) or not name.strip() or len(name.strip()) > 100):
        raise RuntimeError('Enter a project name (maximum 100 characters).')
    source = Path(source).resolve()
    if source == ROOT or ROOT in source.parents or source in ROOT.parents:
        raise RuntimeError('Choose a separate Pack and Go folder, outside this repository.')
    candidates = {}
    for p in source.rglob('*'):
        if p.is_symlink():
            raise RuntimeError('Pack and Go folder contains a symlink.')
        if p.is_file():
            if p.name.startswith('~$') or p.suffix.lower() in {'.sldbak', '.tmp', '.swp'}:
                continue
            dest = project_root(project) + '/' + p.relative_to(source).as_posix()
            require_project_path(dest, project)
            if dest.casefold() in {key.casefold() for key in candidates}:
                raise RuntimeError('Pack and Go contains duplicate Windows filenames: ' + dest)
            candidates[dest] = p
    if not any(Path(p).suffix.lower() == '.sldasm' for p in candidates):
        raise RuntimeError('Choose a complete Pack and Go folder containing an assembly.')
    start([], 'Import initial assembly: ' + (name.strip() if name else 'TVR Rocket'), initial=True, project=project)
    if project != LEGACY:
        meta = project_root(project) + '/' + PROJECT_META
        allow([meta], metadata=True)
        (ROOT / meta).write_text(json.dumps({'schema': 1, 'id': project, 'name': name.strip()}, indent=2) + '\n', encoding='utf-8')
    allow(list(candidates))
    for name, src in candidates.items():
        target = ROOT / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, target)
    message = ('Initial assembly imported into ' + str(ROOT / project_root(project)) +
               '.\nOpen the top-level assembly from this folder, rebuild, and click Submit for review. '
               'The project becomes available to everyone after the lead merges its PR.')
    print(message)
    return message


def gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, simpledialog, ttk
    app = tk.Tk()
    app.title('TVR CAD Vault')
    app.geometry('900x820')
    controls = tk.Frame(app)
    controls.pack(fill=tk.X, padx=12, pady=10)
    tk.Label(controls, text='Project:').pack(side=tk.LEFT)
    choice = ttk.Combobox(controls, state='readonly', width=48)
    choice.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)
    catalog = {}
    selected_project = [LEGACY]
    folder_text = tk.StringVar()
    tk.Label(app, textvariable=folder_text, wraplength=870, justify=tk.LEFT).pack(fill=tk.X, padx=12)
    banner = tk.StringVar(value='Checking shared edit status...')
    tk.Label(app, textvariable=banner, wraplength=780, justify=tk.LEFT).pack(fill=tk.X, padx=12, pady=8)
    tk.Label(app, text='Select the components you intend to edit. Parent assemblies in this project are included.',
             wraplength=720).pack(pady=12)
    listing = tk.Listbox(app, selectmode=tk.EXTENDED, width=105, height=16)
    listing.pack(fill=tk.BOTH, expand=True, padx=12)
    def refresh():
        catalog.clear()
        catalog.update(projects())
        locked = state_file().exists()
        if locked:
            selected_project[0] = session().get('project', LEGACY)
        if selected_project[0] not in catalog:
            selected_project[0] = LEGACY
        choice['values'] = [name + ' [' + identifier + ']' for identifier, name in catalog.items()]
        choice.current(list(catalog).index(selected_project[0]))
        choice['state'] = 'disabled' if locked else 'readonly'
        folder_text.set('Assembly folder: ' + str(ROOT / project_root(selected_project[0])) +
                        ('\nFinish or cancel this session before switching projects.' if locked else ''))
        listing.delete(0, tk.END)
        for p in inventory(project=selected_project[0]):
            if Path(p).name != PROJECT_META:
                listing.insert(tk.END, p)
        refresh_status()
    def refresh_status():
        try:
            banner.set(status_text(active_edit_status(project=selected_project[0])))
        except (RuntimeError, ValueError, OSError) as e:
            banner.set('Edit status unavailable: ' + str(e) + '. You can still download a snapshot.')
    def poll_status():
        refresh_status()
        app.after(60000, poll_status)
    def action(fn, announce=True):
        try:
            result = fn()
            refresh()
            if announce:
                messagebox.showinfo('TVR CAD', result if isinstance(result, str) else 'Done. See the terminal for details.')
        except Exception as e:
            messagebox.showerror('TVR CAD', str(e))
    def selected():
        return [listing.get(i) for i in listing.curselection()]
    def begin():
        reason = simpledialog.askstring('Purpose', 'What will change? Include the target motor/configuration.')
        if reason:
            start(selected(), reason, project=selected_project[0])
    def download():
        s = session()
        if s['phase'] != 'editing':
            raise RuntimeError('Start a fresh edit before exporting an editable ZIP. Viewing downloads remain available.')
        path = filedialog.asksaveasfilename(defaultextension='.zip')
        if path:
            export_zip(path, editable=True, project=s.get('project', LEGACY))
    def upload():
        path = filedialog.askopenfilename(filetypes=[('CAD workspace', '*.zip')])
        if path:
            import_zip(path)
    def history():
        ref = simpledialog.askstring('Snapshot', 'Tag, commit, or origin/main:', initialvalue='origin/main')
        if ref:
            path = filedialog.asksaveasfilename(defaultextension='.zip')
            if path:
                export_ref(ref, path, project=selected_project[0])
    def initial():
        path = filedialog.askdirectory(title='Choose initial Pack and Go folder')
        if path:
            seed(path, project=selected_project[0], name=catalog[selected_project[0]])
    def add_project():
        if state_file().exists():
            raise RuntimeError('Finish or cancel your current session before adding another project.')
        name = simpledialog.askstring('Add project', 'Project name, for example V2 or Cage testing frames:')
        if not name or not name.strip():
            return
        suggested = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')[:48].rstrip('-')
        identifier = simpledialog.askstring('Project folder',
            'Unique folder ID (lowercase letters, numbers and hyphens):', initialvalue=suggested)
        if identifier is None:
            return
        project_root(identifier)
        if identifier == LEGACY or identifier in catalog:
            raise RuntimeError('That project ID already exists. Choose a new ID.')
        path = filedialog.askdirectory(title='Choose the unzipped Pack and Go folder for ' + name)
        if path:
            return seed(path, project=identifier, name=name)
    def change_project(event=None):
        selected_project[0] = list(catalog)[choice.current()]
        refresh()
    choice.bind('<<ComboboxSelected>>', lambda event: action(lambda: change_project(event), announce=False))
    tk.Button(controls, text='Refresh projects', command=lambda: action(refresh_projects)).pack(side=tk.LEFT)
    tk.Button(controls, text='Add project + import assembly', command=lambda: action(add_project)).pack(side=tk.LEFT, padx=6)
    def abandon():
        if messagebox.askyesno('Cancel edit', 'Close SOLIDWORKS first. Cancel your current edit?\n\n'
                               'The helper saves a CAD ZIP and stashes uncommitted work, closes your edit PR, '
                               'and releases your locks. Your branch and backups remain available.'):
            return cancel()
    buttons = tk.Frame(app)
    buttons.pack(fill=tk.X, padx=12, pady=10)
    buttons.columnconfigure(0, weight=1)
    buttons.columnconfigure(1, weight=1)
    for index, (label, fn) in enumerate([('One-time setup', setup), ('Import initial assembly', initial),
                      ('Refresh file list', refresh), ('Start edit', begin),
                      ('Add selected files to scope', lambda: allow(selected())),
                      ('Export editable ZIP', download), ('Import returned ZIP', upload),
                      ('Submit for review', submit), ('Finish after merge / closure', finish),
                      ('Cancel edit (keep backup)', abandon),
                      ('Download current / historic snapshot', history)]):
        tk.Button(buttons, text=label, command=lambda f=fn: action(f)).grid(row=index // 2, column=index % 2, sticky='ew', padx=3, pady=3)
    refresh()
    app.after(60000, poll_status)
    app.mainloop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('setup', 'submit', 'finish', 'cancel', 'gui', 'status'):
        sub.add_parser(name)
    p = sub.add_parser('start')
    p.add_argument('--reason', required=True)
    p.add_argument('--project', default=LEGACY)
    p.add_argument('paths', nargs='+')
    p = sub.add_parser('allow')
    p.add_argument('paths', nargs='+')
    p = sub.add_parser('export')
    p.add_argument('destination')
    p.add_argument('--ref')
    p.add_argument('--project', default=LEGACY)
    p = sub.add_parser('import')
    p.add_argument('source')
    p = sub.add_parser('seed')
    p.add_argument('source')
    p.add_argument('--project', default=LEGACY)
    p.add_argument('--name')
    a = parser.parse_args()
    if a.command == 'start':
        start(a.paths, a.reason, project=a.project)
    elif a.command == 'allow':
        allow(a.paths)
    elif a.command == 'export':
        export_ref(a.ref, a.destination, project=a.project) if a.ref else export_zip(a.destination, project=a.project)
    elif a.command == 'import':
        import_zip(a.source)
    elif a.command == 'seed':
        seed(a.source, project=a.project, name=a.name)
    elif a.command == 'status':
        show_status()
    else:
        globals()[a.command]()


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError, zipfile.BadZipFile) as error:
        print('TVR CAD: ' + str(error))
        raise SystemExit(1)
