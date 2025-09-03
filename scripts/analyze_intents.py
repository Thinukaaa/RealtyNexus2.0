# scripts/analyze_intents.py
import os, sqlite3, json, collections, datetime as dt
DB_PATH = os.getenv("REALTY_DB", os.path.join(os.path.dirname(__file__), "..", "db", "realty.db"))

def rows(sql, args=()):
    with sqlite3.connect(DB_PATH) as cx:
        cx.row_factory = sqlite3.Row
        return cx.execute(sql, args).fetchall()

print("=== Top intents (last 7 days) ===")
for r in rows("""
    SELECT intent, COUNT(*) c
    FROM msg_intents
    WHERE ts >= datetime('now','-7 days')
    GROUP BY intent ORDER BY c DESC"""):
    print(f"{r['intent']:20} {r['c']}")

print("\n=== Fallback rate (last 7 days) ===")
tot = rows("""SELECT COUNT(*) c FROM msg_intents WHERE ts >= datetime('now','-7 days')""")[0]["c"]
fb  = rows("""SELECT COUNT(*) c FROM msg_intents WHERE ts >= datetime('now','-7 days') AND intent='fallback'""")[0]["c"]
rate = (fb/tot*100) if tot else 0
print(f"fallback: {fb}/{tot} = {rate:.1f}%")

print("\n=== Avg result_count by intent (last 7 days) ===")
for r in rows("""
    SELECT intent, AVG(COALESCE(result_count,0.0)) avg_results, COUNT(*) n
    FROM msg_intents
    WHERE ts >= datetime('now','-7 days')
    GROUP BY intent ORDER BY avg_results DESC"""):
    print(f"{r['intent']:20} {r['avg_results']:.2f}  (n={r['n']})")

print("\n=== Recent examples ===")
for r in rows("""SELECT ts, intent, user_text, result_count FROM msg_intents ORDER BY ts DESC LIMIT 10"""):
    print(f"{r['ts']}  [{r['intent']}] rc={r['result_count']} : {r['user_text'][:100]}...")
