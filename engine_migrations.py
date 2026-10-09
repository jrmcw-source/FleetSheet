"""Legacy database migration ledger.

This module owns compatibility upgrades for databases created by older
FleetSheet builds.  The current schema lives in schema.sql; this file only
transforms older databases forward and is intentionally idempotent.
"""
from __future__ import annotations

import sqlite3
from decimal import Decimal, ROUND_HALF_UP

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
    ack_po_record,
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
    update_cert,
    delete_cert,
    get_cert,
    list_certs,
    fleet_certs,
    cert_status,
    set_cert_superseded,
    attach_cert_evidence,
    operative_cert_expiry,
    migrate_legacy_cert_expiry,
    CERT_KINDS,
)

from engine_assets import (
    ticket_money,
)



def _ensure_customer_site_business_tables(con: sqlite3.Connection) -> None:
    con.execute("""CREATE TABLE IF NOT EXISTS customer_locations (
      location_id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id TEXT NOT NULL REFERENCES customers(customer_id),
      location_name TEXT NOT NULL, street TEXT, street2 TEXT, city TEXT, state TEXT, zip TEXT,
      is_primary INTEGER NOT NULL DEFAULT 0)""")
    con.execute("""CREATE TABLE IF NOT EXISTS customer_contacts (
      contact_id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id TEXT NOT NULL REFERENCES customers(customer_id),
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
    cols = [r[1] for r in con.execute("PRAGMA table_info(work_orders)")]
    if cols and "invoice_no" not in cols:
        con.execute("ALTER TABLE work_orders ADD COLUMN invoice_no TEXT")
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
    # Quote/change-order line types (Jason 2026-10-07): item, unit, labor,
    # freight, other. Legacy values rental/service/transport stay valid for
    # old rows. SQLite cannot ALTER a CHECK — recreate both tables.
    # Idempotent: once the new kind list is in the DDL the guard is false.
    for _tbl in ("quote_lines", "change_order_lines"):
        _tsql = con.execute("SELECT sql FROM sqlite_master WHERE name=?", (_tbl,)).fetchone()
        if _tsql and _tsql["sql"] and "kind IN ('rental','service','transport','other')" in _tsql["sql"]:
            _new = _tsql["sql"].replace(
                "kind IN ('rental','service','transport','other')",
                "kind IN ('item','unit','labor','freight','other','rental','service','transport')", 1)
            _new = _new.replace(f"CREATE TABLE {_tbl}", f"CREATE TABLE _{_tbl}_new", 1)
            _new = _new.replace(f"CREATE TABLE IF NOT EXISTS {_tbl}", f"CREATE TABLE _{_tbl}_new", 1)
            con.commit()
            con.execute("PRAGMA foreign_keys=OFF")
            try:
                con.execute(f"DROP TABLE IF EXISTS _{_tbl}_new")
                con.execute(_new)
                _cols = [f'"{r[1]}"' for r in con.execute(f"PRAGMA table_info({_tbl})")]
                con.execute(f"INSERT INTO _{_tbl}_new ({', '.join(_cols)}) SELECT {', '.join(_cols)} FROM {_tbl}")
                con.execute(f"DROP TABLE {_tbl}")
                con.execute(f"ALTER TABLE _{_tbl}_new RENAME TO {_tbl}")
                con.commit()
            finally:
                con.execute("PRAGMA foreign_keys=ON")
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
    if colcols and "cm_no" not in colcols:
        con.execute("ALTER TABLE collections ADD COLUMN cm_no TEXT")
    con.execute("CREATE INDEX IF NOT EXISTS idx_col_cm ON collections(cm_no)")
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
    if tcols and "quote_no" not in tcols:
        con.execute("ALTER TABLE tickets ADD COLUMN quote_no TEXT")
    icols = [r[1] for r in con.execute("PRAGMA table_info(invoices)")]
    if icols and "quote_no" not in icols:
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
    if wcols and "quote_no" not in wcols:
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
    # Backfill invoice snapshots for invoices created before immutable invoice lines existed.
    # This runs once per source row and then becomes a no-op.
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
        if not con.execute("SELECT 1 FROM invoice_lines WHERE invoice_no=? LIMIT 1", (ino,)).fetchone():
            con.execute("""INSERT INTO invoice_lines(invoice_no,po_line,category,description,qty,uom,rate,amount,clerk,tax_rate,tax_amount,tax_exempt,tax_name,tax_loc,source_type,source_id)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                         (ino,"","Other","Legacy zero-value invoice placeholder",1,"Each",0,0,"",0,0,1,"","DEFAULT","extra","legacy-zero"))
    # Split legacy receipts into applied invoice cash and unapplied customer cash.
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
    con.execute("UPDATE company SET next_wo=?, next_payment=? WHERE id=1",(max(wo_nums,default=100)+1,max(pay_nums,default=0)+1))
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
    con.commit()
