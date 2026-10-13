import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from clearledger.ledger import Ledger, LedgerError

SOURCE = "demo-operating"
DESTINATION = "demo-payments"


def balances(ledger):
    return {a["id"]: a["balance_minor"] for a in ledger.accounts()}


def test_transfer_posts_exactly_two_entries_and_conserves_money(ledger):
    before = balances(ledger)
    journal, replay = ledger.transfer(SOURCE, DESTINATION, 12345, "Invoice 42", "one")
    after = balances(ledger)
    assert replay is False
    assert after[SOURCE] == before[SOURCE] - 12345
    assert after[DESTINATION] == before[DESTINATION] + 12345
    assert sum(after.values()) == sum(before.values())
    assert [p["amount_minor"] for p in journal["postings"]] == [-12345, 12345]
    assert ledger.summary()["integrity"]["balanced"] is True


