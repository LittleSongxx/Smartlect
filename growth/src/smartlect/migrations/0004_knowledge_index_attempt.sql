CREATE TABLE IF NOT EXISTS knowledge_index_attempt (
  call_id CHAR(32) PRIMARY KEY, publication_id CHAR(32) NOT NULL,
  execution_scope_id VARCHAR(128) NOT NULL, actor_id VARCHAR(64) NOT NULL,
  doc_id VARCHAR(128) NOT NULL, document_version INT NOT NULL,
  batch_index INT NOT NULL, attempt INT NOT NULL,
  status VARCHAR(16) NOT NULL, trace_json JSON NOT NULL,
  started_at DATETIME(6) NOT NULL, completed_at DATETIME(6),
  UNIQUE KEY uk_index_attempt (publication_id,batch_index,attempt),
  KEY idx_index_attempt_retention (started_at),
  KEY idx_index_attempt_document (execution_scope_id,doc_id,document_version),
  CONSTRAINT fk_index_attempt_document FOREIGN KEY (execution_scope_id,doc_id,document_version)
    REFERENCES knowledge_document(execution_scope_id,doc_id,version)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
