"""All money movements use one database transaction, never floating-point arithmetic."""

import hashlib
import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

MAX_AMOUNT = 1_000_000_000_000


class LedgerError(Exception):
    def __init__(self, code: str, message: str, status: int = 409):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


class Ledger:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    @contextmanager
    def connection(self, *, write: bool = False):
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA synchronous = FULL")
        try:
            # Reserve the single writer BEFORE reading the balance or idempotency key.
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.execute("PRAGMA foreign_keys = ON")
            db.executescript(Path(__file__).with_name("schema.sql").read_text())

    def create_account(self, name: str, currency: str = "GBP") -> dict:
        name = name.strip()
        if not 1 <= len(name) <= 80 or currency not in {"GBP", "USD", "EUR"}:
            raise LedgerError("invalid_account", "Enter a name and supported currency.", 422)
        account = dict(
            id=str(uuid4()), name=name, currency=currency, kind="customer", created_at=now()
        )
        with self.connection(write=True) as db:
            db.execute(
                "INSERT INTO accounts VALUES (:id, :name, :currency, :kind, :created_at)", account
            )
        return {**account, "balance_minor": 0}

    @staticmethod
    def _balance(db, account_id: str) -> int:
        return db.execute(
            "SELECT COALESCE(SUM(p.amount_minor), 0) FROM postings p "
            "JOIN journals j ON j.id = p.journal_id WHERE p.account_id = ? AND j.status = 'posted'",
            (account_id,),
        ).fetchone()[0]

    def accounts(self) -> list[dict]:
        with self.connection() as db:
            return self._accounts(db)

    def _accounts(self, db) -> list[dict]:
        return [
            {**dict(a), "balance_minor": self._balance(db, a["id"])}
            for a in db.execute(
                "SELECT * FROM accounts WHERE kind = 'customer' ORDER BY created_at"
            )
        ]

    @staticmethod
    def _post(
        db,
        source: str,
        destination: str,
        amount: int,
        *,
        key: str,
        digest: str,
        reference: str,
        currency: str,
        kind: str = "transfer",
    ) -> str:
        journal_id = str(uuid4())
        db.execute(
            "INSERT INTO journals "
            "(id,idempotency_key,request_hash,kind,reference,currency,created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (journal_id, key, digest, kind, reference, currency, now()),
        )
        db.executemany(
            "INSERT INTO postings VALUES (?,?,?)",
            [(journal_id, source, -amount), (journal_id, destination, amount)],
        )
        # The database checks balance, cardinality and currency before publishing a journal.
        db.execute("UPDATE journals SET status = 'posted' WHERE id = ?", (journal_id,))
        return journal_id

    @staticmethod
    def _journal(db, journal_id: str) -> dict:
        row = db.execute(
            "SELECT id,kind,reference,currency,status,created_at FROM journals WHERE id = ?",
            (journal_id,),
        ).fetchone()
        postings = [
            dict(p)
            for p in db.execute(
                "SELECT p.account_id,a.name AS account_name,p.amount_minor FROM postings p "
                "JOIN accounts a ON a.id = p.account_id WHERE journal_id = ? ORDER BY amount_minor",
                (journal_id,),
            )
        ]
        return {**dict(row), "postings": postings}

    def transfer(self, source: str, destination: str, amount: int, reference: str, key: str):
        if type(amount) is not int or not 1 <= amount <= MAX_AMOUNT:
            raise LedgerError("invalid_amount", "Amount must be positive integer minor units.", 422)
        if source == destination:
            raise LedgerError("same_account", "Choose two different accounts.", 422)
        if not 1 <= len(key) <= 128 or not 1 <= len(reference.strip()) <= 120:
            raise LedgerError(
                "invalid_request", "A reference and idempotency key are required.", 422
            )
        reference = reference.strip()
        digest = hashlib.sha256(
            json.dumps([source, destination, amount, reference], separators=(",", ":")).encode()
        ).hexdigest()
        with self.connection(write=True) as db:
            existing = db.execute(
                "SELECT id, request_hash FROM journals WHERE idempotency_key = ?", (key,)
            ).fetchone()
            if existing:
                if existing["request_hash"] != digest:
                    raise LedgerError(
                        "idempotency_conflict", "This key belongs to a different request."
                    )
                return self._journal(db, existing["id"]), True
            accounts = [
                db.execute("SELECT * FROM accounts WHERE id = ?", (a,)).fetchone()
                for a in (source, destination)
            ]
            if any(a is None or a["kind"] != "customer" for a in accounts):
                raise LedgerError("account_not_found", "Customer account not found.", 404)
            if accounts[0]["currency"] != accounts[1]["currency"]:
                raise LedgerError("currency_mismatch", "Transfers must use the same currency.", 422)
            if self._balance(db, source) < amount:
                raise LedgerError(
                    "insufficient_funds", "The source account has insufficient funds."
                )
            journal_id = self._post(
                db,
                source,
                destination,
                amount,
                key=key,
                digest=digest,
                reference=reference,
                currency=accounts[0]["currency"],
            )
            return self._journal(db, journal_id), False

    def transfers(self, limit: int = 25, offset: int = 0) -> dict:
        with self.connection() as db:
            total = db.execute(
                "SELECT COUNT(*) FROM journals WHERE kind='transfer' AND status='posted'"
            ).fetchone()[0]
            rows = db.execute(
                "SELECT id FROM journals WHERE kind='transfer' AND status='posted' "
                "ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return {"items": [self._journal(db, r[0]) for r in rows], "total": total}

    def entries(self, account_id: str, limit: int = 25, offset: int = 0) -> dict:
        with self.connection() as db:
            if not db.execute(
                "SELECT id FROM accounts WHERE id=? AND kind='customer'", (account_id,)
            ).fetchone():
                raise LedgerError("account_not_found", "Customer account not found.", 404)
            rows = db.execute(
                "SELECT j.id,j.created_at,j.reference,j.kind,p.amount_minor FROM postings p "
                "JOIN journals j ON j.id=p.journal_id WHERE p.account_id=? AND j.status='posted' "
                "ORDER BY j.created_at DESC,j.id DESC LIMIT ? OFFSET ?",
                (account_id, limit, offset),
            ).fetchall()
            return {
                "items": [dict(r) for r in rows],
                "balance_minor": self._balance(db, account_id),
            }

    def summary(self) -> dict:
        with self.connection() as db:
            currencies = []
            for currency in ("GBP", "USD", "EUR"):
                accounts = [a for a in self._accounts(db) if a["currency"] == currency]
                if not accounts:
                    continue
                volume = db.execute(
                    "SELECT COALESCE(SUM(p.amount_minor),0) FROM postings p "
                    "JOIN journals j ON j.id=p.journal_id WHERE j.kind='transfer' "
                    "AND j.status='posted' AND j.currency=? AND p.amount_minor>0",
                    (currency,),
                ).fetchone()[0]
                currencies.append(
                    {
                        "currency": currency,
                        "balance_minor": sum(a["balance_minor"] for a in accounts),
                        "volume_minor": volume,
                    }
                )
            unbalanced = db.execute(
                "SELECT COUNT(*) FROM (SELECT j.id FROM journals j LEFT JOIN postings p "
                "ON p.journal_id=j.id WHERE j.status='posted' GROUP BY j.id "
                "HAVING COUNT(p.account_id)!=2 OR COALESCE(SUM(p.amount_minor),1)!=0)"
            ).fetchone()[0]
            pending = db.execute("SELECT COUNT(*) FROM journals WHERE status='pending'").fetchone()[
                0
            ]
            count = db.execute(
                "SELECT COUNT(*) FROM journals WHERE status='posted' AND kind='transfer'"
            ).fetchone()[0]
            return {
                "currencies": currencies,
                "transfer_count": count,
                "integrity": {
                    "balanced": unbalanced == 0 and pending == 0,
                    "unbalanced_journals": unbalanced,
                    "pending_journals": pending,
                },
            }

    def seed_demo(self) -> bool:
        """Seed only a pristine database; never overwrite user data. Not a funding API."""
        with self.connection(write=True) as db:
            if db.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]:
                return False
            clearing = "demo-clearing"
            db.execute(
                "INSERT INTO accounts VALUES (?,?,?,?,?)",
                (clearing, "Demo opening equity", "GBP", "clearing", now()),
            )
            demo = [
                ("demo-operating", "Operating account", 12_500_000),
                ("demo-reserve", "Treasury reserve", 7_400_000),
                ("demo-payments", "Payments account", 4_800_000),
            ]
            for account_id, name, amount in demo:
                db.execute(
                    "INSERT INTO accounts VALUES (?,?,?,?,?)",
                    (account_id, name, "GBP", "customer", now()),
                )
                self._post(
                    db,
                    clearing,
                    account_id,
                    amount,
                    key=f"seed-{account_id}",
                    digest="seed",
                    reference="Demo opening balance",
                    currency="GBP",
                    kind="opening",
                )
            for index, (source, destination, amount, reference) in enumerate(
                [
                    ("demo-operating", "demo-payments", 185_000, "Supplier settlement"),
                    ("demo-operating", "demo-reserve", 425_000, "Weekly reserve allocation"),
                    ("demo-payments", "demo-operating", 62_500, "Settlement return"),
                    ("demo-reserve", "demo-payments", 310_000, "Payroll funding"),
                ]
            ):
                self._post(
                    db,
                    source,
                    destination,
                    amount,
                    key=f"seed-transfer-{index}",
                    digest="seed",
                    reference=reference,
                    currency="GBP",
                )
            return True
