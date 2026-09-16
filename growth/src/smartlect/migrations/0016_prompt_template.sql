CREATE TABLE IF NOT EXISTS prompt_template (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  domain VARCHAR(16) NOT NULL, kind VARCHAR(16) NOT NULL, `key` VARCHAR(64) NOT NULL,
  version INT NOT NULL, body MEDIUMTEXT NOT NULL, meta_json JSON,
  status VARCHAR(16) NOT NULL DEFAULT 'draft', updated_by VARCHAR(64) NOT NULL,
  created_at DATETIME(6) NOT NULL, updated_at DATETIME(6) NOT NULL,
  UNIQUE KEY uk_prompt_version (domain, kind, `key`, version),
  KEY idx_prompt_active (domain, kind, `key`, status)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
