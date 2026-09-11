CREATE TABLE IF NOT EXISTS demo_scenario_registry (
    scenario_number BIGINT AUTO_INCREMENT PRIMARY KEY,
    execution_scope_id VARCHAR(64) NOT NULL UNIQUE,
    scenario_run_id VARCHAR(64) NOT NULL,
    branch_id VARCHAR(32) NOT NULL,
    fingerprint CHAR(64) NOT NULL,
    request_json TEXT NOT NULL,
    manifest_json MEDIUMTEXT,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    UNIQUE KEY uk_demo_scenario_branch (scenario_run_id, branch_id)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
