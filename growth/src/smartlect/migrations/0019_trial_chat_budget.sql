CREATE TABLE IF NOT EXISTS trial_chat_budget (
  actor_id VARCHAR(64) NOT NULL,
  budget_date DATE NOT NULL,
  turns INT NOT NULL,
  updated_at DATETIME(6) NOT NULL,
  PRIMARY KEY (actor_id, budget_date),
  CHECK (turns >= 0)
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
