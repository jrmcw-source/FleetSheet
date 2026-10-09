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
    report_work_orders,
    HAUL_BY,
    DELIVER_TO,
    HAUL_LABELS,
    DELIVER_LABELS,
    clean_haul_by,
    clean_deliver_to,
    haul_consequence,
    haul_from,
    RATE_UNITS,
    clean_rate_unit,
    ticket_hours,
    day_equivalent,
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
    invoice_totals_batch,
    invoice_balances_batch,
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
)

from engine_today import (
    today_money_slot,
    advance_money_slot,
    top_of_day,
    today_must_do,
    today_can_do,
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
    con.executescript(SCHEMA.read_text())
    con.executescript(SEED_PACKS.read_text())
    if con.execute("SELECT COUNT(*) FROM company").fetchone()[0] == 0:
        con.execute(
            """INSERT INTO company (id, name, dba, address, phone, billing_email)
               VALUES (1, 'YOUR COMPANY LLC', 'Your yard', '', '', '')"""
        )
    seed_lookups(con)
    migrate_legacy_schema(con)
    con.commit()
    return con
def seed_lookups(con: sqlite3.Connection) -> None:
    rows = []
    packs = {
        "ticket_status": ["Quoted", "Reserved", "Dispatched", "On Rent", "Standby", "Off Rent", "Ready to Bill", "Billed", "Closed", "Void"],
        "rate_type": ["Day", "Week", "Hour", "Special", "Monthly", "Standby", "Yard"],
        "category": ["Pump", "Generator", "Tank", "Light Tower", "Compressor", "Pressure Control", "Flowback", "Vehicle / Trailer", "Living Quarters", "Lifting Gear", "Test Equipment", "Shop Tools", "Other"],
        "yard": ["Lafayette Yard", "New Iberia Yard", "Field / Customer", "Vendor / Subrental", "In Transit"],
        "terms": ["Due on Receipt", "Net 10", "Net 15", "Net 30", "Net 45", "Net 60"],
        "pay_method": ["ACH", "Check", "Wire", "Card", "Cash", "Petty cash"],
        "condition": ["Excellent", "Good", "Fair", "Poor", "Damaged", "Available", "Repair — minor", "Repair — major", "Unusable"],
        "regime": ["USCG", "DNV", "ABS", "BV", "Lloyd's", "API / OEM only", "BSEE + USCG", "None / Onshore"],
        "flag_state": ["USA", "Panama", "Liberia", "Marshall Islands", "Bahamas", "Norway", "UK", "Mexico"],
        "waters": ["Land", "Inland Waters", "State Waters", "Offshore", "International Waters"],
        "wo_type": ["PM / service", "Repair — minor", "Repair — major", "Inspection / cert", "Warranty", "On-job repair", "Other"],
        "wo_status": ["Open", "In progress", "Complete", "Void"],
        "inv_uom": ["Each", "Hours", "Days", "Weeks", "Months", "Miles", "Loads", "Feet", "Gallons", "Lot"],
        "inv_cat": ["Rental", "Labor", "Item", "Mileage", "Freight", "Fuel", "Consumable", "Mobilization", "Demobilization", "Other"],
        "pc_category": [
            "Opening float", "Replenish", "Invoice cash in",
            "Fuel", "Parts", "Postage", "Parking", "Tolls", "Meals",
            "Office", "Tools", "Travel", "Other",
        ],
    }
    for kind, vals in packs.items():
        for i, v in enumerate(vals):
            rows.append((kind, v, i))
    con.executemany("INSERT OR IGNORE INTO lookups(kind,value,sort_order) VALUES (?,?,?)", rows)
def dashboard(con: sqlite3.Connection) -> dict:
    on_rent = con.execute(
        "SELECT COUNT(*) FROM tickets WHERE status IN ('On Rent','Standby')"
    ).fetchone()[0]
    ready = con.execute(
        "SELECT ticket_id FROM tickets WHERE status IN ('Ready to Bill','Off Rent') AND (invoice_no IS NULL OR invoice_no='')"
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
        "pc_balance": petty_balance(con),
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
# Self-diagnosing + self-correcting support for non-technical users:
# integrity tripwires, verified backups, corruption auto-recovery, a health
# snapshot for the System Health page, and self-healing config files.
#
# Rules every function below obeys:
#   * Never raises on bad input — returns ok=False with a plain-language
#     message instead.
#   * Never deletes user data. Damaged files are quarantined (renamed with a
#     timestamp), never removed. Only files matching OUR OWN backup naming
#     pattern are ever pruned, and only to the requested retention count.
#   * Standard library only.
# ---------------------------------------------------------------------------
import json as _json
import re as _re
import shutil as _shutil
import time as _time

_SELFHEAL_TS = "%Y%m%d-%H%M%S"
_BACKUP_PREFIX = "fleetsheet-backup-"
_BACKUP_SUFFIX = ".db"


def _selfheal_stamp():
    return datetime.now().strftime(_SELFHEAL_TS)


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


def check_integrity(con):
    """Fast integrity tripwire for startup. Returns (ok, message)."""
    try:
        if con is None:
            return (False, "No database connection was available to check.")
        rows = con.execute("PRAGMA quick_check").fetchall()
        vals = [r[0] for r in rows]
        if len(vals) == 1 and str(vals[0]).lower() == "ok":
            return (True, "Database integrity check passed.")
        problems = "; ".join(str(v)[:120] for v in vals[:5])
        return (False, "The database reported problems: %s" % problems)
    except Exception as e:
        return (False, "Could not check the database: %s" % _selfheal_msg(e))


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


def verified_backup(db_path, backup_dir, keep=7):
    """Create a verified backup. Returns (ok, backup_path_or_error_message).

    Uses the SQLite Online Backup API (never a raw file copy of a live DB).
    The backup is integrity-checked before it is kept; a failed backup is
    discarded. Prunes OUR OWN older backups to `keep` newest.
    """
    try:
        keep = max(1, int(keep))
    except Exception:
        keep = 7
    try:
        src = Path(db_path)
        if not src.is_file():
            return (False, "No database file was found to back up.")
        dst_dir = Path(backup_dir)
        try:
            dst_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return (False, "Could not create the backup folder: %s"
                    % _selfheal_msg(e))
        name = "%s%s%s" % (_BACKUP_PREFIX, _selfheal_stamp(), _BACKUP_SUFFIX)
        dst = dst_dir / name
        if dst.exists():
            # Same-second rerun: make the name unique, never overwrite.
            dst = dst_dir / ("%s%s-%d%s" % (_BACKUP_PREFIX, _selfheal_stamp(),
                                            os.getpid(), _BACKUP_SUFFIX))
        scon = sqlite3.connect(str(src))
        try:
            tcon = sqlite3.connect(str(dst))
            try:
                scon.backup(tcon)
                # Fold any WAL back into the file so the backup is one
                # clean, self-contained .db with no -wal/-shm sidecars.
                try:
                    tcon.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                except Exception:
                    pass
            finally:
                tcon.close()
        finally:
            scon.close()
        ok, issues = full_integrity_check(dst)
        if not ok:
            try:
                dst.unlink()
            except Exception:
                pass
            return (False, "The backup did not pass its health check and was "
                    "discarded: %s" % "; ".join(issues[:3]))
        # The read-only health check above can recreate -shm/-wal sidecars;
        # drop them now so the backup is one clean, self-contained .db file.
        for sidecar in (str(dst) + "-wal", str(dst) + "-shm",
                        str(dst) + "-journal"):
            try:
                Path(sidecar).unlink()
            except Exception:
                pass
        # Prune only our own backups, oldest beyond `keep`.
        for old in _list_our_backups(dst_dir)[keep:]:
            try:
                old.unlink()
            except Exception:
                pass
        return (True, str(dst))
    except Exception as e:
        return (False, "Backup failed: %s" % _selfheal_msg(e))


def auto_recover(db_path, backup_dir):
    """Recover from corruption. Returns (ok, restored_from, user_message).

    If the database fails its integrity check: quarantine the damaged file
    (+ -wal/-shm/-journal) with a timestamp suffix — NEVER delete — then
    restore the newest backup that passes its own integrity check, and verify
    the restored file too. The message is written for a non-technical user.

    The caller should make sure no other process (e.g. the app server) holds
    the database open before calling this.
    """
    try:
        p = Path(db_path)
    except Exception:
        return (False, "", "The database location was not usable, so no "
                "recovery was attempted. Your files were not touched.")
    ok, _issues = full_integrity_check(p)
    if ok:
        return (True, "", "The database checked out fine — no recovery was "
                "needed.")
    stamp = _selfheal_stamp()
    quarantined = []
    for suffix in ("", "-wal", "-shm", "-journal"):
        f = Path(str(p) + suffix) if suffix else p
        if f.is_file():
            q = f.with_name("%s.corrupt-%s" % (f.name, stamp))
            try:
                # Never overwrite an earlier quarantine from the same second.
                if q.exists():
                    q = f.with_name("%s.corrupt-%s-%d"
                                    % (f.name, stamp, os.getpid()))
                f.rename(q)
                quarantined.append(str(q))
            except Exception as e:
                return (False, "",
                        "The damaged database could not be moved aside safely "
                        "(%s). Nothing was deleted; please ask for help."
                        % _selfheal_msg(e))
    # Newest backup that passes its own health check.
    chosen = None
    try:
        candidates = _list_our_backups(backup_dir)
    except Exception:
        candidates = []
    for cand in candidates:
        cok, _ = full_integrity_check(cand)
        if cok:
            chosen = cand
            break
    if chosen is None:
        return (False, "",
                "The database was damaged and no healthy backup was found. "
                "Your damaged file was kept (renamed with today's date, not "
                "deleted). Please ask for help — do not delete anything.")
    try:
        _shutil.copy2(str(chosen), str(p))
    except Exception as e:
        return (False, "",
                "The damaged database was set aside, but the backup could "
                "not be restored (%s). Nothing was deleted."
                % _selfheal_msg(e))
    rok, _ = full_integrity_check(p)
    if not rok:
        return (False, "",
                "The backup was copied back but did not pass its final "
                "health check. Your files were kept — please ask for help.")
    try:
        when = datetime.strptime(chosen.stem[len(_BACKUP_PREFIX):],
                                 "%Y%m%d-%H%M%S").strftime("%B %d, %Y at %I:%M %p")
    except Exception:
        when = chosen.name
    return (True, str(chosen),
            "We found a problem in your data file and repaired it by "
            "restoring your backup from %s. Anything entered after that "
            "backup may need to be re-entered. Your damaged file was kept "
            "under a new name — nothing was deleted." % when)


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


def config_atomic_write(config_path, data):
    """Write config atomically: temp file + fsync + rename. Never raises.

    Returns (ok, message). The old file is only replaced once the new one
    is fully written and flushed, so a crash mid-write cannot corrupt it.
    """
    try:
        p = Path(config_path)
    except Exception:
        return (False, "The settings location was not usable.")
    try:
        text = _json.dumps(data, indent=2, sort_keys=True)
    except Exception as e:
        return (False, "The settings could not be saved (%s)."
                % _selfheal_msg(e))
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return (False, "The settings folder could not be created (%s)."
                % _selfheal_msg(e))
    tmp = p.with_name("%s.tmp-%d" % (p.name, os.getpid()))
    try:
        with tmp.open("w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(str(tmp), str(p))
        return (True, "Settings saved.")
    except Exception as e:
        try:
            tmp.unlink()
        except Exception:
            pass
        return (False, "The settings could not be saved (%s)."
                % _selfheal_msg(e))


def config_self_heal(config_path, defaults):
    """Read a JSON config; heal it if broken. Returns (healed, message).

    On parse failure the broken file is renamed to config.json.bad.N (N
    counting up, never overwriting an earlier quarantine) and regenerated
    from `defaults`. A missing file is created from defaults. A healthy
    file returns (False, ...) — nothing was wrong.
    """
    try:
        p = Path(config_path)
    except Exception:
        return (False, "The settings location was not usable.")
    if not isinstance(defaults, dict):
        return (False, "The default settings were not valid.")
    if not p.is_file():
        ok, msg = config_atomic_write(p, defaults)
        if ok:
            return (True, "Settings file was missing, so a fresh one was "
                    "created from the defaults.")
        return (False, msg)
    try:
        with p.open("r", encoding="utf-8") as fh:
            _json.load(fh)
        return (False, "Settings are fine — nothing needed fixing.")
    except Exception:
        pass
    # Broken: quarantine under a non-colliding name, then regenerate.
    n = 1
    while True:
        q = p.with_name("%s.bad.%d" % (p.name, n))
        if not q.exists():
            break
        n += 1
        if n > 9999:  # sanity bound; never spin forever
            return (False, "The settings file is broken and could not be "
                    "set aside safely. Your files were not touched.")
    try:
        p.rename(q)
    except Exception as e:
        return (False, "The broken settings file could not be set aside "
                "(%s). Your files were not touched." % _selfheal_msg(e))
    ok, msg = config_atomic_write(p, defaults)
    if ok:
        return (True, "Your settings file was damaged, so it was set aside "
                "as %s (not deleted) and fresh settings were created."
                % q.name)
    return (False, "The settings file was damaged and set aside as %s, but "
            "fresh settings could not be written (%s)." % (q.name, msg))
