# scripts/ls_counts.py
import os, sqlite3
DB = os.getenv("REALTY_DB", os.path.join("db", "realty.db"))
con = sqlite3.connect(DB)
for t in ["properties","property_media","property_fts","investments","investment_properties","area_aliases","type_synonyms"]:
    try:
        c = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"{t:24s} {c}")
    except Exception as e:
        print(f"{t:24s} (missing)  {e}")
con.close()
