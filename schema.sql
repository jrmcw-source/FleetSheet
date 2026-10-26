-- FleetSheet SQLite schema. Calculations live in app code / views, not user cells.
-- Build 'v' (2026-10-25): numbers are never keys. Every table carries an
-- engine-assigned surrogate key (id, or the table's own integer key such as
-- line_id / doc_id / entry_id) as its PRIMARY KEY. Operator-facing numbers
-- and codes (invoice_no, ticket_id, customer_id, ...) are UNIQUE display
-- columns: their values, formats, and presentation are unchanged, and all
-- references between tables run on the surrogate keys underneath.
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
  yard_loc_id INTEGER REFERENCES jurisdictions(id),
  desk_name TEXT,
  backup_dir TEXT,
  last_backup TEXT,
  next_wo INTEGER NOT NULL DEFAULT 101,
  next_payment INTEGER NOT NULL DEFAULT 1,
  next_pay_key INTEGER NOT NULL DEFAULT 1,
  backup_schedule TEXT NOT NULL DEFAULT 'weekly',
  backup_every_days INTEGER NOT NULL DEFAULT 7,
  yard_state TEXT,
  yard_country TEXT DEFAULT 'US',
  phys_street TEXT,
  phys_street2 TEXT,
  phys_city TEXT,
  phys_county TEXT,
  phys_state TEXT,
  phys_zip TEXT,
  next_sale INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS company_phones (
  phone_id INTEGER PRIMARY KEY AUTOINCREMENT,
  label TEXT NOT NULL,
  number TEXT NOT NULL,
  is_main INTEGER NOT NULL DEFAULT 0,
  sort INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS customers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  customer_id TEXT NOT NULL UNIQUE,
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
  customer_id INTEGER NOT NULL REFERENCES customers(id),
  label TEXT NOT NULL,
  number TEXT NOT NULL,
  is_main INTEGER NOT NULL DEFAULT 0,
  sort INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS customer_locations (
  location_id INTEGER PRIMARY KEY AUTOINCREMENT,
  customer_id INTEGER NOT NULL REFERENCES customers(id),
  location_name TEXT NOT NULL,
  street TEXT,
  street2 TEXT,
  city TEXT,
  state TEXT,
  zip TEXT,
  is_primary INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS customer_contacts (
  contact_id INTEGER PRIMARY KEY AUTOINCREMENT,
  customer_id INTEGER NOT NULL REFERENCES customers(id),
  name TEXT NOT NULL,
  role TEXT,
  phone TEXT,
  email TEXT,
  is_primary INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS jurisdictions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  loc_id TEXT NOT NULL UNIQUE,
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
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  site_id TEXT NOT NULL UNIQUE,
  site_name TEXT NOT NULL,
  operator TEXT,
  rig_name TEXT,
  flag_state TEXT,
  waters TEXT,
  primary_regime TEXT,
  customer_id INTEGER REFERENCES customers(id),
  loc_id INTEGER REFERENCES jurisdictions(id),
  tax_exempt INTEGER NOT NULL DEFAULT 0,
  notes TEXT,
  street TEXT,
  street2 TEXT,
  city TEXT,
  state TEXT,
  zip TEXT
);

CREATE TABLE IF NOT EXISTS assets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  asset_id TEXT NOT NULL UNIQUE,
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
  designation TEXT NOT NULL DEFAULT 'Fleet',
  status TEXT NOT NULL DEFAULT 'Active',
  notes TEXT,
  sold_date TEXT,
  sold_amount REAL,
  sold_to TEXT
);

CREATE TABLE IF NOT EXISTS tickets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticket_id TEXT NOT NULL UNIQUE,
  customer_id INTEGER NOT NULL REFERENCES customers(id),
  site_id INTEGER REFERENCES sites(id),
  asset_id INTEGER NOT NULL REFERENCES assets(id),
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
  tax_loc_id INTEGER REFERENCES jurisdictions(id),
  waiver_yn INTEGER NOT NULL DEFAULT 1,
  fit_override TEXT NOT NULL DEFAULT '',
  billed_note TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL CHECK (status IN (
    'Quoted','Reserved','Dispatched','On Rent','Standby','Off Rent','Ready to Bill','Billed','Closed','Void'
  )),
  invoice_id INTEGER REFERENCES invoices(id),
  quote_id INTEGER REFERENCES quotes(id),
  location_note TEXT,
  attached_to TEXT,
  clerk TEXT,
  out_condition TEXT,
  out_note TEXT,
  out_meter TEXT,
  out_photo TEXT,
  out_by TEXT,
  out_at TEXT,
  out_src TEXT,
  in_condition TEXT,
  in_note TEXT,
  in_meter TEXT,
  in_photo TEXT,
  in_by TEXT,
  in_at TEXT,
  in_src TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  haul_note TEXT NOT NULL DEFAULT '',
  deliver_note TEXT NOT NULL DEFAULT '',
  soft_reserve INTEGER NOT NULL DEFAULT 0,
  ref_ticket TEXT
);

CREATE TABLE IF NOT EXISTS invoices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_no TEXT NOT NULL UNIQUE,
  invoice_date TEXT NOT NULL,
  customer_id INTEGER NOT NULL REFERENCES customers(id),
  terms TEXT NOT NULL,
  notes TEXT,
  quote_id INTEGER REFERENCES quotes(id),
  po TEXT,
  status TEXT NOT NULL CHECK (status IN ('Draft','Ready','Sent','Partial','Paid','Disputed','Write-off')),
  adjustment REAL DEFAULT 0,
  adj_label TEXT DEFAULT '',
  adj_taxable INTEGER DEFAULT 0,
  tax_exempt_op INTEGER DEFAULT 0,
  tax_rate REAL,
  contact_name TEXT,
  bar_text TEXT,
  ref_ticket TEXT,
  po_expire TEXT,
  po_cost_code TEXT,
  po_notes TEXT,
  shipped_by TEXT
);

CREATE TABLE IF NOT EXISTS invoice_lines (
  line_id INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_id INTEGER NOT NULL REFERENCES invoices(id),
  po_line TEXT,
  category TEXT NOT NULL,
  item TEXT DEFAULT '',
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
  source_id TEXT NOT NULL DEFAULT '',
  source_line_id INTEGER NOT NULL DEFAULT 0,
  line_note TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS ticket_lines (
  line_id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticket_id INTEGER NOT NULL REFERENCES tickets(id),
  category TEXT NOT NULL DEFAULT 'Other',
  item TEXT DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  qty REAL NOT NULL DEFAULT 1,
  uom TEXT NOT NULL DEFAULT 'Each',
  rate REAL NOT NULL DEFAULT 0,
  amount REAL NOT NULL DEFAULT 0,
  taxed INTEGER NOT NULL DEFAULT 1,
  line_note TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_ticket_lines_ticket ON ticket_lines(ticket_id);

-- The two money ledgers share ONE surrogate-key space (company.next_pay_key):
-- a payment event is one key whether its row lives here or in
-- doc_collections, and a carried mirror row reuses its source row's key.
-- pay_id stays the operator-facing payment number (UNIQUE display column).
CREATE TABLE IF NOT EXISTS collections (
  id INTEGER PRIMARY KEY,
  pay_id TEXT NOT NULL UNIQUE,
  pay_date TEXT NOT NULL,
  invoice_id INTEGER NOT NULL REFERENCES invoices(id),
  method TEXT NOT NULL,
  amount REAL NOT NULL CHECK (amount != 0),
  ref_no TEXT,
  notes TEXT,
  kind TEXT NOT NULL DEFAULT 'payment' CHECK (kind IN ('payment','credit')),
  cm_id INTEGER REFERENCES credit_memos(id),
  clerk TEXT,
  applied_amount REAL,
  unapplied_amount REAL NOT NULL DEFAULT 0,
  batch_id TEXT,
  cash_entry_id INTEGER REFERENCES cash_entries(entry_id),
  carried_from TEXT
);

-- Invoice paperwork (2026-09-27): the PO scan and the tax-exempt certificate
-- attach to the INVOICE and travel with it (print/PDF pack). One slot per
-- kind per invoice — a new upload replaces the old one. Files live in the
-- shared docs/ folder next to the book, like data-book documents.
CREATE TABLE IF NOT EXISTS invoice_docs (
  doc_id INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_id INTEGER NOT NULL REFERENCES invoices(id),
  kind TEXT NOT NULL CHECK (kind IN ('po','tax_exempt','shipping','custom')),
  title TEXT NOT NULL,
  filename TEXT NOT NULL,
  stored TEXT NOT NULL,
  bytes INTEGER NOT NULL DEFAULT 0,
  mime TEXT NOT NULL DEFAULT '',
  uploaded_at TEXT NOT NULL DEFAULT (datetime('now')),
  clerk TEXT,
  print_with INTEGER NOT NULL DEFAULT 1,
  UNIQUE(invoice_id, kind)
);
CREATE INDEX IF NOT EXISTS idx_invdocs_invoice ON invoice_docs(invoice_id);

CREATE TABLE IF NOT EXISTS credit_memos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  cm_no TEXT NOT NULL UNIQUE,
  cm_date TEXT NOT NULL,
  customer_id INTEGER NOT NULL REFERENCES customers(id),
  face_amount REAL NOT NULL CHECK (face_amount != 0),
  reason TEXT NOT NULL,
  notes TEXT,
  clerk TEXT,
  category TEXT DEFAULT 'Other',
  uom TEXT DEFAULT 'Each',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  cash_entry_id INTEGER REFERENCES cash_entries(entry_id)
);

CREATE INDEX IF NOT EXISTS idx_cm_cust ON credit_memos(customer_id);

CREATE TABLE IF NOT EXISTS credit_memo_lines (
  line_id INTEGER PRIMARY KEY AUTOINCREMENT,
  cm_id INTEGER NOT NULL REFERENCES credit_memos(id),
  category TEXT NOT NULL DEFAULT 'Other',
  item TEXT DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  qty REAL NOT NULL DEFAULT 1,
  uom TEXT NOT NULL DEFAULT 'Each',
  rate REAL NOT NULL DEFAULT 0,
  amount REAL NOT NULL DEFAULT 0,
  tax_exempt INTEGER NOT NULL DEFAULT 0,
  source_invoice_id INTEGER REFERENCES invoices(id),
  source_line_id INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_cmlines_cm ON credit_memo_lines(cm_id);

CREATE TABLE IF NOT EXISTS petty_cash (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  pc_id TEXT NOT NULL UNIQUE,
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

-- Cash tab entries (Batch 3 #12): tenders recorded against exactly
-- one attachment — an invoice, a work order, a rental ticket, a sale,
-- a quote, or (build 'v') a change order. No unattached entries. The
-- method list is the full tender list (engine CASH_METHODS; pack 'm'
-- added Bitcoin and Traveler's Check and unified the Cash door with
-- the payment list). Record-only, never processed; collections
-- (payments) and petty_cash stay their own stores and surface on the
-- Cash tab read-only.
CREATE TABLE IF NOT EXISTS cash_entries (
  entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
  entry_date TEXT NOT NULL,
  direction TEXT NOT NULL CHECK (direction IN ('in','out')),
  method TEXT NOT NULL CHECK (method IN ('ACH','Check','Wire','Card','Cash','Venmo','Bitcoin','Traveler''s Check','Other')),
  amount REAL NOT NULL CHECK (amount > 0),
  customer_id INTEGER REFERENCES customers(id),
  invoice_id INTEGER REFERENCES invoices(id),
  wo_id INTEGER REFERENCES work_orders(id),
  ticket_id INTEGER REFERENCES tickets(id),
  sale_id INTEGER,
  quote_id INTEGER REFERENCES quotes(id),
  co_id INTEGER REFERENCES change_orders(id),
  asset_id INTEGER REFERENCES assets(id),
  notes TEXT,
  clerk TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_cash_date ON cash_entries(entry_date);

CREATE TABLE IF NOT EXISTS lookups (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  value TEXT NOT NULL,
  sort_order INTEGER NOT NULL DEFAULT 0,
  UNIQUE (kind, value)
);

CREATE TABLE IF NOT EXISTS work_orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  wo_id TEXT NOT NULL UNIQUE,
  asset_id INTEGER NOT NULL REFERENCES assets(id),
  ticket_id INTEGER REFERENCES tickets(id),
  customer_id INTEGER REFERENCES customers(id),
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
  invoice_id INTEGER REFERENCES invoices(id),
  quote_id INTEGER REFERENCES quotes(id),
  po TEXT,
  ref_ticket TEXT,
  wo_date TEXT,
  item TEXT,
  qty REAL DEFAULT 1,
  cost REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS quotes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  quote_no TEXT NOT NULL UNIQUE,
  quote_date TEXT NOT NULL,
  customer_id INTEGER NOT NULL REFERENCES customers(id),
  site_id INTEGER REFERENCES sites(id),
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
  quote_id INTEGER NOT NULL REFERENCES quotes(id),
  kind TEXT NOT NULL CHECK (kind IN ('Rental','Labor','Item','Mileage','Freight','Fuel','Consumable','Mobilization','Demobilization','Other')),
  asset_id INTEGER REFERENCES assets(id),
  item TEXT DEFAULT '',
  description TEXT NOT NULL,
  qty REAL NOT NULL DEFAULT 1,
  rate REAL NOT NULL DEFAULT 0,
  rate_unit TEXT,
  uom TEXT DEFAULT 'Each',
  amount REAL NOT NULL DEFAULT 0,
  line_note TEXT NOT NULL DEFAULT ''
);

-- Change orders (build 'v', Jason 2026-10-25): a standalone money
-- document. Nothing requires anything — no quote parent, no required
-- association. It may name ONE associated money document (assoc_kind +
-- assoc_id, on the engine keys) as a stated fact; the association
-- changes no totals anywhere. Its own customer carries its money.
CREATE TABLE IF NOT EXISTS change_orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  co_no TEXT NOT NULL UNIQUE,
  customer_id INTEGER REFERENCES customers(id),
  assoc_kind TEXT,
  assoc_id INTEGER,
  co_date TEXT NOT NULL,
  reason TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('Issued','Void')),
  notes TEXT,
  clerk TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  po TEXT
);

CREATE TABLE IF NOT EXISTS change_order_lines (
  line_id INTEGER PRIMARY KEY AUTOINCREMENT,
  co_id INTEGER NOT NULL REFERENCES change_orders(id),
  item TEXT DEFAULT '',
  direction TEXT NOT NULL CHECK (direction IN ('add','subtract')),
  kind TEXT NOT NULL CHECK (kind IN ('Rental','Labor','Item','Mileage','Freight','Fuel','Consumable','Mobilization','Demobilization','Other')),
  description TEXT NOT NULL,
  qty REAL NOT NULL DEFAULT 1,
  rate REAL NOT NULL DEFAULT 0,
  uom TEXT DEFAULT 'Each',
  amount REAL NOT NULL DEFAULT 0,
  line_note TEXT
);

CREATE TABLE IF NOT EXISTS crew (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  position TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS sales (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sale_id TEXT NOT NULL UNIQUE,
  asset_id INTEGER NOT NULL REFERENCES assets(id),
  customer_id INTEGER REFERENCES customers(id),
  sale_date TEXT NOT NULL,
  qty INTEGER DEFAULT 1,
  amount REAL NOT NULL,
  condition TEXT,
  invoice_id INTEGER REFERENCES invoices(id),
  notes TEXT,
  clerk TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  ref_no TEXT,
  item_desc TEXT,
  seq INTEGER,
  group_id INTEGER,
  line_note TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_wo_asset ON work_orders(asset_id);
CREATE INDEX IF NOT EXISTS idx_wo_status ON work_orders(status);

CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);
CREATE INDEX IF NOT EXISTS idx_tickets_asset ON tickets(asset_id);
CREATE INDEX IF NOT EXISTS idx_tickets_invoice ON tickets(invoice_id);
CREATE INDEX IF NOT EXISTS idx_col_inv ON collections(invoice_id);
CREATE INDEX IF NOT EXISTS idx_col_cm ON collections(cm_id);
CREATE INDEX IF NOT EXISTS idx_col_batch ON collections(batch_id);

-- Payment line allocations (Jason 2026-10-23; generalized the same
-- day — "the universality needs to be complete"): money in may
-- OPTIONALLY be distributed line by line against ANY money document's
-- lines — invoice, work order, rental ticket, sale, or change order —
-- for audit and record keeping. One row per allocated portion:
-- line_id NULL is the blanket (document-level) remainder of a
-- broken-down amount. doc_kind names the document kind; doc_id is the
-- document's engine key; line_id is the line's key in that document's
-- line table (for a sale, the sales row's own key). source 'payment'
-- rows hang off a collections key (invoice) or a doc_collections key
-- (other documents) — pay_id is that shared ledger key; source
-- 'credit' rows are a credit memo applied against lines; source
-- 'cash' rows hang off a cash_entries entry — a Cash In settles and
-- consumes, a Cash Out is a record and consumes nothing. carried=1
-- marks a mirror row written onto an invoice when its source document
-- was invoiced: it counts in the invoice line's covered state but is
-- not new money in any total. A payment with no rows here is a plain
-- blanket payment.
CREATE TABLE IF NOT EXISTS payment_allocations (
  alloc_id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL DEFAULT 'payment' CHECK (source IN ('payment','cash','credit')),
  pay_id INTEGER,
  cash_entry_id INTEGER REFERENCES cash_entries(entry_id),
  batch_id TEXT,
  doc_kind TEXT NOT NULL DEFAULT 'invoice',
  doc_id INTEGER NOT NULL DEFAULT 0,
  line_id INTEGER,
  carried INTEGER NOT NULL DEFAULT 0,
  amount REAL NOT NULL CHECK (amount != 0),
  pay_date TEXT NOT NULL DEFAULT '',
  clerk TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_payalloc_pay ON payment_allocations(pay_id);
CREATE INDEX IF NOT EXISTS idx_payalloc_batch ON payment_allocations(batch_id);
CREATE INDEX IF NOT EXISTS idx_payalloc_doc ON payment_allocations(doc_kind, doc_id);
CREATE INDEX IF NOT EXISTS idx_payalloc_line ON payment_allocations(line_id);
CREATE INDEX IF NOT EXISTS idx_payalloc_cash ON payment_allocations(cash_entry_id);

-- Money received against a work order, a rental ticket, a sale, a
-- quote, or a change order (Jason 2026-10-23, universality; build 'v'
-- adds the change order): the same ledger shape as collections, which
-- stays the invoice ledger. kind 'payment' is money in; kind 'credit'
-- is a credit memo applied against the document. Cash In settlements
-- through the Cash tab carry cash_entry_id, exactly as on collections
-- — one money event, two views. When the document is invoiced, its
-- rows are mirrored into collections with carried_from set, so the
-- invoice nets them out exactly once and no ledger counts the money
-- twice. id shares the one pay-key space with collections (see there).
CREATE TABLE IF NOT EXISTS doc_collections (
  id INTEGER PRIMARY KEY,
  pay_id TEXT NOT NULL UNIQUE,
  batch_id TEXT,
  pay_date TEXT NOT NULL,
  doc_kind TEXT NOT NULL CHECK (doc_kind IN ('wo','ticket','sale','quote','change')),
  doc_id INTEGER NOT NULL,
  customer_id INTEGER,
  method TEXT NOT NULL,
  amount REAL NOT NULL CHECK (amount != 0),
  ref_no TEXT,
  notes TEXT,
  kind TEXT NOT NULL DEFAULT 'payment' CHECK (kind IN ('payment','credit')),
  cm_id INTEGER,
  clerk TEXT,
  applied_amount REAL,
  unapplied_amount REAL NOT NULL DEFAULT 0,
  cash_entry_id INTEGER REFERENCES cash_entries(entry_id)
);
CREATE INDEX IF NOT EXISTS idx_dcol_doc ON doc_collections(doc_kind, doc_id);
CREATE INDEX IF NOT EXISTS idx_dcol_cm ON doc_collections(cm_id);
CREATE INDEX IF NOT EXISTS idx_dcol_batch ON doc_collections(batch_id);

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

CREATE TABLE IF NOT EXISTS mixed_presets (
  preset_id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  kinds TEXT NOT NULL DEFAULT '',
  time_mode TEXT NOT NULL DEFAULT 'once',
  date_from TEXT NOT NULL DEFAULT '',
  date_to TEXT NOT NULL DEFAULT '',
  month TEXT NOT NULL DEFAULT '',
  customer_id INTEGER,
  filter_text TEXT NOT NULL DEFAULT '',
  sort_col INTEGER NOT NULL DEFAULT 0,
  sort_dir TEXT NOT NULL DEFAULT 'desc',
  created_at TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now'))
);

-- Compliance packs (pre-built templates) and per-unit checklists.
-- trigger: per_job | per_shift | calendar | event | manufacturer
-- basis: standard | manufacturer | company  (company = shop-policy default
-- where the standard is silent; never presented as a regulatory requirement)
CREATE TABLE IF NOT EXISTS compliance_packs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  pack_id TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  blurb TEXT
);

CREATE TABLE IF NOT EXISTS compliance_requirements (
  req_id INTEGER PRIMARY KEY AUTOINCREMENT,
  pack_id INTEGER NOT NULL REFERENCES compliance_packs(id),
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
  asset_id INTEGER NOT NULL REFERENCES assets(id),
  pack_id INTEGER REFERENCES compliance_packs(id),
  req_id INTEGER REFERENCES compliance_requirements(req_id),
  custom_name TEXT,
  trigger TEXT NOT NULL,
  interval_months REAL,
  deployed_backstop_months REAL,
  last_done TEXT,
  next_due TEXT,
  notes TEXT,
  performer_id INTEGER REFERENCES vendors(vendor_id)
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
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  token TEXT NOT NULL UNIQUE,
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
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  key TEXT NOT NULL UNIQUE,
  value TEXT NOT NULL DEFAULT ''
);

-- Data-book documents per unit (certifications, drawings, instructions,
-- test records). Files live in a docs/ folder next to the book and ride
-- inside every backup archive, like ticket photos.
CREATE TABLE IF NOT EXISTS unit_docs (
  doc_id INTEGER PRIMARY KEY AUTOINCREMENT,
  asset_id INTEGER NOT NULL REFERENCES assets(id),
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
  contact TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS asset_certs (
  cert_id INTEGER PRIMARY KEY AUTOINCREMENT,
  asset_id INTEGER NOT NULL REFERENCES assets(id),
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
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  alert_key TEXT NOT NULL UNIQUE,
  until_ts INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS purchase_orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  po_no TEXT NOT NULL,
  customer_id INTEGER NOT NULL REFERENCES customers(id),
  expire TEXT,
  cost_code TEXT,
  notes TEXT,
  asset_id INTEGER REFERENCES assets(id),
  ack_at TEXT,
  ack_by TEXT,
  total REAL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'Open',
  UNIQUE (customer_id, po_no)
);

CREATE TABLE IF NOT EXISTS wo_lines (
  line_id INTEGER PRIMARY KEY AUTOINCREMENT,
  wo_id INTEGER NOT NULL REFERENCES work_orders(id),
  item TEXT DEFAULT '',
  description TEXT DEFAULT '',
  category TEXT DEFAULT 'Other',
  qty REAL DEFAULT 1,
  rate REAL DEFAULT 0,
  uom TEXT DEFAULT 'Each',
  amount REAL DEFAULT 0,
  line_note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_wo_lines_wo ON wo_lines(wo_id);

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
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  slot_key TEXT NOT NULL UNIQUE,
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
  soft_ticket_id INTEGER NOT NULL,
  data_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
