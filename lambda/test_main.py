import os
import json
import unittest
from unittest.mock import patch, MagicMock

# Set env vars before importing main so the module-level SSM fetch is bypassed.
# PAGERDUTY_API_KEY short-circuits the boto3 SSM call in the module body.
os.environ.setdefault('PAGERDUTY_API_KEY', 'test-pd-key')
os.environ.setdefault('PD_API_KEY_NAME', 'test-pd-key-name')
os.environ.setdefault('SLACK_API_KEY_NAME', 'test-slack-key-name')
os.environ.setdefault('CONFIG_TABLE', 'test-table')

# "lambda" is a Python keyword, so we cannot do `import lambda.main`.
# Insert the lambda/ directory onto the path and import main directly.
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


# ---------------------------------------------------------------------------
# End-to-end: do_work() → get_user() → update_slack_topic()
# ---------------------------------------------------------------------------
class TestDoWorkEndToEnd(unittest.TestCase):
    def test_shift_based_schedule_sets_correct_topic(self):
        ddb_item = {
            'schedule': {'S': 'PSHIFT1'},
            'slack': {'S': 'C123456'},
        }

        with patch.object(main, 'get_user_v3', return_value='Alice Example'), \
             patch.object(main, 'get_pd_schedule_name', return_value='Core Infrastructure'), \
             patch.object(main, 'update_slack_topic') as mock_update:
            main.do_work(ddb_item)

        mock_update.assert_called_once_with(
            'C123456',
            'Alice Example is on-call for Core Infrastructure'
        )

    def test_transient_api_error_skips_topic_update(self):
        # When get_user raises (e.g. a transient PagerDuty 5xx), do_work must
        # leave the existing Slack topic unchanged rather than writing a stale
        # or misleading value.
        ddb_item = {
            'schedule': {'S': 'PSHIFT1'},
            'slack': {'S': 'C123456'},
        }

        with patch.object(main, 'get_user_v3', side_effect=RuntimeError("transient v3 API error")), \
             patch.object(main, 'update_slack_topic') as mock_update:
            main.do_work(ddb_item)

        mock_update.assert_not_called()


# ---------------------------------------------------------------------------
# Smoke: confirm module attributes survive the import workaround above
# ---------------------------------------------------------------------------
class TestImport(unittest.TestCase):
    def test_module_imports(self):
        self.assertTrue(hasattr(main, 'get_user'))
        self.assertTrue(hasattr(main, 'get_pd_schedule_name'))


# ---------------------------------------------------------------------------
# get_pd_schedule_name: tries v3, falls back to v2 on 400
# ---------------------------------------------------------------------------
class TestGetPdScheduleName(unittest.TestCase):
    def test_returns_name_from_v3_for_shift_based(self):
        with patch.object(main.http, 'request') as mock_req:
            mock_req.return_value = _mock_response(200, {
                'schedule': {'name': 'Core Infrastructure', 'type': 'schedule_v3'}
            })
            result = main.get_pd_schedule_name('PSHIFT1')
        self.assertEqual(result, 'Core Infrastructure')
        call_url = mock_req.call_args[0][1]
        self.assertIn('/v3/schedules/', call_url)

    def test_falls_back_to_v2_when_v3_returns_400(self):
        def side_effect(method, url, **kwargs):
            if '/v3/' in url:
                return _mock_response(400, {'error': {'code': 3005}})
            return _mock_response(200, {'schedule': {'name': 'Layer Schedule'}})

        with patch.object(main.http, 'request', side_effect=side_effect):
            result = main.get_pd_schedule_name('PLAYER1')
        self.assertEqual(result, 'Layer Schedule')

    def test_returns_none_when_both_fail(self):
        with patch.object(main.http, 'request') as mock_req:
            mock_req.return_value = _mock_response(404, {})
            result = main.get_pd_schedule_name('PBOGUS1')
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# get_user: dispatch logic — v3 wins when it returns a value, v2 on None
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# get_user_v3: shift-based schedule logic, override detection, empty slots
# ---------------------------------------------------------------------------
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

    def test_raises_on_invalid_schedule(self):
        with patch.object(main.http, 'request') as mock_req:
            mock_req.return_value = _mock_response(404, {})
            with self.assertRaises(RuntimeError):
                main.get_user_v3('PBOGUS1')

    def test_raises_on_transient_server_error(self):
        # A 5xx from PagerDuty must raise rather than fall through to parse
        # the error body, which would produce a false "No One on call" result.
        with patch.object(main.http, 'request') as mock_req:
            mock_req.return_value = _mock_response(500, {})
            with self.assertRaises(RuntimeError):
                main.get_user_v3('PSHIFT1')


    def test_returns_n_people_when_multiple_users_on_call(self):
        assignments = [
            {'member': {'type': 'user_member', 'user_id': 'PUSER01'}, 'source': {'type': 'schedule_rotation'}},
            {'member': {'type': 'user_member', 'user_id': 'PUSER02'}, 'source': {'type': 'schedule_rotation'}},
            {'member': {'type': 'user_member', 'user_id': 'PUSER03'}, 'source': {'type': 'schedule_rotation'}},
        ]
        with patch.object(main.http, 'request') as mock_req:
            mock_req.return_value = self._v3_response(assignments)
            result = main.get_user_v3('PSHIFT1')
        self.assertEqual(result, '3 People on call')


# ---------------------------------------------------------------------------
# get_user_name: resolves user_id → display name, falls back to Unknown User on error
# ---------------------------------------------------------------------------
class TestGetUserName(unittest.TestCase):
    def test_returns_name(self):
        with patch.object(main.http, 'request') as mock_req:
            mock_req.return_value = _mock_response(200, {
                'user': {'name': 'Alice Example', 'id': 'PUSER01'}
            })
            result = main.get_user_name('PUSER01')
        self.assertEqual(result, 'Alice Example')

    def test_falls_back_to_unknown_user_on_error(self):
        with patch.object(main.http, 'request') as mock_req:
            mock_req.return_value = _mock_response(404, {'error': {}})
            result = main.get_user_name('PUSER01')
        self.assertEqual(result, 'Unknown User')


# ---------------------------------------------------------------------------
# get_oncall_emails: every on-call person's email, v3 first then v2
# ---------------------------------------------------------------------------
class TestGetOncallEmails(unittest.TestCase):
    def test_returns_all_emails_for_shift_based_schedule(self):
        v3_body = {'schedule': {'final_schedule': {'computed_shift_assignments': [
            {'member': {'type': 'user_member', 'user_id': 'PUSER01'}},
            {'member': {'type': 'user_member', 'user_id': 'PUSER02'}},
            {'member': {'type': 'empty_member'}},
        ]}}}
        emails = {'PUSER01': 'alice@example.com', 'PUSER02': 'bob@example.com'}

        with patch.object(main.http, 'request', return_value=_mock_response(200, v3_body)), \
             patch.object(main, 'get_user_email', side_effect=lambda uid: emails[uid]):
            result = main.get_oncall_emails('PSHIFT1')
        self.assertEqual(result, ['alice@example.com', 'bob@example.com'])

    def test_falls_back_to_v2_for_layer_based_schedule(self):
        def side_effect(method, url, **kwargs):
            if '/v3/' in url:
                return _mock_response(400, {'error': {'code': 3005}})
            return _mock_response(200, {'users': [
                {'name': 'Carol Example', 'email': 'carol@example.com'},
            ]})

        with patch.object(main.http, 'request', side_effect=side_effect):
            result = main.get_oncall_emails('PLAYER1')
        self.assertEqual(result, ['carol@example.com'])

    def test_raises_on_transient_server_error(self):
        with patch.object(main.http, 'request', return_value=_mock_response(500, {})):
            with self.assertRaises(RuntimeError):
                main.get_oncall_emails('PSHIFT1')


# ---------------------------------------------------------------------------
# sync_usergroup: only calls usergroups.users.update when membership changes
# ---------------------------------------------------------------------------
class TestSyncUsergroup(unittest.TestCase):
    def _fake_slack(self, current_members, known_users):
        calls = []

        def fake(method, http_method, fields):
            calls.append((method, fields))
            if method == 'users.lookupByEmail':
                uid = known_users.get(fields['email'])
                return {'ok': True, 'user': {'id': uid}} if uid else {'ok': False, 'error': 'users_not_found'}
            if method == 'usergroups.users.list':
                return {'ok': True, 'users': current_members}
            return {'ok': True}
        return fake, calls

    def test_updates_group_when_members_change(self):
        fake, calls = self._fake_slack(['UOLD'], {'a@example.com': 'UA', 'b@example.com': 'UB'})
        with patch.object(main, 'slack_api', side_effect=fake):
            main.sync_usergroup('S123', ['a@example.com', 'b@example.com'])
        self.assertIn(('usergroups.users.update', {'usergroup': 'S123', 'users': 'UA,UB'}), calls)

    def test_skips_update_when_members_unchanged(self):
        fake, calls = self._fake_slack(['UA', 'UB'], {'a@example.com': 'UA', 'b@example.com': 'UB'})
        with patch.object(main, 'slack_api', side_effect=fake):
            main.sync_usergroup('S123', ['a@example.com', 'b@example.com'])
        self.assertNotIn('usergroups.users.update', [c[0] for c in calls])

    def test_leaves_group_unchanged_when_no_users_resolve(self):
        fake, calls = self._fake_slack(['UOLD'], {})
        with patch.object(main, 'slack_api', side_effect=fake):
            main.sync_usergroup('S123', ['unknown@example.com'])
        self.assertNotIn('usergroups.users.update', [c[0] for c in calls])

    def test_skips_unresolved_emails_but_syncs_the_rest(self):
        fake, calls = self._fake_slack(['UOLD'], {'a@example.com': 'UA'})
        with patch.object(main, 'slack_api', side_effect=fake):
            main.sync_usergroup('S123', ['a@example.com', 'unknown@example.com'])
        self.assertIn(('usergroups.users.update', {'usergroup': 'S123', 'users': 'UA'}), calls)


# ---------------------------------------------------------------------------
# do_work + usergroup: opt-in per item, never blocks the topic update
# ---------------------------------------------------------------------------
class TestDoWorkUsergroup(unittest.TestCase):
    def test_syncs_usergroup_when_item_has_one(self):
        ddb_item = {
            'schedule': {'S': 'PSHIFT1,PSHIFT2'},
            'slack': {'S': 'C123456'},
            'usergroup': {'S': 'S123'},
        }
        with patch.object(main, 'get_user', return_value='Alice Example'), \
             patch.object(main, 'get_pd_schedule_name', return_value='Eng Blog Review'), \
             patch.object(main, 'update_slack_topic'), \
             patch.object(main, 'sync_oncall_usergroup') as mock_sync:
            main.do_work(ddb_item)
        mock_sync.assert_called_once_with('S123', ['PSHIFT1', 'PSHIFT2'])

    def test_does_not_sync_when_item_has_no_usergroup(self):
        ddb_item = {
            'schedule': {'S': 'PSHIFT1'},
            'slack': {'S': 'C123456'},
        }
        with patch.object(main, 'get_user', return_value='Alice Example'), \
             patch.object(main, 'get_pd_schedule_name', return_value='Core Infrastructure'), \
             patch.object(main, 'update_slack_topic'), \
             patch.object(main, 'sync_oncall_usergroup') as mock_sync:
            main.do_work(ddb_item)
        mock_sync.assert_not_called()

    def test_usergroup_failure_does_not_raise(self):
        with patch.object(main, 'get_oncall_emails', side_effect=RuntimeError("boom")), \
             patch.object(main, 'sync_usergroup') as mock_sync:
            main.sync_oncall_usergroup('S123', ['PSHIFT1'])  # must not raise
        mock_sync.assert_not_called()
