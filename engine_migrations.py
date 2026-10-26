"""Legacy database migration ledger.

This module owns compatibility upgrades for databases created by older
FleetSheet builds.  The current schema lives in schema.sql; this file only
transforms older databases forward and is intentionally idempotent.
"""
from __future__ import annotations

import sqlite3
from decimal import Decimal, ROUND_HALF_UP
import re

from engine_core import (
    _money,
    _mf,
    _ms,
    parse_date,
    _parse,
    terms_days,
    _row_get,
    require_clerk,
    list_crew,
    add_crew,
    drop_crew,
    _reserve_counter,
    _next_doc,
    _set_quote_link,
    lookups,
    period_bounds,
    _ensure_device_tables,
    get_option,
    set_option,
    _pbkdf2,
    pin_is_set,
    get_pin_secret,
    set_pin,
    verify_pin,
    clear_pin,
    PIN_SECURITY_QUESTIONS,
    set_pin_security,
    validate_pin_security,
    pin_security_is_set,
    pin_security_questions,
    verify_pin_security,
    _new_device_token,
    issue_device,
    list_devices,
    get_device,
    device_check,
    touch_device,
    revoke_device,
    rotate_device,
    _shift_months,
    _pos_or_none,
    CENT,
    SCHEMA,
    SEED_PACKS,
    _LOCAL,
    _TMP,
    OPEN_STATUSES,
    BLOCKING,
    ALLOWED_NEXT,
    COND_RANK,
    CASH_METHODS,
    QUOTE_NEXT,
    PC_IN_CATS,
    PC_OUT_CATS,
    EXPORT_WHENS,
    EXPORT_HOWS,
    DEVICE_GRACE_HOURS,
    TRIGGER_LABELS,
    BASIS_LABELS,
    DUE_SOON_DAYS,
    BACKUP_KEEP,
    backup_folder,
    set_backup_dir,
    backup_status,
    list_backups,
    prune_backups,
    run_backup,
    validate_backup_file,
    validate_backup_archive,
    restore_backup,
    restore_backup_archive,
    read_backup_file,
    sweep_orphan_photos,
    PHOTO_MAX_BYTES,
    PHOTO_EXTS,
    photo_dir,
    photo_ext_for,
    validate_photo_blob,
    safe_photo_name,
    DOC_MAX_BYTES,
    DOC_KINDS,
    doc_dir,
    doc_ext_for,
    validate_doc_blob,
    safe_doc_name,
    save_unit_doc,
    list_unit_docs,
    get_unit_doc,
    read_unit_doc,
    delete_unit_doc,
    sweep_orphan_docs,
    list_company_phones,
    main_company_phone,
    add_company_phone,
    del_company_phone,
    set_main_company_phone,
)

from engine_accounting import (
    next_invoice_id,
    create_invoice,
    invoice_has_lines,
    _next_pay_id,
    _refresh_invoice_status,
    record_payment,
    next_cm_id,
    credit_applied,
    credit_open,
    _apply_credit_rows,
    issue_credit_memo,
    apply_open_credit,
    list_open_credits,
    list_open_invoices,
    big_fish_invoices,
    next_quote_id,
    next_co_id,
    _line_amount,
    save_quote,
    set_quote_status,
    issue_change_order,
    quote_totals,
    quote_pack,
    convert_quote,
    next_pc_id,
    petty_balance,
    petty_book,
    set_pc_float,
    record_petty,
    invoice_totals,
    invoice_balance,
    invoice_locked,
    set_invoice_po,
    upsert_po_record,
    po_record,
    backfill_po_records,
    po_check,
    quote_check,
    save_invoice_doc,
    get_invoice_doc,
    read_invoice_doc,
    delete_invoice_doc,
    invoice_job_box,
    INV_DOC_KINDS,
    add_invoice_line,
    drop_invoice_line,
    _ensure_saved_exports,
    list_saved_exports,
    save_export,
    delete_saved_export,
    next_customer_id,
    save_customer,
    report_invoicing,
    report_revenue,
    report_recap,
)

from engine_compliance import (
    checklist_next_due,
    checklist_status,
    list_packs,
    get_pack,
    assign_pack,
    unit_packs,
    add_custom_requirement,
    update_checklist_item,
    remove_checklist_item,
    record_completion,
    item_history,
    unit_checklist,
    compliance_summary,
    fleet_compliance_watch,
    list_vendors,
    save_vendor,
    delete_vendor,
    set_checklist_performer,
    ensure_cert_tables,
    save_cert,
    get_cert,
    list_certs,
    fleet_certs,
    cert_status,
    operative_cert_expiry,
    migrate_legacy_cert_expiry,
)

from engine_assets import (
    ticket_money,
    sync_flat_charges_to_lines,
)



def _ensure_customer_site_business_tables(con: sqlite3.Connection) -> None:
    con.execute("""CREATE TABLE IF NOT EXISTS customer_locations (
      location_id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER NOT NULL REFERENCES customers(id),
      location_name TEXT NOT NULL, street TEXT, street2 TEXT, city TEXT, state TEXT, zip TEXT,
      is_primary INTEGER NOT NULL DEFAULT 0)""")
    con.execute("""CREATE TABLE IF NOT EXISTS customer_contacts (
      contact_id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER NOT NULL REFERENCES customers(id),
      name TEXT NOT NULL, role TEXT, phone TEXT, email TEXT, is_primary INTEGER NOT NULL DEFAULT 0)""")
    scols=[r[1] for r in con.execute("PRAGMA table_info(sites)")]
    for col in ("street","street2","city","state","zip"):
        if col not in scols:
            con.execute(f"ALTER TABLE sites ADD COLUMN {col} TEXT")
    ccols=[r[1] for r in con.execute("PRAGMA table_info(change_orders)")]
    if "po" not in ccols:
        con.execute("ALTER TABLE change_orders ADD COLUMN po TEXT")

def migrate_legacy_schema(con: sqlite3.Connection) -> None:
    _ensure_customer_site_business_tables(con)
    # Build 'v': once a book carries surrogate keys, the pre-'v' data
    # backfills below (written against the number-keyed shape) must
    # never run again — their work is done and their column references
    # no longer exist. Fresh books are born re-keyed and skip them too.
    _rekeyed = "id" in [r[1] for r in con.execute("PRAGMA table_info(invoices)")]

    cols = [r[1] for r in con.execute("PRAGMA table_info(work_orders)")]
    if cols and not _rekeyed and "invoice_no" not in cols:
        con.execute("ALTER TABLE work_orders ADD COLUMN invoice_no TEXT")
    # Work-order form fields (ref_ticket, wo_date, item, qty, cost) were
    # added lazily by save_wo but never to the startup migration, so
    # viewing an existing WO on a DB where none was ever saved raised
    # IndexError (row["ref_ticket"]). Ensure them here.
    if cols:
        for col, ddl in [("ref_ticket", "TEXT"), ("wo_date", "TEXT"), ("item", "TEXT"),
                         ("qty", "REAL DEFAULT 1"), ("cost", "REAL DEFAULT 0")]:
            if col not in cols:
                con.execute(f"ALTER TABLE work_orders ADD COLUMN {col} {ddl}")
    # WO PO reference (2026-10-15): the Job Info popup already has a PO #
    # field, but /wo/save ignored it and work_orders had no column, so a
    # PO typed on a WO was silently lost. The column makes it stick.
    if cols and "po" not in cols:
        con.execute("ALTER TABLE work_orders ADD COLUMN po TEXT")
    # Work-order types (2026-10-15): the wo_type vocabulary changed, and
    # demo + v1.0.0 DBs still carry the old values ('Inspection',
    # 'Preventive', 'Repair', 'Calibration'). save_wo rejects anything
    # not in the lookups, so no old WO could be edited — the save
    # bounced to ?err= with nothing changed. Remap in place.
    # Idempotent: once remapped, no rows match the old values.
    if cols:
        con.execute("UPDATE work_orders SET work_type='Inspection / cert' WHERE work_type='Inspection'")
        con.execute("UPDATE work_orders SET work_type='PM / service' WHERE work_type='Preventive'")
        con.execute("UPDATE work_orders SET work_type='Repair — minor' WHERE work_type='Repair'")
        con.execute("UPDATE work_orders SET work_type='Inspection / cert' WHERE work_type='Calibration'")
    # Cert kinds (Issue 4, 2026-10-15): the vocabulary moved from hardcoded
    # CERT_KINDS slugs to lookups display strings, and demo + v1.0.0 DBs
    # still carry the old slugs ('function_test', ...). Remap in place.
    # Idempotent: once remapped, no rows match the old values.
    accols = [r[1] for r in con.execute("PRAGMA table_info(asset_certs)")]
    if accols and "kind" in accols:
        con.execute("UPDATE asset_certs SET kind='Certification' WHERE kind='certification'")
        con.execute("UPDATE asset_certs SET kind='Calibration' WHERE kind='calibration'")
        con.execute("UPDATE asset_certs SET kind='Function test' WHERE kind='function_test'")
        con.execute("UPDATE asset_certs SET kind='Other' WHERE kind='other'")
    scols = [r[1] for r in con.execute("PRAGMA table_info(sites)")]
    if scols and "tax_exempt" not in scols:
        con.execute("ALTER TABLE sites ADD COLUMN tax_exempt INTEGER NOT NULL DEFAULT 0")
    ccols = [r[1] for r in con.execute("PRAGMA table_info(company)")]
    if ccols and "tooltips" not in ccols:
        con.execute("ALTER TABLE company ADD COLUMN tooltips INTEGER NOT NULL DEFAULT 1")
    if ccols and "yard_loc_id" not in ccols:
        con.execute("ALTER TABLE company ADD COLUMN yard_loc_id TEXT")
    if ccols and "backup_schedule" not in ccols:
        con.execute("ALTER TABLE company ADD COLUMN backup_schedule TEXT NOT NULL DEFAULT 'weekly'")
    if ccols and "backup_every_days" not in ccols:
        con.execute("ALTER TABLE company ADD COLUMN backup_every_days INTEGER NOT NULL DEFAULT 7")
    tcols = [r[1] for r in con.execute("PRAGMA table_info(tickets)")]
    if tcols and "customer_transport" not in tcols:
        con.execute("ALTER TABLE tickets ADD COLUMN customer_transport INTEGER NOT NULL DEFAULT 0")
    if tcols and "haul_by" not in tcols:
        con.execute("ALTER TABLE tickets ADD COLUMN haul_by TEXT NOT NULL DEFAULT 'we'")
        con.execute("ALTER TABLE tickets ADD COLUMN deliver_to TEXT NOT NULL DEFAULT 'job_site'")
        # Legacy compat: customer_transport=1 meant "customer hauls, possession at yard".
        con.execute("UPDATE tickets SET haul_by='customer', deliver_to='our_yard' "
                    "WHERE customer_transport=1")
        tcols = [r[1] for r in con.execute("PRAGMA table_info(tickets)")]
    if tcols and "deliver_to" not in tcols:
        con.execute("ALTER TABLE tickets ADD COLUMN deliver_to TEXT NOT NULL DEFAULT 'job_site'")
    if tcols and "haul_note" not in tcols:
        con.execute("ALTER TABLE tickets ADD COLUMN haul_note TEXT NOT NULL DEFAULT ''")
    if tcols and "deliver_note" not in tcols:
        con.execute("ALTER TABLE tickets ADD COLUMN deliver_note TEXT NOT NULL DEFAULT ''")
    if tcols and "fit_override" not in tcols:
        # Shop flow (Jason, 2026-10-21): no un-overridable blocks anywhere.
        # When the operator deliberately dispatches despite a non-PASS FIT,
        # the override is stamped here — "<FIT value> · by <clerk> · <when>"
        # — and shown wherever the ticket's FIT shows. The condition switch
        # never governs FIT; this record is the audit trail on the ticket.
        con.execute("ALTER TABLE tickets ADD COLUMN fit_override TEXT NOT NULL DEFAULT ''")
    if tcols and "billed_note" not in tcols:
        # Noted passages (Jason, 2026-10-21): a ticket moved to Billed with
        # no invoice behind it (billed on the customer's own portal) is
        # marked out of flow — the passage note is stamped here,
        # "<note> · by <clerk> · <when>", and shown on the ticket page
        # wherever its status shows.
        con.execute("ALTER TABLE tickets ADD COLUMN billed_note TEXT NOT NULL DEFAULT ''")
    if tcols and "transport_fee" not in tcols:
        con.execute("ALTER TABLE tickets ADD COLUMN transport_fee REAL NOT NULL DEFAULT 0")
    if tcols and "tax_loc_id" not in tcols:
        con.execute("ALTER TABLE tickets ADD COLUMN tax_loc_id TEXT REFERENCES jurisdictions(loc_id)")
    if tcols and "soft_reserve" not in tcols:
        # Walkthrough #3 sweep: a PO soft-reserve never blocks an interim
        # booking — the operator picks which reservation wins.
        con.execute("ALTER TABLE tickets ADD COLUMN soft_reserve INTEGER NOT NULL DEFAULT 0")
        con.execute("""UPDATE tickets SET soft_reserve=1
                       WHERE status='Reserved' AND po IS NOT NULL AND po != ''""")
    con.execute("""CREATE TABLE IF NOT EXISTS pending_bookings (
      pending_id INTEGER PRIMARY KEY AUTOINCREMENT,
      soft_ticket_id TEXT NOT NULL,
      data_json TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT (datetime('now')))""")
    # Global line-item row (2026-10-15): every line row uses the inv_cat
    # Type list (Rental/Labor/Item/Mileage/Freight/Fuel/Consumable/
    # Mobilization/Demobilization/Other) and an inv_uom Unit. Quote and
    # change-order lines still carried the old lowercase kind list, and
    # neither had a Unit column. SQLite cannot ALTER a CHECK — recreate
    # both tables, remapping old kinds. Idempotent: once the inv_cat
    # CHECK is in the DDL the guard is false.
    for _tbl in ("quote_lines", "change_order_lines"):
        _tsql = con.execute("SELECT sql FROM sqlite_master WHERE name=?", (_tbl,)).fetchone()
        _old_checks = ("kind IN ('item','unit','labor','freight','other','rental','service','transport')",
                       "kind IN ('rental','service','transport','other')")
        _old = next((s for s in _old_checks if _tsql and _tsql["sql"] and s in _tsql["sql"]), None)
        if not _old:
            continue
        _new = _tsql["sql"].replace(
            _old,
            "kind IN ('Rental','Labor','Item','Mileage','Freight','Fuel','Consumable','Mobilization','Demobilization','Other')", 1)
        # Unit column: quote_lines has rate_unit; change_order_lines does not.
        # Item column: both gain the line's Item text (the combo's typed
        # text was never saved for non-Rental lines).
        if _tbl == "quote_lines":
            _new = _new.replace("rate_unit TEXT,", "rate_unit TEXT,\n  uom TEXT DEFAULT 'Each',", 1)
            _new = _new.replace("asset_id TEXT REFERENCES assets(asset_id),",
                                "asset_id TEXT REFERENCES assets(asset_id),\n  item TEXT DEFAULT '',", 1)
        else:
            _new = _new.replace("rate REAL NOT NULL DEFAULT 0,", "rate REAL NOT NULL DEFAULT 0,\n  uom TEXT DEFAULT 'Each',", 1)
            _new = _new.replace("co_no TEXT NOT NULL REFERENCES change_orders(co_no),",
                                "co_no TEXT NOT NULL REFERENCES change_orders(co_no),\n  item TEXT DEFAULT '',", 1)
        # The table name may be quoted (CREATE TABLE "quote_lines") after a
        # prior RENAME TO, and may carry IF NOT EXISTS — one regex covers
        # all four spellings.
        _new = re.sub(rf"CREATE TABLE (IF NOT EXISTS )?\"?{_tbl}\"?",
                      f"CREATE TABLE _{_tbl}_new", _new, count=1)
        con.commit()
        con.execute("PRAGMA foreign_keys=OFF")
        try:
            con.execute(f"DROP TABLE IF EXISTS _{_tbl}_new")
            con.execute(_new)
            _cols = [f'"{r[1]}"' for r in con.execute(f"PRAGMA table_info({_tbl})")]
            _sel = []
            for _c in _cols:
                if _c == '"kind"':
                    _sel.append("CASE \"kind\" WHEN 'item' THEN 'Item' WHEN 'unit' THEN 'Rental' WHEN 'labor' THEN 'Labor' WHEN 'freight' THEN 'Freight' WHEN 'other' THEN 'Other' WHEN 'rental' THEN 'Rental' WHEN 'service' THEN 'Labor' WHEN 'transport' THEN 'Freight' ELSE 'Other' END")
                else:
                    _sel.append(_c)
            _cols.append('"uom"')
            _sel.append("'Each'")
            con.execute(f"INSERT INTO _{_tbl}_new ({', '.join(_cols)}) SELECT {', '.join(_sel)} FROM {_tbl}")
            con.execute(f"DROP TABLE {_tbl}")
            con.execute(f"ALTER TABLE _{_tbl}_new RENAME TO {_tbl}")
            con.commit()
        finally:
            con.execute("PRAGMA foreign_keys=ON")
    # Global line-item row (2026-10-15): WO lines and credit-memo lines
    # gain a Type (inv_cat) + Unit (inv_uom). Invoice lines gain an Item
    # column — the create form's Item text had nowhere to live.
    for _tbl in ("wo_lines", "credit_memos"):
        _cols = [r[1] for r in con.execute(f"PRAGMA table_info({_tbl})")]
        if _cols and "category" not in _cols:
            con.execute(f"ALTER TABLE {_tbl} ADD COLUMN category TEXT DEFAULT 'Other'")
        if _cols and "uom" not in _cols:
            con.execute(f"ALTER TABLE {_tbl} ADD COLUMN uom TEXT DEFAULT 'Each'")
    # Credit memo multi-line (Jason 2026-10-21): line items move to
    # their own table, mirroring invoice_lines. Backfill is idempotent —
    # a memo with zero lines gains exactly one, carrying the memo's face
    # verbatim (never recomputed, so totals cannot drift); the rate is
    # derived from the legacy qty when the old columns exist. Legacy
    # columns (item, item_desc, qty, rate) exist only on some books —
    # each read is guarded by the PRAGMA column list.
    con.execute("""CREATE TABLE IF NOT EXISTS credit_memo_lines (
      line_id INTEGER PRIMARY KEY AUTOINCREMENT,
      cm_no TEXT NOT NULL REFERENCES credit_memos(cm_no),
      category TEXT NOT NULL DEFAULT 'Other',
      item TEXT DEFAULT '',
      description TEXT NOT NULL DEFAULT '',
      qty REAL NOT NULL DEFAULT 1,
      uom TEXT NOT NULL DEFAULT 'Each',
      rate REAL NOT NULL DEFAULT 0,
      amount REAL NOT NULL DEFAULT 0,
      tax_exempt INTEGER NOT NULL DEFAULT 0,
      source_invoice_no TEXT NOT NULL DEFAULT '',
      source_line_id INTEGER NOT NULL DEFAULT 0)""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_cmlines_cm ON credit_memo_lines(cm_no)")
    _cmcols = [r[1] for r in con.execute("PRAGMA table_info(credit_memos)")]
    if _cmcols and not _rekeyed:
        for _cm in con.execute("SELECT * FROM credit_memos").fetchall():
            if con.execute("SELECT COUNT(*) FROM credit_memo_lines WHERE cm_no=?",
                           (_cm["cm_no"],)).fetchone()[0]:
                continue
            _face = _cm["face_amount"]
            _qty = 1.0
            if "qty" in _cmcols:
                try:
                    _q = float(_row_get(_cm, "qty") or 0)
                except (TypeError, ValueError):
                    _q = 0.0
                if _q > 0:
                    _qty = _q
            _desc = ""
            if "item_desc" in _cmcols:
                _desc = (_row_get(_cm, "item_desc") or "").strip()
            if not _desc:
                _desc = _cm["reason"] or ""
            _item = ((_row_get(_cm, "item") or "").strip()
                     if "item" in _cmcols else "")
            _cat = ((_row_get(_cm, "category") or "").strip()
                    if "category" in _cmcols else "") or "Other"
            _uom = ((_row_get(_cm, "uom") or "").strip()
                    if "uom" in _cmcols else "") or "Each"
            con.execute(
                """INSERT INTO credit_memo_lines(cm_no, category, item, description, qty, uom, rate, amount, tax_exempt, source_invoice_no, source_line_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (_cm["cm_no"], _cat, _item, _desc, _qty, _uom,
                 round(float(_face) / _qty, 2), _face, 0, "", 0),
            )
    _icols = [r[1] for r in con.execute("PRAGMA table_info(invoice_lines)")]
    if _icols and "item" not in _icols:
        con.execute("ALTER TABLE invoice_lines ADD COLUMN item TEXT DEFAULT ''")
    # Existing WO lines were invoiced as Labor/Each before the Type
    # column existed — keep that effective meaning.
    con.execute("UPDATE wo_lines SET category='Labor' WHERE category IS NULL OR category=''")
    con.execute("UPDATE wo_lines SET uom='Each' WHERE uom IS NULL OR uom=''")
    # Sites: loc_id becomes nullable — no tax jurisdiction autofill (Jason
    # 2026-10-04). A custom site starts unset; the operator sets it on the
    # site page. Idempotent: once the NOT NULL is gone the guard is false.
    # NOTE: the rebuild commits first — PRAGMA foreign_keys=OFF is ignored
    # inside a transaction, and tickets references sites(site_id).
    ssql = con.execute("SELECT sql FROM sqlite_master WHERE name='sites'").fetchone()
    if ssql and ssql["sql"] and "loc_id TEXT NOT NULL" in ssql["sql"]:
        new_sql = ssql["sql"].replace("loc_id TEXT NOT NULL", "loc_id TEXT", 1)
        new_sql = new_sql.replace("CREATE TABLE IF NOT EXISTS sites",
                                  "CREATE TABLE _sites_new", 1)
        new_sql = new_sql.replace("CREATE TABLE sites",
                                  "CREATE TABLE _sites_new", 1)
        con.commit()
        con.execute("PRAGMA foreign_keys=OFF")
        try:
            con.execute("DROP TABLE IF EXISTS _sites_new")
            con.execute(new_sql)
            cols = [f'"{r[1]}"' for r in con.execute("PRAGMA table_info(sites)")]
            con.execute(f"INSERT INTO _sites_new ({', '.join(cols)}) SELECT {', '.join(cols)} FROM sites")
            con.execute("DROP TABLE sites")
            con.execute("ALTER TABLE _sites_new RENAME TO sites")
            con.commit()
        finally:
            con.execute("PRAGMA foreign_keys=ON")
    cocols = [r[1] for r in con.execute("PRAGMA table_info(company)")]
    if cocols and "next_cm" not in cocols:
        con.execute("ALTER TABLE company ADD COLUMN next_cm INTEGER NOT NULL DEFAULT 1001")
    colcols = [r[1] for r in con.execute("PRAGMA table_info(collections)")]
    if colcols and "kind" not in colcols:
        con.execute("ALTER TABLE collections ADD COLUMN kind TEXT NOT NULL DEFAULT 'payment'")
    if colcols and not _rekeyed and "cm_no" not in colcols:
        con.execute("ALTER TABLE collections ADD COLUMN cm_no TEXT")
    if not _rekeyed:
        con.execute("CREATE INDEX IF NOT EXISTS idx_col_cm ON collections(cm_no)")
    # Batch rework (2026-10-15): one received payment allocated across
    # several invoices posts one collections row per invoice, all sharing
    # a batch id — the audit groups on it. Legacy rows keep batch_id
    # NULL and group by their own pay_id.
    if colcols and "batch_id" not in colcols:
        con.execute("ALTER TABLE collections ADD COLUMN batch_id TEXT")
    con.execute("CREATE INDEX IF NOT EXISTS idx_col_batch ON collections(batch_id)")
    cocols = [r[1] for r in con.execute("PRAGMA table_info(company)")]
    if cocols and "next_pc" not in cocols:
        con.execute("ALTER TABLE company ADD COLUMN next_pc INTEGER NOT NULL DEFAULT 1001")
    if cocols and "pc_float" not in cocols:
        con.execute("ALTER TABLE company ADD COLUMN pc_float REAL NOT NULL DEFAULT 200")
    if cocols and "next_quote" not in cocols:
        con.execute("ALTER TABLE company ADD COLUMN next_quote INTEGER NOT NULL DEFAULT 1001")
    if cocols and "next_co" not in cocols:
        con.execute("ALTER TABLE company ADD COLUMN next_co INTEGER NOT NULL DEFAULT 1001")
    tcols = [r[1] for r in con.execute("PRAGMA table_info(tickets)")]
    if tcols and not _rekeyed and "quote_no" not in tcols:
        con.execute("ALTER TABLE tickets ADD COLUMN quote_no TEXT")
    icols = [r[1] for r in con.execute("PRAGMA table_info(invoices)")]
    if icols and not _rekeyed and "quote_no" not in icols:
        con.execute("ALTER TABLE invoices ADD COLUMN quote_no TEXT")
    # PO detail: blanket-PO expiry, cost code, other PO requirements.
    for _pocol in ("po_expire", "po_cost_code", "po_notes"):
        if icols and _pocol not in icols:
            con.execute(f"ALTER TABLE invoices ADD COLUMN {_pocol} TEXT")
    # PO record (Q6): the expiry lives on the PO itself — one shared record
    # per (customer, PO#) that every invoice carrying the PO reads. Backfill
    # carries existing invoice-level values over; nothing is lost.
    backfill_po_records(con)
    wcols = [r[1] for r in con.execute("PRAGMA table_info(work_orders)")]
    if wcols and not _rekeyed and "quote_no" not in wcols:
        con.execute("ALTER TABLE work_orders ADD COLUMN quote_no TEXT")
    if cocols and "desk_name" not in cocols:
        con.execute("ALTER TABLE company ADD COLUMN desk_name TEXT")
    if cocols and "yard_state" not in cocols:
        con.execute("ALTER TABLE company ADD COLUMN yard_state TEXT")
    if cocols and "yard_country" not in cocols:
        con.execute("ALTER TABLE company ADD COLUMN yard_country TEXT DEFAULT 'US'")
    if cocols and "backup_dir" not in cocols:
        con.execute("ALTER TABLE company ADD COLUMN backup_dir TEXT")
    if cocols and "last_backup" not in cocols:
        con.execute("ALTER TABLE company ADD COLUMN last_backup TEXT")
    cocols = [r[1] for r in con.execute("PRAGMA table_info(company)")]
    if cocols and "next_wo" not in cocols:
        con.execute("ALTER TABLE company ADD COLUMN next_wo INTEGER NOT NULL DEFAULT 101")
    if cocols and "next_payment" not in cocols:
        con.execute("ALTER TABLE company ADD COLUMN next_payment INTEGER NOT NULL DEFAULT 1")
    for col in (
        "clerk", "out_condition", "out_note", "out_meter", "out_photo", "out_by", "out_at",
        "out_src",
        "in_condition", "in_note", "in_meter", "in_photo", "in_by", "in_at",
        "in_src",
    ):
        if tcols and col not in tcols:
            con.execute(f"ALTER TABLE tickets ADD COLUMN {col} TEXT")
    for table, col in (
        ("collections", "clerk"),
        ("credit_memos", "clerk"),
        ("petty_cash", "clerk"),
        ("quotes", "clerk"),
        ("change_orders", "clerk"),
    ):
        names = [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
        if names and col not in names:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT")
    icols = [r[1] for r in con.execute("PRAGMA table_info(invoices)")]
    if icols and "po" not in icols:
        con.execute("ALTER TABLE invoices ADD COLUMN po TEXT")
    ilcols = [r[1] for r in con.execute("PRAGMA table_info(invoice_lines)")]
    for col, typ, default in (("tax_rate","REAL","0"),("tax_amount","REAL","0"),("tax_exempt","INTEGER","0"),("tax_name","TEXT","''"),("tax_loc","TEXT","''"),("source_type","TEXT","''"),("source_id","TEXT","''")):
        if ilcols and col not in ilcols:
            con.execute(f"ALTER TABLE invoice_lines ADD COLUMN {col} {typ} NOT NULL DEFAULT {default}")
    colcols = [r[1] for r in con.execute("PRAGMA table_info(collections)")]
    if colcols and "applied_amount" not in colcols:
        con.execute("ALTER TABLE collections ADD COLUMN applied_amount REAL")
    if colcols and "unapplied_amount" not in colcols:
        con.execute("ALTER TABLE collections ADD COLUMN unapplied_amount REAL NOT NULL DEFAULT 0")
    # Compliance-pack tables are new in this build; add the deployed-backstop
    # column to any database created before it existed in schema.sql.
    for table in ("compliance_requirements", "equipment_compliance"):
        names = [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
        if names and "deployed_backstop_months" not in names:
            con.execute(f"ALTER TABLE {table} ADD COLUMN deployed_backstop_months REAL")
    # Compliance: "requires certified operator" flag on equipment (the person
    # and their certification are never tracked — equipment only).
    acols = [r[1] for r in con.execute("PRAGMA table_info(assets)")]
    if acols and "cert_operator" not in acols:
        con.execute("ALTER TABLE assets ADD COLUMN cert_operator INTEGER NOT NULL DEFAULT 0")
    # Unit designation (Batch 3, Oct 23): Fleet / Stock / Plant presets,
    # operator-extensible. Existing rows backfill to 'Fleet'.
    if acols and "designation" not in acols:
        con.execute("ALTER TABLE assets ADD COLUMN designation TEXT NOT NULL DEFAULT 'Fleet'")
    if acols:
        con.execute("UPDATE assets SET designation = 'Fleet' "
                    "WHERE designation IS NULL OR designation = ''")
    # Asset lifecycle status (Phase 5, Oct 24): Active / Retired /
    # De-listed, switched on the asset form. Existing rows backfill to
    # 'Active' — every asset already in a book stands in service until
    # the operator moves it.
    if acols and "status" not in acols:
        con.execute("ALTER TABLE assets ADD COLUMN status TEXT NOT NULL DEFAULT 'Active'")
    if acols:
        con.execute("UPDATE assets SET status = 'Active' "
                    "WHERE status IS NULL OR status = ''")
    # Company + customer address split and phone lists (2026-09-26).
    # Old `address` / `phone` columns stay for legacy reads (letterhead).
    # Street line 2 (2026-10-02): optional second line for foreign addresses
    # and "c/o Accounts Payable" style entries.
    ccols = [r[1] for r in con.execute("PRAGMA table_info(company)")]
    for col in ("addr_street", "addr_street2", "addr_city", "addr_state", "addr_zip"):
        if ccols and col not in ccols:
            con.execute(f"ALTER TABLE company ADD COLUMN {col} TEXT")
    cucols = [r[1] for r in con.execute("PRAGMA table_info(customers)")]
    for col in ("bill_street", "bill_street2", "bill_city", "bill_state", "bill_zip"):
        if cucols and col not in cucols:
            con.execute(f"ALTER TABLE customers ADD COLUMN {col} TEXT")
    crow = con.execute("SELECT phone FROM company WHERE id=1").fetchone()
    if crow and (crow["phone"] or "").strip():
        if con.execute("SELECT COUNT(*) FROM company_phones").fetchone()[0] == 0:
            con.execute(
                "INSERT INTO company_phones (label, number, is_main, sort) VALUES ('Main', ?, 1, 0)",
                ((crow["phone"] or "").strip(),),
            )
    if not _rekeyed:
        for cu in con.execute("SELECT customer_id, phone FROM customers").fetchall():
            if (cu["phone"] or "").strip():
                if con.execute(
                    "SELECT COUNT(*) FROM customer_phones WHERE customer_id=?",
                    (cu["customer_id"],),
                ).fetchone()[0] == 0:
                    con.execute(
                        "INSERT INTO customer_phones (customer_id, label, number, is_main, sort)"
                        " VALUES (?, 'Main', ?, 1, 0)",
                        (cu["customer_id"], (cu["phone"] or "").strip()),
                    )
    # Rate-model redesign (2026-09-27): one rate field everywhere.
    # Assets gain a single rate_unit/rate_value pair plus an hour meter, back-
    # filled once from the old six-column layout. The old six columns stay in
    # place, frozen, for historical reads and exports.
    acols = [r[1] for r in con.execute("PRAGMA table_info(assets)")]
    if acols and "rate_unit" not in acols:
        con.execute("ALTER TABLE assets ADD COLUMN rate_unit TEXT NOT NULL DEFAULT 'Day'")
    if acols and "rate_value" not in acols:
        con.execute("ALTER TABLE assets ADD COLUMN rate_value REAL NOT NULL DEFAULT 0")
    if acols and "meter_hours" not in acols:
        con.execute("ALTER TABLE assets ADD COLUMN meter_hours REAL NOT NULL DEFAULT 0")
    for _unit, _col in (("Day", "daily_rate"), ("Week", "weekly_rate"),
                        ("Special", "special_rate"), ("Monthly", "monthly_rate"),
                        ("Standby", "standby_rate"), ("Yard", "yard_rate")):
        con.execute(
            f"UPDATE assets SET rate_unit=?, rate_value={_col} "
            "WHERE rate_unit='Day' AND rate_value=0 AND COALESCE(" + _col + ",0)>0",
            (_unit,),
        )
    # Cert-identity upgrade (Q5, 2026-09-27): certifications, calibrations,
    # and function tests are first-class records naming their asset. The
    # bare assets.cert_expire field migrates into real records (idempotent);
    # the column stays as a fallback read for stragglers.
    ensure_cert_tables(con)
    migrate_legacy_cert_expiry(con)
    # Tickets: widen the rate_type CHECK to the single-rate vocabulary
    # (Day/Week/Hour/Special, keeping Monthly/Standby/Yard legal for old
    # records) and rename special_override -> rate_value. The rename runs as a
    # full table rebuild so the column keeps its exact position; SQLite's
    # legacy alter path copies row data by column order. Idempotent: once the
    # new CHECK is in place the guard below is false forever.
    tcols = [r[1] for r in con.execute("PRAGMA table_info(tickets)")]
    tsql = con.execute("SELECT sql FROM sqlite_master WHERE name='tickets'").fetchone()
    old_check = "('Daily','Weekly','Monthly','Standby','Yard','Special')"
    new_check = "('Day','Week','Hour','Special','Monthly','Standby','Yard')"
    if (tcols and "special_override" in tcols and tsql and tsql["sql"]
            and old_check in tsql["sql"] and "special_override REAL" in tsql["sql"]):
        new_sql = tsql["sql"].replace(old_check, new_check).replace(
            "special_override REAL", "rate_value REAL")
        # SQLite may quote the table name after a prior RENAME TO — handle both.
        if 'CREATE TABLE "tickets"' in new_sql:
            new_sql = new_sql.replace('CREATE TABLE "tickets"', "CREATE TABLE _tickets_new", 1)
        else:
            new_sql = new_sql.replace("CREATE TABLE tickets", "CREATE TABLE _tickets_new", 1)
        con.execute("PRAGMA foreign_keys=OFF")
        try:
            con.execute("DROP TABLE IF EXISTS _tickets_new")
            con.execute(new_sql)
            old = [f'"{r[1]}"' for r in con.execute("PRAGMA table_info(tickets)")]
            new = ['"rate_value"' if c == '"special_override"' else c for c in old]
            sel = [("CASE \"rate_type\" WHEN 'Daily' THEN 'Day' WHEN 'Weekly' THEN 'Week'"
                    " ELSE \"rate_type\" END") if c == '"rate_type"' else c for c in old]
            con.execute(f"INSERT INTO _tickets_new ({', '.join(new)}) SELECT {', '.join(sel)} FROM tickets")
            con.execute("DROP TABLE tickets")
            con.execute("ALTER TABLE _tickets_new RENAME TO tickets")
        finally:
            con.execute("PRAGMA foreign_keys=ON")
        # Legacy adjective forms -> canonical units. 'Hour' had no legacy form.
        con.execute("UPDATE tickets SET rate_type='Day' WHERE rate_type='Daily'")
        con.execute("UPDATE tickets SET rate_type='Week' WHERE rate_type='Weekly'")
        tcols = [r[1] for r in con.execute("PRAGMA table_info(tickets)")]
    # Rental site optional (Jason 2026-10-07): the rental form no longer
    # carries a site, so tickets.site_id must accept NULL. Full table
    # rebuild (same pattern as the rate_type CHECK above). Idempotent:
    # once relaxed, the guard below is false forever.
    tsql = con.execute("SELECT sql FROM sqlite_master WHERE name='tickets'").fetchone()
    if tsql and tsql["sql"] and "site_id TEXT NOT NULL" in tsql["sql"]:
        new_sql = tsql["sql"].replace("site_id TEXT NOT NULL", "site_id TEXT", 1)
        # SQLite may quote the table name after a prior RENAME TO — handle both.
        if 'CREATE TABLE "tickets"' in new_sql:
            new_sql = new_sql.replace('CREATE TABLE "tickets"', "CREATE TABLE _tickets_new", 1)
        else:
            new_sql = new_sql.replace("CREATE TABLE tickets", "CREATE TABLE _tickets_new", 1)
        con.execute("PRAGMA foreign_keys=OFF")
        try:
            con.execute("DROP TABLE IF EXISTS _tickets_new")
            con.execute(new_sql)
            cols = [f'"{r[1]}"' for r in con.execute("PRAGMA table_info(tickets)")]
            con.execute(f"INSERT INTO _tickets_new ({', '.join(cols)}) SELECT {', '.join(cols)} FROM tickets")
            con.execute("DROP TABLE tickets")
            con.execute("ALTER TABLE _tickets_new RENAME TO tickets")
        finally:
            con.execute("PRAGMA foreign_keys=ON")
        tcols = [r[1] for r in con.execute("PRAGMA table_info(tickets)")]
    # Hour-meter readings on tickets (out/in), feeding hour-rate billing.
    if tcols and "hours_start" not in tcols:
        con.execute("ALTER TABLE tickets ADD COLUMN hours_start REAL")
    if tcols and "hours_end" not in tcols:
        con.execute("ALTER TABLE tickets ADD COLUMN hours_end REAL")
    # Quote lines carry their own rate unit so the wording flows down the
    # quote -> ticket -> invoice chain.
    qlcols = [r[1] for r in con.execute("PRAGMA table_info(quote_lines)")]
    if qlcols and "rate_unit" not in qlcols:
        con.execute("ALTER TABLE quote_lines ADD COLUMN rate_unit TEXT")
    # Retract placeholder lines minted by an earlier version of the
    # backfill below (defect fix, pack 'm' round, 2026-10-24): the old
    # zero-value fallback fabricated a line on invoices that had no
    # source documents at all, which made genuinely lineless invoices
    # look payable and defeated record_payment's lineless guard in the
    # live path. The signature is exact and migration-only — operator
    # "extra" lines carry source_id 'extra-<line_id>', never
    # 'legacy-zero' — so no operator-entered line can match this delete.
    con.execute("DELETE FROM invoice_lines WHERE source_type='extra' AND source_id='legacy-zero'")
    # Cash door tender list widened (pack 'm'): a cash_entries table
    # created under the old 3-method CHECK rejects the full tender list
    # at the DB layer even though the form offers it. Rebuild with the
    # current CHECK, rows preserved (same pattern as the tickets
    # rebuilds above). Idempotent: once rebuilt, the guard text is
    # gone forever.
    csql = con.execute("SELECT sql FROM sqlite_master WHERE name='cash_entries'").fetchone()
    if csql and csql["sql"] and "method IN ('Cash','Venmo','Other')" in csql["sql"]:
        new_sql = csql["sql"].replace(
            "method IN ('Cash','Venmo','Other')",
            "method IN ('ACH','Check','Wire','Card','Cash','Venmo','Bitcoin','Traveler''s Check','Other')", 1)
        if 'CREATE TABLE "cash_entries"' in new_sql:
            new_sql = new_sql.replace('CREATE TABLE "cash_entries"', "CREATE TABLE _cash_entries_new", 1)
        else:
            new_sql = new_sql.replace("CREATE TABLE cash_entries", "CREATE TABLE _cash_entries_new", 1)
        # Same shape as the sites rebuild above: commit first, because
        # PRAGMA foreign_keys=OFF is ignored inside a transaction, and
        # collections / doc_collections reference cash_entries.
        con.commit()
        con.execute("PRAGMA foreign_keys=OFF")
        try:
            con.execute("DROP TABLE IF EXISTS _cash_entries_new")
            con.execute(new_sql)
            cols = [f'"{r[1]}"' for r in con.execute("PRAGMA table_info(cash_entries)")]
            con.execute(f"INSERT INTO _cash_entries_new ({', '.join(cols)}) SELECT {', '.join(cols)} FROM cash_entries")
            con.execute("DROP TABLE cash_entries")
            con.execute("ALTER TABLE _cash_entries_new RENAME TO cash_entries")
            con.execute("CREATE INDEX IF NOT EXISTS idx_cash_date ON cash_entries(entry_date)")
            con.commit()
        finally:
            con.execute("PRAGMA foreign_keys=ON")
    # Backfill invoice snapshots for invoices created before immutable invoice lines existed.
    # This runs once per source row and then becomes a no-op. An invoice
    # with NO source tickets or work orders stays lineless on purpose:
    # it is not payable and prints at $0.00 until real lines exist (the
    # editor writes them, or ticket/work-order billing does). Nothing is
    # fabricated for it.
    if not _rekeyed:
        for inv in con.execute("SELECT invoice_no FROM invoices").fetchall():
            ino = inv["invoice_no"]
            existing = con.execute("SELECT 1 FROM invoice_lines WHERE invoice_no=? LIMIT 1", (ino,)).fetchone()
            if existing:
                continue
            for t in con.execute("SELECT * FROM tickets WHERE invoice_no=?", (ino,)).fetchall():
                m = ticket_money(con, t["ticket_id"])
                con.execute("""INSERT INTO invoice_lines(invoice_no,po_line,category,description,qty,uom,rate,amount,clerk,tax_rate,tax_amount,tax_exempt,tax_name,tax_loc,source_type,source_id)
                               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                             (ino,t["po"] or "","Rental",f"{t['ticket_id']} — {m['unit_no']} {m['description'] or ''}".strip(),1,"Each",m["subtotal"],m["subtotal"],t["clerk"] or "",m["tax_rate"],m["tax"],int(bool(m["tax_exempt"])),m["tax_name"],m["tax_loc"],"ticket",t["ticket_id"]))
            for w in con.execute("SELECT * FROM work_orders WHERE invoice_no=?", (ino,)).fetchall():
                cust = con.execute("SELECT tax_exempt FROM customers WHERE customer_id=?", (w["customer_id"],)).fetchone()
                exempt = bool(cust and cust["tax_exempt"]); rate = _money(con.execute("SELECT default_tax FROM company WHERE id=1").fetchone()[0]); amt=_money(w["bill_amount"]); tax=Decimal("0.00") if exempt else (amt*rate).quantize(CENT,rounding=ROUND_HALF_UP)
                con.execute("""INSERT INTO invoice_lines(invoice_no,po_line,category,description,qty,uom,rate,amount,clerk,tax_rate,tax_amount,tax_exempt,tax_name,tax_loc,source_type,source_id)
                               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                             (ino,"","Labor",f"{w['wo_id']} — {w['description']}",1,"Each",float(amt),float(amt),"",float(0 if exempt else rate),float(tax),int(exempt),"Default tax","DEFAULT","work_order",w["wo_id"]))
    # Split legacy receipts into applied invoice cash and unapplied customer cash.
    if not _rekeyed:
        for r in con.execute("SELECT pay_id, invoice_no, amount, kind, applied_amount FROM collections").fetchall():
            if r["applied_amount"] is not None:
                continue
            amt=_money(r["amount"]); applied=amt
            if r["kind"] == "payment":
                total=_money(invoice_totals(con,r["invoice_no"])["total"]); already=_money(con.execute("SELECT COALESCE(SUM(applied_amount),0) FROM collections WHERE invoice_no=? AND kind='payment' AND pay_id<>?",(r["invoice_no"],r["pay_id"])).fetchone()[0]); applied=max(Decimal("0.00"),min(amt,max(Decimal("0.00"),total-already)))
            con.execute("UPDATE collections SET applied_amount=?, unapplied_amount=? WHERE pay_id=?",(float(applied),float(_ms(amt,-applied)),r["pay_id"]))
    # Seed new counters beyond existing IDs.
    wo_nums=[int(x[0].split('-',1)[1]) for x in con.execute("SELECT wo_id FROM work_orders WHERE wo_id LIKE 'WO-%'").fetchall() if str(x[0]).split('-',1)[1].isdigit()]
    pay_nums=[int(x[0].split('-',1)[1]) for x in con.execute("SELECT pay_id FROM collections WHERE pay_id LIKE 'P-%'").fetchall() if str(x[0]).split('-',1)[1].isdigit()]
    # Universality (Oct 23): pay ids also live in doc_collections (WO /
    # ticket / sale money). The counter seed runs on every init_db, so it
    # must scan BOTH ledgers or it rewinds past live doc pay ids and the
    # next mint collides. (A zero-applied overpayment CM mint, which has
    # no ledger row at all, is likewise invisible here — the mint itself
    # is the only writer that must stay ahead; the seed never lowers the
    # counter below its current value for that reason.)
    try:
        pay_nums += [int(x[0].split('-',1)[1]) for x in con.execute("SELECT pay_id FROM doc_collections WHERE pay_id LIKE 'P-%'").fetchall() if str(x[0]).split('-',1)[1].isdigit()]
    except Exception:
        pass
    _cur_pay = con.execute("SELECT next_payment FROM company WHERE id=1").fetchone()
    _seed_pay = max(pay_nums, default=0) + 1
    if _cur_pay and int(_cur_pay[0] or 1) > _seed_pay:
        _seed_pay = int(_cur_pay[0])
    con.execute("UPDATE company SET next_wo=?, next_payment=? WHERE id=1",(max(wo_nums,default=100)+1,_seed_pay))
    # Repair stale document counters so imports/old databases cannot reuse an existing ID.
    for col, table, key, prefix, default in (("next_ticket","tickets","ticket_id","T-",1),("next_invoice","invoices","invoice_no",None,1),("next_quote","quotes","quote_no","QT-",1),("next_co","change_orders","co_no","CO-",1)):
        vals=[]
        for rr in con.execute(f"SELECT {key} FROM {table}"):
            x=str(rr[0] or "")
            try:
                if col=="next_invoice":
                    n=int(x.rsplit("-",1)[1])
                elif x.startswith(prefix):
                    n=int(x.split("-",1)[1])
                else: continue
                vals.append(n)
            except (ValueError,IndexError): pass
        con.execute(f"UPDATE company SET {col}=? WHERE id=1",(max(vals,default=default-1)+1,))
    # Crew position/job title (Jason 2026-10-06).
    crewcols = [r[1] for r in con.execute("PRAGMA table_info(crew)")]
    if crewcols and "position" not in crewcols:
        con.execute("ALTER TABLE crew ADD COLUMN position TEXT NOT NULL DEFAULT ''")
    # Physical address (Jason 2026-10-06): single address for now;
    # multiple yards deferred to v2. County is for tax formulas only,
    # never mailing.
    phcols = [r[1] for r in con.execute("PRAGMA table_info(company)")]
    for col in ("phys_street", "phys_street2", "phys_city", "phys_county",
                "phys_state", "phys_zip"):
        if phcols and col not in phcols:
            con.execute(f"ALTER TABLE company ADD COLUMN {col} TEXT")
    # Equipment sales (Jason 2026-10-07): outright sale of equipment.
    # Sale tab is top-level, left of Rentals.
    con.execute("""CREATE TABLE IF NOT EXISTS sales (
        sale_id TEXT PRIMARY KEY,
        asset_id TEXT NOT NULL REFERENCES assets(asset_id),
        customer_id TEXT REFERENCES customers(customer_id),
        sale_date TEXT NOT NULL,
        qty INTEGER DEFAULT 1,
        amount REAL NOT NULL,
        condition TEXT,
        invoice_no TEXT,
        notes TEXT,
        clerk TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    )""")
    # Add qty/condition to existing sales tables
    scols = [r[1] for r in con.execute("PRAGMA table_info(sales)")]
    if "qty" not in scols:
        con.execute("ALTER TABLE sales ADD COLUMN qty INTEGER DEFAULT 1")
    if "condition" not in scols:
        con.execute("ALTER TABLE sales ADD COLUMN condition TEXT")
    if "ref_no" not in scols:
        con.execute("ALTER TABLE sales ADD COLUMN ref_no TEXT")
    if "item_desc" not in scols:
        con.execute("ALTER TABLE sales ADD COLUMN item_desc TEXT")
    acols = [r[1] for r in con.execute("PRAGMA table_info(assets)")]
    for col in ("sold_date", "sold_amount", "sold_to"):
        if acols and col not in acols:
            con.execute(f"ALTER TABLE assets ADD COLUMN {col} TEXT")
    # Sale number counter
    ccols = [r[1] for r in con.execute("PRAGMA table_info(company)")]
    if ccols and "next_sale" not in ccols:
        con.execute("ALTER TABLE company ADD COLUMN next_sale INTEGER NOT NULL DEFAULT 1")
    # Ticket charges as line items (Jason, 2026-10-23): every ticket
    # charge becomes a line on the invoice template, and tax computes
    # per line. The flat charge fields (mob / demob / transport_fee /
    # fuel / parts / other_amt) convert to ticket_lines rows — freight
    # lines untaxed per Jason's freight ruling, the rest taxed as they
    # were inside the old whole-subtotal base — and are then zeroed.
    # Idempotent: sync_flat_charges_to_lines skips any ticket that
    # already has lines, so re-runs change nothing.
    con.execute("""CREATE TABLE IF NOT EXISTS ticket_lines (
      line_id INTEGER PRIMARY KEY AUTOINCREMENT,
      ticket_id TEXT NOT NULL REFERENCES tickets(ticket_id),
      category TEXT NOT NULL DEFAULT 'Other',
      item TEXT DEFAULT '',
      description TEXT NOT NULL DEFAULT '',
      qty REAL NOT NULL DEFAULT 1,
      uom TEXT NOT NULL DEFAULT 'Each',
      rate REAL NOT NULL DEFAULT 0,
      amount REAL NOT NULL DEFAULT 0,
      taxed INTEGER NOT NULL DEFAULT 1)""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_ticket_lines_ticket ON ticket_lines(ticket_id)")
    if not _rekeyed:
        for _t in con.execute("SELECT ticket_id FROM tickets").fetchall():
            sync_flat_charges_to_lines(con, _t["ticket_id"])
    # Payment line allocations (Jason, 2026-10-23): optional
    # line-by-line distribution of money in against an invoice's
    # lines. Table only — no backfill: payments recorded before this
    # table existed are blanket payments and carry no rows.
    con.execute("""CREATE TABLE IF NOT EXISTS payment_allocations (
      alloc_id INTEGER PRIMARY KEY AUTOINCREMENT,
      source TEXT NOT NULL DEFAULT 'payment' CHECK (source IN ('payment','cash','credit')),
      pay_id TEXT REFERENCES collections(pay_id),
      cash_entry_id INTEGER REFERENCES cash_entries(entry_id),
      batch_id TEXT,
      invoice_no TEXT NOT NULL REFERENCES invoices(invoice_no),
      invoice_line_id INTEGER REFERENCES invoice_lines(line_id),
      amount REAL NOT NULL CHECK (amount > 0),
      pay_date TEXT NOT NULL DEFAULT '',
      clerk TEXT,
      created_at TEXT NOT NULL DEFAULT (datetime('now')))""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_payalloc_pay ON payment_allocations(pay_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_payalloc_batch ON payment_allocations(batch_id)")
    # The invoice_no / invoice_line_id indexes belong to the
    # invoice-only shape; a book already carrying the generalized
    # shape (schema.sql, or the universality rebuild below on an
    # earlier run) has neither column — skip, don't fail.
    _pa_cols0 = [r[1] for r in con.execute("PRAGMA table_info(payment_allocations)")]
    if "invoice_no" in _pa_cols0:
        con.execute("CREATE INDEX IF NOT EXISTS idx_payalloc_inv ON payment_allocations(invoice_no)")
    if "invoice_line_id" in _pa_cols0:
        con.execute("CREATE INDEX IF NOT EXISTS idx_payalloc_line ON payment_allocations(invoice_line_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_payalloc_cash ON payment_allocations(cash_entry_id)")
    # Credit against a line (Jason, 2026-10-23): allocations gain
    # source 'credit'. A CHECK cannot be widened in place — rebuild
    # the (small) table when its stored DDL predates the widening.
    _pa = con.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' "
        "AND name='payment_allocations'").fetchone()
    if _pa and _pa[0] and "'credit'" not in _pa[0]:
        con.execute("""CREATE TABLE payment_allocations_new (
          alloc_id INTEGER PRIMARY KEY AUTOINCREMENT,
          source TEXT NOT NULL DEFAULT 'payment' CHECK (source IN ('payment','cash','credit')),
          pay_id TEXT REFERENCES collections(pay_id),
          cash_entry_id INTEGER REFERENCES cash_entries(entry_id),
          batch_id TEXT,
          invoice_no TEXT NOT NULL REFERENCES invoices(invoice_no),
          invoice_line_id INTEGER REFERENCES invoice_lines(line_id),
          amount REAL NOT NULL CHECK (amount > 0),
          pay_date TEXT NOT NULL DEFAULT '',
          clerk TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now')))""")
        con.execute(
            "INSERT INTO payment_allocations_new SELECT * FROM payment_allocations")
        con.execute("DROP TABLE payment_allocations")
        con.execute("ALTER TABLE payment_allocations_new RENAME TO payment_allocations")
        con.execute("CREATE INDEX IF NOT EXISTS idx_payalloc_pay ON payment_allocations(pay_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_payalloc_batch ON payment_allocations(batch_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_payalloc_inv ON payment_allocations(invoice_no)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_payalloc_line ON payment_allocations(invoice_line_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_payalloc_cash ON payment_allocations(cash_entry_id)")
    # Line note (Jason, 2026-10-23): the short-pay marker — a short
    # note on an invoice line whose remainder is unpaid ("Customer
    # disputes — says not authorized"). Lives on the line, not on an
    # allocation, so it survives later payments and a line paid
    # nothing toward still carries it.
    ilcols = [r[1] for r in con.execute("PRAGMA table_info(invoice_lines)")]
    if ilcols and "line_note" not in ilcols:
        con.execute("ALTER TABLE invoice_lines ADD COLUMN line_note TEXT NOT NULL DEFAULT ''")
    # Cash-in settlement link (Jason, 2026-10-23): a Cash tab Cash In
    # attached to an invoice settles it through the payment path; the
    # collections row carries the cash entry's id, so the entry and
    # the settlement are one money event with two views.
    cecols = [r[1] for r in con.execute("PRAGMA table_info(collections)")]
    if cecols and "cash_entry_id" not in cecols:
        con.execute("ALTER TABLE collections ADD COLUMN cash_entry_id INTEGER")
    # ---- Universality (Jason, 2026-10-23): the line rule complete --
    # money in against every money document (invoice, work order,
    # ticket, sale), blanket or line by line, credits as negative
    # payments, cash through any door. payment_allocations generalizes
    # from invoice-only to doc_kind/doc_ref/line_id; the rebuild maps
    # every existing row (all are invoice rows by construction).
    pacols = [r[1] for r in con.execute("PRAGMA table_info(payment_allocations)")]
    if pacols and "doc_kind" not in pacols:
        con.execute("""CREATE TABLE payment_allocations_doc (
          alloc_id INTEGER PRIMARY KEY AUTOINCREMENT,
          source TEXT NOT NULL DEFAULT 'payment' CHECK (source IN ('payment','cash','credit')),
          pay_id TEXT,
          cash_entry_id INTEGER REFERENCES cash_entries(entry_id),
          batch_id TEXT,
          doc_kind TEXT NOT NULL DEFAULT 'invoice',
          doc_ref TEXT NOT NULL DEFAULT '',
          line_id INTEGER,
          carried INTEGER NOT NULL DEFAULT 0,
          amount REAL NOT NULL CHECK (amount > 0),
          pay_date TEXT NOT NULL DEFAULT '',
          clerk TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now')))""")
        con.execute(
            """INSERT INTO payment_allocations_doc(alloc_id, source, pay_id,
                 cash_entry_id, batch_id, doc_kind, doc_ref, line_id,
                 carried, amount, pay_date, clerk, created_at)
               SELECT alloc_id, source, pay_id, cash_entry_id, batch_id,
                 'invoice', invoice_no, invoice_line_id, 0, amount,
                 pay_date, clerk, created_at FROM payment_allocations""")
        con.execute("DROP TABLE payment_allocations")
        con.execute("ALTER TABLE payment_allocations_doc RENAME TO payment_allocations")
    con.execute("CREATE INDEX IF NOT EXISTS idx_payalloc_pay ON payment_allocations(pay_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_payalloc_batch ON payment_allocations(batch_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_payalloc_doc ON payment_allocations(doc_kind, doc_ref)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_payalloc_line ON payment_allocations(line_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_payalloc_cash ON payment_allocations(cash_entry_id)")
    # The non-invoice money ledger (schema.sql owns the DDL for new
    # books; this is the ensure path for existing ones).
    con.execute("""CREATE TABLE IF NOT EXISTS doc_collections (
      pay_id TEXT PRIMARY KEY,
      batch_id TEXT,
      pay_date TEXT NOT NULL,
      doc_kind TEXT NOT NULL CHECK (doc_kind IN ('wo','ticket','sale','quote')),
      doc_ref TEXT NOT NULL,
      customer_id TEXT,
      method TEXT NOT NULL,
      amount REAL NOT NULL CHECK (amount != 0),
      ref_no TEXT,
      notes TEXT,
      kind TEXT NOT NULL DEFAULT 'payment' CHECK (kind IN ('payment','credit')),
      cm_no TEXT,
      clerk TEXT,
      applied_amount REAL,
      unapplied_amount REAL NOT NULL DEFAULT 0,
      cash_entry_id INTEGER REFERENCES cash_entries(entry_id)
    )""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_dcol_doc ON doc_collections(doc_kind, doc_ref)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_dcol_cm ON doc_collections(cm_no)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_dcol_batch ON doc_collections(batch_id)")
    # Carried settlements: a collections row mirrored from a document
    # at invoicing names its source ('wo:WO-1001' / 'ticket:T-1001').
    if cecols and "carried_from" not in cecols:
        con.execute("ALTER TABLE collections ADD COLUMN carried_from TEXT")
    # An overpaid Cash In that becomes an open credit memo: the memo
    # carries the entry's id, the same one-event link as collections.
    cmcols = [r[1] for r in con.execute("PRAGMA table_info(credit_memos)")]
    if cmcols and "cash_entry_id" not in cmcols:
        con.execute("ALTER TABLE credit_memos ADD COLUMN cash_entry_id INTEGER")
    # Invoice lines remember which source line they came from, so a
    # settlement against that source line can be mirrored onto the
    # exact invoice line at invoicing.
    if ilcols and "source_line_id" not in ilcols:
        con.execute("ALTER TABLE invoice_lines ADD COLUMN source_line_id INTEGER NOT NULL DEFAULT 0")
    # Dispute notes on the other documents' lines (same rule as
    # invoice lines: the note lives on the line).
    wlcols = [r[1] for r in con.execute("PRAGMA table_info(wo_lines)")]
    if wlcols and "line_note" not in wlcols:
        con.execute("ALTER TABLE wo_lines ADD COLUMN line_note TEXT NOT NULL DEFAULT ''")
    tlcols = [r[1] for r in con.execute("PRAGMA table_info(ticket_lines)")]
    if tlcols and "line_note" not in tlcols:
        con.execute("ALTER TABLE ticket_lines ADD COLUMN line_note TEXT NOT NULL DEFAULT ''")
    # Cash entries may attach to a sale (a sale group), the fourth
    # attachment, under the same exactly-one rule. Build 'v': on a
    # rekeyed book the attachment is the sale_id engine key — this
    # legacy text column must never come back.
    cshcols = [r[1] for r in con.execute("PRAGMA table_info(cash_entries)")]
    if cshcols and not _rekeyed and "sale_group" not in cshcols:
        con.execute("ALTER TABLE cash_entries ADD COLUMN sale_group TEXT")
    # Sales gain the two things money needs: a line identity (seq —
    # the sales row's own number, stable across the book) and a group
    # key (one submission's rows share the header's sale number; a
    # legacy row is a group of one). Plus the dispute note.
    if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                   "AND name='sales'").fetchone():
        scols = [r[1] for r in con.execute("PRAGMA table_info(sales)")]
        if "seq" not in scols:
            con.execute("ALTER TABLE sales ADD COLUMN seq INTEGER")
            con.execute(
                "UPDATE sales SET seq = (SELECT COUNT(*) FROM sales s2 "
                "WHERE s2.rowid <= sales.rowid)")
        if "sale_group" not in scols and not _rekeyed:
            # Build 'v': rekeyed books carry group_id instead; the
            # legacy text column must never come back.
            con.execute("ALTER TABLE sales ADD COLUMN sale_group TEXT")
            con.execute("UPDATE sales SET sale_group = sale_id "
                        "WHERE sale_group IS NULL OR sale_group=''")
        if "line_note" not in scols:
            con.execute("ALTER TABLE sales ADD COLUMN line_note TEXT NOT NULL DEFAULT ''")
    # ---- Universality corrections (Jason, 2026-10-23) ----
    # (1) A credit memo may be NEGATIVE (a virtual debit memo, with a
    # note — enforced in issue_credit_memo). The face CHECK widens
    # from > 0 to != 0, and the three money ledgers' amount CHECKs
    # widen the same way so a negative credit's application rows can
    # be written. (2) Quotes join doc_collections as a money
    # document: the doc_kind CHECK gains 'quote'. (3) Quote lines
    # gain the dispute note; cash entries gain the quote attachment.
    # A CHECK cannot be widened in place — rebuild each table whose
    # stored DDL predates its widening (same pattern as the tickets
    # rebuilds above). Idempotent: once widened, the guards are
    # false forever.
    def _widen(table, frag_old, frag_new, indexes):
        row = con.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (table,)).fetchone()
        if not row or not row[0] or frag_old not in row[0]:
            return
        new_sql = row[0].replace(frag_old, frag_new)
        for _a, _b in (("doc_kind IN ('wo','ticket','sale')",
                        "doc_kind IN ('wo','ticket','sale','quote')"),):
            new_sql = new_sql.replace(_a, _b)
        if f'CREATE TABLE "{table}"' in new_sql:
            new_sql = new_sql.replace(f'CREATE TABLE "{table}"',
                                      f"CREATE TABLE _{table}_new", 1)
        elif f"CREATE TABLE IF NOT EXISTS {table}" in new_sql:
            new_sql = new_sql.replace(f"CREATE TABLE IF NOT EXISTS {table}",
                                      f"CREATE TABLE _{table}_new", 1)
        else:
            new_sql = new_sql.replace(f"CREATE TABLE {table}",
                                      f"CREATE TABLE _{table}_new", 1)
        cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
        collist = ", ".join(f'"{c}"' for c in cols)
        # PRAGMA foreign_keys is ignored inside a transaction — the
        # rebuild commits first (same note as the tickets rebuilds).
        con.commit()
        con.execute("PRAGMA foreign_keys=OFF")
        try:
            con.execute(f"DROP TABLE IF EXISTS _{table}_new")
            con.execute(new_sql)
            con.execute(f"INSERT INTO _{table}_new ({collist}) "
                        f"SELECT {collist} FROM {table}")
            con.execute(f"DROP TABLE {table}")
            con.execute(f"ALTER TABLE _{table}_new RENAME TO {table}")
        finally:
            con.execute("PRAGMA foreign_keys=ON")
        for ddl in indexes:
            con.execute(ddl)

    _widen("credit_memos", "face_amount > 0", "face_amount != 0", [
        "CREATE INDEX IF NOT EXISTS idx_cm_cust ON credit_memos(customer_id)",
    ])
    _widen("collections", "amount > 0", "amount != 0", [
        "CREATE INDEX IF NOT EXISTS idx_col_inv ON collections(invoice_no)",
        "CREATE INDEX IF NOT EXISTS idx_col_cm ON collections(cm_no)",
    ])
    _widen("payment_allocations", "amount > 0", "amount != 0", [
        "CREATE INDEX IF NOT EXISTS idx_payalloc_pay ON payment_allocations(pay_id)",
        "CREATE INDEX IF NOT EXISTS idx_payalloc_batch ON payment_allocations(batch_id)",
        "CREATE INDEX IF NOT EXISTS idx_payalloc_doc ON payment_allocations(doc_kind, doc_ref)",
        "CREATE INDEX IF NOT EXISTS idx_payalloc_line ON payment_allocations(line_id)",
        "CREATE INDEX IF NOT EXISTS idx_payalloc_cash ON payment_allocations(cash_entry_id)",
    ])
    _widen("doc_collections", "amount > 0", "amount != 0", [
        "CREATE INDEX IF NOT EXISTS idx_dcol_doc ON doc_collections(doc_kind, doc_ref)",
        "CREATE INDEX IF NOT EXISTS idx_dcol_cm ON doc_collections(cm_no)",
        "CREATE INDEX IF NOT EXISTS idx_dcol_batch ON doc_collections(batch_id)",
    ])
    qlcols2 = [r[1] for r in con.execute("PRAGMA table_info(quote_lines)")]
    if qlcols2 and "line_note" not in qlcols2:
        con.execute("ALTER TABLE quote_lines ADD COLUMN line_note TEXT NOT NULL DEFAULT ''")
    cshcols2 = [r[1] for r in con.execute("PRAGMA table_info(cash_entries)")]
    if cshcols2 and not _rekeyed and "quote_no" not in cshcols2:
        con.execute("ALTER TABLE cash_entries ADD COLUMN quote_no TEXT")
    con.commit()
    # Build 'v' re-key runs LAST: every step above speaks the
    # number-keyed shape, and the re-key translates the finished book.
    _rekey_surrogate_ids(con)


# ---------------------------------------------------------------------------
# Build 'v' re-key (Jason 2026-10-25): "No form number is ever a key ID.
# Key ID's must exist for every table, always be unique, and assigned by
# the engine... it's rather poor taste to have a key ID match any field
# in a table, they are separate things for separate reasons."
#
# Every table gains an engine-assigned surrogate key as its PRIMARY KEY
# (tables that already carry one — line_id, doc_id, entry_id, ... —
# keep it). Number/code columns (invoice_no, ticket_id, customer_id,
# ...) are demoted to UNIQUE display columns: values, formats, and
# presentation unchanged. Every stored reference is rewritten to the
# surrogate key of the row it names. Operators keep addressing
# documents by number everywhere; the engine translates underneath
# (engine_core.key_of / num_of).
#
# The target shape is parsed from schema.sql (the single DDL source —
# no second copy of the shapes lives here). Columns a live book carries
# beyond schema.sql are unioned in with their live types, so nothing a
# book has is dropped. The step runs once: its guard is the presence of
# the invoices.id column, and every later open is a no-op.

_V_SKIP_REBUILD = {
    # No display-keyed references in or out; already integer-keyed.
    "company_phones", "compliance_events", "custom_reports",
    "done_manual", "saved_exports", "today_stickies", "today_tasks",
    "vendors",
}

# Parent tables whose display column other tables reference. Children
# resolve through a per-parent map (display value -> new key).
_V_MAP_DISPLAY = {
    "customers": "customer_id",
    "assets": "asset_id",
    "sites": "site_id",
    "jurisdictions": "loc_id",
    "compliance_packs": "pack_id",
    "invoices": "invoice_no",
    "tickets": "ticket_id",
    "work_orders": "wo_id",
    "quotes": "quote_no",
    "credit_memos": "cm_no",
    "change_orders": "co_no",
    "sales": "sale_id",
}

# Reference columns: table -> {target column: (map name, old column)}.
# Map "sales_group" resolves a sale GROUP's display string (the head
# row's sale number) to the head row's key. Map "DOC" is polymorphic:
# the row's doc_kind picks the map (built as a CASE in _v_ref_expr).
_V_REFS = {
    "company": {"yard_loc_id": ("jurisdictions", "yard_loc_id")},
    "sites": {"customer_id": ("customers", "customer_id"),
              "loc_id": ("jurisdictions", "loc_id")},
    "customer_phones": {"customer_id": ("customers", "customer_id")},
    "customer_locations": {"customer_id": ("customers", "customer_id")},
    "customer_contacts": {"customer_id": ("customers", "customer_id")},
    "tickets": {"customer_id": ("customers", "customer_id"),
                "site_id": ("sites", "site_id"),
                "asset_id": ("assets", "asset_id"),
                "tax_loc_id": ("jurisdictions", "tax_loc_id"),
                "invoice_id": ("invoices", "invoice_no"),
                "quote_id": ("quotes", "quote_no")},
    "invoices": {"customer_id": ("customers", "customer_id"),
                 "quote_id": ("quotes", "quote_no")},
    "invoice_lines": {"invoice_id": ("invoices", "invoice_no")},
    "invoice_docs": {"invoice_id": ("invoices", "invoice_no")},
    "ticket_lines": {"ticket_id": ("tickets", "ticket_id")},
    "collections": {"invoice_id": ("invoices", "invoice_no"),
                    "cm_id": ("credit_memos", "cm_no")},
    "credit_memos": {"customer_id": ("customers", "customer_id")},
    "credit_memo_lines": {"cm_id": ("credit_memos", "cm_no"),
                          "source_invoice_id": ("invoices", "source_invoice_no")},
    "cash_entries": {"customer_id": ("customers", "customer_id"),
                     "invoice_id": ("invoices", "invoice_no"),
                     "wo_id": ("work_orders", "wo_no"),
                     "ticket_id": ("tickets", "ticket_id"),
                     "sale_id": ("sales_group", "sale_group"),
                     "quote_id": ("quotes", "quote_no"),
                     "asset_id": ("assets", "asset_id")},
    "work_orders": {"asset_id": ("assets", "asset_id"),
                    "ticket_id": ("tickets", "ticket_id"),
                    "customer_id": ("customers", "customer_id"),
                    "invoice_id": ("invoices", "invoice_no"),
                    "quote_id": ("quotes", "quote_no")},
    "quotes": {"customer_id": ("customers", "customer_id"),
               "site_id": ("sites", "site_id")},
    "quote_lines": {"quote_id": ("quotes", "quote_no"),
                    "asset_id": ("assets", "asset_id")},
    "change_order_lines": {"co_id": ("change_orders", "co_no")},
    "sales": {"asset_id": ("assets", "asset_id"),
              "customer_id": ("customers", "customer_id"),
              "invoice_id": ("invoices", "invoice_no"),
              "group_id": ("sales_group", "sale_group")},
    "doc_collections": {"doc_id": ("DOC", "doc_ref"),
                        "customer_id": ("customers", "customer_id"),
                        "cm_id": ("credit_memos", "cm_no")},
    "payment_allocations": {"doc_id": ("DOC", "doc_ref")},
    "purchase_orders": {"customer_id": ("customers", "customer_id"),
                        "asset_id": ("assets", "asset_id")},
    "compliance_requirements": {"pack_id": ("compliance_packs", "pack_id")},
    "equipment_compliance": {"asset_id": ("assets", "asset_id"),
                             "pack_id": ("compliance_packs", "pack_id")},
    "asset_certs": {"asset_id": ("assets", "asset_id")},
    "unit_docs": {"asset_id": ("assets", "asset_id")},
    "mixed_presets": {"customer_id": ("customers", "customer_id")},
    "pending_bookings": {"soft_ticket_id": ("tickets", "soft_ticket_id")},
    "wo_lines": {"wo_id": ("work_orders", "wo_id")},
}

_V_DOC_KIND_MAPS = {
    "invoice": "invoices", "ticket": "tickets", "wo": "work_orders",
    "sale": "sales_group", "quote": "quotes", "credit": "credit_memos",
    "change": "change_orders",
}


def _v_split_sql(text: str) -> list:
    """Split SQL text into statements at top-level semicolons
    (string- and comment-aware)."""
    out, inq, cur = [], False, ""
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if inq:
            cur += ch
            if ch == "'":
                if i + 1 < n and text[i + 1] == "'":
                    cur += "'"
                    i += 2
                    continue
                inq = False
            i += 1
            continue
        if ch == "'":
            inq = True
            cur += ch
            i += 1
            continue
        if ch == "-" and i + 1 < n and text[i + 1] == "-":
            j = text.find("\n", i)
            if j == -1:
                j = n
            cur += text[i:j]
            i = j
            continue
        if ch == ";":
            out.append(cur)
            cur = ""
            i += 1
            continue
        cur += ch
        i += 1
    if cur.strip():
        out.append(cur)
    return out


def _v_split_top(s: str) -> list:
    """Split at top-level commas (paren- and string-aware)."""
    out, inq, cur, depth = [], False, "", 0
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        if inq:
            cur += ch
            if ch == "'":
                if i + 1 < n and s[i + 1] == "'":
                    cur += "'"
                    i += 2
                    continue
                inq = False
            i += 1
            continue
        if ch == "'":
            inq = True
            cur += ch
            i += 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
        i += 1
    out.append(cur)
    return out


def _v_schema() -> tuple:
    """Parse schema.sql: ({table: (ddl, [columns], pk_column)}, [index sql])."""
    tables = {}
    indexes = []
    for st in _v_split_sql(SCHEMA.read_text()):
        s = st.strip()
        m = re.search(r"CREATE TABLE IF NOT EXISTS \"?(\w+)\"?\s*\(", s)
        if m:
            name = m.group(1)
            # Strip -- comments from the column body (they can hold
            # commas and apostrophes that desync the column split).
            body = s[s.index("(", m.end() - 1) + 1:s.rindex(")")]
            body = "\n".join(
                ln for ln in body.split("\n")
                if not ln.strip().startswith("--"))
            cols = []
            pk = None
            defaults = {}
            for part in _v_split_top(body):
                p = part.strip()
                if not p:
                    continue
                fm = re.match(r'"?\[?(\w+)', p)
                first = fm.group(1) if fm else ""
                if first.upper() in ("PRIMARY", "UNIQUE", "CHECK",
                                     "FOREIGN", "CONSTRAINT"):
                    continue
                cols.append(first)
                if "PRIMARY KEY" in p.upper():
                    pk = first
                dm = re.search(
                    r"DEFAULT\s+(\((?:[^()]|\([^()]*\))*\)|'[^']*'|[-\w.]+)",
                    p, re.I)
                if dm:
                    defaults[first] = dm.group(1)
            tables[name] = (s, cols, pk, defaults)
        elif re.search(r"CREATE INDEX", s):
            indexes.append(s[s.index("CREATE INDEX"):])
    return tables, indexes


def _v_ref_expr(map_name: str, old_col: str) -> str:
    if map_name == "DOC":
        arms = " ".join(
            f"WHEN '{kind}' THEN (SELECT newkey FROM _v_map_{tbl} "
            f"WHERE display = o.\"{old_col}\")"
            for kind, tbl in _V_DOC_KIND_MAPS.items())
        return f"CASE o.\"doc_kind\" {arms} END"
    return (f"(SELECT newkey FROM _v_map_{map_name} "
            f"WHERE display = o.\"{old_col}\")")


def _rekey_surrogate_ids(con: sqlite3.Connection) -> None:
    """The build-'v' re-key. See the section header above. Runs once per
    book, inside migrate_legacy_schema, after every older step."""
    inv_cols = [r[1] for r in con.execute("PRAGMA table_info(invoices)")]
    if not inv_cols or "id" in inv_cols:
        return
    tables, index_sql = _v_schema()
    live_tables = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%'")}
    con.commit()
    con.execute("PRAGMA foreign_keys=OFF")
    try:
        # --- Key maps first: every parent's new key is known before
        # any table is rebuilt, so rebuild order cannot matter.
        for tbl, disp in _V_MAP_DISPLAY.items():
            if tbl not in live_tables:
                continue
            con.execute(f"CREATE TEMP TABLE _v_map_{tbl} "
                        "(display, newkey INTEGER)")
            rows = con.execute(
                f"SELECT \"{disp}\" FROM \"{tbl}\" ORDER BY rowid").fetchall()
            con.executemany(
                f"INSERT INTO _v_map_{tbl} VALUES (?, ?)",
                [(r[0], i + 1) for i, r in enumerate(rows)])
        # Sale groups: a group's key is its head row's key (the row
        # whose sale number the group carries; first row of the group
        # when no row carries it).
        if "sales" in live_tables:
            con.execute("CREATE TEMP TABLE _v_map_sales_group "
                        "(display, newkey INTEGER)")
            heads = {}
            for rowid, sale_id, grp in con.execute(
                    "SELECT rowid, sale_id, sale_group FROM sales "
                    "ORDER BY rowid"):
                g = grp or sale_id
                if sale_id == g and g not in heads:
                    heads[g] = rowid
                elif g not in heads:
                    heads[g] = rowid
            sale_keys = {}
            for disp, nk in con.execute(
                    "SELECT display, newkey FROM _v_map_sales"):
                sale_keys[disp] = nk
            for g, hrowid in heads.items():
                h_sale = con.execute(
                    "SELECT sale_id FROM sales WHERE rowid=?",
                    (hrowid,)).fetchone()[0]
                con.execute(
                    "INSERT INTO _v_map_sales_group VALUES (?, ?)",
                    (g, sale_keys[h_sale]))
        # The shared pay-key space: doc_collections rows take the
        # first keys (rowid order), collections rows follow — except a
        # carried mirror row, whose pay number IS its source doc
        # row's, so it reuses that row's key by construction.
        con.execute("CREATE TEMP TABLE _v_pay_map (pay_id, newkey INTEGER)")
        nxt = 1
        if "doc_collections" in live_tables:
            for (pid,) in con.execute(
                    "SELECT pay_id FROM doc_collections ORDER BY rowid"):
                con.execute("INSERT INTO _v_pay_map VALUES (?, ?)", (pid, nxt))
                nxt += 1
        if "collections" in live_tables:
            for (pid,) in con.execute(
                    "SELECT pay_id FROM collections ORDER BY rowid"):
                cur = con.execute(
                    "INSERT OR IGNORE INTO _v_pay_map VALUES (?, ?)",
                    (pid, nxt))
                if cur.rowcount:
                    nxt += 1
        # Existing change orders were issued against a quote; their
        # customer is that quote's customer (the standalone CO carries
        # its own customer from build 'v' on).
        con.execute("CREATE TEMP TABLE _v_co_cust (co_no, custkey INTEGER)")
        if "change_orders" in live_tables and "quotes" in live_tables:
            for co_no, q_cust in con.execute(
                    "SELECT c.co_no, q.customer_id FROM change_orders c "
                    "LEFT JOIN quotes q ON q.quote_no = c.quote_no"):
                ck = None
                if q_cust is not None:
                    r = con.execute(
                        "SELECT newkey FROM _v_map_customers "
                        "WHERE display=?", (q_cust,)).fetchone()
                    ck = r[0] if r else None
                con.execute("INSERT INTO _v_co_cust VALUES (?, ?)",
                            (co_no, ck))
        # --- Rebuild each table onto its schema shape.
        for tbl, (ddl, tcols, _pk, tdefs) in tables.items():
            if tbl in _V_SKIP_REBUILD or tbl not in live_tables:
                continue
            live = {r[1]: r for r in con.execute(
                f"PRAGMA table_info({tbl})")}
            refs = _V_REFS.get(tbl, {})
            consumed = {old for (_m, old) in refs.values()}
            if tbl == "change_orders":
                consumed.add("quote_no")
            extras = [c for c in live
                      if c not in tcols and c not in consumed]
            new_ddl = re.sub(
                r"CREATE TABLE IF NOT EXISTS \"?" + tbl + r"\"?",
                f"CREATE TABLE _v_new_{tbl}", ddl, count=1)
            if extras:
                extra_defs = []
                for c in extras:
                    pr = live[c]
                    d = f'"{c}" {pr[2] or "TEXT"}'
                    if pr[3] and pr[4] is not None:
                        d += f" NOT NULL DEFAULT {pr[4]}"
                    extra_defs.append(d)
                cut = new_ddl.rindex(")")
                new_ddl = (new_ddl[:cut] + ",\n  " + ", ".join(extra_defs)
                           + new_ddl[cut:])
            exprs = []
            for c in tcols:
                if c in refs and refs[c][1] in live:
                    exprs.append(_v_ref_expr(refs[c][0], refs[c][1]))
                elif c in refs:
                    # The live (older) table predates this reference
                    # column entirely — nothing to translate.
                    exprs.append("NULL")
                elif tbl in _V_MAP_DISPLAY and c == "id":
                    exprs.append(
                        f"(SELECT newkey FROM _v_map_{tbl} "
                        f"WHERE display = o.\"{_V_MAP_DISPLAY[tbl]}\")")
                elif c == "id" and tbl in ("collections", "doc_collections"):
                    exprs.append(
                        "(SELECT newkey FROM _v_pay_map "
                        "WHERE pay_id = o.\"pay_id\")")
                elif c == "id" and tbl == "purchase_orders":
                    exprs.append("o.rowid")
                elif c == "id":
                    exprs.append("o.rowid")
                elif tbl == "change_orders" and c == "assoc_kind":
                    exprs.append(
                        "CASE WHEN o.\"quote_no\" IS NULL "
                        "OR o.\"quote_no\"='' THEN NULL ELSE 'quote' END")
                elif tbl == "change_orders" and c == "assoc_id":
                    exprs.append(
                        "(SELECT newkey FROM _v_map_quotes "
                        "WHERE display = o.\"quote_no\")")
                elif tbl == "change_orders" and c == "customer_id":
                    exprs.append(
                        "(SELECT custkey FROM _v_co_cust "
                        "WHERE co_no = o.\"co_no\")")
                elif tbl == "payment_allocations" and c == "pay_id":
                    exprs.append(
                        "(SELECT newkey FROM _v_pay_map "
                        "WHERE pay_id = o.\"pay_id\")")
                elif c in live:
                    exprs.append(f'o."{c}"')
                elif c in tdefs:
                    exprs.append(tdefs[c])
                else:
                    exprs.append("NULL")
            for c in extras:
                exprs.append(f'o."{c}"')
            all_cols = tcols + extras
            con.execute(f"DROP TABLE IF EXISTS _v_new_{tbl}")
            con.execute(new_ddl)
            con.execute(
                f"INSERT INTO _v_new_{tbl} ("
                + ", ".join(f'"{c}"' for c in all_cols)
                + ") SELECT " + ", ".join(exprs) + f" FROM \"{tbl}\" o")
            con.execute(f"DROP TABLE \"{tbl}\"")
            con.execute(f"ALTER TABLE _v_new_{tbl} RENAME TO \"{tbl}\"")
        # carried_from names its source document ('ticket:T-1002'): a
        # stored composite that is matched exactly (identity, not a
        # label), so its value migrates to the source's key form
        # ('ticket:7'). Display readers translate back.
        if "collections" in live_tables:
            kind_maps = {"ticket": "tickets", "wo": "work_orders",
                         "quote": "quotes", "sale": "sales_group",
                         "invoice": "invoices"}
            for rid, cf in con.execute(
                    "SELECT id, carried_from FROM collections "
                    "WHERE carried_from IS NOT NULL AND carried_from != ''"):
                kind, _, ref = str(cf).partition(":")
                tbl = kind_maps.get(kind)
                if not tbl or not ref:
                    continue
                r = con.execute(
                    f"SELECT newkey FROM _v_map_{tbl} WHERE display=?",
                    (ref,)).fetchone()
                if r:
                    con.execute(
                        "UPDATE collections SET carried_from=? WHERE id=?",
                        (f"{kind}:{r[0]}", rid))
        # The pay counter continues past every migrated key.
        mx = con.execute("SELECT COALESCE(MAX(newkey), 0) "
                         "FROM _v_pay_map").fetchone()[0]
        ccols = [r[1] for r in con.execute("PRAGMA table_info(company)")]
        if "next_pay_key" in ccols:
            con.execute("UPDATE company SET next_pay_key=? WHERE id=1",
                        (int(mx) + 1,))
        # AUTOINCREMENT sequences follow the rebuilt tables.
        for tbl, (ddl, _c, pk, _d) in tables.items():
            if tbl in _V_SKIP_REBUILD or tbl not in live_tables:
                continue
            if "AUTOINCREMENT" in ddl.upper() and pk:
                con.execute(
                    "INSERT OR REPLACE INTO sqlite_sequence (name, seq) "
                    f"SELECT '{tbl}', COALESCE(MAX(\"{pk}\"), 0) FROM \"{tbl}\"")
        con.execute("DELETE FROM sqlite_sequence WHERE name LIKE '_v_new_%'")
        for s in index_sql:
            con.execute(s)
        for t in list(_V_MAP_DISPLAY) + ["sales_group"]:
            con.execute(f"DROP TABLE IF EXISTS _v_map_{t}")
        con.execute("DROP TABLE IF EXISTS _v_pay_map")
        con.execute("DROP TABLE IF EXISTS _v_co_cust")
        con.commit()
    finally:
        con.execute("PRAGMA foreign_keys=ON")
