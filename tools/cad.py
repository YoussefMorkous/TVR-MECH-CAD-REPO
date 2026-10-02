"""Small, dependency-free TVR CAD client. Git, Git LFS and gh are required."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tempfile
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
NATIVE = {'.sldprt', '.sldasm', '.slddrw'}
LOCK = 'cad/.edit-lock'


def run(*args, cwd=None, env=None):
    p = subprocess.run(args, cwd=cwd or ROOT, env=env, capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    if p.returncode:
        raise RuntimeError(p.stderr.strip() or p.stdout.strip() or 'Command failed')
    return p.stdout.strip()


def git(*args, cwd=None):
    return run('git', *args, cwd=cwd)


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


def inventory(root=None):
    root = ROOT if root is None else root
    result = {}
    for p in sorted((root / 'cad').rglob('*')):
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


def start(paths, reason, initial=False):
    ensure_clean()
    if state_file().exists():
        raise RuntimeError('Finish the existing edit session first.')
    git('fetch', 'origin', 'main')
    git('switch', '--detach', 'origin/main')
    git('lfs', 'pull')
    baseline = inventory()
    if not baseline and not initial:
        raise RuntimeError('No CAD files yet. Lead must import the initial Pack and Go first.')
    requested = sorted(set(paths))
    for p in requested:
        safe_path(p)
        if p not in baseline:
            raise RuntimeError('Select an existing file: ' + p)
    if not requested and not initial:
        raise RuntimeError('Select at least one component.')
    # Every parent assembly can require a save after a component change.
    allowed = sorted(set(requested) | {p for p in baseline if Path(p).suffix.lower() == '.sldasm'})
    identifier = uuid.uuid4().hex
    s = dict(id=identifier, base=git('rev-parse', 'HEAD'), branch='cad/edit-' + identifier[:12],
             reason=reason, allowed=allowed, baseline=baseline, locks=[], phase='editing')
    try:
        # The global lock is acquired FIRST. Concurrent full assembly edits are serialized.
        for p in [LOCK] + [p for p in allowed if Path(p).suffix.lower() in NATIVE]:
            lock = lock_result(git('lfs', 'lock', '--json', p))
            s['locks'].append({'path': p, 'id': str(lock['id'])})
            save(s)  # Keep recovery information even if a later command fails.
        git('switch', '-c', s['branch'])
        (ROOT / LOCK).write_text(identifier + '\n', encoding='utf-8')
        for p in allowed:
            fp = ROOT / p
            fp.chmod(fp.stat().st_mode | stat.S_IWUSR)
        save(s)
    except Exception:
        # Do not lose lock IDs when cleanup cannot reach the server.
        failed = []
        for lock in reversed(s['locks']):
            try:
                git('lfs', 'unlock', '--id', lock['id'])
            except RuntimeError:
                failed.append(lock)
        if failed:
            s['locks'] = list(reversed(failed))
            s['phase'] = 'cleanup'
            save(s)
        else:
            state_file().unlink(missing_ok=True)
        raise
    print('Edit session started: ' + s['branch'])


def check_locks(s):
    obj = json.loads(git('lfs', 'locks', '--verify', '--json'))
    ours = {str(x['id']) for x in obj.get('ours', [])}
    if not {x['id'] for x in s['locks']} <= ours:
        raise RuntimeError('A required lock was lost. Contact the lead before submitting.')


def allow(paths):
    s = session()
    if s['phase'] != 'editing':
        raise RuntimeError('This session is already submitted; finish it first.')
    for p in paths:
        safe_path(p)
        if p == LOCK:
            raise RuntimeError('The session lock is managed automatically.')
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


def submit():
    s = session()
    if s['phase'] == 'cleanup':
        raise RuntimeError('Finish the failed session cleanup first.')
    if git('branch', '--show-current') != s['branch']:
        raise RuntimeError('Return to your edit branch before submitting.')
    check_locks(s)
    git('fetch', 'origin', 'main')
    if git('rev-parse', 'origin/main') != s['base']:
        raise RuntimeError('main advanced since checkout. Keep your files and ask the lead to reconcile the snapshot.')
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
        manifest['changes'] = changes
        path = 'changes/' + s['id'] + '.json'
        (ROOT / 'changes').mkdir(exist_ok=True)
        (ROOT / path).write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
        git('add', '--', 'cad', path)
        # Run the same validator used by CI before making a commit.
        run('python' if os.name != 'nt' else 'py', *( ['-3'] if os.name == 'nt' else []),
            str(ROOT / 'tools/validate.py'), '--base', s['base'], '--staged')
        git('commit', '-m', 'CAD: ' + s['reason'].replace('\n', ' ')[:160])
        s['phase'] = 'committed'
        save(s)
    ensure_clean()
    git('push', '-u', 'origin', s['branch'])
    if s.get('pr'):
        print(s['pr'])
        return
    existing = json.loads(run('gh', 'pr', 'list', '--head', s['branch'], '--json', 'url'))
    if existing:
        s['pr'] = existing[0]['url']
    else:
        body = ('Purpose: ' + s['reason'] + '\n\nBase snapshot: `' + s['base'] + '`\n\n'
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


def finish():
    s = session()
    if s['phase'] in ('submitted', 'committed'):
        prs = json.loads(run('gh', 'pr', 'list', '--head', s['branch'], '--state', 'all', '--json', 'state,url'))
        if not prs or any(p['state'] == 'OPEN' for p in prs):
            raise RuntimeError('Merge or close the pull request before releasing locks.')
    ensure_clean()
    remaining = []
    errors = []
    for lock in reversed(s['locks']):
        try:
            git('lfs', 'unlock', '--id', lock['id'])
        except RuntimeError as e:
            remaining.append(lock)
            errors.append(str(e))
    if remaining:
        s['locks'] = list(reversed(remaining))
        save(s)
        raise RuntimeError('Some locks remain. Retry Finish.\n' + '\n'.join(errors))
    state_file().unlink()
    print('Locks released. Your edit branch is retained locally.')


def export_zip(destination, root=None, editable=False):
    root = ROOT if root is None else root
    files = inventory(root)
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


def export_ref(ref, destination):
    git('fetch', 'origin', '--tags')
    sha = git('rev-parse', '--verify', ref + '^{commit}')
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / 'snapshot'
        git('worktree', 'add', '--detach', str(work), sha)
        try:
            git('lfs', 'pull', cwd=work)
            export_zip(destination, work)
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
        changes = diff(s['baseline'], staged)
        unexpected = sorted(set(changes) - set(s['allowed']))
        if unexpected:
            raise RuntimeError('ZIP changes outside the selected scope:\n' + '\n'.join(unexpected))
        # Keep a complete pre-import copy; never overwrite the only copy of member work.
        backup = ROOT / 'exports' / ('before-import-' + uuid.uuid4().hex[:12] + '.zip')
        backup.parent.mkdir(exist_ok=True)
        export_zip(backup, editable=True)
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


def seed(source):
    if inventory():
        raise RuntimeError('Initial import is only available for an empty vault.')
    source = Path(source).resolve()
    if source == ROOT or ROOT in source.parents or source in ROOT.parents:
        raise RuntimeError('Choose a separate Pack and Go folder, outside this repository.')
    candidates = {}
    for p in source.rglob('*'):
        if p.is_symlink():
            raise RuntimeError('Pack and Go folder contains a symlink.')
        if p.is_file():
            name = 'cad/' + p.relative_to(source).as_posix()
            safe_path(name)
            candidates[name] = p
    if not any(Path(p).suffix.lower() == '.sldasm' for p in candidates):
        raise RuntimeError('Choose a complete Pack and Go folder containing an assembly.')
    start([], 'Import initial TVR assembly', initial=True)
    allow(list(candidates))
    for name, src in candidates.items():
        target = ROOT / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, target)
    print('Initial assembly imported. Open it from cad/, rebuild, and Submit for review.')


def gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, simpledialog
    app = tk.Tk()
    app.title('TVR CAD Vault')
    app.geometry('760x760')
    tk.Label(app, text='Select the components you intend to edit. Parent assemblies are included.',
             wraplength=720).pack(pady=12)
    listing = tk.Listbox(app, selectmode=tk.EXTENDED, width=105, height=16)
    listing.pack(fill=tk.BOTH, expand=True, padx=12)
    def refresh():
        listing.delete(0, tk.END)
        for p in inventory():
            listing.insert(tk.END, p)
    def action(fn):
        try:
            fn()
            refresh()
            messagebox.showinfo('TVR CAD', 'Done. See the terminal for details.')
        except Exception as e:
            messagebox.showerror('TVR CAD', str(e))
    def selected():
        return [listing.get(i) for i in listing.curselection()]
    def begin():
        reason = simpledialog.askstring('Purpose', 'What will change? Include the target motor/configuration.')
        if reason:
            start(selected(), reason)
    def download():
        path = filedialog.asksaveasfilename(defaultextension='.zip')
        if path:
            export_zip(path, editable=True)
    def upload():
        path = filedialog.askopenfilename(filetypes=[('CAD workspace', '*.zip')])
        if path:
            import_zip(path)
    def history():
        ref = simpledialog.askstring('Snapshot', 'Tag, commit, or origin/main:', initialvalue='origin/main')
        if ref:
            path = filedialog.asksaveasfilename(defaultextension='.zip')
            if path:
                export_ref(ref, path)
    def initial():
        path = filedialog.askdirectory(title='Choose initial Pack and Go folder')
        if path:
            seed(path)
    for label, fn in [('One-time setup', setup), ('Import initial assembly (lead)', initial),
                      ('Refresh file list', refresh), ('Start edit', begin),
                      ('Add selected files to scope', lambda: allow(selected())),
                      ('Export editable ZIP', download), ('Import returned ZIP', upload),
                      ('Submit for review', submit), ('Finish after merge / closure', finish),
                      ('Download current / historic snapshot', history)]:
        tk.Button(app, text=label, command=lambda f=fn: action(f)).pack(side=tk.TOP, fill=tk.X, padx=12)
    refresh()
    app.mainloop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('setup', 'submit', 'finish', 'gui', 'status'):
        sub.add_parser(name)
    p = sub.add_parser('start')
    p.add_argument('--reason', required=True)
    p.add_argument('paths', nargs='+')
    p = sub.add_parser('allow')
    p.add_argument('paths', nargs='+')
    p = sub.add_parser('export')
    p.add_argument('destination')
    p.add_argument('--ref')
    p = sub.add_parser('import')
    p.add_argument('source')
    p = sub.add_parser('seed')
    p.add_argument('source')
    a = parser.parse_args()
    if a.command == 'start':
        start(a.paths, a.reason)
    elif a.command == 'allow':
        allow(a.paths)
    elif a.command == 'export':
        export_ref(a.ref, a.destination) if a.ref else export_zip(a.destination, editable=True)
    elif a.command == 'import':
        import_zip(a.source)
    elif a.command == 'seed':
        seed(a.source)
    elif a.command == 'status':
        s = session()
        print(json.dumps({'branch': s['branch'], 'phase': s['phase'],
                          'changes': diff(s['baseline'], inventory())}, indent=2))
    else:
        globals()[a.command]()


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError, zipfile.BadZipFile) as error:
        print('TVR CAD: ' + str(error))
        raise SystemExit(1)
