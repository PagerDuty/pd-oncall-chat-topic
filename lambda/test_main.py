import os
import json
import unittest
from unittest.mock import patch, MagicMock

# Bypass SSM at import time
os.environ.setdefault('PAGERDUTY_API_KEY', 'test-pd-key')
os.environ.setdefault('PD_API_KEY_NAME', 'test-pd-key-name')
os.environ.setdefault('SLACK_API_KEY_NAME', 'test-slack-key-name')
os.environ.setdefault('CONFIG_TABLE', 'test-table')

import sys
import os as _os
sys.path.insert(0, _os.path.join(_os.path.dirname(__file__)))
import main  # noqa: E402


def _mock_response(status, body):
    """Return a urllib3-shaped mock response."""
    mock = MagicMock()
    mock.status = status
    mock.data = json.dumps(body).encode('utf-8')
    return mock


class TestImport(unittest.TestCase):
    def test_module_imports(self):
        self.assertTrue(hasattr(main, 'get_user'))
        self.assertTrue(hasattr(main, 'get_pd_schedule_name'))


class TestGetUserDispatch(unittest.TestCase):
    def test_uses_v3_path_for_shift_based_schedule(self):
        with patch.object(main, 'get_user_v3', return_value='Alice Example') as mock_v3:
            result = main.get_user('PSHIFT1')
        mock_v3.assert_called_once_with('PSHIFT1')
        self.assertEqual(result, 'Alice Example')

    def test_falls_back_to_v2_when_v3_returns_none(self):
        v2_users_body = {'users': [{'name': 'Bob Example'}]}
        v2_overrides_body = {'overrides': []}

        def side_effect(method, url, **kwargs):
            if '/users' in url:
                return _mock_response(200, v2_users_body)
            return _mock_response(200, v2_overrides_body)

        with patch.object(main, 'get_user_v3', return_value=None), \
             patch.object(main.http, 'request', side_effect=side_effect):
            result = main.get_user('PLAYER1')
        self.assertEqual(result, 'Bob Example')

    def test_v2_path_appends_override(self):
        v2_users_body = {'users': [{'name': 'Carol Example'}]}
        v2_overrides_body = {'overrides': [{'id': 'POVER01'}]}

        def side_effect(method, url, **kwargs):
            if '/users' in url:
                return _mock_response(200, v2_users_body)
            return _mock_response(200, v2_overrides_body)

        with patch.object(main, 'get_user_v3', return_value=None), \
             patch.object(main.http, 'request', side_effect=side_effect):
            result = main.get_user('PLAYER1')
        self.assertEqual(result, 'Carol Example (Override)')


class TestGetUserV3(unittest.TestCase):
    def _v3_response(self, assignments):
        return _mock_response(200, {
            'schedule': {
                'final_schedule': {
                    'computed_shift_assignments': assignments
                }
            }
        })

    def test_returns_username_for_shift_based_schedule(self):
        assignment = {
            'member': {'type': 'user_member', 'user_id': 'PUSER01'},
            'source': {'type': 'schedule_rotation'}
        }
        with patch.object(main.http, 'request') as mock_req, \
             patch.object(main, 'get_user_name', return_value='Alice Example'):
            mock_req.return_value = self._v3_response([assignment])
            result = main.get_user_v3('PSHIFT1')
        self.assertEqual(result, 'Alice Example')

    def test_appends_override_when_source_is_override(self):
        assignment = {
            'member': {'type': 'user_member', 'user_id': 'PUSER02'},
            'source': {'type': 'schedule_rotation_override'}
        }
        with patch.object(main.http, 'request') as mock_req, \
             patch.object(main, 'get_user_name', return_value='Bob Example'):
            mock_req.return_value = self._v3_response([assignment])
            result = main.get_user_v3('PSHIFT1')
        self.assertEqual(result, 'Bob Example (Override)')

    def test_returns_no_one_when_empty_member(self):
        assignment = {
            'member': {'type': 'empty_member'},
            'source': {'type': 'schedule_rotation'}
        }
        with patch.object(main.http, 'request') as mock_req:
            mock_req.return_value = self._v3_response([assignment])
            result = main.get_user_v3('PSHIFT1')
        self.assertEqual(result, 'No One :thisisfine:')

    def test_returns_none_for_non_shift_based_schedule(self):
        with patch.object(main.http, 'request') as mock_req:
            mock_req.return_value = _mock_response(400, {'error': {'code': 3005}})
            result = main.get_user_v3('PLAYER1')
        self.assertIsNone(result)

    def test_returns_false_for_invalid_schedule(self):
        with patch.object(main.http, 'request') as mock_req:
            mock_req.return_value = _mock_response(404, {})
            result = main.get_user_v3('PBOGUS1')
        self.assertFalse(result)


class TestGetUserName(unittest.TestCase):
    def test_returns_name(self):
        with patch.object(main.http, 'request') as mock_req:
            mock_req.return_value = _mock_response(200, {
                'user': {'name': 'Alice Example', 'id': 'PUSER01'}
            })
            result = main.get_user_name('PUSER01')
        self.assertEqual(result, 'Alice Example')

    def test_falls_back_to_id_on_error(self):
        with patch.object(main.http, 'request') as mock_req:
            mock_req.return_value = _mock_response(404, {'error': {}})
            result = main.get_user_name('PUSER01')
        self.assertEqual(result, 'PUSER01')
