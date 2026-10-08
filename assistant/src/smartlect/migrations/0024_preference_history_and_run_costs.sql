CREATE TABLE IF NOT EXISTS user_preference_history (
  id CHAR(32) NOT NULL,
  subject_type VARCHAR(16) NOT NULL, actor_id VARCHAR(64) NOT NULL, execution_scope_id VARCHAR(128) NOT NULL,
  preference_key VARCHAR(32) NOT NULL,
  value_json JSON NOT NULL, source VARCHAR(16) NOT NULL, confidence DECIMAL(5,4) NOT NULL,
  evidence_ids_json JSON NOT NULL, observed_at DATETIME(6) NOT NULL, expires_at DATETIME(6) NULL,
  version BIGINT NOT NULL, deleted_at DATETIME(6) NULL,
  action ENUM('superseded','deleted','noop','rejected_conflict') NOT NULL,
  conflict_json JSON NULL,
  superseded_at DATETIME(6) NOT NULL,
  PRIMARY KEY (id),
  KEY idx_pref_history_owner (subject_type,actor_id,execution_scope_id,preference_key,superseded_at)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
-- statement-break
ALTER TABLE agent_run ADD COLUMN cost_estimate_cny DECIMAL(12,6) NULL;
-- statement-break
ALTER TABLE agent_run ADD COLUMN total_tokens BIGINT NULL;
-- statement-break
ALTER TABLE agent_run ADD KEY idx_agent_run_created (created_at);
