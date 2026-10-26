"""All money and status rules live here. The UI never computes them."""
from __future__ import annotations
import sqlite3
from calendar import monthrange
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from pathlib import Path
import hashlib
import hmac
import os
import secrets

from engine_core import (
    _money,
    _mf,
    _ms,
    parse_date,
    _parse,
    terms_days,
    format_phone_number,
    _row_get,
    require_clerk,
    list_crew,
    add_crew,
    drop_crew,
    _reserve_counter,
    _next_doc,
    peek_next_doc,
    validate_new_doc_no,
    key_of,
    num_of,
    doc_key,
    doc_num,
    DOC_TABLES,
    cust_key,
    cust_code,
    asset_key,
    asset_code,
    site_key,
    site_code,
    loc_key,
    loc_code,
    _next_pay_key,
    pay_key_of,
    pay_id_of,
    peek_next_invoice_no,
    peek_next_ticket_no,
    _set_quote_link,
    lookups,
    add_lookup,
    CURATED_LOOKUP_KINDS,
    deleted_lookups,
    clear_deleted_lookup,
    delete_lookup,
    clean_line_type,
    clean_line_uom,
    uom_to_rate_type,
    period_bounds,
    _ensure_device_tables,
    get_option,
    set_option,
    MODULE_NAMES,
    COND_NOT_RECORDED,
    module_on,
    set_module,
    module_seen,
    stamp_module_seen,
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
    get_backup_schedule,
    set_backup_schedule,
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
    save_job_attachment,
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

from engine_assets import (
    billable_days,
    applied_rate,
    rental_amount,
    compliance,
    fit_reason,
    possession_rules,
    ticket_money,
    ticket_lines,
    save_ticket_lines,
    sync_flat_charges_to_lines,
    FREIGHT_CATS,
    asset_status,
    next_ticket_id,
    create_ticket,
    SoftReserveConflict,
    update_ticket_transport,
    condition_worse,
    save_ticket_condition,
    save_ticket_photo,
    read_ticket_photo,
    create_sale,
    list_sales,
    next_sale_id,
    peek_next_sale_id,
    set_status,
    ready_work_orders,
    next_asset_id,
    save_asset,
    next_site_id,
    save_site,
    report_availability,
    report_upcoming,
    report_stays,
    report_maintenance,
    next_wo_id,
    wo_cost,
    save_wo,
    wo_lines,
    report_work_orders,
    HAUL_BY,
    DELIVER_TO,
    HAUL_LABELS,
    DELIVER_LABELS,
    clean_haul_by,
    clean_deliver_to,
    haul_consequence,
    haul_from,
    resolve_haul_text,
    transport_display,
    RATE_UNITS,
    clean_rate_unit,
    ticket_hours,
    day_equivalent,
    ASSET_STATUSES,
    clean_asset_status,
    rentable_or_raise,
)

from engine_accounting import (
    next_invoice_id,
    PO_STATUSES,
    create_invoice,
    invoice_has_lines,
    _next_pay_id,
    _refresh_invoice_status,
    record_payment,
    record_doc_payment,
    quote_money_block,
    apply_doc_credit,
    doc_line_states,
    doc_has_line_allocations,
    set_doc_line_note,
    doc_total,
    doc_settled,
    doc_balance,
    DOC_LABELS,
    next_batch_id,
    invoice_line_states,
    invoice_has_line_allocations,
    list_payment_allocations,
    set_invoice_line_note,
    next_cm_id,
    credit_applied,
    credit_open,
    credit_lines,
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
    save_change_order,
    change_order_assoc,
    associated_change_orders,
    PAYABLE_KINDS,
    quote_totals,
    quote_pack,
    convert_quote,
    next_pc_id,
    petty_balance,
    petty_book,
    set_pc_float,
    record_petty,
    CASH_ENTRY_METHODS,
    record_cash_entry,
    list_cash_entries,
    invoice_totals,
    invoice_totals_batch,
    invoice_balances_batch,
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
    list_invoice_docs,
    set_invoice_doc_print,
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
    compliance_groups,
    daily_check_units,
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
    set_cert_superseded,
    attach_cert_evidence,
    delete_cert,
    update_cert,
    operative_cert_expiry,
    migrate_legacy_cert_expiry,
    LEGACY_CERT_KIND_LABELS,
    cert_kind_label,
)

from engine_alerts import (
    alerts_for,
    ack_alert,
    is_acked,
    ladder_level,
    TAP,
    SLAP,
    PUNCH,
    get_ticker_cats,
    set_ticker_cats,
    TICKER_CATS,
    CAT_LABELS,
    list_snoozed,
    unack_alert,
)

from engine_today import (
    today_money_slot,
    advance_money_slot,
    top_of_day,
    today_must_do,
    today_can_do,
    module_nudge,
    today_later,
    today_tomorrow,
    today_everything,
    add_task,
    complete_task,
    uncomplete_task,
    add_sticky,
    edit_sticky,
    remove_sticky,
    list_stickies,
    update_sticky,
    done_sticky,
    snooze_sticky,
    add_done_manual,
    remove_done_manual,
    done_today,
    done_tasks,
    done_payments,
    done_period,
    list_tasks,
    tasks_for_link,
)

from engine_reports import (
    BUCKETS,
    BUCKET_LABELS,
    FLOW_SECTIONS,
    ar_aging,
    fleet_utilization,
    weeks_flow,
    custom_datasets,
    custom_dataset_fields,
    run_custom,
    list_custom_reports,
    get_custom_report,
    save_custom_report,
    delete_custom_report,
    MIXED_KINDS,
    MIXED_KIND_LABELS,
    MIXED_COLUMNS,
    mixed_range,
    mixed_rows,
    list_mixed_presets,
    get_mixed_preset,
    save_mixed_preset,
    delete_mixed_preset,
)
from engine_health import (
    SEVERITIES,
    data_health,
)

from engine_migrations import migrate_legacy_schema

"""FleetSheet engine facade.

Domain logic lives in engine_core / engine_assets / engine_accounting /
engine_compliance. This module keeps the DB plumbing (DB_PATH, connect,
init_db, backups, dashboard) and re-exports every domain function so
`import engine` keeps working unchanged.
"""

def _db_path() -> Path:
    env = os.environ.get("FLEETSHEET_DB")
    if env:
        return Path(env)
    return _LOCAL
DB_PATH = _db_path()
def connect(path: Path | None = None) -> sqlite3.Connection:
    global DB_PATH
    p = path or DB_PATH
    try:
        con = sqlite3.connect(p)
        con.execute("PRAGMA user_version")
    except sqlite3.OperationalError:
        p = _TMP
        con = sqlite3.connect(p)
    except sqlite3.DatabaseError:
        # The book file exists but is not a database at all (corrupt disk
        # write, clobbered file). Quarantine it under a new name — never
        # delete — and start on a fresh book so the desk can boot and the
        # user can restore a backup archive through the normal page.
        q = p.with_name(p.name + ".corrupt-" +
                        datetime.now().strftime("%Y%m%d%H%M%S"))
        try:
            p.rename(q)
            print(f"Corrupt book quarantined as {q}; starting a fresh book.")
        except OSError:
            pass
        con = sqlite3.connect(p)
        con.execute("PRAGMA user_version")
    DB_PATH = p
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    # Two writers (desk browser + yard phone) can collide on SQLite's default
    # rollback journal. WAL lets readers proceed during a write, and the
    # busy timeout makes a briefly-blocked writer wait instead of erroring.
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA busy_timeout = 5000")
    return con
def init_db(con: sqlite3.Connection | None = None) -> sqlite3.Connection:
    own = con is None
    con = con or connect()
    try:
        con.executescript(SCHEMA.read_text())
    except sqlite3.OperationalError:
        # A pre-'v' book: its tables predate the surrogate-key columns
        # the schema's indexes name, so the index statements cannot
        # run yet. Migrate first (the re-key at the end of the ledger
        # creates the indexes against the rebuilt tables), then apply
        # the schema again — every statement is IF NOT EXISTS.
        migrate_legacy_schema(con)
        con.executescript(SCHEMA.read_text())
    if con.execute("SELECT COUNT(*) FROM company").fetchone()[0] == 0:
        con.execute(
            """INSERT INTO company (id, name, dba, address, phone, billing_email)
               VALUES (1, 'YOUR COMPANY LLC', NULL, '', '', '')"""
        )
    seed_lookups(con)
    migrate_legacy_schema(con)
    # Pack seeds run AFTER the migration (build 'v'): the requirement
    # rows resolve their pack's engine key from the pack's slug, which
    # only exists once the re-key has run on a pre-'v' book.
    con.executescript(SEED_PACKS.read_text())
    con.commit()
    return con
def seed_lookups(con: sqlite3.Connection) -> None:
    rows = []
    packs = {
        "ticket_status": ["Quoted", "Reserved", "Dispatched", "On Rent", "Standby", "Off Rent", "Ready to Bill", "Billed", "Closed", "Void"],
        "rate_type": ["Day", "Week", "Hour", "Special", "Monthly", "Standby", "Yard"],
        "category": ["Pump", "Generator", "Tank", "Light Tower", "Compressor", "Pressure Control", "Flowback", "Vehicle / Trailer", "Living Quarters", "Lifting Gear", "Test Equipment", "Shop Tools", "Other"],
        "yard": ["Lafayette Yard", "New Iberia Yard", "Field / Customer", "Vendor / Subrental", "In Transit"],
        "terms": ['Due on Receipt', 'Net 7', 'Net 10', 'Net 15', 'Net 21', 'Net 30', 'Net 45', 'Net 60', 'Net 90', '1/10 Net 30', '2/10 Net 30', 'Cash in Advance', 'Payment in Advance', 'COD', 'Cash with Order', 'Cash before Shipment', 'Cash Next Delivery', 'End of Month (EOM)', 'Net 30 EOM', '15 MFI', '50% Upfront'],
        "pay_method": ["ACH", "Check", "Wire", "Card", "Cash", "Venmo", "Bitcoin", "Traveler's Check", "Other"],
        # Unit designations (Batch 3, Oct 23): the trade's three piles —
        # held to rent, held for sale, own-use gear we track. The
        # operator can add their own term or write over, because it's
        # theirs (same list-plus-custom pattern). NOT a curated kind:
        # no tombstone machinery — fresh DBs seed these; existing DBs
        # gain any missing preset on the ordinary seed pass.
        "designation": ["Fleet", "Stock", "Plant"],
        "condition": ["Excellent", "Good", "Fair", "Poor", "Damaged", "Available", "Repair — minor", "Repair — major", "Unusable"],
        "regime": ["USCG", "DNV", "ABS", "BV", "Lloyd's", "API / OEM only", "BSEE + USCG", "None / Onshore"],
        "flag_state": ["USA", "Panama", "Liberia", "Marshall Islands", "Bahamas", "Norway", "UK", "Mexico"],
        "waters": ["Land", "Inland Waters", "State Waters", "Offshore", "International Waters"],
        "wo_type": ["PM / service", "Repair — minor", "Repair — major", "Inspection / cert", "Warranty", "On-job repair", "Other"],
        "wo_status": ["Open", "In progress", "Complete", "Void"],
        "inv_uom": ['Each', 'Hours', 'Days', 'Weeks', 'Months', 'Miles', 'Loads', 'Feet', 'Gallons', 'Lot', 'Minutes', 'Years', 'Pieces', 'Pairs', 'Sets', 'Dozen', 'Cases', 'Packages', 'Boxes', 'Pallets', 'Jobs', 'Trips', 'Calls', 'Deliveries', 'Pickups', 'Visits', 'Flat Fee', 'Ounces', 'Pounds', 'Hundredweight', 'Tons', 'Fluid Ounces', 'Cups', 'Pints', 'Quarts', 'Barrels', 'Cubic Inches', 'Cubic Feet', 'Cubic Yards', 'Inches', 'Yards', 'Square Inches', 'Square Feet', 'Square Yards', 'Acres', 'Square Miles', 'Bags', 'Sacks', 'Rolls', 'Sheets', 'Kits', 'Cans', 'Bottles', 'Crates', 'Cartons', 'Bundles', 'Truckloads'],
        "inv_item": ['Labor', 'Parts', 'Service', 'Equipment Rental', 'Equipment Sale', 'Materials', 'Supplies', 'Shop Supplies', 'Consumables', 'Delivery', 'Pickup', 'Freight', 'Hauling', 'Transportation', 'Mileage', 'Travel', 'Per Diem', 'Service Call', 'Setup', 'Installation', 'Inspection', 'Testing', 'Certification', 'Repair', 'Maintenance', 'Preventive Maintenance', 'Cleaning', 'Fuel', 'Fuel Surcharge', 'Damage Waiver', 'Environmental Fee', 'Disposal', 'Storage', 'Standby', 'Operator', 'Mobilization', 'Demobilization', 'Loading', 'Unloading', 'Waiting Time', 'Late Return', 'Damage Repair', 'Replacement', 'Subcontractor', 'Permit Fee', 'Administrative Fee', 'Other'],
        "inv_cat": ["Rental", "Labor", "Item", "Mileage", "Freight", "Fuel", "Consumable", "Mobilization", "Demobilization", "Other"],
        # Cert kinds (Issue 4, 2026-10-15): moved from hardcoded CERT_KINDS
        # so the global Other/-Add- dropdown rule applies to them too.
        "cert_kind": ["Certification", "Calibration", "Function test", "Other"],
        # Compliance document types (laptop-pass fix round, 2026-10-20):
        # the master list behind the Upload Certificate picker on the
        # Compliance page — curated in Setup -> Billing like the other
        # Spec 7 lists (enabled set + add/delete/restore, tombstones).
        "comp_doc": ['Load Test', 'Proof Load Test', 'Load Chart', 'NDT',
                     'Visual Inspection', 'Ultrasonic/Sonic Testing',
                     'Magnetic Particle Inspection', 'Radiographic Testing',
                     'Liquid Penetrant Testing', 'Eddy Current Inspection',
                     'Positive Material Identification', 'Hydrostatic Test',
                     'Pressure Test', 'Relief Valve Test', 'Hardness Test',
                     'Calibration Certificate', 'Certificate of Conformance',
                     'Mill Test Report', 'Manufacturer Data Book',
                     'Inspection Report', 'Third-Party Inspection', 'DNV',
                     'USCG', 'UL', 'ABS', 'API Inspection',
                     'ASME Certification', 'Thorough Examination',
                     'DOT Certification', 'Other'],
        "pc_category": [
            "Opening float", "Replenish", "Invoice cash in",
            "Fuel", "Parts", "Postage", "Parking", "Tolls", "Meals",
            "Office", "Tools", "Travel", "Other",
        ],
    }
    # Item 6 tombstones (2026-10-20): values the operator deleted from
    # a curated master list are never reseeded — this runs on every
    # init_db, so without the skip a deletion would silently resurrect
    # on the next page load, and a list emptied by deletion would come
    # back whole. Never-initialized books carry no tombstones and seed
    # normally.
    try:
        _deleted = deleted_lookups(con)
    except Exception:
        _deleted = {}
    for kind, vals in packs.items():
        _gone = set(_deleted.get(kind, []))
        for i, v in enumerate(vals):
            if v in _gone:
                continue
            rows.append((kind, v, i))
    con.executemany("INSERT OR IGNORE INTO lookups(kind,value,sort_order) VALUES (?,?,?)", rows)
def restore_factory_lookups(con: sqlite3.Connection, kind: str) -> None:
    """Restore one curated master list to the shipped factory list
    (Item 6): clears the kind's deletion tombstones and reseeds, so
    every factory value comes back in factory order (values the
    operator added stay — restore adds the factory set back, it does
    not wipe custom entries). The factory-on enabled set is reset by
    the caller (Setup -> Billing handler), which owns ENABLED_CORES.
    No record/document row is touched."""
    if kind not in CURATED_LOOKUP_KINDS:
        raise ValueError("List cannot be restored here")
    clear_deleted_lookup(con, kind)
    seed_lookups(con)
    con.commit()
def dashboard(con: sqlite3.Connection) -> dict:
    on_rent = con.execute(
        "SELECT COUNT(*) FROM tickets WHERE status IN ('On Rent','Standby')"
    ).fetchone()[0]
    ready = con.execute(
        "SELECT ticket_id FROM tickets WHERE status IN ('Ready to Bill','Off Rent') AND invoice_id IS NULL"
    ).fetchall()
    ready_amt = sum(ticket_money(con, r["ticket_id"])["total"] for r in ready)
    open_ar = 0.0
    ar_n = 0
    for _ino, _tot in invoice_totals_batch(con).items():
        if _tot["balance"] > 0.009:
            open_ar += _tot["balance"]
            ar_n += 1
    # Cert identity (Q5): expired means the operative cert-record expiry is
    # past — the bare legacy column is only a fallback inside the helper.
    today_iso = date.today().isoformat()
    certs = 0
    for _a in con.execute("SELECT asset_id FROM assets WHERE active=1"):
        _exp = operative_cert_expiry(con, _a["asset_id"])
        if _exp and _exp < today_iso:
            certs += 1
    active = con.execute("SELECT COUNT(*) FROM assets WHERE active=1").fetchone()[0]
    fail = 0
    # Paper only matters at shipping: Reserved/Dispatched tickets whose unit
    # fails the job's fit. A unit already on the job passed receiving once —
    # mid-job paper is the field's business, never a shoulder-tap.
    for t in con.execute("SELECT ticket_id FROM tickets WHERE status IN ('Reserved','Dispatched')").fetchall():
        if ticket_money(con, t["ticket_id"]).get("fit", "PASS") != "PASS":
            fail += 1
    no_off = con.execute(
        "SELECT COUNT(*) FROM tickets WHERE status IN ('On Rent','Standby') AND (off_rent IS NULL OR off_rent='')"
    ).fetchone()[0]
    return {
        "on_rent": on_rent,
        "ready_n": len(ready),
        "ready_amt": round(ready_amt, 2),
        "open_ar": round(open_ar, 2),
        "ar_n": ar_n,
        "certs": certs,
        "active": active,
        # Petty cash is NOT read here (Jason 2026-10-23, petty-cash
        # seal): the drawer is its own universe; no dashboard, report,
        # or balance outside /petty consumes it.
        "open_quotes": con.execute(
            "SELECT COUNT(*) FROM quotes WHERE status IN ('Draft','Sent','Accepted')"
        ).fetchone()[0],
        "fail": fail,
        "no_off": no_off,
        "backup": backup_status(con),
    }


# ---------------------------------------------------------------------------
# Self-sufficiency backend (Jason 2026-10-08, Step 1 of the makeover plan).
#
# Self-diagnosing support for non-technical users: integrity tripwires
# and a health snapshot for the System Health page.
#
# Rules every function below obeys:
#   * Never raises on bad input — returns ok=False with a plain-language
#     message instead.
#   * Never deletes user data.
#   * Standard library only.
# ---------------------------------------------------------------------------
import re as _re
import shutil as _shutil
import time as _time


def _selfheal_msg(exc):
    # Plain-language version of an exception for non-technical users.
    return str(exc)[:200] if str(exc) else type(exc).__name__


def _ro_connect(db_path):
    # Read-only connection: cannot modify the book, safe for diagnostics.
    p = Path(db_path)
    return sqlite3.connect("file:%s?mode=ro" % p.as_posix(), uri=True)


def _pragma_rows(db_path, pragma_sql):
    # Run a PRAGMA against db_path read-only; returns list of first-column
    # values. Raises on failure — callers catch and translate.
    con = _ro_connect(db_path)
    try:
        return [r[0] for r in con.execute(pragma_sql).fetchall()]
    finally:
        con.close()


def _is_our_backup(name):
    # fleetsheet-backup-YYYYMMDD-HHMMSS.db, with an optional -PID segment
    # when two backups land in the same second. Regex, not length math.
    return bool(_re.match(r"^fleetsheet-backup-\d{8}-\d{6}(-\d+)?\.db$",
                          name or ""))


def _list_our_backups(backup_dir):
    # Newest first. Only files matching our own naming pattern.
    try:
        d = Path(backup_dir)
        if not d.is_dir():
            return []
        files = [f for f in d.iterdir()
                 if f.is_file() and _is_our_backup(f.name)]
    except Exception:
        return []
    files.sort(key=lambda f: f.name, reverse=True)
    return files


def full_integrity_check(db_path):
    """Deep check: PRAGMA integrity_check + foreign_key_check, read-only.

    Returns (ok, issues) where issues is a list of plain-language strings.
    """
    try:
        p = Path(db_path)
    except Exception:
        return (False, ["The database path was not usable."])
    if not p.is_file():
        return (False, ["No database file was found at %s." % p])
    issues = []
    try:
        for v in _pragma_rows(p, "PRAGMA integrity_check"):
            if str(v).lower() != "ok":
                issues.append("Integrity: %s" % str(v)[:200])
    except Exception as e:
        return (False, ["The database could not be read at all: %s"
                        % _selfheal_msg(e)])
    try:
        for r in _pragma_rows(p, "PRAGMA foreign_key_check"):
            issues.append("Broken link between records: %s" % str(r)[:200])
    except Exception:
        # foreign_key_check failing is not itself corruption evidence; the
        # integrity_check above is the verdict.
        pass
    if issues:
        return (False, issues[:20])
    return (True, [])


def health_snapshot(db_path, backup_dir):
    """Point-in-time health for the System Health page. Returns a dict.

    Never raises; every field degrades to a safe value on failure.
    """
    snap = {
        "integrity_ok": False,
        "foreign_keys_ok": False,
        "disk_free_mb": None,
        "data_dir_writable": False,
        "backup_age_hours": None,
        "db_size_mb": None,
        "wal_size_mb": 0.0,
        "user_version": None,
        "last_errors": [],
    }
    try:
        p = Path(db_path)
    except Exception:
        snap["last_errors"] = ["Database path was not usable."]
        return snap
    ok, issues = full_integrity_check(p)
    snap["integrity_ok"] = ok
    snap["foreign_keys_ok"] = not any("Broken link" in i for i in issues)
    try:
        if p.is_file():
            snap["db_size_mb"] = round(p.stat().st_size / 1048576, 2)
        wal = Path(str(p) + "-wal")
        if wal.is_file():
            snap["wal_size_mb"] = round(wal.stat().st_size / 1048576, 2)
    except Exception:
        pass
    try:
        snap["disk_free_mb"] = round(
            _shutil.disk_usage(str(p.parent)).free / 1048576, 1)
    except Exception:
        pass
    try:
        probe = p.parent / (".writetest-%d" % os.getpid())
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        snap["data_dir_writable"] = True
    except Exception:
        snap["data_dir_writable"] = False
    try:
        rows = _pragma_rows(p, "PRAGMA user_version")
        snap["user_version"] = int(rows[0]) if rows else None
    except Exception:
        pass
    try:
        backs = _list_our_backups(backup_dir)
        if backs:
            newest = backs[0]
            age = _time.time() - newest.stat().st_mtime
            snap["backup_age_hours"] = round(age / 3600, 1)
    except Exception:
        pass
    # Last errors: tail of any *.log next to the database (launch/server logs).
    try:
        logs = sorted(p.parent.glob("*.log"), key=lambda f: f.stat().st_mtime,
                      reverse=True)[:2]
        errs = []
        for lf in logs:
            try:
                with lf.open("r", encoding="utf-8", errors="replace") as fh:
                    lines = fh.readlines()
                for ln in lines[-200:]:
                    low = ln.lower()
                    if ("error" in low or "traceback" in low
                            or "exception" in low):
                        errs.append(ln.strip()[:200])
                        if len(errs) >= 10:
                            break
            except Exception:
                continue
            if len(errs) >= 10:
                break
        snap["last_errors"] = errs[-10:]
    except Exception:
        pass
    return snap


