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
    ttl_cached,
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


"""FleetSheet engine: certification/calibration flow — compliance packs, per-unit checklists, completions, due/overdue watch."""

__all__ = ['checklist_next_due', 'checklist_status', 'list_packs', 'get_pack', 'assign_pack', 'unit_packs', 'add_custom_requirement', 'update_checklist_item', 'remove_checklist_item', 'record_completion', 'item_history', 'unit_checklist', 'compliance_summary', 'fleet_compliance_watch',
           'list_vendors', 'save_vendor', 'delete_vendor', 'set_checklist_performer',
           'ensure_cert_tables', 'save_cert', 'update_cert', 'delete_cert', 'get_cert',
           'list_certs', 'fleet_certs', 'cert_status', 'set_cert_superseded',
           'attach_cert_evidence', 'operative_cert_expiry', 'migrate_legacy_cert_expiry',
           'CERT_KINDS']


def _ensure_vendor_tables(con: sqlite3.Connection) -> None:
    """Who-does-it directory + per-checklist-item performer link.

    No money here on purpose: vendor *cost* tracking is a future module.
    This is just names and phone numbers so a due date comes with "call X".
    """
    # Current schema owns table creation. This helper only repairs columns on
    # legacy books that predate the performer link.
    cols = {r[1] for r in con.execute("PRAGMA table_info(equipment_compliance)")}
    if "performer_id" not in cols:
        con.execute("ALTER TABLE equipment_compliance ADD COLUMN performer_id INTEGER REFERENCES vendors(vendor_id)")
    con.commit()


def list_vendors(con: sqlite3.Connection) -> list:
    _ensure_vendor_tables(con)
    return con.execute(
        "SELECT * FROM vendors ORDER BY kind DESC, name").fetchall()


def save_vendor(con: sqlite3.Connection, name: str, kind: str = "vendor",
                phone: str = "", email: str = "", specialties: str = "",
                notes: str = "", vendor_id: int | None = None) -> int:
    _ensure_vendor_tables(con)
    name = (name or "").strip()
    if not name:
        raise ValueError("Give the vendor a name")
    kind = kind if kind in ("vendor", "crew") else "vendor"
    if vendor_id:
        con.execute(
            """UPDATE vendors SET name=?, kind=?, phone=?, email=?,
               specialties=?, notes=? WHERE vendor_id=?""",
            (name, kind, phone.strip(), email.strip(), specialties.strip(),
             notes.strip(), vendor_id))
        con.commit()
        return int(vendor_id)
    cur = con.execute(
        """INSERT INTO vendors (name, kind, phone, email, specialties, notes)
           VALUES (?,?,?,?,?,?)""",
        (name, kind, phone.strip(), email.strip(), specialties.strip(), notes.strip()))
    con.commit()
    return int(cur.lastrowid)


def delete_vendor(con: sqlite3.Connection, vendor_id: int) -> None:
    _ensure_vendor_tables(con)
    con.execute("UPDATE equipment_compliance SET performer_id=NULL WHERE performer_id=?",
                (vendor_id,))
    con.execute("DELETE FROM vendors WHERE vendor_id=?", (vendor_id,))
    con.commit()


def set_checklist_performer(con: sqlite3.Connection, eqc_id: int,
                            vendor_id: int | None) -> None:
    """Who does this check on this unit. None = we do it ourselves / undecided."""
    _ensure_vendor_tables(con)
    if vendor_id:
        ok = con.execute("SELECT 1 FROM vendors WHERE vendor_id=?", (vendor_id,)).fetchone()
        if not ok:
            raise ValueError("Unknown vendor")
    con.execute("UPDATE equipment_compliance SET performer_id=? WHERE eqc_id=?",
                (vendor_id, eqc_id))
    con.commit()

def checklist_next_due(trigger, interval_months, backstop_months, last_done):
    """Next due date for a checklist row, or None when not date-driven.

    Calendar items run off their interval; per-job and per-manufacturer items
    run off the deployed backstop (the longest a deployed unit may go between
    checks — company policy, never a standard).
    """
    ld = _parse(last_done) if isinstance(last_done, str) else last_done
    if trigger == "calendar":
        if not ld or not interval_months:
            return None
        return _shift_months(ld, float(interval_months))
    if trigger == "per_shift":
        if not ld:
            return None
        return ld + timedelta(days=1)
    if trigger in ("per_job", "manufacturer"):
        if not ld or not backstop_months:
            return None
        return _shift_months(ld, float(backstop_months))
    return None  # event: the event itself is the trigger
def checklist_status(row, today=None) -> str:
    """One equipment_compliance row -> overdue | due | ok | info.

    A failed last result is never 'done' — it stays due until redone.
    """
    today = today or date.today()
    try:
        last_result = row["last_result"]
    except (KeyError, IndexError, TypeError):
        last_result = None
    if last_result == "fail":
        return "due"
    trig = row["trigger"]
    ld = _parse(row["last_done"]) if row["last_done"] else None
    if trig == "per_shift":
        return "ok" if ld == today else "due"
    if trig == "calendar" or (trig in ("per_job", "manufacturer") and row["deployed_backstop_months"]):
        if not ld:
            return "due"  # date-driven item with no record yet
        nd = checklist_next_due(trig, row["interval_months"], row["deployed_backstop_months"], ld)
        if nd is None:
            return "due"
        if nd < today:
            return "overdue"
        if (nd - today).days <= DUE_SOON_DAYS:
            return "due"
        return "ok"
    return "info"
def list_packs(con: sqlite3.Connection):
    return con.execute(
        """SELECT p.pack_id, p.name, p.blurb, COUNT(r.req_id) AS n_reqs
           FROM compliance_packs p LEFT JOIN compliance_requirements r ON r.pack_id = p.pack_id
           GROUP BY p.pack_id ORDER BY p.name"""
    ).fetchall()
def get_pack(con: sqlite3.Connection, pack_id: str):
    pack = con.execute("SELECT * FROM compliance_packs WHERE pack_id=?", (pack_id,)).fetchone()
    reqs = []
    if pack:
        reqs = con.execute(
            "SELECT * FROM compliance_requirements WHERE pack_id=? ORDER BY sort_order, name",
            (pack_id,),
        ).fetchall()
    return pack, reqs
def assign_pack(con: sqlite3.Connection, asset_id: str, pack_id: str) -> int:
    """Copy a pack's requirements onto a unit. Idempotent; returns # added."""
    pack, reqs = get_pack(con, pack_id)
    if not pack:
        raise ValueError("Unknown pack")
    if not con.execute("SELECT 1 FROM assets WHERE asset_id=?", (asset_id,)).fetchone():
        raise ValueError("Unknown unit")
    added = 0
    for r in reqs:
        exists = con.execute(
            "SELECT 1 FROM equipment_compliance WHERE asset_id=? AND req_id=?",
            (asset_id, r["req_id"]),
        ).fetchone()
        if exists:
            continue
        con.execute(
            """INSERT INTO equipment_compliance
               (asset_id, pack_id, req_id, trigger, interval_months, deployed_backstop_months)
               VALUES (?,?,?,?,?,?)""",
            (asset_id, pack_id, r["req_id"], r["trigger"], r["interval_months"],
             r["deployed_backstop_months"]),
        )
        added += 1
    con.commit()
    return added
def unit_packs(con: sqlite3.Connection, asset_id: str):
    """Pack ids already assigned to a unit."""
    return [r[0] for r in con.execute(
        "SELECT DISTINCT pack_id FROM equipment_compliance WHERE asset_id=? AND pack_id IS NOT NULL",
        (asset_id,))]
def add_custom_requirement(con: sqlite3.Connection, asset_id: str, name: str, trigger: str,
                           interval_months=None, backstop_months=None, notes: str = "") -> int:
    name = (name or "").strip()
    if not name:
        raise ValueError("Name the requirement")
    if trigger not in TRIGGER_LABELS:
        raise ValueError("Pick a trigger")
    bv = _pos_or_none(backstop_months)
    if trigger in ("per_job", "manufacturer") and bv is None:
        raise ValueError("Per-job / manufacturer checks need a deployed backstop (months) — "
                         "without one the check can never come due")
    cur = con.execute(
        """INSERT INTO equipment_compliance
           (asset_id, custom_name, trigger, interval_months, deployed_backstop_months, notes)
           VALUES (?,?,?,?,?,?)""",
        (asset_id, name, trigger, _pos_or_none(interval_months), bv,
         notes or ""),
    )
    con.commit()
    return cur.lastrowid
def update_checklist_item(con: sqlite3.Connection, eqc_id: int, trigger: str | None = None,
                          interval_months=None, backstop_months=None, notes: str | None = None,
                          custom_name: str | None = None) -> None:
    row = con.execute("SELECT * FROM equipment_compliance WHERE eqc_id=?", (eqc_id,)).fetchone()
    if not row:
        raise ValueError("Unknown checklist item")
    trig = row["trigger"] if trigger is None else trigger
    if trig not in TRIGGER_LABELS:
        raise ValueError("Pick a trigger")
    iv = row["interval_months"] if interval_months is None else _pos_or_none(interval_months)
    bv = row["deployed_backstop_months"] if backstop_months is None else _pos_or_none(backstop_months)
    if trig in ("per_job", "manufacturer") and bv is None and row["req_id"] is None:
        raise ValueError("Per-job / manufacturer checks need a deployed backstop (months) — "
                         "without one the check can never come due")
    cn = row["custom_name"]
    if row["req_id"] is None and custom_name is not None:
        cn = custom_name.strip()
        if not cn:
            raise ValueError("Name the requirement")
    nd = checklist_next_due(trig, iv, bv, row["last_done"])
    keep_notes = row["notes"] if notes is None else notes
    con.execute(
        """UPDATE equipment_compliance
           SET trigger=?, interval_months=?, deployed_backstop_months=?,
               notes=?, custom_name=?, next_due=? WHERE eqc_id=?""",
        (trig, iv, bv, keep_notes or "", cn, nd.isoformat() if nd else None, eqc_id),
    )
    con.commit()
def remove_checklist_item(con: sqlite3.Connection, eqc_id: int) -> None:
    con.execute("DELETE FROM compliance_events WHERE eqc_id=?", (eqc_id,))
    con.execute("DELETE FROM equipment_compliance WHERE eqc_id=?", (eqc_id,))
    con.commit()
def record_completion(con: sqlite3.Connection, eqc_id: int, done_date: str,
                      result: str = "pass", evidence: str = "", notes: str = "",
                      clerk: str = "") -> None:
    row = con.execute("SELECT * FROM equipment_compliance WHERE eqc_id=?", (eqc_id,)).fetchone()
    if not row:
        raise ValueError("Unknown checklist item")
    d = _parse(done_date)
    if not d:
        raise ValueError("Enter a valid date")
    if d > date.today():
        raise ValueError("Date cannot be in the future")
    if result not in ("pass", "fail"):
        raise ValueError("Bad result")
    con.execute(
        """INSERT INTO compliance_events (eqc_id, done_date, result, evidence, notes, clerk)
           VALUES (?,?,?,?,?,?)""",
        (eqc_id, d.isoformat(), result, evidence or "", notes or "", clerk or ""),
    )
    nd = checklist_next_due(row["trigger"], row["interval_months"],
                            row["deployed_backstop_months"], d)
    con.execute("UPDATE equipment_compliance SET last_done=?, next_due=? WHERE eqc_id=?",
                (d.isoformat(), nd.isoformat() if nd else None, eqc_id))
    con.commit()
def item_history(con: sqlite3.Connection, eqc_id: int, limit: int = 50):
    return con.execute(
        "SELECT * FROM compliance_events WHERE eqc_id=? ORDER BY done_date DESC, event_id DESC LIMIT ?",
        (eqc_id, limit),
    ).fetchall()
def unit_checklist(con: sqlite3.Connection, asset_id: str, today=None):
    """Every checklist row for a unit with live due date and status."""
    _ensure_vendor_tables(con)
    rows = con.execute(
        """SELECT e.*,
                  r.name AS req_name, r.criterion, r.evidence AS req_evidence,
                  r.source, r.basis, r.note AS req_note,
                  p.name AS pack_name,
                  v.name AS performer_name, v.phone AS performer_phone,
                  v.kind AS performer_kind,
                  (SELECT result FROM compliance_events
                   WHERE eqc_id=e.eqc_id ORDER BY done_date DESC, event_id DESC LIMIT 1) AS last_result
           FROM equipment_compliance e
           LEFT JOIN compliance_requirements r ON r.req_id = e.req_id
           LEFT JOIN compliance_packs p ON p.pack_id = e.pack_id
           LEFT JOIN vendors v ON v.vendor_id = e.performer_id
           WHERE e.asset_id=? ORDER BY e.eqc_id""",
        (asset_id,),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["display_name"] = r["custom_name"] or r["req_name"] or "(unnamed)"
        d["next_due_live"] = checklist_next_due(r["trigger"], r["interval_months"],
                                                r["deployed_backstop_months"], r["last_done"])
        d["status"] = checklist_status(r, today)
        out.append(d)
    return out
def compliance_summary(con: sqlite3.Connection, asset_id: str, today=None) -> dict:
    s = {"total": 0, "overdue": 0, "due": 0, "ok": 0, "info": 0}
    for it in unit_checklist(con, asset_id, today):
        s["total"] += 1
        s[it["status"]] += 1
    return s
@ttl_cached()
def fleet_compliance_watch(con: sqlite3.Connection, today=None):
    """Units with overdue/due checklist items — dashboard + reports feed.
    Single query for all assets (was N+1: one unit_checklist per asset)."""
    today = today or date.today()
    _ensure_vendor_tables(con)
    rows = con.execute(
        """SELECT e.*,
                  r.name AS req_name, r.criterion, r.evidence AS req_evidence,
                  r.source, r.basis, r.note AS req_note,
                  p.name AS pack_name,
                  v.name AS performer_name, v.phone AS performer_phone,
                  v.kind AS performer_kind,
                  a.unit_no, a.description,
                  (SELECT result FROM compliance_events
                   WHERE eqc_id=e.eqc_id ORDER BY done_date DESC, event_id DESC LIMIT 1) AS last_result
           FROM equipment_compliance e
           JOIN assets a ON a.asset_id = e.asset_id AND a.active = 1
           LEFT JOIN compliance_requirements r ON r.req_id = e.req_id
           LEFT JOIN compliance_packs p ON p.pack_id = e.pack_id
           LEFT JOIN vendors v ON v.vendor_id = e.performer_id
           ORDER BY a.unit_no, e.eqc_id""",
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["display_name"] = r["custom_name"] or r["req_name"] or "(unnamed)"
        d["next_due_live"] = checklist_next_due(r["trigger"], r["interval_months"],
                                                r["deployed_backstop_months"], r["last_done"])
        d["status"] = checklist_status(r, today)
        if d["status"] in ("overdue", "due"):
            out.append({
                "asset_id": r["asset_id"], "unit_no": r["unit_no"],
                "description": r["description"], "item": d["display_name"],
                "eqc_id": r["eqc_id"],
                "status": d["status"],
                "next_due": d["next_due_live"].isoformat() if d["next_due_live"] else "",
                "last_done": r["last_done"] or "",
                "performer_name": r["performer_name"] or "",
                "performer_phone": r["performer_phone"] or "",
                "performer_kind": r["performer_kind"] or "",
            })
    return out


# ---------------------------------------------------------------------------
# Cert identity (Q5, 2026-09-27): every certification, calibration, and
# function test is a first-class record that NAMES ITS ASSET. No more
# free-floating or bare-expiry certs. Evidence paperwork attaches to the
# record (via the unit's data book, which already carries the asset_id),
# so an auditor can always see which asset a document certifies.
# ---------------------------------------------------------------------------

CERT_KINDS = {
    "certification": "Certification",
    "calibration": "Calibration",
    "function_test": "Function test",
    "other": "Other",
}

_MIGRATED_TITLE = "Certificate (migrated from unit record)"


def ensure_cert_tables(con: sqlite3.Connection) -> None:
    """Repair-only compatibility hook; schema.sql owns current table DDL."""
    row = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='asset_certs'").fetchone()
    if not row:
        raise RuntimeError("Database schema is incomplete: asset_certs is missing")


def _clean_cert_kind(kind: str) -> str:
    kind = (kind or "").strip()
    return kind if kind in CERT_KINDS else "certification"


def _clean_iso(d):
    d = (d or "").strip()
    if not d:
        return None
    return d[:10] if _parse(d) else None


def save_cert(con: sqlite3.Connection, asset_id: str, kind: str, title: str,
              cert_number: str = "", issuer: str = "", issued_date=None,
              expiry_date=None, notes: str = "", clerk: str = "") -> int:
    """A cert record MUST name its asset — no free-floating certs."""
    ensure_cert_tables(con)
    asset_id = (asset_id or "").strip()
    if not asset_id:
        raise ValueError("Pick the unit this certificate covers")
    if not con.execute("SELECT 1 FROM assets WHERE asset_id=?",
                       (asset_id,)).fetchone():
        raise ValueError("Unknown unit")
    title = (title or "").strip()
    if not title:
        raise ValueError("Name the certificate")
    cur = con.execute(
        """INSERT INTO asset_certs
           (asset_id, kind, title, cert_number, issuer, issued_date,
            expiry_date, notes, clerk)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (asset_id, _clean_cert_kind(kind), title,
         (cert_number or "").strip(), (issuer or "").strip(),
         _clean_iso(issued_date), _clean_iso(expiry_date),
         notes or "", clerk or ""),
    )
    con.commit()
    return cur.lastrowid


def update_cert(con: sqlite3.Connection, cert_id: int, kind: str | None = None,
                title: str | None = None, cert_number: str | None = None,
                issuer: str | None = None, issued_date=None, expiry_date=None,
                notes: str | None = None) -> None:
    ensure_cert_tables(con)
    row = con.execute("SELECT * FROM asset_certs WHERE cert_id=?",
                      (cert_id,)).fetchone()
    if not row:
        raise ValueError("Unknown certificate")
    kind = _clean_cert_kind(kind) if kind is not None else row["kind"]
    title = row["title"] if title is None else (title or "").strip()
    if not title:
        raise ValueError("Name the certificate")
    con.execute(
        """UPDATE asset_certs SET kind=?, title=?, cert_number=?, issuer=?,
               issued_date=?, expiry_date=?, notes=? WHERE cert_id=?""",
        (kind, title,
         row["cert_number"] if cert_number is None else (cert_number or "").strip(),
         row["issuer"] if issuer is None else (issuer or "").strip(),
         row["issued_date"] if issued_date is None else _clean_iso(issued_date),
         row["expiry_date"] if expiry_date is None else _clean_iso(expiry_date),
         row["notes"] if notes is None else (notes or ""),
         cert_id),
    )
    con.commit()


def delete_cert(con: sqlite3.Connection, cert_id: int) -> None:
    """Remove the record. Attached evidence stays in the unit's data book —
    paperwork is never destroyed by deleting a record."""
    ensure_cert_tables(con)
    con.execute("DELETE FROM asset_certs WHERE cert_id=?", (cert_id,))
    con.commit()


def get_cert(con: sqlite3.Connection, cert_id: int):
    ensure_cert_tables(con)
    r = con.execute(
        """SELECT c.*, a.unit_no, a.description AS asset_desc,
                  d.title AS doc_title, d.filename AS doc_filename
           FROM asset_certs c
           JOIN assets a ON a.asset_id = c.asset_id
           LEFT JOIN unit_docs d ON d.doc_id = c.evidence_doc_id
           WHERE c.cert_id=?""",
        (cert_id,)).fetchone()
    return dict(r) if r else None


def list_certs(con: sqlite3.Connection, asset_id: str, today=None):
    """Every cert record for a unit, with evidence doc and live status."""
    ensure_cert_tables(con)
    rows = con.execute(
        """SELECT c.*, a.unit_no,
                  d.title AS doc_title, d.filename AS doc_filename
           FROM asset_certs c
           JOIN assets a ON a.asset_id = c.asset_id
           LEFT JOIN unit_docs d ON d.doc_id = c.evidence_doc_id
           WHERE c.asset_id=? ORDER BY c.superseded, c.expiry_date, c.cert_id""",
        (asset_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["status"] = cert_status(d, today)
        d["kind_label"] = CERT_KINDS.get(d["kind"], d["kind"])
        out.append(d)
    return out


def fleet_certs(con: sqlite3.Connection, today=None):
    """Every cert record in the fleet — the audit view: which asset each
    document covers, what it is, when it expires."""
    ensure_cert_tables(con)
    rows = con.execute(
        """SELECT c.*, a.unit_no, a.description AS asset_desc,
                  d.title AS doc_title
           FROM asset_certs c
           JOIN assets a ON a.asset_id = c.asset_id
           LEFT JOIN unit_docs d ON d.doc_id = c.evidence_doc_id
           ORDER BY a.unit_no, c.superseded, c.expiry_date""").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["status"] = cert_status(d, today)
        d["kind_label"] = CERT_KINDS.get(d["kind"], d["kind"])
        out.append(d)
    return out


def cert_status(cert, today=None) -> str:
    """A cert record's live state: expired | valid | no-expiry. Superseded
    records keep their history but never drive alerts."""
    if not isinstance(cert, dict):
        cert = dict(cert)
    if cert.get("superseded"):
        return "superseded"
    today = today or date.today()
    exp = _parse(cert.get("expiry_date")) if cert.get("expiry_date") else None
    if not exp:
        return "no-expiry"
    return "expired" if exp < today else "valid"


def set_cert_superseded(con: sqlite3.Connection, cert_id: int,
                        superseded: bool = True) -> None:
    """Mark an old cert superseded when it is renewed — history stays, but it
    no longer drives the operative expiry."""
    ensure_cert_tables(con)
    if not con.execute("SELECT 1 FROM asset_certs WHERE cert_id=?",
                       (cert_id,)).fetchone():
        raise ValueError("Unknown certificate")
    con.execute("UPDATE asset_certs SET superseded=? WHERE cert_id=?",
                (1 if superseded else 0, cert_id))
    con.commit()


def attach_cert_evidence(con: sqlite3.Connection, cert_id: int,
                         doc_id: int) -> None:
    """Tie a data-book document to the cert record. The document must belong
    to the SAME asset — the evidence always identifies the asset it covers."""
    ensure_cert_tables(con)
    cert = con.execute("SELECT asset_id FROM asset_certs WHERE cert_id=?",
                       (cert_id,)).fetchone()
    if not cert:
        raise ValueError("Unknown certificate")
    doc = con.execute("SELECT asset_id FROM unit_docs WHERE doc_id=?",
                      (doc_id,)).fetchone()
    if not doc:
        raise ValueError("Unknown document")
    if doc["asset_id"] != cert["asset_id"]:
        raise ValueError("That document belongs to a different unit")
    con.execute("UPDATE asset_certs SET evidence_doc_id=? WHERE cert_id=?",
                (doc_id, cert_id))
    con.commit()


def operative_cert_expiry(con: sqlite3.Connection, asset_id: str):
    """The expiry that drives fit-checks and alerts: the earliest expiry
    among the asset's live (non-superseded) cert records. Falls back to the
    legacy assets.cert_expire column for stragglers. Returns 'YYYY-MM-DD'
    or None."""
    ensure_cert_tables(con)
    row = con.execute(
        """SELECT MIN(expiry_date) FROM asset_certs
           WHERE asset_id=? AND superseded=0
             AND expiry_date IS NOT NULL AND expiry_date != ''""",
        (asset_id,)).fetchone()
    if row and row[0]:
        return str(row[0])[:10]
    leg = con.execute("SELECT cert_expire FROM assets WHERE asset_id=?",
                      (asset_id,)).fetchone()
    if leg and leg[0] and str(leg[0]).strip():
        return str(leg[0])[:10]
    return None


def migrate_legacy_cert_expiry(con: sqlite3.Connection) -> int:
    """Upgrade path for the bare assets.cert_expire field: every legacy
    expiry becomes a real cert record naming its asset. Idempotent — a
    rerun never duplicates."""
    ensure_cert_tables(con)
    moved = 0
    for a in con.execute(
            """SELECT asset_id, cert_expire FROM assets
               WHERE cert_expire IS NOT NULL AND TRIM(cert_expire) != ''"""):
        exp = str(a["cert_expire"])[:10]
        exists = con.execute(
            """SELECT 1 FROM asset_certs
               WHERE asset_id=? AND title=? AND COALESCE(expiry_date,'')=?""",
            (a["asset_id"], _MIGRATED_TITLE, exp)).fetchone()
        if exists:
            continue
        con.execute(
            """INSERT INTO asset_certs
               (asset_id, kind, title, expiry_date, notes)
               VALUES (?,?,?,?,?)""",
            (a["asset_id"], "certification", _MIGRATED_TITLE, exp,
             "Migrated from the unit record's bare expiry date. "
             "Attach the paperwork and renew as a proper record."),
        )
        moved += 1
    con.commit()
    return moved
