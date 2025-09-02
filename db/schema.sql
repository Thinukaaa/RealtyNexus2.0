-- =========================================
-- RealtyAI / RealtyNexus 2.0 — SQLite Schema
-- =========================================

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

BEGIN;

-- ---------- Utility: updated_at ----------
-- Add updated_at default and auto-touch trigger per table.

-- ---------- Companies (partners/vendors/developers/law firms) ----------
CREATE TABLE companies (
  company_id      INTEGER PRIMARY KEY,
  name            TEXT NOT NULL UNIQUE,
  company_type    TEXT NOT NULL DEFAULT 'partner'
                    CHECK (company_type IN ('partner','developer','law_firm','bank','vendor','agency','internal','other')),
  phone           TEXT,
  email           TEXT,
  website         TEXT,
  address_line    TEXT,
  city            TEXT,
  country         TEXT,
  status          TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','inactive')),
  notes           TEXT,
  created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TRIGGER companies_touch_uat
AFTER UPDATE ON companies
BEGIN
  UPDATE companies SET updated_at = CURRENT_TIMESTAMP WHERE company_id = NEW.company_id;
END;

-- ---------- Contacts (your agents & partner employees) ----------
CREATE TABLE contacts (
  contact_id      INTEGER PRIMARY KEY,
  company_id      INTEGER REFERENCES companies(company_id) ON DELETE SET NULL,
  first_name      TEXT,
  last_name       TEXT,
  email           TEXT,
  phone           TEXT,
  title           TEXT,                     -- role/title
  preferred_chan  TEXT DEFAULT 'email'      -- email/phone/whatsapp/sms
                    CHECK (preferred_chan IN ('email','phone','whatsapp','sms','other')),
  is_agent        INTEGER NOT NULL DEFAULT 0 CHECK (is_agent IN (0,1)),
  status          TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','inactive')),
  notes           TEXT,
  created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(email)
);

CREATE INDEX idx_contacts_company ON contacts(company_id);
CREATE TRIGGER contacts_touch_uat
AFTER UPDATE ON contacts
BEGIN
  UPDATE contacts SET updated_at = CURRENT_TIMESTAMP WHERE contact_id = NEW.contact_id;
END;

-- ---------- Leads (captured from chat or forms) ----------
CREATE TABLE leads (
  lead_id               INTEGER PRIMARY KEY,
  name                  TEXT,
  email                 TEXT,
  phone                 TEXT,
  source                TEXT NOT NULL DEFAULT 'chat_widget'
                          CHECK (source IN ('chat_widget','web_form','referral','walk_in','phone','other')),
  intent                TEXT                 -- viewing/valuation/buy/rent/investment/general
                          CHECK (intent IN ('viewing','valuation','buy','rent','investment','general')),
  budget_min_lkr        INTEGER,
  budget_max_lkr        INTEGER,
  city_pref             TEXT,
  property_type_pref    TEXT                 -- apartment/house/land/commercial/other
                          CHECK (property_type_pref IN ('apartment','house','land','commercial','office','villa','townhouse','other') OR property_type_pref IS NULL),
  stage                 TEXT NOT NULL DEFAULT 'new'
                          CHECK (stage IN ('new','contacted','qualified','proposal','won','lost','nurture')),
  assigned_contact_id   INTEGER REFERENCES contacts(contact_id) ON DELETE SET NULL, -- your agent
  note                  TEXT,
  created_at            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(email, phone)
);

CREATE INDEX idx_leads_stage ON leads(stage);
CREATE INDEX idx_leads_intent ON leads(intent);
CREATE TRIGGER leads_touch_uat
AFTER UPDATE ON leads
BEGIN
  UPDATE leads SET updated_at = CURRENT_TIMESTAMP WHERE lead_id = NEW.lead_id;
END;

-- ---------- Conversations & Messages (chat transcripts) ----------
CREATE TABLE conversations (
  conversation_id   INTEGER PRIMARY KEY,
  lead_id           INTEGER REFERENCES leads(lead_id) ON DELETE SET NULL,
  source            TEXT NOT NULL DEFAULT 'chat_widget'
                      CHECK (source IN ('chat_widget','whatsapp','phone_log','email','other')),
  session_id        TEXT,                   -- browser/session identifier
  status            TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','closed')),
  started_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  ended_at          DATETIME
);

CREATE INDEX idx_conv_lead ON conversations(lead_id);
CREATE INDEX idx_conv_status ON conversations(status);

CREATE TABLE messages (
  message_id        INTEGER PRIMARY KEY,
  conversation_id   INTEGER NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
  role              TEXT NOT NULL CHECK (role IN ('user','assistant','agent','system')),
  content           TEXT NOT NULL,
  model             TEXT,                   -- if generated by LLM
  tokens            INTEGER,
  error             TEXT,
  created_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_msg_conv_created ON messages(conversation_id, created_at);

-- Optional: per-message detected intents
CREATE TABLE msg_intents (
  id               INTEGER PRIMARY KEY,
  conversation_id  INTEGER NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
  message_id       INTEGER NOT NULL REFERENCES messages(message_id) ON DELETE CASCADE,
  name             TEXT NOT NULL,   -- e.g., 'fees','areas','valuation','viewing','greeting','unknown'
  score            REAL,
  created_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_intent_conv ON msg_intents(conversation_id);

-- ---------- Properties (listings) ----------
CREATE TABLE properties (
  property_id       INTEGER PRIMARY KEY,
  title             TEXT NOT NULL,
  listing_code      TEXT UNIQUE,            -- your internal or MLS-like code
  property_type     TEXT NOT NULL
                      CHECK (property_type IN ('apartment','house','land','commercial','office','villa','townhouse','plot','other')),
  purpose           TEXT NOT NULL DEFAULT 'sale' CHECK (purpose IN ('sale','rent','investment','lease')),
  status            TEXT NOT NULL DEFAULT 'available'
                      CHECK (status IN ('available','pending','reserved','sold','rented','offmarket')),
  description       TEXT,
  address_line      TEXT,
  city              TEXT,
  district          TEXT,
  country           TEXT DEFAULT 'Sri Lanka',
  latitude          REAL,
  longitude         REAL,
  bedrooms          INTEGER,
  bathrooms         INTEGER,
  parking           INTEGER,
  build_year        INTEGER,
  area_sqm          REAL,
  land_perch        REAL,
  price_lkr         INTEGER,
  currency          TEXT NOT NULL DEFAULT 'LKR',
  price_period      TEXT NOT NULL DEFAULT 'total' CHECK (price_period IN ('total','per_month','per_year','per_sqft')),
  listed_by_contact_id INTEGER REFERENCES contacts(contact_id) ON DELETE SET NULL, -- your agent
  company_id        INTEGER REFERENCES companies(company_id) ON DELETE SET NULL,   -- developer/owner company
  featured          INTEGER NOT NULL DEFAULT 0 CHECK (featured IN (0,1)),
  created_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_props_city ON properties(city);
CREATE INDEX idx_props_type ON properties(property_type);
CREATE INDEX idx_props_status ON properties(status);
CREATE INDEX idx_props_price ON properties(price_lkr);
CREATE TRIGGER properties_touch_uat
AFTER UPDATE ON properties
BEGIN
  UPDATE properties SET updated_at = CURRENT_TIMESTAMP WHERE property_id = NEW.property_id;
END;

-- Media per property
CREATE TABLE property_media (
  media_id     INTEGER PRIMARY KEY,
  property_id  INTEGER NOT NULL REFERENCES properties(property_id) ON DELETE CASCADE,
  media_type   TEXT NOT NULL CHECK (media_type IN ('image','video','floorplan','document')),
  url          TEXT NOT NULL,
  caption      TEXT,
  sort_order   INTEGER DEFAULT 0
);
CREATE INDEX idx_media_prop ON property_media(property_id);

-- ---------- Investment Plans ----------
CREATE TABLE investments (
  investment_id        INTEGER PRIMARY KEY,
  plan_name            TEXT NOT NULL,
  category             TEXT NOT NULL    -- off_plan, land_bank, reit, flip, rental_yield, development
                        CHECK (category IN ('off_plan','land_bank','reit','flip','rental_yield','development','other')),
  risk_level           TEXT NOT NULL DEFAULT 'medium' CHECK (risk_level IN ('low','medium','high')),
  min_investment_lkr   INTEGER,
  expected_yield_pct   REAL,
  expected_roi_pct     REAL,
  lockup_months        INTEGER,
  units_total          INTEGER,
  units_available      INTEGER,
  start_date           DATE,
  end_date             DATE,
  property_id          INTEGER REFERENCES properties(property_id) ON DELETE SET NULL, -- tie to a property when applicable
  developer_company_id INTEGER REFERENCES companies(company_id) ON DELETE SET NULL,
  status               TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','closed','sold_out','paused')),
  summary              TEXT,
  created_at           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_inv_status ON investments(status);
CREATE INDEX idx_inv_category ON investments(category);
CREATE TRIGGER investments_touch_uat
AFTER UPDATE ON investments
BEGIN
  UPDATE investments SET updated_at = CURRENT_TIMESTAMP WHERE investment_id = NEW.investment_id;
END;

-- In case one plan spans multiple properties
CREATE TABLE investment_properties (
  investment_id  INTEGER NOT NULL REFERENCES investments(investment_id) ON DELETE CASCADE,
  property_id    INTEGER NOT NULL REFERENCES properties(property_id) ON DELETE CASCADE,
  allocation_pct REAL,                      -- optional share of plan tied to this property
  PRIMARY KEY (investment_id, property_id)
);

-- ---------- Operational: Viewings & Valuations ----------
CREATE TABLE viewings (
  viewing_id     INTEGER PRIMARY KEY,
  property_id    INTEGER NOT NULL REFERENCES properties(property_id) ON DELETE CASCADE,
  lead_id        INTEGER REFERENCES leads(lead_id) ON DELETE SET NULL,
  agent_id       INTEGER REFERENCES contacts(contact_id) ON DELETE SET NULL,
  scheduled_at   DATETIME NOT NULL,
  status         TEXT NOT NULL DEFAULT 'scheduled' CHECK (status IN ('scheduled','completed','no_show','cancelled')),
  notes          TEXT,
  created_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_viewings_prop ON viewings(property_id);
CREATE INDEX idx_viewings_lead ON viewings(lead_id);

CREATE TABLE valuations (
  valuation_id   INTEGER PRIMARY KEY,
  property_id    INTEGER NOT NULL REFERENCES properties(property_id) ON DELETE CASCADE,
  by_company_id  INTEGER REFERENCES companies(company_id) ON DELETE SET NULL,
  requested_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  completed_at   DATETIME,
  value_lkr      INTEGER,
  valuation_type TEXT CHECK (valuation_type IN ('bank','market','rental','desktop','other')),
  status         TEXT NOT NULL DEFAULT 'requested' CHECK (status IN ('requested','in_progress','delivered','cancelled')),
  notes          TEXT
);
CREATE INDEX idx_val_prop ON valuations(property_id);

-- ---------- Knowledge Base (FAQs / policies / canned snippets) ----------
CREATE TABLE kb_chunks (
  chunk_id       INTEGER PRIMARY KEY,
  source         TEXT NOT NULL,           -- faq, service, policy, script, other
  text           TEXT NOT NULL,
  meta           TEXT,                    -- JSON blob (use json1 functions)
  created_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TRIGGER kb_touch_uat
AFTER UPDATE ON kb_chunks
BEGIN
  UPDATE kb_chunks SET updated_at = CURRENT_TIMESTAMP WHERE chunk_id = NEW.chunk_id;
END;

-- ---------- Full-Text Search (FTS5) ----------
-- Properties FTS
CREATE VIRTUAL TABLE property_fts USING fts5(
  title, description, city, district,
  content='properties', content_rowid='property_id'
);

-- keep FTS in sync
CREATE TRIGGER property_ai AFTER INSERT ON properties BEGIN
  INSERT INTO property_fts(rowid,title,description,city,district)
  VALUES (new.property_id, new.title, new.description, new.city, new.district);
END;
CREATE TRIGGER property_ad AFTER DELETE ON properties BEGIN
  DELETE FROM property_fts WHERE rowid = old.property_id;
END;
CREATE TRIGGER property_au AFTER UPDATE ON properties BEGIN
  DELETE FROM property_fts WHERE rowid = old.property_id;
  INSERT INTO property_fts(rowid,title,description,city,district)
  VALUES (new.property_id, new.title, new.description, new.city, new.district);
END;

-- KB FTS
CREATE VIRTUAL TABLE kb_fts USING fts5(
  text, source,
  content='kb_chunks', content_rowid='chunk_id'
);
CREATE TRIGGER kb_ai AFTER INSERT ON kb_chunks BEGIN
  INSERT INTO kb_fts(rowid,text,source) VALUES (new.chunk_id, new.text, new.source);
END;
CREATE TRIGGER kb_ad AFTER DELETE ON kb_chunks BEGIN
  DELETE FROM kb_fts WHERE rowid = old.chunk_id;
END;
CREATE TRIGGER kb_au AFTER UPDATE ON kb_chunks BEGIN
  DELETE FROM kb_fts WHERE rowid = old.chunk_id;
  INSERT INTO kb_fts(rowid,text,source) VALUES (new.chunk_id, new.text, new.source);
END;

-- ---------- Helpful Views ----------
CREATE VIEW v_active_properties AS
  SELECT p.*
  FROM properties p
  WHERE p.status = 'available';

CREATE VIEW v_open_investments AS
  SELECT i.*, c.name AS developer_name, p.city AS primary_city
  FROM investments i
  LEFT JOIN companies c ON c.company_id = i.developer_company_id
  LEFT JOIN properties p ON p.property_id = i.property_id
  WHERE i.status = 'open';

CREATE VIEW v_conversation_last_message AS
  SELECT m1.conversation_id,
         MAX(m1.created_at) AS last_ts,
         (SELECT content FROM messages m2 WHERE m2.conversation_id = m1.conversation_id ORDER BY m2.created_at DESC LIMIT 1) AS last_content
  FROM messages m1
  GROUP BY m1.conversation_id;

COMMIT;
