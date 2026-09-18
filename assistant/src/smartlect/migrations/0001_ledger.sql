CREATE TABLE IF NOT EXISTS commerce_ledger_lock (id TINYINT PRIMARY KEY) ENGINE=InnoDB;
-- statement-break
INSERT IGNORE INTO commerce_ledger_lock VALUES (1);
-- statement-break
CREATE TABLE IF NOT EXISTS commerce_event (
  event_id VARCHAR(128) PRIMARY KEY, idempotency_key VARCHAR(128) NOT NULL UNIQUE,
  event_type VARCHAR(32) NOT NULL, user_id VARCHAR(64) NOT NULL, source VARCHAR(64) NOT NULL,
  product_id VARCHAR(64), sku_key VARCHAR(128), order_id VARCHAR(64), request_id VARCHAR(128),
  pay_order_id VARCHAR(64), order_item_id VARCHAR(64), amount_cents BIGINT,
  occurred_at DATETIME(6) NOT NULL, received_at DATETIME(6) NOT NULL,
  schema_version INT NOT NULL, raw_json LONGTEXT NOT NULL, fingerprint CHAR(64) NOT NULL,
  status VARCHAR(16) NOT NULL, reason VARCHAR(255),
  KEY idx_commerce_item (order_item_id, event_type, status),
  KEY idx_commerce_payment (pay_order_id, status), KEY idx_commerce_pending (status)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
-- statement-break
CREATE TABLE IF NOT EXISTS commerce_exception (
  message_hash CHAR(64) PRIMARY KEY, raw_body LONGBLOB NOT NULL, reason VARCHAR(500) NOT NULL,
  received_at DATETIME(6) NOT NULL, last_seen_at DATETIME(6) NOT NULL, occurrences INT NOT NULL DEFAULT 1
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
