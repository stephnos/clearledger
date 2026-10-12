# ClearLedger

A local banking transaction ledger built as a software engineering interview project.
Independent portfolio work; not affiliated with JPMorgan Chase. All funds are simulated.

## Run

Requires Python 3.11 or newer. On this Mac, use `python3.13`.

```sh
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.lock
pip install --no-deps -e .
clearledger
```

Open http://127.0.0.1:8000 for the dashboard and `/docs` for the API explorer.
The first launch seeds three GBP accounts and four sample transfers. Subsequent launches
preserve the database in `data/ledger.sqlite3`. Set `CLEARLEDGER_DB` to choose another
database, or `CLEARLEDGER_DEMO=0` to start without sample data.

Alternatively, `docker compose up --build` starts the app with persistent storage.
The container configuration is included; local verification used the Python environment.

## Features

- Double-entry journals with two signed postings that sum to zero.
- Atomic balance checks and transfers using SQLite `BEGIN IMMEDIATE` transactions.
- Integer minor units for money, with strict API validation and no cross-currency transfers.
- Idempotency keys: an identical retry returns the original journal; a changed payload returns 409.
- Database triggers prevent changes to posted journals and postings.
- Account statements, paginated transfer history, currency-specific totals, and integrity checks.
- Responsive dashboard with transfer confirmation and an idempotency replay demonstration.
- CI configuration for Python 3.11/3.13 and a container smoke test.

## Verify

```sh
make check
```

41 backend tests cover concurrent spending, concurrent retries, rollback after a failed
posting, insufficient funds, persistence, immutability, validation, and HTTP contracts.

## API example

```sh
curl -X POST http://127.0.0.1:8000/api/transfers \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: interview-demo-001' \
  -d '{"source_account_id":"demo-operating","destination_account_id":"demo-payments","amount_minor":1250,"reference":"Demo settlement"}'
```

Repeat the exact request to observe a replay: HTTP 200 and `Idempotent-Replayed: true`.
A new transfer returns HTTP 201. Failed transfers do not reserve an idempotency key.

## Design trade-offs to discuss

The ledger is the source of truth: balances are calculated from posted entries rather
than maintained separately. An opening-equity account balances the seeded customer funds.
Positive and negative postings represent increases and decreases in customer balances;
this is a focused internal-transfer model, not a complete bank general ledger.

SQLite serializes writes before the balance check, preventing concurrent overspending.
WAL allows readers alongside a writer. This is suitable for a small local demo; a larger
service would need PostgreSQL, deliberate locking, indexed balance projections,
transactional outbox events, and operational reconciliation. Idempotency prevents duplicate
ledger effects for a key; it does not guarantee exactly-once network delivery.

This demo has no authentication, authorization, real payment integration, fraud screening,
or regulatory controls. Keep it on localhost. Account creation starts at zero; opening
funding is only available through the initial seed. Database triggers protect normal writes,
not against an administrator who can alter the schema. Pagination uses offsets and may
shift when new transfers arrive. The UI statement shows the latest 100 entries; the API
supports pagination. Browser retry state persists per tab when session storage is available.
