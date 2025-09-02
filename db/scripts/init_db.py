# scripts/init_db.py
import sqlite3, pathlib

DB = pathlib.Path("db/realty.db")
SCHEMA = pathlib.Path("db/schema.sql")

DB.parent.mkdir(exist_ok=True)
sql = SCHEMA.read_text(encoding="utf-8")

con = sqlite3.connect(str(DB))
con.executescript(sql)
con.close()
print(f"Schema applied to {DB}")
