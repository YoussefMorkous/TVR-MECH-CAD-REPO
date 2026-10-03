"""Validate CAD change manifests without executing code from a pull request."""
import argparse
import json
from pathlib import PurePosixPath
import re
import subprocess

LFS = re.compile(rb'version https://git-lfs.github.com/spec/v1\noid sha256:[0-9a-f]{64}\nsize [0-9]+\n\Z')
NATIVE = {'.sldprt', '.sldasm', '.slddrw'}


def git(*args):
    return subprocess.check_output(['git', *args])


def validate(base, head='HEAD', staged=False):
    if not re.fullmatch(r'[0-9a-f]{40}', base):
        raise ValueError('Base must be a complete commit SHA.')
    if not staged and not re.fullmatch(r'[0-9a-f]{40}|HEAD', head):
        raise ValueError('Head must be a complete commit SHA or HEAD.')
    fields = git('diff', '--name-status', '--no-renames', '-z',
                 *(['--cached', base] if staged else [base, head])).decode().split('\0')
    fields = fields[:-1] if fields[-1] == '' else fields
    changes = dict(zip(fields[1::2], fields[::2]))
    manifests = [p for p in changes if re.fullmatch(r'changes/[0-9a-f]{32}\.json', p)]
    if not any(p.startswith('changes/') or p.startswith('cad/') for p in changes):
        print('No CAD changes. Review this pull request as a tooling change.')
        return 'No CAD changes.'
    if len(manifests) != 1 or changes[manifests[0]] != 'A':
        raise ValueError('Each CAD PR needs exactly one new change manifest.')
    def blob(path):
        return git('show', (':' if staged else head + ':') + path)
    payload = blob(manifests[0])
    if len(payload) > 2 * 1024 * 1024:
        raise ValueError('Manifest too large.')
    m = json.loads(payload)
    project = m.get('project', 'legacy')
    if not isinstance(project, str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', project) or len(project) > 48:
        raise ValueError('Invalid project ID.')
    prefix = 'cad/' if project == 'legacy' else 'cad/projects/' + project + '/'
    lock = prefix + '.edit-lock'
    cad = {p: s for p, s in changes.items() if p.startswith('cad/') and p != lock}
    extras = set(changes) - set(cad) - set(manifests) - {lock}
    if extras:
        raise ValueError('Keep tooling changes in a separate PR: ' + ', '.join(sorted(extras)))
    if not cad:
        raise ValueError('The change contains no CAD modifications.')
    if changes.get(lock) not in ({'M'} if project == 'legacy' else {'A', 'M'}):
        raise ValueError('The project session marker must change with the snapshot.')
    if m['id'] != PurePosixPath(manifests[0]).stem or m['base'] != base:
        raise ValueError('Stale snapshot: manifest base must equal the current target commit.')
    if not isinstance(m.get('reason'), str) or not m['reason'].strip():
        raise ValueError('A change reason is required.')
    allowed = m.get('allowed')
    if not isinstance(allowed, list) or not all(isinstance(p, str) for p in allowed):
        raise ValueError('Scope must be a list of paths.')
    for p in set(allowed) | set(cad):
        parts = PurePosixPath(p).parts
        if ('\\' in p or ':' in p or not p.startswith('cad/') or '..' in parts or
                any(x.startswith('.') for x in parts[1:]) or str(PurePosixPath(p)) != p):
            raise ValueError('Unsafe CAD path: ' + p)
        if not p.startswith(prefix) or (project == 'legacy' and p.startswith('cad/projects/')):
            raise ValueError('Changes outside selected project: ' + p)
    if project != 'legacy':
        meta = prefix + '_project.json'
        if changes.get(meta) in {'M', 'D'}:
            raise ValueError('Existing project details cannot be changed in a CAD edit.')
        raw = blob(meta)
        if len(raw) > 4096:
            raise ValueError('Project details too large.')
        details = json.loads(raw)
        name = details.get('name')
        if details.get('schema') != 1 or details.get('id') != project or not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise ValueError('Invalid project details.')
        if changes.get(lock) == 'A' and (changes.get(meta) != 'A' or not any(
                s == 'A' and PurePosixPath(p).suffix.lower() == '.sldasm' for p, s in cad.items())):
            raise ValueError('New projects require details and an initial assembly.')
    unexpected = set(cad) - set(allowed)
    if unexpected:
        raise ValueError('Changes outside requested scope: ' + ', '.join(sorted(unexpected)))
    expected = {p: {'A': 'added', 'D': 'deleted', 'M': 'modified'}[s] for p, s in cad.items()}
    if m['changes'] != expected:
        raise ValueError('The manifest does not match the actual changed files.')
    for p, status in cad.items():
        if status != 'D' and PurePosixPath(p).suffix.lower() in NATIVE:
            # Check size before reading so an accidentally committed huge binary is cheap to reject.
            spec = (':' if staged else head + ':') + p
            if int(git('cat-file', '-s', spec)) > 1024 or not LFS.fullmatch(blob(p)):
                raise ValueError('Native CAD must be stored using Git LFS: ' + p)
    report = 'CAD snapshot checks passed.\n\n' + '\n'.join(f'- {expected[p]}: `{p}`' for p in sorted(expected))
    print(report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', required=True)
    parser.add_argument('--head', default='HEAD')
    parser.add_argument('--staged', action='store_true')
    a = parser.parse_args()
    validate(a.base, a.head, a.staged)
