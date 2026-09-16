CREATE TABLE IF NOT EXISTS model_runtime_config (
  role VARCHAR(16) PRIMARY KEY,
  model_id VARCHAR(64) NOT NULL,
  params_json JSON,
  note VARCHAR(256),
  updated_by VARCHAR(64) NOT NULL,
  updated_at DATETIME(6) NOT NULL
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
