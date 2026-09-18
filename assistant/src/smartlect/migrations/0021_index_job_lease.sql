ALTER TABLE knowledge_index_job
    ADD COLUMN lease_owner VARCHAR(64) NULL,
    ADD COLUMN lease_until DATETIME(6) NULL;
