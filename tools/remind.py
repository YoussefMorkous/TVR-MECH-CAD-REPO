"""Notify the repository lead once per overdue assembly lock; never unlock it."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import re

from cad import active_edit_status, all_edit_status, lock_list, run


def marker(lock_id):
    return '<!-- tvr-edit-lock:' + hashlib.sha256(str(lock_id).encode()).hexdigest() + ' -->'


def remind(repository, hours=24, now=None):
    if not re.fullmatch(r'[A-Za-z0-9-]+/[A-Za-z0-9_.-]+', repository) or hours <= 0:
        raise ValueError('Expected owner/repo and a positive overdue threshold.')
    now = now or datetime.now(timezone.utc)
    locks = lock_list()  # A failed request must not be interpreted as an unlocked vault.
    statuses = all_edit_status(locks, now)
    active_markers = {marker(status['lock_id']) for status in statuses.values()}
    if any(status['age_hours'] is None for status in statuses.values()):
        raise RuntimeError('Active lock has no valid start time; the lead must inspect it.')
    pages = json.loads(run('gh', 'api', 'repos/' + repository + '/issues?state=all&per_page=100',
                           '--paginate', '--slurp'))
    issues = [issue for page in pages for issue in page
              if not issue.get('pull_request') and
              issue.get('user', {}).get('login') == 'github-actions[bot]' and
              re.search(r'<!-- tvr-edit-lock:[a-f0-9]{64} -->', issue.get('body') or '')]
    # Resolve previous bot reminders once their specific lock is gone.
    for issue in issues:
        if issue['state'] == 'open' and not any(value in (issue.get('body') or '') for value in active_markers):
            run('gh', 'issue', 'close', str(issue['number']), '--repo', repository,
                '--reason', 'completed')
    if not statuses:
        return 'No active assembly edit. Previous reminders resolved.'
    results = []
    for project, status in statuses.items():
        active_marker = marker(status['lock_id'])
        if status['age_hours'] < hours:
            results.append(project + ': active session is below the overdue threshold.')
            continue
        if any(active_marker in (issue.get('body') or '') for issue in issues):
            results.append(project + ': this edit session already has a reminder; no duplicate notification.')
            continue
        # Recheck this project immediately before posting. Other projects remain independent.
        latest = active_edit_status(lock_list(), now, project=project)
        if not latest['active'] or latest['lock_id'] != status['lock_id']:
            results.append(project + ': the session finished while checking; no reminder sent.')
            continue
        lead = repository.split('/')[0]
        owner = json.dumps(status['owner']).replace('@', '\\@').replace('`', '\\`')
        body = (active_marker + '\n\nProject: `' + project + '`\n\n@' + lead + ', this assembly edit has been held for '
                + f"{status['age_hours']:.1f} hours.\n\n"
                + 'Editor reported by Git LFS: ' + owner + '\n\n'
                + 'Started: ' + str(status['locked_at']) + '\n\n'
                + 'Please check with the editor. They can submit and finish the session, or close '
                + 'SOLIDWORKS and click **Cancel edit (keep backup)**. If the editor is unavailable, '
                + 'confirm their work is preserved before the lead clears abandoned locks.\n\n'
                + 'Viewing and downloading the approved assembly remain available. '
                + 'This reminder does not expire or release any lock. The daily check closes '
                + 'this issue once this specific assembly lock is gone. Closing the issue yourself '
                + 'acknowledges it; the same session will not generate another issue.')
        output = run('gh', 'api', '--method', 'POST', 'repos/' + repository + '/issues',
                     '-f', 'title=Overdue CAD edit: ' + project + ' (' + status['lock_id'] + ')', '-f', 'body=' + body)
        results.append('Overdue edit reminder created: ' + json.loads(output)['html_url'])
    return '\n'.join(results)



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', default=os.environ.get('GITHUB_REPOSITORY'), required=not os.environ.get('GITHUB_REPOSITORY'))
    parser.add_argument('--hours', type=float, default=24)
    args = parser.parse_args()
    result = remind(args.repo, args.hours)
    print(result)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as summary:
            summary.write(result + '\n')
