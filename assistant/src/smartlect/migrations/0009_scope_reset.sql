CREATE TABLE IF NOT EXISTS execution_scope_reset (
  scenario_run_id VARCHAR(128) PRIMARY KEY, reset_request_id VARCHAR(64) NOT NULL UNIQUE,
  state VARCHAR(16) NOT NULL, manifest_hash CHAR(64) NOT NULL, manifests_json MEDIUMTEXT NOT NULL,
  event_ids_json MEDIUMTEXT NOT NULL, expected_watermark_hash CHAR(64), java_call_started BOOLEAN NOT NULL DEFAULT FALSE,
  result_json MEDIUMTEXT, created_at DATETIME(6) NOT NULL, updated_at DATETIME(6) NOT NULL,
  CHECK (state IN ('QUIESCING','RETIRED')), CHECK (JSON_VALID(manifests_json)),
  CHECK (JSON_VALID(event_ids_json)), CHECK (result_json IS NULL OR JSON_VALID(result_json))
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
