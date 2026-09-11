CREATE TABLE order_attribution_context (
    order_id varchar(64) NOT NULL PRIMARY KEY,
    user_id varchar(64) NOT NULL,
    order_created_at datetime(3) NOT NULL,
    context_id char(32) NULL,
    snapshot_version int NULL,
    snapshot_hash char(64) NULL,
    execution_scope_id varchar(128) NOT NULL,
    context_status varchar(32) NOT NULL,
    reason varchar(64) NOT NULL,
    frozen_at datetime(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    CONSTRAINT ck_order_attribution_status CHECK (context_status IN ('VERIFIED','UNKNOWN_CONTEXT')),
    KEY idx_order_attribution_context (context_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
