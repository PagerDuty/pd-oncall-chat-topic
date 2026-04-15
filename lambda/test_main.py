import os
import sys
import json
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

# Set required env vars before importing main (read at module level)
os.environ.setdefault('PD_API_KEY_NAME', 'fake-pd-key')

# Stub boto3 and urllib3 before importing main to prevent module-level side effects
_boto3_stub = MagicMock()
_boto3_stub.client.return_value.get_parameters.return_value = {
    'Parameters': [{'Value': 'fake-api-key'}]
}
sys.modules.setdefault('boto3', _boto3_stub)
sys.modules.setdefault('urllib3', MagicMock())

import main  # noqa: E402


def _resp(data, status=200):
    m = MagicMock()
    m.data = json.dumps(data).encode()
    m.status = status
    return m


NOW = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


class TestGetUser(unittest.TestCase):

    SCHEDULE_ID = 'PABC123'

    def test_returns_no_one_when_schedule_is_empty(self):
        with patch('main.http') as mock_http, patch('main.datetime') as mock_dt:
            mock_dt.now.return_value = NOW
            mock_http.request.return_value = _resp({'users': []})
            self.assertEqual(main.get_user(self.SCHEDULE_ID), 'No One :thisisfine:')

    def test_returns_false_when_schedule_not_found(self):
        with patch('main.http') as mock_http, patch('main.datetime') as mock_dt:
            mock_dt.now.return_value = NOW
            mock_http.request.return_value = _resp({}, status=404)
            self.assertFalse(main.get_user(self.SCHEDULE_ID))

    def test_returns_deactivated_label_for_user_without_name(self):
        with patch('main.http') as mock_http, patch('main.datetime') as mock_dt:
            mock_dt.now.return_value = NOW
            mock_http.request.return_value = _resp({'users': [{'summary': 'Summary but no name'}]})
            result = main.get_user(self.SCHEDULE_ID)
        self.assertIn('Deactivated User :scream:', result)
        self.assertIn('Summary but no name', result)

    class OverrideLabel(unittest.TestCase):

        SCHEDULE_ID = 'PABC123'

        def _call(self, users, overrides, now=NOW):
            with patch('main.http') as mock_http, patch('main.datetime') as mock_dt:
                mock_dt.now.return_value = now
                mock_http.request.side_effect = [
                    _resp({'users': users}),
                    _resp({'overrides': overrides}),
                ]
                return main.get_user(self.SCHEDULE_ID)

        def test_no_label_when_no_overrides(self):
            self.assertEqual(self._call([{'name': 'Alice'}], []), 'Alice')

        def test_appends_label_when_override_is_active(self):
            override = {'start': '2024-06-01T11:00:00+00:00', 'end': '2024-06-01T13:00:00+00:00'}
            self.assertEqual(self._call([{'name': 'Bob'}], [override]), 'Bob (Override)')

        def test_no_label_when_override_just_ended(self):
            # end is exclusive: end == now means the override just finished
            override = {'start': '2024-06-01T11:00:00+00:00', 'end': '2024-06-01T12:00:00+00:00'}
            self.assertEqual(self._call([{'name': 'Carol'}], [override]), 'Carol')

        def test_no_label_when_override_starts_in_future(self):
            override = {'start': '2024-06-01T12:00:30+00:00', 'end': '2024-06-01T14:00:00+00:00'}
            self.assertEqual(self._call([{'name': 'Dave'}], [override]), 'Dave')

        def test_appends_label_when_one_of_many_overrides_is_active(self):
            overrides = [
                {'start': '2024-06-01T09:00:00+00:00', 'end': '2024-06-01T10:00:00+00:00'},  # ended
                {'start': '2024-06-01T11:30:00+00:00', 'end': '2024-06-01T13:00:00+00:00'},  # active
                {'start': '2024-06-01T13:00:00+00:00', 'end': '2024-06-01T14:00:00+00:00'},  # future
            ]
            self.assertEqual(self._call([{'name': 'Eve'}], overrides), 'Eve (Override)')

        def test_no_label_when_all_overrides_expired(self):
            overrides = [
                {'start': '2024-06-01T09:00:00+00:00', 'end': '2024-06-01T10:00:00+00:00'},
                {'start': '2024-06-01T10:00:00+00:00', 'end': '2024-06-01T11:00:00+00:00'},
            ]
            self.assertEqual(self._call([{'name': 'Frank'}], overrides), 'Frank')


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    suite.addTests(tests)
    suite.addTests(loader.loadTestsFromTestCase(TestGetUser.OverrideLabel))
    return suite


if __name__ == '__main__':
    unittest.main()
