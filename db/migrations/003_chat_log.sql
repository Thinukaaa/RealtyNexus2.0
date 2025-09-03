BEGIN;

-- Conversations (open/close a thread per browser session)
CREATE TABLE IF NOT EXISTS conversations (
  conversation_id   INTEGER PRIMARY KEY,
  lead_id           INTEGER,
  source            TEXT NOT NULL DEFAULT 'chat_widget'
                      CHECK (source IN ('chat_widget','whatsapp','phone_log','email','other')),
  session_id        TEXT,
  status            TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','closed')),
  started_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  ended_at          DATETIME
);
CREATE INDEX IF NOT EXISTS idx_conv_lead   ON conversations(lead_id);
CREATE INDEX IF NOT EXISTS idx_conv_status ON conversations(status);

-- Messages (chat transcript)
CREATE TABLE IF NOT EXISTS messages (
  message_id        INTEGER PRIMARY KEY,
  conversation_id   INTEGER NOT NULL,
  role              TEXT NOT NULL CHECK (role IN ('user','assistant','agent','system')),
  content           TEXT NOT NULL,
  model             TEXT,
  tokens            INTEGER,
  error             TEXT,
  created_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_msg_conv_created ON messages(conversation_id, created_at);

-- Intent log (schema used by new app.py)
CREATE TABLE IF NOT EXISTS msg_intents (
  id               INTEGER PRIMARY KEY,
  conversation_id  INTEGER NOT NULL,
  message_id       INTEGER NOT NULL,
  name             TEXT NOT NULL,
  score            REAL,
  created_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE,
  FOREIGN KEY (message_id)      REFERENCES messages(message_id)        ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_intent_conv ON msg_intents(conversation_id);

COMMIT;
