CREATE TABLE order_quote (
    quote_id varchar(32) NOT NULL PRIMARY KEY,
    user_id varchar(64) NOT NULL,
    request_hash char(64) NOT NULL,
    offer_hash char(64) NOT NULL,
    amount_cents bigint NOT NULL,
    expires_at datetime(3) NOT NULL,
    request_json json NOT NULL,
    pay_order_id varchar(64) NULL,
    created_at datetime(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    CONSTRAINT ck_quote_amount CHECK (amount_cents >= 0),
    KEY idx_quote_owner (user_id, expires_at),
    UNIQUE KEY uk_quote_payment (pay_order_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
