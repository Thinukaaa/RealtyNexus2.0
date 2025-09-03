PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS msg_intents (
  id            INTEGER PRIMARY KEY,
  ts            DATETIME DEFAULT (CURRENT_TIMESTAMP),
  session_id    TEXT NOT NULL,
  user_text     TEXT NOT NULL,
  intent        TEXT NOT NULL,
  confidence    REAL,
  slots_json    TEXT,
  reply_type    TEXT,
  result_count  INTEGER,
  notes         TEXT
);

CREATE INDEX IF NOT EXISTS idx_msg_intents_ts ON msg_intents (ts DESC);
CREATE INDEX IF NOT EXISTS idx_msg_intents_session ON msg_intents (session_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_msg_intents_intent ON msg_intents (intent, ts DESC);
