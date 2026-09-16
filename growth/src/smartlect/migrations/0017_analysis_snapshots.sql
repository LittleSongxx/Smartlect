CREATE TABLE IF NOT EXISTS review_analysis_snapshot (
  execution_scope_id VARCHAR(128) NOT NULL, product_id VARCHAR(64) NOT NULL,
  stats_json JSON NOT NULL, insights_json JSON, comment_count INT NOT NULL,
  analysis_version VARCHAR(32) NOT NULL, model_label VARCHAR(64),
  updated_by VARCHAR(64) NOT NULL, created_at DATETIME(6) NOT NULL, updated_at DATETIME(6) NOT NULL,
  PRIMARY KEY (execution_scope_id, product_id)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
-- statement-break
CREATE TABLE IF NOT EXISTS growth_report_snapshot (
  execution_scope_id VARCHAR(128) PRIMARY KEY,
  data_json JSON NOT NULL, suggestions MEDIUMTEXT,
  model_label VARCHAR(64), updated_by VARCHAR(64) NOT NULL,
  created_at DATETIME(6) NOT NULL, updated_at DATETIME(6) NOT NULL
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
