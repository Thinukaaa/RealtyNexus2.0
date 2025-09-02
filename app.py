import os, re, sqlite3, secrets, json
from flask import Flask, request, jsonify, render_template, send_from_directory

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.getenv("REALTY_DB", os.path.join(APP_DIR, "db", "realty.db"))

app = Flask(__name__, static_folder="static", template_folder="templates")

# ---------- ensure schema for logging ----------
def ensure_logging_schema(cnx):
    cnx.execute("""
      CREATE TABLE IF NOT EXISTS msg_intents_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT,
        turn_index INTEGER,
        user_text TEXT,
        intent TEXT,
        slots_json TEXT,
        reply_type TEXT,
        created_at TEXT DEFAULT (datetime('now'))
      )
    """)
    cnx.commit()

def log_intent(cnx, session_id:str, turn_index:int, user_text:str, intent:str, slots:dict, reply_type:str):
    ensure_logging_schema(cnx)
    cnx.execute(
        "INSERT INTO msg_intents_log (session_id, turn_index, user_text, intent, slots_json, reply_type) VALUES (?,?,?,?,?,?)",
        (session_id, turn_index, user_text, intent, json.dumps(slots, ensure_ascii=False), reply_type)
    )
    cnx.commit()

# ---------- helpers: cheapest viable budget suggestion ----------
def cheapest_price_for(cnx, city: str, ptype: str, tenure: str | None = None):
    params, where = [city, city, ptype], ["(city = ? OR district = ?)", "property_type = ?"]
    if tenure in ("rent","sale"):
        where.append("purpose = ?"); params.append(tenure)
    sql = f"""
      SELECT MIN(price_lkr) AS min_price, COUNT(*) AS cnt
      FROM properties
      WHERE status='available' AND {' AND '.join(where)}
    """
    row = cnx.execute(sql, params).fetchone()
    if not row: return None, 0
    return row["min_price"], row["cnt"]

# ---------- tiny session store ----------
class SessionStore(dict):
    def new(self):
        sid = secrets.token_hex(8)
        self[sid] = {"turn_index": 0}
        return sid
    def get(self, sid, default=None):
        return super().get(sid, default or {"turn_index": 0})
    def set(self, sid, val): self[sid] = val

STORE = SessionStore()

# ---------- DB ----------
def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

# ---------- utils ----------
def parse_budget_value(text: str):
    low = text.lower().replace(",", "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)(\s*(m|mn|million))?", low)
    if m:
        a, b = float(m.group(1)), float(m.group(2)); mul = 1_000_000 if m.group(4) else 1
        return {"price_min": int(a*mul), "price_max": int(b*mul)}
    m = re.search(r"(?:under|below|max(?:imum)?)\s+(\d+(?:\.\d+)?)(\s*(m|mn|million))?", low)
    if m:
        v = float(m.group(1)); 
        if m.group(3): v *= 1_000_000
        return {"price_max": int(v)}
    m = re.search(r"(?:over|min(?:imum)?)\s+(\d+(?:\.\d+)?)(\s*(m|mn|million))?", low)
    if m:
        v = float(m.group(1)); 
        if m.group(3): v *= 1_000_000
        return {"price_min": int(v)}
    m = re.search(r"\b(\d{2,})(\s*(m|mn|million))?\b", low)
    if m:
        v = float(m.group(1)); 
        if m.group(3): v *= 1_000_000
        return {"price_max": int(v)}
    return None

CANON_TYPES = {
    "apartment": {"apt","apartment","condo","flat","flats"},
    "house": {"house","home","villa","villas"},
    "townhouse": {"townhouse","town house"},
    "land": {"land","plot","plots"},
    "commercial": {"commercial","building","office","shop","offices","shops","buildings"},
}
CANON_CITIES = {"colombo","colombo 5","galle","kandy","mount lavinia","dehiwala"}

def detect_type(t):
    low = t.lower()
    for canon, aliases in CANON_TYPES.items():
        for a in aliases:
            if re.search(rf"\b{re.escape(a)}(es|s)?\b", low):
                return canon
    return None

def detect_city(t):
    low = t.lower()
    for c in sorted(CANON_CITIES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(c)}\b", low): return c.title()
    m = re.search(r"\b(borella|galle fort|mt\.?\s?lavinia|mount lavinia|dehiwala|colombo\s?\d)\b", low)
    if m: return m.group(1).replace("mt","mount").title()
    return None

def detect_beds(t):
    m = re.search(r"\b(\d+)\s*br\b", t.lower()) or re.search(r"\b(\d+)\s*bed", t.lower())
    return int(m.group(1)) if m else None

def detect_tenure(t):
    low = t.lower()
    if any(w in low for w in ["rent","rental","lease"]): return "rent"
    if any(w in low for w in ["buy","sale","sell"]): return "sale"
    return None

def parse_intent_slots(text, session):
    low = text.lower()
    if re.search(r"\b(reset|start over|clear|new search)\b", low):
        return "reset_session", {}

    slots = {}
    city = detect_city(text);  typ = detect_type(text);  beds = detect_beds(text)
    if city: slots["city"] = city
    if typ:  slots["type"] = typ
    if beds: slots["beds"] = beds
    b = parse_budget_value(text)
    if b: slots.update(b)
    tnr = detect_tenure(text)
    if tnr: slots["tenure"] = tnr

    if re.search(r"\b(hi|hello|hey)\b", low): intent = "greet"
    elif any(p in low for p in ["what type","what types","what properties","categories"]): intent = "ask_categories"
    elif "nearest" in low or re.search(r"\bnear\b", low): intent = "nearest_query"
    elif "investment" in low: intent = "investment_advice"
    elif b: intent = "set_budget"
    elif city and not typ and any(w in low for w in ["show","find","list","search"]): intent = "set_location"
    elif typ and not city and any(w in low for w in ["show","find","list","search"]): intent = "set_type"
    elif tnr in ("rent","sale") and not (city or typ): intent = "rent_or_buy"
    elif any(w in low for w in ["show","find","search","apartment","house","land","townhouse","plot"]): intent = "browse_listings"
    else: intent = "fallback"
    return intent, slots

def missing_for_search(session):
    need = []
    if not session.get("city"): need.append("city")
    if not session.get("type"): need.append("property type")
    return need

def list_cards(rows):
    out = []
    for r in rows:
        subtitle = f"{r.get('bedrooms') or '-'} BR · {r.get('bathrooms') or '-'} Bath · {r.get('city') or ''}".strip()
        out.append({
            "id": r["property_id"], "title": r["title"], "subtitle": subtitle,
            "price_lkr": r["price_lkr"], "type": r["property_type"],
            "badge": "Featured" if r.get("featured") else None,
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

# --- helper: does table have a column? ---
def _table_has_column(cnx, table: str, column: str) -> bool:
    try:
        cols = [r["name"] for r in cnx.execute(f"PRAGMA table_info({table})")]
        return column in cols
    except sqlite3.Error:
        return False

def map_area_to_city(cnx, area_or_city: str | None):
    """Resolve an area/alias (e.g., 'Borella') to a displayable city.
       Works across varying schemas: properties, area_aliases, areas."""
    if not area_or_city:
        return None
    low = area_or_city.strip().lower()

    # 1) If it's already a city/district in properties, use that
    row = cnx.execute(
        """
        SELECT city
        FROM properties
        WHERE (LOWER(city) = ? OR LOWER(district) = ?)
        LIMIT 1
        """,
        (low, low),
    ).fetchone()
    if row and row["city"]:
        return row["city"].title()

    # 2) Try area_aliases / areas, but adapt to available columns
    has_aliases = False
    has_areas = False
    try:
        cnx.execute("SELECT 1 FROM area_aliases LIMIT 1")
        has_aliases = True
    except sqlite3.Error:
        pass
    try:
        cnx.execute("SELECT 1 FROM areas LIMIT 1")
        has_areas = True
    except sqlite3.Error:
        pass

    if has_aliases:
        # Pick a viable "city-ish" column
        # Prefer areas.city, then areas.name, then area_aliases.city
        if has_areas and _table_has_column(cnx, "areas", "city"):
            city_expr = "a.city"
        elif has_areas and _table_has_column(cnx, "areas", "name"):
            city_expr = "a.name"
        elif _table_has_column(cnx, "area_aliases", "city"):
            city_expr = "aa.city"
        else:
            city_expr = None

        if city_expr:
            try:
                if has_areas:
                    row = cnx.execute(
                        f"""
                        SELECT {city_expr} AS city
                        FROM area_aliases aa
                        LEFT JOIN areas a ON a.area_id = aa.area_id
                        WHERE LOWER(aa.alias) = ?
                        LIMIT 1
                        """,
                        (low,),
                    ).fetchone()
                else:
                    row = cnx.execute(
                        f"""
                        SELECT {city_expr} AS city
                        FROM area_aliases aa
                        WHERE LOWER(aa.alias) = ?
                        LIMIT 1
                        """,
                        (low,),
                    ).fetchone()
                if row and row["city"]:
                    return str(row["city"]).title()
            except sqlite3.Error:
                # ignore and fall through
                pass

    # 3) Heuristics (common Sri Lanka patterns)
    if "borella" in low:
        return "Colombo"
    m = re.search(r"(colombo\s*\d+)", low)
    if m:
        return m.group(1).title()

    # 4) Last resort: title-case the input
    return area_or_city.title()


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
            "title": d["plan_name"],
            "badge": (d["category"] or "").replace("_"," ").title(),
            "subtitle": d.get("city") or "-",
            "min_investment_lkr": d["min_investment_lkr"],
            "summary": d["summary"],
            "yield_pct": d["expected_yield_pct"],
            "roi_pct": d["expected_roi_pct"],
        })
    return items

def kb_answer_categories(cnx):
    return ("We support apartments, houses, townhouses, land, and commercial (rent and sale). "
            "Search by city (Colombo, Galle, Kandy), budget, bedrooms, and features. "
            "Example: “3BR apartments in Galle under 80M”.")

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
    intent, slots = parse_intent_slots(text, session)

    # reset before merge
    if intent == "reset_session":
        STORE.set(sid, {"turn_index": 0})
        with conn() as cx:
            log_intent(cx, sid, 0, text, intent, {}, "text")
        return jsonify({"reply":{"type":"text","content":"Cleared. Tell me a city, property type, and budget to start."},
                        "session_id":sid, "session": {"turn_index": 0}})

    # merge slots & increment turn
    session.update(slots)
    session["turn_index"] = int(session.get("turn_index") or 0) + 1
    STORE.set(sid, session)

    with conn() as cx:
        # Normalize area → city when possible
        if session.get("city"):
            session["city"] = map_area_to_city(cx, session["city"])

        # route
        if intent == "ask_categories":
            payload = {"type":"text","content": kb_answer_categories(cx)}

        elif intent in ("set_budget","set_location","set_type","rent_or_buy"):
            results, missing = search_listings(cx, session)
            if missing:
                payload = {"type":"text","content": f"Got it. To refine, tell me your {', '.join(missing)}."}
            elif not results:
                if session.get("city") and session.get("type"):
                    mprice, cnt = cheapest_price_for(cx, session["city"], session["type"], session.get("tenure"))
                    payload = {"type":"text","content":
                               f"No matches at that budget. The lowest for {session['type']} in {session['city']} is around LKR {mprice:,}."
                               if mprice else "No matches yet. Try increasing budget or changing city/type."}
                else:
                    payload = {"type":"text","content":"No matches yet. Try increasing budget or changing city/type."}
            else:
                payload = {"type":"cards","items": results[:6]}

        elif intent == "nearest_query":
            results, msg = search_nearest(cx, session)
            if msg: payload = {"type":"text","content": msg}
            elif not results: payload = {"type":"text","content":"I didn’t find listings near that area. Try a different area or increase radius."}
            else: payload = {"type":"cards","items": results[:6]}

        elif intent == "investment_advice":
            items = open_investments(cx)
            payload = {"type":"investments","items": items[:6]} if items else {"type":"text","content":"No open investment plans right now."}

        elif intent == "browse_listings":
            results, missing = search_listings(cx, session)
            if missing:
                payload = {"type":"text","content": f"To search, tell me your {', '.join(missing)} (e.g., ‘apartments in Galle under 80M’)."} 
            elif not results:
                if session.get("city") and session.get("type"):
                    mprice, cnt = cheapest_price_for(cx, session["city"], session["type"], session.get("tenure"))
                    payload = {"type":"text","content":
                               f"No matches with those filters. Lowest {session['type']} in {session['city']} is ~LKR {mprice:,}."
                               if mprice else "No matches with those filters. Try adjusting budget/beds/type."}
                else:
                    payload = {"type":"text","content":"No matches with those filters. Try adjusting budget/beds/type."}
            else:
                payload = {"type":"cards","items": results[:6]}

        else:
            payload = {"type":"text","content":"I can filter by city (Colombo, Galle, Kandy), type (apartment/house), and budget. Try: “3BR apartments in Galle under 80M”. What should I search?"}

        # log intent
        log_intent(cx, sid, session["turn_index"], text, intent, slots, payload.get("type","text"))

    return jsonify({"reply": payload, "session_id": sid, "session": session})

if __name__ == "__main__":
    port = int(os.getenv("PORT","5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
