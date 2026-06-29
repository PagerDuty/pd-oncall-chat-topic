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
