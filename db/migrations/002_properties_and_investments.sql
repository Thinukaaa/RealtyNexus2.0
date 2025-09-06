PRAGMA foreign_keys=ON;
BEGIN;

/* ---------- Core listings table ---------- */
CREATE TABLE IF NOT EXISTS properties (
  property_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  listing_code    TEXT UNIQUE,
  title           TEXT NOT NULL,
  description     TEXT,
  property_type   TEXT NOT NULL,          -- apartment | house | land | townhouse | commercial
  purpose         TEXT NOT NULL DEFAULT 'sale',   -- sale | rent
  status          TEXT NOT NULL DEFAULT 'available', -- available | sold | reserved | off_market
  city            TEXT,
  district        TEXT,
  address_line    TEXT,
  bedrooms        INTEGER,
  bathrooms       INTEGER,
  area_sqm        REAL,                   -- built area (for built properties)
  land_perch      REAL,                   -- land size (for land)
  price_lkr       INTEGER NOT NULL,
  featured        INTEGER NOT NULL DEFAULT 0, -- 0/1
  latitude        REAL,
  longitude       REAL,
  created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME
);

-- Helpful indexes for the queries used in app.py
CREATE INDEX IF NOT EXISTS idx_props_status           ON properties(status);
CREATE INDEX IF NOT EXISTS idx_props_city_district    ON properties(city, district);
CREATE INDEX IF NOT EXISTS idx_props_type             ON properties(property_type);
CREATE INDEX IF NOT EXISTS idx_props_purpose          ON properties(purpose);
CREATE INDEX IF NOT EXISTS idx_props_beds             ON properties(bedrooms);
CREATE INDEX IF NOT EXISTS idx_props_price            ON properties(price_lkr);
CREATE INDEX IF NOT EXISTS idx_props_featured_price   ON properties(featured, price_lkr);

/* ---------- Optional media table (already present for you, keep IF NOT EXISTS) ---------- */
CREATE TABLE IF NOT EXISTS property_media (
  media_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  property_id  INTEGER NOT NULL,
  kind         TEXT,                 -- photo | plan | doc | etc.
  url          TEXT,
  caption      TEXT,
  created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(property_id) REFERENCES properties(property_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_media_prop ON property_media(property_id);

/* ---------- Full-Text Search (FTS5) ---------- */
-- If your SQLite has FTS5 enabled (standard on modern Python builds),
-- this virtual table will power the DB context for LLM & quick searches.
CREATE VIRTUAL TABLE IF NOT EXISTS property_fts USING fts5(
  title,
  description,
  city,
  property_type,
  content='properties',
  content_rowid='property_id'
);

-- Keep FTS in sync with base table
CREATE TRIGGER IF NOT EXISTS properties_ai AFTER INSERT ON properties BEGIN
  INSERT INTO property_fts(rowid,title,description,city,property_type)
  VALUES (new.property_id, new.title, new.description, COALESCE(new.city, new.district, ''), new.property_type);
END;

CREATE TRIGGER IF NOT EXISTS properties_ad AFTER DELETE ON properties BEGIN
  INSERT INTO property_fts(property_fts, rowid, title, description, city, property_type)
  VALUES ('delete', old.property_id, old.title, old.description, COALESCE(old.city, old.district, ''), old.property_type);
END;

CREATE TRIGGER IF NOT EXISTS properties_au AFTER UPDATE ON properties BEGIN
  INSERT INTO property_fts(property_fts, rowid, title, description, city, property_type)
  VALUES ('delete', old.property_id, old.title, old.description, COALESCE(old.city, old.district, ''), old.property_type);
  INSERT INTO property_fts(rowid,title,description,city,property_type)
  VALUES (new.property_id, new.title, new.description, COALESCE(new.city, new.district, ''), new.property_type);
END;

/* ---------- Investments ---------- */
CREATE TABLE IF NOT EXISTS investments (
  investment_id         INTEGER PRIMARY KEY AUTOINCREMENT,
  plan_name             TEXT NOT NULL,
  category              TEXT,         -- e.g., rental_yield | land_bank | off_plan | flip | co_invest
  summary               TEXT,
  expected_yield_pct    REAL,
  expected_roi_pct      REAL,
  min_investment_lkr    INTEGER,
  property_id           INTEGER,      -- optional anchor property
  status                TEXT NOT NULL DEFAULT 'open', -- open | closed
  created_at            DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at            DATETIME,
  FOREIGN KEY(property_id) REFERENCES properties(property_id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_invest_status ON investments(status);
CREATE INDEX IF NOT EXISTS idx_invest_cat    ON investments(category);

-- Many-to-many between investments and properties (optional)
CREATE TABLE IF NOT EXISTS investment_properties (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  investment_id INTEGER NOT NULL,
  property_id   INTEGER NOT NULL,
  role          TEXT,                           -- anchor | comparable | pipeline
  FOREIGN KEY(investment_id) REFERENCES investments(investment_id) ON DELETE CASCADE,
  FOREIGN KEY(property_id)   REFERENCES properties(property_id)   ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_invprop_inv ON investment_properties(investment_id);
CREATE INDEX IF NOT EXISTS idx_invprop_prop ON investment_properties(property_id);

COMMIT;
