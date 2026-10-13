import pytest
from fastapi.testclient import TestClient

from clearledger.app import create_app
from clearledger.ledger import Ledger


@pytest.fixture
def ledger(tmp_path):
    ledger = Ledger(tmp_path / "test.sqlite3")
    ledger.initialize()
    ledger.seed_demo()
    return ledger


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "api.sqlite3", demo=True)) as client:
        yield client
