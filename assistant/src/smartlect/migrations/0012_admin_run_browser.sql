CREATE INDEX idx_agent_run_created ON agent_run (created_at);
-- statement-break
CREATE INDEX idx_conversation_scope ON conversation (execution_scope_id, updated_at);
