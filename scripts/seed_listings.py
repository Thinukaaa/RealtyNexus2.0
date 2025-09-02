# scripts/seed_listings.py
import argparse
import os
import random
import sqlite3
from datetime import datetime, timedelta, timezone

DB_PATH = os.getenv("REALTY_DB", os.path.join("db", "realty.db"))

CITIES = [
    ("Colombo 5", "Colombo", 1.45, 12.0),
    ("Colombo 7", "Colombo", 1.65, 16.0),
    ("Nugegoda", "Colombo", 1.10, 9.0),
    ("Rajagiriya", "Colombo", 1.20, 10.0),
    ("Malabe", "Colombo", 0.95, 6.5),
    ("Dehiwala", "Colombo", 1.00, 7.5),
    ("Mount Lavinia", "Colombo", 1.05, 8.5),
    ("Negombo", "Gampaha", 0.80, 5.5),
    ("Galle", "Galle", 0.85, 6.0),
    ("Kandy", "Kandy", 0.75, 4.5),
]

TYPE_WEIGHTS = [
    ("apartment", 0.45),
    ("house", 0.30),
    ("land", 0.15),
    ("townhouse", 0.05),
    ("commercial", 0.05),
]

TYPE_IMAGE = {
    "apartment": "/static/img/apartment.jpg",
    "house": "/static/img/house.jpg",
    "land": "/static/img/land.jpg",
    "townhouse": "/static/img/townhouse.jpg",
    "commercial": "/static/img/commercial.jpg",
}

AREA_ALIASES = {
    "Colombo 5": ["CMB 05", "Havelock Town", "CMB5"],
    "Colombo 7": ["Cinnamon Gardens", "CMB 07", "CMB7"],
    "Nugegoda": ["Nawala nearby", "Wijerama"],
    "Rajagiriya": ["Cotta Rd", "Koswatte"],
    "Malabe": ["Thalahena", "Kaduwela road"],
    "Dehiwala": ["Dehiwala-Mount Lavinia", "Zoological area"],
    "Mount Lavinia": ["Mt Lavinia", "Hotel Rd area"],
    "Negombo": ["Sea St", "Katunayake area"],
    "Galle": ["Galle Fort", "Peddler St"],
    "Kandy": ["Peradeniya", "Katugastota"],
}

TYPE_SYNONYMS = {
    "apartment": ["flat", "condo"],
    "house": ["home", "villa"],
    "land": ["plot", "bare land"],
    "townhouse": ["row house"],
    "commercial": ["office", "retail", "shop"],
}

# valid property statuses (matches your CHECK constraint)
STATUS_CHOICES = (
    ("available", 0.85),
    ("pending",   0.05),
    ("reserved",  0.03),
    ("sold",      0.04),
    ("rented",    0.02),
    ("offmarket", 0.01),
)

# allowed categories per your investments.category CHECK
ALLOWED_CATEGORIES = {"off_plan","land_bank","reit","flip","rental_yield","development","other"}

# ---------- small utils ----------
def choice_weighted(pairs):
    r = random.random()
    upto = 0.0
    for name, w in pairs:
        upto += w
        if r <= upto:
            return name
    return pairs[-1][0]

def get_table_info(con, table):
    try:
        rows = con.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.OperationalError:
        return []
    # cid, name, type, notnull, dflt_value, pk
    return [{"name": r[1], "type": (r[2] or "").upper(), "notnull": bool(r[3]), "dflt": r[4], "pk": bool(r[5])} for r in rows]

def table_cols(con, table):
    return [r["name"] for r in get_table_info(con, table)]

def first_present(cols, candidates):
    for c in candidates:
        if c in cols:
            return c
    return None

def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

# ---------- ensure tables ----------
def ensure_extra_tables(con):
    con.execute("""
      CREATE TABLE IF NOT EXISTS area_aliases(
        city TEXT NOT NULL,
        alias TEXT NOT NULL,
        UNIQUE(city, alias)
      );
    """)
    con.execute("""
      CREATE TABLE IF NOT EXISTS type_synonyms(
        canonical TEXT NOT NULL,
        alias TEXT NOT NULL,
        UNIQUE(canonical, alias)
      );
    """)

    # Indexes for properties (ignore if table doesn't exist yet)
    try: con.execute("CREATE INDEX IF NOT EXISTS idx_properties_city ON properties(city);")
    except Exception: pass
    try: con.execute("CREATE INDEX IF NOT EXISTS idx_properties_type ON properties(property_type);")
    except Exception: pass
    try: con.execute("CREATE INDEX IF NOT EXISTS idx_properties_price ON properties(price_lkr);")
    except Exception: pass

    # property_media if missing
    con.execute("""
      CREATE TABLE IF NOT EXISTS property_media(
        media_id INTEGER PRIMARY KEY,
        property_id INTEGER NOT NULL,
        url TEXT NOT NULL,
        kind TEXT DEFAULT 'image',
        is_primary INTEGER DEFAULT 0,
        FOREIGN KEY(property_id) REFERENCES properties(property_id)
      );
    """)

def seed_aliases(con):
    for city, aliases in AREA_ALIASES.items():
        for a in aliases:
            con.execute("INSERT OR IGNORE INTO area_aliases(city, alias) VALUES (?,?)", (city, a))
    for canon, aliases in TYPE_SYNONYMS.items():
        for a in aliases:
            con.execute("INSERT OR IGNORE INTO type_synonyms(canonical, alias) VALUES (?,?)", (canon, a))

# ---------- row builders ----------
def insert_row(con, table, data):
    cols = table_cols(con, table)
    use = {k: v for k, v in data.items() if k in cols}
    if not use:
        raise RuntimeError(f"No matching columns when inserting into {table}")
    q = f"INSERT INTO {table} ({','.join(use.keys())}) VALUES ({','.join(['?']*len(use))})"
    cur = con.execute(q, tuple(use.values()))
    return cur.lastrowid

def gen_title(city, ptype, beds, baths):
    t = ptype.capitalize()
    if ptype == "land":
        return f"Land in {city}"
    if ptype == "commercial":
        label = random.choice(["Office", "Retail Unit", "Shop Lot"])
        return f"{label} in {city}"
    bits = []
    if beds:  bits.append(f"{beds} bed")
    if baths: bits.append(f"{baths} bath")
    meta = ", ".join(bits) if bits else ""
    return f"{t} in {city} {meta}".strip()

def price_lkr_for(city_meta, ptype, beds, land_m):
    mult = city_meta[2]
    if ptype == "apartment":
        base = random.uniform(40, 140) * mult
        if beds: base *= (0.8 + 0.25 * beds)
        return int(base * 1_000_000)
    if ptype in ("house", "townhouse"):
        base = random.uniform(35, 160) * mult
        if beds: base *= (0.85 + 0.20 * beds)
        return int(base * 1_000_000)
    if ptype == "commercial":
        base = random.uniform(60, 220) * mult
        return int(base * 1_000_000)
    price_m = land_m * random.uniform(0.7, 1.4) * city_meta[3]
    return int(price_m * 1_000_000)

# ---------- seeds ----------
def seed_properties(con, n=500):
    pcols = table_cols(con, "properties")
    if not pcols:
        raise RuntimeError("Table 'properties' not found. Make sure your schema is applied.")

    have_desc    = "description" in pcols
    have_created = "created_at" in pcols
    have_status  = "status" in pcols

    ids = []

    for _ in range(n):
        city_meta = random.choice(CITIES)
        city = city_meta[0]
        ptype = choice_weighted(TYPE_WEIGHTS)

        beds = baths = land_perch = None
        if ptype in ("apartment", "house", "townhouse"):
            beds = random.randint(1, 5 if ptype == "apartment" else 6)
            baths = max(1, min(beds or 1, random.randint(1, 4)))
        elif ptype == "commercial":
            baths = random.choice([None, 1, 2])
        else:
            land_perch = random.randint(6, 40)

        title = gen_title(city, ptype, beds, baths)
        price = price_lkr_for(city_meta, ptype, beds, land_perch or 10)
        summary = f"{ptype.capitalize()} opportunity in {city}. Excellent access and neighborhood amenities."

        row = {
            "title": title,
            "city": city,
            "property_type": ptype,
            "bedrooms": beds,
            "bathrooms": baths,
            "price_lkr": price,
        }
        if have_desc:
            row["description"] = summary
        if have_status:
            row["status"] = choice_weighted(STATUS_CHOICES)
        if have_created:
            row["created_at"] = (datetime.now(timezone.utc) - timedelta(days=random.randint(0, 180))).isoformat(timespec="seconds")

        pid = insert_row(con, "properties", row)
        ids.append((pid, ptype))

        # primary image placeholder
        try:
            insert_row(con, "property_media", {
                "property_id": pid,
                "url": TYPE_IMAGE.get(ptype, "/static/img/listing.jpg"),
                "is_primary": 1,
                "kind": "image",
            })
        except Exception:
            pass

    # Rebuild FTS if present
    try:
        con.execute("INSERT INTO property_fts(property_fts) VALUES ('rebuild');")
    except Exception:
        pass

    return ids

def default_for_col(col_name, col_type, plan):
    n = col_name.lower()
    t = (col_type or "TEXT").upper()

    # semantic defaults
    if "category" in n:
        # must respect CHECK constraint; choose safe default
        return plan.get("category") or "other"
    if n in ("status", "plan_status"):
        return plan.get("status") or "open"
    if "currency" in n:
        return "LKR"
    if "country" in n or "region" in n:
        return "Sri Lanka"
    if n in ("name", "plan_name", "title", "plan_title"):
        return plan.get("name")
    if "summary" in n or "description" in n or "notes" in n:
        return plan.get("summary") or (plan.get("name") + " plan")
    if ("min" in n and ("ticket" in n or "amount" in n or "investment" in n)) or n == "min_ticket_lkr":
        return plan.get("min_ticket_lkr") or 0
    if "irr" in n or "roi" in n:
        return plan.get("target_irr") or 0.0
    if n.endswith("_at") or "date" in n:
        return now_iso()
    if n.startswith("is_") or "active" in n:
        return 1
    if "code" in n or "id_code" in n:
        return "PLN-" + str(random.randint(1000, 9999))

    # type-based fallbacks
    if t.startswith("INT"):
        return 0
    if t in ("REAL", "NUMERIC", "FLOAT", "DOUBLE"):
        return 0.0
    return plan.get("name", "")

def seed_investments(con, property_ids):
    # Ensure minimal table exists if not present (your DB may already have a stricter one with CHECK on category)
    con.execute("""
      CREATE TABLE IF NOT EXISTS investments(
        investment_id INTEGER PRIMARY KEY,
        plan_name TEXT,
        status TEXT,
        min_ticket_lkr INTEGER,
        target_irr REAL,
        summary TEXT,
        category TEXT
      );
    """)
    con.execute("""
      CREATE TABLE IF NOT EXISTS investment_properties(
        investment_id INTEGER NOT NULL,
        property_id INTEGER NOT NULL,
        PRIMARY KEY(investment_id, property_id),
        FOREIGN KEY(investment_id) REFERENCES investments(investment_id),
        FOREIGN KEY(property_id) REFERENCES properties(property_id)
      );
    """)

    inv_info = get_table_info(con, "investments")
    inv_cols = [c["name"] for c in inv_info]

    # Plans with VALID categories only
    plans = [
        {"name": "Income Fund A", "status": "open",   "min_ticket_lkr": 5_000_000,  "target_irr": 0.13,
         "summary": "Yield-focused pool across apartments and townhouses.", "category": "rental_yield"},
        {"name": "Growth Pool B", "status": "open",   "min_ticket_lkr": 10_000_000, "target_irr": 0.18,
         "summary": "Capital appreciation via land banking and houses.",    "category": "land_bank"},
        {"name": "Co-invest C",   "status": "open",   "min_ticket_lkr": 2_500_000,  "target_irr": 0.15,
         "summary": "Small tickets into trophy assets.",                    "category": "flip"},
        {"name": "RE Dev D",      "status": "closed", "min_ticket_lkr": 15_000_000, "target_irr": 0.20,
         "summary": "Off-plan development pipeline.",                       "category": "development"},
    ]

    def inv_row(plan):
        # Ensure category is valid
        cat = plan.get("category") or "other"
        if cat not in ALLOWED_CATEGORIES:
            cat = "other"
        row = {}

        # Name/title variants — set ALL that exist
        for nm in ["plan_name", "name", "title", "plan_title"]:
            if nm in inv_cols:
                row[nm] = plan["name"]

        # Category field
        for cc in ["category", "plan_category", "type"]:
            if cc in inv_cols:
                row[cc] = cat

        # Status / ticket / irr / summary
        if "status" in inv_cols: row["status"] = plan["status"]
        if "plan_status" in inv_cols: row["plan_status"] = plan["status"]
        for mn in ["min_ticket_lkr", "min_investment_lkr", "min_ticket", "min_amount_lkr"]:
            if mn in inv_cols:
                row[mn] = plan["min_ticket_lkr"]
        for ir in ["target_irr", "expected_irr", "target_roi"]:
            if ir in inv_cols:
                row[ir] = plan["target_irr"]
        for sm in ["summary", "description", "notes"]:
            if sm in inv_cols:
                row[sm] = plan["summary"]

        # Fill any other NOT NULL columns without defaults
        for meta in inv_info:
            name = meta["name"]
            if name in row or meta["pk"]:
                continue
            if meta["notnull"] and meta["dflt"] is None:
                row[name] = default_for_col(name, meta["type"], plan)

        return row

    inv_ids = []
    for plan in plans:
        row = inv_row(plan)
        inv_id = insert_row(con, "investments", row)
        inv_ids.append(inv_id)

    # Link random properties to each plan
    pids = [pid for pid, _ in property_ids]
    if pids:
        random.shuffle(pids)
        for inv_id in inv_ids:
            sample = random.sample(pids, k=min(len(pids), random.randint(15, 30)))
            for pid in sample:
                con.execute(
                    "INSERT OR IGNORE INTO investment_properties(investment_id, property_id) VALUES (?,?)",
                    (inv_id, pid)
                )

# ---------- PRAGMAs ----------
def fast_pragmas(con):
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    con.execute("PRAGMA temp_store=MEMORY;")
    con.execute("PRAGMA cache_size=-20000;")

# ---------- main ----------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=500, help="number of listings to seed")
    parser.add_argument("--no-invest", action="store_true", help="seed listings only (skip investments)")
    args = parser.parse_args()

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    fast_pragmas(con)

    try:
        with con:
            ensure_extra_tables(con)
            seed_aliases(con)
            props = seed_properties(con, n=args.n)
            if not args.no_invest:
                seed_investments(con, props)

        total_props = con.execute("SELECT COUNT(*) FROM properties").fetchone()[0]
        print(f"✅ Seed complete. properties={total_props}")
        try:
            k = con.execute("SELECT COUNT(*) FROM investment_properties").fetchone()[0]
            print(f"Linked properties to investments: {k}")
        except Exception:
            pass
    finally:
        con.close()

if __name__ == "__main__":
    main()
