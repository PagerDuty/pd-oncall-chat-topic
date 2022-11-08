import pytest
from dotenv import load_dotenv
from pathlib import Path

from functions.update_topics.handler import *


DEV_ENV_PATH = '.env.dev'


@pytest.fixture(autouse=True)
def dev_config():
    load_dotenv(dotenv_path=Path(DEV_ENV_PATH))


def test_init_threading():
    pytest.fail('Not yet implemented!')
    init_threading()


def test_init_logging():
    pytest.fail('Not yet implemented!')
    init_logging()


def test_init_config():
    pytest.fail('Not yet implemented!')
    init_config()
