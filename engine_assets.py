"""All money and status rules live here. The UI never computes them."""
from __future__ import annotations
import sqlite3
from calendar import monthrange
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from pathlib import Path
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
    validate_new_doc_no,
    key_of,
    num_of,
    cust_key,
    cust_code,
    asset_key,
    asset_code,
    site_key,
    loc_key,
    loc_code,
    list_crew,
    add_crew,
    drop_crew,
    _reserve_counter,
    _next_doc,
    _set_quote_link,
    lookups,
    clean_line_type,
    clean_line_uom,
    period_bounds,
    _ensure_device_tables,
    get_option,
    set_option,
    module_on,
    COND_NOT_RECORDED,
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

__all__ = ['billable_days', 'applied_rate', 'rental_amount', 'compliance', 'fit_reason', 'possession_rules', 'ticket_money', 'ticket_lines', 'save_ticket_lines', 'sync_flat_charges_to_lines', 'FREIGHT_CATS', 'asset_status', 'next_ticket_id', 'create_ticket', 'SoftReserveConflict', 'update_ticket_transport', 'condition_worse', 'save_ticket_condition', 'save_ticket_photo', 'read_ticket_photo', 'set_status', 'ready_work_orders', 'next_asset_id', 'save_asset', 'next_site_id', 'save_site', 'report_availability', 'report_upcoming', 'report_stays', 'report_maintenance', 'next_wo_id', 'wo_cost', 'save_wo', 'wo_lines', 'report_work_orders', 'HAUL_BY', 'DELIVER_TO', 'HAUL_LABELS', 'DELIVER_LABELS', 'clean_haul_by', 'clean_deliver_to', 'haul_consequence', 'haul_from', 'RATE_UNITS', 'clean_rate_unit', 'ticket_hours',
 'day_equivalent', 'ASSET_STATUSES', 'clean_asset_status', 'rentable_or_raise',
 'create_sale', 'list_sales', 'next_sale_id', 'peek_next_sale_id']

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
    "we": "Company Transport",
    "customer": "Customer Transport",
    "third_party": "Third-party Transport",
}
# Label set retired 2026-10-23 (Jason: too informal, too complicated).
# Stored haul_by keys never changed; these texts are recognised on input
# only, so records and forms carrying the old words still resolve.
HAUL_LEGACY_LABELS = {
    "We deliver — our truck": "we",
    "Customer picks up — their truck": "customer",
    "Third-party truck": "third_party",
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


def resolve_haul_text(text) -> tuple:
    """Resolve operator-entered transport text to (haul_by, haul_note).

    The two presets and the storage keys resolve to their key with no
    note; the retired label set resolves the same way. Any other text is
    a third-party carrier name and is kept verbatim as the note."""
    t = (text or "").strip()
    if not t:
        return ("we", "")
    low = t.lower()
    for key in HAUL_BY:
        if low == key or low == HAUL_LABELS[key].lower():
            return (key, "")
    for label, key in HAUL_LEGACY_LABELS.items():
        if low == label.lower():
            return (key, "")
    return ("third_party", t)


def transport_display(haul_by, haul_note="") -> str:
    """The one transport wording shown on screens and print."""
    h = clean_haul_by(haul_by)
    if h == "customer":
        return HAUL_LABELS["customer"]
    if h == "third_party":
        return (haul_note or "").strip() or HAUL_LABELS["third_party"]
    return HAUL_LABELS["we"]

def haul_consequence(haul: str, dest: str) -> str:
    """Explain the operational consequence. Tax is the operator's call —
    the software states where possession transfers, never the tax situs."""
    if haul == "customer":
        return "Customer pickup at our yard."
    fee = ("Company transport — a transportation fee applies."
           if haul == "we" else
           "Third-party transport — no FleetSheet transportation fee unless entered.")
    return f"{fee} Possession transfers at the {DELIVER_LABELS.get(dest, dest).lower()}."


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
        # Display only: render MM/DD/YYYY like the central helpers
        # (fmt_date / _fmt_date); storage stays ISO. _parse comes from
        # engine_core — no views import in the engine layer.
        exp = _parse(cert_expire) if cert_expire else None
        return f"cert expired {exp.strftime('%m/%d/%Y')}" if exp else "cert expired"
    return {
        "FAIL-USCG": "Missing USCG stamp (site requires it)",
        "FAIL-DNV": "Missing DNV stamp (site requires it)",
        "FAIL-ABS": "Missing ABS stamp (site requires it)",
    }.get(fit_code or "", "Paper does not meet job requirements")
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
    # Build 'v': the row carries the jurisdiction's engine key; the
    # display code is what tax lines and labels carry.
    _tl = _row_get(t, "tax_loc_id")
    explicit_loc = (_tl.strip() if isinstance(_tl, str)
                    else (loc_code(con, _tl) or ""))
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
        "haul_note": (_row_get(t, "haul_note") or "").strip(),
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

# Ticket charges as line items (Jason, 2026-10-23): every charge on a
# ticket is a line on the invoice template — Type | Item | Description |
# Qty | Unit | Rate, plus a per-line Tax flag. The rental itself, with
# the waiver and environmental percentages, is computed from the
# ticket's rate and dates; every other charge is a stored ticket_lines
# row. Tax is computed per line: the jurisdiction supplies only the
# rate, and a line is taxed only when its own flag is set. Freight
# lines default to untaxed (Jason's freight ruling).
FREIGHT_CATS = ("Freight", "Mobilization", "Demobilization")


def _ensure_ticket_lines_table(con: sqlite3.Connection) -> None:
    """ticket_lines owns a ticket's charge lines (2026-10-23). Fresh
    DBs get it from schema.sql; this migrates existing DBs."""
    con.execute("""CREATE TABLE IF NOT EXISTS ticket_lines (
        line_id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_id INTEGER NOT NULL REFERENCES tickets(id),
        category TEXT NOT NULL DEFAULT 'Other',
        item TEXT DEFAULT '',
        description TEXT NOT NULL DEFAULT '',
        qty REAL NOT NULL DEFAULT 1,
        uom TEXT NOT NULL DEFAULT 'Each',
        rate REAL NOT NULL DEFAULT 0,
        amount REAL NOT NULL DEFAULT 0,
        taxed INTEGER NOT NULL DEFAULT 1
    )""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_ticket_lines_ticket ON ticket_lines(ticket_id)")
    _tlcols = [r[1] for r in con.execute("PRAGMA table_info(ticket_lines)")]
    if "line_note" not in _tlcols:
        con.execute("ALTER TABLE ticket_lines ADD COLUMN line_note TEXT")


def _flat_charge_lines(t) -> list[dict]:
    """A ticket row's legacy flat charge fields as line dicts — the
    migration shape. Transport money (mob / demob / transportation fee)
    becomes freight lines with taxed=False (Jason's freight ruling);
    fuel, parts, and other charges sat inside the old whole-subtotal
    tax base, so their lines carry taxed=True: totals do not move
    except for the intended freight effect."""
    def g(k):
        try:
            return float(_row_get(t, k, 0) or 0)
        except (TypeError, ValueError):
            return 0.0
    out = []
    for key, cat, desc, taxed in (
        ("mob", "Mobilization", "Mobilization", 0),
        ("demob", "Demobilization", "Demobilization", 0),
        ("transport_fee", "Freight", "Transportation", 0),
        ("fuel", "Fuel", "Fuel", 1),
        ("parts", "Item", "Parts", 1),
        ("other_amt", "Other", "Other charges", 1),
    ):
        amt = g(key)
        if amt:
            out.append({"category": cat, "item": "", "description": desc,
                        "qty": 1.0, "uom": "Each", "rate": amt,
                        "amount": round(amt, 2), "taxed": bool(taxed)})
    return out


def _ticket_ref(con, ticket_id):
    """The value ticket_lines.ticket_id holds for a ticket: its engine
    key on a re-keyed book, its number on a pre-'v' book (the legacy
    migration steps call the line sync before the re-key runs)."""
    if "id" in [r[1] for r in con.execute("PRAGMA table_info(tickets)")]:
        return key_of(con, "tickets", ticket_id)
    return ticket_id


def _insert_ticket_line(con: sqlite3.Connection, ticket_key, ln: dict) -> None:
    qty = float(ln.get("qty") or 0)
    rate = float(ln.get("rate") or 0)
    amt = ln.get("amount")
    amt = round(qty * rate, 2) if amt is None else round(float(amt), 2)
    con.execute(
        "INSERT INTO ticket_lines(ticket_id,category,item,description,qty,uom,rate,amount,taxed)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (ticket_key, clean_line_type(con, ln.get("category")),
         (ln.get("item") or "").strip(), (ln.get("description") or "").strip(),
         qty, clean_line_uom(con, ln.get("uom")), rate, amt,
         1 if ln.get("taxed", True) else 0))


def sync_flat_charges_to_lines(con: sqlite3.Connection, ticket_id: str) -> int:
    """Move a ticket's legacy flat charges into ticket_lines, once.
    Idempotent: a ticket that already has lines is left alone. The
    flat columns are zeroed so no reader can count a charge twice.
    Returns the number of lines written. Does not commit."""
    _ensure_ticket_lines_table(con)
    tkey = _ticket_ref(con, ticket_id)
    if con.execute("SELECT 1 FROM ticket_lines WHERE ticket_id=? LIMIT 1",
                   (tkey,)).fetchone():
        return 0
    t = con.execute("SELECT * FROM tickets WHERE ticket_id=?", (ticket_id,)).fetchone()
    if not t:
        return 0
    lines = _flat_charge_lines(t)
    for ln in lines:
        _insert_ticket_line(con, tkey, ln)
    if lines:
        con.execute("UPDATE tickets SET mob=0, demob=0, transport_fee=0,"
                    " fuel=0, parts=0, other_amt=0 WHERE ticket_id=?",
                    (ticket_id,))
    return len(lines)


def ticket_lines(con: sqlite3.Connection, ticket_id: str) -> list[dict]:
    """Stored charge lines for one ticket, in entry order."""
    _ensure_ticket_lines_table(con)
    out = []
    for r in con.execute("SELECT * FROM ticket_lines WHERE ticket_id=? ORDER BY line_id",
                         (_ticket_ref(con, ticket_id),)).fetchall():
        out.append({"line_id": r["line_id"], "category": r["category"],
                    "item": r["item"] or "", "description": r["description"] or "",
                    "qty": float(r["qty"] or 0), "uom": r["uom"] or "Each",
                    "rate": float(r["rate"] or 0), "amount": float(r["amount"] or 0),
                    "taxed": bool(r["taxed"]),
                    "note": _row_get(r, "line_note", "") or ""})
    return out


def save_ticket_lines(con: sqlite3.Connection, ticket_id: str, lines: list) -> None:
    """Replace a ticket's stored charge lines (the ticket form's line
    grid, saved with the ticket's Save). Locked once the ticket is
    billed, like transport."""
    t = con.execute("SELECT status, invoice_id FROM tickets WHERE ticket_id=?",
                    (ticket_id,)).fetchone()
    if not t:
        raise ValueError("Unknown rental ticket")
    if t["status"] in ("Billed", "Closed", "Void") or t["invoice_id"]:
        raise ValueError("Charges are locked after invoicing")
    _ensure_ticket_lines_table(con)
    tkey = _ticket_ref(con, ticket_id)
    con.execute("DELETE FROM ticket_lines WHERE ticket_id=?", (tkey,))
    for ln in lines:
        if not (ln.get("item") or "").strip() \
                and not (ln.get("description") or "").strip() \
                and not float(ln.get("rate") or 0):
            continue  # untouched form row — the invoice editor's rule
        _insert_ticket_line(con, tkey, ln)
    con.commit()


def ticket_money(con: sqlite3.Connection, ticket_id: str) -> dict:
    # A ticket may carry no job site (Jason 2026-10-24): the site join is
    # a LEFT JOIN so a site-less ticket's money computes in full — its
    # site-derived fields stand empty, and tax still comes only from the
    # ticket's own explicit jurisdiction (possession_rules).
    t = con.execute(
        """
        SELECT t.*, a.*, a.asset_id AS asset_code, s.loc_id AS site_loc_key, s.site_name,
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
        JOIN assets a ON a.id = t.asset_id
        LEFT JOIN sites s ON s.id = t.site_id
        LEFT JOIN jurisdictions j ON j.id = s.loc_id
        JOIN customers c ON c.id = t.customer_id
        JOIN company co ON co.id = 1
        LEFT JOIN jurisdictions yj ON yj.id = co.yard_loc_id
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
    waiver = rental * float(t["waiver_pct"]) if t["waiver_yn"] else 0.0
    env = rental * float(t["env_pct"])
    rental_sub = rental + waiver + env
    pos = possession_rules(con, t)
    # Line items (2026-10-23): the computed rental lines first, then
    # the ticket's stored charge lines. A book whose flat charges have
    # not been migrated yet falls back to those fields read as lines,
    # so no charge is ever dropped from a total.
    stored = ticket_lines(con, ticket_id)
    if not stored:
        stored = _flat_charge_lines(t)
    _unit_word = {"Day": "Days", "Week": "Weeks", "Monthly": "Months",
                  "Hour": "Hours"}.get(
                      _LEGACY_RATE_UNIT.get(t["rate_type"] or "", t["rate_type"] or ""),
                      "Each")
    lines = []
    if rental:
        lines.append({"category": "Rental", "item": t["unit_no"],
                      "description": (t["description"] or "").strip(),
                      "qty": hours if _unit_word == "Hours" else days,
                      "uom": _unit_word, "rate": round(rate, 2),
                      "amount": round(rental, 2), "taxed": True,
                      "computed": True})
    if waiver:
        lines.append({"category": "Rental", "item": "",
                      "description": "Damage waiver", "qty": 1,
                      "uom": "Each", "rate": round(waiver, 2),
                      "amount": round(waiver, 2), "taxed": True,
                      "computed": True})
    if env:
        lines.append({"category": "Other", "item": "",
                      "description": "Environmental fee", "qty": 1,
                      "uom": "Each", "rate": round(env, 2),
                      "amount": round(env, 2), "taxed": True,
                      "computed": True})
    lines.extend(stored)
    transport = sum(ln["amount"] for ln in stored if ln["category"] in FREIGHT_CATS)
    other = sum(ln["amount"] for ln in stored if ln["category"] not in FREIGHT_CATS)
    sub = rental_sub + transport + other
    # Per-line tax base: only lines carrying their own Tax flag.
    tax_base = rental_sub + sum(ln["amount"] for ln in stored if ln["taxed"])
    tax = 0.0 if pos["tax_exempt"] else tax_base * pos["tax_rate"]
    _mob = sum(ln["amount"] for ln in stored if ln["description"] == "Mobilization")
    _demob = sum(ln["amount"] for ln in stored if ln["description"] == "Demobilization")
    _tfee = sum(ln["amount"] for ln in stored if ln["category"] == "Freight")
    # Cert identity (Q5): fit reads the operative cert-record expiry, not the
    # bare legacy column. Lazy import: engine_compliance must not be a
    # module-level import here (engine.py import order).
    from engine_compliance import operative_cert_expiry
    cert_expiry = operative_cert_expiry(con, t["asset_code"])
    return {
        "days": days,
        "hours": round(hours, 2),
        "rate": rate,
        "rental": round(rental, 2),
        "transport": round(transport, 2),
        "mob": round(_mob, 2),
        "demob": round(_demob, 2),
        "transport_fee": round(_tfee, 2),
        "other": round(other, 2),
        "lines": lines,
        "tax_base": round(tax_base, 2),
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
        (asset_key(con, asset_id),),
    ).fetchone()
    if row:
        return row["status"]
    sold = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sales'"
    ).fetchone()
    return "Available"
def next_ticket_id(con: sqlite3.Connection) -> str:
    # Skip numbers already in use, like every other generator: a ticket
    # created ahead of the counter (say T-1050) must never be reissued.
    while True:
        n = _reserve_counter(con, "next_ticket", 1001)
        tid = f"T-{n}"
        if not con.execute("SELECT 1 FROM tickets WHERE ticket_id=?",
                           (tid,)).fetchone():
            return tid


class SoftReserveConflict(Exception):
    """A new ticket overlaps a PO soft-reservation. The app never auto-blocks
    here — it names the stakes and lets the operator pick which reservation
    wins. Carries the blocking ticket's row in `.ticket`."""
    def __init__(self, ticket_row):
        self.ticket = ticket_row
        super().__init__(f"Unit soft-reserved on rental ticket {ticket_row['ticket_id']}")


def create_ticket(con: sqlite3.Connection, data: dict) -> str:
    aid = data["asset_id"]
    # Engine class foundation (Phase 5, Jason 2026-10-24): a rental
    # ticket is the rental motion itself, so the class + lifecycle
    # guard stands here — a crafted post or a direct caller gets the
    # same refusal the picker implies by not offering the unit.
    rentable_or_raise(con, aid)
    akey = asset_key(con, aid)
    busy = con.execute(
        """SELECT ticket_id, customer_id, job_name, well_or_pad, po, on_rent, off_rent,
                  COALESCE(soft_reserve,0) AS soft_reserve
           FROM tickets
           WHERE asset_id=? AND status IN ('Reserved','Dispatched','On Rent','Standby')""",
        (akey,),
    ).fetchone()
    if busy:
        if busy["soft_reserve"]:
            # PO soft-reserve: flag it, don't block it. The web layer names
            # the stakes and the operator chooses.
            raise SoftReserveConflict(busy)
        raise ValueError(f"Unit already on rental ticket {busy['ticket_id']} ({'open'})")
    # B1: tickets enter the workflow at the start — Quoted or Reserved only.
    # Creating one directly as Billed / On Rent / Dispatched skips check-out,
    # FIT, and invoicing gates.
    status = (data.get("status") or "Quoted").strip()
    if status not in ("Quoted", "Reserved"):
        raise ValueError(f"New rental tickets start as Quoted or Reserved, not {status}")
    # B8: never store garbage dates.
    on_rent = parse_date(data.get("on_rent"), "On-rent date")
    off_rent = parse_date(data.get("off_rent"), "Off-rent date", required=False)
    _custom_tid = (data.get("ticket_id") or "").strip()
    tid = (validate_new_doc_no(con, "tickets", "ticket_id", _custom_tid, "rental ticket")
           if _custom_tid else next_ticket_id(con))
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
            tid, cust_key(con, data["customer_id"]),
            site_key(con, data["site_id"]) if (data.get("site_id") or "") else None,
            akey,
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
            haul, dest, loc_key(con, tax_loc_id),
            1 if data.get("waiver_yn", True) else 0,
            status, soft,
            data.get("location_note") or "",
            data.get("haul_note") or "",
            data.get("deliver_note") or "",
        ),
    )
    # Charges (2026-10-23): lines posted with the ticket win; otherwise
    # the legacy flat charge fields the caller supplied become lines.
    _posted_lines = data.get("lines")
    if _posted_lines:
        _ensure_ticket_lines_table(con)
        tkey = key_of(con, "tickets", tid)
        for _ln in _posted_lines:
            if not (_ln.get("item") or "").strip() \
                    and not (_ln.get("description") or "").strip() \
                    and not float(_ln.get("rate") or 0):
                continue
            _insert_ticket_line(con, tkey, _ln)
    else:
        sync_flat_charges_to_lines(con, tid)
    if (data.get("quote_no") or "").strip():
        _set_quote_link(con, "tickets", "ticket_id", tid, data["quote_no"].strip(), data["customer_id"])
    con.commit()
    return tid
def update_ticket_transport(con: sqlite3.Connection, ticket_id: str, data: dict) -> None:
    t = con.execute("SELECT status, invoice_id, haul_note FROM tickets WHERE ticket_id=?", (ticket_id,)).fetchone()
    if not t:
        raise ValueError("Unknown rental ticket")
    if t["status"] in ("Billed", "Closed", "Void") or t["invoice_id"]:
        raise ValueError("Transport / possession is locked after invoicing")
    haul = haul_from(data)
    dest = clean_deliver_to(data.get("deliver_to"))
    tax_loc_id = clean_tax_loc_id(data.get("tax_loc_id"))
    if tax_loc_id and not con.execute("SELECT 1 FROM jurisdictions WHERE loc_id=?", (tax_loc_id,)).fetchone():
        raise ValueError("Selected tax jurisdiction does not exist")
    haul_note = data["haul_note"] if "haul_note" in data else (t["haul_note"] or "")
    # Charge amounts are ticket_lines now (2026-10-23), edited through
    # save_ticket_lines; the legacy fee keys are no longer read here.
    con.execute(
        """UPDATE tickets SET customer_transport=?, haul_by=?, haul_note=?, deliver_to=?, tax_loc_id=?
           WHERE ticket_id=?""",
        (
            0 if haul == "we" else 1,
            haul, haul_note, dest, loc_key(con, tax_loc_id),
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
        raise ValueError("Unknown rental ticket")
    if t["status"] in ("Billed", "Closed", "Void") or t["invoice_id"]:
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
                "SELECT meter_hours FROM assets WHERE id=?",
                (t["asset_id"],)).fetchone()
            cur = float(cur[0] or 0) if cur else 0.0
            if hrs > cur:
                con.execute("UPDATE assets SET meter_hours=? WHERE id=?",
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
def set_status(con: sqlite3.Connection, ticket_id: str, new: str, off_rent: str | None = None, clerk: str | None = None,
               skip_condition: bool = False, audit_bypass: bool = False,
               override_fit: bool = False, jump_note: str | None = None) -> None:
    t = con.execute("SELECT * FROM tickets WHERE ticket_id=?", (ticket_id,)).fetchone()
    if not t:
        raise ValueError("Unknown rental ticket")
    # Noted passage (Jason, 2026-10-21): what is in the flow stays in the
    # flow but is over-ridable WITH A NOTE. jump_note is that deliberate
    # passage: it may leave the ALLOWED_NEXT steps and may reach Billed
    # with no invoice behind it, and it composes the condition/FIT gates
    # the way a Proceed-anyway move does — the stamps still land on the
    # ticket, and ONE Done entry records the whole act (clerk, time,
    # from -> to, note, and which gates it stepped past). Without a note
    # there is no passage: the normal refusals below stand untouched.
    jump = jump_note is not None
    note = (jump_note or "").strip()[:150]
    if jump:
        if not note:
            raise ValueError("A note is required to move outside the usual steps")
        if new == t["status"]:
            raise ValueError(f"{ticket_id} is already {new}")
        if new not in ("Quoted", "Reserved", "Dispatched", "On Rent",
                       "Standby", "Off Rent", "Ready to Bill", "Billed",
                       "Closed", "Void"):
            raise ValueError(f"Unknown status {new}")
    if not jump and new not in ALLOWED_NEXT.get(t["status"], ()):
        # Billing OFF (shop flow, Jason 2026-10-21): no invoice will ever
        # exist in this shop, so the chain's Billed step is not a gate —
        # a returned ticket finishes by closing. Closed joins the normal
        # next steps from Off Rent / Ready to Bill, with no invoice and
        # no note required (the charity must not have to confess on every
        # ticket; Move-with-note still exists for odder jumps). Billing
        # ON: this exception never fires and the chain is as before.
        if not (new == "Closed"
                and t["status"] in ("Off Rent", "Ready to Bill")
                and not module_on(con, "billing")):
            raise ValueError(f"Cannot move {t['status']} → {new}")
    who = require_clerk(clerk)
    # Engine class foundation (Phase 5, Jason 2026-10-24): a ticket
    # moves INTO the rental — Reserved, Dispatched, On Rent — only on
    # a rentable asset (right class, Active status). Tickets are
    # created on rentable assets and class/status cannot change while
    # a ticket is live, so in practice this refuses only states a book
    # reached around the form (an asset reclassed behind a Quoted
    # ticket, a pre-guard book). Check-in and every later step are
    # never refused on class: a unit coming home always comes home.
    # A noted jump passage composes this gate like the condition/FIT
    # gates — it steps past deliberately and the passage record names
    # it (class_fact below).
    class_fact = ""
    if new in ("Reserved", "Dispatched", "On Rent"):
        _a = _asset_row(con, asset_code(con, t["asset_id"]))
        if _a and (_a["designation"] in RENT_BLOCK_CLASSES
                   or _a["status"] != "Active"):
            _bad = (_a["designation"]
                    if _a["designation"] in RENT_BLOCK_CLASSES
                    else _a["status"])
            if not jump:
                raise ValueError(f"Unit {_a['unit_no']} is {_bad} — not rentable")
            class_fact = f"unit is {_bad}, not rentable"
    # B8: validate the off-rent date instead of storing it verbatim.
    if off_rent:
        off_rent = parse_date(off_rent, "Off-rent date", required=False)
    if new in ("Off Rent", "Ready to Bill") and not (off_rent or t["off_rent"]):
        off_rent = date.today().isoformat()
    if new == "Billed" and not t["invoice_id"] and not jump:
        raise ValueError("Assign an invoice before Billed")
    # Condition gates (shop-flow ruling, Jason 2026-10-21): no
    # un-overridable blocks anywhere — every refusal here has a
    # deliberate, audit-logged override. The PRESENCE checks may be
    # bypassed — skip_condition is set by the caller when the condition
    # switch is off, or when the operator explicitly chose "Proceed
    # anyway" (audit_bypass then puts the choice in the done log). A
    # bypassed gate writes COND_NOT_RECORDED into the condition field,
    # so the ticket shows the decision, never a silent blank. The FIT
    # check refuses dispatch on a recorded non-PASS result in BOTH
    # condition-switch modes (the switch governs condition records
    # only); it opens solely through override_fit — a deliberate
    # Proceed-anyway that stamps the override onto the ticket itself
    # (fit_override: value, clerk, when) and into the done log with the
    # FIT value. Never a silent pass.
    bypassed = []  # (field, side word) for gates this call steps past
    fit_overridden = ""  # the FIT value this call dispatches despite
    if new in ("Dispatched", "On Rent"):
        out_c = t["out_condition"] if "out_condition" in t.keys() else None
        if not out_c:
            if not skip_condition and not jump:
                raise ValueError("Record check-out condition before dispatch / on rent")
            bypassed.append(("out_condition", "check-out"))
        money = ticket_money(con, ticket_id)
        if money.get("fit") and money["fit"] != "PASS":
            if not override_fit and not jump:
                raise ValueError(f"FIT is {money['fit']} — do not dispatch")
            fit_overridden = money["fit"]
    if new in ("Off Rent", "Ready to Bill"):
        in_c = t["in_condition"] if "in_condition" in t.keys() else None
        if not in_c:
            if not skip_condition and not jump:
                raise ValueError("Record check-in condition before off rent")
            bypassed.append(("in_condition", "check-in"))
    con.execute(
        "UPDATE tickets SET status=?, off_rent=COALESCE(?, off_rent), clerk=? WHERE ticket_id=?",
        (new, off_rent, who, ticket_id),
    )
    for field, _side in bypassed:
        con.execute(
            f"UPDATE tickets SET {field}=? WHERE ticket_id=? AND ({field} IS NULL OR {field}='')",
            (COND_NOT_RECORDED, ticket_id),
        )
    if fit_overridden and "fit_override" in t.keys():
        stamp = (f"{fit_overridden} · by {who} · "
                 f"{datetime.now().strftime('%Y-%m-%d %H:%M')}")
        con.execute("UPDATE tickets SET fit_override=? WHERE ticket_id=?",
                    (stamp, ticket_id))
    billed_out_of_flow = bool(jump and new == "Billed" and not t["invoice_id"])
    if billed_out_of_flow and "billed_note" in t.keys():
        # Marked out of flow on the ticket itself: billed with no invoice
        # behind it (the customer's own portal, say) — note, who, when,
        # shown on the ticket page wherever its status shows.
        stamp = (f"{note} · by {who} · "
                 f"{datetime.now().strftime('%Y-%m-%d %H:%M')}")
        con.execute("UPDATE tickets SET billed_note=? WHERE ticket_id=?",
                    (stamp, ticket_id))
    con.commit()
    if jump:
        from engine_today import add_done_manual
        facts = [f"without a {side} condition (not recorded)"
                 for _field, side in bypassed]
        if class_fact:
            facts.append(class_fact)
        if fit_overridden:
            facts.append(f"FIT {fit_overridden} overridden")
        if billed_out_of_flow:
            facts.append("billed without an invoice")
        text = f"{ticket_id}: {t['status']} → {new} — moved with note: {note}"
        if facts:
            text += " · " + " · ".join(facts)
        add_done_manual(con, text, f"/ticket/{ticket_id}", who)
    elif (bypassed and audit_bypass) or fit_overridden:
        from engine_today import add_done_manual
        if bypassed and audit_bypass:
            for _field, side in bypassed:
                add_done_manual(
                    con,
                    f"{new} {ticket_id} without a {side} condition (proceeded anyway)",
                    f"/ticket/{ticket_id}", who)
        if fit_overridden:
            add_done_manual(
                con,
                f"Dispatched {ticket_id} — FIT {fit_overridden} overridden (proceeded anyway)",
                f"/ticket/{ticket_id}", who)
def ready_work_orders(con, customer_id: str | None = None):
    q = """SELECT w.wo_id, c.customer_id, w.bill_amount, w.description, w.work_type,
                  a.unit_no, c.account_name
           FROM work_orders w
           JOIN assets a ON a.id = w.asset_id
           JOIN customers c ON c.id = w.customer_id
           WHERE w.charge_to='customer' AND w.status='Complete'
             AND w.bill_amount > 0
             AND w.invoice_id IS NULL
        """
    args = []
    if customer_id:
        q += " AND w.customer_id=?"
        args.append(cust_key(con, customer_id))
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
def _ensure_designation(con) -> None:
    """Lazy ensure for assets.designation (Batch 3, Oct 23) — same
    shape as the connect-time migration, so direct engine callers on
    an un-migrated book don't fail the save."""
    cols = [r[1] for r in con.execute("PRAGMA table_info(assets)")]
    if cols and "designation" not in cols:
        con.execute("ALTER TABLE assets ADD COLUMN designation TEXT NOT NULL DEFAULT 'Fleet'")
        con.execute("UPDATE assets SET designation = 'Fleet' "
                    "WHERE designation IS NULL OR designation = ''")


# Asset lifecycle (Phase 5, Oct 24): every asset stands Active until
# the operator moves it. Retired keeps the asset on the books and in
# history, out of every draw. De-listed takes it off the working
# lists as well; it stays in the all-assets view and in history, and
# either state returns to Active on the same switch. Nothing is ever
# deleted. The lifecycle is a closed set — the operator picks, the
# app never derives it.
ASSET_STATUSES = ("Active", "Retired", "De-listed")

# Classes the rental motion may never draw: Stock is held for sale,
# Plant for the business itself. The operator's own designations draw
# as they always have — the classes strand nothing already recorded.
RENT_BLOCK_CLASSES = ("Plant", "Stock")


def clean_asset_status(v) -> str:
    s = (v or "Active").strip() or "Active"
    if s not in ASSET_STATUSES:
        raise ValueError("Pick a status: Active, Retired, or De-listed")
    return s


def _ensure_asset_status(con) -> None:
    """Lazy ensure for assets.status (Phase 5, Oct 24) — same shape
    as _ensure_designation."""
    cols = [r[1] for r in con.execute("PRAGMA table_info(assets)")]
    if cols and "status" not in cols:
        con.execute("ALTER TABLE assets ADD COLUMN status TEXT NOT NULL DEFAULT 'Active'")
        con.execute("UPDATE assets SET status = 'Active' "
                    "WHERE status IS NULL OR status = ''")


def _asset_row(con, asset_id):
    """The asset's class + lifecycle for the engine guards, or None."""
    _ensure_designation(con)
    _ensure_asset_status(con)
    return con.execute(
        "SELECT asset_id, unit_no, COALESCE(designation,'Fleet') AS designation, "
        "COALESCE(status,'Active') AS status FROM assets WHERE asset_id=?",
        (asset_id,)).fetchone()


def rentable_or_raise(con, asset_id, use="rent"):
    """The engine foundation under the class system (Jason,
    2026-10-24): the rental motion — and the quote, which proposes
    it — draws the rentable classes in Active status only. The
    pickers offer exactly this; the engine refuses the rest no
    matter what a caller posts, with the reason stated."""
    _code = asset_code(con, asset_id) or asset_id
    a = _asset_row(con, _code)
    if not a:
        raise ValueError(f"Unknown unit {_code}")
    bad = None
    if a["designation"] in RENT_BLOCK_CLASSES:
        bad = a["designation"]
    elif a["status"] != "Active":
        bad = a["status"]
    if bad is not None:
        if use == "quote":
            raise ValueError(f"Unit {a['unit_no']} is {bad} — not offered on a quote")
        raise ValueError(f"Unit {a['unit_no']} is {bad} — not rentable")
    return a


def save_asset(con, data: dict, asset_id: str | None = None) -> str:
    _ensure_designation(con)
    _ensure_asset_status(con)
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
    # Global dropdown rule (Issue 4): any non-empty condition is kept as-is
    # — typed-over Other values save on the unit. Empty still defaults.
    # "__add__" is a UI sentinel, never a stored value.
    cond = (data.get("condition") or "Available").strip() or "Available"
    if cond == "__add__":
        cond = "Available"
    # Designation (Batch 3, Oct 23): same rule as condition — presets
    # Fleet / Stock / Plant, typed-over values save on the unit, empty
    # and the "__add__" sentinel default to 'Fleet'. Phase 5: a save
    # that does not carry the field at all (a direct engine caller
    # editing other facts) leaves the class as it stands — the class
    # changes only when a caller actually states one.
    _old = None
    if asset_id:
        _old = con.execute(
            "SELECT unit_no, designation, status FROM assets WHERE asset_id=?",
            (asset_id,)).fetchone()
    if data.get("designation") is not None:
        desig = (data.get("designation") or "Fleet").strip() or "Fleet"
        if desig == "__add__":
            desig = "Fleet"
    elif _old:
        desig = _old["designation"] or "Fleet"
    else:
        desig = "Fleet"
    # Lifecycle status (Phase 5, Oct 24): the same preserve rule.
    if data.get("status") is not None:
        status = clean_asset_status(data.get("status"))
    elif _old:
        status = _old["status"] or "Active"
    else:
        status = "Active"
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
        1 if data.get("cert_operator") else 0, desig, status, aid,
    )
    exists = con.execute("SELECT 1 FROM assets WHERE asset_id=?", (aid,)).fetchone()
    _class_change = bool(_old) and desig != (_old["designation"] or "Fleet")
    _status_change = bool(_old) and status != (_old["status"] or "Active")
    _live_ticket = None
    _switch_note = ""
    if _class_change or _status_change:
        # Entanglement (Phase 5, Jason 2026-10-24): while the unit is
        # out on a live ticket — Reserved / Dispatched / On Rent /
        # Standby, the same set the form locks the unit number
        # against — a class or status switch was refused outright.
        # Build 'o' (Jason 2026-10-24, ruling on the Phase 5 flag):
        # "The while-out switch is okay, but inconsistent. let them
        # switch it with a note." The switch is now a noted passage,
        # composed like the condition/FIT jumps in set_status: it
        # proceeds when the operator supplies a note, refuses only
        # when no note is given, and the note and the live ticket
        # stand in the Done record below. A Quoted ticket does not
        # hold the switch (a proposal, not possession — and its
        # conversion draws through the engine guard at that time), and
        # neither does an open work order (service is recorded against
        # the unit in any class).
        live = con.execute(
            "SELECT ticket_id FROM tickets WHERE asset_id=? "
            "AND status IN ('Reserved','Dispatched','On Rent','Standby')",
            (asset_key(con, aid),)).fetchone()
        if live:
            _switch_note = (data.get("switch_note") or "").strip()[:150]
            if not _switch_note:
                raise ValueError(
                    f"{_old['unit_no']} is out on rental ticket {live['ticket_id']} — "
                    "a note is required to switch a unit that is out")
            _live_ticket = live["ticket_id"]
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
               ownership=?, active=?, condition=?, notes=?, cert_operator=?, designation=?, status=? WHERE asset_id=?""",
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
               ownership, active, condition, notes, cert_operator, designation, status, asset_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            row,
        )
    con.commit()
    if _class_change or _status_change:
        # The switches are audited events (Phase 5): who made the
        # change, when, and from what to what stand in the Done
        # record — the app's audit of record — beside the FIT
        # overrides and noted passages recorded the same way.
        from engine_today import add_done_manual
        _who = (data.get("clerk") or "").strip()[:40]
        _passage = (f" — switched while out on Rental Ticket {_live_ticket} "
                    f"with note: {_switch_note}") if _live_ticket else ""
        if _class_change:
            add_done_manual(
                con,
                f"Asset {unit}: class {_old['designation'] or 'Fleet'} → {desig}"
                + _passage,
                f"/unit/{aid}", _who)
        if _status_change:
            add_done_manual(
                con,
                f"Asset {unit}: status {_old['status'] or 'Active'} → {status}"
                + _passage,
                f"/unit/{aid}", _who)
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
    loc = (data.get("loc_id") or "").strip()
    # Tax location is optional at site creation (form says so; Jason's tax
    # rule: blank = no tax, operator's call). Validate only when given.
    if loc:
        j = con.execute("SELECT loc_id FROM jurisdictions WHERE loc_id=?", (loc,)).fetchone()
        if not j:
            raise ValueError("Unknown tax location")
    else:
        loc = None
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
        cust_key(con, cust) if cust else None,
        loc_key(con, loc) if loc else None,
        exempt, data.get("notes") or "", sid,
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
        """SELECT id, asset_id, unit_no, category, description, condition, active, yard,
                  COALESCE(status,'Active') AS status
           FROM assets ORDER BY unit_no"""
    ).fetchall()
    for a in assets:
        # Lifecycle (Phase 5, Oct 24): Retired and De-listed units
        # leave the availability board entirely — they stand in the
        # history reports and the all-assets view, not here.
        if a["status"] != "Active":
            continue
        live = con.execute(
            """SELECT ticket_id, status, on_rent, customer_id
               FROM tickets
               WHERE asset_id=? AND status IN ('Reserved','Dispatched','On Rent','Standby')
               ORDER BY on_rent DESC LIMIT 1""",
            (a["id"],),
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
            "customer_id": cust_code(con, live["customer_id"]) if live else "",
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
           JOIN assets a ON a.id = t.asset_id
           JOIN customers c ON c.id = t.customer_id
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
        """SELECT t.ticket_id, a.asset_id AS asset_code, t.status, t.on_rent, t.off_rent,
                  a.unit_no, a.description, c.account_name, s.site_name
           FROM tickets t
           JOIN assets a ON a.id = t.asset_id
           JOIN customers c ON c.id = t.customer_id
           LEFT JOIN sites s ON s.id = t.site_id
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
            "asset_id": t["asset_code"],
            "unit_no": t["unit_no"],
            "description": t["description"] or "",
            "account_name": t["account_name"],
            "site_name": t["site_name"] or "",
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
    # Build 'v' (landmine c): skip numbers already in use, like every
    # other generator — a WO created ahead of the counter must never
    # be reissued.
    while True:
        n = _reserve_counter(con, "next_wo", 101)
        wid = f"WO-{n}"
        if not con.execute("SELECT 1 FROM work_orders WHERE wo_id=?",
                           (wid,)).fetchone():
            return wid
def wo_cost(labor, parts, other) -> float:
    return round(float(labor or 0) + float(parts or 0) + float(other or 0), 2)
def _ensure_wo_lines_table(con: sqlite3.Connection) -> None:
    """wo_lines owns the WO's line items (2026-10-15: one WO, many lines).
    Fresh DBs get it from schema.sql; this migrates existing DBs."""
    con.execute("""CREATE TABLE IF NOT EXISTS wo_lines (
        line_id INTEGER PRIMARY KEY AUTOINCREMENT,
        wo_id INTEGER NOT NULL,
        item TEXT DEFAULT '',
        description TEXT DEFAULT '',
        category TEXT DEFAULT 'Other',
        qty REAL DEFAULT 1,
        rate REAL DEFAULT 0,
        uom TEXT DEFAULT 'Each',
        amount REAL DEFAULT 0
    )""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_wo_lines_wo ON wo_lines(wo_id)")
    # Global line-item row (2026-10-15): Type + Unit on WO lines.
    _wcols = [r[1] for r in con.execute("PRAGMA table_info(wo_lines)")]
    if "category" not in _wcols:
        con.execute("ALTER TABLE wo_lines ADD COLUMN category TEXT DEFAULT 'Other'")
    if "uom" not in _wcols:
        con.execute("ALTER TABLE wo_lines ADD COLUMN uom TEXT DEFAULT 'Each'")


def wo_lines(con: sqlite3.Connection, wo_id: str):
    """Line items for one WO, in entry order. Lazy-migrates legacy WOs
    whose single line still lives on the work_orders row (item/qty/cost
    columns, dormant since 2026-10-15): one-time, idempotent, and only
    when no wo_lines rows exist yet."""
    _ensure_wo_lines_table(con)
    wkey = key_of(con, "work_orders", wo_id)
    rows = con.execute(
        "SELECT * FROM wo_lines WHERE wo_id=? ORDER BY line_id", (wkey,)
    ).fetchall()
    if rows:
        return rows
    try:
        w = con.execute(
            "SELECT item, description, qty, cost FROM work_orders WHERE wo_id=?",
            (wo_id,)).fetchone()
    except sqlite3.Error:
        return []
    if w and w["item"] is not None and ((w["item"] or "").strip() or (w["description"] or "").strip()):
        # Line-era WO only: item IS NULL means the row predates the line
        # columns (its description is the header description, not a
        # line) — no migration; the WO is header-only.
        qty = _money(w["qty"] or 1)
        rate = _money(w["cost"] or 0)
        amt = (qty * rate).quantize(CENT, rounding=ROUND_HALF_UP)
        con.execute(
            "INSERT INTO wo_lines(wo_id,item,description,qty,rate,amount)"
            " VALUES (?,?,?,?,?,?)",
            (wkey, w["item"] or "", w["description"] or "",
             float(qty), float(rate), float(amt)))
        con.commit()
        return con.execute(
            "SELECT * FROM wo_lines WHERE wo_id=? ORDER BY line_id",
            (wkey,)).fetchall()
    return []


def save_wo(con, data: dict, wo_id: str | None = None) -> str:
    # Ensure new columns exist (Jason 2026-10-07 F8)
    wcols = [r[1] for r in con.execute("PRAGMA table_info(work_orders)")]
    for col, ddl in [("ref_ticket", "TEXT"), ("wo_date", "TEXT"), ("item", "TEXT"),
                     ("qty", "REAL DEFAULT 1"), ("cost", "REAL DEFAULT 0"),
                     ("po", "TEXT")]:
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
            raise ValueError("Unknown rental ticket")
        cust = cust or t["customer_id"]
    cust = cust_key(con, cust) if cust else None
    if charge == "customer" and not cust:
        raise ValueError("Billable work needs a customer")
    status = data.get("status") or "Open"
    if status not in lookups(con, "wo_status"):
        raise ValueError("Pick a status")
    # Bill (2026-10-15): one WO with line items — the bill IS the sum of
    # the lines. The form never sends bill_amount (it never had a Bill
    # field), so a lines-less save keeps the old bill_amount path.
    lines = data.get("lines")
    if lines is not None:
        # Money is Decimal in computation, REAL at rest: sum the
        # per-line amounts (each rounded to cents) so the bill equals
        # exactly the sum of the stored line amounts.
        line_total = Decimal("0.00")
        for ln in lines:
            line_total += (_money(ln.get("qty") or 0) * _money(ln.get("cost") or 0)).quantize(CENT, rounding=ROUND_HALF_UP)
        bill = float(line_total) if charge == "customer" else 0.0
    elif charge == "internal":
        bill = 0.0
    else:
        bill = _mf(data.get("bill_amount") or 0)
    if charge == "customer" and status == "Complete" and bill <= 0:
        raise ValueError("Completed customer work needs a positive bill amount")
    open_d = data.get("open_date") or date.today().isoformat()
    close_d = data.get("close_date") or None
    if status == "Complete" and not close_d:
        close_d = date.today().isoformat()
    if status in ("Open", "In progress"):
        close_d = close_d or None
    wid = wo_id or next_wo_id(con)
    prior = con.execute("SELECT * FROM work_orders WHERE wo_id=?", (wid,)).fetchone()
    if prior and prior["invoice_id"]:
        charge = prior["charge_to"]
        bill = float(prior["bill_amount"] or 0)
        cust = prior["customer_id"]
        status = prior["status"]
    row = (
        asset_key(con, aid),
        key_of(con, "tickets", tid) if tid else None,
        cust, charge, wtype, desc, data.get("vendor") or "",
        open_d, close_d,
        _mf(data.get("labor") or 0), _mf(data.get("parts") or 0),
        _mf(data.get("other_cost") or 0), bill, status,
        1 if data.get("warranty") else 0,
        data.get("yard_or_site") or "", data.get("notes") or "",
        data.get("ref_ticket") or "", data.get("wo_date") or "",
        (data.get("po") or "").strip(),
        wid,
    )
    exists = con.execute("SELECT 1 FROM work_orders WHERE wo_id=?", (wid,)).fetchone()
    sql_u = """UPDATE work_orders SET asset_id=?, ticket_id=?, customer_id=?, charge_to=?,
               work_type=?, description=?, vendor=?, open_date=?, close_date=?,
               labor=?, parts=?, other_cost=?, bill_amount=?, status=?, warranty=?,
               yard_or_site=?, notes=?, ref_ticket=?, wo_date=?, po=?
               WHERE wo_id=?"""
    sql_i = """INSERT INTO work_orders (asset_id, ticket_id, customer_id, charge_to,
               work_type, description, vendor, open_date, close_date, labor, parts,
               other_cost, bill_amount, status, warranty, yard_or_site, notes,
               ref_ticket, wo_date, po, wo_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""
    con.execute(sql_u if exists else sql_i, row)
    # Line items (2026-10-15): the WO row no longer carries item/qty/cost
    # (those columns are dormant). Replace the whole line set on every
    # save that carries lines.
    if lines is not None:
        _ensure_wo_lines_table(con)
        wkey = key_of(con, "work_orders", wid)
        con.execute("DELETE FROM wo_lines WHERE wo_id=?", (wkey,))
        for ln in lines:
            qty = _money(ln.get("qty") or 0)
            rate = _money(ln.get("cost") or 0)
            amt = (qty * rate).quantize(CENT, rounding=ROUND_HALF_UP)
            con.execute(
                "INSERT INTO wo_lines(wo_id,item,description,category,qty,rate,uom,amount)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (wkey, (ln.get("item") or "").strip(),
                 (ln.get("description") or "").strip(),
                 clean_line_type(con, ln.get("category")),
                 float(qty), float(rate),
                 clean_line_uom(con, ln.get("uom")), float(amt)))
    if data.get("quote_no") and cust:
        _set_quote_link(con, "work_orders", "wo_id", wid, data["quote_no"], cust)
    con.commit()
    return wid
def report_work_orders(con, kind: str = "ytd") -> dict:
    start, end, label = period_bounds(kind)
    rows = []
    exp = inc = 0.0
    for w in con.execute(
        """SELECT w.*, a.unit_no, a.asset_id AS asset_code, a.description AS asset_desc, c.account_name
           FROM work_orders w
           JOIN assets a ON a.id = w.asset_id
           LEFT JOIN customers c ON c.id = w.customer_id
           ORDER BY w.open_date DESC"""
    ):
        d = _parse(w["open_date"])
        if d and (d < start or d > end):
            continue
        if w["status"] == "Void":
            continue
        cost = wo_cost(w["labor"], w["parts"], w["other_cost"])
        bill = float(w["bill_amount"] or 0) if w["charge_to"] == "customer" and w["invoice_id"] else 0.0
        exp += cost
        inc += bill
        rows.append({
            "wo_id": w["wo_id"],
            "unit_no": w["unit_no"],
            "asset_id": w["asset_code"],
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

def next_sale_id(con) -> str:
    """The one sale-number minter (build 'v'): S-{year}-{n}, unpadded —
    the format the book already carries (the sale form's padded
    variant is retired; existing numbers never change). Skips any
    number already in use."""
    import datetime as _dt
    yr = _dt.date.today().year
    n = con.execute(
        "SELECT COALESCE(MAX(CAST(SUBSTR(sale_id, 8) AS INTEGER)), 0) "
        "FROM sales WHERE sale_id LIKE ?", (f"S-{yr}-%",)).fetchone()[0]
    while True:
        n += 1
        sid = f"S-{yr}-{n}"
        if not con.execute("SELECT 1 FROM sales WHERE sale_id=?",
                           (sid,)).fetchone():
            return sid


def peek_next_sale_id(con) -> str:
    """The number the next minted sale will carry (display only)."""
    return next_sale_id(con)


def create_sale(con, asset_id, customer_id, sale_date, amount, notes="", clerk="", qty=1, condition="", sale_id=None, ref_no="", item_desc="", sale_group=None, plant_confirm=False, fleet_confirm=False):
    """Record an outright equipment sale. Marks the asset as sold.
    Money universality (Jason 2026-10-23): every sale row carries a
    stable line identity — seq, its position in the book — and a
    group: the rows of one multi-line sale submission share the
    group's engine key (the first row's key), so money can be taken
    against the sale as a whole or line by line. A lone sale is its
    own group. (Build 'v': the group is the surrogate group_id; the
    group's number is the head row's sale number, as before.)"""
    # Ensure new columns exist (Jason 2026-10-07)
    scols = [r[1] for r in con.execute("PRAGMA table_info(sales)")]
    if "ref_no" not in scols:
        con.execute("ALTER TABLE sales ADD COLUMN ref_no TEXT")
    if "item_desc" not in scols:
        con.execute("ALTER TABLE sales ADD COLUMN item_desc TEXT")
    if "seq" not in scols:
        con.execute("ALTER TABLE sales ADD COLUMN seq INTEGER")
    if "group_id" not in scols:
        con.execute("ALTER TABLE sales ADD COLUMN group_id INTEGER")
    if "line_note" not in scols:
        con.execute("ALTER TABLE sales ADD COLUMN line_note TEXT")
    # Engine class foundation (Phase 5, Jason 2026-10-24): the sale
    # motion draws Stock freely; Plant and Fleet sell only through
    # their deliberate double checks — plant_confirm / fleet_confirm,
    # the same flags the sale form's confirm checkboxes carry — and a
    # unit out of Active service does not sell at all (set it Active
    # first; the switch is one audited step on the asset form). The
    # picker offers exactly this; the engine refuses the rest no
    # matter what a caller posts, with the reason stated.
    _a = _asset_row(con, asset_id)
    if not _a:
        raise ValueError(f"Unknown unit {asset_id}")
    if _a["status"] != "Active":
        raise ValueError(
            f"Unit {_a['unit_no']} is {_a['status']} — set it Active to sell it")
    _sold = con.execute(
        "SELECT sold_date FROM assets WHERE asset_id=?", (asset_id,)).fetchone()
    if _sold and _sold["sold_date"]:
        raise ValueError(f"Unit {_a['unit_no']} is already sold")
    if _a["designation"] == "Plant" and not plant_confirm:
        raise ValueError(
            f"Plant asset {_a['unit_no']} is a fixed asset — confirm the "
            "Plant sale to proceed")
    if _a["designation"] == "Fleet" and not fleet_confirm:
        raise ValueError(
            f"Fleet asset {_a['unit_no']} is a rental unit — confirm the "
            "Fleet sale to proceed")
    if not sale_id:
        sale_id = next_sale_id(con)
    seq = con.execute(
        "SELECT COALESCE(MAX(seq), 0) + 1 FROM sales").fetchone()[0]
    akey = asset_key(con, asset_id)
    ckey = cust_key(con, customer_id)
    gkey = key_of(con, "sales", sale_group) if sale_group else None
    cur = con.execute(
        "INSERT INTO sales (sale_id, asset_id, customer_id, sale_date, qty, amount, condition, notes, clerk, ref_no, item_desc, seq, group_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (sale_id, akey, ckey, sale_date, qty, amount, condition, notes, clerk, ref_no, item_desc, seq, gkey)
    )
    if gkey is None:
        # A lone sale / the head of a group: its group is itself.
        con.execute("UPDATE sales SET group_id=? WHERE id=?",
                    (cur.lastrowid, cur.lastrowid))
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
           JOIN assets a ON a.id=s.asset_id
           LEFT JOIN customers c ON c.id=s.customer_id
           ORDER BY s.sale_date DESC, s.sale_id DESC
           LIMIT ?""",
        (limit,)
    ).fetchall()
    return [dict(r) for r in rows]
