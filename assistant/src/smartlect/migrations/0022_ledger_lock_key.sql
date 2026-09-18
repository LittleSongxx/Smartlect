CREATE TABLE IF NOT EXISTS commerce_ledger_lock_key (
    lock_key VARCHAR(64) PRIMARY KEY,
    touched_at DATETIME(6) NOT NULL
);
