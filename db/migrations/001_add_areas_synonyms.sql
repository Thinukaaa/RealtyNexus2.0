BEGIN;

-- Areas & aliases (for cities/locations)
CREATE TABLE IF NOT EXISTS areas (
  area_id      INTEGER PRIMARY KEY,
  name         TEXT NOT NULL UNIQUE,   -- e.g., "Colombo 5"
  district     TEXT,                   -- e.g., "Colombo"
  aliases_json TEXT,                   -- JSON array: ["Havelock Town","CMB 05","CMB5"]
  created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TRIGGER IF NOT EXISTS areas_touch_uat
AFTER UPDATE ON areas
BEGIN
  UPDATE areas SET updated_at=CURRENT_TIMESTAMP WHERE area_id=NEW.area_id;
END;

-- Generic synonyms (cities and property types)
CREATE TABLE IF NOT EXISTS synonyms (
  id        INTEGER PRIMARY KEY,
  kind      TEXT NOT NULL CHECK (kind IN ('city','property_type')),
  canonical TEXT NOT NULL,     -- "Colombo 5" or "apartment"
  alias     TEXT NOT NULL,     -- "Havelock Town" or "condo"
  UNIQUE(kind, alias)
);
CREATE INDEX IF NOT EXISTS idx_syn_kind_canon ON synonyms(kind, canonical);

COMMIT;
