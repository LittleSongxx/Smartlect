CREATE TABLE IF NOT EXISTS demo_scenario_run (
    scenario_run_id VARCHAR(64) PRIMARY KEY,
    state VARCHAR(16) NOT NULL DEFAULT 'ACTIVE',
    reset_request_id VARCHAR(64) UNIQUE,
    reset_fingerprint CHAR(64),
    reset_result_json MEDIUMTEXT,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    retired_at DATETIME(6),
    CHECK (state IN ('ACTIVE','RETIRED')),
    CHECK (reset_result_json IS NULL OR JSON_VALID(reset_result_json))
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;

INSERT INTO demo_scenario_run (scenario_run_id)
SELECT DISTINCT scenario_run_id FROM demo_scenario_registry
ON DUPLICATE KEY UPDATE scenario_run_id=demo_scenario_run.scenario_run_id;
