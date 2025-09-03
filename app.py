import os, re, sqlite3, secrets, json
from flask import Flask, request, jsonify, render_template, send_from_directory
from difflib import SequenceMatcher

# --- OpenAI + dotenv (optional) ---
from dotenv import load_dotenv
try:
    from openai import OpenAI
except Exception:
    OpenAI = None

RELAX_ON_EMPTY = True  # try similar results if exact search has zero matches

load_dotenv()
client = OpenAI() if OpenAI else None
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_TEMPERATURE = float(os.getenv("OPENAI_TEMPERATURE", "0.3"))

# ---------- app/DB ----------
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.getenv("REALTY_DB", os.path.join(APP_DIR, "db", "realty.db"))
app = Flask(__name__, static_folder="static", template_folder="templates")

def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

# ---------- tiny session store (for user filters only) ----------
class SessionStore(dict):
    def new(self):
        sid = secrets.token_hex(8)
        self[sid] = {}
        return sid
    def get(self, sid, default=None):
        return super().get(sid, default or {})
    def set(self, sid, val): self[sid] = val
STORE = SessionStore()

# ---------- string helpers ----------
def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())
def _similar(a,b):
    return SequenceMatcher(a=_norm(a), b=_norm(b)).ratio()

# ---------- domain helpers ----------
CANON_TYPES = {
    "apartment": {"apt","apartment","condo","flat","apartments"},
    "house": {"house","home","villa","houses"},
    "townhouse": {"townhouse","town house","townhouses"},
    "land": {"land","plot","plots","lands"},
    "commercial": {"commercial","building","office","shop","retail","warehouse","building(s)?"},
}

# Expanded Sri Lankan coverage
CANON_CITIES = {
    "colombo","colombo 5","colombo 8","kotte","borella","dehiwala","mount lavinia","mt lavinia","moratuwa",
    "gampaha","negombo","kalutara","panadura","wattala",
    "galle","matara","matale","kandy","nuwara eliya","kurunegala","jaffna","anuradhapura","polonnaruwa",
    "trincomalee","batticaloa","hambantota","badulla","ratnapura"
}

def detect_type(t):
    low = (t or "").lower()
    for canon, aliases in CANON_TYPES.items():
        for a in aliases:
            if re.search(rf"\b{re.escape(a)}(es|s)?\b", low):
                return canon
    return None

def detect_city(t):
    low = (t or "").lower()
    # explicit known cities first
    for c in sorted(CANON_CITIES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(c)}\b", low):
            return c.title()

    # fallback: capture token(s) after "in ..."
    m = re.search(r"\bin\s+([a-zA-Z][a-zA-Z\s\.]+)", low)
    if m:
        cand = m.group(1).strip(" .")
        # stop at common trailing words
        cand = re.split(r"\s+(under|below|over|near|around|with|for|and|,|\.)", cand)[0].strip()
        if 2 <= len(cand) <= 30:
            return cand.title()
    return None

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
        v = float(m.group(1))
        if m.group(3): v *= 1_000_000
        return {"price_max": int(v)}
    m = re.search(r"(?:over|min(?:imum)?)\s+(\d+(?:\.\d+)?)(\s*(m|mn|million))?", low)
    if m:
        v = float(m.group(1))
        if m.group(3): v *= 1_000_000
        return {"price_min": int(v)}
    m = re.search(r"\b(\d{2,})(\s*(m|mn|million))?\b", low)
    if m:
        v = float(m.group(1))
        if m.group(3): v *= 1_000_000
        return {"price_max": int(v)}
    return None

def cheapest_price_for(cnx, city: str | None, ptype: str | None, tenure: str | None = None, beds: int | None = None):
    if not city or not ptype:
        return None, 0
    params, where = [city, city, ptype], ["(city = ? OR district = ?)", "property_type = ?"]
    if tenure in ("rent","sale"):
        where.append("purpose = ?"); params.append(tenure)
    if beds:
        where.append("bedrooms >= ?"); params.append(int(beds))
    sql = f"""
      SELECT MIN(price_lkr) AS min_price, COUNT(*) AS cnt
      FROM properties
      WHERE status='available' AND {' AND '.join(where)}
    """
    row = cnx.execute(sql, params).fetchone()
    if not row: return None, 0
    return row["min_price"], row["cnt"]

def top_city_alternative(cnx, exclude_city: str | None, ptype: str | None):
    params, where = [], ["status='available'"]
    if ptype:
        where.append("property_type = ?"); params.append(ptype)
    if exclude_city:
        where.append("(city IS NOT ? AND district IS NOT ?)"); params += [exclude_city, exclude_city]
    sql = f"""
      SELECT COALESCE(city, district) AS c, COUNT(*) AS n
      FROM properties
      WHERE {' AND '.join(where)}
      GROUP BY COALESCE(city, district)
      ORDER BY n DESC
      LIMIT 1
    """
    row = cnx.execute(sql, params).fetchone()
    return (row["c"], row["n"]) if row else (None, 0)

# ---------- list builders ----------
def missing_for_search(session):
    # City is now OPTIONAL. Type is preferred but also optional; when both missing, we ask.
    need = []
    if not session.get("type") and not session.get("city"):
        need = ["city or property type"]
    return need

def list_cards(rows):
    out = []
    for r in rows:
        subtitle = f"{r.get('bedrooms') or '-'} BR · {r.get('bathrooms') or '-'} Bath · {r.get('city') or ''}".strip()
        out.append({
            "id": r["property_id"], "title": r["title"], "subtitle": subtitle,
            "price_lkr": r["price_lkr"], "type": r["property_type"],
            "badge": "Featured" if r.get("featured") else r.get("badge"),
            "code": r.get("listing_code"),
        })
    return out

def search_listings(cnx, session):
    need = missing_for_search(session)
    if need: return [], need

    params, where = [], ["status='available'"]
    city = session.get("city")
    if city:
        where.append("(city = ? OR district = ?)")
        params += [city, city]
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

    sql = f"""SELECT property_id,title,city,property_type,price_lkr,bedrooms,bathrooms,area_sqm,land_perch,featured,description,listing_code
              FROM properties WHERE {' AND '.join(where)}
              ORDER BY featured DESC, price_lkr ASC LIMIT 20"""
    rows = [dict(r) for r in cnx.execute(sql, params)]
    return list_cards(rows), []

def search_nearest(cnx, session):
    area = session.get("area") or session.get("city")
    if not area: return [], "Tell me the area or city (e.g., ‘nearest apartments to Borella’)."
    s = dict(session); s.setdefault("type","apartment"); s["city"] = area
    rows, _ = search_listings(cnx, s)
    return rows, None

def open_investments(cnx):
    sql = """
        SELECT
          i.plan_name,
          i.category,
          i.min_investment_lkr,
          i.summary,
          i.expected_roi_pct,
          i.expected_yield_pct,
          p.city AS city
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

def kb_answer_categories(_cnx):
    return ("We support apartments, houses, townhouses, land, and commercial (rent and sale). "
            "Search by city (Colombo, Galle, Kandy, Matara, Jaffna), budget, bedrooms, and features. "
            "Example: “3BR apartments in Galle under 80M”.") 

# ---------- NLU (FAQ + smart intents) ----------
INTENT_KEYWORDS = {
    "greet": {"hi":1,"hello":1,"hey":1,"good morning":1,"good evening":1},
    "gratitude": {"thanks":3,"thank you":3,"tnx":2,"thankyou":3},
    "ask_categories": {
        "property types":2,"types":1,"categories":1,"what properties":3,"what kind of properties":3,
        "what do you have":2,"what properties do you have":3
    },
    "capabilities": {"what can you do":3,"how do you work":2,"what can you":1,"help":1,"features":1,"offer":2,"what can you offer":3},
    "our_services": {
        "services":3,"what are your services":3,"consult":2,"consultation":2,"consulting":2,
        "legal":2,"due diligence":3,"valuation":3,"free valuation":3,"deed verification":3,"investment advisory":3
    },
    "bot_identity": {"what are you":3,"who are you":2,"your name":1},
    "bot_creator": {"who made you":3,"who created you":3,"your creator":2,"who designed you":3},
    "contact_agent": {"live agent":3,"real agent":3,"contact agent":3,"talk to agent":3,"human":2,"call you":2},
    "reset": {"reset":3,"start over":2,"clear filters":2,"clear":1},
    "investment_advice": {"investments":2,"investment":2,"plans":1,"yield":1,"roi":1,"invesment":2},
    "nearest_query": {"nearest":2,"near me":2,"close to":1,"near":1},
    "ask_coverage": {
        "what cities do you cover": 3, "cities you cover": 3, "areas do you cover": 3,
        "coverage": 2, "service areas": 2, "what cities": 1, "what areas": 1,
        "cities that you have properties": 3, "what are the cities that you have properties": 3
    },
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
    if smart:
        return smart, conf, slots

    if "nearest" in low or re.search(r"\bnear\b", low): return "nearest_query", 0.9, slots
    if b and not (city or typ): return "set_budget", 0.7, slots
    if city and not typ and any(w in low for w in ["show","find","list","search","want"]): return "set_location", 0.7, slots
    if typ and not city and any(w in low for w in ["show","find","list","search","in"]):   return "set_type", 0.7, slots
    if tnr in ("rent","sale") and not (city or typ): return "rent_or_buy", 0.6, slots
    if any(w in low for w in ["show","find","search","apartment","house","land","townhouse","plot"]):
        return "browse_listings", 0.6, slots
    return "fallback", 0.3, slots

# ---------- Conversation & LLM ----------
SYSTEM_PROMPT = """You are RealtyAI, a concise, friendly Sri Lankan real-estate assistant.
- Stick to facts from the DB context when provided.
- If filters are missing, ask exactly ONE clarifying question.
- Prefer showing city, property type, bedrooms, and price in suggestions.
- If no matches, suggest relaxing budget/location or property type, or show a nearby/alternative city with supply.
- Never invent addresses or prices; if unknown, say so briefly.
"""

def ensure_conversation(cnx, session_id: str) -> int:
    row = cnx.execute(
        "SELECT conversation_id FROM conversations WHERE session_id=? AND status='open' ORDER BY started_at DESC LIMIT 1",
        (session_id,)
    ).fetchone()
    if row: return row["conversation_id"]
    cur = cnx.execute("INSERT INTO conversations(session_id, status) VALUES (?, 'open')",(session_id,))
    return cur.lastrowid

def get_history(cnx, conversation_id: int, limit: int = 12):
    rows = cx.execute(  # type: ignore  # (helper only used internally)
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

def log_intent(
    cnx,
    conversation_id: int,
    message_id: int,
    name: str,
    score: float | None,
    user_text: str | None = None,
    slots: dict | None = None,
    reply_type: str | None = None,
    result_count: int | None = None,
    notes: str | None = None,
):
    """Schema-flexible insert into msg_intents."""
    try:
        cols = {r["name"] for r in cnx.execute("PRAGMA table_info(msg_intents)")}
    except sqlite3.OperationalError as e:
        print("log_intent warning: table missing?", e)
        return

    row = {}
    if "conversation_id" in cols: row["conversation_id"] = conversation_id
    if "message_id" in cols:      row["message_id"] = message_id
    if "name" in cols:            row["name"] = name
    if "intent" in cols:          row["intent"] = name

    val = float(score or 0.0)
    if "score" in cols:      row["score"] = val
    if "confidence" in cols: row["confidence"] = val

    if "user_text" in cols:  row["user_text"] = user_text or ""
    if "slots_json" in cols:
        try: row["slots_json"] = json.dumps(slots or {}, ensure_ascii=False)
        except Exception: row["slots_json"] = "{}"
    if "reply_type" in cols:   row["reply_type"] = reply_type
    if "result_count" in cols: row["result_count"] = result_count
    if "notes" in cols:        row["notes"] = notes

    if "session_id" in cols:
        sid_row = cnx.execute("SELECT session_id FROM conversations WHERE conversation_id=?", (conversation_id,)).fetchone()
        row["session_id"] = (sid_row and sid_row["session_id"]) or "unknown"

    if not row: return
    keys = ",".join(row.keys())
    qs   = ",".join(["?"] * len(row))
    try:
        cnx.execute(f"INSERT INTO msg_intents({keys}) VALUES({qs})", tuple(row.values()))
        cnx.commit()
    except Exception as e:
        print("log_intent insert warning:", e)

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
            def fmt_card(c):
                return f"#{c['id']} | {c['title']} | {c['type']} in {c.get('subtitle','')} | LKR {int(c['price_lkr']):,}"
            return "Top listings:\n" + "\n".join(fmt_card(c) for c in cards[:k])
        out = []
        for r in rows:
            out.append(f"#{r['property_id']} | {r['title']} | {r['property_type']} | {r['city']} | "
                       f"{r['bedrooms'] or '-'}BR/{r['bathrooms'] or '-'}BA | LKR {int(r['price_lkr']):,} | {r['snip'] or ''}")
        return "Top listings:\n" + "\n".join(out)
    except sqlite3.OperationalError:
        return ""

def call_llm(history: list, db_context: str) -> str | None:
    if not client:
        return None
    messages = [{"role":"system","content": SYSTEM_PROMPT}]
    if db_context:
        messages.append({"role":"system","content": f"Database context:\n{db_context}"})
    messages.extend(history)
    try:
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            temperature=OPENAI_TEMPERATURE,
            messages=messages
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception:
        return None

# ---------- relaxed search helpers ----------
def search_relaxed(cnx, session, user_text: str, k: int = 6):
    """Return (items, mode, preface). modes: exact, drop_beds, raise_budget, fallback_city_type, alt_city:<C>, none"""
    # 1) exact
    s1 = dict(session)
    rows, _ = search_listings(cnx, s1)
    if rows:
        return rows[:k], "exact", None

    # 2) drop bedrooms
    s2 = {k:v for k,v in s1.items() if k != "beds"}
    rows, _ = search_listings(cnx, s2)
    if rows:
        for it in rows: it["badge"] = it.get("badge") or "Similar"
        return rows[:k], "drop_beds", "No matches at that bedroom count — showing similar options."

    # 3) raise budget 25%
    s3 = dict(s2)
    if "price_max" in s3:
        try:
            s3["price_max"] = int(int(s3["price_max"]) * 1.25)
        except Exception:
            pass
    rows, _ = search_listings(cnx, s3)
    if rows:
        for it in rows: it["badge"] = it.get("badge") or "Similar"
        return rows[:k], "raise_budget", "Nothing in that budget — showing a few just above it."

    # 4) fallback: keep only city+type
    s4 = {"city": session.get("city"), "type": session.get("type")}
    rows, _ = search_listings(cnx, s4)
    if rows:
        for it in rows: it["badge"] = it.get("badge") or "Nearby"
        return rows[:k], "fallback_city_type", "Couldn’t match all filters — here are close matches."

    # 5) alternative city
    alt_city, _ = top_city_alternative(cnx, exclude_city=session.get("city"), ptype=session.get("type"))
    if alt_city:
        s5 = {"city": alt_city, "type": session.get("type")}
        rows, _ = search_listings(cnx, s5)
        if rows:
            for it in rows: it["badge"] = it.get("badge") or "Nearby"
            pre = f"I couldn’t find any in {session.get('city') or 'that area'}. Here are similar options in {alt_city}."
            return rows[:k], f"alt_city:{alt_city}", pre

    return [], "none", None

# ---- schema-safe area→city mapping ----
def map_area_to_city(cnx, area_or_city: str | None):
    if not area_or_city: return None
    try:
        row = cnx.execute(
            "SELECT a.city FROM area_aliases aa JOIN areas a ON a.area_id=aa.area_id WHERE LOWER(aa.alias)=LOWER(?)",
            (area_or_city,)
        ).fetchone()
        if row and "city" in row.keys() and row["city"]:
            return row["city"]
    except Exception:
        pass
    try:
        row = cnx.execute(
            "SELECT city FROM properties WHERE LOWER(city)=LOWER(?) OR LOWER(district)=LOWER(?) LIMIT 1",
            (area_or_city, area_or_city)
        ).fetchone()
        if row and row["city"]:
            return row["city"]
    except Exception:
        pass
    return str(area_or_city).title()

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
        return jsonify({"reply":{"type":"text","content":"Tell me a city or property type to start (e.g., “apartments in Galle under 80M”)."},"session_id":sid})

    session = STORE.get(sid)

    # parse intent/slots
    prev = dict(session)
    intent, conf, slots = parse_intent_slots(text, session)

    has_city = bool(slots.get("city"))
    has_type = bool(slots.get("type"))

    # update then apply "fresh city resets" (drop sticky filters unless user re-stated a type)
    session.update(slots)
    if has_city and not has_type:
        for key in ("type", "beds", "price", "price_min", "price_max"):
            session.pop(key, None)
    # keep city if user changed only type; keep type if user changed only city and also sent type; otherwise reset above.
    STORE.set(sid, session)

    with conn() as cx:
        conversation_id = ensure_conversation(cx, sid)

        # normalize city via alias map
        if session.get("city"):
            session["city"] = map_area_to_city(cx, session["city"])
            STORE.set(sid, session)

        user_mid = save_message(cx, conversation_id, "user", text)

        # Quick replies (no LLM)
        if intent == "greet":
            ans = "Hi! Tell me a city or property type and budget (e.g., “3BR apartments in Galle under 80M”)."
            save_message(cx, conversation_id, "assistant", ans)
            log_intent(cx, conversation_id, user_mid, intent, conf)
            return jsonify({"reply":{"type":"text","content": ans},"session_id":sid,"session":session})

        if intent == "gratitude":
            ans = "You’re welcome! Anything else I can look up for you?"
            save_message(cx, conversation_id, "assistant", ans)
            log_intent(cx, conversation_id, user_mid, intent, conf)
            return jsonify({"reply":{"type":"text","content": ans},"session_id":sid,"session":session})

        if intent == "bot_identity":
            ans = "I’m RealtyAI — your real-estate assistant at RealtyNexus."
            save_message(cx, conversation_id, "assistant", ans)
            log_intent(cx, conversation_id, user_mid, intent, conf)
            return jsonify({"reply":{"type":"text","content": ans},"session_id":sid,"session":session})

        if intent == "bot_creator":
            ans = "This AI agent was designed & developed by Thinukaaa for RealtyNexus. © RealtyNexus — All rights reserved."
            save_message(cx, conversation_id, "assistant", ans)
            log_intent(cx, conversation_id, user_mid, intent, conf)
            return jsonify({"reply":{"type":"text","content": ans},"session_id":sid,"session":session})

        if intent == "capabilities":
            ans = ("I can search apartments, houses, land, and commercial by city, bedrooms, and budget; "
                   "show curated investments; and answer service questions.")
            save_message(cx, conversation_id, "assistant", ans)
            log_intent(cx, conversation_id, user_mid, intent, conf)
            return jsonify({"reply":{"type":"text","content": ans},"session_id":sid,"session":session})

        if intent == "ask_categories":
            content = kb_answer_categories(cx)
            save_message(cx, conversation_id, "assistant", content)
            log_intent(cx, conversation_id, user_mid, intent, conf)
            return jsonify({"reply":{"type":"text","content": content},"session_id":sid,"session":session})

        if intent == "our_services":
            content = ("Services: Legal due diligence, Deed verification, Consultation, Investment advisory, "
                       "Residential & rentals, and Valuations. Tell me what you need and a city, and I’ll guide you.")
            save_message(cx, conversation_id, "assistant", content)
            log_intent(cx, conversation_id, user_mid, intent, conf)
            return jsonify({"reply":{"type":"text","content": content},"session_id":sid,"session":session})

        if intent == "ask_coverage":
            content = ("We currently cover Greater Colombo (Colombo 5, 8, Borella, Dehiwala/Mount Lavinia), "
                       "Galle, Kandy, plus expanding cities like Matara and Jaffna. Try: “apartments in Matara under 60M”.")
            save_message(cx, conversation_id, "assistant", content)
            log_intent(cx, conversation_id, user_mid, intent, conf)
            return jsonify({"reply":{"type":"text","content": content},"session_id":sid,"session":session})

        if intent == "contact_agent":
            content = ("I can connect you with a live agent.\n"
                       "• Call/WhatsApp: +94 11 234 5678\n"
                       "• Or leave your details in the Contact form below — we’ll reach out.")
            save_message(cx, conversation_id, "assistant", content)
            log_intent(cx, conversation_id, user_mid, intent, conf)
            return jsonify({"reply":{"type":"text","content": content},"session_id":sid,"session":session})

        if intent == "reset":
            try:
                cx.execute("UPDATE conversations SET status='closed', ended_at=CURRENT_TIMESTAMP WHERE conversation_id=?", (conversation_id,))
            except Exception:
                pass
            STORE.set(sid, {})
            content = "Cleared. Tell me a city or property type and budget to start."
            save_message(cx, conversation_id, "assistant", content)
            log_intent(cx, conversation_id, user_mid, "reset", 1.0)
            return jsonify({"reply":{"type":"text","content": content},"session_id":sid,"session":{}})

        if intent == "nearest_query":
            results, msg = search_nearest(cx, session)
            if msg:
                payload = {"type":"text","content": msg}
                save_message(cx, conversation_id, "assistant", msg)
                log_intent(cx, conversation_id, user_mid, intent, conf)
            elif not results:
                content = "I didn’t find listings near that area. Try a different area or increase radius."
                payload = {"type":"text","content": content}
                save_message(cx, conversation_id, "assistant", content)
                log_intent(cx, conversation_id, user_mid, intent, conf)
            else:
                payload = {"type":"cards","items": results[:6]}
                save_message(cx, conversation_id, "assistant", f"[cards:{len(results[:6])}]")
                log_intent(cx, conversation_id, user_mid, intent, conf)
            return jsonify({"reply": payload, "session_id": sid, "session": session})

        if intent == "investment_advice":
            items = open_investments(cx)
            if items:
                payload = {"type":"investments","items": items[:6]}
                save_message(cx, conversation_id, "assistant", f"[investments:{len(items[:6])}]")
            else:
                content = "No open investment plans right now."
                payload = {"type":"text","content": content}
                save_message(cx, conversation_id, "assistant", content)
            log_intent(cx, conversation_id, user_mid, intent, conf)
            return jsonify({"reply": payload, "session_id": sid, "session": session})

        if intent in ("set_budget","set_location","set_type","rent_or_buy","browse_listings"):
            results, missing = search_listings(cx, session)
            if missing:
                nice = " and ".join(missing) if len(missing)==2 else ", ".join(missing)
                # deterministic clarifier (no LLM dependency)
                example = "e.g., “apartments in Galle under 80M”" if "city" in nice or "type" in nice else ""
                content = f"Got it. To refine, tell me your {nice}. {example}".strip()
                payload = {"type":"text","content": content}
                save_message(cx, conversation_id, "assistant", content)
                log_intent(cx, conversation_id, user_mid, intent, conf)
            elif not results:
                if RELAX_ON_EMPTY:
                    alt_items, mode, pre = search_relaxed(cx, session, text, k=6)
                    if alt_items:
                        payload = {"type":"cards","items": alt_items}
                        if pre: payload["preface"] = pre
                        save_message(cx, conversation_id, "assistant", f"[cards:{len(alt_items)}]")
                        log_intent(cx, conversation_id, user_mid, intent, conf, notes=f"relaxed:{mode}")
                        return jsonify({"reply": payload, "session_id": sid, "session": session})

                # Fallback: say none; suggest alternative with min price hint if possible
                city = session.get("city"); typ = session.get("type"); beds = session.get("beds")
                hint = ""
                if city and typ:
                    min_price, cnt = cheapest_price_for(cx, city, typ, session.get("tenure"), session.get("beds"))
                    if isinstance(min_price, (int,float)) and min_price and cnt:
                        hint = f" The lowest for {typ}{' (≥'+str(beds)+'BR)' if beds else ''} in {city} is around LKR {int(min_price):,}."
                # alternative city suggestion if nothing in requested city
                alt_city, alt_cnt = (None, 0)
                if city and typ:
                    alt_city, alt_cnt = top_city_alternative(cx, city, typ)
                if alt_city and alt_cnt:
                    content = (f"I couldn't find any {typ} in {city}. {hint} "
                               f"Would you like to see options in {alt_city} instead?")
                else:
                    content = "No matches yet. Try increasing budget or changing filters." + hint
                payload = {"type":"text","content": content}
                save_message(cx, conversation_id, "assistant", content)
                log_intent(cx, conversation_id, user_mid, intent, conf, notes="no_results_with_filters")
            else:
                payload = {"type":"cards","items": results[:6]}
                save_message(cx, conversation_id, "assistant", f"[cards:{len(results[:6])}]")
                log_intent(cx, conversation_id, user_mid, intent, conf, result_count=len(results))
            return jsonify({"reply": payload, "session_id": sid, "session": session})

        # --- FINAL FALLBACK → LLM with DB context (optional) ---
        hist = [{"role":"user","content": text}]
        db_ctx = build_db_context(cx, session, text, k=5)
        ai_text = call_llm(hist, db_ctx)
        if not ai_text:
            ai_text = ("I can help with apartments, houses, land, and commercial in Colombo, Galle, Kandy and more. "
                       "Try: “3BR apartments in Matara under 60M”.")
        save_message(cx, conversation_id, "assistant", ai_text, OPENAI_MODEL if client else None)
        log_intent(cx, conversation_id, user_mid, "fallback", conf)
        return jsonify({"reply": {"type":"text","content": ai_text}, "session_id": sid, "session": session})

@app.get("/health")
def health():
    try:
        with conn() as cx:
            cx.execute("SELECT 1").fetchone()
        db_ok = True
    except Exception:
        db_ok = False
    return jsonify({
        "ok": True,
        "db": db_ok,
        "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        "llm_enabled": bool(client)
    })

@app.post("/api/contact")
def api_contact():
    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip().lower() or None
    phone = (request.form.get("phone") or "").strip() or None
    msg   = (request.form.get("message") or "").strip()

    if not (name and email and msg):
        return jsonify({"ok": False, "error": "missing_fields"}), 400

    with conn() as cx:
        lead_id = None
        try:
            cur = cx.execute(
                """INSERT INTO leads(name,email,phone,source,intent,stage,note)
                   VALUES (?,?,?,?, 'general','new',?)""",
                (name, email, phone, 'web_form', msg)
            )
            lead_id = cur.lastrowid
        except sqlite3.IntegrityError:
            row = cx.execute(
                "SELECT lead_id, note FROM leads WHERE (email=? AND email IS NOT NULL) OR (phone=? AND phone IS NOT NULL) "
                "ORDER BY created_at DESC LIMIT 1",
                (email or "", phone or "")
            ).fetchone()
            if row:
                lead_id = row["lead_id"]
                cx.execute(
                    "UPDATE leads SET note = COALESCE(note,'') || char(10) || ?, updated_at=CURRENT_TIMESTAMP WHERE lead_id=?",
                    (f"[web_form] {msg}", lead_id)
                )

        conv_id = cx.execute(
            "INSERT INTO conversations(lead_id, source, session_id, status) VALUES (?,?,?, 'open')",
            (lead_id, 'web_form', None)
        ).lastrowid
        cx.execute(
            "INSERT INTO messages(conversation_id, role, content) VALUES (?,?,?)",
            (conv_id, 'user', f"Contact form from {name} <{email or '-'}>:\n{msg}")
        )

    return jsonify({"ok": True})

if __name__ == "__main__":
    port = int(os.getenv("PORT","5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
