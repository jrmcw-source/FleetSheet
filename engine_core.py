"""All money and status rules live here. The UI never computes them."""
from __future__ import annotations
import sqlite3
from calendar import monthrange
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from pathlib import Path
import hashlib
import hmac
import json
import time

# Tiny TTL cache for expensive read-only aggregations (invoice batches,
# compliance watch). Collapses duplicate calls within a single page render.
# 2-second TTL: invisible to users, data changes only via their own actions.
_ttl_cache: dict = {}
def ttl_cached(ttl_seconds: float = 2.0):
    def deco(fn):
        def wrapper(*args, **kwargs):
            now = time.monotonic()
            # Key on function + identity of args (connections are
            # per-request). A connection keys on its database FILE,
            # not id() alone (build 'x'): a closed connection's id()
            # is recycled by the next connection, and within the TTL
            # the cache then served one book's aggregates to another
            # book in the same process — the compliance watch reached
            # the Today ticker one book behind in the test harness.
            # Same file + id() keeps the intended same-book sharing;
            # a different file never collides.
            def _key_of(a):
                if isinstance(a, sqlite3.Connection):
                    try:
                        row = a.execute("PRAGMA database_list").fetchone()
                        return ("db", row[2] if row else "", id(a))
                    except Exception:
                        return ("con", id(a))
                return ("id", id(a))
            key = (fn.__name__, tuple(_key_of(a) for a in args),
                   tuple(sorted((k, _key_of(v)) for k, v in kwargs.items())))
            hit = _ttl_cache.get(key)
            if hit and now - hit[0] < ttl_seconds:
                return hit[1]
            val = fn(*args, **kwargs)
            _ttl_cache[key] = (now, val)
            # Bound growth: drop expired entries opportunistically.
            if len(_ttl_cache) > 64:
                for k in [k for k, (t, _) in _ttl_cache.items() if now - t >= ttl_seconds]:
                    del _ttl_cache[k]
            return val
        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__
        return wrapper
    return deco
import io
import json
import os
import re
import secrets
import shutil
import tempfile
import zipfile

"""FleetSheet engine core: money/date/row helpers, shared domain constants, options, desk PIN, yard-device auth, crew, lookups. No imports from sibling engine modules."""

__all__ = ['_money', '_mf', '_ms', 'parse_date', '_parse', 'terms_days', '_row_get', 'require_clerk', 'list_crew', 'add_crew', 'drop_crew', '_reserve_counter', '_next_doc', 'peek_next_doc', '_set_quote_link', 'lookups', 'LOOKUP_ADDABLE_KINDS', 'add_lookup', 'CURATED_LOOKUP_KINDS', 'deleted_lookups', 'clear_deleted_lookup', 'delete_lookup', 'period_bounds', '_ensure_device_tables', 'get_option', 'set_option', 'DOC_PREFIX_DEFAULTS', 'doc_prefix', 'DOC_NUMBER_FLOOR', 'DOC_NUMBER_FLOORS', 'doc_number_floor', 'company_snapshot_json', 'stamp_company_snapshot', 'MODULE_NAMES', 'COND_NOT_RECORDED', 'module_on', 'set_module', 'module_seen', 'stamp_module_seen', '_pbkdf2', 'pin_is_set', 'get_pin_secret', 'set_pin', 'verify_pin', 'clear_pin', 'PIN_SECURITY_QUESTIONS', 'format_phone_number',
    'set_pin_security', 'validate_pin_security', 'pin_security_is_set', 'pin_security_questions',
    'verify_pin_security', '_new_device_token', 'issue_device', 'list_devices', 'get_device', 'device_check', 'touch_device', 'revoke_device', 'rotate_device', '_shift_months', '_pos_or_none', 'CENT', 'SCHEMA', 'SEED_PACKS', '_LOCAL', '_TMP', 'OPEN_STATUSES', 'BLOCKING', 'ALLOWED_NEXT', 'COND_RANK', 'CASH_METHODS', 'QUOTE_NEXT', 'PC_IN_CATS', 'PC_OUT_CATS', 'EXPORT_WHENS', 'EXPORT_HOWS', 'DEVICE_GRACE_HOURS', 'TRIGGER_LABELS', 'BASIS_LABELS', 'DUE_SOON_DAYS', 'BACKUP_KEEP', 'backup_folder', 'set_backup_dir', 'backup_status', 'get_backup_schedule', 'set_backup_schedule', 'list_backups', 'prune_backups', 'run_backup', 'validate_backup_file', 'validate_backup_archive', 'restore_backup', 'restore_backup_archive', 'read_backup_file', 'sweep_orphan_photos', 'PHOTO_MAX_BYTES', 'PHOTO_EXTS', 'photo_dir', 'photo_ext_for', 'validate_photo_blob', 'safe_photo_name', 'DOC_MAX_BYTES', 'DOC_KINDS', 'doc_dir', 'doc_ext_for', 'validate_doc_blob', 'safe_doc_name', 'save_unit_doc', 'list_unit_docs', 'get_unit_doc', 'read_unit_doc', 'delete_unit_doc', 'sweep_orphan_docs', 'list_company_phones', 'main_company_phone', 'add_company_phone', 'del_company_phone', 'set_main_company_phone', 'validate_new_doc_no', 'peek_next_invoice_no', 'peek_next_ticket_no', 'key_of', 'num_of', 'doc_key', 'doc_num', 'DOC_TABLES', 'cust_key', 'cust_code', 'asset_key', 'asset_code', 'site_key', 'site_code', 'loc_key', 'loc_code', '_next_pay_key', 'pay_key_of', 'pay_id_of']

def _money(v):
    try: return Decimal(str(v or 0)).quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError): raise ValueError("Invalid monetary amount") from None
def _mf(v): return float(_money(v))
def _ms(*vs): return sum((_money(v) for v in vs), Decimal("0.00")).quantize(CENT, rounding=ROUND_HALF_UP)
def parse_date(value, field: str = "Date", required: bool = True):
    """Validate a YYYY-MM-DD date string. Returns the normalized ISO string.

    Raises ValueError on garbage like 'not-a-date' instead of letting it
    into the database. Empty + required=False returns None.
    """
    v = (value or "")
    v = str(v).strip()
    if not v:
        if required:
            raise ValueError(f"{field} is required")
        return None
    try:
        d = date.fromisoformat(v)
    except ValueError:
        raise ValueError(f"{field} must be a real calendar date (YYYY-MM-DD)") from None
    return d.isoformat()
def _parse(d: str | None) -> date | None:
    if not d:
        return None
    d = str(d)[:10]
    # Fast path: ISO YYYY-MM-DD is the stored format for ~all dates.
    if len(d) == 10 and d[4] == "-" and d[7] == "-":
        try:
            return date.fromisoformat(d)
        except ValueError:
            pass
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(d, fmt).date()
        except ValueError:
            continue
    return None
_PHONE_EXT_RE = re.compile(
    r"^(.*?)[\s.\-]*(?:x|ext\.?|extension)\s*(\d{1,6})\s*$", re.IGNORECASE)


def format_phone_number(value):
    """The ONE phone formatter (Jason 2026-10-21, look-see batch 2):
    every phone field app-wide stores and shows through here.

    Pattern: +X (XXX) XXX-XXXX, with Jason's rules:
    - 10 digits, no country prefix entered -> (XXX) XXX-XXXX
      (no prefix is invented).
    - 11 digits leading 1, or an explicit +1 -> +1 (XXX) XXX-XXXX.
    - An explicit +country number: best-effort — the leading digits
      are the country code and the last ten digits group as
      (XXX) XXX-XXXX (e.g. +63 917 123 4567 -> +63 (917) 123-4567).
    - An extension marked with x / ext / ext. / extension and digits
      rides along as " x12345".
    - Anything that does not parse to the pattern — international
      free-form, letters, odd digit counts — returns EXACTLY as
      typed, never mangled. The typist always wins: this only ever
      runs at save/display time on the value as a whole, and it is
      idempotent (a formatted number formats to itself).
    """
    raw = "" if value is None else str(value)
    s = raw.strip()
    if not s:
        return raw
    ext = ""
    m = _PHONE_EXT_RE.match(s)
    if m and m.group(1).strip():
        s, ext = m.group(1).strip(), m.group(2)
    has_plus = s.startswith("+")
    digits = "".join(ch for ch in s if ch.isdigit())
    # Letters anywhere in the main part (vanity numbers, notes like
    # "call office") mean free-form: hands off.
    if any(ch.isalpha() for ch in s):
        return raw
    out = None
    if has_plus:
        if len(digits) == 11 and digits.startswith("1"):
            out = f"+1 ({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
        elif 12 <= len(digits) <= 13:
            cc, rest = digits[:-10], digits[-10:]
            out = f"+{cc} ({rest[:3]}) {rest[3:6]}-{rest[6:]}"
    else:
        if len(digits) == 10:
            out = f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
        elif len(digits) == 11 and digits.startswith("1"):
            out = f"+1 ({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
    if out is None:
        return raw
    return out + (f" x{ext}" if ext else "")


def terms_days(terms: str) -> int:
    """Days until due for a payment-terms string (ITEM F). 'Net N' is
    parsed by regex — Net 7/21/90 and the discount forms ('1/10 Net 30',
    '2/10 Net 30' -> 30) compute from the Net number, never a substring
    scan (the old scan read '1/10 Net 30' as 10). Immediate terms
    (Due on Receipt, Cash in Advance, Payment in Advance, COD, Cash
    with Order, Cash before Shipment) are 0. Anything else — EOM, MFI,
    '50% Upfront', one-off custom strings with no Net number — falls
    back to 30 days: EOM/MFI aging is approximated at 30, while the
    printed terms text itself is always the verbatim stored string."""
    t = (terms or "").strip().lower()
    if not t:
        return 30
    if ("receipt" in t or "cash in advance" in t or "payment in advance" in t
            or t == "cod" or "cash with order" in t
            or "cash before shipment" in t):
        return 0
    m = re.search(r"net\s*(\d+)", t)
    if m:
        return int(m.group(1))
    return 30
def _row_get(row, key, default=None):
    try:
        val = row[key]
    except (KeyError, IndexError):
        return default
    return default if val is None else val
def require_clerk(name: str | None) -> str:
    n = (name or "").strip()
    if not n:
        raise ValueError("Name is required")
    return n[:40]
def list_crew(con) -> list[str]:
    return [r[0] for r in con.execute("SELECT name FROM crew ORDER BY name COLLATE NOCASE")]
def add_crew(con, name: str, position: str = "") -> None:
    n = require_clerk(name)
    p = (position or "").strip()[:40]
    con.execute("INSERT OR IGNORE INTO crew(name) VALUES (?)", (n,))
    con.execute("UPDATE crew SET position=? WHERE name=?", (p, n))
    con.commit()
def drop_crew(con, name: str) -> None:
    con.execute("DELETE FROM crew WHERE name=?", ((name or "").strip(),))
    con.commit()
# --- Company phone list ---------------------------------------------------
# One company, many numbers. The legacy company.phone column stays for old
# reads (letterhead); the list below is what the Setup page shows and edits.
def list_company_phones(con) -> list:
    return con.execute(
        "SELECT phone_id, label, number, is_main FROM company_phones"
        " ORDER BY is_main DESC, sort, phone_id"
    ).fetchall()
def main_company_phone(con):
    row = con.execute(
        "SELECT label, number FROM company_phones WHERE is_main=1"
        " ORDER BY sort, phone_id LIMIT 1"
    ).fetchone()
    if row:
        return row
    return con.execute(
        "SELECT label, number FROM company_phones ORDER BY sort, phone_id LIMIT 1"
    ).fetchone()


def company_snapshot_json(con) -> str:
    """The company identity exactly as the print header reads it
    (build 'ab', redirect #3): the company row with the operator-
    picked main phone overlaid — the same composition
    printpack._company_for_print performs — frozen as JSON.
    Issuance stamps this onto the document; reprints render the
    stamp, never the live record."""
    row = con.execute("SELECT * FROM company WHERE id=1").fetchone()
    d = dict(row) if row else {}
    try:
        main = main_company_phone(con)
    except Exception:
        main = None
    if main:
        num = (main["number"] or "").strip()
        if num:
            d["phone"] = num
    return json.dumps(d)


def stamp_company_snapshot(con, table: str, key, pk: str = "id") -> None:
    """Freeze the current company identity onto one document row
    (its co_snapshot column). Called at every posting — creation
    saves and revision-completion saves alike: a posted revision
    is a new issuance and wears the identity current at its own
    posting. A no-op on books whose table predates the column."""
    if key is None:
        return
    cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
    if "co_snapshot" not in cols:
        return
    con.execute(f"UPDATE {table} SET co_snapshot=? WHERE {pk}=?",
                (company_snapshot_json(con), key))


def add_company_phone(con, label: str, number: str, make_main: bool = False) -> None:
    label = ((label or "").strip() or "Main")[:40]
    number = format_phone_number((number or "").strip())[:40]
    if not number:
        raise ValueError("Phone number is required")
    # Main is an explicit operator pick only (Batch 3 #5): adding a
    # phone never promotes it — not by label, not by being first.
    if make_main:
        con.execute("UPDATE company_phones SET is_main=0")
    mx = con.execute("SELECT COALESCE(MAX(sort), -1) FROM company_phones").fetchone()[0]
    con.execute(
        "INSERT INTO company_phones (label, number, is_main, sort) VALUES (?, ?, ?, ?)",
        (label, number, 1 if make_main else 0, (mx or 0) + 1),
    )
    con.commit()
def del_company_phone(con, phone_id: int) -> None:
    row = con.execute(
        "SELECT is_main FROM company_phones WHERE phone_id=?", (phone_id,)
    ).fetchone()
    if not row:
        return
    con.execute("DELETE FROM company_phones WHERE phone_id=?", (phone_id,))
    # No delete-promotes-next (Batch 3 #5): deleting the main number
    # leaves no main picked until the operator picks one; reads fall
    # back to the first listed number (main_company_phone).
    con.commit()
def set_main_company_phone(con, phone_id: int) -> None:
    if not con.execute(
        "SELECT 1 FROM company_phones WHERE phone_id=?", (phone_id,)
    ).fetchone():
        raise ValueError("Unknown phone")
    con.execute("UPDATE company_phones SET is_main=0")
    con.execute("UPDATE company_phones SET is_main=1 WHERE phone_id=?", (phone_id,))
    con.commit()
# Generated-number floor (build 'ai', Jason 2026-10-28): every
# number the program generates starts at 100001. The floor is
# applied at mint and peek time — the next generated number for a
# kind is max(its counter's current next value, 100001) — so an
# existing book's stored counter is never rewritten, its documents
# never renumber, and a book already past the floor is untouched.
# Build 'ao' (Jason 2026-10-29): the single floor becomes a
# per-kind start — the kinds all read too similar at one start,
# so each kind's series opens at its own number. The invoice
# keeps 100001 (DOC_NUMBER_FLOOR, also the default for any kind
# not listed); an existing book's counter or documents are never
# rewritten — a kind already past its start is untouched, and a
# kind standing below it opens at the start.
DOC_NUMBER_FLOOR = 100001
DOC_NUMBER_FLOORS = {
    "pay": 200001,
    "cm": 300001,
    "sale": 400001,
    "ticket": 500001,
    "wo": 600001,
    "change": 700001,
    "quote": 800001,
    "batch": 900001,
    "cash": 20001,
    "petty": 2001,
}

def doc_number_floor(kind: str) -> int:
    """The first number the generator hands out for a document
    kind (build 'ao'): the kind's own start from DOC_NUMBER_FLOORS,
    keyed by the same kind names doc_prefix uses; the invoice and
    any unlisted kind keep the 100001 floor."""
    return DOC_NUMBER_FLOORS.get(kind, DOC_NUMBER_FLOOR)

def _reserve_counter(con: sqlite3.Connection, col: str, default: int = 1001,
                     floor: int = 0) -> int:
    """Atomically reserve and return the current value of a company counter.

    SQLite serializes the UPDATE itself, so two desk/yard writers cannot both
    receive the same number.  The caller remains responsible for its normal
    surrounding transaction/commit. With floor set (document-number
    minters, build 'ai'), a counter standing below the floor hands
    out the floor itself and advances past it in the same UPDATE.
    """
    if floor:
        row = con.execute(
            f"UPDATE company SET {col}=MAX(COALESCE({col}, ?), ?) + 1 "
            f"WHERE id=1 RETURNING {col} - 1", (default, floor)
        ).fetchone()
    else:
        row = con.execute(
            f"UPDATE company SET {col}=COALESCE({col}, ?) + 1 WHERE id=1 "
            f"RETURNING {col} - 1", (default,)
        ).fetchone()
    if not row:
        raise ValueError("Company setup is missing")
    return int(row[0])

def _next_doc(con, col: str, prefix: str, table: str, idcol: str,
              floor: int = DOC_NUMBER_FLOOR) -> str:
    while True:
        n = _reserve_counter(con, col, 1001, floor=floor)
        did = f"{prefix}-{n:04d}"
        if not con.execute(f"SELECT 1 FROM {table} WHERE {idcol}=?", (did,)).fetchone():
            return did
def peek_next_doc(con, col: str, prefix: str, table: str, idcol: str,
                  floor: int = DOC_NUMBER_FLOOR) -> str:
    """What _next_doc would return, WITHOUT reserving: read the counter and
    skip numbers already in the table, but write nothing. GET previews use
    this so rendering a form never burns a sequence number; the real
    reservation happens at save time via _next_doc. The counter column holds
    the next number to hand out (see _reserve_counter). Build 'ai': the
    preview applies the same floor the mint applies (build 'ao': the
    caller's per-kind start)."""
    row = con.execute(f"SELECT COALESCE({col}, 1001) FROM company WHERE id=1").fetchone()
    n = max(int(row[0]) if row else 1001, floor)
    while True:
        did = f"{prefix}-{n:04d}"
        if not con.execute(f"SELECT 1 FROM {table} WHERE {idcol}=?", (did,)).fetchone():
            return did
        n += 1
def validate_new_doc_no(con, table: str, idcol: str, value, noun: str) -> str:
    """Creation-time document number (Batch 3 #14): the operator's own
    number, free text, used exactly as typed. It must be non-empty and
    not already in use for that document type — a duplicate (or a blank)
    refuses the save and writes nothing. Returns the number, stripped."""
    v = (value or "").strip()
    if not v:
        raise ValueError(f"Type the {noun} number")
    if con.execute(f"SELECT 1 FROM {table} WHERE {idcol}=?", (v,)).fetchone():
        raise ValueError(f"{v} is already in use")
    return v


# ---------------------------------------------------------------------------
# Number <-> key resolution (build 'v', Jason 2026-10-25: "No form number
# is ever a key ID. Key ID's must exist for every table, always be unique,
# and assigned by the engine"). Storage references run on the surrogate
# keys; operators keep addressing everything by its display number or
# code — URLs, forms, print. These helpers are the translation seam.
# Permissive on the way in: an int key or a display value both resolve
# to the key. Exact on the way out: a key resolves to its display value.
# Blank or unknown resolves to None.

_KEY_TABLES = {
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
    "collections": "pay_id",
    "doc_collections": "pay_id",
    "petty_cash": "pc_id",
}

# Document kinds (the money layer's vocabulary) -> their tables. A sale
# is addressed by its head row's number, so the row key IS the group key.
DOC_TABLES = {
    "invoice": "invoices",
    "ticket": "tickets",
    "wo": "work_orders",
    "quote": "quotes",
    "sale": "sales",
    "credit": "credit_memos",
    "change": "change_orders",
}


def key_of(con, table: str, value):
    """Display value (or an existing surrogate key) -> surrogate key."""
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
    col = _KEY_TABLES[table]
    if isinstance(value, int):
        r = con.execute(f"SELECT id FROM {table} WHERE id=?", (value,)).fetchone()
        if r:
            return int(r[0])
    r = con.execute(f"SELECT id FROM {table} WHERE {col}=?", (value,)).fetchone()
    return int(r[0]) if r else None


def num_of(con, table: str, key):
    """Surrogate key -> display value (number / code), or None."""
    if key is None:
        return None
    col = _KEY_TABLES[table]
    r = con.execute(f"SELECT {col} FROM {table} WHERE id=?", (key,)).fetchone()
    return r[0] if r else None


def doc_key(con, kind: str, ref):
    """A money document's display reference -> its engine key."""
    return key_of(con, DOC_TABLES[kind], ref)


def doc_num(con, kind: str, key):
    """A money document's engine key -> its display reference."""
    return num_of(con, DOC_TABLES[kind], key)


def cust_key(con, value):
    return key_of(con, "customers", value)


def cust_code(con, key):
    return num_of(con, "customers", key)


def asset_key(con, value):
    return key_of(con, "assets", value)


def asset_code(con, key):
    return num_of(con, "assets", key)


def site_key(con, value):
    return key_of(con, "sites", value)


def site_code(con, key):
    return num_of(con, "sites", key)


def loc_key(con, value):
    return key_of(con, "jurisdictions", value)


def loc_code(con, key):
    return num_of(con, "jurisdictions", key)


def _next_pay_key(con) -> int:
    """Reserve the next key in the ONE pay-key space shared by the two
    money ledgers (collections + doc_collections): one payment event is
    one key wherever its rows live. The company counter holds the next
    key to hand out (see _reserve_counter)."""
    return _reserve_counter(con, "next_pay_key", 1)


def pay_key_of(con, pay_no):
    """A payment number -> its shared ledger key (either ledger)."""
    if pay_no is None:
        return None
    if isinstance(pay_no, str):
        pay_no = pay_no.strip()
        if not pay_no:
            return None
    if isinstance(pay_no, int):
        for tbl in ("collections", "doc_collections"):
            r = con.execute(f"SELECT id FROM {tbl} WHERE id=?", (pay_no,)).fetchone()
            if r:
                return int(r[0])
    for tbl in ("collections", "doc_collections"):
        r = con.execute(f"SELECT id FROM {tbl} WHERE pay_id=?", (pay_no,)).fetchone()
        if r:
            return int(r[0])
    return None


def pay_id_of(con, pay_key):
    """A shared ledger key -> its payment number (either ledger)."""
    if pay_key is None:
        return None
    for tbl in ("collections", "doc_collections"):
        r = con.execute(f"SELECT pay_id FROM {tbl} WHERE id=?", (pay_key,)).fetchone()
        if r:
            return r[0]
    return None


def peek_next_invoice_no(con) -> str:
    """What next_invoice_id would hand out, WITHOUT reserving: read the
    counter and skip numbers already in the table, but write nothing.
    GET previews use this so rendering a form never burns a number."""
    row = con.execute(
        "SELECT invoice_prefix, COALESCE(next_invoice, 1001) FROM company WHERE id=1"
    ).fetchone()
    prefix = row[0] if row else "INV"
    n = max(int(row[1]) if row else 1001, DOC_NUMBER_FLOOR)
    while True:
        did = f"{prefix}-{n}"
        if not con.execute("SELECT 1 FROM invoices WHERE invoice_no=?",
                           (did,)).fetchone():
            return did
        n += 1


def peek_next_ticket_no(con) -> str:
    """What next_ticket_id would hand out, WITHOUT reserving (see
    peek_next_invoice_no). Build 'af': the stem is the operator's
    (prefix_ticket)."""
    row = con.execute(
        "SELECT COALESCE(next_ticket, 1001) FROM company WHERE id=1").fetchone()
    n = max(int(row[0]) if row else 1001, doc_number_floor("ticket"))
    while True:
        did = f"{doc_prefix(con, 'ticket')}-{n}"
        if not con.execute("SELECT 1 FROM tickets WHERE ticket_id=?",
                           (did,)).fetchone():
            return did
        n += 1


def _set_quote_link(con, table: str, idcol: str, row_id: str, quote_no: str, customer_id: str) -> None:
    q = con.execute("SELECT id, customer_id, status FROM quotes WHERE quote_no=?", (quote_no,)).fetchone()
    if not q:
        raise ValueError("Unknown quote")
    if q["status"] == "Void":
        raise ValueError("Quote is void")
    if q["customer_id"] != cust_key(con, customer_id):
        raise ValueError("Quote belongs to another customer")
    # The child must belong to the same customer too (2026-10-15): the
    # quote-side Against picker passes the quote's customer, so without
    # this check one customer's WO could be linked to another's quote.
    child = con.execute(f"SELECT customer_id FROM {table} WHERE {idcol}=?", (row_id,)).fetchone()
    if not child:
        raise ValueError("Unknown work order" if table == "work_orders" else "Unknown rental ticket")
    if (child["customer_id"] or 0) != (cust_key(con, customer_id) or 0):
        raise ValueError("Work order belongs to another customer"
                         if table == "work_orders" else
                         "Rental ticket belongs to another customer")
    con.execute(f"UPDATE {table} SET quote_id=? WHERE {idcol}=?", (q["id"], row_id))
def lookups(con, kind):
    return [r["value"] for r in con.execute(
        "SELECT value FROM lookups WHERE kind=? ORDER BY sort_order, value", (kind,)
    )]


# Lookup kinds the global Other/-Add- dropdown rule (Issue 4) may extend.
# Fixed-semantic lists stay out: rate_type (values drive billing math —
# a custom rate type would silently bill as Day), status enums with CHECK
# constraints (ticket_status, wo_status), and combo-backed lists.
LOOKUP_ADDABLE_KINDS = ("cert_kind", "inv_cat", "inv_uom", "inv_item", "terms", "condition", "comp_doc", "designation")


# The three Spec 7 curated kinds (Setup -> Billing panels): the only
# kinds an operator can delete from the master list or restore to
# factory (polish round Item 6, 2026-10-20).
CURATED_LOOKUP_KINDS = ("terms", "inv_uom", "inv_item", "comp_doc")

# Deletion tombstones (Item 6): seed_lookups runs on every init_db —
# i.e. every request — and INSERT OR IGNOREs the factory packs, so a
# plain DELETE would be silently resurrected by the next page load.
# A deleted value is therefore also recorded in the book option
# "lookups_deleted" (JSON {kind: [values]}); seed_lookups skips
# tombstoned values. This is also what distinguishes "never
# initialized" (no tombstones; seeds fill the list) from "emptied by
# deletion" (tombstones present; seeds stay out). Re-adding a value
# (add_lookup) or restoring its kind clears its tombstone.
_DELETED_LOOKUPS_KEY = "lookups_deleted"


def deleted_lookups(con, kind=None):
    """Tombstoned (deleted-by-operator) lookup values. With `kind`,
    returns that kind's list; without, the whole {kind: [values]} dict.
    Absent/unreadable option -> empty."""
    try:
        raw = get_option(con, _DELETED_LOOKUPS_KEY, "") or ""
        data = json.loads(raw) if raw else {}
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    out = {}
    for k, vals in data.items():
        if isinstance(vals, list):
            out[str(k)] = [str(v) for v in vals]
    return out.get(kind, []) if kind else out


def _save_deleted_lookups(con, data):
    cleaned = {k: vals for k, vals in data.items() if vals}
    set_option(con, _DELETED_LOOKUPS_KEY,
               json.dumps(cleaned) if cleaned else "")


def clear_deleted_lookup(con, kind, value=None):
    """Clear tombstones: one value's, or (value=None) the kind's whole
    set — the Restore factory lists path. Commits via set_option."""
    data = deleted_lookups(con)
    if kind not in data:
        return
    if value is None:
        del data[kind]
    else:
        data[kind] = [v for v in data[kind] if v != value]
    _save_deleted_lookups(con, data)


def delete_lookup(con, kind, value):
    """Delete one entry from a curated master list (Item 6). Removes
    ONLY the lookups row and records a tombstone so the factory seed
    never resurrects it; no record/document row is touched — stored
    documents, invoices and customers keep their strings verbatim.
    Returns True when a row was removed. Raises ValueError for kinds
    outside the curated three or an empty value."""
    value = (value or "").strip()
    if kind not in CURATED_LOOKUP_KINDS:
        raise ValueError("List cannot be deleted here")
    if not value:
        raise ValueError("Nothing to delete")
    cur = con.execute(
        "DELETE FROM lookups WHERE kind=? AND value=?", (kind, value))
    data = deleted_lookups(con)
    vals = data.get(kind, [])
    if value not in vals:
        vals.append(value)
    data[kind] = vals
    _save_deleted_lookups(con, data)
    con.commit()
    return cur.rowcount == 1


def add_lookup(con, kind, value):
    """Insert one option into a lookups list (the -Add- path). Returns True
    when the option is new; False when it already existed. Raises ValueError
    for kinds outside LOOKUP_ADDABLE_KINDS or empty values."""
    value = (value or "").strip()
    if kind not in LOOKUP_ADDABLE_KINDS:
        raise ValueError("List cannot be extended here")
    if not value:
        raise ValueError("Type the new option first")
    if len(value) > 60:
        raise ValueError("New option exceeds 60 characters")
    # Re-adding a previously deleted value is an explicit undelete:
    # clear its tombstone or the next seed pass would keep it out and
    # the row below would be the only copy fighting the tombstone.
    if value in deleted_lookups(con, kind):
        clear_deleted_lookup(con, kind, value)
    nxt = con.execute(
        "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM lookups WHERE kind=?", (kind,)
    ).fetchone()[0]
    cur = con.execute(
        "INSERT OR IGNORE INTO lookups(kind,value,sort_order) VALUES (?,?,?)",
        (kind, value, nxt))
    con.commit()
    return cur.rowcount == 1

# Global line-item row (2026-10-15): every line row carries a Type from
# inv_cat and a Unit from inv_uom. Old lowercase quote kinds map over.
# Global dropdown rule (Issue 4, 2026-10-15): any non-empty string is a
# valid Type/Unit — picking Other and typing over it saves on that record.
# A blank still falls back to the neutral Other/Each rather than bouncing
# the save — the operator can fix it on the detail page.
_LEGACY_LINE_KIND = {"item": "Item", "unit": "Rental", "labor": "Labor",
                     "freight": "Freight", "other": "Other", "rental": "Rental",
                     "service": "Labor", "transport": "Freight"}


def clean_line_type(con, v) -> str:
    v = (v or "").strip()
    v = _LEGACY_LINE_KIND.get(v, v)
    # The -Add- sentinel is never a value: without JS it can arrive as a
    # bare form value; degrade to the neutral default, never store it.
    if v == "__add__":
        v = ""
    return v if v else "Other"


def clean_line_uom(con, v) -> str:
    v = (v or "").strip()
    if v == "__add__":
        v = ""
    return v if v else "Each"


# A Rental line's Unit (inv_uom) drives the ticket's rate type: the
# rental form and quote conversion share this map — one source.
_UOM_TO_RATE_TYPE = {"Days": "Day", "Weeks": "Week",
                     "Months": "Monthly", "Hours": "Hour"}


def uom_to_rate_type(uom) -> str:
    return _UOM_TO_RATE_TYPE.get((uom or "").strip(), "")
def period_bounds(kind: str, today: date | None = None) -> tuple[date, date, str]:
    today = today or date.today()
    kind = (kind or "mtd").lower()
    if kind == "7d":
        return today - timedelta(days=6), today, "Last 7 days"
    if kind == "30d":
        return today - timedelta(days=29), today, "Last 30 days"
    if kind == "ytd":
        return date(today.year, 1, 1), today, f"Year {today.year}"
    if kind == "lastm":
        first = date(today.year, today.month, 1)
        last_m_end = first - timedelta(days=1)
        last_m_start = date(last_m_end.year, last_m_end.month, 1)
        return last_m_start, last_m_end, last_m_start.strftime("%B %Y")
    if kind == "all":
        return date(2000, 1, 1), today, "All dates"
    # mtd
    return date(today.year, today.month, 1), today, today.strftime("%B %Y")
def _ensure_device_tables(con: sqlite3.Connection) -> None:
    """Compatibility assertion; schema.sql owns current table DDL."""
    for table in ("device_auths", "options"):
        if not con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
            raise RuntimeError(f"Database schema is incomplete: {table} is missing")

def get_option(con: sqlite3.Connection, key: str, default: str = "") -> str:
    _ensure_device_tables(con)
    r = con.execute("SELECT value FROM options WHERE key=?", (key,)).fetchone()
    return r["value"] if r else default
def set_option(con: sqlite3.Connection, key: str, value: str) -> None:
    _ensure_device_tables(con)
    con.execute(
        "INSERT INTO options(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value or ""),
    )
    con.commit()

# Document number stems (build 'af', Jason 2026-10-28): every form
# kind's number prefix is the operator's, set in Admin -> Billing
# beside the Invoice Number Prefix and stored as an option
# (prefix_<kind>). Unset or blank reads as the factory literal —
# the stem each minter carried in code before this build. The
# invoice stem is NOT here: it is the company record's
# invoice_prefix column, older than this mechanism.
# Build 'ai' (Jason 2026-10-28): the factory literals reset to his
# table — sale S -> ST, ticket T -> RT, pay P -> PMT, cash CE ->
# CASH. A book that stored its own prefix_<kind> option keeps it;
# only the unset fallback changes.
DOC_PREFIX_DEFAULTS = {
    "quote": "QT", "wo": "WO", "sale": "ST", "ticket": "RT",
    "change": "CO", "cm": "CM", "pay": "PMT",
    "cash": "CASH", "petty": "PC", "batch": "PB",
}

def doc_prefix(con: sqlite3.Connection, kind: str) -> str:
    """The effective number stem for a document kind: the
    operator's prefix_<kind> option when set, else the factory
    literal. Minters take only the stem from here — each kind's
    number shape and padding are its own and unchanged."""
    v = (get_option(con, f"prefix_{kind}", "") or "").strip()
    return v or DOC_PREFIX_DEFAULTS[kind]

# --- Shop-flow switches (Jason 2026-10-21) --------------------------------
# "What your shop does" (Setup -> Administration): one option key per
# module, read through module_on(). Never set = ON — the same defaulting
# rule as the ticker categories — so no existing book changes until the
# owner flips a switch. Switches hide surfaces only: never records,
# never routes, never money math.
MODULE_NAMES = ("rentals", "work_orders", "compliance", "quotes", "condition",
                "billing")
# The value written into a ticket's condition field when a gate is
# bypassed (Proceed anyway, or the condition switch is off): the record
# shows the decision, never a silent blank. Not a COND_RANK member, so
# it can never be saved as a real condition.
COND_NOT_RECORDED = "Not recorded"

def module_on(con: sqlite3.Connection, name: str) -> bool:
    """True unless the shop explicitly turned this module off."""
    return get_option(con, f"module_{name}", "") != "0"

def set_module(con: sqlite3.Connection, name: str, on: bool) -> None:
    if name not in MODULE_NAMES:
        raise ValueError(f"Unknown module {name}")
    set_option(con, f"module_{name}", "1" if on else "0")

def module_seen(con: sqlite3.Connection, name: str) -> str:
    """ISO date the module's home page was last opened, or '' if never
    (under this build — the discovery nudge baselines on first check)."""
    return get_option(con, f"module_seen_{name}", "")

def stamp_module_seen(con: sqlite3.Connection, name: str) -> None:
    """Record today's date as the module's last-opened day. Writes at
    most once per module per day."""
    today = date.today().isoformat()
    if module_seen(con, name) != today:
        try:
            set_option(con, f"module_seen_{name}", today)
        except Exception:
            pass
def _pbkdf2(secret: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"),
                               salt.encode("utf-8"), 200_000).hex()
def pin_is_set(con: sqlite3.Connection) -> bool:
    return bool(get_option(con, "pin_hash", ""))
def get_pin_secret(con: sqlite3.Connection) -> str:
    """Random per-database secret used to sign PIN session cookies."""
    s = get_option(con, "pin_secret", "")
    if not s:
        s = secrets.token_hex(32)
        set_option(con, "pin_secret", s)
    return s
def set_pin(con: sqlite3.Connection, pin: str) -> None:
    """Set (or replace) the desk PIN. No recovery code (Jason 2026-10-07);
    security questions are the recovery path."""
    pin = (pin or "").strip()
    if not (pin.isdigit() and 4 <= len(pin) <= 8):
        raise ValueError("The PIN must be 4 to 8 digits.")
    salt = secrets.token_hex(16)
    set_option(con, "pin_hash", f"{salt}${_pbkdf2(pin, salt)}")
def verify_pin(con: sqlite3.Connection, pin: str) -> bool:
    stored = get_option(con, "pin_hash", "")
    if not stored or "$" not in stored:
        return False
    salt, want = stored.split("$", 1)
    return hmac.compare_digest(_pbkdf2((pin or "").strip(), salt), want)
def clear_pin(con: sqlite3.Connection) -> None:
    set_option(con, "pin_hash", "")
    set_option(con, "pin_sq1", "")
    set_option(con, "pin_sq1_hash", "")
    set_option(con, "pin_sq2", "")
    set_option(con, "pin_sq2_hash", "")


PIN_SECURITY_QUESTIONS = [
    "What was the name of your first pet?",
    "What street did you grow up on?",
    "What city were you born in?",
    "What was the name of your first employer?",
    "What was your childhood nickname?",
    "What was the name of your favorite teacher?",
    "What was your first car?",
    "What is your favorite movie?",
]


def _sq_norm(answer: str) -> str:
    return " ".join((answer or "").strip().lower().split())


def validate_pin_security(q1: int, a1: str, q2: int, a2: str) -> None:
    """Check two security questions + answers without storing anything.

    Raises ValueError on two identical questions, an unknown question, or
    an empty answer. Call before set_pin so a failed validation never
    leaves a PIN with no recovery questions.
    """
    n = len(PIN_SECURITY_QUESTIONS)
    if not (0 <= q1 < n and 0 <= q2 < n):
        raise ValueError("Pick two security questions from the list")
    if q1 == q2:
        raise ValueError("Pick two different security questions")
    if not _sq_norm(a1) or not _sq_norm(a2):
        raise ValueError("Answer both security questions")


def set_pin_security(con: sqlite3.Connection, q1: int, a1: str,
                     q2: int, a2: str) -> None:
    """Store two security questions + salted-hashed answers for PIN reset.

    Raises ValueError on two identical questions, an unknown question, or
    an empty answer. Called whenever a PIN is set; the answers are the
    fallback when the one-time recovery code is lost.
    """
    validate_pin_security(q1, a1, q2, a2)
    for tag, q, a in (("sq1", q1, a1), ("sq2", q2, a2)):
        salt = secrets.token_hex(16)
        set_option(con, f"pin_{tag}", str(q))
        set_option(con, f"pin_{tag}_hash", f"{salt}${_pbkdf2(_sq_norm(a), salt)}")


def pin_security_is_set(con: sqlite3.Connection) -> bool:
    return bool(get_option(con, "pin_sq1_hash", "") and
                get_option(con, "pin_sq2_hash", ""))


def pin_security_questions(con: sqlite3.Connection) -> tuple:
    """The two stored question indexes (for rendering the reset form)."""
    try:
        return (int(get_option(con, "pin_sq1", "0")),
                int(get_option(con, "pin_sq2", "1")))
    except ValueError:
        return (0, 1)


def verify_pin_security(con: sqlite3.Connection, a1: str, a2: str) -> bool:
    for tag, a in (("sq1", a1), ("sq2", a2)):
        stored = get_option(con, f"pin_{tag}_hash", "")
        if not stored or "$" not in stored:
            return False
        salt, want = stored.split("$", 1)
        if not hmac.compare_digest(_pbkdf2(_sq_norm(a), salt), want):
            return False
    return True
def _new_device_token() -> str:
    import secrets
    return secrets.token_urlsafe(32)
def issue_device(con: sqlite3.Connection, label: str, days: int = 90,
                 clerk: str = "") -> dict:
    """Create a device authorization. Returns the row incl. the secret token."""
    _ensure_device_tables(con)
    label = (label or "").strip()
    if not label:
        raise ValueError("Give the device a name (e.g. Yard tablet 1)")
    try:
        days = int(days)
    except (TypeError, ValueError):
        raise ValueError("Expiry days must be a number")
    if days < 1 or days > 3650:
        raise ValueError("Expiry must be 1–3650 days")
    token = _new_device_token()
    today = date.today()
    expires = (today + timedelta(days=days)).isoformat()
    con.execute(
        "INSERT INTO device_auths(token, label, scope, created_at, created_by, expires_at)"
        " VALUES (?, ?, 'yard', ?, ?, ?)",
        (token, label[:60], today.isoformat(), (clerk or "")[:40], expires),
    )
    con.commit()
    return {"token": token, "label": label[:60], "expires_at": expires}
def list_devices(con: sqlite3.Connection) -> list[dict]:
    _ensure_device_tables(con)
    rows = con.execute(
        "SELECT token, label, created_at, created_by, expires_at, revoked_at,"
        " grace_until, last_seen_at FROM device_auths ORDER BY created_at DESC, label"
    ).fetchall()
    out = []
    today = date.today().isoformat()
    now = datetime.now().isoformat(timespec="seconds")
    for r in rows:
        d = dict(r)
        if d["revoked_at"] and not (d["grace_until"] and d["grace_until"] >= now):
            d["state"] = "revoked"
        elif d["expires_at"] and d["expires_at"] < today:
            d["state"] = "expired"
        elif d["expires_at"]:
            left = (date.fromisoformat(d["expires_at"]) - date.today()).days
            d["state"] = "expiring" if left <= 14 else "active"
            d["days_left"] = left
        else:
            d["state"] = "active"
            d["days_left"] = None
        out.append(d)
    return out
def get_device(con: sqlite3.Connection, token: str) -> dict | None:
    _ensure_device_tables(con)
    r = con.execute("SELECT * FROM device_auths WHERE token=?", (token or "",)).fetchone()
    return dict(r) if r else None
def device_check(con: sqlite3.Connection, token: str) -> tuple[bool, str, dict | None]:
    """(ok, reason, row). Grace window keeps a rotated token alive briefly."""
    d = get_device(con, token)
    if not d:
        return False, "unknown device", None
    now = datetime.now().isoformat(timespec="seconds")
    today = date.today().isoformat()
    if d["revoked_at"] and not (d["grace_until"] and d["grace_until"] >= now):
        return False, "device access revoked", d
    if d["expires_at"] and d["expires_at"] < today:
        return False, "device authorization expired", d
    return True, "ok", d
def touch_device(con: sqlite3.Connection, token: str) -> None:
    _ensure_device_tables(con)
    con.execute(
        "UPDATE device_auths SET last_seen_at=? WHERE token=?",
        (datetime.now().isoformat(timespec="seconds"), token),
    )
    con.commit()
def revoke_device(con: sqlite3.Connection, token: str) -> None:
    _ensure_device_tables(con)
    con.execute(
        "UPDATE device_auths SET revoked_at=?, grace_until=NULL WHERE token=?",
        (datetime.now().isoformat(timespec="seconds"), token),
    )
    con.commit()
def rotate_device(con: sqlite3.Connection, token: str, days: int = 90,
                  clerk: str = "") -> dict:
    """Issue a fresh token for the same label; old token gets a 24h grace."""
    _ensure_device_tables(con)
    d = get_device(con, token)
    if not d:
        raise ValueError("Unknown device")
    new = issue_device(con, d["label"] + " (rotated)" if not d["label"].endswith("(rotated)") else d["label"],
                       days=days, clerk=clerk)
    grace = (datetime.now() + timedelta(hours=DEVICE_GRACE_HOURS)).isoformat(timespec="seconds")
    con.execute(
        "UPDATE device_auths SET revoked_at=?, grace_until=? WHERE token=?",
        (datetime.now().isoformat(timespec="seconds"), grace, token),
    )
    con.commit()
    return new
def _shift_months(d: date, months: float) -> date:
    """Add (possibly fractional) months to a date, clamping the day."""
    whole = int(months)
    frac = months - whole
    m = d.month - 1 + whole
    y = d.year + m // 12
    m = m % 12 + 1
    out = date(y, m, min(d.day, monthrange(y, m)[1]))
    if frac:
        out += timedelta(days=round(frac * 30.44))
    return out
def _pos_or_none(v):
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    f = float(s)
    if f <= 0:
        raise ValueError("Intervals must be positive")
    return f
CENT = Decimal("0.01")
SCHEMA = Path(__file__).resolve().parent / "schema.sql"
SEED_PACKS = Path(__file__).resolve().parent / "seed_packs.sql"
_LOCAL = Path(__file__).resolve().parent / "fleetsheet.db"
_TMP = Path("/tmp/fleetsheet.db")
OPEN_STATUSES = ("Quoted", "Reserved", "Dispatched", "On Rent", "Standby")
BLOCKING = ("Reserved", "Dispatched", "On Rent", "Standby")
ALLOWED_NEXT = {
    "Quoted": ("Reserved", "Void"),
    "Reserved": ("Dispatched", "Quoted", "Void"),
    "Dispatched": ("On Rent", "Standby", "Void"),
    "On Rent": ("Standby", "Off Rent"),
    "Standby": ("On Rent", "Off Rent"),
    "Off Rent": ("Ready to Bill", "On Rent"),
    "Ready to Bill": ("Billed", "Off Rent"),
    "Billed": ("Closed",),
    "Closed": (),
    "Void": (),
}
COND_RANK = {
    "Excellent": 0,
    "Good": 1,
    "Fair": 2,
    "Poor": 3,
    "Damaged": 4,
    "Other / note": 2,
    "Available": 0,
    "Repair — minor": 1,
    "Repair — major": 2,
    "Unusable": 4,
}
# Payment tenders. "Petty cash" is NOT a tender (Jason 2026-10-23,
# petty-cash seal): the petty box is its own universe — no payment
# may claim it as its source, and no route draws on it. Rows already
# recorded with that method keep displaying their stored string.
CASH_METHODS = ("ACH", "Check", "Wire", "Card", "Cash", "Venmo", "Bitcoin", "Traveler's Check", "Other")
QUOTE_NEXT = {
    "Draft": ("Sent", "Void"),
    "Sent": ("Accepted", "Declined", "Expired", "Void"),
    "Accepted": ("Converted", "Void"),
    "Declined": ("Void",),
    "Expired": ("Void",),
    "Converted": (),
    "Void": (),
}
PC_IN_CATS = ("Opening float", "Replenish", "Invoice cash in")
PC_OUT_CATS = ("Fuel", "Parts", "Postage", "Parking", "Tolls", "Meals", "Office", "Tools", "Travel", "Other")
EXPORT_WHENS = ("all", "ytd", "month", "week", "custom")
EXPORT_HOWS = ("csv", "xlsx", "json")
DEVICE_GRACE_HOURS = 24
TRIGGER_LABELS = {
    "per_job": "Per job / pre-mob",
    "per_shift": "Each shift",
    "calendar": "Calendar",
    "event": "On event",
    "manufacturer": "Per manufacturer",
}
BASIS_LABELS = {
    "standard": "Standard",
    "manufacturer": "Manufacturer",
    "company": "Company policy",
}
DUE_SOON_DAYS = 30


# ---------------------------------------------------------------------------
# Backups: dated archives of the book (database + ticket photos), downloads,
# validated restore, retention.
# ---------------------------------------------------------------------------
BACKUP_KEEP = 14  # how many dated archives the folder keeps
_BACKUP_NAME_RE = re.compile(r"^fleetsheet-\d{4}-\d{2}-\d{2}-\d{4}(-\d+)?\.db$")
_ARCHIVE_NAME_RE = re.compile(r"^fleetsheet-\d{4}-\d{2}-\d{2}-\d{4}(-\d+)?\.zip$")
ARCHIVE_FORMAT = 1  # manifest format version inside backup archives
# Tables that must exist for an upload to count as a FleetSheet book.
_BACKUP_REQUIRED_TABLES = ("company", "assets", "tickets", "invoices", "customers")


def _live_db_path() -> Path:
    env = os.environ.get("FLEETSHEET_DB")
    return Path(env) if env else _LOCAL


def backup_folder(con) -> Path:
    row = con.execute("SELECT backup_dir FROM company WHERE id=1").fetchone()
    raw = ""
    try:
        raw = (row["backup_dir"] or "").strip() if row else ""
    except Exception:
        raw = ""
    p = Path(raw).expanduser() if raw else (_live_db_path().parent / "backups")
    return p


def set_backup_dir(con, path: str) -> None:
    raw = (path or "").strip()
    con.execute("UPDATE company SET backup_dir=? WHERE id=1", (raw,))
    con.commit()


_BACKUP_SCHEDULES = ("nightly", "weekly", "monthly", "custom", "never")

_BACKUP_SCHEDULE_DAYS = {"nightly": 1, "weekly": 7, "monthly": 30}


def get_backup_schedule(con) -> tuple:
    """Return (schedule, every_days) for automatic backups.

    schedule is one of: nightly, weekly, monthly, custom, never.
    every_days applies to the custom schedule (1-365). (2026-10-06)
    """
    try:
        row = con.execute(
            "SELECT backup_schedule, backup_every_days FROM company WHERE id=1"
        ).fetchone()
    except Exception:
        return ("weekly", 7)
    if not row:
        return ("weekly", 7)
    sched = (row["backup_schedule"] or "weekly").strip().lower()
    if sched not in _BACKUP_SCHEDULES:
        sched = "weekly"
    try:
        days = int(row["backup_every_days"] or 7)
    except (TypeError, ValueError):
        days = 7
    days = max(1, min(365, days))
    return (sched, days)


def set_backup_schedule(con, schedule, every_days=7) -> None:
    """Save the automatic backup schedule. Raises ValueError on bad input."""
    sched = (schedule or "").strip().lower()
    if sched not in _BACKUP_SCHEDULES:
        raise ValueError("Unknown backup schedule")
    try:
        days = int(every_days or 7)
    except (TypeError, ValueError):
        raise ValueError("Days must be a number")
    if sched == "custom" and not 1 <= days <= 365:
        raise ValueError("Days must be between 1 and 365")
    con.execute(
        "UPDATE company SET backup_schedule=?, backup_every_days=? WHERE id=1",
        (sched, max(1, min(365, days))),
    )


def backup_status(con) -> dict:
    sched, every_days = get_backup_schedule(con)
    stale_after = (
        _BACKUP_SCHEDULE_DAYS.get(sched)
        if sched != "custom" else every_days
    )
    row = con.execute("SELECT last_backup FROM company WHERE id=1").fetchone()
    last = ""
    try:
        last = (row["last_backup"] or "") if row else ""
    except Exception:
        last = ""
    folder = str(backup_folder(con))
    stale = False
    age_days = None
    if sched != "never":
        stale = True
        if last:
            dt = _parse(last[:10])
            if dt:
                age_days = (date.today() - dt).days
                stale = age_days > (stale_after or 7)
    return {"last": last[:16] if last else "", "folder": folder,
            "stale": stale, "age_days": age_days,
            "schedule": sched, "every_days": every_days}


def _backup_name_ok(name: str) -> bool:
    return bool(_BACKUP_NAME_RE.match(name or ""))


def _archive_name_ok(name: str) -> bool:
    return bool(_ARCHIVE_NAME_RE.match(name or ""))


def _archive_manifest(archive: Path) -> dict | None:
    """Read the manifest from a backup archive; None if unreadable."""
    try:
        with zipfile.ZipFile(archive) as z:
            return json.loads(z.read("manifest.json").decode("utf-8"))
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError, zipfile.BadZipFile):
        return None


def list_backups(con) -> list:
    """Dated backups in the backup folder, newest first.

    New archives (.zip: book + photos + manifest) and legacy db-only
    copies (.db) are both listed; each row carries its kind.
    """
    folder = backup_folder(con)
    out = []
    try:
        names = os.listdir(folder)
    except OSError:
        return out
    for name in names:
        if _archive_name_ok(name):
            kind = "archive"
        elif _backup_name_ok(name):
            kind = "legacy"
        else:
            continue
        p = folder / name
        try:
            st = p.stat()
        except OSError:
            continue
        photos = None
        docs = None
        if kind == "archive":
            m = _archive_manifest(p)
            if isinstance(m, dict):
                try:
                    photos = int(m.get("photo_count", 0))
                except (TypeError, ValueError):
                    photos = None
                try:
                    docs = int(m.get("doc_count", 0))
                except (TypeError, ValueError):
                    docs = None
        out.append({"name": name, "size": st.st_size,
                    "mtime": datetime.fromtimestamp(st.st_mtime),
                    "kind": kind, "photos": photos, "docs": docs})
    out.sort(key=lambda b: b["mtime"], reverse=True)
    return out


def prune_backups(con, keep: int = BACKUP_KEEP) -> int:
    """Delete dated copies beyond the newest `keep`. Returns count removed."""
    olds = list_backups(con)[keep:]
    folder = backup_folder(con)
    n = 0
    for b in olds:
        try:
            (folder / b["name"]).unlink()
            n += 1
        except OSError:
            pass
    return n


def run_backup(con, clerk: str = "") -> Path:
    """Write a dated backup archive: the book plus every ticket photo and
    every data-book document.

    The archive is one self-contained .zip (fleetsheet.db + photos/ +
    docs/ + manifest.json with SHA-256 hashes), so a downloaded backup is
    a complete copy — no separate folder to remember. Returns the archive
    path.
    """
    who = require_clerk(clerk)
    folder = backup_folder(con)
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise ValueError(f"Cannot create backup folder: {folder}") from e
    if not folder.is_dir():
        raise ValueError(f"{folder} is not a folder")
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    dest = folder / f"fleetsheet-{stamp}.zip"
    n = 2
    while dest.exists():
        dest = folder / f"fleetsheet-{stamp}-{n}.zip"
        n += 1
    if dest.resolve() == _live_db_path().resolve():
        raise ValueError("Backup folder cannot be the live book")
    # Consistent point-in-time copy of the book via the backup API.
    tmp_db = Path(tempfile.gettempdir()) / (
        f"fleetsheet-snap-{os.getpid()}-{secrets.token_hex(4)}.db")
    snap = sqlite3.connect(tmp_db)
    try:
        con.backup(snap)
    finally:
        snap.close()
    try:
        db_bytes = tmp_db.read_bytes()
        photos = []
        pdir = photo_dir()
        for p in sorted(pdir.iterdir()):
            if not p.is_file():
                continue
            if not safe_photo_name(p.name):
                continue
            blob = p.read_bytes()
            photos.append({
                "path": f"photos/{p.name}",
                "sha256": hashlib.sha256(blob).hexdigest(),
                "bytes": len(blob),
            })
        docs = []
        ddir = doc_dir()
        for p in sorted(ddir.iterdir()):
            if not p.is_file():
                continue
            if not safe_doc_name(p.name):
                continue
            blob = p.read_bytes()
            docs.append({
                "path": f"docs/{p.name}",
                "sha256": hashlib.sha256(blob).hexdigest(),
                "bytes": len(blob),
            })
        manifest = {
            "format": ARCHIVE_FORMAT,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "created_by": who,
            "db_sha256": hashlib.sha256(db_bytes).hexdigest(),
            "db_size": len(db_bytes),
            "photo_count": len(photos),
            "photos": photos,
            "doc_count": len(docs),
            "docs": docs,
        }
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("fleetsheet.db", db_bytes)
            for ph in photos:
                z.write(pdir / Path(ph["path"]).name, ph["path"])
            for dh in docs:
                z.write(ddir / Path(dh["path"]).name, dh["path"])
            z.writestr("manifest.json",
                       json.dumps(manifest, indent=1).encode("utf-8"))
    finally:
        try:
            tmp_db.unlink()
        except OSError:
            pass
    when = datetime.now().strftime("%Y-%m-%d %H:%M")
    note = folder / "fleetsheet-last-backup.txt"
    try:
        note.write_text(f"{when}\n{dest.name}\nby {who}\n", encoding="utf-8")
    except OSError:
        pass
    con.execute("UPDATE company SET last_backup=? WHERE id=1", (when,))
    con.commit()
    prune_backups(con)
    return dest


def read_backup_file(con, name: str) -> bytes:
    """Read one dated backup (archive or legacy db-only). The name must match
    the strict backup pattern — no paths, no surprises. Raises ValueError."""
    if not (_archive_name_ok(name) or _backup_name_ok(name)):
        raise ValueError("Unknown backup file")
    p = backup_folder(con) / name
    if not p.is_file():
        raise ValueError("Unknown backup file")
    return p.read_bytes()


def _check_book_db(path) -> dict:
    """Check a database file is a healthy FleetSheet book. Raises ValueError."""
    p = Path(path)
    with open(p, "rb") as f:
        if f.read(16) != b"SQLite format 3\x00":
            raise ValueError("That file is not a SQLite database")
    uri = "file:" + str(p.resolve()) + "?mode=ro"
    db = sqlite3.connect(uri, uri=True)
    try:
        tables = {r[0] for r in
                  db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = [t for t in _BACKUP_REQUIRED_TABLES if t not in tables]
        if missing:
            raise ValueError(
                "That database is not a FleetSheet book "
                f"(missing: {', '.join(missing)})")
        cell = db.execute("PRAGMA integrity_check").fetchone()
        if not cell or cell[0] != "ok":
            raise ValueError(
                f"Database integrity check failed: {cell[0] if cell else '?'}")
    finally:
        db.close()
    return {"tables": len(tables), "size": p.stat().st_size}


def validate_backup_file(path) -> dict:
    """Check an uploaded legacy .db file is a healthy FleetSheet book.
    Raises ValueError."""
    p = Path(path)
    if not p.is_file():
        raise ValueError("Upload is not a file")
    return _check_book_db(p)


def validate_backup_archive(path) -> dict:
    """Check an uploaded backup archive before anything is restored.

    Verifies: it is a zip, names are safe (no traversal), the manifest is
    present and well-formed, every photo and every data-book document in
    the manifest is present with a matching SHA-256, and the bundled
    database is a healthy FleetSheet book. Raises ValueError on the first
    problem found. Returns a summary dict on success.
    """
    p = Path(path)
    if not p.is_file():
        raise ValueError("Upload is not a file")
    if not zipfile.is_zipfile(p):
        raise ValueError("That file is not a backup archive (.zip)")
    with zipfile.ZipFile(p) as z:
        names = z.namelist()
        bad = [n for n in names
               if n.startswith("/") or ".." in n.split("/") or n.startswith("\\")]
        if bad:
            raise ValueError("Backup archive contains unsafe file names")
        if "fleetsheet.db" not in names or "manifest.json" not in names:
            raise ValueError("That archive is not a FleetSheet backup")
        try:
            manifest = json.loads(z.read("manifest.json").decode("utf-8"))
        except Exception:
            raise ValueError("Backup archive manifest is unreadable") from None
        if not isinstance(manifest, dict) or manifest.get("format") != ARCHIVE_FORMAT:
            raise ValueError("Backup archive format is not recognized")
        photos = manifest.get("photos")
        if not isinstance(photos, list):
            raise ValueError("Backup archive manifest is corrupt")
        docs = manifest.get("docs", [])
        if not isinstance(docs, list):
            raise ValueError("Backup archive manifest is corrupt")
        seen = set()
        for ph in photos:
            if not isinstance(ph, dict):
                raise ValueError("Backup archive manifest is corrupt")
            rel = ph.get("path") or ""
            if not rel.startswith("photos/") or "/" in rel[7:] or rel in seen:
                raise ValueError("Backup archive manifest is corrupt")
            seen.add(rel)
            if rel not in names:
                raise ValueError(f"Backup archive is missing photo {rel[7:]}")
            blob = z.read(rel)
            if hashlib.sha256(blob).hexdigest() != ph.get("sha256"):
                raise ValueError(f"Photo {rel[7:]} failed its integrity check")
            if len(blob) != ph.get("bytes"):
                raise ValueError(f"Photo {rel[7:]} has the wrong size")
        for dh in docs:
            if not isinstance(dh, dict):
                raise ValueError("Backup archive manifest is corrupt")
            rel = dh.get("path") or ""
            if not rel.startswith("docs/") or "/" in rel[5:] or rel in seen:
                raise ValueError("Backup archive manifest is corrupt")
            seen.add(rel)
            if rel not in names:
                raise ValueError(f"Backup archive is missing document {rel[5:]}")
            blob = z.read(rel)
            if hashlib.sha256(blob).hexdigest() != dh.get("sha256"):
                raise ValueError(f"Document {rel[5:]} failed its integrity check")
            if len(blob) != dh.get("bytes"):
                raise ValueError(f"Document {rel[5:]} has the wrong size")
        tmp = Path(tempfile.gettempdir()) / (
            f"fleetsheet-validate-{os.getpid()}-{secrets.token_hex(4)}.db")
        tmp.write_bytes(z.read("fleetsheet.db"))
        try:
            dbinfo = _check_book_db(tmp)
        finally:
            try:
                tmp.unlink()
            except OSError:
                pass
    try:
        photo_count = int(manifest.get("photo_count", len(photos)))
    except (TypeError, ValueError):
        photo_count = len(photos)
    try:
        doc_count = int(manifest.get("doc_count", len(docs)))
    except (TypeError, ValueError):
        doc_count = len(docs)
    return {"photo_count": photo_count, "doc_count": doc_count,
            "db_size": dbinfo["size"],
            "created_at": str(manifest.get("created_at") or ""),
            "created_by": str(manifest.get("created_by") or "")}


def _swap_live_dir(live_dir: Path, staged_dir: Path, label: str) -> None:
    """Atomically-ish swap a live data folder with a staged one.

    The current folder is renamed aside, the staged folder takes its
    place, and the old folder is removed only after the swap succeeds.
    On failure the previous folder is rolled back. Raises ValueError.
    """
    prev = live_dir.parent / (
        f"{live_dir.name}-prev-" + datetime.now().strftime("%Y%m%d%H%M%S"))
    if live_dir.exists() or live_dir.is_symlink():
        live_dir.rename(prev)
    else:
        prev = None
    try:
        if staged_dir.is_dir():
            staged_dir.rename(live_dir)
        else:
            live_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        try:
            if live_dir.exists() or live_dir.is_symlink():
                if live_dir.is_dir() and not live_dir.is_symlink():
                    shutil.rmtree(live_dir)
                else:
                    live_dir.unlink()
            if prev is not None:
                prev.rename(live_dir)
        except OSError:
            pass
        raise ValueError(
            f"Book restored but {label} could not be swapped; "
            "the previous files were kept in place")
    if prev is not None:
        shutil.rmtree(prev, ignore_errors=True)


def restore_backup(con, src, clerk: str = "") -> Path:
    """Replace the live book with a validated backup file.

    Takes a safety snapshot of the current book first, so a bad restore
    can itself be restored. Returns the safety snapshot path.

    The upload is copied INTO the live connection with SQLite's backup
    API rather than swapping the file on disk: the server (and any yard
    phone) may hold other connections open, and replacing the file under
    them invalidates WAL shared memory and causes I/O errors.
    """
    who = require_clerk(clerk)
    info = validate_backup_file(src)  # raises before anything is touched
    live = _live_db_path()
    if Path(src).resolve() == live.resolve():
        raise ValueError("That file is already the live book")
    snap = run_backup(con, f"{who} (pre-restore)")
    srcdb = sqlite3.connect("file:" + str(Path(src).resolve()) + "?mode=ro",
                            uri=True)
    try:
        srcdb.backup(con)
    finally:
        srcdb.close()
    try:
        con.commit()
    except sqlite3.Error:
        pass
    return snap


def restore_backup_archive(con, src, clerk: str = "") -> Path:
    """Replace the live book, the ticket photos, AND the data-book
    documents from a backup archive.

    The archive is fully validated before anything is touched. A safety
    snapshot of the current book is taken first, so a bad restore can
    itself be restored. Returns the safety snapshot path.

    The database is copied INTO the live connection with SQLite's backup
    API rather than swapping the file on disk (the server may hold other
    connections open; replacing the file under them invalidates WAL shared
    memory and causes I/O errors). Photo and document files are only ever
    read, never held open, so those directories are swapped on disk with
    rollback kept until each swap succeeds.
    """
    who = require_clerk(clerk)
    info = validate_backup_archive(src)  # raises before anything is touched
    live = _live_db_path()
    if Path(src).resolve() == live.resolve():
        raise ValueError("That file is already the live book")
    snap = run_backup(con, f"{who} (pre-restore)")
    stage = Path(tempfile.mkdtemp(prefix="fleetsheet-restore-"))
    try:
        with zipfile.ZipFile(src) as z:
            z.extractall(stage)
        srcdb = sqlite3.connect(
            "file:" + str((stage / "fleetsheet.db").resolve()) + "?mode=ro",
            uri=True)
        try:
            srcdb.backup(con)
        finally:
            srcdb.close()
        try:
            con.commit()
        except Exception:
            pass
        _swap_live_dir(live.parent / "photos", stage / "photos", "photos")
        _swap_live_dir(live.parent / "docs", stage / "docs", "documents")
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return snap


def sweep_orphan_photos(con) -> int:
    """Delete photo files no ticket references anymore. Returns count removed.

    Only files matching this app's own photo-name pattern are ever
    deleted; anything foreign in the folder is left alone.
    """
    keep = set()
    for col in ("out_photo", "in_photo"):
        try:
            rows = con.execute(
                f"SELECT {col} FROM tickets WHERE {col} IS NOT NULL AND {col} != ''")
        except Exception:
            continue
        for (name,) in rows:
            s = safe_photo_name(name)
            if s:
                keep.add(s)
    d = photo_dir()
    n = 0
    try:
        entries = list(d.iterdir())
    except OSError:
        return 0
    for p in entries:
        if not p.is_file() or p.name in keep:
            continue
        if not safe_photo_name(p.name):
            continue
        try:
            p.unlink()
            n += 1
        except OSError:
            pass
    return n

# ---------------------------------------------------------------------------
# Ticket condition photos (real image uploads: JPG / PNG / WebP)
# ---------------------------------------------------------------------------
PHOTO_MAX_BYTES = 10 * 1024 * 1024
PHOTO_EXTS = {".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
_PHOTO_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*\.(jpg|png|webp)$")

def photo_dir() -> Path:
    """Folder holding ticket photos; sits next to the live book file."""
    d = _live_db_path().parent / "photos"
    d.mkdir(parents=True, exist_ok=True)
    return d

def photo_ext_for(blob: bytes) -> str | None:
    """Sniff the image type from magic bytes. Returns '.jpg' / '.png' / '.webp' or None."""
    if len(blob) >= 3 and blob[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if len(blob) >= 8 and blob[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if len(blob) >= 12 and blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
        return ".webp"
    return None


def validate_photo_blob(blob: bytes) -> str:
    """Validate an uploaded photo before anything is stored or committed.

    Checks the size cap, sniffs the type from magic bytes, then actually
    decodes the image (Pillow) so truncated or malformed files are rejected
    here — not after the ticket condition has been committed. Returns the
    file extension ('.jpg' / '.png' / '.webp'). Raises ValueError.
    """
    if not blob:
        raise ValueError("Empty photo upload")
    if len(blob) > PHOTO_MAX_BYTES:
        raise ValueError("Photo is too large (10 MB max)")
    ext = photo_ext_for(blob)
    if not ext:
        raise ValueError("Photo must be a JPG, PNG, or WebP image")
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(blob))
        img.verify()
    except Exception:
        raise ValueError("That photo file is damaged and cannot be read") from None
    return ext

def safe_photo_name(name: str | None) -> str | None:
    """Accept only names matching the pattern this app generates (blocks traversal)."""
    if name and _PHOTO_NAME_RE.match(name):
        return name
    return None


# Unit data-book documents (certs, one-line drawings, instructions, test
# records — PDFs, images, and plain text). Stored in a docs/ folder next to
# the live book; every file rides inside the backup archive like photos do.
# ---------------------------------------------------------------------------
DOC_MAX_BYTES = 25 * 1024 * 1024
DOC_KINDS = {
    "cert": "Certification",
    "drawing": "Drawing / schematic",
    "instruction": "Instructions",
    "test": "Test record",
    "other": "Other",
}
_DOC_MIMES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".txt": "text/plain",
    ".csv": "text/csv",
}
_DOC_NAME_RE = re.compile(
    r"^doc-[0-9]{14,26}-[0-9a-f]{8}\.(pdf|png|jpe?g|webp|txt|csv)$")


def doc_dir() -> Path:
    """Folder holding data-book documents; sits next to the live book file."""
    d = _live_db_path().parent / "docs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def doc_ext_for(blob: bytes) -> str | None:
    """Sniff the document type from magic bytes. Returns an extension or None."""
    if len(blob) >= 5 and blob[:5] == b"%PDF-":
        return ".pdf"
    ext = photo_ext_for(blob)
    if ext:
        return ext
    # Plain text (txt/csv): must decode as UTF-8 and be mostly printable.
    if blob and len(blob) >= 1:
        try:
            text = blob.decode("utf-8")
        except UnicodeDecodeError:
            return None
        if text and not any(c in text for c in ("\x00",)):
            sample = text[:4000]
            printable = sum(1 for c in sample if c.isprintable() or c in "\r\n\t")
            if len(sample) and printable / len(sample) > 0.95:
                return ".txt"
    return None


def validate_doc_blob(blob: bytes, filename: str = "") -> tuple:
    """Validate an uploaded data-book document before anything is stored.

    Size cap, magic-byte type sniff (PDF / image / text only — never
    executables), and a real decode for images. Returns (ext, mime).
    Raises ValueError.
    """
    if not blob:
        raise ValueError("Empty document upload")
    if len(blob) > DOC_MAX_BYTES:
        raise ValueError("Document is too large (25 MB max)")
    ext = doc_ext_for(blob)
    if not ext:
        raise ValueError("Document must be a PDF, an image (JPG/PNG/WebP), "
                         "or plain text")
    # Prefer the upload's own extension for .csv (sniffed as text).
    up = (filename or "").lower()
    if ext == ".txt" and up.endswith(".csv"):
        ext = ".csv"
    if ext in (".jpg", ".jpeg", ".png", ".webp"):
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(blob))
            img.verify()
        except Exception:
            raise ValueError("That image file is damaged and cannot be read") from None
    return ext, _DOC_MIMES[ext]


def safe_doc_name(name: str | None) -> str | None:
    """Accept only names matching the pattern this app generates (blocks traversal)."""
    if name and _DOC_NAME_RE.match(name):
        return name
    return None


def _new_doc_name(ext: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    return f"doc-{stamp}-{secrets.token_hex(4)}{ext}"


def save_unit_doc(con: sqlite3.Connection, asset_id: str, title: str,
                  kind: str, filename: str, blob: bytes, clerk: str = "") -> int:
    """Validate, store, and register a data-book document. Returns doc_id."""
    title = (title or "").strip()
    if not title:
        raise ValueError("Give the document a title")
    # Global dropdown rule (Issue 4): any non-empty kind string is kept
    # as-is — the Upload Certificate form submits cert kinds (e.g. "VAUT")
    # through this path. Empty still defaults to "other". The -Add-
    # sentinel is never a value.
    kind = (kind or "").strip()
    if kind == "__add__":
        kind = ""
    kind = kind or "other"
    unit = con.execute("SELECT asset_id FROM assets WHERE asset_id=?",
                       (asset_id,)).fetchone()
    if not unit:
        raise ValueError("Unknown unit")
    akey = asset_key(con, asset_id)
    ext, mime = validate_doc_blob(blob, filename)
    stored = _new_doc_name(ext)
    d = doc_dir()
    target = d / stored
    n = 2
    while target.exists():
        target = d / f"{stored[:-len(ext)]}-{n}{ext}"
        stored = target.name
        n += 1
    target.write_bytes(blob)
    cur = con.execute(
        """INSERT INTO unit_docs
           (asset_id, title, kind, filename, stored, bytes, mime, clerk)
           VALUES (?,?,?,?,?,?,?,?)""",
        (akey, title, kind, (filename or stored)[:120], stored,
         len(blob), mime, clerk or ""),
    )
    con.commit()
    return cur.lastrowid


def save_job_attachment(con: sqlite3.Connection, ref_type: str, ref_id: str,
                          filename: str, blob: bytes, clerk: str = "") -> str:
    """Save a catch-all job info attachment. Returns stored filename.

    The stored name carries the document's DISPLAY number
    (``<ref>_<number>_<timestamp>_<filename>``): numbers are permanent,
    so the name keeps resolving after the build-'v' re-key — the
    listers (print pack, Job Info popups) scan the docs folder by that
    number prefix. The attachment event lands in the app's real Done
    record (done_manual, via engine_today.add_done_manual) — the old
    insert targeted a done_log table that never existed and its
    failure was swallowed, so attachments used to leave no record."""
    from datetime import datetime
    import re
    safe = re.sub(r'[^a-zA-Z0-9._-]', '_', filename or "upload")[:80]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    stored = f"{ref_type}_{ref_id}_{ts}_{safe}"
    d = doc_dir()
    target = d / stored
    n = 2
    while target.exists():
        target = d / f"{ref_type}_{ref_id}_{ts}_{n}_{safe}"
        stored = target.name
        n += 1
    target.write_bytes(blob)
    # Log it — in the real Done record.
    try:
        from engine_today import add_done_manual
        _links = {
            "ticket": f"/ticket/{ref_id}",
            "wo": f"/summary/wo/{ref_id}",
            "invoice": f"/invoice/{ref_id}",
            "sale": f"/sale/{ref_id}",
            "quote": f"/summary/quote/{ref_id}",
            "change": f"/summary/change/{ref_id}",
            "credit": f"/summary/credit/{ref_id}",
            "pay": f"/summary/payment/{ref_id}",
        }
        add_done_manual(con, f"Attached {safe}",
                        _links.get(ref_type, ""), clerk or "")
    except Exception:
        pass
    return stored


def list_unit_docs(con: sqlite3.Connection, asset_id: str) -> list:
    rows = con.execute(
        """SELECT doc_id, asset_id, title, kind, filename, stored, bytes,
                  mime, uploaded_at, clerk
           FROM unit_docs WHERE asset_id=? ORDER BY uploaded_at, doc_id""",
        (asset_key(con, asset_id),)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["asset_id"] = asset_code(con, d["asset_id"])
        out.append(d)
    return out


def get_unit_doc(con: sqlite3.Connection, doc_id: int) -> dict | None:
    r = con.execute(
        """SELECT doc_id, asset_id, title, kind, filename, stored, bytes,
                  mime, uploaded_at, clerk
           FROM unit_docs WHERE doc_id=?""", (doc_id,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["asset_id"] = asset_code(con, d["asset_id"])
    return d


def read_unit_doc(con: sqlite3.Connection, doc_id: int):
    """Return (row dict, bytes) for a stored document, or None."""
    row = get_unit_doc(con, doc_id)
    if not row:
        return None
    name = safe_doc_name(row["stored"])
    if not name:
        return None
    p = doc_dir() / name
    if not p.is_file():
        return None
    return row, p.read_bytes()


def delete_unit_doc(con: sqlite3.Connection, doc_id: int) -> bool:
    """Remove a document's row and its file. Returns True if one existed."""
    row = get_unit_doc(con, doc_id)
    if not row:
        return False
    con.execute("DELETE FROM unit_docs WHERE doc_id=?", (doc_id,))
    con.commit()
    name = safe_doc_name(row["stored"])
    if name:
        try:
            (doc_dir() / name).unlink()
        except OSError:
            pass
    return True


def sweep_orphan_docs(con: sqlite3.Connection) -> int:
    """Delete doc files no docs table references anymore. Returns count."""
    keep = set()
    for _tbl in ("unit_docs", "invoice_docs"):
        try:
            rows = con.execute(f"SELECT stored FROM {_tbl}")
        except sqlite3.Error:
            rows = []
        for (name,) in rows:
            s = safe_doc_name(name)
            if s:
                keep.add(s)
    d = doc_dir()
    n = 0
    try:
        entries = list(d.iterdir())
    except OSError:
        return 0
    for p in entries:
        if not p.is_file() or p.name in keep:
            continue
        if not safe_doc_name(p.name):
            continue
        try:
            p.unlink()
            n += 1
        except OSError:
            pass
    return n


