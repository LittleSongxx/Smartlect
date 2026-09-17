CREATE TABLE IF NOT EXISTS product_projection_job (
  job_id CHAR(32) PRIMARY KEY,
  execution_scope_id VARCHAR(128) NOT NULL,
  actor_id VARCHAR(64) NOT NULL,
  product_id VARCHAR(64) NOT NULL,
  state VARCHAR(32) NOT NULL DEFAULT 'PENDING',
  attempt INT NOT NULL DEFAULT 0,
  checksum CHAR(64),
  doc_id VARCHAR(128),
  version INT,
  index_job_id CHAR(32),
  message TEXT,
  error_type VARCHAR(64),
  created_at DATETIME(6) NOT NULL,
  updated_at DATETIME(6) NOT NULL,
  KEY idx_projection_product (execution_scope_id, product_id, created_at),
  KEY idx_projection_state (state, updated_at)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
