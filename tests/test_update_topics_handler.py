import pytest
from dotenv import load_dotenv
from pathlib import Path
import os

from functions.update_topics import handler
from functions.update_topics.handler import EnvironmentVariableNotReadyError


DEV_ENV_PATH = '.env.dev'


@pytest.fixture(autouse=True)
def dev_config(mocker):
    load_dotenv(dotenv_path=Path(DEV_ENV_PATH))

    # NOTE: We're mocking this function since it initates an internet connection
    #       under normal circumstances. 
    PD_API_KEY = os.environ['PD_API_KEY']
    mocker.patch('functions.update_topics.handler.load_pd_api_key', return_value=PD_API_KEY)

    handler.init_config()


def test_get_pdapi_schedules_route():
    route = handler.get_pdapi_schedules_route()
    assert 'https://api.pagerduty.com/schedules' == route


def test_get_pdapi_schedules_route_environment_not_ready_PD_API_FQDN():
    handler.PD_API_FQDN = None
    with pytest.raises(EnvironmentVariableNotReadyError, match="^Variable 'PD_API_FQDN'.*"):
        route = handler.get_pdapi_schedules_route()


def test_get_pdapi_schedules_route_environment_not_ready_PD_API_ROUTE_SCHEDULES():
    handler.PD_API_ROUTE_SCHEDULES = None
    with pytest.raises(EnvironmentVariableNotReadyError, match="^Variable 'PD_API_ROUTE_SCHEDULES'.*"):
        route = handler.get_pdapi_schedules_route()


def test_get_pdapi_schedule_users_route():
    schedule_id = 'ABC0123'
    route = handler.get_pdapi_schedule_users_route(schedule_id)
    assert 'https://api.pagerduty.com/schedules/ABC0123/users' == route


def test_get_pdapi_schedule_users_route_environment_not_ready_PD_API_FQDN():
    handler.PD_API_FQDN = None
    with pytest.raises(EnvironmentVariableNotReadyError, match="^Variable 'PD_API_FQDN'.*"):
        route = handler.get_pdapi_schedule_users_route('schedule_id')


def test_get_pdapi_schedule_users_route_environment_not_ready_PD_API_ROUTE_SCHEDULE_USERS():
    handler.PD_API_ROUTE_SCHEDULE_USERS = None
    with pytest.raises(EnvironmentVariableNotReadyError, match="^Variable 'PD_API_ROUTE_SCHEDULE_USERS'.*"):
        route = handler.get_pdapi_schedule_users_route('schedule_id')


def test_get_pdapi_schedule_overrides_route():
    schedule_id = 'ABC0123'
    route = handler.get_pdapi_schedule_overrides_route(schedule_id)
    assert 'https://api.pagerduty.com/schedules/ABC0123/overrides' == route


def test_get_pdapi_schedule_overrides_route_environment_not_ready_PD_API_FQDN():
    handler.PD_API_FQDN = None
    with pytest.raises(EnvironmentVariableNotReadyError, match="^Variable 'PD_API_FQDN'.*"):
        route = handler.get_pdapi_schedule_overrides_route('schedule_id')


def test_get_pdapi_schedule_overrides_route_environment_not_ready_PD_API_ROUTE_SCHEDULE_OVERRIDES():
    handler.PD_API_ROUTE_SCHEDULE_OVERRIDES = None
    with pytest.raises(EnvironmentVariableNotReadyError, match="^Variable 'PD_API_ROUTE_SCHEDULE_OVERRIDES'.*"):
        route = handler.get_pdapi_schedule_overrides_route('schedule_id')


def test_get_pdapi_headers():
    headers = handler.get_pdapi_headers()
    assert 'Accept' in headers.keys()
    assert 'application/vnd.pagerduty+json;version=2' == headers['Accept']
    assert 'Authorization' in headers.keys()
    assert 'Token token=myfakekey' == headers['Authorization']


def test_get_pdapi_headers_environment_not_ready_PD_API_KEY():
    handler.PD_API_KEY = None
    with pytest.raises(EnvironmentVariableNotReadyError, match="^Variable 'PD_API_KEY'.*"):
        headers = handler.get_pdapi_headers()


def test_init_threading():
    handler.init_threading()
    assert 5 == handler.MAX_THREADS


def test_init_logging():
    handler.init_logging()
    assert handler.LOGGER is not None

def test_init_config():
    handler.init_config()
    assert handler.MAX_THREADS is not None
    assert handler.PD_API_FQDN is not None
    assert handler.PD_API_ROUTE_SCHEDULES is not None
    assert handler.PD_API_ROUTE_SCHEDULE_USERS is not None
    assert handler.PD_API_ROUTE_SCHEDULE_OVERRIDES is not None
