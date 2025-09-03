import os, sqlite3, json, sys

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.getenv("REALTY_DB", os.path.join(APP_DIR, "db", "realty.db"))

REQUIRED_COLUMNS = [
    ("id",            "INTEGER PRIMARY KEY"),
    ("ts",            "DATETIME DEFAULT (CURRENT_TIMESTAMP)"),
    ("session_id",    "TEXT NOT NULL"),
    ("user_text",     "TEXT NOT NULL"),
    ("intent",        "TEXT NOT NULL"),
    ("confidence",    "REAL"),
    ("slots_json",    "TEXT"),
    ("reply_type",    "TEXT"),
    ("result_count",  "INTEGER"),
    ("notes",         "TEXT"),
]

def table_exists(cx, name):
    r = cx.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
    return bool(r)

def columns(cx, table):
    cols = {}
    for r in cx.execute(f"PRAGMA table_info({table})"):
        cols[r[1]] = r[2]  # name -> type
    return cols

def ensure_msg_intents(cx):
    if not table_exists(cx, "msg_intents"):
        cx.execute("""
            CREATE TABLE msg_intents (
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
            )
        """)
        cx.execute("CREATE INDEX IF NOT EXISTS idx_msg_intents_ts ON msg_intents (ts DESC)")
        cx.execute("CREATE INDEX IF NOT EXISTS idx_msg_intents_session ON msg_intents (session_id, ts DESC)")
        cx.execute("CREATE INDEX IF NOT EXISTS idx_msg_intents_intent ON msg_intents (intent, ts DESC)")
        print("Created table msg_intents")
        return

    existing = columns(cx, "msg_intents")
    for col, typ in REQUIRED_COLUMNS:
        if col not in existing:
            cx.execute(f"ALTER TABLE msg_intents ADD COLUMN {col} {typ}")
            print(f"Added column {col} {typ}")

def main():
    with sqlite3.connect(DB_PATH) as cx:
        ensure_msg_intents(cx)
        cx.commit()
    print("Migration complete on", DB_PATH)

if __name__ == "__main__":
    main()
