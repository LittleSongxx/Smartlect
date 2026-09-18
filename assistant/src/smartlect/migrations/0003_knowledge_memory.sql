CREATE TABLE IF NOT EXISTS knowledge_catalog (
  execution_scope_id VARCHAR(128) PRIMARY KEY, revision BIGINT NOT NULL DEFAULT 0
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
-- statement-break
CREATE TABLE IF NOT EXISTS knowledge_document (
  doc_id VARCHAR(128) NOT NULL, version INT NOT NULL,
  execution_scope_id VARCHAR(128) NOT NULL, title VARCHAR(256) NOT NULL,
  source_uri VARCHAR(512) NOT NULL, checksum CHAR(64) NOT NULL, body MEDIUMTEXT NOT NULL,
  language VARCHAR(16) NOT NULL, acl VARCHAR(16) NOT NULL, acl_actor_id VARCHAR(64),
  product_ids_json JSON NOT NULL, category_ids_json JSON NOT NULL, facts_json JSON NOT NULL,
  valid_from DATETIME(6) NOT NULL, valid_until DATETIME(6) NOT NULL,
  status VARCHAR(16) NOT NULL, created_by VARCHAR(64) NOT NULL,
  created_at DATETIME(6) NOT NULL, published_at DATETIME(6), withdrawn_at DATETIME(6),
  PRIMARY KEY (execution_scope_id,doc_id,version),
  KEY idx_knowledge_lifecycle (execution_scope_id,status,acl,valid_from,valid_until),
  CONSTRAINT fk_knowledge_catalog FOREIGN KEY (execution_scope_id) REFERENCES knowledge_catalog(execution_scope_id)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
-- statement-break
CREATE TABLE IF NOT EXISTS knowledge_chunk (
  execution_scope_id VARCHAR(128) NOT NULL, doc_id VARCHAR(128) NOT NULL, version INT NOT NULL,
  chunk_id VARCHAR(32) NOT NULL, heading VARCHAR(256) NOT NULL, content TEXT NOT NULL,
  start_offset INT NOT NULL, end_offset INT NOT NULL, start_line INT NOT NULL, end_line INT NOT NULL,
  embedding_model VARCHAR(128), embedding_dimensions INT, index_version VARCHAR(128), vector_json JSON,
  PRIMARY KEY (execution_scope_id,doc_id,version,chunk_id),
  CONSTRAINT fk_chunk_document FOREIGN KEY (execution_scope_id,doc_id,version)
    REFERENCES knowledge_document(execution_scope_id,doc_id,version)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
-- statement-break
CREATE TABLE IF NOT EXISTS user_preference (
  subject_type VARCHAR(16) NOT NULL, actor_id VARCHAR(64) NOT NULL, execution_scope_id VARCHAR(128) NOT NULL,
  preference_key VARCHAR(32) NOT NULL, value_json JSON NOT NULL, source VARCHAR(16) NOT NULL,
  confidence DECIMAL(5,4) NOT NULL, evidence_ids_json JSON NOT NULL, observed_at DATETIME(6) NOT NULL,
  expires_at DATETIME(6), deleted_at DATETIME(6), version BIGINT NOT NULL DEFAULT 1,
  PRIMARY KEY (subject_type,actor_id,execution_scope_id,preference_key)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
-- statement-break
CREATE TABLE IF NOT EXISTS conversation_memory (
  conversation_id CHAR(32) PRIMARY KEY, version BIGINT NOT NULL DEFAULT 1,
  forgotten_before_sequence BIGINT NOT NULL DEFAULT 0,
  summary_json JSON, summary_sequence BIGINT NOT NULL DEFAULT 0,
  updated_at DATETIME(6) NOT NULL,
  CONSTRAINT fk_memory_conversation FOREIGN KEY (conversation_id) REFERENCES conversation(conversation_id)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
-- statement-break
CREATE TABLE IF NOT EXISTS support_ticket (
  ticket_id CHAR(32) PRIMARY KEY, conversation_id CHAR(32) NOT NULL,
  status VARCHAR(16) NOT NULL, reason VARCHAR(64) NOT NULL, evidence_json JSON NOT NULL,
  assigned_actor_id VARCHAR(64), resolution TEXT, version BIGINT NOT NULL DEFAULT 1,
  created_at DATETIME(6) NOT NULL, updated_at DATETIME(6) NOT NULL,
  KEY idx_support_conversation (conversation_id,status),
  CONSTRAINT fk_support_conversation FOREIGN KEY (conversation_id) REFERENCES conversation(conversation_id)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
