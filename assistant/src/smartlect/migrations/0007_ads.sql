CREATE TABLE IF NOT EXISTS ads_account (
  execution_scope_id VARCHAR(128) PRIMARY KEY, account_id VARCHAR(128) NOT NULL,
  budget_period VARCHAR(32) NOT NULL DEFAULT 'scope_lifetime', budget_cap_cents BIGINT NOT NULL,
  spent_cents BIGINT NOT NULL DEFAULT 0, reservations_cents BIGINT NOT NULL DEFAULT 0,
  grant_id VARCHAR(64) NOT NULL, version BIGINT NOT NULL DEFAULT 1, created_at DATETIME(6) NOT NULL,
  CHECK (budget_cap_cents >= spent_cents AND spent_cents >= 0 AND reservations_cents = 0)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
-- statement-break
CREATE TABLE IF NOT EXISTS ads_campaign (
  campaign_id VARCHAR(64) PRIMARY KEY, execution_scope_id VARCHAR(128) NOT NULL, owner_id VARCHAR(64) NOT NULL,
  name VARCHAR(200) NOT NULL, product_id VARCHAR(64) NOT NULL, sku_key VARCHAR(128) NOT NULL,
  budget_cents BIGINT NOT NULL, spent_cents BIGINT NOT NULL DEFAULT 0, cpc_cents BIGINT NOT NULL,
  status VARCHAR(16) NOT NULL DEFAULT 'DRAFT', version BIGINT NOT NULL DEFAULT 1,
  pause_reason VARCHAR(128), last_action_id VARCHAR(64), initial_json JSON NOT NULL, created_at DATETIME(6) NOT NULL,
  KEY idx_ads_campaign_scope (execution_scope_id),
  CHECK (budget_cents >= spent_cents AND spent_cents >= 0 AND cpc_cents > 0)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
-- statement-break
CREATE TABLE IF NOT EXISTS ads_creative (
  creative_id VARCHAR(64) PRIMARY KEY, execution_scope_id VARCHAR(128) NOT NULL, owner_id VARCHAR(64) NOT NULL,
  campaign_id VARCHAR(64) NOT NULL, copy_text VARCHAR(1000) NOT NULL,
  status VARCHAR(16) NOT NULL DEFAULT 'DRAFT', version BIGINT NOT NULL DEFAULT 1,
  pause_reason VARCHAR(128), last_action_id VARCHAR(64), initial_json JSON NOT NULL, created_at DATETIME(6) NOT NULL,
  KEY idx_ads_creative_campaign (campaign_id),
  FOREIGN KEY (campaign_id) REFERENCES ads_campaign(campaign_id)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
-- statement-break
CREATE TABLE IF NOT EXISTS ads_grant (
  grant_id VARCHAR(64) PRIMARY KEY, execution_scope_id VARCHAR(128) NOT NULL, approval_actor VARCHAR(64) NOT NULL,
  initial_plan_id VARCHAR(128) NOT NULL, initial_plan_version BIGINT NOT NULL,
  envelope_json JSON NOT NULL, envelope_hash CHAR(64) NOT NULL, initial_json JSON NOT NULL,
  plan_snapshot_json JSON NOT NULL, plan_snapshot_hash CHAR(64) NOT NULL,
  replaces_grant_id VARCHAR(64), valid_until DATETIME(6) NOT NULL, approval_time DATETIME(6) NOT NULL,
  revoked_at DATETIME(6), version BIGINT NOT NULL DEFAULT 1,
  KEY idx_ads_grant_scope (execution_scope_id)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
-- statement-break
CREATE TABLE IF NOT EXISTS growth_action (
  action_id VARCHAR(64) PRIMARY KEY, idempotency_key VARCHAR(128) NOT NULL UNIQUE,
  execution_scope_id VARCHAR(128) NOT NULL, actor_id VARCHAR(64) NOT NULL,
  fingerprint CHAR(64) NOT NULL, request_json JSON NOT NULL, result_json JSON NOT NULL,
  created_at DATETIME(6) NOT NULL, KEY idx_ads_action_scope (execution_scope_id,created_at)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
-- statement-break
CREATE TABLE IF NOT EXISTS ads_inventory (
  execution_scope_id VARCHAR(128) NOT NULL, product_id VARCHAR(64) NOT NULL, sku_key VARCHAR(128) NOT NULL,
  generation BIGINT NOT NULL DEFAULT 0, pause_generation BIGINT NOT NULL DEFAULT 0,
  observed_generation BIGINT NOT NULL DEFAULT 0, stock BIGINT,
  query_started_latest_at DATETIME(6), query_started_at DATETIME(6), query_completed_at DATETIME(6), elapsed_ms DOUBLE,
  PRIMARY KEY (execution_scope_id,product_id,sku_key)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
-- statement-break
CREATE TABLE IF NOT EXISTS ad_interaction (
  exposure_id VARCHAR(64) PRIMARY KEY, execution_scope_id VARCHAR(128) NOT NULL,
  subject_type VARCHAR(16) NOT NULL, actor_id VARCHAR(64) NOT NULL, creative_id VARCHAR(64) NOT NULL,
  result_json JSON NOT NULL, created_at DATETIME(6) NOT NULL,
  KEY idx_ad_interaction_scope (execution_scope_id,created_at)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
-- statement-break
CREATE TABLE IF NOT EXISTS ad_spend (
  click_id VARCHAR(64) PRIMARY KEY, exposure_id VARCHAR(64) NOT NULL UNIQUE,
  execution_scope_id VARCHAR(128) NOT NULL, subject_type VARCHAR(16) NOT NULL, actor_id VARCHAR(64) NOT NULL,
  account_id VARCHAR(128) NOT NULL, grant_id VARCHAR(64) NOT NULL,
  campaign_id VARCHAR(64) NOT NULL, creative_id VARCHAR(64) NOT NULL,
  amount_cents BIGINT NOT NULL, touch_id CHAR(32) NOT NULL UNIQUE, result_json JSON NOT NULL,
  occurred_at DATETIME(6) NOT NULL, KEY idx_ad_spend_scope (execution_scope_id,occurred_at),
  FOREIGN KEY (exposure_id) REFERENCES ad_interaction(exposure_id),
  FOREIGN KEY (touch_id) REFERENCES traffic_touch(touch_id), CHECK (amount_cents > 0)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
