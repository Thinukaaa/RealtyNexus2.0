# db.py
import sqlite3, pathlib, typing as t, re, json, datetime as dt

BASE_DIR = pathlib.Path(__file__).resolve().parent
DB_FILE  = BASE_DIR / "db" / "realty.db"

def dict_factory(cursor, row):
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}

def get_conn() -> sqlite3.Connection:
    con = sqlite3.connect(DB_FILE)
    con.row_factory = dict_factory
    con.execute("PRAGMA foreign_keys=ON")
    return con

_STOP = {
    "the","a","an","and","or","to","in","on","for","with","of","is","are","am",
    "do","does","did","you","your","we","us","our","what","which","who","whom",
    "have","has","had","me","i","please","show","list","give","properties","property","homes","house","apartments"
}

def _basic_tokens(q: str|None) -> list[str]:
    if not q: return []
    return re.findall(r"[0-9A-Za-z]+", q.lower())

def _fts_query_from_tokens(tokens: list[str]) -> str|None:
    tokens = [t for t in tokens if t and t not in _STOP]
    if not tokens: return None
    tokens = tokens[:8]
    return " OR ".join(t+"*" for t in tokens)

def _augment_tokens_with_synonyms(q: str, tokens: list[str], con: sqlite3.Connection) -> list[str]:
    txt = (q or "").lower()
    rows = con.execute("SELECT kind, canonical, alias FROM synonyms").fetchall()
    extra: list[str] = []
    for r in rows:
        alias = (r["alias"] or "").lower()
        if not alias: continue
        if alias in txt:
            canon_words = re.findall(r"[0-9A-Za-z]+", (r["canonical"] or "").lower())
            extra.extend(canon_words)
    all_tokens = list(dict.fromkeys(tokens + extra))
    return all_tokens

def upsert_lead(name: str|None, email: str|None, phone: str|None, intent: str|None, note: str|None) -> int:
    with get_conn() as con:
        cur = con.cursor()
        lead = None
        if email:
            lead = cur.execute("SELECT lead_id FROM leads WHERE email = ?", (email,)).fetchone()
        if not lead and phone:
            lead = cur.execute("SELECT lead_id FROM leads WHERE phone = ?", (phone,)).fetchone()
        if lead:
            lid = lead["lead_id"]
            cur.execute("""
              UPDATE leads
                 SET name=COALESCE(?,name),
                     intent=COALESCE(?,intent),
                     note=COALESCE(?,note),
                     updated_at=CURRENT_TIMESTAMP
               WHERE lead_id=?
            """, (name, intent, note, lid))
            return lid
        cur.execute("""
          INSERT INTO leads (name,email,phone,intent,note) VALUES (?,?,?,?,?)
        """, (name, email, phone, intent, note))
        return cur.lastrowid

def ensure_conversation(session_id: str, lead_id: int|None=None) -> int:
    with get_conn() as con:
        cur = con.cursor()
        row = cur.execute("""
          SELECT conversation_id
            FROM conversations
           WHERE session_id=? AND status='open'
        ORDER BY started_at DESC LIMIT 1
        """, (session_id,)).fetchone()
        if row:
            return row["conversation_id"]
        cur.execute("""
          INSERT INTO conversations (lead_id, source, session_id, status)
          VALUES (?,?,?, 'open')
        """, (lead_id, "chat_widget", session_id))
        return cur.lastrowid

def log_message(conversation_id: int, role: str, content: str, model: str|None=None, tokens: int|None=None, error: str|None=None) -> int:
    with get_conn() as con:
        cur = con.cursor()
        cur.execute("""
          INSERT INTO messages (conversation_id, role, content, model, tokens, error)
          VALUES (?,?,?,?,?,?)
        """, (conversation_id, role, content, model, tokens, error))
        return cur.lastrowid

def featured_properties(limit: int = 3) -> list[dict]:
    with get_conn() as con:
        return con.execute("""
          SELECT property_id, title, city, price_lkr, property_type
            FROM properties
           WHERE status='available'
        ORDER BY featured DESC, created_at DESC
           LIMIT ?
        """, (limit,)).fetchall()

def refresh_featured_summary() -> str:
    items = featured_properties(limit=3)
    if not items:
        text = "We currently have a rotating catalog of apartments, houses, and land across Colombo, Galle, and Kandy. Ask for areas or budget to get matches."
    else:
        bullets = []
        for p in items:
            city = p.get("city") or ""
            price = p.get("price_lkr")
            price_str = f"LKR {price:,}" if price else "POA"
            bullets.append(f"- {p.get('title')} — {city} — {price_str}")
        text = "Top featured properties right now:\n" + "\n".join(bullets)

    meta = json.dumps({"generated_at": dt.datetime.utcnow().isoformat() + "Z"})
    with get_conn() as con:
        cur = con.cursor()
        cur.execute("DELETE FROM kb_chunks WHERE source='featured_rollup'")
        cur.execute(
            "INSERT INTO kb_chunks (source, text, meta) VALUES ('featured_rollup', ?, ?)",
            (text, meta),
        )
    return text

def search_properties_fts(q: str, city: str|None=None, max_price: int|None=None, limit: int=10) -> list[dict]:
    with get_conn() as con:
        tokens = re.findall(r"[0-9A-Za-z]+", (q or "").lower())
        tokens = _augment_tokens_with_synonyms(q, tokens, con)
        fts_q = _fts_query_from_tokens(tokens)
        params: list[t.Any] = []
        if fts_q:
            sql = """
              SELECT p.*
                FROM property_fts f
                JOIN properties p ON p.property_id = f.rowid
               WHERE property_fts MATCH ?
            """
            params.append(fts_q)
        else:
            sql = "SELECT p.* FROM properties p WHERE 1=1"
        if city:
            sql += " AND p.city = ?"
            params.append(city)
        if max_price is not None:
            sql += " AND p.price_lkr <= ?"
            params.append(max_price)
        sql += " ORDER BY p.featured DESC, p.created_at DESC LIMIT ?"
        params.append(limit)
        try:
            return con.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            return con.execute(
                "SELECT * FROM properties WHERE status='available' ORDER BY featured DESC, created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()

def list_open_investments(limit: int=10) -> list[dict]:
    with get_conn() as con:
        return con.execute("SELECT * FROM v_open_investments LIMIT ?", (limit,)).fetchall()

def search_kb(q: str, limit: int=5) -> list[dict]:
    with get_conn() as con:
        tokens = re.findall(r"[0-9A-Za-z]+", (q or "").lower())
        tokens = _augment_tokens_with_synonyms(q, tokens, con)
        fts_q = _fts_query_from_tokens(tokens)
        if not fts_q:
            return con.execute("""
              SELECT text, source, chunk_id
                FROM kb_chunks
            ORDER BY created_at DESC LIMIT ?
            """, (limit,)).fetchall()
        try:
            return con.execute("""
              SELECT text, source, rowid AS chunk_id
                FROM kb_fts
               WHERE kb_fts MATCH ?
               LIMIT ?
            """, (fts_q, limit)).fetchall()
        except sqlite3.OperationalError:
            return con.execute("""
              SELECT text, source, chunk_id
                FROM kb_chunks
            ORDER BY created_at DESC LIMIT ?
            """, (limit,)).fetchall()

# ---- NEW: blend FTS with structured filters ----
def search_properties(q: str, slots: dict, limit: int = 10) -> list[dict]:
    """Use FTS + structured filters from slots (city/type/beds/price/purpose)."""
    candidates = search_properties_fts(q, city=slots.get("city"), max_price=slots.get("price_max"), limit=limit*3)
    res: list[dict] = []
    for r in candidates:
        if slots.get("purpose") and r.get("purpose") != slots["purpose"]:
            continue
        if slots.get("type") and r.get("property_type") != slots["type"]:
            continue
        if slots.get("beds") and (r.get("bedrooms") or 0) < int(slots["beds"]):
            continue
        if slots.get("baths") and (r.get("bathrooms") or 0) < int(slots["baths"]):
            continue
        if slots.get("price_min") and r.get("price_lkr") and r["price_lkr"] < int(slots["price_min"]):
            continue
        res.append(r)
    return res[:limit] if res else candidates[:limit]

# ---- Conversation state helpers ----
import json as _json

def get_state(conversation_id: int) -> dict:
    with get_conn() as con:
        row = con.execute("SELECT pending_field, slots_json FROM conversation_state WHERE conversation_id=?",
                          (conversation_id,)).fetchone()
        if not row:
            return {"pending_field": None, "slots": {}}
        slots = {}
        try:
            slots = _json.loads(row.get("slots_json") or "{}")
        except Exception:
            slots = {}
        return {"pending_field": row.get("pending_field"), "slots": slots}

def set_state(conversation_id: int, pending_field: str|None, slots: dict) -> None:
    data = _json.dumps(slots or {})
    with get_conn() as con:
        cur = con.cursor()
        cur.execute("""
          INSERT INTO conversation_state (conversation_id, pending_field, slots_json)
          VALUES (?,?,?)
          ON CONFLICT(conversation_id) DO UPDATE SET
            pending_field=excluded.pending_field,
            slots_json=excluded.slots_json,
            updated_at=CURRENT_TIMESTAMP
        """, (conversation_id, pending_field, data))

def clear_state(conversation_id: int) -> None:
    with get_conn() as con:
        con.execute("DELETE FROM conversation_state WHERE conversation_id=?", (conversation_id,))

def get_primary_image(property_id: int|None) -> str|None:
    if not property_id:
        return None
    with get_conn() as con:
        row = con.execute("""
          SELECT url
            FROM property_media
           WHERE property_id=?
        ORDER BY COALESCE(sort_order, 9999) ASC, media_id ASC
           LIMIT 1
        """, (property_id,)).fetchone()
        return row["url"] if row else None
