import os, sqlite3

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.getenv("REALTY_DB", os.path.join(APP_DIR, "db", "realty.db"))

with sqlite3.connect(DB_PATH) as cx:
    cx.execute("PRAGMA journal_mode=WAL")
    cx.execute("""CREATE TABLE IF NOT EXISTS faqs(
        id INTEGER PRIMARY KEY,
        question TEXT UNIQUE,
        answer TEXT NOT NULL
    )""")
    cx.execute("""CREATE TABLE IF NOT EXISTS intent_phrases(
        id INTEGER PRIMARY KEY,
        intent_name TEXT NOT NULL,
        phrase TEXT NOT NULL
    )""")

    faqs = [
        ("what can you do", "I can search by city/type/bedrooms/budget and show investment plans. Try: “apartments in Colombo 5 under 50M”."),
        ("who are you", "I’m RealtyAI, a virtual agent by RealtyNexus."),
        ("who created you", "I was built by RealtyNexus to assist with property and investments."),
    ]
    for q,a in faqs:
        cx.execute("INSERT OR IGNORE INTO faqs(question,answer) VALUES(?,?)", (q,a))

    phrases = [
        ("greet", "hello"),
        ("greet", "hi"),
        ("greet", "hey"),
        ("capabilities", "what can you do"),
        ("bot_identity", "what are you"),
        ("bot_creator", "who created you"),
    ]
    for it, ph in phrases:
        cx.execute("INSERT INTO intent_phrases(intent_name, phrase) VALUES(?,?)", (it,ph))

    cx.commit()

print("Seeded faqs and intent_phrases.")
