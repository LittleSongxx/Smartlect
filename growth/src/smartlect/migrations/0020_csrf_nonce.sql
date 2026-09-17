CREATE TABLE IF NOT EXISTS csrf_nonce (
    jti VARCHAR(64) PRIMARY KEY,
    actor_id VARCHAR(64) NOT NULL,
    session_id VARCHAR(128) NOT NULL,
    consumed_at DATETIME(6) NOT NULL
);
