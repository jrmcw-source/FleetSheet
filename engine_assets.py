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
import re
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


"""FleetSheet engine: assets flow — units, sites, tickets, work orders, rental calculations, availability reports."""

__all__ = ['billable_days', 'applied_rate', 'rental_amount', 'compliance', 'fit_reason', 'possession_rules', 'ticket_money', 'asset_status', 'next_ticket_id', 'create_ticket', 'SoftReserveConflict', 'update_ticket_transport', 'condition_worse', 'save_ticket_condition', 'save_ticket_photo', 'read_ticket_photo', 'set_status', 'ready_work_orders', 'next_asset_id', 'save_asset', 'next_site_id', 'save_site', 'report_availability', 'report_upcoming', 'report_stays', 'report_maintenance', 'next_wo_id', 'wo_cost', 'save_wo', 'report_work_orders', 'HAUL_BY', 'DELIVER_TO', 'HAUL_LABELS', 'DELIVER_LABELS', 'clean_haul_by', 'clean_deliver_to', 'haul_consequence', 'haul_from', 'RATE_UNITS', 'clean_rate_unit', 'ticket_hours',
 'day_equivalent']

# Single rate field (2026-09-27): one unit + one value per record. The common
# four lead; Monthly/Standby/Yard stay legal for legacy records that use them.
RATE_UNITS = ("Day", "Week", "Hour", "Special", "Monthly", "Standby", "Yard")
# Legacy adjective forms, normalized to the canonical four at rest.
_LEGACY_RATE_UNIT = {"Daily": "Day", "Weekly": "Week"}

def clean_rate_unit(v) -> str:
    v = (v or "").strip()
    v = _LEGACY_RATE_UNIT.get(v, v)
    return v if v in RATE_UNITS else "Day"

def ticket_hours(t) -> float:
    """Billable hours from the ticket's hour-meter readings (0 when absent)."""
    try:
        hs = float(_row_get(t, "hours_start", 0) or 0)
        he = float(_row_get(t, "hours_end", 0) or 0)
    except (TypeError, ValueError):
        return 0.0
    return max(he - hs, 0.0) if hs > 0 and he > 0 else 0.0

def day_equivalent(unit, value) -> float:
    """A rate expressed per day, for at-a-glance totals. Week/Monthly prorate
    exactly as billing does; Hour and Special have no day equivalent (0)."""
    unit = _LEGACY_RATE_UNIT.get(unit or "", unit or "")
    v = float(value or 0)
    if unit == "Week":
        return v / 7.0
    if unit == "Monthly":
        return v / 30.0
    if unit in ("Day", "Standby", "Yard"):
        return v
    return 0.0

# Who hauls the unit, and where it goes. Stored context on the ticket;
# tax/fee math still keys off customer_transport (mapped from haul_by).
HAUL_BY = ("we", "customer", "third_party")
HAUL_LABELS = {
    "we": "We deliver — our truck",
    "customer": "Customer picks up — their truck",
    "third_party": "Third-party truck",
}
DELIVER_TO = ("our_yard", "customer_yard", "job_site", "dock")
DELIVER_LABELS = {
    "our_yard": "Our yard",
    "customer_yard": "Customer yard",
    "job_site": "Job site",
    "dock": "Dock — offshore",
}

def clean_haul_by(v) -> str:
    v = (v or "").strip()
    return v if v in HAUL_BY else "we"

def clean_deliver_to(v) -> str:
    v = (v or "").strip()
    return v if v in DELIVER_TO else "job_site"

def haul_from(data: dict) -> str:
    """haul_by from a form dict, with legacy customer_transport compat."""
    if data.get("haul_by") is None and "customer_transport" in data:
        return "customer" if data.get("customer_transport") else "we"
    return clean_haul_by(data.get("haul_by"))

def haul_consequence(haul: str, dest: str) -> str:
    """Explain the operational consequence. Tax is the operator's call —
    the software states where possession transfers, never the tax situs."""
    if haul == "customer":
        return ("Customer pickup at our yard. Tax jurisdiction is your call — "
                "pick it explicitly on the ticket.")
    fee = ("Our truck delivers — a transportation fee applies."
           if haul == "we" else
           "Third-party carrier delivers — no FleetSheet transportation fee unless entered.")
    return (f"{fee} Possession transfers at the {DELIVER_LABELS.get(dest, dest).lower()}. "
            f"Tax jurisdiction is your call — pick it explicitly on the ticket.")


def _possession_destination(haul: str, dest: str) -> str:
    """Return the operational possession destination before tax lookup."""
    return "our_yard" if haul == "customer" else dest


def clean_tax_loc_id(value) -> str | None:
    """Tax jurisdiction is the operator's explicit choice — never inferred,
    never autofilled. Blank stays blank: the software does not decide tax."""
    loc = (value or "").strip()
    return loc or None

def billable_days(on_s: str, off_s: str | None, today: date | None, min_days: int, both: bool) -> int:
    on = _parse(on_s)
    if not on:
        return 0
    off = _parse(off_s) or (today or date.today())
    if off < on:
        return min_days
    raw = (off - on).days + (1 if both else 0)
    if not both:
        raw = max((off - on).days, 1)
    return max(raw, min_days)
def applied_rate(asset: sqlite3.Row, rate_type: str, override: float | None) -> float:
    # An explicit per-ticket value always wins (any unit, not just Special).
    if override not in (None, ""):
        return float(override)
    unit = _LEGACY_RATE_UNIT.get(rate_type or "", rate_type or "")
    cols = asset.keys() if hasattr(asset, "keys") else ()
    # The single rate field: the asset's own unit + value. In ticket+asset
    # joined rows both sides now carry rate_value, so read the aliased
    # asset_rate_* columns (ticket_money provides them); fall back to the
    # plain names for pure asset rows.
    au = asset["asset_rate_unit"] if "asset_rate_unit" in cols else (asset["rate_unit"] if "rate_unit" in cols else "")
    av = asset["asset_rate_value"] if "asset_rate_value" in cols else (asset["rate_value"] if "rate_value" in cols else 0)
    if (au or "") == unit:
        return float(av or 0)
    # Legacy fallback: the old per-unit columns (frozen at migration).
    col = {
        "Day": "daily_rate", "Daily": "daily_rate",
        "Week": "weekly_rate", "Weekly": "weekly_rate",
        "Monthly": "monthly_rate", "Standby": "standby_rate",
        "Yard": "yard_rate", "Special": "special_rate",
    }.get(unit)
    if col and col in cols:
        return float(asset[col] or 0)
    return 0.0
def rental_amount(rate: float, rate_type: str, days: int, hours: float = 0.0) -> float:
    unit = _LEGACY_RATE_UNIT.get(rate_type or "", rate_type or "")
    if unit == "Week":
        return rate * max(days / 7.0, 1 / 7.0)
    if unit == "Monthly":
        return rate * max(days / 30.0, 1 / 30.0)
    if unit == "Hour":
        return rate * max(hours or 0.0, 0.0)
    return rate * days
def compliance(asset: sqlite3.Row, site_j: sqlite3.Row, today: date | None = None,
               cert_expiry=None) -> str:
    today = today or date.today()
    # Cert identity (Q5): the operative expiry comes from the asset's cert
    # records; the bare assets.cert_expire column is only the legacy fallback.
    exp = _parse(cert_expiry) if cert_expiry is not None else _parse(asset["cert_expire"])
    if exp and exp < today:
        return "FAIL-CERT"
    if site_j["req_uscg"] and not asset["uscg_ok"]:
        return "FAIL-USCG"
    if site_j["req_dnv"] and not asset["dnv_ok"]:
        return "FAIL-DNV"
    if site_j["req_abs"] and not asset["abs_ok"]:
        return "FAIL-ABS"
    return "PASS"


def fit_reason(fit_code: str, cert_expire=None) -> str:
    """Plain-English reason for a failing fit code — for alerts and warnings.

    Paper only matters at shipping (receiving checks it once); this names
    what the receiving site would flag."""
    if fit_code == "FAIL-CERT":
        return f"cert expired {str(cert_expire)[:10]}" if cert_expire else "cert expired"
    return {
        "FAIL-USCG": "site requires a USCG stamp this unit doesn't have",
        "FAIL-DNV": "site requires a DNV stamp this unit doesn't have",
        "FAIL-ABS": "site requires an ABS stamp this unit doesn't have",
    }.get(fit_code or "", "paper doesn't fit this job")
def possession_rules(con: sqlite3.Connection, t) -> dict:
    """Possession facts + tax from the operator's explicit jurisdiction ONLY.

    Jason's rule (2026-10-04): the software never decides tax. Tax is computed
    solely from the ticket's explicit tax jurisdiction — the operator's pick.
    When none is set, no tax is computed; that is the operator's call, not the
    app's. Customer/site tax-exempt flags are the operator's own record data
    and still apply. Possession labels state operational facts only.
    """
    haul = clean_haul_by(_row_get(t, "haul_by"))
    dest = clean_deliver_to(_row_get(t, "deliver_to"))
    customer_haul = haul == "customer"
    cust_exempt = int(_row_get(t, "cust_tax_exempt", 0) or 0) == 1
    site_exempt = int(_row_get(t, "site_tax_exempt", 0) or 0) == 1
    explicit_loc = (_row_get(t, "tax_loc_id") or "").strip()
    possession_dest = _possession_destination(haul, dest)

    if customer_haul:
        label = "Customer pickup at our yard"
    else:
        label = f"Delivered to {DELIVER_LABELS.get(dest, dest).lower()}"

    tax_loc, tax_name, tax_rate = "", "Tax jurisdiction not set", 0.0
    if explicit_loc:
        jr = con.execute(
            "SELECT loc_id, display_name, tax_rate, tax_name FROM jurisdictions WHERE loc_id=?",
            (explicit_loc,)).fetchone()
        if jr:
            tax_loc = jr["loc_id"]
            tax_name = jr["tax_name"] or "Tax"
            tax_rate = float(jr["tax_rate"] or 0)

    return {
        "customer_transport": customer_haul,
        "haul_by": haul,
        "deliver_to": dest,
        "possession_point": possession_dest,
        "possession_label": label,
        "tax_loc": tax_loc,
        "tax_name": tax_name,
        "tax_rate": float(tax_rate or 0),
        "tax_exempt": cust_exempt or site_exempt,
        "tax_note": ("Tax from the operator's selected jurisdiction."
                     if explicit_loc else
                     "No tax jurisdiction selected — tax is the operator's call."),
    }

def ticket_money(con: sqlite3.Connection, ticket_id: str) -> dict:
    t = con.execute(
        """
        SELECT t.*, a.*, s.loc_id AS site_loc_id, s.site_name,
               COALESCE(s.tax_exempt, 0) AS site_tax_exempt,
               j.tax_rate AS site_tax_rate, j.tax_name AS site_tax_name,
               j.display_name AS site_loc_name,
               j.req_uscg, j.req_dnv, j.req_abs,
               c.account_name, c.waiver_default,
               COALESCE(c.tax_exempt, 0) AS cust_tax_exempt,
               co.waiver_pct, co.env_pct, co.min_days, co.bill_both_dates,
               co.default_tax, co.yard_loc_id,
               yj.tax_rate AS yard_tax_rate, yj.tax_name AS yard_tax_name,
               yj.display_name AS yard_loc_name,
               a.rate_unit AS asset_rate_unit, a.rate_value AS asset_rate_value
        FROM tickets t
        JOIN assets a ON a.asset_id = t.asset_id
        JOIN sites s ON s.site_id = t.site_id
        LEFT JOIN jurisdictions j ON j.loc_id = s.loc_id
        JOIN customers c ON c.customer_id = t.customer_id
        JOIN company co ON co.id = 1
        LEFT JOIN jurisdictions yj ON yj.loc_id = co.yard_loc_id
        WHERE t.ticket_id = ?
        """,
        (ticket_id,),
    ).fetchone()
    if not t:
        return {}
    days = billable_days(t["on_rent"], t["off_rent"], date.today(), t["min_days"], bool(t["bill_both_dates"]))
    rate = applied_rate(t, t["rate_type"], _row_get(t, "rate_value", _row_get(t, "special_override")))
    hours = ticket_hours(t)
    rental = rental_amount(rate, t["rate_type"], days, hours)
    transport = (
        float(_row_get(t, "mob", 0) or 0)
        + float(_row_get(t, "demob", 0) or 0)
        + float(_row_get(t, "transport_fee", 0) or 0)
    )
    other = float(t["fuel"] or 0) + float(t["parts"] or 0) + float(t["other_amt"] or 0)
    waiver = rental * float(t["waiver_pct"]) if t["waiver_yn"] else 0.0
    env = rental * float(t["env_pct"])
    rental_sub = rental + waiver + env
    sub = rental_sub + transport + other
    pos = possession_rules(con, t)
    tax = 0.0 if pos["tax_exempt"] else sub * pos["tax_rate"]
    # Cert identity (Q5): fit reads the operative cert-record expiry, not the
    # bare legacy column. Lazy import: engine_compliance must not be a
    # module-level import here (engine.py import order).
    from engine_compliance import operative_cert_expiry
    cert_expiry = operative_cert_expiry(con, t["asset_id"])
    return {
        "days": days,
        "hours": round(hours, 2),
        "rate": rate,
        "rental": round(rental, 2),
        "transport": round(transport, 2),
        "mob": round(float(_row_get(t, "mob", 0) or 0), 2),
        "demob": round(float(_row_get(t, "demob", 0) or 0), 2),
        "transport_fee": round(float(_row_get(t, "transport_fee", 0) or 0), 2),
        "other": round(other, 2),
        "waiver": round(waiver, 2),
        "env": round(env, 2),
        "rental_sub": round(rental_sub, 2),
        "subtotal": round(sub, 2),
        "tax": round(tax, 2),
        "total": round(sub + tax, 2),
        "fit": compliance(t, t, cert_expiry=cert_expiry),
        "cert_expiry": cert_expiry,
        "account_name": t["account_name"],
        "unit_no": t["unit_no"],
        "description": t["description"],
        **pos,
    }
def asset_status(con: sqlite3.Connection, asset_id: str) -> str:
    row = con.execute(
        """SELECT status FROM tickets
           WHERE asset_id=? AND status NOT IN ('Billed','Closed','Void','Quoted','Off Rent','Ready to Bill')
           ORDER BY on_rent DESC LIMIT 1""",
        (asset_id,),
    ).fetchone()
    if row:
        return row["status"]
    sold = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sales'"
    ).fetchone()
    return "Available"
def next_ticket_id(con: sqlite3.Connection) -> str:
    n = _reserve_counter(con, "next_ticket", 1001)
    return f"T-{n}"
class SoftReserveConflict(Exception):
    """A new ticket overlaps a PO soft-reservation. The app never auto-blocks
    here — it names the stakes and lets the operator pick which reservation
    wins. Carries the blocking ticket's row in `.ticket`."""
    def __init__(self, ticket_row):
        self.ticket = ticket_row
        super().__init__(f"Unit soft-reserved on ticket {ticket_row['ticket_id']}")


def create_ticket(con: sqlite3.Connection, data: dict) -> str:
    aid = data["asset_id"]
    busy = con.execute(
        """SELECT ticket_id, customer_id, job_name, well_or_pad, po, on_rent, off_rent,
                  COALESCE(soft_reserve,0) AS soft_reserve
           FROM tickets
           WHERE asset_id=? AND status IN ('Reserved','Dispatched','On Rent','Standby')""",
        (aid,),
    ).fetchone()
    if busy:
        if busy["soft_reserve"]:
            # PO soft-reserve: flag it, don't block it. The web layer names
            # the stakes and the operator chooses.
            raise SoftReserveConflict(busy)
        raise ValueError(f"Unit already on ticket {busy['ticket_id']} ({'open'})")
    # B1: tickets enter the workflow at the start — Quoted or Reserved only.
    # Creating one directly as Billed / On Rent / Dispatched skips check-out,
    # FIT, and invoicing gates.
    status = (data.get("status") or "Quoted").strip()
    if status not in ("Quoted", "Reserved"):
        raise ValueError(f"New tickets start as Quoted or Reserved, not {status}")
    # B8: never store garbage dates.
    on_rent = parse_date(data.get("on_rent"), "On-rent date")
    off_rent = parse_date(data.get("off_rent"), "Off-rent date", required=False)
    tid = data.get("ticket_id") or next_ticket_id(con)
    haul = haul_from(data)
    dest = clean_deliver_to(data.get("deliver_to"))
    tax_loc_id = clean_tax_loc_id(data.get("tax_loc_id"))
    if tax_loc_id and not con.execute("SELECT 1 FROM jurisdictions WHERE loc_id=?", (tax_loc_id,)).fetchone():
        raise ValueError("Selected tax jurisdiction does not exist")
    # A Reserved ticket carrying a PO is a soft hold for that PO's job — it
    # must not block an interim booking (Jason 2026-09-30 / 2026-10-04).
    soft = 1 if status == "Reserved" and (data.get("po") or "").strip() else 0
    con.execute(
        """INSERT INTO tickets (
            ticket_id, customer_id, site_id, asset_id, job_name, well_or_pad, afe, po,
            rate_type, rate_value, on_rent, off_rent, mob, demob, fuel, parts,
            other_amt, transport_fee, customer_transport, haul_by, deliver_to, tax_loc_id,
            waiver_yn, status, soft_reserve, location_note, haul_note, deliver_note
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            tid, data["customer_id"], data["site_id"], data["asset_id"],
            data.get("job_name") or "", data.get("well_or_pad") or "",
            data.get("afe") or "", data.get("po") or "",
            clean_rate_unit(data.get("rate_type")),
            data.get("rate_value") if data.get("rate_value") not in (None, "") else data.get("special_override"),
            on_rent, off_rent,
            float(data.get("mob") or 0), float(data.get("demob") or 0),
            float(data.get("fuel") or 0), float(data.get("parts") or 0),
            float(data.get("other_amt") or 0),
            float(data.get("transport_fee") or 0),
            0 if haul == "we" else 1,
            haul, dest, tax_loc_id,
            1 if data.get("waiver_yn", True) else 0,
            status, soft,
            data.get("location_note") or "",
            data.get("haul_note") or "",
            data.get("deliver_note") or "",
        ),
    )
    if (data.get("quote_no") or "").strip():
        _set_quote_link(con, "tickets", "ticket_id", tid, data["quote_no"].strip(), data["customer_id"])
    con.commit()
    return tid
def update_ticket_transport(con: sqlite3.Connection, ticket_id: str, data: dict) -> None:
    t = con.execute("SELECT status, invoice_no FROM tickets WHERE ticket_id=?", (ticket_id,)).fetchone()
    if not t:
        raise ValueError("Unknown ticket")
    if t["status"] in ("Billed", "Closed", "Void") or t["invoice_no"]:
        raise ValueError("Transport / possession is locked after invoicing")
    haul = haul_from(data)
    dest = clean_deliver_to(data.get("deliver_to"))
    tax_loc_id = clean_tax_loc_id(data.get("tax_loc_id"))
    if tax_loc_id and not con.execute("SELECT 1 FROM jurisdictions WHERE loc_id=?", (tax_loc_id,)).fetchone():
        raise ValueError("Selected tax jurisdiction does not exist")
    con.execute(
        """UPDATE tickets SET customer_transport=?, haul_by=?, deliver_to=?, tax_loc_id=?,
           transport_fee=?, mob=?, demob=? WHERE ticket_id=?""",
        (
            0 if haul == "we" else 1,
            haul, dest, tax_loc_id,
            float(data.get("transport_fee") or 0),
            float(data.get("mob") or 0),
            float(data.get("demob") or 0),
            ticket_id,
        ),
    )
    con.commit()
def condition_worse(out_c: str | None, in_c: str | None) -> bool:
    return COND_RANK.get(in_c or "", 0) > COND_RANK.get(out_c or "", 0)
def _condition_ticket(con: sqlite3.Connection, ticket_id: str):
    """Fetch a ticket for condition/photo edits; enforces the invoice lock."""
    t = con.execute("SELECT * FROM tickets WHERE ticket_id=?", (ticket_id,)).fetchone()
    if not t:
        raise ValueError("Unknown ticket")
    if t["status"] in ("Billed", "Closed", "Void") or t["invoice_no"]:
        raise ValueError("Condition is locked on the invoice")
    return t


def save_ticket_condition(con: sqlite3.Connection, ticket_id: str, side: str, data: dict) -> None:
    t = _condition_ticket(con, ticket_id)
    side = (side or "").strip().lower()
    if side not in ("out", "in"):
        raise ValueError("Condition is out or in")
    cond = (data.get("condition") or "").strip()
    if cond not in COND_RANK:
        raise ValueError("Pick a condition")
    clerk = require_clerk(data.get("clerk"))
    meter = (data.get("meter") or "").strip()
    note = (data.get("note") or "").strip()
    # Numeric hour-meter reading, alongside the free-text meter/fuel field.
    try:
        hrs = float(data.get("hours") or 0) or None
    except (TypeError, ValueError):
        hrs = None
    # A blank/absent photo value keeps the existing photo; real uploads go
    # through save_ticket_photo(). This keeps file inputs from wiping photos.
    photo = (data.get("photo") or "").strip()
    when = date.today().isoformat()
    cols = ["out_condition", "out_note", "out_meter"]
    if photo:
        cols.append("out_photo")
    cols += ["out_by", "out_at", "out_src", "clerk"]
    if side == "in":
        cols = [c.replace("out_", "in_") for c in cols]
    src = (data.get("source") or "desk").strip() or "desk"
    vals = {"out_condition": cond, "out_note": note, "out_meter": meter,
            "out_photo": photo, "out_by": clerk, "out_at": when,
            "out_src": src, "clerk": clerk}
    if side == "in":
        vals = {k.replace("out_", "in_"): v for k, v in vals.items()}
    hcol = "hours_start" if side == "out" else "hours_end"
    hcols = [r[1] for r in con.execute("PRAGMA table_info(tickets)")]
    if hrs and hcol in hcols:
        cols.append(hcol)
        vals[hcol] = hrs
    set_clause = ", ".join(f"{c}=?" for c in cols)
    con.execute(f"UPDATE tickets SET {set_clause} WHERE ticket_id=?",
                [vals[c] for c in cols] + [ticket_id])
    if side == "in" and hrs:
        # Keep the unit's hour meter current from check-in readings.
        acols = [r[1] for r in con.execute("PRAGMA table_info(assets)")]
        if "meter_hours" in acols:
            cur = con.execute(
                "SELECT meter_hours FROM assets WHERE asset_id=?",
                (t["asset_id"],)).fetchone()
            cur = float(cur[0] or 0) if cur else 0.0
            if hrs > cur:
                con.execute("UPDATE assets SET meter_hours=? WHERE asset_id=?",
                            (hrs, t["asset_id"]))
    con.commit()


def save_ticket_photo(con: sqlite3.Connection, ticket_id: str, side: str,
                      blob: bytes, orig_name: str = "") -> str:
    """Store an uploaded condition photo (JPG/PNG/WebP, 10 MB max). Returns the stored name.

    The blob is fully validated (type + decodable image) before anything is
    written. The stored name carries microseconds plus a random suffix, so
    two rapid uploads can never collide on the old one-second timestamp.
    """
    t = _condition_ticket(con, ticket_id)
    side = (side or "").strip().lower()
    if side not in ("out", "in"):
        raise ValueError("Condition is out or in")
    ext = validate_photo_blob(blob)
    safe_tid = re.sub(r"[^A-Za-z0-9_-]", "_", ticket_id)[:32] or "ticket"
    stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    name = f"{safe_tid}-{side}-{stamp}-{secrets.token_hex(2)}{ext}"
    d = photo_dir()
    (d / name).write_bytes(blob)
    col = "out_photo" if side == "out" else "in_photo"
    old = safe_photo_name(t[col])
    con.execute(f"UPDATE tickets SET {col}=? WHERE ticket_id=?", (name, ticket_id))
    con.commit()
    if old and old != name:
        try:
            (d / old).unlink(missing_ok=True)
        except OSError:
            pass
    return name


def read_ticket_photo(con: sqlite3.Connection, ticket_id: str,
                      side: str) -> tuple[bytes, str] | None:
    """Return (bytes, content-type) for a ticket's condition photo, or None."""
    if (side or "").strip().lower() not in ("out", "in"):
        return None
    col = "out_photo" if side == "out" else "in_photo"
    t = con.execute(f"SELECT {col} FROM tickets WHERE ticket_id=?", (ticket_id,)).fetchone()
    if not t:
        return None
    name = safe_photo_name(t[0])
    if not name:
        return None
    p = photo_dir() / name
    if not p.is_file():
        return None
    return p.read_bytes(), PHOTO_EXTS["." + name.rsplit(".", 1)[1]]
def set_status(con: sqlite3.Connection, ticket_id: str, new: str, off_rent: str | None = None, clerk: str | None = None) -> None:
    t = con.execute("SELECT * FROM tickets WHERE ticket_id=?", (ticket_id,)).fetchone()
    if not t:
        raise ValueError("Unknown ticket")
    if new not in ALLOWED_NEXT.get(t["status"], ()):
        raise ValueError(f"Cannot move {t['status']} → {new}")
    who = require_clerk(clerk)
    # B8: validate the off-rent date instead of storing it verbatim.
    if off_rent:
        off_rent = parse_date(off_rent, "Off-rent date", required=False)
    if new in ("Off Rent", "Ready to Bill") and not (off_rent or t["off_rent"]):
        off_rent = date.today().isoformat()
    if new == "Billed" and not t["invoice_no"]:
        raise ValueError("Assign an invoice before Billed")
    if new in ("Dispatched", "On Rent"):
        out_c = t["out_condition"] if "out_condition" in t.keys() else None
        if not out_c:
            raise ValueError("Record check-out condition before dispatch / on rent")
        money = ticket_money(con, ticket_id)
        if money.get("fit") and money["fit"] != "PASS":
            raise ValueError(f"FIT is {money['fit']} — do not dispatch")
    if new in ("Off Rent", "Ready to Bill"):
        in_c = t["in_condition"] if "in_condition" in t.keys() else None
        if not in_c:
            raise ValueError("Record check-in condition before off rent")
    con.execute(
        "UPDATE tickets SET status=?, off_rent=COALESCE(?, off_rent), clerk=? WHERE ticket_id=?",
        (new, off_rent, who, ticket_id),
    )
    con.commit()
def ready_work_orders(con, customer_id: str | None = None):
    q = """SELECT w.wo_id, w.customer_id, w.bill_amount, w.description, w.work_type,
                  a.unit_no, c.account_name
           FROM work_orders w
           JOIN assets a ON a.asset_id = w.asset_id
           JOIN customers c ON c.customer_id = w.customer_id
           WHERE w.charge_to='customer' AND w.status='Complete'
             AND w.bill_amount > 0
             AND (w.invoice_no IS NULL OR w.invoice_no='')
        """
    args = []
    if customer_id:
        q += " AND w.customer_id=?"
        args.append(customer_id)
    q += " ORDER BY w.wo_id"
    return con.execute(q, args).fetchall()
def next_asset_id(con) -> str:
    rows = con.execute("SELECT asset_id FROM assets").fetchall()
    nums = []
    for r in rows:
        s = r["asset_id"]
        if s and s.upper().startswith("A-"):
            try:
                nums.append(int(s.split("-", 1)[1]))
            except ValueError:
                pass
    return f"A-{max(nums, default=0) + 1:03d}"
def save_asset(con, data: dict, asset_id: str | None = None) -> str:
    unit = (data.get("unit_no") or "").strip()
    desc = (data.get("description") or "").strip()
    if not unit:
        raise ValueError("Unit number is required")
    if not desc:
        raise ValueError("Description is required")
    cat = data.get("category") or ""
    if cat and cat not in lookups(con, "category"):
        raise ValueError("Pick a category from the list")
    yard = data.get("yard") or ""
    if yard and yard not in lookups(con, "yard"):
        raise ValueError("Pick a yard from the list")
    cond = data.get("condition") or "Available"
    if cond not in lookups(con, "condition"):
        raise ValueError("Pick condition from the list")
    aid = asset_id or next_asset_id(con)
    def money(key):
        v = data.get(key)
        return float(v) if v not in (None, "") else 0.0
    row = (
        unit, cat, desc, data.get("serial_no") or "", yard,
        1 if data.get("uscg_ok") else 0, 1 if data.get("dnv_ok") else 0, 1 if data.get("abs_ok") else 0,
        # Single rate field: the legacy six columns are frozen history now.
        # Cert identity (Q5): the bare cert_expire column is legacy read-only —
        # cert records carry expiries now, so this field is never written here.
        clean_rate_unit(data.get("rate_unit")), money("rate_value"), money("meter_hours"),
        money("replacement_cost") or None,
        data.get("ownership") or "Owned", 0 if data.get("active") == "0" else 1,
        cond, data.get("notes") or "",
        1 if data.get("cert_operator") else 0, aid,
    )
    exists = con.execute("SELECT 1 FROM assets WHERE asset_id=?", (aid,)).fetchone()
    if exists:
        # refuse unit_no change collision
        other = con.execute(
            "SELECT asset_id FROM assets WHERE unit_no=? AND asset_id!=?", (unit, aid)
        ).fetchone()
        if other:
            raise ValueError(f"Unit number {unit} already on {other['asset_id']}")
        con.execute(
            """UPDATE assets SET unit_no=?, category=?, description=?, serial_no=?, yard=?,
               uscg_ok=?, dnv_ok=?, abs_ok=?, rate_unit=?, rate_value=?, meter_hours=?,
               replacement_cost=?,
               ownership=?, active=?, condition=?, notes=?, cert_operator=? WHERE asset_id=?""",
            row,
        )
    else:
        other = con.execute("SELECT asset_id FROM assets WHERE unit_no=?", (unit,)).fetchone()
        if other:
            raise ValueError(f"Unit number {unit} already on {other['asset_id']}")
        con.execute(
            """INSERT INTO assets (unit_no, category, description, serial_no, yard,
               uscg_ok, dnv_ok, abs_ok, rate_unit, rate_value, meter_hours,
               replacement_cost,
               ownership, active, condition, notes, cert_operator, asset_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            row,
        )
    con.commit()
    return aid
def next_site_id(con) -> str:
    rows = con.execute("SELECT site_id FROM sites").fetchall()
    nums = []
    for r in rows:
        s = r["site_id"]
        if s and s.upper().startswith("S-"):
            try:
                nums.append(int(s.split("-", 1)[1]))
            except ValueError:
                pass
    return f"S-{max(nums, default=0) + 1:03d}"
def save_site(con, data: dict, site_id: str | None = None) -> str:
    name = (data.get("site_name") or "").strip()
    if not name:
        raise ValueError("Site name is required")
    loc = data.get("loc_id") or ""
    if not loc:
        raise ValueError("Pick a tax location")
    j = con.execute("SELECT loc_id FROM jurisdictions WHERE loc_id=?", (loc,)).fetchone()
    if not j:
        raise ValueError("Unknown tax location")
    cust = data.get("customer_id") or None
    if cust:
        if not con.execute("SELECT 1 FROM customers WHERE customer_id=?", (cust,)).fetchone():
            raise ValueError("Unknown customer")
    regime = data.get("primary_regime") or ""
    if regime and regime not in lookups(con, "regime"):
        raise ValueError("Pick regime from the list")
    flag = data.get("flag_state") or ""
    if flag and flag not in lookups(con, "flag_state"):
        raise ValueError("Pick flag state from the list")
    waters = data.get("waters") or ""
    if waters and waters not in lookups(con, "waters"):
        raise ValueError("Pick waters / loc class from the list")
    sid = site_id or next_site_id(con)
    exempt = 1 if data.get("tax_exempt") else 0
    row = (
        name, data.get("street") or "", data.get("street2") or "", data.get("city") or "", data.get("state") or "", data.get("zip") or "",
        data.get("operator") or "", data.get("rig_name") or "",
        flag or None, waters or None, regime or None,
        cust, loc, exempt, data.get("notes") or "", sid,
    )
    exists = con.execute("SELECT 1 FROM sites WHERE site_id=?", (sid,)).fetchone()
    if exists:
        con.execute(
            """UPDATE sites SET site_name=?, street=?, street2=?, city=?, state=?, zip=?, operator=?, rig_name=?, flag_state=?, waters=?,
               primary_regime=?, customer_id=?, loc_id=?, tax_exempt=?, notes=? WHERE site_id=?""",
            row,
        )
    else:
        con.execute(
            """INSERT INTO sites (site_name, street, street2, city, state, zip, operator, rig_name, flag_state, waters,
               primary_regime, customer_id, loc_id, tax_exempt, notes, site_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            row,
        )
    con.commit()
    return sid
def report_availability(con: sqlite3.Connection) -> list[dict]:
    """One row per unit. Status is computed; never typed."""
    today = date.today().isoformat()
    out = []
    # Cert identity (Q5): operative expiry comes from the cert records.
    from engine_compliance import operative_cert_expiry
    assets = con.execute(
        """SELECT asset_id, unit_no, category, description, condition, active, yard
           FROM assets ORDER BY unit_no"""
    ).fetchall()
    for a in assets:
        live = con.execute(
            """SELECT ticket_id, status, on_rent, customer_id
               FROM tickets
               WHERE asset_id=? AND status IN ('Reserved','Dispatched','On Rent','Standby')
               ORDER BY on_rent DESC LIMIT 1""",
            (a["asset_id"],),
        ).fetchone()
        _exp = operative_cert_expiry(con, a["asset_id"])
        exp = _parse(_exp)
        cert_dead = bool(exp and exp < date.today())
        cond = a["condition"] or "Available"
        if not a["active"]:
            board = "Inactive"
        elif cert_dead:
            board = "Cert expired"
        elif cond.startswith("Repair") or cond == "Unusable":
            board = cond
        elif live:
            board = live["status"]
        else:
            board = "Available"
        out.append({
            "asset_id": a["asset_id"],
            "unit_no": a["unit_no"],
            "category": a["category"] or "",
            "description": a["description"] or "",
            "yard": a["yard"] or "",
            "board": board,
            "ticket_id": live["ticket_id"] if live else "",
            "customer_id": live["customer_id"] if live else "",
            "on_rent": live["on_rent"] if live else "",
            "cert_expire": _exp or "",
            "cert_dead": cert_dead,
            "rentable": board == "Available",
        })
    return out
def report_upcoming(con: sqlite3.Connection, days: int = 14) -> dict:
    today = date.today()
    horizon = today + timedelta(days=max(int(days), 1))
    # Cert identity (Q5): expiries come from cert records, legacy column as fallback.
    from engine_compliance import operative_cert_expiry
    certs = []
    for a in con.execute(
        "SELECT asset_id, unit_no, description FROM assets WHERE active=1 ORDER BY unit_no"
    ):
        exp = _parse(operative_cert_expiry(con, a["asset_id"]))
        if not exp:
            continue
        if exp <= horizon:
            certs.append({
                "asset_id": a["asset_id"],
                "unit_no": a["unit_no"],
                "description": a["description"] or "",
                "cert_expire": exp.isoformat(),
                "days": (exp - today).days,
                "dead": exp < today,
            })
    certs.sort(key=lambda c: c["cert_expire"])
    offs = []
    missing = []
    for t in con.execute(
        """SELECT t.ticket_id, t.asset_id, t.customer_id, t.status, t.on_rent, t.off_rent,
                  a.unit_no, c.account_name
           FROM tickets t
           JOIN assets a ON a.asset_id = t.asset_id
           JOIN customers c ON c.customer_id = t.customer_id
           WHERE t.status IN ('Reserved','Dispatched','On Rent','Standby','Off Rent')
           ORDER BY t.off_rent"""
    ):
        off = _parse(t["off_rent"])
        if not off:
            if t["status"] in ("On Rent", "Standby", "Dispatched"):
                missing.append({
                    "ticket_id": t["ticket_id"],
                    "unit_no": t["unit_no"],
                    "account_name": t["account_name"],
                    "status": t["status"],
                    "on_rent": t["on_rent"],
                })
            continue
        if off <= horizon:
            offs.append({
                "ticket_id": t["ticket_id"],
                "unit_no": t["unit_no"],
                "account_name": t["account_name"],
                "status": t["status"],
                "off_rent": off.isoformat(),
                "days": (off - today).days,
            })
    return {"days": days, "certs": certs, "offs": offs, "missing_off": missing}
def report_stays(con: sqlite3.Connection, start_s: str, end_s: str) -> dict:
    start = _parse(start_s) or (date.today() - timedelta(days=29))
    end = _parse(end_s) or date.today()
    if end < start:
        start, end = end, start
    rows = []
    for t in con.execute(
        """SELECT t.ticket_id, t.asset_id, t.customer_id, t.status, t.on_rent, t.off_rent,
                  a.unit_no, a.description, c.account_name, s.site_name
           FROM tickets t
           JOIN assets a ON a.asset_id = t.asset_id
           JOIN customers c ON c.customer_id = t.customer_id
           JOIN sites s ON s.site_id = t.site_id
           WHERE t.status != 'Void'
           ORDER BY a.unit_no, t.on_rent"""
    ):
        on = _parse(t["on_rent"])
        if not on:
            continue
        off = _parse(t["off_rent"]) or date.today()
        if off < on:
            off = on
        if off < start or on > end:
            continue
        overlap_start = max(on, start)
        overlap_end = min(off, end)
        days = (overlap_end - overlap_start).days + 1
        rows.append({
            "ticket_id": t["ticket_id"],
            "asset_id": t["asset_id"],
            "unit_no": t["unit_no"],
            "description": t["description"] or "",
            "account_name": t["account_name"],
            "site_name": t["site_name"],
            "status": t["status"],
            "on_rent": on.isoformat(),
            "off_rent": (t["off_rent"] or "")[:10] if t["off_rent"] else "open",
            "overlap_days": days,
        })
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "rows": rows,
        "n": len(rows),
        "units": len({r["asset_id"] for r in rows}),
    }
def report_maintenance(con: sqlite3.Connection) -> dict:
    shop = []
    certs = []
    today = date.today()
    # Cert identity (Q5): expiries come from cert records, legacy column as fallback.
    from engine_compliance import operative_cert_expiry
    for a in con.execute(
        """SELECT asset_id, unit_no, description, condition, active, yard
           FROM assets ORDER BY unit_no"""
    ):
        cond = a["condition"] or "Available"
        exp = _parse(operative_cert_expiry(con, a["asset_id"]))
        if cond != "Available" or not a["active"]:
            shop.append({
                "asset_id": a["asset_id"],
                "unit_no": a["unit_no"],
                "description": a["description"] or "",
                "condition": cond if a["active"] else "Inactive",
                "yard": a["yard"] or "",
                "cert_expire": exp.isoformat() if exp else "",
            })
        if exp and exp <= today + timedelta(days=30):
            certs.append({
                "asset_id": a["asset_id"],
                "unit_no": a["unit_no"],
                "description": a["description"] or "",
                "cert_expire": exp.isoformat(),
                "days": (exp - today).days,
                "dead": exp < today,
            })
    certs.sort(key=lambda c: c["cert_expire"])
    return {
        "shop": shop,
        "certs": sorted(certs, key=lambda x: x["days"]),
        "shop_n": len(shop),
        "cert_n": len(certs),
    }
def next_wo_id(con) -> str:
    n = _reserve_counter(con, "next_wo", 101)
    return f"WO-{n}"
def wo_cost(labor, parts, other) -> float:
    return round(float(labor or 0) + float(parts or 0) + float(other or 0), 2)
def save_wo(con, data: dict, wo_id: str | None = None) -> str:
    # Ensure new columns exist (Jason 2026-10-07 F8)
    wcols = [r[1] for r in con.execute("PRAGMA table_info(work_orders)")]
    for col, ddl in [("ref_ticket", "TEXT"), ("wo_date", "TEXT"), ("item", "TEXT"),
                     ("qty", "REAL DEFAULT 1"), ("cost", "REAL DEFAULT 0")]:
        if col not in wcols:
            con.execute(f"ALTER TABLE work_orders ADD COLUMN {col} {ddl}")
    aid = data.get("asset_id") or ""
    if not aid or not con.execute("SELECT 1 FROM assets WHERE asset_id=?", (aid,)).fetchone():
        raise ValueError("Pick a unit")
    desc = (data.get("description") or "").strip()
    if not desc:
        raise ValueError("Describe the work")
    wtype = data.get("work_type") or ""
    if wtype not in lookups(con, "wo_type"):
        raise ValueError("Pick a work type")
    charge = data.get("charge_to") or "internal"
    if charge not in ("internal", "customer"):
        raise ValueError("Charge to must be internal or customer")
    cust = data.get("customer_id") or None
    tid = data.get("ticket_id") or None
    if tid:
        t = con.execute("SELECT customer_id FROM tickets WHERE ticket_id=?", (tid,)).fetchone()
        if not t:
            raise ValueError("Unknown ticket")
        cust = cust or t["customer_id"]
    if charge == "customer" and not cust:
        raise ValueError("Billable work needs a customer")
    status = data.get("status") or "Open"
    if status not in lookups(con, "wo_status"):
        raise ValueError("Pick a status")
    if charge == "internal":
        bill = 0.0
    else:
        bill = _mf(data.get("bill_amount") or 0)
        if status == "Complete" and bill <= 0:
            raise ValueError("Completed customer work needs a positive bill amount")
    open_d = data.get("open_date") or date.today().isoformat()
    close_d = data.get("close_date") or None
    if status == "Complete" and not close_d:
        close_d = date.today().isoformat()
    if status in ("Open", "In progress"):
        close_d = close_d or None
    wid = wo_id or next_wo_id(con)
    prior = con.execute("SELECT * FROM work_orders WHERE wo_id=?", (wid,)).fetchone()
    if prior and prior["invoice_no"]:
        charge = prior["charge_to"]
        bill = float(prior["bill_amount"] or 0)
        cust = prior["customer_id"]
        status = prior["status"]
    row = (
        aid, tid, cust, charge, wtype, desc, data.get("vendor") or "",
        open_d, close_d,
        _mf(data.get("labor") or 0), _mf(data.get("parts") or 0),
        _mf(data.get("other_cost") or 0), bill, status,
        1 if data.get("warranty") else 0,
        data.get("yard_or_site") or "", data.get("notes") or "",
        data.get("ref_ticket") or "", data.get("wo_date") or "",
        data.get("item") or "", _mf(data.get("qty") or 1), _mf(data.get("cost") or 0),
        wid,
    )
    exists = con.execute("SELECT 1 FROM work_orders WHERE wo_id=?", (wid,)).fetchone()
    sql_u = """UPDATE work_orders SET asset_id=?, ticket_id=?, customer_id=?, charge_to=?,
               work_type=?, description=?, vendor=?, open_date=?, close_date=?,
               labor=?, parts=?, other_cost=?, bill_amount=?, status=?, warranty=?,
               yard_or_site=?, notes=?, ref_ticket=?, wo_date=?, item=?, qty=?, cost=?
               WHERE wo_id=?"""
    sql_i = """INSERT INTO work_orders (asset_id, ticket_id, customer_id, charge_to,
               work_type, description, vendor, open_date, close_date, labor, parts,
               other_cost, bill_amount, status, warranty, yard_or_site, notes,
               ref_ticket, wo_date, item, qty, cost, wo_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""
    con.execute(sql_u if exists else sql_i, row)
    if data.get("quote_no") and cust:
        _set_quote_link(con, "work_orders", "wo_id", wid, data["quote_no"], cust)
    con.commit()
    return wid
def report_work_orders(con, kind: str = "ytd") -> dict:
    start, end, label = period_bounds(kind)
    rows = []
    exp = inc = 0.0
    for w in con.execute(
        """SELECT w.*, a.unit_no, a.description AS asset_desc, c.account_name
           FROM work_orders w
           JOIN assets a ON a.asset_id = w.asset_id
           LEFT JOIN customers c ON c.customer_id = w.customer_id
           ORDER BY w.open_date DESC"""
    ):
        d = _parse(w["open_date"])
        if d and (d < start or d > end):
            continue
        if w["status"] == "Void":
            continue
        cost = wo_cost(w["labor"], w["parts"], w["other_cost"])
        bill = float(w["bill_amount"] or 0) if w["charge_to"] == "customer" and w["invoice_no"] else 0.0
        exp += cost
        inc += bill
        rows.append({
            "wo_id": w["wo_id"],
            "unit_no": w["unit_no"],
            "asset_id": w["asset_id"],
            "work_type": w["work_type"],
            "description": w["description"],
            "charge_to": w["charge_to"],
            "account_name": w["account_name"] or "Yard (internal)",
            "status": w["status"],
            "open_date": str(w["open_date"])[:10],
            "cost": cost,
            "bill": bill,
            "net": round(bill - cost, 2),
        })
    open_n = con.execute(
        "SELECT COUNT(*) FROM work_orders WHERE status IN ('Open','In progress')"
    ).fetchone()[0]
    return {
        "label": label, "start": start.isoformat(), "end": end.isoformat(),
        "rows": rows, "expense": round(exp, 2), "income": round(inc, 2),
        "net": round(inc - exp, 2), "open_n": open_n, "n": len(rows),
    }

def create_sale(con, asset_id, customer_id, sale_date, amount, notes="", clerk="", qty=1, condition="", sale_id=None, ref_no="", item_desc=""):
    """Record an outright equipment sale. Marks the asset as sold."""
    import datetime
    # Ensure new columns exist (Jason 2026-10-07)
    scols = [r[1] for r in con.execute("PRAGMA table_info(sales)")]
    if "ref_no" not in scols:
        con.execute("ALTER TABLE sales ADD COLUMN ref_no TEXT")
    if "item_desc" not in scols:
        con.execute("ALTER TABLE sales ADD COLUMN item_desc TEXT")
    if not sale_id:
        sale_id = f"S-{datetime.date.today().year}-{con.execute('SELECT COALESCE(MAX(CAST(SUBSTR(sale_id, 8) AS INTEGER)), 0) + 1 FROM sales WHERE sale_id LIKE ?', (f"S-{datetime.date.today().year}-%",)).fetchone()[0]}"
    con.execute(
        "INSERT INTO sales (sale_id, asset_id, customer_id, sale_date, qty, amount, condition, notes, clerk, ref_no, item_desc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (sale_id, asset_id, customer_id, sale_date, qty, amount, condition, notes, clerk, ref_no, item_desc)
    )
    # Mark asset as sold
    con.execute(
        "UPDATE assets SET sold_date=?, sold_amount=?, sold_to=?, active=0 WHERE asset_id=?",
        (sale_date, amount, customer_id, asset_id)
    )
    con.commit()
    return sale_id

def list_sales(con, limit=50):
    """Recent equipment sales, newest first."""
    rows = con.execute(
        """SELECT s.sale_id, s.sale_date, s.amount, s.notes,
                  a.unit_no, c.account_name
           FROM sales s
           JOIN assets a ON a.asset_id=s.asset_id
           LEFT JOIN customers c ON c.customer_id=s.customer_id
           ORDER BY s.sale_date DESC, s.sale_id DESC
           LIMIT ?""",
        (limit,)
    ).fetchall()
    return [dict(r) for r in rows]
