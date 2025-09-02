BEGIN;
CREATE TABLE IF NOT EXISTS conversation_state (
  conversation_id INTEGER PRIMARY KEY
    REFERENCES conversations(conversation_id) ON DELETE CASCADE,
  pending_field   TEXT,                -- 'city' | 'type' | 'price_max' | 'beds' | NULL
  slots_json      TEXT,                -- last-known slots for this conversation
  updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TRIGGER IF NOT EXISTS conversation_state_touch_uat
AFTER UPDATE ON conversation_state
BEGIN
  UPDATE conversation_state SET updated_at=CURRENT_TIMESTAMP
  WHERE conversation_id=NEW.conversation_id;
END;
COMMIT;
