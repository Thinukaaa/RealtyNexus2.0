# scripts/run_sql.py
import sys, sqlite3, pathlib
if len(sys.argv) != 2:
    raise SystemExit("Usage: python scripts/run_sql.py <path-to-sql-file>")
p = pathlib.Path(sys.argv[1])
sql = p.read_text(encoding="utf-8")
con = sqlite3.connect("db/realty.db")
con.executescript(sql)
con.close()
print(f"Applied {p}")
