-- Separate attempted payment facts: a declined attempt does not close or settle an intent.
CREATE TABLE IF NOT EXISTS pay_payment_attempt (
    attempt_id VARCHAR(64) PRIMARY KEY,
    pay_order_id VARCHAR(32) NOT NULL,
    order_id VARCHAR(32) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    attempt_status VARCHAR(16) NOT NULL,
    reason_code VARCHAR(64) NOT NULL,
    payment_mode VARCHAR(16) NOT NULL,
    attempted_amount_cents BIGINT NOT NULL,
    occurred_at_epoch_ms BIGINT NOT NULL,
    fingerprint CHAR(64) NOT NULL,
    result_json MEDIUMTEXT NOT NULL,
    KEY idx_pay_attempt_intent (pay_order_id, occurred_at_epoch_ms),
    CHECK (attempt_status = 'DECLINED' AND reason_code = 'MOCK_CHANNEL_DECLINED'
           AND payment_mode = 'mock' AND attempted_amount_cents > 0)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;

-- Same transactional Outbox contract as the existing order service.
CREATE TABLE IF NOT EXISTS local_message_outbox (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    idempotency_key VARCHAR(128) NOT NULL,
    exchange_name VARCHAR(64) NOT NULL,
    routing_key VARCHAR(64) NOT NULL,
    payload_json MEDIUMTEXT NOT NULL,
    reliability_level VARCHAR(16) DEFAULT 'STANDARD' NOT NULL,
    status TINYINT DEFAULT 0 NOT NULL,
    retry_count INT DEFAULT 0 NOT NULL,
    error_message VARCHAR(512),
    lease_owner VARCHAR(64),
    lease_until DATETIME,
    next_retry_time DATETIME,
    create_time DATETIME NOT NULL,
    update_time DATETIME,
    sent_time DATETIME,
    CONSTRAINT uk_outbox_idempotency UNIQUE (idempotency_key),
    KEY idx_outbox_status_ctime (status, create_time),
    KEY idx_outbox_dispatch (status, next_retry_time, lease_until, id)
) ENGINE=InnoDB CHARACTER SET utf8mb4;
