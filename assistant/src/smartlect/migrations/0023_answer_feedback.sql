CREATE TABLE IF NOT EXISTS answer_feedback (
  id CHAR(32) NOT NULL, agent_run_id CHAR(32) NOT NULL,
  subject_type VARCHAR(16) NOT NULL, actor_id VARCHAR(64) NOT NULL, execution_scope_id VARCHAR(128) NOT NULL,
  rating ENUM('up','down') NOT NULL, reason_code VARCHAR(32) NULL, reason_text VARCHAR(2000) NULL,
  created_at DATETIME(6) NOT NULL, updated_at DATETIME(6) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_feedback_run_actor (agent_run_id,actor_id),
  KEY idx_feedback_run (agent_run_id),
  KEY idx_feedback_owner (execution_scope_id,subject_type,actor_id,created_at)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
