CREATE TABLE IF NOT EXISTS conversation (
  conversation_id CHAR(32) PRIMARY KEY,
  subject_type VARCHAR(16) NOT NULL, actor_id VARCHAR(64) NOT NULL,
  execution_scope_id VARCHAR(128) NOT NULL,
  version BIGINT NOT NULL DEFAULT 1, message_sequence BIGINT NOT NULL DEFAULT 0,
  lease_run_id CHAR(32), lease_owner VARCHAR(128), lease_token CHAR(32),
  lease_epoch BIGINT NOT NULL DEFAULT 0, lease_until DATETIME(6),
  created_at DATETIME(6) NOT NULL, updated_at DATETIME(6) NOT NULL,
  KEY idx_conversation_owner (subject_type, actor_id, execution_scope_id)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
-- statement-break
CREATE TABLE IF NOT EXISTS agent_run (
  agent_run_id CHAR(32) PRIMARY KEY, conversation_id CHAR(32) NOT NULL,
  parent_run_id CHAR(32), message_id VARCHAR(128) NOT NULL,
  request_hash CHAR(64) NOT NULL, state VARCHAR(32) NOT NULL DEFAULT 'CREATED',
  version BIGINT NOT NULL DEFAULT 1, model_mode VARCHAR(32) NOT NULL,
  deadline DATETIME(6), context_json JSON NOT NULL, result_json JSON,
  event_sequence BIGINT NOT NULL DEFAULT 0,
  created_at DATETIME(6) NOT NULL, updated_at DATETIME(6) NOT NULL,
  UNIQUE KEY uk_run_message (conversation_id, message_id),
  CONSTRAINT fk_run_conversation FOREIGN KEY (conversation_id) REFERENCES conversation(conversation_id),
  CONSTRAINT fk_run_parent FOREIGN KEY (parent_run_id) REFERENCES agent_run(agent_run_id)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
-- statement-break
CREATE TABLE IF NOT EXISTS message (
  conversation_id CHAR(32) NOT NULL, message_id VARCHAR(128) NOT NULL,
  sequence BIGINT NOT NULL, agent_run_id CHAR(32), role VARCHAR(16) NOT NULL,
  content TEXT NOT NULL, content_hash CHAR(64) NOT NULL, created_at DATETIME(6) NOT NULL,
  PRIMARY KEY (conversation_id, message_id), UNIQUE KEY uk_message_sequence (conversation_id, sequence),
  CONSTRAINT fk_message_conversation FOREIGN KEY (conversation_id) REFERENCES conversation(conversation_id),
  CONSTRAINT fk_message_run FOREIGN KEY (agent_run_id) REFERENCES agent_run(agent_run_id)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
-- statement-break
CREATE TABLE IF NOT EXISTS proposal (
  proposal_id CHAR(32) PRIMARY KEY, conversation_id CHAR(32) NOT NULL,
  agent_run_id CHAR(32) NOT NULL, action_type VARCHAR(16) NOT NULL,
  parameters_json JSON NOT NULL, parameters_hash CHAR(64) NOT NULL, proposal_hash CHAR(64) NOT NULL,
  quote_id VARCHAR(128), quote_total_cents BIGINT, expires_at DATETIME(6) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'PROPOSED', version BIGINT NOT NULL DEFAULT 1,
  decision_version BIGINT, approved BOOLEAN, confirmed_at DATETIME(6),
  action_id CHAR(32) NOT NULL UNIQUE, idempotency_key VARCHAR(128) NOT NULL UNIQUE,
  outcome VARCHAR(32), receipt_json JSON,
  created_at DATETIME(6) NOT NULL, updated_at DATETIME(6) NOT NULL,
  UNIQUE KEY uk_proposal_request (agent_run_id, action_type, parameters_hash),
  CONSTRAINT fk_proposal_conversation FOREIGN KEY (conversation_id) REFERENCES conversation(conversation_id),
  CONSTRAINT fk_proposal_run FOREIGN KEY (agent_run_id) REFERENCES agent_run(agent_run_id)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
-- statement-break
CREATE TABLE IF NOT EXISTS tool_call (
  agent_run_id CHAR(32) NOT NULL, call_id VARCHAR(128) NOT NULL,
  tool_name VARCHAR(128) NOT NULL, arguments_hash CHAR(64) NOT NULL, arguments_json JSON NOT NULL,
  outcome VARCHAR(32) NOT NULL DEFAULT 'started', receipt_json JSON,
  started_at DATETIME(6) NOT NULL, completed_at DATETIME(6),
  PRIMARY KEY (agent_run_id, call_id),
  CONSTRAINT fk_tool_run FOREIGN KEY (agent_run_id) REFERENCES agent_run(agent_run_id)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
-- statement-break
CREATE TABLE IF NOT EXISTS agent_run_event (
  agent_run_id CHAR(32) NOT NULL, sequence BIGINT NOT NULL,
  event_type VARCHAR(32) NOT NULL, data_json JSON NOT NULL, created_at DATETIME(6) NOT NULL,
  PRIMARY KEY (agent_run_id, sequence),
  CONSTRAINT fk_event_run FOREIGN KEY (agent_run_id) REFERENCES agent_run(agent_run_id)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
