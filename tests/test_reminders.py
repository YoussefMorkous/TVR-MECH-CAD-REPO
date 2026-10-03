from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
spec = importlib.util.spec_from_file_location('remind', TOOLS / 'remind.py')
reminder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reminder)
sys.path.pop(0)


class ReminderTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 3, 16, tzinfo=timezone.utc)
        self.lock = {'id': '123', 'path': 'cad/.edit-lock', 'owner': {'name': 'Engineer'},
                     'locked_at': '2026-10-02T15:00:00Z'}
        self.calls = []
        self.issues = []

    def cli(self, *args):
        self.calls.append(args)
        if '--method' in args:
            return json.dumps({'html_url': 'https://github.com/example/repo/issues/1'})
        if args[:2] == ('gh', 'api'):
            return json.dumps([self.issues])
        return ''

    def bot_issue(self, lock_id, state='open'):
        return {'number': 8, 'state': state, 'body': reminder.marker(lock_id),
                'user': {'login': 'github-actions[bot]'}}

    def execute(self, locks=None):
        with patch.object(reminder, 'lock_list', return_value=[self.lock] if locks is None else locks), patch.object(reminder, 'run', self.cli):
            return reminder.remind('YoussefMorkous/TVR-MECH-CAD-REPO', now=self.now)

    def test_overdue_notification_goes_to_lead_once_and_never_unlocks(self):
        self.assertIn('created', self.execute())
        post = next(call for call in self.calls if '--method' in call)
        body = next(arg for arg in post if arg.startswith('body='))
        self.assertIn('@YoussefMorkous', body)
        self.assertIn('Engineer', body)
        self.assertFalse(any('unlock' in call for call in self.calls))
        self.issues = [self.bot_issue('123')]
        self.calls = []
        self.assertIn('no duplicate', self.execute())
        self.assertFalse(any('--method' in call for call in self.calls))

    def test_closed_issue_acknowledges_session_without_spam(self):
        self.issues = [self.bot_issue('123', state='closed')]
        self.execute()
        self.assertFalse(any('--method' in call for call in self.calls))

    def test_recent_lock_does_not_generate_reminder(self):
        self.lock['locked_at'] = '2026-10-03T15:00:00Z'
        self.assertIn('below', self.execute())
        self.assertFalse(any('--method' in call for call in self.calls))

    def test_finished_session_resolves_only_bot_reminders(self):
        fake = self.bot_issue('human')
        fake['user']['login'] = 'human'
        self.issues = [self.bot_issue('old'), fake]
        self.assertIn('resolved', self.execute(locks=[]))
        closes = [call for call in self.calls if call[:3] == ('gh', 'issue', 'close')]
        self.assertEqual(len(closes), 1)

    def test_network_failure_neither_sends_nor_closes_reminders(self):
        with patch.object(reminder, 'lock_list', side_effect=RuntimeError('Offline')), patch.object(reminder, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'Offline'):
                reminder.remind('YoussefMorkous/TVR-MECH-CAD-REPO', now=self.now)
        run.assert_not_called()

    def test_session_release_during_check_does_not_send_stale_reminder(self):
        with patch.object(reminder, 'lock_list', side_effect=[[self.lock], []]), patch.object(reminder, 'run', self.cli):
            self.assertIn('no reminder', reminder.remind('YoussefMorkous/TVR-MECH-CAD-REPO', now=self.now))
        self.assertFalse(any('--method' in call for call in self.calls))

    def test_invalid_timestamp_is_reported_for_investigation(self):
        self.lock['locked_at'] = 'unknown'
        with self.assertRaisesRegex(RuntimeError, 'valid start time'):
            self.execute()
        self.assertFalse(any('--method' in call for call in self.calls))


if __name__ == '__main__':
    unittest.main()
