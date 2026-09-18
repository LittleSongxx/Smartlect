CREATE TABLE IF NOT EXISTS recommendation_strategy (
  execution_scope_id VARCHAR(128) NOT NULL, strategy_version VARCHAR(128) NOT NULL,
  config_json JSON NOT NULL, config_checksum CHAR(64) NOT NULL,
  created_by VARCHAR(64) NOT NULL, created_at DATETIME(6) NOT NULL,
  PRIMARY KEY (execution_scope_id,strategy_version)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
-- statement-break
CREATE TABLE IF NOT EXISTS recommendation_experiment (
  execution_scope_id VARCHAR(128) NOT NULL, experiment_id VARCHAR(128) NOT NULL,
  salt CHAR(64) NOT NULL, control_strategy_version VARCHAR(128) NOT NULL,
  treatment_strategy_version VARCHAR(128) NOT NULL, revision BIGINT NOT NULL DEFAULT 1,
  created_at DATETIME(6) NOT NULL, updated_at DATETIME(6) NOT NULL,
  PRIMARY KEY (execution_scope_id,experiment_id),
  CONSTRAINT fk_rec_control_strategy FOREIGN KEY (execution_scope_id,control_strategy_version)
    REFERENCES recommendation_strategy(execution_scope_id,strategy_version),
  CONSTRAINT fk_rec_treatment_strategy FOREIGN KEY (execution_scope_id,treatment_strategy_version)
    REFERENCES recommendation_strategy(execution_scope_id,strategy_version)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
-- statement-break
CREATE TABLE IF NOT EXISTS recommendation_assignment (
  assignment_id CHAR(32) PRIMARY KEY, execution_scope_id VARCHAR(128) NOT NULL,
  experiment_id VARCHAR(128) NOT NULL, subject_key VARCHAR(128) NOT NULL,
  group_name VARCHAR(16) NOT NULL, bucket INT NOT NULL, strategy_version VARCHAR(128) NOT NULL,
  created_at DATETIME(6) NOT NULL, updated_at DATETIME(6) NOT NULL,
  UNIQUE KEY uk_rec_assignment_subject (execution_scope_id,experiment_id,subject_key),
  CONSTRAINT fk_rec_assignment_experiment FOREIGN KEY (execution_scope_id,experiment_id)
    REFERENCES recommendation_experiment(execution_scope_id,experiment_id),
  CONSTRAINT fk_rec_assignment_strategy FOREIGN KEY (execution_scope_id,strategy_version)
    REFERENCES recommendation_strategy(execution_scope_id,strategy_version)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
