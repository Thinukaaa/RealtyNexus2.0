import os, re, sqlite3, secrets, json
from flask import Flask, request, jsonify, render_template, send_from_directory
from difflib import SequenceMatcher

# --- dotenv & OpenAI are OPTIONAL now ---
try:
    from dotenv import load_dotenv
except Exception:
    def load_dotenv(*args, **kwargs):  # no-op if dotenv not installed
        return None
try:
    from openai import OpenAI
except Exception:
    OpenAI = None

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "") or os.getenv("OPENAI_API_KEY_1", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_TEMPERATURE = float(os.getenv("OPENAI_TEMPERATURE", "0.3"))
client = OpenAI(api_key=OPENAI_API_KEY) if (OpenAI and OPENAI_API_KEY) else None

RELAX_ON_EMPTY = True     # show similar options if exact search is empty
RELAX_ON_MISSING = True   # show broad results when only city OR type is missing

# ---------- app/DB ----------
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.getenv("REALTY_DB", os.path.join(APP_DIR, "db", "realty.db"))
app = Flask(__name__, static_folder="static", template_folder="templates")

def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

# ---------- schema bootstrap (creates only if missing) ----------
def table_exists(cnx, name: str) -> bool:
    return bool(cnx.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())

def ensure_column(cnx, table: str, coldef: str):
    colname = coldef.split()[0]
    try:
        cols = {r["name"] for r in cnx.execute(f"PRAGMA table_info({table})")}
        if colname not in cols:
            cnx.execute(f"ALTER TABLE {table} ADD COLUMN {coldef}")
    except Exception:
        pass

def ensure_schema():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with conn() as cnx:
        # conversations (chat sessions)
        if not table_exists(cnx, "conversations"):
            cnx.execute("""
                CREATE TABLE conversations (
                  conversation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                  session_id TEXT,
                  lead_id INTEGER,
                  source TEXT,
                  status TEXT DEFAULT 'open',
                  started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                  ended_at DATETIME
                )
            """)
        # messages (chat history)
        if not table_exists(cnx, "messages"):
            cnx.execute("""
                CREATE TABLE messages (
                  message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                  conversation_id INTEGER NOT NULL,
                  role TEXT NOT NULL,
                  content TEXT NOT NULL,
                  model TEXT,
                  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
        # msg_intents (telemetry; tolerant superset schema)
        if not table_exists(cnx, "msg_intents"):
            cnx.execute("""
                CREATE TABLE msg_intents (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  conversation_id INTEGER,
                  message_id INTEGER,
                  session_id TEXT,
                  name TEXT,
                  intent TEXT,
                  score REAL,
                  confidence REAL,
                  user_text TEXT,
                  slots_json TEXT,
                  reply_type TEXT,
                  result_count INTEGER,
                  notes TEXT,
                  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
        else:
            for col in [
                "conversation_id INTEGER","message_id INTEGER","session_id TEXT",
                "name TEXT","intent TEXT","score REAL","confidence REAL",
                "user_text TEXT","slots_json TEXT","reply_type TEXT",
                "result_count INTEGER","notes TEXT","created_at DATETIME"
            ]:
                ensure_column(cnx, "msg_intents", col)

        # leads table (used by /api/contact); create if missing
        if not table_exists(cnx, "leads"):
            cnx.execute("""
                CREATE TABLE leads (
                  lead_id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT,
                  email TEXT,
                  phone TEXT,
                  source TEXT,
                  intent TEXT,
                  stage TEXT,
                  note TEXT,
                  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                  updated_at DATETIME
                )
            """)

ensure_schema()

# ---------- in-memory session filters ----------
class SessionStore(dict):
    def new(self):
        sid = secrets.token_hex(8); self[sid] = {}; return sid
    def get(self, sid, default=None): return super().get(sid, default or {})
    def set(self, sid, val): self[sid] = val
STORE = SessionStore()

# ---------- helpers ----------
def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())
def _similar(a,b): return SequenceMatcher(a=_norm(a), b=_norm(b)).ratio()

CANON_TYPES = {
    "apartment": {"apt","apartment","condo","flat","apartments"},
    "house": {"house","home","villa","houses"},
    "townhouse": {"townhouse","town house","townhouses"},
    "land": {"land","plot","plots","bare land"},
    "commercial": {"commercial","building","office","shop","retail"},
}
CANON_CITIES = {"colombo","colombo 5","galle","kandy","mount lavinia","dehiwala","borella","colombo 8"}

def detect_type(t):
    low = (t or "").lower()
    for canon, aliases in CANON_TYPES.items():
        for a in aliases:
            if re.search(rf"\b{re.escape(a)}(es|s)?\b", low): return canon
    return None

def detect_city(t):
    low = (t or "").lower()
    for c in sorted(CANON_CITIES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(c)}\b", low): return c.title()
    m = re.search(r"\b(borella|galle fort|mt\.?\s?lavinia|mount lavinia|dehiwala|colombo\s?\d)\b", low)
    return m.group(1).replace("mt","mount").title() if m else None

def detect_beds(t):
    m = re.search(r"\b(\d+)\s*br\b", (t or "").lower()) or re.search(r"\b(\d+)\s*bed", (t or "").lower())
    return int(m.group(1)) if m else None

def detect_tenure(t):
    low = (t or "").lower()
    if any(w in low for w in ["rent","rental","lease"]): return "rent"
    if any(w in low for w in ["buy","sale","sell"]): return "sale"
    return None

def parse_budget_value(text: str):
    low = (text or "").lower().replace(",", "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)(\s*(m|mn|million))?", low)
    if m:
        a, b = float(m.group(1)), float(m.group(2)); mul = 1_000_000 if m.group(4) else 1
        return {"price_min": int(a*mul), "price_max": int(b*mul)}
    m = re.search(r"(?:under|below|max(?:imum)?)\s+(\d+(?:\.\d+)?)(\s*(m|mn|million))?", low)
    if m:
        v = float(m.group(1));  v *= 1_000_000 if m.group(3) else 1
        return {"price_max": int(v)}
    m = re.search(r"(?:over|min(?:imum)?)\s+(\d+(?:\.\d+)?)(\s*(m|mn|million))?", low)
    if m:
        v = float(m.group(1));  v *= 1_000_000 if m.group(3) else 1
        return {"price_min": int(v)}
    m = re.search(r"\b(\d{2,})(\s*(m|mn|million))?\b", low)
    if m:
        v = float(m.group(1)); v *= 1_000_000 if m.group(3) else 1
        return {"price_max": int(v)}
    return None

def cheapest_price_for(cnx, city, ptype, tenure=None, beds=None):
    try:
        if not city or not ptype: return None, 0
        params, where = [city, city, ptype], ["(city = ? OR district = ?)", "property_type = ?"]
        if tenure in ("rent","sale"):
            where.append("purpose = ?"); params.append(tenure)
        if beds:
            where.append("bedrooms >= ?"); params.append(int(beds))
        sql = f"SELECT MIN(price_lkr) AS min_price, COUNT(*) AS cnt FROM properties WHERE status='available' AND {' AND '.join(where)}"
        row = cnx.execute(sql, params).fetchone()
        return (row["min_price"], row["cnt"]) if row else (None, 0)
    except Exception:
        return None, 0

def map_area_to_city(cnx, area_or_city: str | None):
    if not area_or_city: return None
    try:
        row = cnx.execute(
            "SELECT a.city FROM area_aliases aa JOIN areas a ON a.area_id=aa.area_id WHERE LOWER(aa.alias)=LOWER(?)",
            (area_or_city,)
        ).fetchone()
        if row and row["city"]: return row["city"]
    except Exception:
        pass
    try:
        row = cnx.execute(
            "SELECT city FROM properties WHERE LOWER(city)=LOWER(?) OR LOWER(district)=LOWER(?) LIMIT 1",
            (area_or_city, area_or_city)
        ).fetchone()
        if row and row["city"]: return row["city"]
    except Exception:
        pass
    return str(area_or_city).title()

# ---------- list builders ----------
def missing_for_search(session):
    need = []
    if not session.get("city"): need.append("city")
    if not session.get("type"): need.append("property type")
    return need

def _format_land_subtitle(r):
    parts = []
    if r.get("land_perch"): parts.append(f"{int(r['land_perch'])} perch")
    elif r.get("area_sqm"): parts.append(f"{int(r['area_sqm'])} m²")
    if r.get("city"): parts.append(r["city"])
    return " · ".join(parts) if parts else (r.get("city") or "-")

def list_cards(rows):
    out = []
    for r in rows:
        is_land = (r.get("property_type") == "land")
        subtitle = _format_land_subtitle(r) if is_land else f"{r.get('bedrooms') or '-'} BR · {r.get('bathrooms') or '-'} Bath · {r.get('city') or ''}".strip()
        out.append({
            "id": r["property_id"],
            "title": r["title"],
            "subtitle": subtitle,
            "price_lkr": r.get("price_lkr"),
            "type": r.get("property_type"),
            "badge": "Featured" if r.get("featured") else None,
            "code": r.get("listing_code"),
            "area_sqm": r.get("area_sqm"),
            "land_perch": r.get("land_perch"),
        })
    return out

def _base_search_sql(where):
    return f"""SELECT property_id,title,city,property_type,price_lkr,bedrooms,bathrooms,area_sqm,land_perch,featured,description,listing_code
               FROM properties WHERE {' AND '.join(where)}
               ORDER BY featured DESC, price_lkr ASC LIMIT 20"""

def search_listings(cnx, session):
    try:
        need = missing_for_search(session)
        if need: return [], need
        params, where = [], ["status='available'"]
        city = session.get("city")
        if city:
            where.append("(city = ? OR district = ?)"); params += [city, city]
        if session.get("type"):
            where.append("property_type = ?"); params.append(session["type"])
        if session.get("tenure") in ("rent","sale"):
            where.append("purpose = ?"); params.append(session["tenure"])
        if session.get("beds"):
            where.append("bedrooms >= ?"); params.append(int(session["beds"]))
        if "price" in session:
            where.append("price_lkr = ?"); params.append(int(session["price"]))
        if "price_max" in session:
            where.append("price_lkr <= ?"); params.append(int(session["price_max"]))
        if "price_min" in session:
            where.append("price_lkr >= ?"); params.append(int(session["price_min"]))
        rows = [dict(r) for r in cnx.execute(_base_search_sql(where), params)]
        return list_cards(rows), []
    except Exception:
        return [], []

def browse_any_listings(cnx, session):
    """
    Broad show:
      - City set only → show mixed types in that city.
      - Type set only → show that type across all cities.
    """
    try:
        city, ptype = session.get("city"), session.get("type")
        params, where = [], ["status='available'"]
        preface = None
        if city and not ptype:
            where.append("(city = ? OR district = ?)"); params += [city, city]
            preface = f"Showing a mix of property types in {city}. Tell me a property type to refine."
        elif ptype and not city:
            where.append("property_type = ?"); params.append(ptype)
            preface = f"You didn’t specify a city. Showing {ptype}s across our areas. Tell me a city to refine."
        else:
            return [], None
        if session.get("beds"):
            where.append("bedrooms >= ?"); params.append(int(session["beds"]))
        if session.get("tenure") in ("rent","sale"):
            where.append("purpose = ?"); params.append(session["tenure"])
        if "price_max" in session:
            where.append("price_lkr <= ?"); params.append(int(session["price_max"]))
        if "price_min" in session:
            where.append("price_lkr >= ?"); params.append(int(session["price_min"]))
        rows = [dict(r) for r in cnx.execute(_base_search_sql(where), params)]
        return list_cards(rows), preface
    except Exception:
        return [], None

def search_nearest(cnx, session):
    try:
        area = session.get("area") or session.get("city")
        if not area: return [], "Tell me the area or city (e.g., ‘nearest apartments to Borella’)."
        s = dict(session); s.setdefault("type","apartment"); s["city"] = area
        rows, _ = search_listings(cnx, s)
        return rows, None
    except Exception:
        return [], "Tell me the area or city (e.g., ‘nearest apartments to Borella’)."

def open_investments(cnx):
    try:
        sql = """
            SELECT
              i.plan_name, i.category, i.min_investment_lkr, i.summary,
              i.expected_roi_pct, i.expected_yield_pct, p.city AS city
            FROM investments i
            LEFT JOIN properties p ON p.property_id = i.property_id
            WHERE i.status = 'open'
            ORDER BY i.created_at DESC
            LIMIT 20
        """
        items = []
        for r in cnx.execute(sql):
            d = dict(r)
            items.append({
                "title": d.get("plan_name") or "Investment Plan",
                "badge": ((d.get("category") or "").replace("_"," ").title() or None),
                "subtitle": d.get("city") or "-",
                "min_investment_lkr": d.get("min_investment_lkr"),
                "summary": d.get("summary"),
                "yield_pct": d.get("expected_yield_pct"),
                "roi_pct": d.get("expected_roi_pct"),
            })
        return items
    except Exception:
        return []

def kb_answer_categories(cnx):
    return ("We support apartments, houses, townhouses, land, and commercial (rent and sale). "
            "Search by city (Colombo, Galle, Kandy), budget, bedrooms, and features. "
            "Example: “3BR apartments in Galle under 80M”.") 

# ---------- NLU ----------
INTENT_KEYWORDS = {
    "greet": {"hi":1,"hello":1,"hey":1,"good morning":1,"good evening":1},
    "ask_categories": {"property types":2,"types":1,"categories":1,"what properties":2,"what kind of properties":2},
    "capabilities": {"what can you do":3,"how do you work":2,"what can you":1,"help":1,"features":1},
    "bot_identity": {"what are you":3,"who are you":2,"your name":1},
    "bot_creator": {"who made you":3,"who created you":3,"your creator":2},
    "services_info": {"services":3,"service":2,"consulting":2,"valuation":2,"legal":2,"due diligence":2,"deed":2,"advisory":2},
    "coverage_info": {"cities do you cover":3,"areas do you cover":3,"coverage":2,"which cities":2,"what cities":2},
    "contact_agent": {"contact a real agent":3,"talk to an agent":3,"contact agent":2,"speak to agent":2},
    "book_valuation": {"book a valuation":3,"free valuation":3,"valuation":2,"schedule valuation":2},
    "reset": {"reset":3,"start over":2,"clear filters":2,"clear":1},
    "investment_advice": {"investments":2,"investment":2,"plans":1,"yield":1,"roi":1},
    "nearest_query": {"nearest":2,"near me":2,"close to":1,"near":1},
}

def faq_answer(cnx, text, threshold=0.78):
    try:
        best = (0.0, None)
        for r in cnx.execute("SELECT question, answer FROM faqs"):
            sim = _similar(text, r["question"])
            if sim > best[0]:
                best = (sim, r["answer"])
        return best[1] if best[0] >= threshold else None
    except Exception:
        return None

def classify_intent_smart(text: str):
    t = _norm(text)
    best, best_name = 0, None
    for name, kw in INTENT_KEYWORDS.items():
        score = sum(w for k,w in kw.items() if k in t)
        if score > best:
            best, best_name = score, name
    try:
        with conn() as cnx:
            for r in cnx.execute("SELECT intent_name, phrase FROM intent_phrases"):
                sim = _similar(t, r["phrase"])
                if sim >= 0.88 and best < 2:
                    best, best_name = 3, r["intent_name"]
    except Exception:
        pass
    conf = min(1.0, best / 3.0) if best else 0.0
    return best_name, conf

def parse_intent_slots(text, session):
    slots = {}
    city = detect_city(text);  typ = detect_type(text);  beds = detect_beds(text)
    if city: slots["city"] = city
    if typ:  slots["type"] = typ
    if beds: slots["beds"] = beds
    b = parse_budget_value(text)
    if b: slots.update(b)
    tnr = detect_tenure(text)
    if tnr: slots["tenure"] = tnr

    low = (text or "").lower().strip()
    if low in ("reset","restart","clear","clear filters","start over"):
        return "reset", 1.0, slots

    smart, conf = classify_intent_smart(text)
    if smart: return smart, conf, slots

    if "nearest" in low or re.search(r"\bnear\b", low): return "nearest_query", 0.9, slots
    if "investment" in low: return "investment_advice", 0.9, slots
    if b and not (city or typ): return "set_budget", 0.7, slots
    if city and not typ and any(w in low for w in ["show","find","list","search","want"]): return "set_location", 0.7, slots
    if typ and not city and any(w in low for w in ["show","find","list","search","in"]):   return "set_type", 0.7, slots
    if tnr in ("rent","sale") and not (city or typ): return "rent_or_buy", 0.6, slots
    if any(w in low for w in ["show","find","search","apartment","house","land","townhouse","plot"]):
        return "browse_listings", 0.6, slots
    return "fallback", 0.3, slots

# ---------- conversations/messages ----------
SYSTEM_PROMPT = """You are RealtyAI, a concise, friendly Sri Lankan real-estate assistant.
- Stick to facts from the DB context when provided.
- If filters are missing, ask exactly ONE clarifying question.
- Prefer showing city, property type, bedrooms, and price in suggestions.
- If no matches, suggest relaxing budget/location or property type.
- Never invent addresses or prices; if unknown, say so briefly.
"""

def ensure_conversation(cnx, session_id: str) -> int:
    row = cnx.execute(
        "SELECT conversation_id FROM conversations WHERE session_id=? AND status='open' ORDER BY started_at DESC LIMIT 1",
        (session_id,)
    ).fetchone()
    if row: return row["conversation_id"]
    return cnx.execute("INSERT INTO conversations(session_id, status) VALUES (?, 'open')", (session_id,)).lastrowid

def get_history(cnx, conversation_id: int, limit: int = 12):
    rows = cnx.execute(
        "SELECT role, content FROM messages WHERE conversation_id=? ORDER BY created_at DESC, message_id DESC LIMIT ?",
        (conversation_id, limit)
    ).fetchall()
    return list(reversed([{"role": r["role"], "content": r["content"]} for r in rows]))

def save_message(cnx, conversation_id: int, role: str, content: str, model: str | None = None):
    cur = cnx.execute(
        "INSERT INTO messages(conversation_id, role, content, model) VALUES (?,?,?,?)",
        (conversation_id, role, content, model)
    )
    return cur.lastrowid

def log_intent(cnx, conversation_id, message_id, name, score, user_text=None, slots=None, reply_type=None, result_count=None, notes=None):
    try:
        cols = {r["name"] for r in cnx.execute("PRAGMA table_info(msg_intents)")}
        row = {}
        if "conversation_id" in cols: row["conversation_id"] = conversation_id
        if "message_id" in cols:      row["message_id"] = message_id
        if "name" in cols:            row["name"] = name
        if "intent" in cols:          row["intent"] = name
        val = float(score or 0.0)
        if "score" in cols:           row["score"] = val
        if "confidence" in cols:      row["confidence"] = val
        if "user_text" in cols:       row["user_text"] = user_text or ""
        if "slots_json" in cols:
            row["slots_json"] = json.dumps(slots or {}, ensure_ascii=False)
        if "reply_type" in cols:      row["reply_type"] = reply_type
        if "result_count" in cols:    row["result_count"] = result_count
        if "notes" in cols:           row["notes"] = notes
        if "session_id" in cols:
            sid_row = cnx.execute("SELECT session_id FROM conversations WHERE conversation_id=?", (conversation_id,)).fetchone()
            row["session_id"] = (sid_row and sid_row["session_id"]) or "unknown"
        if row:
            keys = ",".join(row.keys()); qs = ",".join(["?"]*len(row))
            cnx.execute(f"INSERT INTO msg_intents({keys}) VALUES({qs})", tuple(row.values()))
            cnx.commit()
    except Exception as e:
        print("log_intent warning:", e)

# ---------- FTS context + LLM (optional) ----------
def build_db_context(cnx, session: dict, user_text: str, k: int = 5) -> str:
    try:
        terms = []
        if session.get("city"): terms.append(session["city"])
        if session.get("type"): terms.append(session["type"])
        if session.get("beds"): terms.append(f"{session['beds']} BR")
        if session.get("tenure"): terms.append(session["tenure"])
        query = " ".join([t for t in terms if t]) + " " + (user_text or "")
        rows = cnx.execute("""
            SELECT p.property_id, p.title, p.city, p.property_type, p.price_lkr, p.bedrooms, p.bathrooms,
                   substr(p.description,1,180) AS snip
            FROM property_fts f
            JOIN properties p ON p.property_id = f.rowid
            WHERE property_fts MATCH ?
              AND p.status='available'
            LIMIT ?
        """, (query, k)).fetchall()
        if not rows:
            cards, _ = search_listings(cnx, session)
            if not cards: return ""
            def fmt_card(c): return f"#{c['id']} | {c['title']} | {c['type']} in {c.get('subtitle','')} | LKR {int(c.get('price_lkr') or 0):,}"
            return "Top listings:\n" + "\n".join(fmt_card(c) for c in cards[:k])
        out = []
        for r in rows:
            out.append(f"#{r['property_id']} | {r['title']} | {r['property_type']} | {r['city']} | "
                       f"{r['bedrooms'] or '-'}BR/{r['bathrooms'] or '-'}BA | LKR {int(r['price_lkr'] or 0):,} | {r['snip'] or ''}")
        return "Top listings:\n" + "\n".join(out)
    except Exception:
        return ""

def call_llm(history: list, db_context: str) -> str:
    if not client: return ""
    messages = [{"role":"system","content": SYSTEM_PROMPT}]
    if db_context: messages.append({"role":"system","content": f"Database context:\n{db_context}"})
    messages.extend(history)
    try:
        resp = client.chat.completions.create(model=OPENAI_MODEL, temperature=OPENAI_TEMPERATURE, messages=messages)
        return (resp.choices[0].message.content or "").strip()
    except Exception:
        return ""

# ---------- routes ----------
@app.get("/")
def home():
    tpl = os.path.join(APP_DIR, "templates", "index.html")
    if os.path.exists(tpl): return render_template("index.html")
    return send_from_directory(APP_DIR, "index.html")

@app.post("/api/chat")
def api_chat():
    data = request.get_json(force=True, silent=True) or {}
    text = (data.get("message") or "").strip()
    sid  = data.get("session_id") or STORE.new()

    if not text:
        return jsonify({"reply":{"type":"text","content":"Tell me city, property type, and budget to start."},"session_id":sid})

    session = STORE.get(sid)

    # parse intent/slots and update session filters
    intent, conf, slots = parse_intent_slots(text, session)
    session.update(slots); STORE.set(sid, session)

    with conn() as cnx:
        conversation_id = ensure_conversation(cnx, sid)
        if session.get("city"):
            session["city"] = map_area_to_city(cnx, session["city"]); STORE.set(sid, session)
        user_mid = save_message(cnx, conversation_id, "user", text)

        # canned/meta
        if intent in ("greet","capabilities","bot_identity","bot_creator","services_info","coverage_info","contact_agent","book_valuation"):
            canned = {
                "greet": "Hi! I’m RealtyAI. Tell me city, property type, and budget (e.g., “3BR apartments in Galle under 80M”).",
                "capabilities": "I can search by city/type/bedrooms/budget and show investment plans. Try: “apartments in Colombo 5 under 50M”.",
                "bot_identity": "I’m RealtyAI, a virtual agent by RealtyNexus.",
                "bot_creator": "I’m RealtyAI — designed & developed by Thinukaaa. © RealtyNexus.",
                "services_info": "We offer: Residential & Rentals • Investment Advisory • Consulting • Legal Due Diligence • Deed Verification • Bank-approved Valuations.",
                "coverage_info": "We currently cover Greater Colombo (Colombo 5, 8, Borella, Dehiwala/Mount Lavinia), Galle, and Kandy. Tell me the city, property type, and budget to start.",
                "contact_agent": "Share your name, email/phone, and a short note here, or use the Contact panel—we’ll connect you to a live agent.",
                "book_valuation": "To book a free valuation, drop your property location & contacts here, or use the ‘Book a free valuation’ button."
            }
            ans = faq_answer(cnx, text) or canned[intent]
            save_message(cnx, conversation_id, "assistant", ans)
            log_intent(cnx, conversation_id, user_mid, intent, conf)
            return jsonify({"reply": {"type":"text","content": ans}, "session_id": sid, "session": session})

        if intent == "ask_categories":
            content = kb_answer_categories(cnx)
            save_message(cnx, conversation_id, "assistant", content)
            log_intent(cnx, conversation_id, user_mid, intent, conf)
            return jsonify({"reply": {"type":"text","content": content}, "session_id": sid, "session": session})

        if intent == "reset":
            try: cnx.execute("UPDATE conversations SET status='closed', ended_at=CURRENT_TIMESTAMP WHERE conversation_id=?", (conversation_id,))
            except Exception: pass
            STORE.set(sid, {})
            content = "Cleared. Tell me a city, property type, and budget to start."
            save_message(cnx, conversation_id, "assistant", content)
            log_intent(cnx, conversation_id, user_mid, "reset", 1.0)
            return jsonify({"reply": {"type":"text","content": content}, "session_id": sid, "session": {}})

        if intent == "nearest_query":
            results, msg = search_nearest(cnx, session)
            if msg:
                payload = {"type":"text","content": msg}
                save_message(cnx, conversation_id, "assistant", msg)
                log_intent(cnx, conversation_id, user_mid, intent, conf)
            elif not results:
                content = "I didn’t find listings near that area. Try a different area or increase radius."
                payload = {"type":"text","content": content}
                save_message(cnx, conversation_id, "assistant", content)
                log_intent(cnx, conversation_id, user_mid, intent, conf)
            else:
                payload = {"type":"cards","items": results[:6]}
                save_message(cnx, conversation_id, "assistant", f"[cards:{len(results[:6])}]")
                log_intent(cnx, conversation_id, user_mid, intent, conf)
            return jsonify({"reply": payload, "session_id": sid, "session": session})

        if intent == "investment_advice":
            items = open_investments(cnx)
            if items:
                payload = {"type":"investments","items": items[:6]}
                save_message(cnx, conversation_id, "assistant", f"[investments:{len(items[:6])}]")
            else:
                content = "No open investment plans right now."
                payload = {"type":"text","content": content}
                save_message(cnx, conversation_id, "assistant", content)
            log_intent(cnx, conversation_id, user_mid, intent, conf)
            return jsonify({"reply": payload, "session_id": sid, "session": session})

        # search/browse
        if intent in ("set_budget","set_location","set_type","rent_or_buy","browse_listings"):
            results, missing = search_listings(cnx, session)
            if missing:
                if RELAX_ON_MISSING and len(missing) == 1:
                    alt_items, preface = browse_any_listings(cnx, session)
                    if alt_items:
                        payload = {"type":"cards","items": alt_items, "preface": preface}
                        save_message(cnx, conversation_id, "assistant", f"[cards:{len(alt_items)}]")
                        log_intent(cnx, conversation_id, user_mid, intent, conf, notes=f"broad_for_missing:{missing[0]}")
                        return jsonify({"reply": payload, "session_id": sid, "session": session})
                nice = " and ".join(missing) if len(missing)==2 else ", ".join(missing)
                hist = get_history(cnx, conversation_id)
                db_ctx = build_db_context(cnx, session, text, k=5)
                ai = call_llm(hist + [{"role":"user","content": f"User is missing: {nice}. Ask one short clarifying question."}], db_ctx)
                content = ai or f"Got it. To refine, tell me your {nice}."
                payload = {"type":"text","content": content}
                save_message(cnx, conversation_id, "assistant", content, OPENAI_MODEL if ai else None)
                log_intent(cnx, conversation_id, user_mid, intent, conf, notes=f"missing:{nice}")
                return jsonify({"reply": payload, "session_id": sid, "session": session})

            if not results:
                if RELAX_ON_EMPTY:
                    alt_items, mode = search_relaxed(cnx, session, text, k=6)
                    if alt_items:
                        city = session.get("city"); typ = session.get("type"); beds = session.get("beds")
                        hint = ""
                        if city and typ:
                            min_price, _ = cheapest_price_for(cnx, city, typ, session.get("tenure"), beds)
                            if isinstance(min_price, (int,float)) and min_price:
                                hint = f" (lowest ~ LKR {int(min_price):,}{' for ≥'+str(beds)+'BR' if beds else ''})"
                        payload = {"type":"cards","items": alt_items, "preface": "No exact match — showing similar options." + hint}
                        save_message(cnx, conversation_id, "assistant", f"[cards:{len(alt_items)}]")
                        log_intent(cnx, conversation_id, user_mid, intent, conf, notes=f"relaxed:{mode}")
                        return jsonify({"reply": payload, "session_id": sid, "session": session})

                city = session.get("city"); typ = session.get("type")
                hint = ""
                if city and typ:
                    min_price, _ = cheapest_price_for(cnx, city, typ, session.get("tenure"), session.get("beds"))
                    if isinstance(min_price, (int,float)) and min_price:
                        hint = f" The lowest for {typ}{' (≥'+str(session.get('beds'))+'BR)' if session.get('beds') else ''} in {city} is around LKR {int(min_price):,}."
                content = "No matches yet. Try increasing budget or changing filters." + hint
                payload = {"type":"text","content": content}
                save_message(cnx, conversation_id, "assistant", content)
                log_intent(cnx, conversation_id, user_mid, intent, conf, notes="no_results_with_filters")
                return jsonify({"reply": payload, "session_id": sid, "session": session})

            payload = {"type":"cards","items": results[:6]}
            save_message(cnx, conversation_id, "assistant", f"[cards:{len(results[:6])}]")
            log_intent(cnx, conversation_id, user_mid, intent, conf)
            return jsonify({"reply": payload, "session_id": sid, "session": session})

        # fallback
        hist = get_history(cnx, conversation_id)
        db_ctx = build_db_context(cnx, session, text, k=5)
        ai_text = call_llm(hist + [{"role":"user","content": text}], db_ctx)
        content = ai_text or "I can filter by city (Colombo, Galle, Kandy), type (apartment/house/land), and budget. Try: “3BR apartments in Galle under 80M”. What should I search?"
        save_message(cnx, conversation_id, "assistant", content, OPENAI_MODEL if ai_text else None)
        log_intent(cnx, conversation_id, user_mid, "fallback", conf)
        return jsonify({"reply": {"type":"text","content": content}, "session_id": sid, "session": session})

def search_relaxed(cnx, session, user_text: str, k: int = 6):
    s1 = dict(session)
    rows, _ = search_listings(cnx, s1)
    if rows: return rows[:k], "exact"
    s2 = {k:v for k,v in s1.items() if k != "beds"}
    rows, _ = search_listings(cnx, s2)
    if rows:
        for it in rows: it["badge"] = it.get("badge") or "Similar"
        return rows[:k], "drop_beds"
    s3 = dict(s2)
    if "price_max" in s3:
        try: s3["price_max"] = int(int(s3["price_max"]) * 1.25)
        except Exception: pass
    rows, _ = search_listings(cnx, s3)
    if rows:
        for it in rows: it["badge"] = it.get("badge") or "Similar"
        return rows[:k], "raise_budget"
    s4 = { "city": session.get("city"), "type": session.get("type") }
    rows, _ = search_listings(cnx, s4)
    if rows:
        for it in rows: it["badge"] = it.get("badge") or "Nearby"
        return rows[:k], "fallback_city_type"
    return [], "none"

@app.get("/health")
def health():
    try:
        with conn() as cnx:
            cnx.execute("SELECT 1").fetchone()
        db_ok = True
    except Exception:
        db_ok = False
    return jsonify({"ok": True, "db": db_ok, "model": OPENAI_MODEL, "openai_key": bool(OPENAI_API_KEY)})

@app.post("/api/contact")
def api_contact():
    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip().lower() or None
    phone = (request.form.get("phone") or "").strip() or None
    msg   = (request.form.get("message") or "").strip()
    if not (name and email and msg):
        return jsonify({"ok": False, "error": "missing_fields"}), 400
    with conn() as cnx:
        lead_id = None
        try:
            lead_id = cnx.execute(
                "INSERT INTO leads(name,email,phone,source,intent,stage,note) VALUES (?,?,?,?, 'general','new',?)",
                (name, email, phone, 'web_form', msg)
            ).lastrowid
        except sqlite3.IntegrityError:
            row = cnx.execute(
                "SELECT lead_id FROM leads WHERE (email=? AND email IS NOT NULL) OR (phone=? AND phone IS NOT NULL) "
                "ORDER BY created_at DESC LIMIT 1",
                (email or "", phone or "")
            ).fetchone()
            if row:
                lead_id = row["lead_id"]
                cnx.execute(
                    "UPDATE leads SET note = COALESCE(note,'') || char(10) || ?, updated_at=CURRENT_TIMESTAMP WHERE lead_id=?",
                    (f"[web_form] {msg}", lead_id)
                )
        conv_id = cnx.execute(
            "INSERT INTO conversations(lead_id, source, session_id, status) VALUES (?,?,?, 'open')",
            (lead_id, 'web_form', None)
        ).lastrowid
        cnx.execute(
            "INSERT INTO messages(conversation_id, role, content) VALUES (?,?,?)",
            (conv_id, 'user', f"Contact form from {name} <{email or '-'}>:\n{msg}")
        )
    return jsonify({"ok": True})

if __name__ == "__main__":
    port = int(os.getenv("PORT","5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
