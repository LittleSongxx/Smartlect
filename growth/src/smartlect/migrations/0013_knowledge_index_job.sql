CREATE TABLE IF NOT EXISTS knowledge_index_job (
  job_id CHAR(32) PRIMARY KEY,
  execution_scope_id VARCHAR(128) NOT NULL, actor_id VARCHAR(64) NOT NULL,
  doc_id VARCHAR(128) NOT NULL, version BIGINT NOT NULL,
  state VARCHAR(32) NOT NULL DEFAULT 'PENDING',
  total_chunks INT NOT NULL, processed_chunks INT NOT NULL DEFAULT 0, failed_chunks INT NOT NULL DEFAULT 0,
  embedding_model VARCHAR(128), index_version VARCHAR(128),
  message TEXT, error_type VARCHAR(64),
  created_at DATETIME(6) NOT NULL, updated_at DATETIME(6) NOT NULL,
  KEY idx_index_job_scope (execution_scope_id, created_at)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
