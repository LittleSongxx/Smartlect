CREATE TABLE IF NOT EXISTS merchant_observation (
  observation_id CHAR(32) PRIMARY KEY, execution_scope_id VARCHAR(128) NOT NULL, actor_id VARCHAR(64) NOT NULL,
  round_number BIGINT NOT NULL, watermark CHAR(64) NOT NULL, snapshot_json MEDIUMTEXT NOT NULL,
  observed_at DATETIME(6) NOT NULL, UNIQUE KEY uk_merchant_round (execution_scope_id,actor_id,round_number),
  CHECK (JSON_VALID(snapshot_json))
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
-- statement-break
CREATE TABLE IF NOT EXISTS merchant_run_context (
  agent_run_id CHAR(32) PRIMARY KEY, execution_scope_id VARCHAR(128) NOT NULL, actor_id VARCHAR(64) NOT NULL,
  request_id VARCHAR(128) NOT NULL, request_hash CHAR(64) NOT NULL, observation_id CHAR(32) NOT NULL,
  context_json MEDIUMTEXT NOT NULL, created_at DATETIME(6) NOT NULL,
  UNIQUE KEY uk_merchant_request (execution_scope_id,actor_id,request_id),
  FOREIGN KEY (agent_run_id) REFERENCES agent_run(agent_run_id),
  FOREIGN KEY (observation_id) REFERENCES merchant_observation(observation_id), CHECK (JSON_VALID(context_json))
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
-- statement-break
CREATE TABLE IF NOT EXISTS merchant_plan (
  plan_id CHAR(32) PRIMARY KEY, version BIGINT NOT NULL, execution_scope_id VARCHAR(128) NOT NULL,
  actor_id VARCHAR(64) NOT NULL, agent_run_id CHAR(32) NOT NULL UNIQUE, observation_id CHAR(32) NOT NULL,
  parent_plan_id CHAR(32), parent_plan_version BIGINT, status VARCHAR(32) NOT NULL,
  spec_json MEDIUMTEXT NOT NULL, diagnosis_json MEDIUMTEXT NOT NULL,
  grant_id VARCHAR(64), envelope_hash CHAR(64), authorization_json MEDIUMTEXT,
  action_receipts_json MEDIUMTEXT NOT NULL, lease_token CHAR(32), lease_until DATETIME(6),
  created_at DATETIME(6) NOT NULL, updated_at DATETIME(6) NOT NULL,
  UNIQUE KEY uk_merchant_effective_plan (execution_scope_id,actor_id,observation_id),
  KEY idx_merchant_plan_scope (execution_scope_id,actor_id,created_at),
  FOREIGN KEY (agent_run_id) REFERENCES agent_run(agent_run_id),
  CHECK (JSON_VALID(spec_json)), CHECK (JSON_VALID(diagnosis_json)), CHECK (JSON_VALID(action_receipts_json))
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
-- statement-break
CREATE TABLE IF NOT EXISTS merchant_experience (
  memory_id CHAR(32) PRIMARY KEY, execution_scope_id VARCHAR(128) NOT NULL, actor_id VARCHAR(64) NOT NULL,
  plan_id CHAR(32) NOT NULL, content TEXT NOT NULL, evidence_ids_json MEDIUMTEXT NOT NULL,
  status VARCHAR(16) NOT NULL DEFAULT 'DRAFT', version BIGINT NOT NULL DEFAULT 1,
  approved_by VARCHAR(64), approved_at DATETIME(6), created_at DATETIME(6) NOT NULL,
  UNIQUE KEY uk_merchant_experience_plan (plan_id), FOREIGN KEY (plan_id) REFERENCES merchant_plan(plan_id),
  CHECK (JSON_VALID(evidence_ids_json))
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
-- statement-break
CREATE TABLE IF NOT EXISTS merchant_scope_access (
  actor_id VARCHAR(64) NOT NULL, execution_scope_id VARCHAR(128) NOT NULL, label VARCHAR(200) NOT NULL,
  PRIMARY KEY (actor_id,execution_scope_id), FOREIGN KEY (execution_scope_id) REFERENCES execution_scope(execution_scope_id)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
-- statement-break
CREATE TABLE IF NOT EXISTS merchant_scope_selection (
  session_hash CHAR(64) PRIMARY KEY, actor_id VARCHAR(64) NOT NULL, execution_scope_id VARCHAR(128) NOT NULL,
  FOREIGN KEY (execution_scope_id) REFERENCES execution_scope(execution_scope_id)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
-- statement-break
CREATE TABLE IF NOT EXISTS growth_diagnostic_fact (
  signal_id CHAR(64) PRIMARY KEY, execution_scope_id VARCHAR(128) NOT NULL,
  subject_type VARCHAR(16) NOT NULL, actor_id VARCHAR(64) NOT NULL,
  kind VARCHAR(32) NOT NULL, reason VARCHAR(64) NOT NULL, source_json MEDIUMTEXT NOT NULL,
  occurred_at DATETIME(6) NOT NULL, KEY idx_diagnostic_scope (execution_scope_id,occurred_at), CHECK (JSON_VALID(source_json))
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
