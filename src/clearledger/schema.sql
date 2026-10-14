CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 80),
    currency TEXT NOT NULL CHECK(currency IN ('GBP', 'USD', 'EUR')),
    kind TEXT NOT NULL CHECK(kind IN ('customer', 'clearing')),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS journals (
    id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_hash TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('transfer', 'opening')),
    reference TEXT NOT NULL,
    currency TEXT NOT NULL CHECK(currency IN ('GBP', 'USD', 'EUR')),
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'posted')),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS postings (
    journal_id TEXT NOT NULL REFERENCES journals(id),
    account_id TEXT NOT NULL REFERENCES accounts(id),
    amount_minor INTEGER NOT NULL CHECK(typeof(amount_minor) = 'integer' AND amount_minor != 0),
    PRIMARY KEY(journal_id, account_id)
);
CREATE INDEX IF NOT EXISTS postings_account ON postings(account_id);
CREATE INDEX IF NOT EXISTS journals_history ON journals(kind, status, created_at DESC, id DESC);

CREATE TRIGGER IF NOT EXISTS journal_insert_pending
BEFORE INSERT ON journals WHEN NEW.status != 'pending'
BEGIN SELECT RAISE(ABORT, 'journal must start pending'); END;

CREATE TRIGGER IF NOT EXISTS journal_post_balanced
BEFORE UPDATE OF status ON journals WHEN NEW.status = 'posted'
BEGIN
    SELECT CASE WHEN (SELECT COUNT(*) FROM postings WHERE journal_id = NEW.id) != 2
        OR (SELECT COALESCE(SUM(amount_minor), 1) FROM postings WHERE journal_id = NEW.id) != 0
        THEN RAISE(ABORT, 'journal must have two balanced postings') END;
    SELECT CASE WHEN EXISTS (
        SELECT 1 FROM postings p JOIN accounts a ON a.id = p.account_id
        WHERE p.journal_id = NEW.id AND a.currency != NEW.currency
    ) THEN RAISE(ABORT, 'posting currency mismatch') END;
END;

CREATE TRIGGER IF NOT EXISTS journal_immutable_update
BEFORE UPDATE ON journals WHEN OLD.status = 'posted'
BEGIN SELECT RAISE(ABORT, 'posted journals are immutable'); END;
CREATE TRIGGER IF NOT EXISTS journal_immutable_delete
BEFORE DELETE ON journals WHEN OLD.status = 'posted'
BEGIN SELECT RAISE(ABORT, 'posted journals are immutable'); END;
CREATE TRIGGER IF NOT EXISTS posting_insert_pending
BEFORE INSERT ON postings
WHEN (SELECT status FROM journals WHERE id = NEW.journal_id) != 'pending'
BEGIN SELECT RAISE(ABORT, 'cannot append to posted journal'); END;
CREATE TRIGGER IF NOT EXISTS posting_immutable_update
BEFORE UPDATE ON postings
BEGIN SELECT RAISE(ABORT, 'postings are immutable'); END;
CREATE TRIGGER IF NOT EXISTS posting_immutable_delete
BEFORE DELETE ON postings
BEGIN SELECT RAISE(ABORT, 'postings are immutable'); END;
CREATE TRIGGER IF NOT EXISTS account_immutable
BEFORE UPDATE ON accounts
BEGIN SELECT RAISE(ABORT, 'account identity is immutable'); END;
