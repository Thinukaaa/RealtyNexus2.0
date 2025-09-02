# scripts/refresh_featured_summary.py
import sys, pathlib
# Ensure the project root (where db.py lives) is on the import path
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import db

txt = db.refresh_featured_summary()
print("\n=== Featured summary written to KB (source=featured_rollup) ===\n")
print(txt)
