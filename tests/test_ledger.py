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


def test_missing_self_and_cross_currency_transfers_rejected(ledger):
    euro = ledger.create_account("Euro account", "EUR")
    for source, destination, code in [
        (SOURCE, SOURCE, "same_account"),
        (SOURCE, "missing", "account_not_found"),
        (SOURCE, euro["id"], "currency_mismatch"),
        ("demo-clearing", SOURCE, "account_not_found"),
    ]:
        with pytest.raises(LedgerError) as error:
            ledger.transfer(source, destination, 1, "Invalid", "bad")
        assert error.value.code == code


def test_overdraft_does_not_reserve_idempotency_key(ledger):
    amount = balances(ledger)[SOURCE] + 1
    with pytest.raises(LedgerError, match="insufficient"):
        ledger.transfer(SOURCE, DESTINATION, amount, "Invoice", "retry-after-funding")
    ledger.transfer(DESTINATION, SOURCE, 1000, "Funding", "funding")
    _, replayed = ledger.transfer(SOURCE, DESTINATION, amount, "Invoice", "retry-after-funding")
    assert replayed is False


def test_failure_after_first_posting_rolls_back_everything(ledger):
    before = balances(ledger)
    count = ledger.transfers()["total"]
    with ledger.connection(write=True) as db:
        db.execute(
            "CREATE TRIGGER simulate_disk_failure BEFORE INSERT ON postings "
            "WHEN NEW.amount_minor > 0 BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="injected failure"):
        ledger.transfer(SOURCE, DESTINATION, 100, "Rollback", "rollback-key")
    assert balances(ledger) == before
    assert ledger.transfers()["total"] == count
    with ledger.connection(write=True) as db:
        assert not db.execute(
            "SELECT 1 FROM journals WHERE idempotency_key='rollback-key'"
        ).fetchone()
        db.execute("DROP TRIGGER simulate_disk_failure")
    ledger.transfer(SOURCE, DESTINATION, 100, "Rollback", "rollback-key")


def test_competing_transfers_cannot_spend_the_same_balance(ledger):
    before = balances(ledger)
    amount = before[SOURCE] - 1
    barrier = Barrier(2)

    def attempt(key):
        barrier.wait()
        try:
            ledger.transfer(SOURCE, DESTINATION, amount, "Concurrent", key)
            return "posted"
        except LedgerError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, ["competing-1", "competing-2"]))
    assert sorted(results) == ["insufficient_funds", "posted"]
    assert balances(ledger)[SOURCE] == 1
    assert sum(balances(ledger).values()) == sum(before.values())


def test_concurrent_identical_requests_post_once(ledger):
    before = balances(ledger)
    barrier = Barrier(6)

    def attempt(_):
        barrier.wait()
        return ledger.transfer(SOURCE, DESTINATION, 100, "Same request", "concurrent-key")

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(attempt, range(6)))
    assert len({result[0]["id"] for result in results}) == 1
    assert sum(not replayed for _, replayed in results) == 1
    assert balances(ledger)[SOURCE] == before[SOURCE] - 100


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE postings SET amount_minor=42 WHERE journal_id=?",
        "DELETE FROM postings WHERE journal_id=?",
        "UPDATE journals SET reference='edited' WHERE id=?",
        "DELETE FROM journals WHERE id=?",
        "INSERT INTO postings VALUES (?, 'demo-reserve', 1)",
    ],
)
def test_posted_journal_is_immutable(ledger, sql):
    journal, _ = ledger.transfer(SOURCE, DESTINATION, 100, "Immutable", "immutable")
    with pytest.raises(sqlite3.IntegrityError), ledger.connection(write=True) as db:
        db.execute(sql, (journal["id"],))


def test_database_rejects_unbalanced_journal(ledger):
    with (
        pytest.raises(sqlite3.IntegrityError, match="balanced"),
        ledger.connection(write=True) as db,
    ):
        db.execute(
            "INSERT INTO journals VALUES ('bad','bad','bad','transfer','bad','GBP',"
            "'pending','2026-01-01T00:00:00Z')"
        )
        db.executemany(
            "INSERT INTO postings VALUES ('bad',?,?)", [(SOURCE, -100), (DESTINATION, 99)]
        )
        db.execute("UPDATE journals SET status='posted' WHERE id='bad'")
    assert ledger.summary()["integrity"]["balanced"]


def test_restart_persists_records_and_seed_is_idempotent(ledger):
    journal, _ = ledger.transfer(SOURCE, DESTINATION, 100, "Persist", "persist-key")
    restarted = Ledger(ledger.path)
    restarted.initialize()
    assert restarted.seed_demo() is False
    replay, replayed = restarted.transfer(SOURCE, DESTINATION, 100, "Persist", "persist-key")
    assert replayed is True and replay == journal


def test_summary_keeps_currencies_separate(ledger):
    ledger.create_account("USD reserve", "USD")
    rows = {r["currency"]: r for r in ledger.summary()["currencies"]}
    assert rows["GBP"]["balance_minor"] == 24_700_000
    assert rows["USD"]["balance_minor"] == 0


def test_history_pages_do_not_overlap(ledger):
    first, second = ledger.transfers(2, 0), ledger.transfers(2, 2)
    assert first["total"] == second["total"] == 4
    assert len({j["id"] for j in first["items"] + second["items"]}) == 4
