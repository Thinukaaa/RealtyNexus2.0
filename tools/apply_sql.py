# save as tools\apply_sql.py
import os, sqlite3, sys
db = os.environ.get("REALTY_DB", r"db\realty.db")
path = sys.argv[1]
sql = open(path, "r", encoding="utf-8").read()
with sqlite3.connect(db) as cx:
    cx.executescript(sql)
print("Applied:", path, "to", db)
