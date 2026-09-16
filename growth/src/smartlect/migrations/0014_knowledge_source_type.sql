ALTER TABLE knowledge_document
  ADD COLUMN source_type VARCHAR(32) NOT NULL DEFAULT 'MANUAL';
-- statement-break
CREATE INDEX idx_document_source ON knowledge_document (execution_scope_id, source_type, doc_id);
