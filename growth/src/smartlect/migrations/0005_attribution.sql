CREATE TABLE IF NOT EXISTS execution_scope (
  execution_scope_id VARCHAR(128) PRIMARY KEY, scenario_run_id VARCHAR(128), branch_id VARCHAR(64),
  created_at DATETIME(6) NOT NULL
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
-- statement-break
INSERT IGNORE INTO execution_scope VALUES ('store',NULL,NULL,UTC_TIMESTAMP(6));
-- statement-break
CREATE TABLE IF NOT EXISTS execution_resource (
  resource_type VARCHAR(16) NOT NULL, resource_id VARCHAR(64) NOT NULL, execution_scope_id VARCHAR(128) NOT NULL,
  PRIMARY KEY (resource_type,resource_id), KEY idx_scope_resource (execution_scope_id,resource_type),
  FOREIGN KEY (execution_scope_id) REFERENCES execution_scope(execution_scope_id)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
-- statement-break
CREATE TABLE IF NOT EXISTS visitor_binding (
  visitor_id CHAR(32) PRIMARY KEY, user_id VARCHAR(64) NOT NULL, execution_scope_id VARCHAR(128) NOT NULL,
  bound_at DATETIME(6) NOT NULL, assignment_conflict BOOLEAN NOT NULL DEFAULT FALSE,
  KEY idx_bound_user (execution_scope_id,user_id)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
-- statement-break
CREATE TABLE IF NOT EXISTS recommendation_receipt (
  recommendation_id CHAR(32) PRIMARY KEY, execution_scope_id VARCHAR(128) NOT NULL,
  subject_type VARCHAR(16) NOT NULL, actor_id VARCHAR(64) NOT NULL, session_id VARCHAR(128) NOT NULL,
  conversation_id CHAR(32), assignment_id CHAR(32) NOT NULL, strategy_version VARCHAR(128) NOT NULL,
  result_json JSON NOT NULL, created_at DATETIME(6) NOT NULL, expires_at DATETIME(6) NOT NULL,
  KEY idx_recommendation_owner (execution_scope_id,subject_type,actor_id,created_at)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
-- statement-break
CREATE TABLE IF NOT EXISTS traffic_touch (
  touch_id CHAR(32) PRIMARY KEY, idempotency_key CHAR(64) NOT NULL UNIQUE, fingerprint CHAR(64) NOT NULL,
  execution_scope_id VARCHAR(128) NOT NULL, subject_type VARCHAR(16) NOT NULL, actor_id VARCHAR(64) NOT NULL,
  session_id VARCHAR(128) NOT NULL, conversation_id CHAR(32), kind VARCHAR(24) NOT NULL,
  traffic_channel VARCHAR(24), campaign_id VARCHAR(64), creative_id VARCHAR(64),
  product_id VARCHAR(64), sku_key VARCHAR(128), recommendation_id CHAR(32), position INT,
  assignment_id CHAR(32), strategy_version VARCHAR(128), occurred_at DATETIME(6) NOT NULL,
  origin VARCHAR(32) NOT NULL, metadata_json JSON NOT NULL,
  KEY idx_touch_owner (execution_scope_id,subject_type,actor_id,occurred_at),
  KEY idx_touch_recommendation (recommendation_id,position,kind)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
-- statement-break
CREATE TABLE IF NOT EXISTS attribution_context (
  context_id CHAR(32) PRIMARY KEY, context_key VARCHAR(128) NOT NULL UNIQUE,
  execution_scope_id VARCHAR(128) NOT NULL, user_id VARCHAR(64) NOT NULL,
  snapshot_version INT NOT NULL, snapshot_hash CHAR(64) NOT NULL, snapshot_json JSON NOT NULL,
  captured_at DATETIME(6) NOT NULL, expires_at DATETIME(6) NOT NULL
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
-- statement-break
CREATE TABLE IF NOT EXISTS commerce_attribution_meta (
  event_id VARCHAR(128) PRIMARY KEY, execution_scope_id VARCHAR(128) NOT NULL, metadata_json JSON NOT NULL,
  FOREIGN KEY (event_id) REFERENCES commerce_event(event_id), KEY idx_event_scope (execution_scope_id)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
-- statement-break
CREATE TABLE IF NOT EXISTS commerce_attribution (
  event_id VARCHAR(128) PRIMARY KEY, execution_scope_id VARCHAR(128) NOT NULL,
  category VARCHAR(24) NOT NULL, calculation_status VARCHAR(16) NOT NULL, reason VARCHAR(128) NOT NULL,
  rule_version VARCHAR(64) NOT NULL, as_of DATETIME(6) NOT NULL,
  context_id CHAR(32), order_created_at DATETIME(6), traffic_channel VARCHAR(24),
  ad_click_id CHAR(32), campaign_id VARCHAR(64), creative_id VARCHAR(64),
  recommendation_click_id CHAR(32), recommendation_id CHAR(32), recommendation_assist_id CHAR(32),
  assignment_id CHAR(32), strategy_version VARCHAR(128),
  FOREIGN KEY (event_id) REFERENCES commerce_event(event_id), KEY idx_attribution_scope (execution_scope_id,category)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
