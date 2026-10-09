-- FleetSheet SQLite schema. Calculations live in app code / views, not user cells.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS company (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  name TEXT NOT NULL,
  dba TEXT,
  address TEXT,
  addr_street TEXT,
  addr_street2 TEXT,
  addr_city TEXT,
  addr_state TEXT,
  addr_zip TEXT,
  phone TEXT,
  billing_email TEXT,
  invoice_prefix TEXT NOT NULL DEFAULT 'INV',
  next_invoice INTEGER NOT NULL DEFAULT 1001,
  next_ticket INTEGER NOT NULL DEFAULT 1001,
  next_cm INTEGER NOT NULL DEFAULT 1001,
  next_pc INTEGER NOT NULL DEFAULT 1001,
  next_quote INTEGER NOT NULL DEFAULT 1001,
  next_co INTEGER NOT NULL DEFAULT 1001,
  pc_float REAL NOT NULL DEFAULT 200,
  default_terms TEXT NOT NULL DEFAULT 'Net 30',
  default_tax REAL NOT NULL DEFAULT 0.0825,
  waiver_pct REAL NOT NULL DEFAULT 0.12,
  env_pct REAL NOT NULL DEFAULT 0.02,
  min_days INTEGER NOT NULL DEFAULT 1,
  bill_both_dates INTEGER NOT NULL DEFAULT 1,
  fiscal_start_month INTEGER NOT NULL DEFAULT 1,
  tooltips INTEGER NOT NULL DEFAULT 1,
  yard_loc_id TEXT REFERENCES jurisdictions(loc_id),
  desk_name TEXT,
  backup_dir TEXT,
  last_backup TEXT,
  next_wo INTEGER NOT NULL DEFAULT 101,
  next_payment INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS company_phones (
  phone_id INTEGER PRIMARY KEY AUTOINCREMENT,
  label TEXT NOT NULL,
  number TEXT NOT NULL,
  is_main INTEGER NOT NULL DEFAULT 0,
  sort INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS customers (
  customer_id TEXT PRIMARY KEY,
  account_name TEXT NOT NULL,
  short_name TEXT,
  bill_to TEXT,
  phone TEXT,
  email TEXT,
  city_st TEXT,
  bill_street TEXT,
  bill_street2 TEXT,
  bill_city TEXT,
  bill_state TEXT,
  bill_zip TEXT,
  terms TEXT NOT NULL DEFAULT 'Net 30',
  tax_exempt INTEGER NOT NULL DEFAULT 0,
  waiver_default INTEGER NOT NULL DEFAULT 1,
  credit_limit REAL,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS customer_phones (
  phone_id INTEGER PRIMARY KEY AUTOINCREMENT,
  customer_id TEXT NOT NULL REFERENCES customers(customer_id),
  label TEXT NOT NULL,
  number TEXT NOT NULL,
  is_main INTEGER NOT NULL DEFAULT 0,
  sort INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS jurisdictions (
  loc_id TEXT PRIMARY KEY,
  loc_class TEXT NOT NULL,
  country TEXT,
  region TEXT,
  county TEXT,
  city TEXT,
  display_name TEXT,
  tax_rate REAL NOT NULL DEFAULT 0,
  tax_name TEXT,
  default_regime TEXT,
  req_uscg INTEGER NOT NULL DEFAULT 0,
  req_dnv INTEGER NOT NULL DEFAULT 0,
  req_abs INTEGER NOT NULL DEFAULT 0,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS sites (
  site_id TEXT PRIMARY KEY,
  site_name TEXT NOT NULL,
  operator TEXT,
  rig_name TEXT,
  flag_state TEXT,
  waters TEXT,
  primary_regime TEXT,
  customer_id TEXT REFERENCES customers(customer_id),
  loc_id TEXT REFERENCES jurisdictions(loc_id),
  tax_exempt INTEGER NOT NULL DEFAULT 0,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS assets (
  asset_id TEXT PRIMARY KEY,
  unit_no TEXT NOT NULL,
  category TEXT,
  description TEXT,
  serial_no TEXT,
  yard TEXT,
  uscg_ok INTEGER NOT NULL DEFAULT 0,
  dnv_ok INTEGER NOT NULL DEFAULT 0,
  abs_ok INTEGER NOT NULL DEFAULT 0,
  daily_rate REAL NOT NULL DEFAULT 0,
  weekly_rate REAL NOT NULL DEFAULT 0,
  monthly_rate REAL NOT NULL DEFAULT 0,
  standby_rate REAL NOT NULL DEFAULT 0,
  yard_rate REAL NOT NULL DEFAULT 0,
  special_rate REAL NOT NULL DEFAULT 0,
  -- Single rate field (2026-09-27): one unit + one value per asset.
  -- The six legacy columns stay frozen for historical reads/exports.
  rate_unit TEXT NOT NULL DEFAULT 'Day',
  rate_value REAL NOT NULL DEFAULT 0,
  meter_hours REAL NOT NULL DEFAULT 0,
  replacement_cost REAL,
  cert_expire TEXT,
  ownership TEXT DEFAULT 'Owned',
  active INTEGER NOT NULL DEFAULT 1,
  condition TEXT DEFAULT 'Available',
  cert_operator INTEGER NOT NULL DEFAULT 0,
  notes TEXT,
  sold_date TEXT,
  sold_amount REAL,
  sold_to TEXT
);

CREATE TABLE IF NOT EXISTS tickets (
  ticket_id TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL REFERENCES customers(customer_id),
  site_id TEXT NOT NULL REFERENCES sites(site_id),
  asset_id TEXT NOT NULL REFERENCES assets(asset_id),
  job_name TEXT,
  well_or_pad TEXT,
  afe TEXT,
  po TEXT,
  rate_type TEXT NOT NULL CHECK (rate_type IN ('Day','Week','Hour','Special','Monthly','Standby','Yard')),
  rate_value REAL,
  hours_start REAL,
  hours_end REAL,
  on_rent TEXT NOT NULL,
  off_rent TEXT,
  mob REAL NOT NULL DEFAULT 0,
  demob REAL NOT NULL DEFAULT 0,
  fuel REAL NOT NULL DEFAULT 0,
  parts REAL NOT NULL DEFAULT 0,
  other_amt REAL NOT NULL DEFAULT 0,
  transport_fee REAL NOT NULL DEFAULT 0,
  customer_transport INTEGER NOT NULL DEFAULT 0,
  haul_by TEXT NOT NULL DEFAULT 'we',
  deliver_to TEXT NOT NULL DEFAULT 'job_site',
  tax_loc_id TEXT REFERENCES jurisdictions(loc_id),
  waiver_yn INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL CHECK (status IN (
    'Quoted','Reserved','Dispatched','On Rent','Standby','Off Rent','Ready to Bill','Billed','Closed','Void'
  )),
  invoice_no TEXT,
  quote_no TEXT,
  location_note TEXT,
  attached_to TEXT,
  clerk TEXT,
  out_condition TEXT,
  out_note TEXT,
  out_meter TEXT,
  out_photo TEXT,
  out_by TEXT,
  out_at TEXT,
  in_condition TEXT,
  in_note TEXT,
  in_meter TEXT,
  in_photo TEXT,
  in_by TEXT,
  in_at TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS invoices (
  invoice_no TEXT PRIMARY KEY,
  invoice_date TEXT NOT NULL,
  customer_id TEXT NOT NULL REFERENCES customers(customer_id),
  terms TEXT NOT NULL,
  notes TEXT,
  quote_no TEXT,
  po TEXT,
  status TEXT NOT NULL CHECK (status IN ('Draft','Ready','Sent','Partial','Paid','Disputed','Write-off'))
);

CREATE TABLE IF NOT EXISTS invoice_lines (
  line_id INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_no TEXT NOT NULL REFERENCES invoices(invoice_no),
  po_line TEXT,
  category TEXT NOT NULL,
  description TEXT NOT NULL,
  qty REAL NOT NULL DEFAULT 1,
  uom TEXT NOT NULL,
  rate REAL NOT NULL DEFAULT 0,
  amount REAL NOT NULL DEFAULT 0,
  clerk TEXT,
  tax_rate REAL NOT NULL DEFAULT 0,
  tax_amount REAL NOT NULL DEFAULT 0,
  tax_exempt INTEGER NOT NULL DEFAULT 0,
  tax_name TEXT NOT NULL DEFAULT '',
  tax_loc TEXT NOT NULL DEFAULT '',
  source_type TEXT NOT NULL DEFAULT '',
  source_id TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS collections (
  pay_id TEXT PRIMARY KEY,
  pay_date TEXT NOT NULL,
  invoice_no TEXT NOT NULL REFERENCES invoices(invoice_no),
  method TEXT NOT NULL,
  amount REAL NOT NULL CHECK (amount > 0),
  ref_no TEXT,
  notes TEXT,
  kind TEXT NOT NULL DEFAULT 'payment' CHECK (kind IN ('payment','credit')),
  cm_no TEXT,
  clerk TEXT,
  applied_amount REAL,
  unapplied_amount REAL NOT NULL DEFAULT 0
);

-- Invoice paperwork (2026-09-27): the PO scan and the tax-exempt certificate
-- attach to the INVOICE and travel with it (print/PDF pack). One slot per
-- kind per invoice — a new upload replaces the old one. Files live in the
-- shared docs/ folder next to the book, like data-book documents.
CREATE TABLE IF NOT EXISTS invoice_docs (
  doc_id INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_no TEXT NOT NULL REFERENCES invoices(invoice_no),
  kind TEXT NOT NULL CHECK (kind IN ('po','tax_exempt')),
  title TEXT NOT NULL,
  filename TEXT NOT NULL,
  stored TEXT NOT NULL,
  bytes INTEGER NOT NULL DEFAULT 0,
  mime TEXT NOT NULL DEFAULT '',
  uploaded_at TEXT NOT NULL DEFAULT (datetime('now')),
  clerk TEXT,
  UNIQUE(invoice_no, kind)
);
CREATE INDEX IF NOT EXISTS idx_invdocs_invoice ON invoice_docs(invoice_no);

CREATE TABLE IF NOT EXISTS credit_memos (
  cm_no TEXT PRIMARY KEY,
  cm_date TEXT NOT NULL,
  customer_id TEXT NOT NULL REFERENCES customers(customer_id),
  face_amount REAL NOT NULL CHECK (face_amount > 0),
  reason TEXT NOT NULL,
  notes TEXT,
  clerk TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_cm_cust ON credit_memos(customer_id);

CREATE TABLE IF NOT EXISTS petty_cash (
  pc_id TEXT PRIMARY KEY,
  txn_date TEXT NOT NULL,
  direction TEXT NOT NULL CHECK (direction IN ('in','out')),
  amount REAL NOT NULL CHECK (amount > 0),
  category TEXT NOT NULL,
  payee TEXT,
  ref_no TEXT,
  notes TEXT,
  clerk TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_pc_date ON petty_cash(txn_date);

CREATE TABLE IF NOT EXISTS lookups (
  kind TEXT NOT NULL,
  value TEXT NOT NULL,
  sort_order INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (kind, value)
);

CREATE TABLE IF NOT EXISTS work_orders (
  wo_id TEXT PRIMARY KEY,
  asset_id TEXT NOT NULL REFERENCES assets(asset_id),
  ticket_id TEXT REFERENCES tickets(ticket_id),
  customer_id TEXT REFERENCES customers(customer_id),
  charge_to TEXT NOT NULL CHECK (charge_to IN ('internal','customer')),
  work_type TEXT NOT NULL,
  description TEXT NOT NULL,
  vendor TEXT,
  open_date TEXT NOT NULL,
  close_date TEXT,
  labor REAL NOT NULL DEFAULT 0,
  parts REAL NOT NULL DEFAULT 0,
  other_cost REAL NOT NULL DEFAULT 0,
  bill_amount REAL NOT NULL DEFAULT 0,
  status TEXT NOT NULL CHECK (status IN ('Open','In progress','Complete','Void')),
  warranty INTEGER NOT NULL DEFAULT 0,
  yard_or_site TEXT,
  notes TEXT,
  invoice_no TEXT,
  quote_no TEXT
);

CREATE TABLE IF NOT EXISTS quotes (
  quote_no TEXT PRIMARY KEY,
  quote_date TEXT NOT NULL,
  customer_id TEXT NOT NULL REFERENCES customers(customer_id),
  site_id TEXT REFERENCES sites(site_id),
  job_name TEXT,
  afe TEXT,
  po TEXT,
  valid_until TEXT,
  status TEXT NOT NULL CHECK (status IN ('Draft','Sent','Accepted','Declined','Expired','Converted','Void')),
  notes TEXT,
  clerk TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS quote_lines (
  line_id INTEGER PRIMARY KEY AUTOINCREMENT,
  quote_no TEXT NOT NULL REFERENCES quotes(quote_no),
  kind TEXT NOT NULL CHECK (kind IN ('item','unit','labor','freight','other','rental','service','transport')),
  asset_id TEXT REFERENCES assets(asset_id),
  description TEXT NOT NULL,
  qty REAL NOT NULL DEFAULT 1,
  rate REAL NOT NULL DEFAULT 0,
  rate_unit TEXT,
  amount REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS change_orders (
  co_no TEXT PRIMARY KEY,
  quote_no TEXT NOT NULL REFERENCES quotes(quote_no),
  co_date TEXT NOT NULL,
  reason TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('Issued','Void')),
  notes TEXT,
  clerk TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS change_order_lines (
  line_id INTEGER PRIMARY KEY AUTOINCREMENT,
  co_no TEXT NOT NULL REFERENCES change_orders(co_no),
  direction TEXT NOT NULL CHECK (direction IN ('add','subtract')),
  kind TEXT NOT NULL CHECK (kind IN ('item','unit','labor','freight','other','rental','service','transport')),
  description TEXT NOT NULL,
  qty REAL NOT NULL DEFAULT 1,
  rate REAL NOT NULL DEFAULT 0,
  amount REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS crew (
  name TEXT PRIMARY KEY
);

CREATE INDEX IF NOT EXISTS idx_wo_asset ON work_orders(asset_id);
CREATE INDEX IF NOT EXISTS idx_wo_status ON work_orders(status);

CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);
CREATE INDEX IF NOT EXISTS idx_tickets_asset ON tickets(asset_id);
CREATE INDEX IF NOT EXISTS idx_tickets_invoice ON tickets(invoice_no);
CREATE INDEX IF NOT EXISTS idx_col_inv ON collections(invoice_no);
CREATE INDEX IF NOT EXISTS idx_col_cm ON collections(cm_no);

-- Migration: saved export presets (Setup > Export > "Save preset").
-- Added because engine.py's list_saved_exports/save_export/delete_saved_export
-- reference this table but it predates the production schema.
CREATE TABLE IF NOT EXISTS saved_exports (
  export_id INTEGER PRIMARY KEY AUTOINCREMENT,
  label TEXT NOT NULL,
  what TEXT NOT NULL,
  "when" TEXT NOT NULL,
  from_date TEXT,
  to_date TEXT,
  how TEXT NOT NULL
);

-- Saved custom report builds: real field + filter selection over the named
-- datasets (engine_reports). Lazy-created by engine_reports too, for DBs
-- built before this table existed.
CREATE TABLE IF NOT EXISTS custom_reports (
  report_id INTEGER PRIMARY KEY AUTOINCREMENT,
  label TEXT NOT NULL,
  dataset TEXT NOT NULL,
  fields TEXT NOT NULL DEFAULT '[]',
  from_date TEXT DEFAULT '',
  to_date TEXT DEFAULT '',
  contains_field TEXT DEFAULT '',
  contains_text TEXT DEFAULT '',
  sort_field TEXT DEFAULT '',
  sort_dir TEXT DEFAULT 'asc',
  how TEXT DEFAULT 'csv',
  created_at TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now'))
);

-- Compliance packs (pre-built templates) and per-unit checklists.
-- trigger: per_job | per_shift | calendar | event | manufacturer
-- basis: standard | manufacturer | company  (company = shop-policy default
-- where the standard is silent; never presented as a regulatory requirement)
CREATE TABLE IF NOT EXISTS compliance_packs (
  pack_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  blurb TEXT
);

CREATE TABLE IF NOT EXISTS compliance_requirements (
  req_id INTEGER PRIMARY KEY AUTOINCREMENT,
  pack_id TEXT NOT NULL REFERENCES compliance_packs(pack_id),
  name TEXT NOT NULL,
  trigger TEXT NOT NULL,
  interval_months REAL,
  deployed_backstop_months REAL,
  criterion TEXT,
  evidence TEXT,
  source TEXT,
  basis TEXT NOT NULL DEFAULT 'standard',
  note TEXT,
  sort_order INTEGER NOT NULL DEFAULT 0,
  UNIQUE (pack_id, name)
);

CREATE TABLE IF NOT EXISTS equipment_compliance (
  eqc_id INTEGER PRIMARY KEY AUTOINCREMENT,
  asset_id TEXT NOT NULL REFERENCES assets(asset_id),
  pack_id TEXT REFERENCES compliance_packs(pack_id),
  req_id INTEGER REFERENCES compliance_requirements(req_id),
  custom_name TEXT,
  trigger TEXT NOT NULL,
  interval_months REAL,
  deployed_backstop_months REAL,
  last_done TEXT,
  next_due TEXT,
  notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_eqc_asset ON equipment_compliance(asset_id);

CREATE TABLE IF NOT EXISTS compliance_events (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  eqc_id INTEGER NOT NULL REFERENCES equipment_compliance(eqc_id),
  done_date TEXT NOT NULL,
  result TEXT NOT NULL DEFAULT 'pass',
  evidence TEXT,
  notes TEXT,
  clerk TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_cev_eqc ON compliance_events(eqc_id);

-- Yard-device auth tokens (Setup > Devices) and the generic key/value store
-- (desk PIN hash + recovery hash, backup settings, etc.). Previously these were
-- created lazily by engine code on first use; they belong in the schema so a
-- fresh build from this file alone is complete.
CREATE TABLE IF NOT EXISTS device_auths (
  token TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  scope TEXT NOT NULL DEFAULT 'yard',
  created_at TEXT NOT NULL,
  created_by TEXT NOT NULL DEFAULT '',
  expires_at TEXT,
  revoked_at TEXT,
  grace_until TEXT,
  last_seen_at TEXT
);

CREATE TABLE IF NOT EXISTS options (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL DEFAULT ''
);

-- Data-book documents per unit (certifications, drawings, instructions,
-- test records). Files live in a docs/ folder next to the book and ride
-- inside every backup archive, like ticket photos.
CREATE TABLE IF NOT EXISTS unit_docs (
  doc_id INTEGER PRIMARY KEY AUTOINCREMENT,
  asset_id TEXT NOT NULL,
  title TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'other',
  filename TEXT NOT NULL,
  stored TEXT NOT NULL,
  bytes INTEGER NOT NULL DEFAULT 0,
  mime TEXT NOT NULL DEFAULT '',
  uploaded_at TEXT NOT NULL DEFAULT (datetime('now')),
  clerk TEXT
);
CREATE INDEX IF NOT EXISTS idx_docs_asset ON unit_docs(asset_id);

-- Runtime-created tables are declared here so schema.sql is the single
-- authoritative source for the current database shape. Runtime ensure helpers
-- remain only for backward-compatible column repairs on older books.
CREATE TABLE IF NOT EXISTS vendors (
  vendor_id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'vendor' CHECK (kind IN ('vendor','crew')),
  phone TEXT NOT NULL DEFAULT '',
  email TEXT NOT NULL DEFAULT '',
  specialties TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS asset_certs (
  cert_id INTEGER PRIMARY KEY AUTOINCREMENT,
  asset_id TEXT NOT NULL REFERENCES assets(asset_id),
  kind TEXT NOT NULL DEFAULT 'certification',
  title TEXT NOT NULL,
  cert_number TEXT NOT NULL DEFAULT '',
  issuer TEXT NOT NULL DEFAULT '',
  issued_date TEXT,
  expiry_date TEXT,
  superseded INTEGER NOT NULL DEFAULT 0,
  evidence_doc_id INTEGER REFERENCES unit_docs(doc_id),
  notes TEXT NOT NULL DEFAULT '',
  clerk TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_certs_asset ON asset_certs(asset_id);

CREATE TABLE IF NOT EXISTS alert_ack (
  alert_key TEXT PRIMARY KEY,
  until_ts INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS purchase_orders (
  po_no TEXT NOT NULL,
  customer_id TEXT NOT NULL,
  expire TEXT,
  cost_code TEXT,
  notes TEXT,
  asset_id TEXT,
  ack_at TEXT,
  ack_by TEXT,
  PRIMARY KEY (customer_id, po_no)
);

CREATE TABLE IF NOT EXISTS today_tasks (
  task_id INTEGER PRIMARY KEY AUTOINCREMENT,
  text TEXT NOT NULL,
  tier TEXT NOT NULL CHECK (tier IN ('must','can','later')),
  done INTEGER NOT NULL DEFAULT 0,
  link TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  done_at TEXT,
  done_by TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS done_manual (
  entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
  text TEXT NOT NULL,
  link TEXT NOT NULL DEFAULT '',
  done_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
  done_by TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS today_money_done (
  slot_key TEXT PRIMARY KEY,
  done_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS today_stickies (
  sticky_id INTEGER PRIMARY KEY AUTOINCREMENT,
  text TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  priority INTEGER NOT NULL DEFAULT 1,
  color TEXT NOT NULL DEFAULT 'yellow',
  snoozed_until TEXT,
  hide_until TEXT,
  pinned INTEGER NOT NULL DEFAULT 0,
  dismissed INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS pending_bookings (
  pending_id INTEGER PRIMARY KEY AUTOINCREMENT,
  soft_ticket_id TEXT NOT NULL,
  data_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
