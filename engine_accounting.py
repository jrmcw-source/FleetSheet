"""All money and status rules live here. The UI never computes them."""
from __future__ import annotations
import sqlite3
from calendar import monthrange
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from pathlib import Path
import secrets

from engine_core import (
    _money,
    _mf,
    _ms,
    ttl_cached,
    parse_date,
    _parse,
    terms_days,
    format_phone_number,
    _row_get,
    require_clerk,
    validate_new_doc_no,
    key_of,
    num_of,
    doc_key,
    doc_num,
    cust_key,
    cust_code,
    asset_code,
    site_code,
    _next_pay_key,
    pay_key_of,
    pay_id_of,
    list_crew,
    add_crew,
    drop_crew,
    _reserve_counter,
    _next_doc,
    _set_quote_link,
    lookups,
    clean_line_type,
    uom_to_rate_type,    clean_line_uom,
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

from engine_assets import create_ticket, ticket_money, clean_rate_unit, RATE_UNITS, rentable_or_raise

"""FleetSheet engine: accounting flow — quotes, invoices, payments, credit memos, petty cash, exports, revenue reports."""

__all__ = ['next_invoice_id', 'create_invoice', 'invoice_has_lines', '_next_pay_id', '_refresh_invoice_status', 'record_payment', 'next_batch_id', 'next_cm_id', 'credit_applied', 'credit_open', 'credit_lines', '_apply_credit_rows', 'issue_credit_memo', 'apply_open_credit', 'list_open_credits', 'list_open_invoices', 'big_fish_invoices', 'next_quote_id', 'next_co_id', '_line_amount', 'save_quote', 'set_quote_status', 'issue_change_order', 'save_change_order', 'change_order_assoc', 'associated_change_orders', 'record_doc_payment', 'apply_doc_credit', 'doc_total', 'doc_balance', 'doc_settled', 'doc_line_states', 'set_doc_line_note', 'doc_has_line_allocations', 'PAYABLE_KINDS', 'DOC_LABELS', 'quote_totals', 'quote_pack', 'convert_quote', 'next_pc_id', 'petty_balance', 'petty_book', 'set_pc_float', 'record_petty', 'CASH_ENTRY_METHODS', 'record_cash_entry', 'list_cash_entries', 'invoice_line_states', 'invoice_has_line_allocations', 'list_payment_allocations', 'set_invoice_line_note', 'invoice_totals', 'invoice_totals_batch', 'invoice_balance', 'invoice_locked', 'set_invoice_po', 'upsert_po_record', 'po_record', 'backfill_po_records', 'po_check', 'quote_check',
 'save_invoice_doc', 'get_invoice_doc', 'read_invoice_doc', 'delete_invoice_doc', 'set_invoice_doc_print', 'list_invoice_docs', 'invoice_job_box', 'INV_DOC_KINDS', 'add_invoice_line', 'drop_invoice_line', 'PO_STATUSES', '_ensure_saved_exports', 'list_saved_exports', 'save_export', 'delete_saved_export', 'next_customer_id', 'save_customer', 'report_invoicing', 'report_revenue', 'report_recap']

# PO register status (Batch 3 #15): a stored, operator-set value —
# never derived from totals or lines. "Open" until the operator marks
# the PO "Paid in full" on the invoice PO form.
PO_STATUSES = ("Open", "Paid in full")


def next_invoice_id(con: sqlite3.Connection) -> str:
    prefix = con.execute("SELECT invoice_prefix FROM company WHERE id=1").fetchone()[0]
    while True:
        n = _reserve_counter(con, "next_invoice", 1001)
        ino = f"{prefix}-{n}"
        if not con.execute("SELECT 1 FROM invoices WHERE invoice_no=?", (ino,)).fetchone():
            return ino
def _wo_lines_for_invoice(con: sqlite3.Connection, wo_key):
    """wo_lines for invoice expansion, without importing engine_assets
    (circular). Empty when the table doesn't exist yet (pre-migration) —
    the caller falls back to the legacy one-line-per-WO insert."""
    try:
        return con.execute(
            "SELECT * FROM wo_lines WHERE wo_id=? ORDER BY line_id",
            (wo_key,)).fetchall()
    except sqlite3.Error:
        return []


def create_invoice(con: sqlite3.Connection, customer_id: str, ticket_ids: list[str], inv_date: str|None=None, wo_ids: list[str]|None=None, quote_no: str|None=None, po: str|None=None, po_expire: str|None=None, po_cost_code: str|None=None, po_notes: str|None=None, terms: str|None=None, skip_condition: bool=False, invoice_no: str|None=None) -> str:
    ticket_ids=list(dict.fromkeys(ticket_ids or [])); wo_ids=list(dict.fromkeys(wo_ids or []))
    if not ticket_ids and not wo_ids and not customer_id:
        raise ValueError("Pick a customer")
    # Standalone invoice is legal: no ticket, no work order, no quote. The
    # chain is a chain, not a cage — an invoice alone must always be possible.
    ts=[]; ws=[]
    ckey = cust_key(con, customer_id) if customer_id else None
    for tid in ticket_ids:
        t=con.execute("SELECT * FROM tickets WHERE ticket_id=?",(tid,)).fetchone()
        if not t: raise ValueError(f"Unknown rental ticket {tid}")
        if t["customer_id"]!=ckey: raise ValueError(f"{tid} belongs to another customer")
        if t["invoice_id"]: raise ValueError(f"{tid} already belongs to {doc_num(con, 'invoices', t['invoice_id'])}")
        if t["status"] not in ("Ready to Bill","Off Rent"): raise ValueError(f"{tid} is {t['status']} — a rental ticket bills only from Ready to Bill or Off Rent")
        # Check-in condition gate (shop-flow ruling, Jason 2026-10-21):
        # skip_condition is set by the caller when the condition switch
        # is off, or the operator chose "Proceed anyway" on the form.
        # A bypassed ticket gets COND_NOT_RECORDED stamped below, when
        # it is marked Billed — the decision on the record.
        if not t["in_condition"] and not skip_condition: raise ValueError(f"{tid} has no check-in condition")
        ts.append(t)
    for wid in wo_ids:
        w=con.execute("SELECT * FROM work_orders WHERE wo_id=?",(wid,)).fetchone()
        if not w: raise ValueError(f"Unknown work order {wid}")
        if w["customer_id"]!=ckey: raise ValueError(f"{wid} belongs to another customer")
        if w["charge_to"]!="customer" or w["status"]!="Complete" or _money(w["bill_amount"])<=0: raise ValueError(f"{wid} is not a completed billable work order")
        if w["invoice_id"]: raise ValueError(f"{wid} already on {doc_num(con, 'invoices', w['invoice_id'])}")
        ws.append(w)
    terms=(terms or "").strip() or con.execute("SELECT terms FROM customers WHERE id=?",(ckey,)).fetchone()["terms"]
    _custom_ino = (invoice_no or "").strip()
    ino = (validate_new_doc_no(con, "invoices", "invoice_no", _custom_ino, "invoice")
           if _custom_ino else next_invoice_id(con))
    d=inv_date or date.today().isoformat(); qn=(quote_no or "").strip() or None
    if qn:
        q=con.execute("SELECT customer_id,status FROM quotes WHERE quote_no=?",(qn,)).fetchone()
        if not q: raise ValueError("Unknown quote")
        if q["customer_id"]!=ckey: raise ValueError("Quote belongs to another customer")
        if q["status"]=="Void": raise ValueError("Cannot bill a void quote")
    try:
        _icur = con.execute("INSERT INTO invoices(invoice_no,invoice_date,customer_id,terms,status,quote_id,po,po_expire,po_cost_code,po_notes) VALUES (?,?,?,?,?,?,?,?,?,?)",(ino,d,ckey,terms,"Ready",key_of(con, "quotes", qn) if qn else None,(po or "").strip() or None,(po_expire or "").strip() or None,(po_cost_code or "").strip() or None,(po_notes or "").strip() or None))
        ikey = _icur.lastrowid
        # Universality carry (Jason 2026-10-23): each source line maps
        # to the invoice line it becomes (invoice_lines.source_line_id),
        # and each source's invoice-line total is tracked, so money
        # already settled against a ticket or work order can be
        # mirrored onto this invoice below — exactly once.
        _src_line_map: dict = {}
        _src_totals: dict = {}
        for t in ts:
            m=ticket_money(con,t["ticket_id"])
            desc=f"{t['ticket_id']} — {m['unit_no']} {m['description'] or ''}".strip()
            if t["rate_type"]=="Hour" and m.get("hours",0)>0:
                desc=f"{desc} — {m['hours']:g} hrs @ ${m['rate']:,.2f}/hr"
            # One invoice line per ticket line (2026-10-23): the invoice
            # carries the ticket's lines — types and per-line Tax flags —
            # so its totals are the ticket's totals. Per-line tax is
            # rounded line by line; any cent of rounding difference
            # against the ticket's tax lands on the last taxed line, so
            # the invoice tax equals the ticket tax exactly.
            # Build 's' (Jason 2026-10-25): only the COMPUTED lines
            # carry — stored charge lines (typed before this build)
            # stay on the ticket's own record and in its total, but
            # they no longer flow onto the invoice; freight and extras
            # are typed on the invoice by the operator. Per-line
            # settlements aimed at a stored line have no invoice line
            # to land on and fold to blanket in the carry below; money
            # settled beyond the carried total is kept as an open
            # credit memo by that same carry, never dropped.
            _tlines = [ln for ln in (m.get("lines") or [])
                       if ln.get("computed")]
            _exempt = bool(m["tax_exempt"])
            _trate = Decimal(str(m["tax_rate"] or 0))
            _rows = []
            for _ln in _tlines:
                _amt = _money(_ln["amount"])
                _ltax = Decimal("0.00") if (_exempt or not _ln["taxed"]) else (_amt * _trate).quantize(CENT, rounding=ROUND_HALF_UP)
                _ldesc = desc if _ln.get("computed") and _ln["category"] == "Rental" and _ln["description"] == (m["description"] or "").strip() else (_ln["description"] or "")
                _rows.append([_ln["category"], _ln.get("item") or "", _ldesc,
                              float(_ln["qty"]), _ln["uom"], float(_ln["rate"]),
                              _amt, _ltax, bool(_ln["taxed"]),
                              int(_ln.get("line_id") or 0)])
            if not _rows:
                _rows.append(["Rental", "", desc, 1.0, "Each", 0.0,
                              Decimal("0.00"), Decimal("0.00"), True, 0])
            # The rounding-difference target is the tax on the CARRIED
            # lines only (build 's'): the ticket's own tax (m["tax"])
            # still counts any stored lines' tax share, and that share
            # must not be forced onto the invoice's computed lines.
            # Computed lines are exactly the rental subtotal's parts,
            # so the target is the rental subtotal at the ticket's
            # rate — identical to m["tax"] whenever no stored taxed
            # line stands on the ticket.
            _carry_tax = (Decimal("0.00") if _exempt else
                          (_money(m["rental_sub"]) * _trate).quantize(
                              CENT, rounding=ROUND_HALF_UP))
            _diff = _carry_tax - sum((r[7] for r in _rows), Decimal("0.00"))
            if _diff:
                for _r in reversed(_rows):
                    if _r[8] and not _exempt:
                        _r[7] += _diff
                        break
            _tmap: dict = {}
            _ttot = Decimal("0.00")
            for _i, _r in enumerate(_rows):
                _cur = con.execute("""INSERT INTO invoice_lines(invoice_id,po_line,category,item,description,qty,uom,rate,amount,clerk,tax_rate,tax_amount,tax_exempt,tax_name,tax_loc,source_type,source_id,source_line_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(ikey,t["po"] or "" if _i == 0 else "",_r[0],_r[1],_r[2],_r[3],_r[4],_r[5],float(_r[6]),"",float(0 if _exempt else m["tax_rate"]),float(_r[7]),int(_exempt),m["tax_name"],m["tax_loc"],"ticket",t["ticket_id"],_r[9]))
                if _r[9]:
                    _tmap[_r[9]] = int(_cur.lastrowid)
                _ttot = _ms(_ttot, _r[6], _r[7])
            _src_line_map[("ticket", t["ticket_id"])] = _tmap
            _src_totals[("ticket", t["ticket_id"])] = _ttot
            con.execute("UPDATE tickets SET invoice_id=?,status='Billed' WHERE ticket_id=?",(ikey,t["ticket_id"]))
            if skip_condition and not t["in_condition"]:
                con.execute("UPDATE tickets SET in_condition=? WHERE ticket_id=? AND (in_condition IS NULL OR in_condition='')",(COND_NOT_RECORDED,t["ticket_id"]))
        cust_exempt=bool(con.execute("SELECT tax_exempt FROM customers WHERE id=?",(ckey,)).fetchone()[0])
        for w in ws:
            exempt=cust_exempt; rate=_money(0); tax_name=""; tax_loc=""
            if w["ticket_id"]:
                tm=ticket_money(con,doc_num(con, "ticket", w["ticket_id"])); exempt=bool(tm["tax_exempt"]); rate=_money(tm["tax_rate"]); tax_name=tm["tax_name"]; tax_loc=tm["tax_loc"]
            wlines=_wo_lines_for_invoice(con,w["id"])
            _wmap: dict = {}
            _wtot = Decimal("0.00")
            if wlines:
                # One invoice line per WO line (2026-10-15): the invoice
                # matches the work order, line by line.
                for ln in wlines:
                    amt=_money(ln["amount"])
                    tax=Decimal("0.00") if exempt else (amt*rate).quantize(CENT,rounding=ROUND_HALF_UP)
                    # The WO line's own Type/Unit flow onto the invoice
                    # line (global row); pre-migration rows have neither
                    # and keep the old Labor/Each.
                    cat = clean_line_type(con, _row_get(ln, "category", "Labor"))
                    uom = clean_line_uom(con, _row_get(ln, "uom", "Each"))
                    itm = (_row_get(ln, "item", "") or "").strip()
                    _cur = con.execute("""INSERT INTO invoice_lines(invoice_id,po_line,category,item,description,qty,uom,rate,amount,clerk,tax_rate,tax_amount,tax_exempt,tax_name,tax_loc,source_type,source_id,source_line_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(ikey,"",cat,itm,ln["description"] or "",float(ln["qty"]),uom,float(ln["rate"]),float(amt),"",float(0 if exempt else rate),float(tax),int(exempt),tax_name,tax_loc,"work_order",w["wo_id"],int(_row_get(ln, "line_id", 0) or 0)))
                    if _row_get(ln, "line_id", 0):
                        _wmap[int(ln["line_id"])] = int(_cur.lastrowid)
                    _wtot = _ms(_wtot, amt, tax)
            else:
                amt=_money(w["bill_amount"])
                tax=Decimal("0.00") if exempt else (amt*rate).quantize(CENT,rounding=ROUND_HALF_UP)
                con.execute("""INSERT INTO invoice_lines(invoice_id,po_line,category,description,qty,uom,rate,amount,clerk,tax_rate,tax_amount,tax_exempt,tax_name,tax_loc,source_type,source_id,source_line_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(ikey,"","Labor",f"{w['wo_id']} — {w['description']}",1,"Each",float(amt),float(amt),"",float(0 if exempt else rate),float(tax),int(exempt),tax_name,tax_loc,"work_order",w["wo_id"],0))
                _wtot = _ms(amt, tax)
            _src_line_map[("wo", w["wo_id"])] = _wmap
            _src_totals[("wo", w["wo_id"])] = _wtot
            con.execute("UPDATE work_orders SET invoice_id=? WHERE wo_id=?",(ikey,w["wo_id"]))
        # Dispute notes carry too (Jason 2026-10-23): a note on a
        # source line lands on the invoice line it becomes, so the
        # short-pay story survives invoicing.
        for (_k, _ref), _map in _src_line_map.items():
            _srctbl, _idc = (("wo_lines", "wo_id") if _k == "wo"
                             else ("ticket_lines", "ticket_id"))
            _srckey = (key_of(con, "work_orders", _ref) if _k == "wo"
                       else key_of(con, "tickets", _ref))
            try:
                _notes = con.execute(
                    f"SELECT line_id, line_note FROM {_srctbl} "
                    f"WHERE {_idc}=? AND COALESCE(line_note,'')<>''",
                    (_srckey,)).fetchall()
            except sqlite3.Error:
                _notes = []
            for _nr in _notes:
                if int(_nr["line_id"]) in _map:
                    con.execute(
                        "UPDATE invoice_lines SET line_note=? "
                        "WHERE line_id=?",
                        (_nr["line_note"], _map[int(_nr["line_id"])]))
        # Carry (Jason 2026-10-23): settlements already made against
        # these tickets / work orders mirror onto this invoice, so its
        # balance nets money taken at the yard or the desk — exactly
        # once (see _carry_doc_settlements). Inside this transaction:
        # the invoice and its carried money appear together or not
        # at all.
        _carried = 0.0
        for (_k, _ref), _map in _src_line_map.items():
            _carried += _carry_doc_settlements(
                con, _k, _ref, ino, _map, _src_totals[(_k, _ref)],
                customer_id, d)
        # Quote money carries too (Jason 2026-10-23): money taken
        # against the quote this invoice came from mirrors onto the
        # invoice — capped at what the invoice still has room for
        # after the ticket / work-order carries; any excess is kept
        # as an open credit memo by the carry itself. No quote line
        # maps onto an invoice line (quote lines become rental
        # tickets, not invoice lines), so a quote breakdown folds to
        # blanket mirrors here; the per-line record stays on the
        # quote, which every descendant names through quote_no.
        _qn = (quote_no or "").strip()
        if not _qn:
            _qn = next((doc_num(con, "quote", t["quote_id"]) for t in ts if t["quote_id"]), "")
        if _qn:
            _inv_total = _money(invoice_totals(con, ino)["total"])
            _room = _ms(_inv_total, -_money(_carried))
            if _room > Decimal("0.009"):
                _carried += _carry_doc_settlements(
                    con, "quote", _qn, ino, {}, _room, customer_id, d)
        if _carried > 0.009:
            _refresh_invoice_status(con, ino)
        con.commit()
        # Q6: the PO record is shared — this invoice's PO detail keeps it current.
        # A newly issued PO linked to a unit auto-reserves that unit when it's
        # in-yard; the reservation is soft and never blocks an interim job.
        _po_assets = [t["asset_id"] for t in ts if t["asset_id"]]
        _is_new_po = upsert_po_record(con, customer_id, po, po_expire, po_cost_code, po_notes,
                                      asset_id=_po_assets[0] if _po_assets else None)
        if _is_new_po and _po_assets:
            _auto_reserve_for_po(con, customer_id, (po or "").strip(), _po_assets[0], ts[0])
        con.commit(); return ino
    except Exception:
        con.rollback(); raise
def invoice_has_lines(con, invoice_no: str) -> bool:
    return con.execute("SELECT 1 FROM invoice_lines WHERE invoice_id=? LIMIT 1",(key_of(con, "invoices", invoice_no),)).fetchone() is not None
def _next_pay_id(con) -> str:
    # Build 'v' (landmine c): skip numbers already standing in either
    # payment ledger — a payment number minted ahead of the counter
    # must never be reissued.
    while True:
        row=con.execute("SELECT next_payment FROM company WHERE id=1").fetchone(); n=int(row["next_payment"] or 1)
        con.execute("UPDATE company SET next_payment=? WHERE id=1",(n+1,))
        pid = f"P-{n:03d}"
        taken = con.execute("SELECT 1 FROM collections WHERE pay_id=?", (pid,)).fetchone()
        if not taken and _doc_collections_exist(con):
            taken = con.execute("SELECT 1 FROM doc_collections WHERE pay_id=?", (pid,)).fetchone()
        if not taken:
            return pid
def _refresh_invoice_status(con, invoice_no: str) -> None:
    tot=invoice_totals(con,invoice_no); cur=con.execute("SELECT status FROM invoices WHERE invoice_no=?",(invoice_no,)).fetchone()
    if not cur: return
    st="Paid" if tot["balance"]<=0.009 else ("Partial" if tot["paid"]>0.009 else (cur["status"] if cur["status"] not in ("Paid","Partial") else "Ready"))
    con.execute("UPDATE invoices SET status=? WHERE invoice_no=?",(st,invoice_no))
def next_batch_id(con: sqlite3.Connection) -> str:
    """Next payment-batch id (PB-NNN): one received payment allocated
    across one or many invoices. MAX-based like the pay_nums backfill —
    no counter column, single-user app. First batch is PB-1001."""
    nums = []
    for (b,) in con.execute(
            "SELECT batch_id FROM collections WHERE batch_id LIKE 'PB-%'"):
        try:
            nums.append(int(str(b).split("-", 1)[1]))
        except (ValueError, IndexError):
            pass
    return f"PB-{max(nums, default=1000) + 1:03d}"


# ---------------------------------------------------------------------------
# Payment line allocations (Jason 2026-10-23): money in may OPTIONALLY be
# distributed line by line against an invoice's lines — for audits and
# record keeping. Never mandatory: a payment with no allocation rows is
# a plain blanket payment, and invoice balances / paid-in-full derive
# from collections exactly as they always have.
def _ensure_payalloc_table(con: sqlite3.Connection) -> None:
    """Create payment_allocations (generalized doc shape) on books
    that predate it (schema.sql owns the DDL for new books; the
    migration rebuilds the invoice-only shape into this one)."""
    con.execute("""CREATE TABLE IF NOT EXISTS payment_allocations (
      alloc_id INTEGER PRIMARY KEY AUTOINCREMENT,
      source TEXT NOT NULL DEFAULT 'payment' CHECK (source IN ('payment','cash','credit')),
      pay_id INTEGER,
      cash_entry_id INTEGER REFERENCES cash_entries(entry_id),
      batch_id TEXT,
      doc_kind TEXT NOT NULL DEFAULT 'invoice',
      doc_id INTEGER NOT NULL DEFAULT 0,
      line_id INTEGER,
      carried INTEGER NOT NULL DEFAULT 0,
      amount REAL NOT NULL CHECK (amount > 0),
      pay_date TEXT NOT NULL DEFAULT '',
      clerk TEXT,
      created_at TEXT NOT NULL DEFAULT (datetime('now')))""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_payalloc_doc ON payment_allocations(doc_kind, doc_id)")


def _ensure_doc_collections(con: sqlite3.Connection) -> None:
    """Create doc_collections — the money ledger for work orders,
    rental tickets, sales, quotes, and change orders — on books that
    predate it."""
    con.execute("""CREATE TABLE IF NOT EXISTS doc_collections (
      id INTEGER PRIMARY KEY,
      pay_id TEXT NOT NULL UNIQUE,
      batch_id TEXT,
      pay_date TEXT NOT NULL,
      doc_kind TEXT NOT NULL CHECK (doc_kind IN ('wo','ticket','sale','quote','change')),
      doc_id INTEGER NOT NULL DEFAULT 0,
      customer_id INTEGER REFERENCES customers(id),
      method TEXT NOT NULL,
      amount REAL NOT NULL CHECK (amount != 0),
      ref_no TEXT,
      notes TEXT,
      kind TEXT NOT NULL DEFAULT 'payment' CHECK (kind IN ('payment','credit')),
      cm_id INTEGER REFERENCES credit_memos(id),
      clerk TEXT,
      applied_amount REAL,
      unapplied_amount REAL NOT NULL DEFAULT 0,
      cash_entry_id INTEGER REFERENCES cash_entries(entry_id)
    )""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_dcol_doc ON doc_collections(doc_kind, doc_id)")


def _payalloc_exists(con) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='payment_allocations'").fetchone() is not None


def _doc_collections_exist(con) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='doc_collections'").fetchone() is not None


# Document kinds for money (Jason 2026-10-23, universality — the
# principle applied as a principle): every document that carries
# money — invoice, work order, rental ticket, quote, sale. Build 'v'
# (Jason 2026-10-25): a Change Order is a standalone money document
# in its own right — its own receivable, settled directly, optionally
# associated with one other money document without merging. The
# earlier reading ("change orders are never settled directly; their
# amounts live inside the quote's face") is superseded. Credit memos
# are instruments, settled by application — see issue_credit_memo.)
# DOC_LABELS names them the way the app does.
PAYABLE_KINDS = ("invoice", "wo", "ticket", "sale", "quote", "change")
DOC_LABELS = {"invoice": "Invoice", "wo": "WO", "ticket": "Rental Ticket",
              "sale": "Sale", "quote": "Quote", "change": "Change Order"}


def _line_total(row) -> Decimal:
    """A line's full amount: its amount plus its own tax."""
    return _ms(_money(row["amount"]), _money(row["tax_amount"]))


def _doc_line_rows(con, doc_kind: str, doc_ref: str) -> list:
    """One document's charge lines in the allocation shape:
    {line_id, category, item, description, qty, uom, rate, amount,
    tax_amount, total, note}. Line ids live in each kind's own table
    (invoice_lines / wo_lines / sales.seq; tickets return no rows —
    see below).

    Ticket lines: NONE (build 's', Jason 2026-10-25). A rental
    ticket settles blanket-only — its computed lines are system
    figures with no stored row to aim at, and stored charge lines
    ended as a capability (existing rows stay on the ticket's
    record and in its total, read-only in its Job Info popup; they
    are not settlement targets and no longer flow to the invoice).
    Every other kind returns its stored lines as before."""
    out = []
    if doc_kind == "ticket":
        return out
    if doc_kind == "invoice":
        for r in con.execute(
                "SELECT * FROM invoice_lines WHERE invoice_id=? "
                "ORDER BY line_id", (doc_key(con, "invoice", doc_ref),)):
            out.append({
                "line_id": int(r["line_id"]),
                "category": r["category"] or "",
                "item": r["item"] or "",
                "description": r["description"] or "",
                "qty": float(r["qty"] or 0), "uom": r["uom"] or "",
                "rate": float(r["rate"] or 0),
                "amount": float(_money(r["amount"])),
                "tax_amount": float(_money(r["tax_amount"])),
                "note": _row_get(r, "line_note", "") or "",
            })
    elif doc_kind == "wo":
        try:
            rows = con.execute(
                "SELECT * FROM wo_lines WHERE wo_id=? ORDER BY line_id",
                (doc_key(con, "wo", doc_ref),)).fetchall()
        except sqlite3.Error:
            rows = []
        for r in rows:
            out.append({
                "line_id": int(r["line_id"]),
                "category": _row_get(r, "category", "Other") or "Other",
                "item": _row_get(r, "item", "") or "",
                "description": _row_get(r, "description", "") or "",
                "qty": float(_row_get(r, "qty", 1) or 0),
                "uom": _row_get(r, "uom", "Each") or "Each",
                "rate": float(_row_get(r, "rate", 0) or 0),
                "amount": float(_money(_row_get(r, "amount", 0))),
                "tax_amount": 0.0,
                "note": _row_get(r, "line_note", "") or "",
            })
    elif doc_kind == "quote":
        # Quote lines carry no tax (a quote computes none — its print
        # says taxes are not included); the tax flag first exists
        # where tax is computed, on the rental ticket / invoice.
        try:
            rows = con.execute(
                "SELECT * FROM quote_lines WHERE quote_id=? "
                "ORDER BY line_id", (doc_key(con, "quote", doc_ref),)).fetchall()
        except sqlite3.Error:
            rows = []
        for r in rows:
            out.append({
                "line_id": int(r["line_id"]),
                "category": _row_get(r, "kind", "Other") or "Other",
                "item": _row_get(r, "item", "") or "",
                "description": _row_get(r, "description", "") or "",
                "qty": float(_row_get(r, "qty", 1) or 0),
                "uom": _row_get(r, "uom", "Each") or "Each",
                "rate": float(_row_get(r, "rate", 0) or 0),
                "amount": float(_money(_row_get(r, "amount", 0))),
                "tax_amount": 0.0,
                "note": _row_get(r, "line_note", "") or "",
            })
    elif doc_kind == "sale":
        try:
            rows = con.execute(
                """SELECT s.*, COALESCE(a.unit_no, '') AS unit_no
                   FROM sales s LEFT JOIN assets a
                     ON a.id = s.asset_id
                   WHERE s.group_id=? ORDER BY s.seq, s.id""",
                (doc_key(con, "sale", doc_ref),)).fetchall()
        except sqlite3.Error:
            rows = []
        for r in rows:
            out.append({
                "line_id": int(r["id"]),
                "category": "Item",
                "item": _row_get(r, "unit_no", "") or "",
                "description": _row_get(r, "item_desc", "") or "",
                "qty": float(_row_get(r, "qty", 1) or 0),
                "uom": "Each",
                "rate": float(_money(_row_get(r, "amount", 0))),
                "amount": float(_money(_row_get(r, "amount", 0))),
                "tax_amount": 0.0,
                "note": _row_get(r, "line_note", "") or "",
            })
    elif doc_kind == "change":
        # A Change Order's lines (build 'v'): direction signs the
        # amount — adds count positive, subtracts negative — and
        # the document's total is their sum.
        try:
            rows = con.execute(
                "SELECT * FROM change_order_lines WHERE co_id=? "
                "ORDER BY line_id", (doc_key(con, "change", doc_ref),)).fetchall()
        except sqlite3.Error:
            rows = []
        for r in rows:
            amt = float(_money(_row_get(r, "amount", 0)))
            if (_row_get(r, "direction", "add") or "add") == "subtract":
                amt = -abs(amt)
            out.append({
                "line_id": int(r["line_id"]),
                "category": _row_get(r, "kind", "Other") or "Other",
                "item": _row_get(r, "item", "") or "",
                "description": _row_get(r, "description", "") or "",
                "qty": float(_row_get(r, "qty", 1) or 0),
                "uom": _row_get(r, "uom", "Each") or "Each",
                "rate": float(_money(_row_get(r, "rate", 0))),
                "amount": amt,
                "tax_amount": 0.0,
                "note": _row_get(r, "line_note", "") or "",
            })
    for d in out:
        d["total"] = float(_ms(_money(d["amount"]), _money(d["tax_amount"])))
    return out


def _doc_line_allocated(con, doc_kind: str, doc_ref: str,
                        line_id: int) -> Decimal:
    """What one document line has been covered so far — payments,
    credits applied against the line (a credit against a line counts
    like paid for that line), settling Cash In entries (a Cash In
    attached to a document IS a payment through the Cash door —
    Jason 2026-10-23), and, on an invoice, settlements carried onto
    the line when its source document was invoiced. Cash Out
    breakdowns are records only and never consume a line."""
    if not _payalloc_exists(con):
        return Decimal("0.00")
    v = con.execute(
        "SELECT COALESCE(SUM(pa.amount),0) FROM payment_allocations pa "
        "LEFT JOIN cash_entries ce ON ce.entry_id = pa.cash_entry_id "
        "WHERE pa.doc_kind=? AND pa.doc_id=? AND pa.line_id=? "
        "AND (pa.source IN ('payment','credit') "
        "OR (pa.source='cash' AND ce.direction='in'))",
        (doc_kind, doc_key(con, doc_kind, doc_ref), int(line_id))).fetchone()[0]
    return _money(v)


def _line_allocated(con, line_id: int) -> Decimal:
    """Compat wrapper: an invoice line's covered amount."""
    row = con.execute(
        "SELECT invoice_id FROM invoice_lines WHERE line_id=?",
        (int(line_id),)).fetchone()
    if not row:
        return Decimal("0.00")
    return _doc_line_allocated(con, "invoice", num_of(con, "invoices", row[0]), line_id)


def _clean_doc_line_allocs(con, doc_kind: str, doc_ref: str, line_allocs,
                           cap_total, source: str, direction: int = 1) -> list:
    """Validate [(line_id, amount)] against a document's lines; return
    [(line_id, Decimal)] in entry order, signed by direction. Every
    line belongs to the document, and the sum's magnitude may not
    exceed cap_total's (the applied amount for a payment, the entry
    amount for a cash entry) — a lesser sum is fine; the rest stays
    blanket. A payment or a positive credit may not push a line past
    its uncovered remainder (credits count like paid for a line); a
    cash entry caps at the line's own total instead (its Out rows are
    records). direction=-1 serves a NEGATIVE credit memo (Jason
    2026-10-23): the operator posts positive magnitudes, the cleaner
    returns negative amounts, and the per-line cap is what the line
    has been settled so far — a negative credit re-opens settled
    amount only; it never pushes a line's net settled below zero."""
    by_line: dict = {}
    order: list = []
    for lid, raw in (line_allocs or []):
        try:
            lid = int(lid)
        except (TypeError, ValueError):
            raise ValueError("Bad line in the line breakdown") from None
        amt = _money(raw)
        if direction < 0:
            amt = -abs(amt)
            if amt >= 0:
                continue
        elif amt <= 0:
            continue
        if lid not in by_line:
            order.append(lid)
            by_line[lid] = Decimal("0.00")
        by_line[lid] = _ms(by_line[lid], amt)
    if not order:
        return []
    total = Decimal("0.00")
    for lid in order:
        total = _ms(total, by_line[lid])
    if abs(total) - abs(_money(cap_total)) > Decimal("0.009"):
        raise ValueError(
            f"Line amounts add to ${abs(total):,.2f} — more than the "
            f"${abs(_money(cap_total)):,.2f} on {doc_ref}")
    lines = {d["line_id"]: d for d in _doc_line_rows(con, doc_kind, doc_ref)}
    out = []
    for lid in order:
        d = lines.get(lid)
        if d is None:
            raise ValueError(
                f"A broken-down line is not a line of {doc_ref}")
        lt = _money(d["total"])
        if direction < 0:
            cap = _doc_line_allocated(con, doc_kind, doc_ref, lid)
            if -by_line[lid] - cap > Decimal("0.009"):
                raise ValueError(
                    f"Line amount ${-by_line[lid]:,.2f} exceeds what "
                    f"that line of {doc_ref} has settled (${cap:,.2f}) — "
                    "a negative credit re-opens settled amount only")
        else:
            cap = (lt if source == "cash"
                   else _ms(lt, -_doc_line_allocated(con, doc_kind, doc_ref, lid)))
            if by_line[lid] - cap > Decimal("0.009"):
                raise ValueError(
                    f"Line amount ${by_line[lid]:,.2f} exceeds what that "
                    f"line of {doc_ref} can take (${cap:,.2f})")
        out.append((lid, by_line[lid]))
    return out


def _clean_line_allocs(con, invoice_no: str, line_allocs, cap_total,
                       source: str, direction: int = 1) -> list:
    """Compat wrapper: validate a breakdown against an invoice."""
    return _clean_doc_line_allocs(con, "invoice", invoice_no,
                                  line_allocs, cap_total, source,
                                  direction=direction)


def _write_line_allocs(con, *, source, pay_key, cash_entry_id, batch_id,
                       doc_kind, doc_ref, pay_date, clerk, applied,
                       cleaned, carried=0) -> None:
    """Insert one amount's allocation rows against a document: one per
    line, plus the blanket remainder row (line NULL) when the lines
    do not cover the whole amount — a broken-down amount's rows always
    sum back to what was applied. Caller owns the transaction.
    pay_key is the payment's shared engine key; doc_ref is the
    document's number, stored as its engine key."""
    dkey = doc_key(con, doc_kind, doc_ref)
    rest = _money(applied)
    for lid, amt in cleaned:
        con.execute(
            """INSERT INTO payment_allocations(source, pay_id, cash_entry_id,
               batch_id, doc_kind, doc_id, line_id, carried, amount,
               pay_date, clerk)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (source, pay_key, cash_entry_id, batch_id, doc_kind, dkey,
             lid, int(carried), float(amt), pay_date or "", clerk or ""))
        rest = _ms(rest, -amt)
    if abs(rest) > Decimal("0.005"):
        con.execute(
            """INSERT INTO payment_allocations(source, pay_id, cash_entry_id,
               batch_id, doc_kind, doc_id, line_id, carried, amount,
               pay_date, clerk)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (source, pay_key, cash_entry_id, batch_id, doc_kind, dkey,
             None, int(carried), float(rest), pay_date or "", clerk or ""))


def doc_line_states(con, doc_kind: str, doc_ref: str) -> list:
    """Per-line covered state for one document, derived from payment,
    credit, and settling cash-in allocations: each line's total
    (amount + its tax), what payments allocated to it, what credits
    were applied against it (with their memo numbers), what cash-in
    entries settled against it, what was carried onto it at invoicing
    (invoice lines only), and the remainder. Blanket money never
    touches lines, so an unallocated line reads fully open here even
    on a settled document — the document balance above it remains
    the governing figure."""
    rows = _doc_line_rows(con, doc_kind, doc_ref)
    paid, credited, cash_paid, carried, credit_refs = {}, {}, {}, {}, {}
    if _payalloc_exists(con):
        dkey = doc_key(con, doc_kind, doc_ref)
        for lid, src, carr, s in con.execute(
                "SELECT pa.line_id, pa.source, pa.carried, "
                "COALESCE(SUM(pa.amount),0) "
                "FROM payment_allocations pa "
                "LEFT JOIN cash_entries ce "
                "ON ce.entry_id = pa.cash_entry_id "
                "WHERE pa.doc_kind=? AND pa.doc_id=? "
                "AND pa.line_id IS NOT NULL "
                "AND (pa.source IN ('payment','credit') "
                "OR (pa.source='cash' AND ce.direction='in')) "
                "GROUP BY pa.line_id, pa.source, pa.carried",
                (doc_kind, dkey)):
            lid = int(lid)
            if carr:
                carried[lid] = _money(s)
            elif src == "credit":
                credited[lid] = _money(s)
            elif src == "cash":
                cash_paid[lid] = _money(s)
            else:
                paid[lid] = _money(s)
        for lid, cmkey in con.execute(
                "SELECT pa.line_id, COALESCE(c.cm_id, dc.cm_id) "
                "FROM payment_allocations pa "
                "LEFT JOIN collections c ON c.id = pa.pay_id "
                "LEFT JOIN doc_collections dc ON dc.id = pa.pay_id "
                "WHERE pa.doc_kind=? AND pa.doc_id=? "
                "AND pa.source='credit' AND pa.line_id IS NOT NULL "
                "AND COALESCE(c.cm_id, dc.cm_id) IS NOT NULL "
                "ORDER BY pa.alloc_id", (doc_kind, dkey)):
            cm = num_of(con, "credit_memos", cmkey)
            refs = credit_refs.setdefault(int(lid), [])
            if cm and cm not in refs:
                refs.append(cm)
    out = []
    for d in rows:
        lid = d["line_id"]
        pd_ = paid.get(lid, Decimal("0.00"))
        cr_ = credited.get(lid, Decimal("0.00"))
        cp_ = cash_paid.get(lid, Decimal("0.00"))
        ca_ = carried.get(lid, Decimal("0.00"))
        al = _ms(pd_, cr_, cp_, ca_)
        out.append({
            "line_id": lid,
            "category": d["category"], "item": d["item"],
            "description": d["description"],
            "qty": d["qty"], "uom": d["uom"], "rate": d["rate"],
            "amount": d["amount"], "tax_amount": d["tax_amount"],
            "total": d["total"],
            "allocated": float(al),
            "paid_amount": float(pd_),
            "credited": float(cr_),
            "cash_paid": float(cp_),
            "carried": float(ca_),
            "credit_refs": credit_refs.get(lid, []),
            "remaining": float(_ms(_money(d["total"]), -al)),
            "note": d["note"],
        })
    return out


def invoice_line_states(con, invoice_no: str) -> list:
    """Per-line covered state for one invoice (see doc_line_states)."""
    return doc_line_states(con, "invoice", invoice_no)


def set_doc_line_note(con, doc_kind: str, doc_ref: str, line_id,
                      note: str) -> str:
    """Set or clear the note on one document line (Jason 2026-10-23 —
    the short-pay marker: why a line's remainder stands open). The
    note is an annotation, not money: it is editable on locked
    documents too, and saving it blank clears it. Returns the stored
    note."""
    try:
        lid = int(line_id)
    except (TypeError, ValueError):
        raise ValueError("Bad line") from None
    lines = {d["line_id"]: d for d in _doc_line_rows(con, doc_kind, doc_ref)}
    if lid not in lines:
        raise ValueError(f"That line is not a line of {doc_ref}")
    # Notes doctrine (Jason 2026-10-24): a note saves up to 2000
    # characters; the little field shows what fits, the pop-up reads
    # the rest. The old 300 cap cut dissertations off mid-thought.
    txt = (note or "").strip()[:2000]
    if doc_kind == "invoice":
        con.execute("UPDATE invoice_lines SET line_note=? WHERE line_id=?",
                    (txt, lid))
    elif doc_kind == "wo":
        con.execute("UPDATE wo_lines SET line_note=? WHERE line_id=? "
                    "AND wo_id=?", (txt, lid, doc_key(con, "wo", doc_ref)))
    elif doc_kind == "ticket":
        con.execute("UPDATE ticket_lines SET line_note=? WHERE line_id=? "
                    "AND ticket_id=?", (txt, lid, doc_key(con, "ticket", doc_ref)))
    elif doc_kind == "sale":
        con.execute("UPDATE sales SET line_note=? WHERE id=?",
                    (txt, lid))
    elif doc_kind == "quote":
        con.execute("UPDATE quote_lines SET line_note=? WHERE line_id=? "
                    "AND quote_id=?", (txt, lid, doc_key(con, "quote", doc_ref)))
    elif doc_kind == "change":
        con.execute("UPDATE change_order_lines SET line_note=? "
                    "WHERE line_id=? AND co_id=?",
                    (txt, lid, doc_key(con, "change", doc_ref)))
    con.commit()
    return txt


def set_invoice_line_note(con, invoice_no: str, line_id, note: str) -> str:
    """Set or clear the note on one invoice line (see
    set_doc_line_note)."""
    return set_doc_line_note(con, "invoice", invoice_no, line_id, note)


def doc_has_line_allocations(con, doc_kind: str, doc_ref: str) -> bool:
    if not _payalloc_exists(con):
        return False
    return con.execute(
        "SELECT 1 FROM payment_allocations WHERE doc_kind=? AND doc_id=? "
        "AND line_id IS NOT NULL LIMIT 1",
        (doc_kind, doc_key(con, doc_kind, doc_ref))).fetchone() is not None


def invoice_has_line_allocations(con, invoice_no: str) -> bool:
    return doc_has_line_allocations(con, "invoice", invoice_no)


def list_payment_allocations(con, pay_id=None, batch_id=None,
                             invoice_no=None, cash_entry_id=None,
                             source=None, doc_kind=None, doc_ref=None,
                             carried=None) -> list:
    """Allocation rows with the line label resolved per document kind
    (item, else description, else category). Blanket rows read
    'Blanket'. Filters combine; invoice_no remains as the invoice
    shortcut for doc_kind='invoice' + doc_ref."""
    if not _payalloc_exists(con):
        return []
    conds, args = [], []
    if pay_id is not None:
        conds.append("pa.pay_id=?")
        args.append(pay_key_of(con, pay_id))
    if batch_id is not None:
        conds.append("pa.batch_id=?")
        args.append(batch_id)
    if invoice_no is not None:
        conds.append("pa.doc_kind='invoice' AND pa.doc_id=?")
        args.append(doc_key(con, "invoice", invoice_no))
    if doc_kind is not None:
        conds.append("pa.doc_kind=?")
        args.append(doc_kind)
    if doc_ref is not None:
        if doc_kind is not None:
            conds.append("pa.doc_id=?")
            args.append(doc_key(con, doc_kind, doc_ref))
        else:
            keys = [doc_key(con, k, doc_ref) for k in PAYABLE_KINDS]
            keys = [k for k in keys if k is not None]
            conds.append("pa.doc_id IN (%s)" % ",".join("?" * len(keys))
                         if keys else "1=0")
            args.extend(keys)
    if cash_entry_id is not None:
        conds.append("pa.cash_entry_id=?")
        args.append(cash_entry_id)
    if source is not None:
        conds.append("pa.source=?")
        args.append(source)
    if carried is not None:
        conds.append("pa.carried=?")
        args.append(int(carried))
    out = []
    for r in con.execute(
            f"""SELECT pa.*,
                       COALESCE(il.category, wl.category, tl.category,
                                ql.kind, 'Item') AS lcat,
                       COALESCE(il.item, wl.item,
                                tl.item, ql.item, '') AS litem,
                       COALESCE(il.description, wl.description,
                                tl.description, ql.description,
                                co_l.description,
                                sl_item.item_desc, '') AS ldesc,
                       COALESCE(il.line_note, wl.line_note, tl.line_note,
                                ql.line_note, co_l.line_note,
                                sl_item.line_note,
                                '') AS lnote,
                       cmr.cm_no AS cm_no,
                       COALESCE(c.carried_from, '') AS carried_from
                FROM payment_allocations pa
                LEFT JOIN invoice_lines il
                  ON pa.doc_kind='invoice' AND il.line_id = pa.line_id
                LEFT JOIN wo_lines wl
                  ON pa.doc_kind='wo' AND wl.line_id = pa.line_id
                LEFT JOIN ticket_lines tl
                  ON pa.doc_kind='ticket' AND tl.line_id = pa.line_id
                LEFT JOIN quote_lines ql
                  ON pa.doc_kind='quote' AND ql.line_id = pa.line_id
                LEFT JOIN change_order_lines co_l
                  ON pa.doc_kind='change' AND co_l.line_id = pa.line_id
                LEFT JOIN sales sl_item
                  ON pa.doc_kind='sale' AND sl_item.id = pa.line_id
                 AND sl_item.group_id = pa.doc_id
                LEFT JOIN collections c ON c.id = pa.pay_id
                LEFT JOIN doc_collections dc ON dc.id = pa.pay_id
                LEFT JOIN credit_memos cmr
                  ON cmr.id = COALESCE(c.cm_id, dc.cm_id)
                WHERE {' AND '.join(conds) if conds else '1=1'}
                ORDER BY pa.alloc_id""", args):
        d = dict(r)
        d["doc_ref"] = doc_num(con, d["doc_kind"], d["doc_id"]) or ""
        d["pay_id"] = pay_id_of(con, d["pay_id"]) or ""
        if d.get("carried_from") and ":" in str(d["carried_from"]):
            _ck, _cv = str(d["carried_from"]).split(":", 1)
            try:
                _cv = doc_num(con, _ck, int(_cv)) or _cv
            except (TypeError, ValueError):
                pass
            d["carried_from"] = f"{_ck}:{_cv}"
        d["invoice_no"] = d["doc_ref"] if d["doc_kind"] == "invoice" else ""
        d["invoice_line_id"] = d["line_id"]
        d["line_note"] = d.get("lnote") or ""
        d["cm_no"] = d.get("cm_no") or ""
        if d["line_id"] is None:
            d["line_label"] = "Blanket"
        else:
            d["line_label"] = ((d.get("litem") or "").strip()
                               or (d.get("ldesc") or "").strip()
                               or (d.get("lcat") or ""))
        out.append(d)
    return out


def _doc_customer(con, doc_kind: str, doc_ref: str):
    """The customer NUMBER a money document belongs to (None when the
    document does not exist or carries none)."""
    if doc_kind == "invoice":
        r = con.execute("SELECT customer_id FROM invoices WHERE invoice_no=?",
                        (doc_ref,)).fetchone()
    elif doc_kind == "wo":
        r = con.execute("SELECT customer_id FROM work_orders WHERE wo_id=?",
                        (doc_ref,)).fetchone()
    elif doc_kind == "ticket":
        r = con.execute("SELECT customer_id FROM tickets WHERE ticket_id=?",
                        (doc_ref,)).fetchone()
    elif doc_kind == "sale":
        r = con.execute("SELECT customer_id FROM sales WHERE group_id=? "
                        "ORDER BY seq LIMIT 1",
                        (doc_key(con, "sale", doc_ref),)).fetchone()
    elif doc_kind == "quote":
        r = con.execute("SELECT customer_id FROM quotes WHERE quote_no=?",
                        (doc_ref,)).fetchone()
    elif doc_kind == "change":
        r = con.execute("SELECT customer_id FROM change_orders WHERE co_no=?",
                        (doc_ref,)).fetchone()
    else:
        return None
    return (cust_code(con, r["customer_id"]) if r else None)


def doc_total(con, doc_kind: str, doc_ref: str) -> Decimal:
    """A money document's full total. A work order totals at its bill
    amount (the sum of its lines, by the save rule); a ticket at its
    computed money total; a sale at the sum of its rows; an invoice
    at its invoice total."""
    if doc_kind == "invoice":
        return _money(invoice_totals(con, doc_ref)["total"])
    if doc_kind == "wo":
        r = con.execute("SELECT bill_amount FROM work_orders WHERE wo_id=?",
                        (doc_ref,)).fetchone()
        return _money(r["bill_amount"]) if r else Decimal("0.00")
    if doc_kind == "ticket":
        m = ticket_money(con, doc_ref)
        return _money(m["total"]) if m else Decimal("0.00")
    if doc_kind == "sale":
        v = con.execute("SELECT COALESCE(SUM(amount),0) FROM sales "
                        "WHERE group_id=?",
                        (doc_key(con, "sale", doc_ref),)).fetchone()
        return _money(v[0]) if v else Decimal("0.00")
    if doc_kind == "quote":
        # A quote's face is its own lines (quote_totals owns that
        # arithmetic; build 'v' removed the change-order folding).
        return _money(quote_totals(con, doc_ref)["face"])
    if doc_kind == "change":
        return sum((_money(d["total"]) for d in
                    _doc_line_rows(con, "change", doc_ref)),
                   Decimal("0.00"))
    return Decimal("0.00")


def doc_settled(con, doc_kind: str, doc_ref: str) -> dict:
    """What a document has been settled, split by kind: cash-side
    payments (any tender, Cash door included) and credits applied.
    A negative credit memo lowers the credit figure — it re-opens
    amount the payments had settled. Invoices read collections; the
    other documents read doc_collections. Carried mirrors are not
    counted here — they are the invoice-side reflection of a source
    document's rows, which are counted on the source document."""
    if doc_kind == "invoice":
        t = invoice_totals(con, doc_ref)
        return {"payment": _money(t["cash"]), "credit": _money(t["credit"]),
                "total": _money(t["paid"])}
    pay = cred = Decimal("0.00")
    if _doc_collections_exist(con):
        for kind, s in con.execute(
                "SELECT kind, COALESCE(SUM(amount),0) FROM doc_collections "
                "WHERE doc_kind=? AND doc_id=? GROUP BY kind",
                (doc_kind, doc_key(con, doc_kind, doc_ref))):
            if kind == "credit":
                cred = _money(s)
            else:
                pay = _money(s)
    return {"payment": pay, "credit": cred, "total": _ms(pay, cred)}


def doc_balance(con, doc_kind: str, doc_ref: str) -> Decimal:
    """Total minus settled. May stand negative (overpaid) or positive
    (underpaid) indefinitely — nothing in the app nets or closes it."""
    return _ms(doc_total(con, doc_kind, doc_ref),
               -doc_settled(con, doc_kind, doc_ref)["total"])


def _issue_overpay_cm(con, customer_id: str, doc_label: str,
                      amount, applied, pid: str, pay_date: str,
                      who: str, cash_entry_id=None) -> str:
    """The overpayment mechanism (Jason 2026-09-24, extended to every
    money path 2026-10-23): money beyond a document's balance is kept
    as an OPEN credit memo for the customer — auto-issued, unapplied,
    dated the payment date, its note tying it to the payment. The
    credit may sit open indefinitely. Caller owns the transaction."""
    excess = _ms(_money(amount), -_money(applied))
    cm_no = next_cm_id(con)
    ckey = cust_key(con, customer_id)
    con.execute(
        """INSERT INTO credit_memos(cm_no, cm_date, customer_id, face_amount,
           reason, notes, clerk, cash_entry_id) VALUES (?,?,?,?,?,?,?,?)""",
        (cm_no, pay_date or date.today().isoformat(), ckey,
         float(excess), f"Overpayment on {doc_label}",
         f"Auto-created: customer paid ${_money(amount):,.2f}; "
         f"${_money(applied):,.2f} applied to {doc_label} (payment {pid}), "
         f"${excess:,.2f} kept as open credit.",
         who, cash_entry_id))
    # Credit memo multi-line (Jason 2026-10-21): every memo is
    # line-backed — the auto-created memo carries one synthesized
    # line for the excess, described by the memo's reason.
    con.execute(
        """INSERT INTO credit_memo_lines(cm_id, category, item, description,
           qty, uom, rate, amount, tax_exempt, source_invoice_id,
           source_line_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (key_of(con, "credit_memos", cm_no), "Other", "",
         f"Overpayment on {doc_label}", 1, "Each",
         float(excess), float(excess), 0, None, 0))
    return cm_no


def record_payment(con: sqlite3.Connection, invoice_no: str, amount: float, pay_date: str, method: str, ref: str="", clerk: str="", batch_id: str | None = None, commit: bool = True, line_allocs: list | None = None, alloc_source: str = "payment", cash_entry_id=None) -> dict:
    """Apply cash to an invoice. Best practice for overpayments: the invoice
    is paid in full and the excess is kept as an OPEN customer credit memo
    (auto-issued, unapplied) that the clerk can apply to other invoices on
    the /credit page. An overpayment against a settled invoice (balance
    zero or less) posts the same way — nothing applied, the whole amount
    kept as open credit; no path raises a raw error (Jason 2026-10-23).
    Returns {"pay_id","batch_id","applied","credit_memo","credit_amount"}
    — pay_id is None when nothing was applied (the money lives entirely
    in the credit memo).
    Batching (2026-10-15): pass one shared batch_id for every split of a
    multi-invoice payment, with commit=False — the caller commits once, so
    a mid-batch failure rolls the whole payment back (close without commit
    discards the open transaction). batch_id defaults to the row's own
    pay_id (a batch of one).
    Line allocations (2026-10-23): line_allocs=[(invoice_line_id, amount)]
    optionally distributes the applied amount across the invoice's lines;
    it posts inside the same transaction as the payment itself.
    Cash door (2026-10-23): record_cash_entry routes a settling Cash In
    through here with alloc_source='cash' and the entry's id, so the
    settlement is this function's one collections row — linked back to
    the entry by collections.cash_entry_id — and its breakdown rows are
    tagged with the door the money came through."""
    inv=con.execute("SELECT invoice_no, customer_id FROM invoices WHERE invoice_no=?",(invoice_no,)).fetchone()
    if not inv: raise ValueError("Payment must attach to an existing invoice")
    if not invoice_has_lines(con,invoice_no): raise ValueError("Invoice has no invoice lines — cannot take payment")
    amount=_money(amount)
    if amount<=0: raise ValueError("Payment amount must be positive")
    method=(method or "").strip()
    if method not in CASH_METHODS: raise ValueError("Pick " + ", ".join(CASH_METHODS[:-1]) + ", or " + CASH_METHODS[-1])
    who=require_clerk(clerk)
    bal=_money(invoice_balance(con,invoice_no))
    applied=min(amount,bal) if bal>0 else Decimal("0.00")
    excess=amount-applied
    # Optional line breakdown (Jason 2026-10-23): validated against
    # the applied amount BEFORE anything is written — the lines may
    # cover part or all of it, never more; the rest stays blanket.
    cleaned_allocs = (_clean_doc_line_allocs(con, "invoice", invoice_no,
                                             line_allocs, applied, "payment")
                      if line_allocs else [])
    pid=_next_pay_id(con)
    pkey=_next_pay_key(con)
    batch_id = batch_id or pid
    posted_pid = None
    if applied > Decimal("0.005"):
        con.execute("""INSERT INTO collections(id,pay_id,batch_id,pay_date,invoice_id,method,amount,ref_no,kind,clerk,applied_amount,unapplied_amount,cash_entry_id) VALUES (?,?,?,?,?,?,?,?, 'payment',?,?,?,?)""",(pkey,pid,batch_id,pay_date,key_of(con, "invoices", invoice_no),method,float(applied),ref,who,float(applied),0.0,cash_entry_id))
        posted_pid = pid
    cm_no=None
    if excess>Decimal("0.009"):
        cm_no=_issue_overpay_cm(
            con, inv["customer_id"], invoice_no, amount, applied, pid,
            pay_date, who,
            cash_entry_id=(cash_entry_id if posted_pid is None else None))
    if cleaned_allocs:
        _ensure_payalloc_table(con)
        _write_line_allocs(
            con, source=alloc_source, pay_key=pkey,
            cash_entry_id=cash_entry_id,
            batch_id=batch_id, doc_kind="invoice", doc_ref=invoice_no,
            pay_date=pay_date, clerk=who, applied=applied,
            cleaned=cleaned_allocs)
    _refresh_invoice_status(con,invoice_no)
    if commit:
        con.commit()
    return {"pay_id":posted_pid,"batch_id":batch_id,"applied":float(applied),"credit_memo":cm_no,"credit_amount":float(excess)}


def _carried_invoice(con, doc_kind: str, doc_ref: str):
    """The invoice a document's settlements already carried onto, if
    any (the collections mirror rows marked carried_from — stored in
    kind:key form since build 'v')."""
    r = con.execute(
        "SELECT invoice_id FROM collections WHERE carried_from=? "
        "LIMIT 1",
        (f"{doc_kind}:{doc_key(con, doc_kind, doc_ref)}",)).fetchone()
    return doc_num(con, "invoice", r[0]) if r else None


def quote_money_block(con, qno: str):
    """Why money may not be taken on quote qno right now, or None.
    The quote money door (Jason 2026-10-23): a quote takes money
    while it is a live quote — a deposit or part payment against the
    work it proposes. Once the quote has converted and its money
    carried onto an invoice, the money lives on the invoice. A Void
    or Declined quote is closed."""
    r = con.execute("SELECT status FROM quotes WHERE quote_no=?",
                    (qno,)).fetchone()
    if not r:
        return None
    inv = _carried_invoice(con, "quote", qno)
    if inv:
        return (f"{qno} has converted — its money carried onto "
                f"{inv}; take the money on the invoice")
    if r["status"] == "Converted":
        return f"{qno} has converted — take the money on its documents"
    if r["status"] in ("Void", "Declined"):
        return f"{qno} is {r['status'].lower()} — no money"
    return None


def record_doc_payment(con: sqlite3.Connection, doc_kind: str, doc_ref: str, amount: float, pay_date: str, method: str, ref: str="", clerk: str="", batch_id: str | None = None, commit: bool = True, line_allocs: list | None = None, alloc_source: str = "payment", cash_entry_id=None) -> dict:
    """Apply money to a work order, a rental ticket, a sale, a quote,
    or a change order — the same rules as record_payment, on the
    document's own ledger (doc_collections): any tender; blanket or
    line by line (line_allocs=[(line_id, amount)] against the
    document's lines); overpayment beyond the document's balance is
    kept as an OPEN credit memo, on this path exactly as on the
    invoice path; a payment against a settled document posts as pure
    credit. A Change Order settles independently of the document it
    is associated with, in both directions (Jason 2026-10-25).
    One transaction: payment row, breakdown rows, and credit memo
    post together or not at all (commit=False + the caller's commit,
    the batching pattern). Returns the record_payment dict shape;
    pay_id is None when nothing was applied."""
    if doc_kind not in ("wo", "ticket", "sale", "quote", "change"):
        raise ValueError("Money applies to a work order, rental ticket, sale, quote, or change order here")
    _ensure_doc_collections(con)
    cust = _doc_customer(con, doc_kind, doc_ref)
    if cust is None and doc_kind != "wo":
        raise ValueError(f"Unknown {DOC_LABELS[doc_kind]} {doc_ref}")
    if doc_kind == "wo":
        w = con.execute("SELECT charge_to, customer_id FROM work_orders "
                        "WHERE wo_id=?", (doc_ref,)).fetchone()
        if not w:
            raise ValueError(f"Unknown WO {doc_ref}")
        if w["charge_to"] != "customer":
            raise ValueError(f"{doc_ref} is internal work — it carries no customer bill")
        cust = cust_code(con, w["customer_id"])
    if not cust:
        raise ValueError(f"{doc_ref} has no customer")
    if doc_kind == "quote":
        _blk = quote_money_block(con, doc_ref)
        if _blk:
            raise ValueError(_blk)
    if doc_kind in ("wo", "ticket"):
        _tbl, _idc = (("work_orders", "wo_id") if doc_kind == "wo"
                      else ("tickets", "ticket_id"))
        _inv = con.execute(
            f"SELECT invoice_id FROM {_tbl} WHERE {_idc}=?",
            (doc_ref,)).fetchone()
        if _inv and _inv["invoice_id"]:
            raise ValueError(
                f"{doc_ref} is on {doc_num(con, 'invoices', _inv['invoice_id'])} — take the money "
                "on the invoice")
    amount = _money(amount)
    if amount <= 0:
        raise ValueError("Payment amount must be positive")
    method = (method or "").strip()
    if method not in CASH_METHODS:
        raise ValueError("Pick " + ", ".join(CASH_METHODS[:-1]) + ", or " + CASH_METHODS[-1])
    who = require_clerk(clerk)
    bal = doc_balance(con, doc_kind, doc_ref)
    applied = min(amount, bal) if bal > 0 else Decimal("0.00")
    excess = amount - applied
    cleaned_allocs = (_clean_doc_line_allocs(con, doc_kind, doc_ref,
                                             line_allocs, applied, "payment")
                      if line_allocs else [])
    pid = _next_pay_id(con)
    pkey = _next_pay_key(con)
    batch_id = batch_id or pid
    posted_pid = None
    if applied > Decimal("0.005"):
        con.execute(
            """INSERT INTO doc_collections(id,pay_id,batch_id,pay_date,doc_kind,
               doc_id,customer_id,method,amount,ref_no,kind,clerk,
               applied_amount,unapplied_amount,cash_entry_id)
               VALUES (?,?,?,?,?,?,?,?,?,?, 'payment',?,?,0.0,?)""",
            (pkey, pid, batch_id, pay_date, doc_kind,
             doc_key(con, doc_kind, doc_ref), cust_key(con, cust), method,
             float(applied), ref, who, float(applied), cash_entry_id))
        posted_pid = pid
    cm_no = None
    if excess > Decimal("0.009"):
        cm_no = _issue_overpay_cm(
            con, cust, f"{DOC_LABELS[doc_kind]} {doc_ref}", amount,
            applied, pid, pay_date, who,
            cash_entry_id=(cash_entry_id if posted_pid is None else None))
    if cleaned_allocs:
        _ensure_payalloc_table(con)
        _write_line_allocs(
            con, source=alloc_source, pay_key=pkey,
            cash_entry_id=cash_entry_id, batch_id=batch_id,
            doc_kind=doc_kind, doc_ref=doc_ref, pay_date=pay_date,
            clerk=who, applied=applied, cleaned=cleaned_allocs)
    if commit:
        con.commit()
    return {"pay_id": posted_pid, "batch_id": batch_id,
            "applied": float(applied), "credit_memo": cm_no,
            "credit_amount": float(excess)}


def _apply_doc_credit_rows(con, cm_no: str, customer_id: str,
                           doc_applies: list, pay_date: str,
                           clerk: str = "") -> float:
    """doc_applies = [(doc_kind, doc_ref, amount, line_allocs|None)].
    A credit applied against a work order, rental ticket, sale,
    quote, or change order stays a credit (Jason 2026-10-23): one
    doc_collections row (kind 'credit') plus its breakdown rows
    (source 'credit'), in the same allocation model as payments.
    Amounts are signed by the memo's direction — a negative credit
    memo applies negative amounts, re-opening settled amount.
    Returns the total applied this call. Caller owns the transaction
    and the face check."""
    _cm = con.execute("SELECT face_amount FROM credit_memos "
                      "WHERE cm_no=?", (cm_no,)).fetchone()
    direction = -1 if (_cm and float(_cm["face_amount"]) < 0) else 1
    used = 0.0
    seen = set()
    for doc_kind, doc_ref, raw, line_allocs in doc_applies:
        doc_kind = (doc_kind or "").strip()
        doc_ref = (doc_ref or "").strip()
        if doc_kind not in ("wo", "ticket", "sale", "quote", "change") or not doc_ref:
            raise ValueError("A credit applies to an invoice, work order, rental ticket, sale, quote, or change order")
        try:
            amt = direction * abs(_money(raw))
        except Exception:
            raise ValueError(f"Bad apply amount on {doc_ref}") from None
        if amt == 0:
            continue
        key = (doc_kind, doc_ref)
        if key in seen:
            raise ValueError(f"{doc_ref} listed twice")
        seen.add(key)
        if _doc_customer(con, doc_kind, doc_ref) != customer_id:
            raise ValueError(f"{doc_ref} belongs to another customer")
        if doc_kind == "quote":
            _blk = quote_money_block(con, doc_ref)
            if _blk:
                raise ValueError(_blk)
        if doc_kind in ("wo", "ticket"):
            _tbl, _idc = (("work_orders", "wo_id") if doc_kind == "wo"
                          else ("tickets", "ticket_id"))
            _inv = con.execute(
                f"SELECT invoice_id FROM {_tbl} WHERE {_idc}=?",
                (doc_ref,)).fetchone()
            if _inv and _inv["invoice_id"]:
                raise ValueError(
                    f"{doc_ref} is on {doc_num(con, 'invoices', _inv['invoice_id'])} — apply the "
                    "credit on the invoice")
        if direction > 0:
            bal = doc_balance(con, doc_kind, doc_ref)
            if amt - bal > Decimal("0.009"):
                raise ValueError(f"{doc_ref} balance is ${bal:,.2f}")
        else:
            # A negative credit re-opens settled amount only: it may
            # not exceed what the document has settled so far, and so
            # never pushes a balance above the document's own total.
            settled = doc_settled(con, doc_kind, doc_ref)["total"]
            if -amt - settled > Decimal("0.009"):
                raise ValueError(
                    f"{doc_ref} has ${settled:,.2f} settled — a "
                    "negative credit re-opens settled amount only")
        cleaned_allocs = []
        if line_allocs:
            _ensure_payalloc_table(con)
            cleaned_allocs = _clean_doc_line_allocs(
                con, doc_kind, doc_ref, line_allocs, amt, "credit",
                direction=direction)
        pid = _next_pay_id(con)
        pkey = _next_pay_key(con)
        cmkey = key_of(con, "credit_memos", cm_no)
        con.execute(
            """INSERT INTO doc_collections(id,pay_id,pay_date,doc_kind,doc_id,
               customer_id,method,amount,ref_no,kind,cm_id,clerk)
               VALUES (?,?,?,?,?,?,?,?,?, 'credit', ?, ?)""",
            (pkey, pid, pay_date, doc_kind,
             doc_key(con, doc_kind, doc_ref), cust_key(con, customer_id),
             "Credit memo", float(amt), cm_no, cmkey, clerk or ""))
        if cleaned_allocs:
            _write_line_allocs(
                con, source="credit", pay_key=pkey, cash_entry_id=None,
                batch_id=None, doc_kind=doc_kind, doc_ref=doc_ref,
                pay_date=pay_date, clerk=clerk or "", applied=amt,
                cleaned=cleaned_allocs)
        used += float(amt)
    return used


def apply_doc_credit(con: sqlite3.Connection, cm_no: str, doc_kind: str,
                     doc_ref: str, amount, pay_date: str | None = None,
                     clerk: str = "", line_allocs: list | None = None,
                     commit: bool = True) -> float:
    """Apply open credit against one work order, rental ticket, sale,
    or quote — blanket or line by line. The mirror of
    apply_open_credit for the other documents. A negative memo
    applies negative amounts (re-opening settled amount) under the
    same guardrails."""
    info = credit_open(con, cm_no)
    if abs(info["unapplied"]) <= 0.009:
        raise ValueError("This credit memo is fully applied")
    who = require_clerk(clerk)
    d = pay_date or date.today().isoformat()
    used = _apply_doc_credit_rows(
        con, cm_no, info["customer_id"],
        [(doc_kind, doc_ref, amount, line_allocs)], d, who)
    if used == 0:
        raise ValueError("Enter an apply amount")
    if abs(used) - abs(info["unapplied"]) > 0.009:
        raise ValueError(f"Only ${abs(info['unapplied']):,.2f} left on {cm_no}")
    if commit:
        con.commit()
    return used


def _carry_doc_settlements(con, src_kind: str, src_ref: str, ino: str,
                           line_map: dict, doc_invoice_total,
                           customer_id: str, inv_date: str) -> float:
    """Carry semantics (Jason 2026-10-23, universality): when a work
    order or ticket is invoiced, money already settled against it —
    payments, credits, settling cash, blanket or by line — is
    mirrored onto the invoice so the invoice nets it out exactly
    once. Per source money row, oldest first: one collections row
    reusing the row's own pay_id, marked carried_from
    '{src_kind}:{src_ref}', plus mirror allocation rows (carried=1)
    — source line rows land on the corresponding invoice line
    (line_map: source line_id -> invoice line_id, built from
    invoice_lines.source_line_id), blanket rows stay blanket, and a
    line's overflow folds to blanket. The carried total is capped at
    the invoice total of the lines this document produced; any
    settled excess beyond it is kept as an OPEN credit memo for the
    customer, audit-noted to the source and the invoice — money is
    never scaled, split silently, or dropped. The source document's
    own ledger is untouched: its rows remain the originals every
    ledger total counts; the mirrors are excluded from money totals
    and exist so invoice derivation (which reads collections) and
    invoice line states see the settlement. Caller owns the
    transaction (create_invoice). Returns the carried amount."""
    if not _doc_collections_exist(con):
        return 0.0
    src_key = doc_key(con, src_kind, src_ref)
    rows = con.execute(
        "SELECT * FROM doc_collections WHERE doc_kind=? AND doc_id=? "
        "ORDER BY pay_date, pay_id", (src_kind, src_key)).fetchall()
    settled = sum((_money(r["amount"]) for r in rows), Decimal("0.00"))
    if settled <= Decimal("0.009"):
        return 0.0
    cap = _money(doc_invoice_total)
    carry_room = cap
    if settled - cap > Decimal("0.009"):
        _issue_overpay_cm(
            con, customer_id,
            f"{DOC_LABELS[src_kind]} {src_ref}", settled, cap,
            f"carry to {ino}", inv_date, "")
    # Per-invoice-line carried capacity (amount + its tax).
    line_room: dict = {}
    for il_id in set(line_map.values()):
        r = con.execute(
            "SELECT amount, tax_amount FROM invoice_lines WHERE line_id=?",
            (il_id,)).fetchone()
        if r:
            line_room[il_id] = _line_total(r)
    carried_total = Decimal("0.00")
    line_carried: dict = {}
    for r in rows:
        amt_r = _money(r["amount"])
        if amt_r > 0:
            take = min(amt_r, carry_room)
        elif amt_r < 0:
            # A negative credit row un-carries: it mirrors as a
            # negative collections row, but never more than this
            # carry has put on so far (netting, never new debt).
            take = max(amt_r, -carried_total)
        else:
            continue
        if abs(take) <= Decimal("0.005"):
            continue
        if con.execute("SELECT 1 FROM collections WHERE id=?",
                       (r["id"],)).fetchone():
            continue  # already mirrored onto an invoice — never twice
        con.execute(
            """INSERT INTO collections(id,pay_id,batch_id,pay_date,invoice_id,
               method,amount,ref_no,kind,cm_id,clerk,applied_amount,
               unapplied_amount,cash_entry_id,carried_from)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (r["id"], r["pay_id"], r["batch_id"], r["pay_date"],
             key_of(con, "invoices", ino), r["method"],
             float(take), r["ref_no"], r["kind"], r["cm_id"], r["clerk"],
             (float(take) if r["kind"] == "payment" else None), 0.0,
             r["cash_entry_id"], f"{src_kind}:{src_key}"))
        # Mirror this row's breakdown: lines first (onto the mapped
        # invoice lines, capped at each line's remaining capacity),
        # the rest as the blanket remainder — the mirror rows always
        # sum back to the carried amount, like any breakdown. A
        # negative row mirrors negative amounts onto the same lines,
        # capped at what this carry put on each line.
        src_allocs = (list_payment_allocations(con, pay_id=r["pay_id"])
                      if _payalloc_exists(con) else [])
        rest = take
        cleaned = []
        for a in src_allocs:
            if a["line_id"] is None:
                continue
            tgt = line_map.get(int(a["line_id"]))
            if take > 0:
                if rest <= Decimal("0.005"):
                    break
                if tgt is None or tgt not in line_room:
                    continue
                amt2 = min(_money(a["amount"]), line_room[tgt], rest)
                if amt2 <= Decimal("0.005"):
                    continue
                line_carried[tgt] = _ms(line_carried.get(tgt, Decimal("0.00")), amt2)
            else:
                if rest >= Decimal("-0.005"):
                    break
                if tgt is None:
                    continue
                amt2 = -min(abs(_money(a["amount"])),
                            line_carried.get(tgt, Decimal("0.00")),
                            abs(rest))
                if abs(amt2) <= Decimal("0.005"):
                    continue
                line_carried[tgt] = _ms(line_carried.get(tgt, Decimal("0.00")), amt2)
            cleaned.append((tgt, amt2))
            if tgt in line_room:
                line_room[tgt] = _ms(line_room[tgt], -amt2)
            rest = _ms(rest, -amt2)
        _write_line_allocs(
            con, source=r["kind"] if r["kind"] == "credit" else
            ("cash" if r["cash_entry_id"] else "payment"),
            pay_key=r["id"], cash_entry_id=r["cash_entry_id"],
            batch_id=r["batch_id"], doc_kind="invoice", doc_ref=ino,
            pay_date=r["pay_date"], clerk=r["clerk"] or "",
            applied=take, cleaned=cleaned, carried=1)
        carried_total = _ms(carried_total, take)
        carry_room = _ms(cap, -carried_total)
    return float(carried_total)


def next_cm_id(con: sqlite3.Connection) -> str:
    while True:
        n = _reserve_counter(con, "next_cm", 1001)
        cno = f"CM-{n:04d}"
        if not con.execute("SELECT 1 FROM credit_memos WHERE cm_no=?", (cno,)).fetchone():
            return cno
def credit_applied(con: sqlite3.Connection, cm_no: str) -> float:
    """Applied totals read BOTH ledgers (Jason 2026-10-23,
    universality): credits applied against instruments live in
    collections; credits applied against work orders, tickets, and
    sales live in doc_collections. Carried mirrors are not counted —
    they reuse the source row's memo through the source ledger."""
    row = con.execute(
        "SELECT COALESCE(SUM(COALESCE(applied_amount,amount)),0) FROM collections WHERE cm_id=? AND kind='credit'",
        (key_of(con, "credit_memos", cm_no),),
    ).fetchone()
    total = float(row[0] or 0)
    if _doc_collections_exist(con):
        row2 = con.execute(
            "SELECT COALESCE(SUM(amount),0) FROM doc_collections "
            "WHERE cm_id=? AND kind='credit'",
            (key_of(con, "credit_memos", cm_no),)).fetchone()
        total += float(row2[0] or 0)
    return total
def credit_lines(con: sqlite3.Connection, cm_no: str) -> list[dict]:
    """The memo's line items, in entry order (credit memo multi-line,
    Jason 2026-10-21). Every memo is line-backed: memos issued without
    explicit lines carry one synthesized line, and the legacy migration
    backfills one line per pre-existing memo. A pre-migration book has
    no lines table yet and reads as no lines."""
    try:
        rows = con.execute(
            "SELECT * FROM credit_memo_lines WHERE cm_id=? ORDER BY line_id",
            (key_of(con, "credit_memos", cm_no),),
        ).fetchall()
    except sqlite3.Error:
        return []
    out = []
    for r in rows:
        exempt = bool(_row_get(r, "tax_exempt", 0))
        out.append({
            "line_id": int(_row_get(r, "line_id", 0) or 0),
            "cm_no": _row_get(r, "cm_no", cm_no) or cm_no,
            "category": _row_get(r, "category", "Other") or "Other",
            "item": _row_get(r, "item", "") or "",
            "description": _row_get(r, "description", "") or "",
            "qty": float(_row_get(r, "qty", 1) or 0),
            "uom": _row_get(r, "uom", "Each") or "Each",
            "rate": float(_row_get(r, "rate", 0) or 0),
            "amount": float(_row_get(r, "amount", 0) or 0),
            "tax_exempt": exempt,
            "taxed": not exempt,
            "source_invoice_no": num_of(con, "invoices", _row_get(r, "source_invoice_id")) or "",
            "source_line_id": int(_row_get(r, "source_line_id", 0) or 0),
        })
    return out
def credit_open(con: sqlite3.Connection, cm_no: str) -> dict:
    cm = con.execute("SELECT * FROM credit_memos WHERE cm_no=?", (cm_no,)).fetchone()
    if not cm:
        raise ValueError("Unknown credit memo")
    applied = credit_applied(con, cm_no)
    face = float(cm["face_amount"])
    return {
        "cm_no": cm["cm_no"],
        "cm_date": str(cm["cm_date"])[:10],
        "customer_id": cust_code(con, cm["customer_id"]),
        "reason": cm["reason"],
        "notes": cm["notes"] or "",
        "face": round(face, 2),
        "applied": round(applied, 2),
        "unapplied": round(face - applied, 2),
        "lines": credit_lines(con, cm_no),
    }
def _apply_credit_rows(con, cm_no: str, customer_id: str, applies: list, pay_date: str,
                      clerk: str = "", line_allocs_map: dict | None = None) -> float:
    """applies = [(invoice_no, amount), ...]. Returns total applied
    this call (signed). Line allocations (Jason 2026-10-23):
    line_allocs_map may carry {invoice_no: [(line_id, amount)]} — the
    mirror of a payment's breakdown, so a credit can close a specific
    line (the disputed remainder). Same allocation table, source
    'credit'; a credited amount counts like paid for that line.
    A NEGATIVE memo (Jason 2026-10-23) applies with the opposite
    sign: the operator posts positive magnitudes; the stored rows
    are negative and re-open settled amount. Guardrails: a negative
    application may not exceed what the target has settled (blanket:
    the invoice's paid total; per line: that line's settled total) —
    it never pushes a balance above the document's own total and
    never drives a line's net settled below zero."""
    _cm = con.execute("SELECT face_amount FROM credit_memos "
                      "WHERE cm_no=?", (cm_no,)).fetchone()
    direction = -1 if (_cm and float(_cm["face_amount"]) < 0) else 1
    used = 0.0
    seen = set()
    for invoice_no, raw in applies:
        invoice_no = (invoice_no or "").strip()
        if not invoice_no:
            continue
        try:
            amt = direction * abs(float(raw))
        except (TypeError, ValueError):
            raise ValueError(f"Bad apply amount on {invoice_no}") from None
        if amt == 0:
            continue
        if invoice_no in seen:
            raise ValueError(f"{invoice_no} listed twice")
        seen.add(invoice_no)
        inv = con.execute(
            "SELECT invoice_no, customer_id FROM invoices WHERE invoice_no=?",
            (invoice_no,),
        ).fetchone()
        if not inv:
            raise ValueError(f"{invoice_no} is not an invoice")
        if inv["customer_id"] != cust_key(con, customer_id):
            raise ValueError(f"{invoice_no} belongs to another customer")
        if not invoice_has_lines(con, invoice_no):
            raise ValueError(f"{invoice_no} has no Rental Tickets or Work Orders")
        if direction > 0:
            bal = invoice_balance(con, invoice_no)
            if amt - bal > 0.009:
                raise ValueError(f"{invoice_no} balance is ${bal:,.2f}")
        else:
            settled = _money(invoice_totals(con, invoice_no)["paid"])
            if -amt - float(settled) > 0.009:
                raise ValueError(
                    f"{invoice_no} has ${settled:,.2f} settled — a "
                    "negative credit re-opens settled amount only")
        cleaned_allocs = []
        if line_allocs_map and line_allocs_map.get(invoice_no):
            _ensure_payalloc_table(con)
            cleaned_allocs = _clean_line_allocs(
                con, invoice_no, line_allocs_map[invoice_no], amt,
                "credit", direction=direction)
        pid = _next_pay_id(con)
        pkey = _next_pay_key(con)
        con.execute(
            """INSERT INTO collections(id,pay_id, pay_date, invoice_id, method, amount, ref_no, kind, cm_id, clerk)
               VALUES (?,?,?,?,?,?,?, 'credit', ?, ?)""",
            (pkey, pid, pay_date, key_of(con, "invoices", invoice_no),
             "Credit memo", amt, cm_no,
             key_of(con, "credit_memos", cm_no), clerk or ""),
        )
        if cleaned_allocs:
            _write_line_allocs(
                con, source="credit", pay_key=pkey, cash_entry_id=None,
                batch_id=None, doc_kind="invoice", doc_ref=invoice_no,
                pay_date=pay_date,
                clerk=clerk or "", applied=amt, cleaned=cleaned_allocs)
        _refresh_invoice_status(con, invoice_no)
        used += amt
    return used
def issue_credit_memo(
    con: sqlite3.Connection,
    customer_id: str,
    face_amount: float,
    reason: str,
    applies: list | None = None,
    cm_date: str | None = None,
    notes: str = "",
    clerk: str = "",
    lines: list | None = None,
    cm_no: str | None = None,
    line_allocs_map: dict | None = None,
    doc_applies: list | None = None,
) -> str:
    """Open a credit memo. Apply all, part, or none to existing invoices of that customer.

    doc_applies (Jason 2026-10-23, universality): [(doc_kind, doc_ref,
    amount, line_allocs|None)] — the same memo may also be applied, in
    the same transaction, against the customer's work orders, tickets,
    and sales; a credit stays a credit, applied in one allocation
    model across all document kinds. A NEGATIVE memo (a virtual
    debit memo — Jason 2026-10-23) requires a note and re-opens
    settled amount; see the guardrails in _apply_credit_rows.

    Multi-line (Jason 2026-10-21): when lines are supplied, the memo's
    face is the sum of the cleaned line amounts — the passed face_amount
    is ignored. With no usable lines, the memo keeps the single-amount
    behavior and gains one synthesized line (description = reason), so
    every memo is line-backed."""
    cust = con.execute("SELECT customer_id FROM customers WHERE customer_id=?", (customer_id,)).fetchone()
    if not cust:
        raise ValueError("Unknown customer")
    # Clean each supplied line the way save_quote cleans quote lines.
    cleaned = []
    for ln in lines or []:
        desc = (ln.get("description") or "").strip()
        item = (ln.get("item") or "").strip()
        try:
            qty = float(ln.get("qty") or 1)
        except (TypeError, ValueError):
            qty = 1
        if qty <= 0:
            qty = 1
        rate = float(ln.get("rate") or 0)
        amount = round(qty * rate, 2)
        if not item and not desc and rate == 0 and amount == 0:
            continue
        cleaned.append({
            "category": clean_line_type(con, ln.get("category") or ln.get("type")),
            "item": item,
            "description": desc,
            "qty": qty,
            "uom": clean_line_uom(con, ln.get("uom")),
            "rate": rate,
            "amount": amount,
            "tax_exempt": int(bool(ln.get("tax_exempt"))),
            "source_invoice_no": str(ln.get("source_invoice_no") or ""),
            "source_line_id": int(ln.get("source_line_id") or 0),
        })
    if cleaned:
        face = round(sum(ln["amount"] for ln in cleaned), 2)
        if face == 0:
            raise ValueError("Credit amount must not be zero")
    else:
        try:
            face = float(face_amount)
        except (TypeError, ValueError):
            raise ValueError("Credit amount must be a number") from None
        if face == 0:
            raise ValueError("Credit amount must not be zero")
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("Reason is required")
    if face < 0 and not (notes or "").strip():
        # Jason 2026-10-23: a negative credit (a virtual debit memo)
        # is allowed for the operator's bookkeeping — WITH A NOTE
        # AND RECORD. No note, no negative memo.
        raise ValueError(
            "A negative credit memo requires a note — the note is "
            "the record of why the amount was re-opened")
    d = cm_date or date.today().isoformat()
    applies = applies or []
    alloc_map = line_allocs_map or {}
    who = require_clerk(clerk)
    _cm_in = (cm_no or "").strip()
    cm_no = (validate_new_doc_no(con, "credit_memos", "cm_no", _cm_in, "credit memo")
             if _cm_in else next_cm_id(con))
    con.execute(
        """INSERT INTO credit_memos(cm_no, cm_date, customer_id, face_amount, reason, notes, clerk)
           VALUES (?,?,?,?,?,?,?)""",
        (cm_no, d, cust_key(con, customer_id), face, reason, notes or "", who),
    )
    cmkey = key_of(con, "credit_memos", cm_no)
    if not cleaned:
        cleaned = [{
            "category": "Other", "item": "", "description": reason,
            "qty": 1, "uom": "Each", "rate": face, "amount": face,
            "tax_exempt": 0, "source_invoice_no": "", "source_line_id": 0,
        }]
    con.executemany(
        """INSERT INTO credit_memo_lines(cm_id, category, item, description, qty, uom, rate, amount, tax_exempt, source_invoice_id, source_line_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        [(cmkey, ln["category"], ln["item"], ln["description"], ln["qty"],
          ln["uom"], ln["rate"], ln["amount"], ln["tax_exempt"],
          key_of(con, "invoices", ln["source_invoice_no"]) if ln["source_invoice_no"] else None,
          ln["source_line_id"]) for ln in cleaned],
    )
    # Backward-compat readers: the memo row mirrors its first line's
    # Type/Unit. Guarded on the columns existing — legacy books may
    # lack them until the migration adds them.
    _cmcols = [r[1] for r in con.execute("PRAGMA table_info(credit_memos)")]
    if "category" in _cmcols and "uom" in _cmcols:
        con.execute(
            "UPDATE credit_memos SET category=?, uom=? WHERE cm_no=?",
            (cleaned[0]["category"], cleaned[0]["uom"], cm_no),
        )
    used = _apply_credit_rows(con, cm_no, customer_id, applies, d, who,
                              line_allocs_map=alloc_map)
    if doc_applies:
        _ensure_doc_collections(con)
        used += _apply_doc_credit_rows(con, cm_no, customer_id,
                                       doc_applies, d, who)
    if abs(used) - abs(face) > 0.009:
        raise ValueError("Applied more than the credit memo face")
    con.commit()
    return cm_no
def apply_open_credit(
    con: sqlite3.Connection,
    cm_no: str,
    applies: list,
    pay_date: str | None = None,
    clerk: str = "",
    line_allocs_map: dict | None = None,
    doc_applies: list | None = None,
) -> float:
    """Use leftover credit against more invoices of the same customer.
    line_allocs_map optionally breaks an application down by invoice
    line, as at issue time; doc_applies takes the credit against the
    customer's work orders, rental tickets, sales, and quotes instead
    of (or beside) invoices."""
    info = credit_open(con, cm_no)
    if abs(info["unapplied"]) <= 0.009:
        raise ValueError("This credit memo is fully applied")
    who = require_clerk(clerk)
    d = pay_date or date.today().isoformat()
    used = _apply_credit_rows(con, cm_no, info["customer_id"], applies, d, who,
                              line_allocs_map=line_allocs_map)
    if doc_applies:
        _ensure_doc_collections(con)
        used += _apply_doc_credit_rows(con, cm_no, info["customer_id"],
                                       doc_applies, d, who)
    if used == 0:
        raise ValueError("Enter at least one apply amount")
    if abs(used) - abs(info["unapplied"]) > 0.009:
        raise ValueError(f"Only ${abs(info['unapplied']):,.2f} left on {cm_no}")
    con.commit()
    return used
def list_open_credits(con: sqlite3.Connection, customer_id: str | None = None) -> list[dict]:
    q = "SELECT cm_no FROM credit_memos"
    args: list = []
    if customer_id:
        q += " WHERE customer_id=?"
        args.append(cust_key(con, customer_id))
    q += " ORDER BY cm_date DESC, cm_no DESC"
    out = []
    for r in con.execute(q, args):
        info = credit_open(con, r["cm_no"])
        if abs(info["unapplied"]) > 0.009:
            out.append(info)
    return out
def list_open_invoices(con: sqlite3.Connection, customer_id: str | None = None) -> list[dict]:
    q = """SELECT i.invoice_no, i.invoice_date, i.status, i.customer_id, c.account_name
           FROM invoices i JOIN customers c ON c.id=i.customer_id"""
    args: list = []
    if customer_id:
        q += " WHERE i.customer_id=?"
        args.append(cust_key(con, customer_id))
    q += " ORDER BY i.invoice_date DESC"
    balances = invoice_totals_batch(con)
    out = []
    for r in con.execute(q, args):
        if not invoice_has_lines(con, r["invoice_no"]):
            continue
        tot = balances.get(r["invoice_no"])
        if not tot or tot["balance"] <= 0.009:
            continue
        out.append({
            "invoice_no": r["invoice_no"],
            "invoice_date": str(r["invoice_date"])[:10],
            "status": r["status"],
            "customer_id": cust_code(con, r["customer_id"]),
            "account_name": r["account_name"],
            "total": tot["total"],
            "paid": tot["paid"],
            "cash": tot["cash"],
            "credit": tot["credit"],
            "balance": tot["balance"],
        })
    return out


def big_fish_invoices(con: sqlite3.Connection, min_n: int = 8, factor: float = 2.0) -> dict:
    """Invoices that are big *for this yard*: open balance >= factor x the
    median open balance. Weighs the book against itself, so a one-man shop
    and a big yard each get their own definition of "big". Returns
    {"invoice_nos": set, "median": float}. Empty set when the book is too
    small to have a meaningful middle (fewer than min_n open invoices)."""
    bals = sorted(
        inv["balance"] for inv in list_open_invoices(con)
        if inv["balance"] > 0.009 and inv["status"] != "Draft")
    if len(bals) < min_n:
        return {"invoice_nos": set(), "median": 0.0}
    mid = len(bals) // 2
    median = (bals[mid] + bals[~mid]) / 2.0
    if median <= 0:
        return {"invoice_nos": set(), "median": 0.0}
    big = {inv["invoice_no"] for inv in list_open_invoices(con)
           if inv["status"] != "Draft" and inv["balance"] >= factor * median}
    return {"invoice_nos": big, "median": round(median, 2)}


def next_quote_id(con) -> str:
    return _next_doc(con, "next_quote", "QT", "quotes", "quote_no")
def next_co_id(con) -> str:
    return _next_doc(con, "next_co", "CO", "change_orders", "co_no")
def _line_amount(qty, rate) -> float:
    return round(float(qty or 0) * float(rate or 0), 2)
def save_quote(con, header: dict, lines: list) -> str:
    cid = header.get("customer_id") or ""
    if not con.execute("SELECT 1 FROM customers WHERE customer_id=?", (cid,)).fetchone():
        raise ValueError("Pick a customer")
    site = header.get("site_id") or None
    if site and not con.execute("SELECT 1 FROM sites WHERE site_id=?", (site,)).fetchone():
        raise ValueError("Unknown site")
    clean = []
    for ln in lines:
        desc = (ln.get("description") or "").strip()
        if not desc:
            continue
        # Global line-item row (2026-10-15): Type is inv_cat, Unit is
        # inv_uom. The asset link only sticks on Rental lines — on any
        # other Type the Item field is hand-filled text, not a unit.
        kind = clean_line_type(con, ln.get("kind"))
        uom = clean_line_uom(con, ln.get("uom"))
        qty = float(ln.get("qty") or 0)
        rate = float(ln.get("rate") or 0)
        if qty <= 0:
            continue
        aid = (ln.get("asset_id") or "").strip() or None
        if kind != "Rental":
            aid = None
        elif aid:
            # Engine class foundation (Phase 5, Jason 2026-10-24): a
            # quote proposes the rental motion, so a Rental line's
            # unit stands under the same guard as a ticket — rentable
            # class, Active status; anything else is refused here, not
            # merely left out of the picker.
            rentable_or_raise(con, aid, use="quote")
        # A Rental line's Unit drives the converted ticket's rate type
        # (Days→Day, Weeks→Week, Months→Monthly, Hours→Hour); any other
        # Unit keeps the line's rate_unit as posted.
        ru = clean_rate_unit(ln.get("rate_unit"))
        if kind == "Rental":
            ru = uom_to_rate_type(uom) or ru
        item = (ln.get("item") or "").strip()
        clean.append((kind, aid, item, desc, qty, rate, ru, uom, _line_amount(qty, rate)))
    if not clean:
        raise ValueError("Add at least one quote line")
    # Expiry is required on every quote but never blocks: a blank value falls
    # back to the 30-day business default from the quote date.
    valid_until = (header.get("valid_until") or "").strip()
    if not valid_until:
        try:
            _base = date.fromisoformat(str(header.get("quote_date") or date.today().isoformat())[:10])
        except ValueError:
            _base = date.today()
        try:
            days = max(1, int(get_option(con, "quote_valid_days", "30") or 30))
        except (TypeError, ValueError):
            days = 30
        valid_until = (_base + timedelta(days=days)).isoformat()
    _qn_in = (header.get("quote_no") or "").strip()
    exists = (con.execute("SELECT status FROM quotes WHERE quote_no=?", (_qn_in,)).fetchone()
              if _qn_in else None)
    if exists:
        qno = _qn_in
    elif _qn_in:
        # A number that matches nothing is a creation (Batch 3 #14):
        # save_quote doubles as the edit path, so existence above is
        # what separates an edit from a duplicate.
        qno = validate_new_doc_no(con, "quotes", "quote_no", _qn_in, "quote")
    else:
        qno = next_quote_id(con)
    if exists and exists["status"] in ("Accepted", "Converted", "Void"):
        raise ValueError("Cannot edit an accepted, converted, or void quote")
    vals = (
        header.get("quote_date") or date.today().isoformat(),
        cust_key(con, cid),
        key_of(con, "sites", site) if site else None,
        header.get("job_name") or "", header.get("afe") or "",
        header.get("po") or "", valid_until,
        header.get("status") or (exists["status"] if exists else "Draft"),
        header.get("notes") or "", require_clerk(header.get("clerk")), qno,
    )
    if exists:
        con.execute(
            """UPDATE quotes SET quote_date=?, customer_id=?, site_id=?, job_name=?, afe=?, po=?,
               valid_until=?, status=?, notes=?, clerk=? WHERE quote_no=?""",
            vals,
        )
        con.execute("DELETE FROM quote_lines WHERE quote_id=?",
                    (key_of(con, "quotes", qno),))
    else:
        con.execute(
            """INSERT INTO quotes(quote_date, customer_id, site_id, job_name, afe, po,
               valid_until, status, notes, clerk, quote_no) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            vals,
        )
    qkey = key_of(con, "quotes", qno)
    con.executemany(
        """INSERT INTO quote_lines(quote_id, kind, asset_id, item, description, qty, rate, rate_unit, uom, amount)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        [(qkey, row[0], key_of(con, "assets", row[1]) if row[1] else None) + row[2:]
         for row in clean],
    )
    con.commit()
    return qno
def set_quote_status(con, quote_no: str, new: str) -> None:
    q = con.execute("SELECT status FROM quotes WHERE quote_no=?", (quote_no,)).fetchone()
    if not q:
        raise ValueError("Unknown quote")
    if new not in QUOTE_NEXT.get(q["status"], ()):
        raise ValueError(f"Cannot move {q['status']} → {new}")
    con.execute("UPDATE quotes SET status=? WHERE quote_no=?", (new, quote_no))
    con.commit()
def _clean_co_lines(con, lines: list) -> list:
    clean = []
    for ln in lines:
        desc = (ln.get("description") or "").strip()
        if not desc:
            continue
        direction = ln.get("direction") or "add"
        if direction not in ("add", "subtract"):
            raise ValueError("Change is add or subtract")
        kind = clean_line_type(con, ln.get("kind"))
        uom = clean_line_uom(con, ln.get("uom"))
        item = (ln.get("item") or "").strip()
        qty = float(ln.get("qty") or 0)
        rate = float(ln.get("rate") or 0)
        if qty <= 0:
            continue
        amt = _line_amount(qty, rate)
        clean.append((direction, kind, item, desc, qty, rate, uom, amt))
    if not clean:
        raise ValueError("Add at least one change line")
    return clean


def _clean_co_assoc(con, customer_id: str, assoc_kind, assoc_ref):
    """Validate a Change Order's optional association: ONE other
    money document, named by kind + number. Returns
    (assoc_kind, assoc_key) or (None, None). The associated document
    must exist and belong to the same customer — the association is
    a fact between two documents of one account."""
    kind = (assoc_kind or "").strip()
    ref = (assoc_ref or "").strip()
    if not kind and not ref:
        return None, None
    if kind not in ("invoice", "sale", "wo", "ticket", "change"):
        raise ValueError("A change order associates with an invoice, "
                         "sale, work order, rental ticket, or change order")
    akey = doc_key(con, kind, ref)
    if akey is None:
        raise ValueError(f"Unknown {DOC_LABELS[kind]} {ref}")
    ocust = _doc_customer(con, kind, ref)
    if ocust and ocust != customer_id:
        raise ValueError(
            f"{DOC_LABELS[kind]} {ref} belongs to another customer")
    return kind, akey


def issue_change_order(con, customer_id: str, reason: str, lines: list, co_date: str | None = None, notes: str = "", clerk: str = "", po: str = "", co_no: str | None = None, assoc_kind: str | None = None, assoc_ref: str | None = None) -> str:
    """Issue a Change Order (build 'v', Jason 2026-10-25): a
    standalone money document. Nothing requires anything — no quote
    parent, no required association. It carries its own customer,
    lines (adds and subtracts), amount, and reason; it may name ONE
    associated money document (Invoice, Sale, Work Order, Rental
    Ticket, or another Change Order) as a fact that changes no
    totals. It is a receivable: payments and credits settle it
    directly, independently of the associated document."""
    if not con.execute("SELECT 1 FROM customers WHERE customer_id=?",
                       (customer_id or "",)).fetchone():
        raise ValueError("Pick a customer")
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("Reason is required")
    clean = _clean_co_lines(con, lines)
    akind, akey = _clean_co_assoc(con, customer_id, assoc_kind, assoc_ref)
    _co_in = (co_no or "").strip()
    cno = (validate_new_doc_no(con, "change_orders", "co_no", _co_in, "change order")
           if _co_in else next_co_id(con))
    who = require_clerk(clerk)
    cur = con.execute(
        """INSERT INTO change_orders(co_no, co_date, customer_id, reason, po, status, notes, clerk, assoc_kind, assoc_id)
           VALUES (?,?,?,?,?, 'Issued', ?, ?, ?, ?)""",
        (cno, co_date or date.today().isoformat(),
         cust_key(con, customer_id), reason, (po or "").strip(),
         notes or "", who, akind, akey),
    )
    con.executemany(
        """INSERT INTO change_order_lines(co_id, direction, kind, item, description, qty, rate, uom, amount)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        [(cur.lastrowid,) + row for row in clean],
    )
    con.commit()
    return cno


def save_change_order(con, co_no: str, customer_id: str, reason: str, lines: list, co_date: str | None = None, notes: str = "", clerk: str = "", po: str = "", assoc_kind: str | None = None, assoc_ref: str | None = None) -> str:
    """Edit an issued Change Order (header + lines + association).
    The record is the protection: once money has settled against a
    Change Order its lines and amount stand as issued — the edit is
    refused and the correction is a new Change Order."""
    co = con.execute("SELECT * FROM change_orders WHERE co_no=?",
                     (co_no,)).fetchone()
    if not co:
        raise ValueError("Unknown change order")
    if co["status"] == "Void":
        raise ValueError("A void change order does not change")
    if abs(doc_settled(con, "change", co_no)["total"]) > Decimal("0.009"):
        raise ValueError(
            f"{co_no} has money settled against it — its lines stand "
            "as issued; pursue a correction as a new change order")
    if not con.execute("SELECT 1 FROM customers WHERE customer_id=?",
                       (customer_id or "",)).fetchone():
        raise ValueError("Pick a customer")
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("Reason is required")
    clean = _clean_co_lines(con, lines)
    akind, akey = _clean_co_assoc(con, customer_id, assoc_kind, assoc_ref)
    who = require_clerk(clerk)
    con.execute(
        """UPDATE change_orders SET co_date=?, customer_id=?, reason=?,
           po=?, notes=?, clerk=?, assoc_kind=?, assoc_id=?
           WHERE co_no=?""",
        (co_date or str(co["co_date"])[:10], cust_key(con, customer_id),
         reason, (po or "").strip(), notes or "", who, akind, akey,
         co_no),
    )
    con.execute("DELETE FROM change_order_lines WHERE co_id=?", (co["id"],))
    con.executemany(
        """INSERT INTO change_order_lines(co_id, direction, kind, item, description, qty, rate, uom, amount)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        [(co["id"],) + row for row in clean],
    )
    con.commit()
    return co_no


def change_order_assoc(con, co_no: str):
    """A Change Order's association as (kind, number) or (None, None)."""
    co = con.execute("SELECT assoc_kind, assoc_id FROM change_orders "
                     "WHERE co_no=?", (co_no,)).fetchone()
    if not co or not co["assoc_kind"]:
        return None, None
    return co["assoc_kind"], doc_num(con, co["assoc_kind"], co["assoc_id"])


def associated_change_orders(con, doc_kind: str, doc_ref: str) -> list:
    """Change Orders naming this document as their association —
    facts for the document's summary; they change no totals."""
    akey = doc_key(con, doc_kind, doc_ref)
    if akey is None:
        return []
    out = []
    for co in con.execute(
            "SELECT co_no FROM change_orders WHERE assoc_kind=? "
            "AND assoc_id=? AND status != 'Void' ORDER BY co_date, co_no",
            (doc_kind, akey)):
        out.append(co["co_no"])
    return out
def quote_totals(con, quote_no: str) -> dict:
    base = float(con.execute(
        "SELECT COALESCE(SUM(amount),0) FROM quote_lines WHERE quote_id=?",
        (key_of(con, "quotes", quote_no),)
    ).fetchone()[0] or 0)
    # Build 'v' (Jason 2026-10-25): a quote's numbers are its own —
    # Change Orders no longer fold into the quote's face. A Change
    # Order associated with a quote stands on its own as a fact
    # (see associated_change_orders), settled on its own.
    face = round(base, 2)
    billed = 0.0
    for inv in con.execute("SELECT invoice_no FROM invoices WHERE quote_id=?",
                           (key_of(con, "quotes", quote_no),)):
        billed += invoice_totals(con, inv["invoice_no"])["total"]
    return {
        "quoted": round(base, 2),
        "face": face,
        "billed": round(billed, 2),
        "variance": round(billed - face, 2),
    }
def quote_pack(con, quote_no: str) -> dict | None:
    q = con.execute(
        """SELECT q.*, c.account_name, c.bill_to, c.phone, c.email, c.city_st
           FROM quotes q JOIN customers c ON c.id=q.customer_id
           WHERE q.quote_no=?""",
        (quote_no,),
    ).fetchone()
    if not q:
        return None
    qkey = q["id"]
    lines = []
    for r in con.execute(
            "SELECT * FROM quote_lines WHERE quote_id=? ORDER BY line_id",
            (qkey,)):
        d = dict(r)
        d["asset_id"] = asset_code(con, d["asset_id"])
        lines.append(d)
    # Build 'v': the quote's Change Orders are the ones ASSOCIATED
    # with it — stated as facts with their own money state; nothing
    # folds into the quote's totals.
    cos = []
    for cno in associated_change_orders(con, "quote", quote_no):
        co = con.execute("SELECT * FROM change_orders WHERE co_no=?",
                         (cno,)).fetchone()
        cl = [dict(r) for r in con.execute(
            "SELECT * FROM change_order_lines WHERE co_id=? ORDER BY line_id",
            (co["id"],)
        )]
        st = doc_settled(con, "change", cno)
        cos.append({"header": dict(co), "lines": cl,
                    "total": float(doc_total(con, "change", cno)),
                    "settled": float(st["total"]),
                    "balance": float(doc_balance(con, "change", cno))})
    tickets = []
    for r in con.execute(
            "SELECT ticket_id, status, invoice_id FROM tickets "
            "WHERE quote_id=? ORDER BY ticket_id", (qkey,)):
        d = dict(r)
        d["invoice_no"] = doc_num(con, "invoice", d.pop("invoice_id"))
        tickets.append(d)
    wos = []
    for r in con.execute(
            "SELECT wo_id, status, bill_amount, invoice_id FROM work_orders "
            "WHERE quote_id=? ORDER BY wo_id", (qkey,)):
        d = dict(r)
        d["invoice_no"] = doc_num(con, "invoice", d.pop("invoice_id"))
        wos.append(d)
    invs = [dict(r) for r in con.execute(
        "SELECT invoice_no, status, invoice_date FROM invoices WHERE quote_id=? ORDER BY invoice_date", (qkey,)
    )]
    _q = dict(q)
    # Boundary: views/print read the operator's codes, not keys.
    _q["customer_id"] = cust_code(con, _q.get("customer_id")) or ""
    _q["site_id"] = site_code(con, _q.get("site_id")) or ""
    _q["account_name"] = q["account_name"]
    return {"q": _q, "lines": lines, "cos": cos, "tickets": tickets, "wos": wos, "invoices": invs, "tot": quote_totals(con, quote_no)}
def convert_quote(con, quote_no: str, on_rent: str | None = None) -> list[str]:
    """Accepted quote → Reserved tickets for rental lines that name a free unit. Does not invent invoice totals."""
    pack = quote_pack(con, quote_no)
    if not pack:
        raise ValueError("Unknown quote")
    q = pack["q"]
    if q["status"] not in ("Accepted", "Converted"):
        raise ValueError("Accept the quote before converting")
    # No site gate (Jason 2026-10-24): a quotation with no job site
    # converts like any other — the tickets it books carry no site,
    # which is a complete and valid state of a ticket.
    made = []
    on = on_rent or date.today().isoformat()
    for ln in pack["lines"]:
        # "Rental" is the global line Type; "rental"/"unit" are the legacy
        # values the migration remaps (kept defensively).
        if ln["kind"] not in ("Rental", "rental", "unit") or not ln.get("asset_id"):
            continue
        already = con.execute(
            "SELECT ticket_id FROM tickets WHERE quote_id=? AND asset_id=?",
            (q["id"], key_of(con, "assets", ln["asset_id"])),
        ).fetchone()
        if already:
            continue
        # The ticket carries the quote line's own rate wording: the line's unit
        # (Day/Week/Hour/Special/...) becomes the ticket's rate type and the
        # line's rate overrides whatever the asset says.
        unit = clean_rate_unit(ln.get("rate_unit")) if ln.get("rate_unit") else "Day"
        qty = float(ln["qty"] or 1)
        off = None
        if unit != "Hour" and _parse(on):
            mult = {"Week": 7, "Monthly": 30}.get(unit, 1)
            off = (_parse(on) + timedelta(days=max(int(round(qty * mult)) - 1, 0))).isoformat()
        tid = create_ticket(con, {
            "customer_id": q["customer_id"],
            "site_id": q["site_id"],
            "asset_id": ln["asset_id"],
            "job_name": q.get("job_name") or "",
            "afe": q.get("afe") or "",
            "po": q.get("po") or "",
            "rate_type": unit,
            "rate_value": float(ln["rate"] or 0) or None,
            "on_rent": on,
            "off_rent": off,
            "status": "Reserved",
            "quote_no": quote_no,
        })
        made.append(tid)
    if q["status"] == "Accepted":
        con.execute("UPDATE quotes SET status='Converted' WHERE quote_no=?", (quote_no,))
        con.commit()
    if not made and q["status"] == "Accepted":
        # service-only quote still marks converted
        pass
    return made
def next_pc_id(con: sqlite3.Connection) -> str:
    while True:
        n = _reserve_counter(con, "next_pc", 1001)
        pid = f"PC-{n:04d}"
        if not con.execute("SELECT 1 FROM petty_cash WHERE pc_id=?", (pid,)).fetchone():
            return pid
def petty_balance(con: sqlite3.Connection) -> float:
    row = con.execute(
        """SELECT COALESCE(SUM(CASE WHEN direction='in' THEN amount ELSE -amount END),0)
           FROM petty_cash"""
    ).fetchone()
    return round(float(row[0] or 0), 2)
def petty_book(con: sqlite3.Connection) -> dict:
    co = con.execute("SELECT pc_float FROM company WHERE id=1").fetchone()
    target = float(co["pc_float"] or 0) if co else 0.0
    bal = petty_balance(con)
    rows = []
    run = 0.0
    for r in con.execute("SELECT * FROM petty_cash ORDER BY txn_date, pc_id"):
        amt = float(r["amount"])
        run += amt if r["direction"] == "in" else -amt
        rows.append({
            "pc_id": r["pc_id"],
            "txn_date": str(r["txn_date"])[:10],
            "direction": r["direction"],
            "amount": amt,
            "signed": amt if r["direction"] == "in" else -amt,
            "category": r["category"],
            "payee": r["payee"] or "",
            "ref_no": r["ref_no"] or "",
            "notes": r["notes"] or "",
            "running": round(run, 2),
        })
    rows.reverse()
    return {
        "balance": bal,
        "target": round(target, 2),
        "to_replenish": round(max(0.0, target - bal), 2),
        "rows": rows,
    }
def set_pc_float(con: sqlite3.Connection, target: float) -> None:
    t = float(target)
    if t < 0:
        raise ValueError("Float cannot be negative")
    con.execute("UPDATE company SET pc_float=? WHERE id=1", (t,))
    con.commit()
def record_petty(
    con: sqlite3.Connection,
    direction: str,
    amount: float,
    category: str,
    txn_date: str | None = None,
    payee: str = "",
    ref_no: str = "",
    notes: str = "",
    clerk: str = "",
) -> str:
    who = require_clerk(clerk)
    direction = (direction or "").strip().lower()
    if direction not in ("in", "out"):
        raise ValueError("Petty cash is in or out")
    try:
        amt = float(amount)
    except (TypeError, ValueError):
        raise ValueError("Amount must be a number") from None
    if amt <= 0:
        raise ValueError("Amount must be positive")
    category = (category or "").strip()
    allowed = PC_IN_CATS if direction == "in" else PC_OUT_CATS
    if category not in allowed:
        raise ValueError("Pick a category that matches in or out")
    if direction == "out" and amt - petty_balance(con) > 0.009:
        raise ValueError(f"Box only holds ${petty_balance(con):,.2f}")
    pid = next_pc_id(con)
    con.execute(
        """INSERT INTO petty_cash(pc_id, txn_date, direction, amount, category, payee, ref_no, notes, clerk)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (pid, txn_date or date.today().isoformat(), direction, amt, category, payee or "", ref_no or "", notes or "", who),
    )
    con.commit()
    return pid
# ---------------------------------------------------------------------------
# Cash tab entries (Batch 3 #12): tenders recorded on their own
# table, attached to exactly one of an invoice / a work order / a ticket.
# Record-only — an entry never moves an invoice balance or the petty box.
# The Cash door offers the same tender list as every other money door
# (pack 'm', Jason's 'l' look): one list, CASH_METHODS, no narrower
# cash-only subset.
CASH_ENTRY_METHODS = CASH_METHODS


def _ensure_cash_table(con: sqlite3.Connection) -> None:
    """Create cash_entries on books that predate it (schema.sql owns the
    DDL for new books; this is the ensure path for existing ones)."""
    con.execute("""CREATE TABLE IF NOT EXISTS cash_entries (
      entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
      entry_date TEXT NOT NULL,
      direction TEXT NOT NULL CHECK (direction IN ('in','out')),
      method TEXT NOT NULL CHECK (method IN ('ACH','Check','Wire','Card','Cash','Venmo','Bitcoin','Traveler''s Check','Other')),
      amount REAL NOT NULL CHECK (amount > 0),
      customer_id INTEGER REFERENCES customers(id),
      invoice_id INTEGER REFERENCES invoices(id),
      wo_id INTEGER REFERENCES work_orders(id),
      ticket_id INTEGER REFERENCES tickets(id),
      sale_id INTEGER REFERENCES sales(id),
      quote_id INTEGER REFERENCES quotes(id),
      co_id INTEGER REFERENCES change_orders(id),
      asset_id INTEGER REFERENCES assets(id),
      notes TEXT,
      clerk TEXT,
      created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )""")
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_cash_date ON cash_entries(entry_date)")


def record_cash_entry(con: sqlite3.Connection, entry_date: str | None = None,
                      direction: str = "", method: str = "",
                      amount: float = 0, customer_id: str = "",
                      invoice_no: str = "", wo_no: str = "",
                      ticket_id: str = "", asset_id: str = "",
                      notes: str = "", clerk: str = "",
                      line_allocs: list | None = None,
                      sale_group: str = "", quote_no: str = "",
                      co_no: str = "") -> int:
    """Record one cash entry. Exactly one attachment (invoice, work
    order, rental ticket, sale, quote, or change order) is required —
    an unattached entry is refused. Customer / asset default from the
    attachment when not given.
    A Cash In SETTLES its attachment (Jason 2026-10-23 — "customers
    may only take cash"; universality: the Cash door settles every
    document kind): the settlement posts through record_payment /
    record_doc_payment in this same transaction — one ledger row,
    linked back here by cash_entry_id, so the Cash tab row and the
    payments-audit row are one money event, never two records. An
    overage becomes an open credit memo, exactly like a payment's;
    a Cash In against a settled document posts as pure open credit
    the same way — no path errors. line_allocs breaks a settlement
    down by the document's lines under the payment rules (a line
    takes only its uncovered remainder).
    Every Cash Out stays record-only (Jason 2026-10-23 — cash out of
    pocket settles nothing); a Cash Out may still carry a line
    breakdown as a record — its per-line cap is the line's own total
    and it consumes nothing. Entry, settlement, and breakdown post
    in one commit."""
    _ensure_cash_table(con)
    who = require_clerk(clerk)
    direction = (direction or "").strip().lower()
    if direction not in ("in", "out"):
        raise ValueError("Cash is in or out")
    method = (method or "").strip()
    if method not in CASH_ENTRY_METHODS:
        raise ValueError("Pick " + ", ".join(CASH_ENTRY_METHODS[:-1]) + ", or " + CASH_ENTRY_METHODS[-1])
    try:
        amt = float(amount)
    except (TypeError, ValueError):
        raise ValueError("Amount must be a number") from None
    if amt <= 0:
        raise ValueError("Amount must be positive")
    ino = (invoice_no or "").strip()
    wno = (wo_no or "").strip()
    tid = (ticket_id or "").strip()
    sgrp = (sale_group or "").strip()
    qno = (quote_no or "").strip()
    cono = (co_no or "").strip()
    attached = [x for x in (ino, wno, tid, sgrp, qno, cono) if x]
    if len(attached) != 1:
        raise ValueError(
            "Attach to exactly one: invoice, work order, rental ticket, "
            "sale, quote, or change order")
    cid = (customer_id or "").strip()
    aid = (asset_id or "").strip()
    doc_kind = doc_ref = ""
    if ino:
        row = con.execute(
            "SELECT customer_id FROM invoices WHERE invoice_no=?",
            (ino,)).fetchone()
        if not row:
            raise ValueError(f"Unknown invoice {ino}")
        cid = cid or cust_code(con, row["customer_id"])
        doc_kind, doc_ref = "invoice", ino
    elif wno:
        row = con.execute(
            "SELECT customer_id, asset_id FROM work_orders WHERE wo_id=?",
            (wno,)).fetchone()
        if not row:
            raise ValueError(f"Unknown work order {wno}")
        cid = cid or (cust_code(con, row["customer_id"]) or "")
        aid = aid or (asset_code(con, row["asset_id"]) or "")
        doc_kind, doc_ref = "wo", wno
    elif tid:
        row = con.execute(
            "SELECT customer_id, asset_id FROM tickets WHERE ticket_id=?",
            (tid,)).fetchone()
        if not row:
            raise ValueError(f"Unknown rental ticket {tid}")
        cid = cid or cust_code(con, row["customer_id"])
        aid = aid or (asset_code(con, row["asset_id"]) or "")
        doc_kind, doc_ref = "ticket", tid
    elif sgrp:
        row = con.execute(
            "SELECT customer_id FROM sales WHERE group_id=? LIMIT 1",
            (doc_key(con, "sale", sgrp),)).fetchone()
        if not row:
            raise ValueError(f"Unknown sale {sgrp}")
        cid = cid or cust_code(con, row["customer_id"])
        doc_kind, doc_ref = "sale", sgrp
    elif cono:
        row = con.execute(
            "SELECT customer_id FROM change_orders WHERE co_no=?",
            (cono,)).fetchone()
        if not row:
            raise ValueError(f"Unknown change order {cono}")
        cid = cid or cust_code(con, row["customer_id"])
        doc_kind, doc_ref = "change", cono
    else:
        row = con.execute(
            "SELECT customer_id FROM quotes WHERE quote_no=?",
            (qno,)).fetchone()
        if not row:
            raise ValueError(f"Unknown quote {qno}")
        cid = cid or cust_code(con, row["customer_id"])
        doc_kind, doc_ref = "quote", qno
    if cid and not con.execute(
            "SELECT 1 FROM customers WHERE customer_id=?", (cid,)).fetchone():
        raise ValueError(f"Unknown customer {cid}")
    if aid and not con.execute(
            "SELECT 1 FROM assets WHERE asset_id=?", (aid,)).fetchone():
        raise ValueError(f"Unknown asset {aid}")
    # A Cash In settles its attachment; a Cash Out is a record. A
    # settling entry's breakdown is validated by the payment path
    # (settlement caps) inside this transaction; a record-only
    # breakdown validates here, capped at line totals.
    settling = (direction == "in")
    cleaned_allocs = []
    if line_allocs and not settling:
        _ensure_payalloc_table(con)
        cleaned_allocs = _clean_doc_line_allocs(
            con, doc_kind, doc_ref, line_allocs, amt, "cash")
    edate = (entry_date or date.today().isoformat())[:10]
    cur = con.execute(
        """INSERT INTO cash_entries(entry_date, direction, method, amount,
           customer_id, invoice_id, wo_id, ticket_id, sale_id, quote_id,
           co_id, asset_id, notes, clerk)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (edate, direction, method, round(amt, 2),
         cust_key(con, cid) if cid else None,
         key_of(con, "invoices", ino) if ino else None,
         key_of(con, "work_orders", wno) if wno else None,
         key_of(con, "tickets", tid) if tid else None,
         doc_key(con, "sale", sgrp) if sgrp else None,
         key_of(con, "quotes", qno) if qno else None,
         key_of(con, "change_orders", cono) if cono else None,
         key_of(con, "assets", aid) if aid else None,
         (notes or "").strip(), who))
    eid = int(cur.lastrowid)
    if settling:
        if doc_kind == "invoice":
            res = record_payment(
                con, ino, amt, edate, method, clerk=who, commit=False,
                line_allocs=line_allocs, alloc_source="cash",
                cash_entry_id=eid)
            if any(r[1] == "cash_entry_id" for r in con.execute(
                    "PRAGMA table_info(collections)")):
                con.execute(
                    "UPDATE collections SET cash_entry_id=? WHERE pay_id=?",
                    (eid, res["pay_id"]))
        else:
            record_doc_payment(
                con, doc_kind, doc_ref, amt, edate, method, clerk=who,
                commit=False, line_allocs=line_allocs,
                alloc_source="cash", cash_entry_id=eid)
    elif cleaned_allocs:
        _write_line_allocs(
            con, source="cash", pay_key=None, cash_entry_id=eid,
            batch_id=None, doc_kind=doc_kind, doc_ref=doc_ref,
            pay_date=edate, clerk=who,
            applied=round(amt, 2), cleaned=cleaned_allocs)
    con.commit()
    return eid


def list_cash_entries(con: sqlite3.Connection) -> list[dict]:
    """Cash entries, newest first, with the customer name and the
    attachment label resolved. A settling Cash In also carries
    settle_pay_id — the one ledger row that is its balance effect
    (the same money event, seen from the payments side) — wherever
    that row lives (collections for an invoice, doc_collections for
    a work order, rental ticket, sale, or quote); when the entry settled nothing
    because the document was already paid, settle_cm_no names the
    open credit memo the money became."""
    _ensure_cash_table(con)
    _cols = [r[1] for r in con.execute("PRAGMA table_info(collections)")]
    _link = ("(SELECT c2.pay_id FROM collections c2 "
             "WHERE c2.cash_entry_id = ce.entry_id "
             "AND c2.kind='payment' LIMIT 1)"
             if "cash_entry_id" in _cols else "NULL")
    _dlink = ("(SELECT d2.pay_id FROM doc_collections d2 "
              "WHERE d2.cash_entry_id = ce.entry_id "
              "AND d2.kind='payment' LIMIT 1)"
              if _doc_collections_exist(con) else "NULL")
    _cmlink = ("(SELECT cm2.cm_no FROM credit_memos cm2 "
               "WHERE cm2.cash_entry_id = ce.entry_id LIMIT 1)"
               if any(r[1] == "cash_entry_id" for r in con.execute(
                   "PRAGMA table_info(credit_memos)")) else "NULL")
    out = []
    for r in con.execute(
            f"""SELECT ce.*, COALESCE(c.account_name, '') AS account_name,
                      COALESCE(a.unit_no, '') AS unit_no,
                      COALESCE({_link}, {_dlink}) AS settle_pay_id,
                      {_cmlink} AS settle_cm_no
               FROM cash_entries ce
               LEFT JOIN customers c ON c.id = ce.customer_id
               LEFT JOIN assets a ON a.id = ce.asset_id
               ORDER BY ce.entry_date DESC, ce.entry_id DESC"""):
        d = dict(r)
        d["customer_id"] = cust_code(con, d.get("customer_id"))
        d["asset_id"] = asset_code(con, d.get("asset_id"))
        d["invoice_no"] = num_of(con, "invoices", d.pop("invoice_id", None))
        d["wo_no"] = num_of(con, "work_orders", d.pop("wo_id", None))
        d["ticket_id"] = num_of(con, "tickets", d.pop("ticket_id", None))
        d["sale_group"] = num_of(con, "sales", d.pop("sale_id", None))
        d["quote_no"] = num_of(con, "quotes", d.pop("quote_id", None))
        d["co_no"] = num_of(con, "change_orders", d.pop("co_id", None))
        if d.get("invoice_no"):
            d["attached"] = f"Invoice {d['invoice_no']}"
        elif d.get("wo_no"):
            d["attached"] = f"WO {d['wo_no']}"
        elif d.get("ticket_id"):
            d["attached"] = f"Rental Ticket {d['ticket_id']}"
        elif d.get("sale_group"):
            d["attached"] = f"Sale {d['sale_group']}"
        elif d.get("quote_no"):
            d["attached"] = f"Quote {d['quote_no']}"
        elif d.get("co_no"):
            d["attached"] = f"Change Order {d['co_no']}"
        else:
            d["attached"] = ""
        out.append(d)
    return out


def _invoice_writein(con: sqlite3.Connection, invoice_no: str) -> Decimal:
    """The invoice's stored write-in amount (the editor's Write-in row;
    Jason 2026-10-20): a typed amount there is money on the invoice and
    adds into the Grand Total — it is calculated nowhere else. The
    label lives in invoices.adj_label. Returns Decimal 0 when the
    column predates the migration or nothing was typed."""
    try:
        r = con.execute("SELECT adjustment FROM invoices WHERE invoice_no=?",
                        (invoice_no,)).fetchone()
        return _money(r[0]) if r and r[0] is not None else Decimal("0.00")
    except Exception:
        return Decimal("0.00")
def _invoice_tax_extras(con: sqlite3.Connection, invoice_no: str):
    """(writein, writein_taxable, operator_exempt, invoice_rate) for the
    invoice-round tax model (Jason 2026-10-20): the write-in's taxable
    toggle taxes the write-in at the invoice's own rate; the operator's
    tax-exempt click zeroes the invoice's whole tax on their say-so —
    no paperwork required, the click governs. Guarded: pre-migration
    DBs read as (writein-or-0, False, False, 0). The rate is NOT
    cent-quantized (jurisdiction rates carry 4 places)."""
    adj = _invoice_writein(con, invoice_no)
    try:
        r = con.execute("SELECT adj_taxable, tax_exempt_op, tax_rate FROM invoices WHERE invoice_no=?",
                        (invoice_no,)).fetchone()
        if r is None:
            return adj, False, False, Decimal("0")
        return adj, bool(r[0]), bool(r[1]), Decimal(str(r[2] or 0))
    except Exception:
        return adj, False, False, Decimal("0")
def invoice_totals(con: sqlite3.Connection, invoice_no: str) -> dict:
    ikey = key_of(con, "invoices", invoice_no)
    rows=con.execute("SELECT amount,tax_amount,source_type FROM invoice_lines WHERE invoice_id=? ORDER BY line_id",(ikey,)).fetchall()
    sub=sum((_money(r["amount"]) for r in rows),Decimal("0.00")); linetax=sum((_money(r["tax_amount"]) for r in rows),Decimal("0.00"))
    adj,adj_taxable,op_exempt,inv_rate=_invoice_tax_extras(con,invoice_no)
    if op_exempt:
        tax=Decimal("0.00")
    elif adj_taxable and adj:
        tax=_ms(linetax,(adj*inv_rate).quantize(CENT,rounding=ROUND_HALF_UP))
    else:
        tax=linetax
    total=_ms(sub,tax,adj)
    cash=_money(con.execute("SELECT COALESCE(SUM(COALESCE(applied_amount,amount)),0) FROM collections WHERE invoice_id=? AND kind='payment'",(ikey,)).fetchone()[0])
    credit=_money(con.execute("SELECT COALESCE(SUM(COALESCE(applied_amount,amount)),0) FROM collections WHERE invoice_id=? AND kind='credit'",(ikey,)).fetchone()[0])
    paid=_ms(cash,credit); bal=_ms(total,-paid)
    return {"subtotal":float(sub),"tax":float(tax),"adjustment":float(adj),"total":float(total),"cash":float(cash),"credit":float(credit),"paid":float(paid),"balance":float(bal),"count":sum(r["source_type"]=="ticket" for r in rows),"wo_count":sum(r["source_type"]=="work_order" for r in rows),"wo_sub":float(sum((_money(r["amount"]) for r in rows if r["source_type"]=="work_order"),Decimal("0.00"))),"extra_sub":float(sum((_money(r["amount"]) for r in rows if r["source_type"]=="extra"),Decimal("0.00"))),"line_count":len(rows)}
@ttl_cached()
def invoice_totals_batch(con: sqlite3.Connection) -> dict:
    """Full totals for every invoice in 2 queries (N+1 killer for Today/alerts).
    Returns {invoice_no: {subtotal,tax,total,cash,credit,paid,balance}}. Uses the
    same Decimal math as invoice_totals so figures match exactly."""
    line_totals = {}
    for ino, sub, tax in con.execute(
        "SELECT i.invoice_no, COALESCE(SUM(l.amount),0), "
        "COALESCE(SUM(l.tax_amount),0) "
        "FROM invoice_lines l JOIN invoices i ON i.id = l.invoice_id "
        "GROUP BY i.invoice_no"):
        sub_d, tax_d = _money(sub), _money(tax)
        line_totals[ino] = (sub_d, tax_d, _ms(sub_d, tax_d))
    paid_totals = {}
    for ino, cash, credit in con.execute(
        "SELECT i.invoice_no, "
        "COALESCE(SUM(CASE WHEN c.kind='payment' THEN COALESCE(c.applied_amount,c.amount) ELSE 0 END),0), "
        "COALESCE(SUM(CASE WHEN c.kind='credit' THEN COALESCE(c.applied_amount,c.amount) ELSE 0 END),0) "
        "FROM collections c JOIN invoices i ON i.id = c.invoice_id "
        "GROUP BY i.invoice_no"):
        cash_d, credit_d = _money(cash), _money(credit)
        paid_totals[ino] = (cash_d, credit_d, _ms(cash_d, credit_d))
    adj_totals = {}
    try:
        for ino, adj in con.execute(
                "SELECT invoice_no, COALESCE(adjustment,0) FROM invoices"):
            if adj:
                adj_totals[ino] = _money(adj)
    except Exception:
        adj_totals = {}
    inv_extras = {}
    try:
        for ino, adjtx, opex, rate in con.execute(
                "SELECT invoice_no, COALESCE(adj_taxable,0), "
                "COALESCE(tax_exempt_op,0), COALESCE(tax_rate,0) FROM invoices"):
            inv_extras[ino] = (bool(adjtx), bool(opex), Decimal(str(rate or 0)))
    except Exception:
        inv_extras = {}
    out = {}
    zero = Decimal("0.00")
    for ino, (sub, tax, _linetotal) in line_totals.items():
        adj = adj_totals.get(ino, zero)
        adjtx, opex, rate = inv_extras.get(ino, (False, False, Decimal("0")))
        if opex:
            tax = zero
        elif adjtx and adj:
            tax = _ms(tax, (adj * rate).quantize(CENT, rounding=ROUND_HALF_UP))
        total = _ms(sub, tax, adj)
        cash, credit, paid = paid_totals.get(ino, (zero, zero, zero))
        bal = _ms(total, -paid)
        out[ino] = {"subtotal": float(sub), "tax": float(tax), "total": float(total),
                    "cash": float(cash), "credit": float(credit), "paid": float(paid),
                    "balance": float(bal)}
    return out
def invoice_balances_batch(con: sqlite3.Connection) -> dict:
    """Balance for every invoice in 2 queries. {invoice_no: balance_float}."""
    return {ino: t["balance"] for ino, t in invoice_totals_batch(con).items()}
def invoice_balance(con, invoice_no: str) -> float:
    return invoice_totals(con, invoice_no)["balance"]
def invoice_locked(con, invoice_no: str) -> bool:
    inv=con.execute("SELECT status FROM invoices WHERE invoice_no=?",(invoice_no,)).fetchone()
    if not inv: return True
    # B7: a posted invoice (Sent to the customer) is locked, not just Paid /
    # Write-off or one with cash applied. The PO is the customer's document
    # reference — it must not change after they've seen the invoice.
    if inv["status"] in ("Sent","Paid","Write-off"): return True
    return con.execute("SELECT 1 FROM collections WHERE invoice_id=? LIMIT 1",(key_of(con, "invoices", invoice_no),)).fetchone() is not None
def set_invoice_po(con, invoice_no: str, po: str, clerk: str = "", po_expire: str|None=None, po_cost_code: str|None=None, po_notes: str|None=None, po_total: float|None=None, po_status: str|None=None) -> None:
    if invoice_locked(con, invoice_no):
        raise ValueError("Invoice is locked (sent, paid, or has payments)")
    require_clerk(clerk)
    con.execute("UPDATE invoices SET po=?, po_expire=?, po_cost_code=?, po_notes=? WHERE invoice_no=?", ((po or "").strip(), (po_expire or "").strip() or None, (po_cost_code or "").strip() or None, (po_notes or "").strip() or None, invoice_no))
    # Q6: keep the shared PO record current alongside the invoice snapshot.
    _cid = con.execute("SELECT customer_id FROM invoices WHERE invoice_no=?", (invoice_no,)).fetchone()
    upsert_po_record(con, _cid["customer_id"] if _cid else "", po, po_expire, po_cost_code, po_notes, total=po_total, status=po_status)
    con.commit()


def _ensure_po_table(con: sqlite3.Connection) -> None:
    """Repair-only compatibility hook; schema.sql owns current table DDL."""
    if not con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='purchase_orders'").fetchone():
        raise RuntimeError("Database schema is incomplete: purchase_orders is missing")
    # Migration: older PO tables lack the asset/ack columns.
    cols = [r[1] for r in con.execute("PRAGMA table_info(purchase_orders)").fetchall()]
    for col in ("asset_id", "ack_at", "ack_by"):
        if col not in cols:
            con.execute(f"ALTER TABLE purchase_orders ADD COLUMN {col} TEXT")
    if "total" not in cols:
        con.execute("ALTER TABLE purchase_orders ADD COLUMN total REAL DEFAULT 0")
    if "status" not in cols:
        con.execute("ALTER TABLE purchase_orders ADD COLUMN status TEXT NOT NULL DEFAULT 'Open'")

def upsert_po_record(con: sqlite3.Connection, customer_id: str, po_no: str,
                     expire: str | None = None, cost_code: str | None = None,
                     notes: str | None = None, asset_id: str | None = None,
                     total: float | None = None, status: str | None = None) -> bool:
    """Keep the shared PO record current. Q6: the expiry lives on the PO
    itself, not scattered per-invoice — every invoice carrying this PO reads
    the same record. Non-blank values win; blanks never clear: a form left
    blank is "didn't specify", not "remove". Free-text throughout.
    Returns True when the PO record is newly created (an issued PO)."""
    po_no = (po_no or "").strip()
    if not po_no or not customer_id:
        return False
    ckey = cust_key(con, customer_id)
    if ckey is None:
        return False
    # Status is the operator's call (Batch 3 #15): a stored value from
    # the fixed pair, never derived. None leaves the stored value alone;
    # a new record starts "Open" unless the operator says otherwise.
    if status is not None:
        status = (status or "").strip()
        if status not in PO_STATUSES:
            raise ValueError("PO status is Open or Paid in full")
    _ensure_po_table(con)
    exp = (expire or "").strip() or None
    cc = (cost_code or "").strip() or None
    nt = (notes or "").strip() or None
    aid = asset_id if isinstance(asset_id, int) else ((asset_id or "").strip() or None)
    akey = key_of(con, "assets", aid) if aid is not None else None
    if not con.execute("SELECT 1 FROM purchase_orders WHERE customer_id=? AND po_no=?",
                       (ckey, po_no)).fetchone():
        con.execute("INSERT INTO purchase_orders(po_no,customer_id,expire,cost_code,notes,asset_id,total,status) VALUES (?,?,?,?,?,?,?,?)",
                    (po_no, ckey, exp, cc, nt, akey, float(total) if total is not None else 0, status or "Open"))
        return True
    else:
        con.execute("""UPDATE purchase_orders
                       SET expire=COALESCE(?,expire), cost_code=COALESCE(?,cost_code), notes=COALESCE(?,notes),
                           asset_id=COALESCE(?,asset_id), total=COALESCE(?,total), status=COALESCE(?,status)
                       WHERE customer_id=? AND po_no=?""", (exp, cc, nt, akey, float(total) if total is not None else None, status, ckey, po_no))
        return False

def _auto_reserve_for_po(con: sqlite3.Connection, customer_id: str, po_no: str,
                         asset_id: str, src_ticket) -> str | None:
    """Issued PO for an in-yard unit: auto-reserve until shipped. The
    reservation is soft — it never blocks an interim job that fits the gap;
    that's the customer's judgment call, not the app's. Returns the new
    Reserved ticket id, or None when the unit is already on a job (then the
    PO is a paperwork change only)."""
    akey = key_of(con, "assets", asset_id)
    busy = con.execute(
        """SELECT ticket_id FROM tickets WHERE asset_id=?
           AND status IN ('Reserved','Dispatched','On Rent','Standby')""",
        (akey,)).fetchone()
    if busy:
        return None
    return create_ticket(con, {
        "customer_id": customer_id,
        "site_id": src_ticket["site_id"],
        "asset_id": asset_code(con, akey),
        "job_name": f"PO {po_no} — future job",
        "po": po_no,
        "rate_type": src_ticket["rate_type"],
        "rate_value": src_ticket["rate_value"],
        "on_rent": date.today().isoformat(),
        "status": "Reserved",
    })

def po_record(con: sqlite3.Connection, customer_id: str, po_no: str):
    """The shared PO record for (customer, PO#), or None."""
    po_no = (po_no or "").strip()
    if not po_no or not customer_id:
        return None
    try:
        _ensure_po_table(con)
        return con.execute("SELECT * FROM purchase_orders WHERE customer_id=? AND po_no=?",
                           (cust_key(con, customer_id), po_no)).fetchone()
    except Exception:
        return None

def backfill_po_records(con: sqlite3.Connection) -> None:
    """One-time bootstrap for the PO record: carry existing invoice-level PO
    detail onto the shared record — never lost. INSERT-only (an existing
    record is never touched, so a later restart can't resurrect a value the
    user blanked); last non-blank value per field wins, so a later invoice
    correcting the expiry beats an earlier one."""
    _ensure_po_table(con)
    try:
        rows = con.execute(
            """SELECT customer_id, po, po_expire, po_cost_code, po_notes FROM invoices
               WHERE po IS NOT NULL AND TRIM(po) != '' ORDER BY rowid""").fetchall()
    except Exception:
        return  # pre-migration DB: no PO detail columns yet
    seen: dict = {}
    for r in rows:
        key = (r["customer_id"], (r["po"] or "").strip())
        agg = seen.setdefault(key, {"expire": None, "cost_code": None, "notes": None})
        for f, col in (("expire", "po_expire"), ("cost_code", "po_cost_code"), ("notes", "po_notes")):
            try:
                v = (r[col] or "").strip()
            except (KeyError, IndexError):
                v = ""
            if v:
                agg[f] = v
    for (cid, po_no), agg in seen.items():
        con.execute("INSERT OR IGNORE INTO purchase_orders(po_no,customer_id,expire,cost_code,notes) VALUES (?,?,?,?,?)",
                    (po_no, cid, agg["expire"], agg["cost_code"], agg["notes"]))

def po_check(con, invoice_no: str) -> dict:
    """PO status for the invoice-time PO check panel. All logic lives here,
    not in the views. Q6: the expiry lives on the shared PO record
    (purchase_orders) — every invoice carrying this PO sees the same date.
    Invoice-level columns are the fallback for pre-migration DBs. View-only,
    never a gate, never printed as a line."""
    out = {"po": "", "expired": False, "expiring_soon": False,
           "days": None, "date_str": "", "expire": "", "cost_code": "", "notes": "",
           "total": 0.0, "status": "Open"}
    try:
        inv = con.execute(
            "SELECT customer_id, po, po_expire, po_cost_code, po_notes FROM invoices WHERE invoice_no=?",
            (invoice_no,)).fetchone()
    except sqlite3.Error:
        return out  # pre-migration DB: no PO detail columns yet
    if not inv:
        return out
    po_no = (inv["po"] or "").strip()
    out["po"] = po_no
    rec = po_record(con, inv["customer_id"], po_no) if po_no else None
    if rec is not None:
        exp = (rec["expire"] or "").strip()
        out["cost_code"] = (rec["cost_code"] or "").strip()
        out["notes"] = (rec["notes"] or "").strip()
        # Stored status (Batch 3 #15): read, never derived.
        try:
            _st = (rec["status"] or "").strip()
        except (KeyError, IndexError):
            _st = ""
        out["status"] = _st if _st in PO_STATUSES else "Open"
    else:
        exp = (inv["po_expire"] or "").strip()
        out["cost_code"] = (inv["po_cost_code"] or "").strip()
        out["notes"] = (inv["po_notes"] or "").strip()
    out["expire"] = exp
    if rec is not None:
        try:
            out["total"] = float(rec["total"] or 0)
        except (KeyError, TypeError, ValueError):
            out["total"] = 0.0
    if not exp:
        return out
    d = _parse(exp)
    out["date_str"] = d.strftime("%a %m/%d/%Y") if d else exp
    if d:
        delta = (d - date.today()).days
        out["days"] = delta
        out["expired"] = delta < 0
        out["expiring_soon"] = 0 <= delta <= 14
    return out


# ---------------------------------------------------------------------------
# Invoice paperwork (2026-09-27): the PO scan and the tax-exempt certificate
# attach to the INVOICE and travel with it (print + PDF pack). One slot per
# kind per invoice — a new upload replaces the old one. Files live in the
# shared docs/ folder next to the book, and validate_doc_blob keeps the same
# PDF/image/text-only gate as the data-book documents. sweep_orphan_docs
# (engine_core) keeps these files too.
# Invoice Round Part D (Jason update 8, 2026-10-20): two more typed slots —
# "shipping" (Shipping paperwork) and "custom" (an operator-named document;
# its stored title is the operator's name for it, not the kind label). Every
# slot also carries a print_with flag (1 = print with the invoice, the
# default; 0 = file it but keep it out of the print pack).
INV_DOC_KINDS = {"po": "PO scan", "tax_exempt": "Tax-exempt certificate",
                 "shipping": "Shipping paperwork", "custom": "Custom document"}

def _ensure_invoice_docs(con: sqlite3.Connection) -> None:
    """Compatibility assertion + lazy repairs for invoice_docs.

    schema.sql owns current table DDL, but older books (and, until the
    coordinator lands the matching schema.sql delta, fresh ones too)
    carry the original shape, so the save/get/read paths repair it here:
    - print_with (INTEGER NOT NULL DEFAULT 1) is ALTERed in when missing.
    - The original kind CHECK ('po','tax_exempt') predates the shipping /
      custom slots; SQLite cannot ALTER a CHECK, so the table is rebuilt
      in place with the widened CHECK — the same rebuild pattern
      engine_migrations uses for CHECK widenings. Idempotent: once the
      widened CHECK is in the DDL the guard is false forever.
    COORDINATOR NOTE: schema.sql's invoice_docs DDL still has the narrow
    kind CHECK and no print_with column — it needs the same two changes
    so a fresh book is born current instead of repaired on first touch."""
    row = con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='invoice_docs'").fetchone()
    if not row:
        raise RuntimeError("Database schema is incomplete: invoice_docs is missing")
    sql = row[0] or ""
    if "kind IN ('po','tax_exempt')" in sql and "'shipping'" not in sql:
        new_sql = sql.replace(
            "kind IN ('po','tax_exempt')",
            "kind IN ('po','tax_exempt','shipping','custom')", 1)
        for pat in ('CREATE TABLE "invoice_docs"',
                    "CREATE TABLE IF NOT EXISTS invoice_docs",
                    "CREATE TABLE invoice_docs"):
            if pat in new_sql:
                new_sql = new_sql.replace(pat, "CREATE TABLE _invoice_docs_new", 1)
                break
        # The rebuild commits first — PRAGMA foreign_keys=OFF is ignored
        # inside a transaction (same note as the sites rebuild).
        con.commit()
        con.execute("PRAGMA foreign_keys=OFF")
        try:
            con.execute("DROP TABLE IF EXISTS _invoice_docs_new")
            con.execute(new_sql)
            cols = [f'"{r[1]}"' for r in con.execute("PRAGMA table_info(invoice_docs)")]
            con.execute(f"INSERT INTO _invoice_docs_new ({', '.join(cols)}) "
                        f"SELECT {', '.join(cols)} FROM invoice_docs")
            con.execute("DROP TABLE invoice_docs")
            con.execute("ALTER TABLE _invoice_docs_new RENAME TO invoice_docs")
            con.execute("CREATE INDEX IF NOT EXISTS idx_invdocs_invoice ON invoice_docs(invoice_id)")
            con.commit()
        finally:
            con.execute("PRAGMA foreign_keys=ON")
    cols = [r[1] for r in con.execute("PRAGMA table_info(invoice_docs)")]
    if "print_with" not in cols:
        con.execute("ALTER TABLE invoice_docs ADD COLUMN print_with INTEGER NOT NULL DEFAULT 1")
        con.commit()

def _new_invoice_doc_name(ext: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    return f"doc-{stamp}-{secrets.token_hex(4)}{ext}"

def save_invoice_doc(con: sqlite3.Connection, invoice_no: str, kind: str,
                     filename: str, blob: bytes, clerk: str = "",
                     title: str | None = None) -> int:
    """Attach paperwork to an invoice. One slot per kind — a new upload
    replaces the old scan (the old file is removed). Returns doc_id.
    Title rule (Part D): for kind "custom" the stored title is the
    operator's name for the document (``title``, stripped, capped at
    120 chars), falling back to the kind label when blank; every other
    kind keeps its kind label as the title. A replacement upload keeps
    the slot's existing print_with flag."""
    kind = (kind or "").strip()
    if kind not in INV_DOC_KINDS:
        raise ValueError("Unknown paperwork kind")
    if not con.execute("SELECT 1 FROM invoices WHERE invoice_no=?",
                       (invoice_no,)).fetchone():
        raise ValueError("Unknown invoice")
    ext, mime = validate_doc_blob(blob, filename)
    _ensure_invoice_docs(con)
    old = get_invoice_doc(con, invoice_no, kind)
    stored = _new_invoice_doc_name(ext)
    d = doc_dir()
    target = d / stored
    n = 2
    while target.exists():
        target = d / f"{stored[:-len(ext)]}-{n}{ext}"
        stored = target.name
        n += 1
    target.write_bytes(blob)
    if kind == "custom":
        title = (title or "").strip()[:120] or INV_DOC_KINDS[kind]
    else:
        title = INV_DOC_KINDS[kind]
    if old:
        con.execute("""UPDATE invoice_docs SET title=?, filename=?, stored=?,
                       bytes=?, mime=?, uploaded_at=datetime('now'), clerk=?
                       WHERE doc_id=?""",
                    (title, (filename or stored)[:120], stored, len(blob),
                     mime, clerk or "", old["doc_id"]))
        doc_id = old["doc_id"]
        name = safe_doc_name(old["stored"])
        if name and name != stored:
            try:
                (d / name).unlink()
            except OSError:
                pass
    else:
        cur = con.execute(
            """INSERT INTO invoice_docs
               (invoice_id, kind, title, filename, stored, bytes, mime, clerk)
               VALUES (?,?,?,?,?,?,?,?)""",
            (key_of(con, "invoices", invoice_no), kind, title,
             (filename or stored)[:120], stored,
             len(blob), mime, clerk or ""))
        doc_id = cur.lastrowid
    con.commit()
    return doc_id

def _invoice_doc_cols(con: sqlite3.Connection) -> list:
    return [r[1] for r in con.execute("PRAGMA table_info(invoice_docs)")]

def get_invoice_doc(con: sqlite3.Connection, invoice_no: str, kind: str):
    """The attached paperwork row for (invoice, kind), or None. The dict
    carries print_with when the column exists (guarded — the lazy ensure
    adds it, but a pre-repair row shape must never break a read)."""
    try:
        _ensure_invoice_docs(con)
        pw = ", print_with" if "print_with" in _invoice_doc_cols(con) else ""
        r = con.execute(
            f"""SELECT doc_id, invoice_id, kind, title, filename, stored, bytes,
                      mime, uploaded_at, clerk{pw}
               FROM invoice_docs WHERE invoice_id=? AND kind=?""",
            (key_of(con, "invoices", invoice_no), kind)).fetchone()
    except sqlite3.Error:
        return None
    if not r:
        return None
    d = dict(r)
    d["invoice_no"] = invoice_no
    return d

def list_invoice_docs(con: sqlite3.Connection, invoice_no: str) -> list:
    """All paperwork rows attached to the invoice (any kind), in slot
    order (INV_DOC_KINDS order, then doc_id). Each dict is shaped like
    get_invoice_doc's, including print_with when the column exists."""
    try:
        _ensure_invoice_docs(con)
        pw = ", print_with" if "print_with" in _invoice_doc_cols(con) else ""
        rows = con.execute(
            f"""SELECT doc_id, invoice_id, kind, title, filename, stored,
                       bytes, mime, uploaded_at, clerk{pw}
                FROM invoice_docs WHERE invoice_id=?""",
            (key_of(con, "invoices", invoice_no),)).fetchall()
    except sqlite3.Error:
        return []
    out = []
    for r in rows:
        d = dict(r)
        d["invoice_no"] = invoice_no
        out.append(d)
    order = {k: i for i, k in enumerate(INV_DOC_KINDS)}
    out.sort(key=lambda d: (order.get(d.get("kind"), 99), d.get("doc_id") or 0))
    return out

def set_invoice_doc_print(con: sqlite3.Connection, invoice_no: str,
                          kind: str, on: bool) -> bool:
    """Set a slot's print_with flag (True = print with the invoice).
    Returns True when a paperwork row was updated, False when the kind
    is unknown or nothing is attached in that slot."""
    kind = (kind or "").strip()
    if kind not in INV_DOC_KINDS:
        return False
    _ensure_invoice_docs(con)
    cur = con.execute(
        "UPDATE invoice_docs SET print_with=? WHERE invoice_id=? AND kind=?",
        (1 if on else 0, key_of(con, "invoices", invoice_no), kind))
    con.commit()
    return cur.rowcount > 0

def read_invoice_doc(con: sqlite3.Connection, invoice_no: str, kind: str):
    """Return (row dict, bytes) for attached paperwork, or None."""
    row = get_invoice_doc(con, invoice_no, kind)
    if not row:
        return None
    name = safe_doc_name(row["stored"])
    if not name:
        return None
    p = doc_dir() / name
    if not p.is_file():
        return None
    return row, p.read_bytes()

def delete_invoice_doc(con: sqlite3.Connection, invoice_no: str, kind: str) -> bool:
    """Remove attached paperwork (row and file). Returns True if one existed."""
    row = get_invoice_doc(con, invoice_no, kind)
    if not row:
        return False
    con.execute("DELETE FROM invoice_docs WHERE doc_id=?", (row["doc_id"],))
    con.commit()
    name = safe_doc_name(row["stored"])
    if name:
        try:
            (doc_dir() / name).unlink()
        except OSError:
            pass
    return True

def invoice_job_box(con: sqlite3.Connection, invoice_no: str) -> dict:
    """The invoice Job Info box data. Which lines print is the
    operator's choice (Setup -> Billing; option inv_jobinfo_fields) —
    factory default PO, Job, Well, Location, Tax-exempt (Jason
    2026-10-18); the toggle set covers every Job Info card field
    (tweak round 2, 2026-10-20). Job/well/location/AFE derive from the
    invoice's tickets (and the tickets behind its work orders); the
    invoice carries no duplicate copy. PO expiry is record data, never
    a line — it is not in this box. Field sources: Cost Code from the
    shared PO record (po_check); Ticket # ref = the linked ticket
    ids; Phone/Email from the customer record; Notes from the invoice
    row. Contact Name comes from the invoice row's contact_name
    column (the Job Info card field, persisted by the invoice create
    POST; guarded — pre-migration rows read blank). Tax-exempt is
    invoice-level (tweak round 4): tax_exempt_source is "cert" when
    a tax-exempt certificate doc is attached to THIS invoice,
    "customer" when the customer record's tax_exempt flag is set,
    "operator" when the invoice's tax_exempt_op click is set, else
    ""; tax_exempt is bool(source). Per-line tax_exempt flags no
    longer drive this box."""
    out = {"po": "", "jobs": [], "wells": [], "locations": [],
           "tax_exempt": False, "tax_exempt_source": "",
           "po_doc": None, "tax_doc": None,
           "shipping_doc": None, "custom_doc": None,
           "afes": [], "afe": "", "contact_name": "",
           "contact_phone": "", "contact_email": "", "cost_code": "",
           "ticket_refs": [], "ticket_ref": "", "job_notes": ""}
    try:
        inv = con.execute("SELECT * FROM invoices WHERE invoice_no=?",
                          (invoice_no,)).fetchone()
    except Exception:
        return out
    if not inv:
        return out
    def _icol(row, key):
        try:
            return (row[key] or "") if key in row.keys() else ""
        except Exception:
            return ""
    out["po"] = _icol(inv, "po").strip()
    out["job_notes"] = _icol(inv, "notes").strip()
    out["cost_code"] = _icol(inv, "po_cost_code").strip()
    out["contact_name"] = _icol(inv, "contact_name").strip()
    try:
        _pc = po_check(con, invoice_no)
        if _pc.get("cost_code"):
            out["cost_code"] = _pc["cost_code"]
    except Exception:
        pass
    try:
        cust = con.execute(
            "SELECT phone, email FROM customers WHERE id=?",
            (_icol(inv, "customer_id"),)).fetchone()
        if cust:
            out["contact_phone"] = (cust["phone"] or "").strip()
            out["contact_email"] = (cust["email"] or "").strip()
    except Exception:
        pass
    _cust_exempt = False
    try:
        _cx = con.execute(
            "SELECT tax_exempt FROM customers WHERE id=?",
            (_icol(inv, "customer_id"),)).fetchone()
        _cust_exempt = bool(_cx and _cx[0])
    except Exception:
        _cust_exempt = False
    wells: list = []
    locs: list = []
    jobs: list = []
    afes: list = []
    trefs: list = []
    def _add(tid: str):
        if tid and tid not in trefs:
            trefs.append(tid)
        t = con.execute("""SELECT t.well_or_pad, t.job_name, t.afe, s.site_name FROM tickets t
                           LEFT JOIN sites s ON s.id=t.site_id
                           WHERE t.ticket_id=?""", (tid,)).fetchone()
        if not t:
            return
        w = (t["well_or_pad"] or "").strip()
        s = (t["site_name"] or "").strip()
        j = (t["job_name"] or "").strip()
        a = (t["afe"] or "").strip() if "afe" in t.keys() else ""
        if w and w not in wells:
            wells.append(w)
        if s and s not in locs:
            locs.append(s)
        if j and j not in jobs:
            jobs.append(j)
        if a and a not in afes:
            afes.append(a)
    _ikey = inv["id"]
    try:
        for (tid,) in con.execute("SELECT ticket_id FROM tickets WHERE invoice_id=?",
                                  (_ikey,)):
            _add(tid)
        for (tkey,) in con.execute("""SELECT ticket_id FROM work_orders
                                    WHERE invoice_id=? AND ticket_id IS NOT NULL""",
                                   (_ikey,)):
            _add(doc_num(con, "ticket", tkey))
    except Exception:
        pass
    _qn = doc_num(con, "quote", inv["quote_id"]) if inv["quote_id"] else ""
    if _qn and not afes:
        try:
            q = con.execute("SELECT afe FROM quotes WHERE quote_no=?",
                            (_qn,)).fetchone()
            if q and (q["afe"] or "").strip():
                afes.append(q["afe"].strip())
        except Exception:
            pass
    out["wells"] = wells
    out["jobs"] = jobs
    out["locations"] = locs
    out["afes"] = afes
    out["afe"] = ", ".join(afes)
    out["ticket_refs"] = trefs
    out["ticket_ref"] = ", ".join(trefs)
    out["po_doc"] = get_invoice_doc(con, invoice_no, "po")
    out["tax_doc"] = get_invoice_doc(con, invoice_no, "tax_exempt")
    out["shipping_doc"] = get_invoice_doc(con, invoice_no, "shipping")
    out["custom_doc"] = get_invoice_doc(con, invoice_no, "custom")
    # Tax-exempt derivation (tweak round 4): invoice-level sources in
    # priority order — cert > customer > operator. The old per-line
    # heuristic (any invoice_lines.tax_exempt=1) is deleted: a single
    # untaxed line no longer marks the whole invoice exempt.
    _tax_source = ""
    if out["tax_doc"]:
        _tax_source = "cert"
    elif _cust_exempt:
        _tax_source = "customer"
    else:
        _op = _icol(inv, "tax_exempt_op")
        if _op == 1 or _op == "1":
            _tax_source = "operator"
    out["tax_exempt_source"] = _tax_source
    out["tax_exempt"] = bool(_tax_source)
    return out

def quote_check(con, quote_no: str) -> dict:
    """Quote-expiry status for the amber nudge. Mirrors po_check: the expiry
    (valid_until) is logged on the quote record itself, and any ticket, work
    order, or invoice carrying the quote_no gets the warning when the quote is
    past expiry. View-only — never a gate, never printed as a line."""
    out = {"quote_no": (quote_no or "").strip(), "expired": False,
           "days": None, "date_str": ""}
    qn = out["quote_no"]
    if not qn:
        return out
    try:
        q = con.execute(
            "SELECT valid_until FROM quotes WHERE quote_no=?", (qn,)).fetchone()
    except Exception:
        return out  # pre-migration DB: no quotes table detail yet
    if not q:
        return out
    exp = (q["valid_until"] or "").strip()
    if not exp:
        return out
    d = _parse(exp)
    out["date_str"] = d.strftime("%a %m/%d/%Y") if d else exp
    if d:
        out["days"] = (d - date.today()).days
        out["expired"] = out["days"] < 0
    return out
def add_invoice_line(con, invoice_no: str, data: dict) -> int:
    if not con.execute("SELECT 1 FROM invoices WHERE invoice_no=?",(invoice_no,)).fetchone(): raise ValueError("Unknown invoice")
    if invoice_locked(con,invoice_no): raise ValueError("Invoice is locked (sent, paid, or has payments)")
    if not invoice_has_lines(con,invoice_no): raise ValueError("Invoice must contain a billed Rental Ticket or Work Order before extra lines")
    desc=(data.get("description") or "").strip(); cat=(data.get("category") or "").strip(); uom=(data.get("uom") or "").strip()
    if not desc: raise ValueError("Description must match the PO wording")
    # Global dropdown rule (Issue 4): any non-empty category/unit is kept
    # as-is — typed-over Other values save on this line. The -Add-
    # sentinel degrades to the neutral default, never stored.
    if cat == "__add__": cat = "Other"
    if uom == "__add__": uom = "Each"
    if not cat: raise ValueError("Pick a line category")
    if not uom: raise ValueError("Pick a unit")
    qty=_money(data.get("qty") or 0); rate=_money(data.get("rate") or 0)
    if qty<=0: raise ValueError("Qty must be greater than zero")
    amt=(qty*rate).quantize(CENT,rounding=ROUND_HALF_UP); inv=con.execute("SELECT customer_id FROM invoices WHERE invoice_no=?",(invoice_no,)).fetchone()
    ikey = key_of(con, "invoices", invoice_no)
    src=con.execute("SELECT DISTINCT tax_rate,tax_exempt,tax_name,tax_loc FROM invoice_lines WHERE invoice_id=? AND source_type IN ('ticket','work_order')",(ikey,)).fetchall()
    if data.get("tax_rate") not in (None,""):
        tr=_money(data.get("tax_rate")); tax_name=(data.get("tax_name") or "Tax").strip(); tax_loc=(data.get("tax_loc") or "MANUAL").strip(); exempt=bool(data.get("tax_exempt"))
    elif len({(r["tax_loc"],float(r["tax_rate"]),int(r["tax_exempt"] or 0)) for r in src})==1 and src:
        tr=_money(src[0]["tax_rate"]); tax_name=src[0]["tax_name"] or "Tax"; tax_loc=src[0]["tax_loc"] or ""; exempt=bool(src[0]["tax_exempt"])
    else:
        cust=con.execute("SELECT tax_exempt FROM customers WHERE id=?",(inv["customer_id"],)).fetchone(); exempt=bool(cust and cust["tax_exempt"]); tr=_money(0); tax_name=""; tax_loc=""
        if len(src)>1: raise ValueError("Invoice has multiple tax jurisdictions; specify tax_rate and tax_loc for the extra line")
    tax=Decimal("0.00") if exempt else (amt*tr).quantize(CENT,rounding=ROUND_HALF_UP)
    # Operator's per-line Tax toggle (invoice round, Jason 2026-10-20):
    # the detail Add-a-Line form posts a tax_ui sentinel; with it, an
    # untoggled line is not taxable on the operator's say-so, whatever
    # the jurisdiction resolution above decided.
    if data.get("tax_ui") and not data.get("taxable"):
        exempt=True; tax=Decimal("0.00")
    # B4: source_id is NOT NULL, so a manual ("extra") line can't insert with
    # source_id=None. Point it at its own line_id — traceable and unique.
    cur=con.execute("""INSERT INTO invoice_lines(invoice_id,po_line,category,item,description,qty,uom,rate,amount,clerk,tax_rate,tax_amount,tax_exempt,tax_name,tax_loc,source_type,source_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(ikey,(data.get("po_line") or "").strip(),cat,(data.get("item") or "").strip(),desc,float(qty),uom,float(rate),float(amt),require_clerk(data.get("clerk")),float(0 if exempt else tr),float(tax),int(exempt),tax_name,tax_loc,"extra","pending")); con.commit()
    lid=int(cur.lastrowid)
    con.execute("UPDATE invoice_lines SET source_id=? WHERE line_id=?",(f"extra-{lid}",lid)); con.commit(); return lid
def drop_invoice_line(con, line_id: int, clerk: str = "") -> None:
    require_clerk(clerk)
    row = con.execute("SELECT invoice_id FROM invoice_lines WHERE line_id=?", (line_id,)).fetchone()
    if not row:
        raise ValueError("Unknown line")
    if invoice_locked(con, num_of(con, "invoices", row["invoice_id"])):
        raise ValueError("Invoice is locked (sent, paid, or has payments)")
    src=con.execute("SELECT source_type FROM invoice_lines WHERE line_id=?",(line_id,)).fetchone()
    if src and src["source_type"] not in (None,"","extra"):
        raise ValueError("Billed source lines cannot be changed")
    con.execute("DELETE FROM invoice_lines WHERE line_id=?", (line_id,))
    con.commit()
def _ensure_saved_exports(con: sqlite3.Connection) -> None:
    """Compatibility assertion; schema.sql owns current table DDL."""
    if not con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='saved_exports'").fetchone():
        raise RuntimeError("Database schema is incomplete: saved_exports is missing")
def list_saved_exports(con: sqlite3.Connection) -> list[dict]:
    _ensure_saved_exports(con)
    return [
        dict(r)
        for r in con.execute("SELECT * FROM saved_exports ORDER BY label, export_id")
    ]
def save_export(
    con: sqlite3.Connection,
    label: str,
    what: str,
    when: str,
    from_date: str,
    to_date: str,
    how: str,
) -> int:
    """Save an export preset. Returns the new export_id."""
    import exportpack  # lazy: exportpack imports engine

    _ensure_saved_exports(con)
    label = (label or "").strip()
    if not label:
        raise ValueError("Preset name is required")
    valid_whats = [k for k, _ in exportpack.PACK_LABELS]
    if what not in valid_whats:
        raise ValueError("Unknown export choice")
    if when not in EXPORT_WHENS:
        raise ValueError("Unknown date range choice")
    if how not in EXPORT_HOWS:
        raise ValueError("Unknown format choice")
    if when == "custom" and not (from_date and to_date):
        raise ValueError("Custom range needs both From and To dates")
    cur = con.execute(
        'INSERT INTO saved_exports (label, what, "when", from_date, to_date, how)'
        " VALUES (?, ?, ?, ?, ?, ?)",
        (label[:60], what, when, from_date or None, to_date or None, how),
    )
    con.commit()
    return cur.lastrowid
def delete_saved_export(con: sqlite3.Connection, export_id) -> None:
    _ensure_saved_exports(con)
    try:
        eid = int(export_id)
    except (TypeError, ValueError):
        raise ValueError("Unknown saved export") from None
    cur = con.execute("DELETE FROM saved_exports WHERE export_id=?", (eid,))
    con.commit()
    if cur.rowcount == 0:
        raise ValueError("Saved export not found")
def next_customer_id(con) -> str:
    rows = con.execute("SELECT customer_id FROM customers").fetchall()
    nums = []
    for r in rows:
        s = r["customer_id"]
        if s and s.upper().startswith("C-"):
            try:
                nums.append(int(s.split("-", 1)[1]))
            except ValueError:
                pass
    return f"C-{max(nums, default=0) + 1:03d}"
def save_customer(con, data: dict, customer_id: str | None = None) -> str:
    name = (data.get("account_name") or "").strip()
    if not name:
        raise ValueError("Account name is required")
    # ITEM F: terms are the same custom system as line Type/Unit —
    # any non-empty string saves verbatim (one-off custom terms are
    # legal and are NOT forced into the lookups list). Empty falls
    # back to the book default (company.default_terms, fallback
    # "Net 30"), not a hardcoded value.
    terms = (data.get("terms") or "").strip()
    if not terms:
        try:
            _crow = con.execute(
                "SELECT default_terms FROM company WHERE id=1").fetchone()
            terms = ((_crow["default_terms"] or "").strip()
                     if _crow else "")
        except Exception:
            terms = ""
        if not terms:
            terms = "Net 30"
    cid = customer_id or next_customer_id(con)
    # Keep the legacy city_st column in sync as "City, ST" for letterhead/print reads.
    city_st = ", ".join(p for p in ((data.get("bill_city") or "").strip(),
                                    (data.get("bill_state") or "").strip()) if p)
    row = (
        name, data.get("short_name") or "", data.get("bill_to") or "",
        format_phone_number(data.get("phone") or ""), data.get("email") or "",
        data.get("bill_street") or "", data.get("bill_street2") or "",
        data.get("bill_city") or "",
        data.get("bill_state") or "", data.get("bill_zip") or "",
        city_st,
        terms, 1 if data.get("tax_exempt") else 0, 1 if data.get("waiver_default") else 0,
        float(data["credit_limit"]) if data.get("credit_limit") else None,
        data.get("notes") or "", cid,
    )
    exists = con.execute("SELECT 1 FROM customers WHERE customer_id=?", (cid,)).fetchone()
    if exists:
        con.execute(
            """UPDATE customers SET account_name=?, short_name=?, bill_to=?, phone=?, email=?,
               bill_street=?, bill_street2=?, bill_city=?, bill_state=?, bill_zip=?,
               city_st=?, terms=?, tax_exempt=?, waiver_default=?, credit_limit=?, notes=?
               WHERE customer_id=?""",
            row,
        )
    else:
        con.execute(
            """INSERT INTO customers (account_name, short_name, bill_to, phone, email,
               bill_street, bill_street2, bill_city, bill_state, bill_zip,
               city_st, terms, tax_exempt, waiver_default, credit_limit, notes, customer_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            row,
        )
    # Maintain normalized contact/location records while preserving legacy fields used by prints/exports.
    ckey = cust_key(con, cid)
    if (data.get("bill_to") or "").strip():
        con.execute("UPDATE customer_contacts SET is_primary=0 WHERE customer_id=?", (ckey,))
        con.execute("DELETE FROM customer_contacts WHERE customer_id=? AND is_primary=1", (ckey,))
        con.execute("INSERT INTO customer_contacts(customer_id,name,role,phone,email,is_primary) VALUES (?,?,?,?,?,1)",
                     (ckey, (data.get("bill_to") or "").strip(), "Accounting / Billing", data.get("phone") or "", data.get("email") or ""))
    if not con.execute("SELECT 1 FROM customer_locations WHERE customer_id=?", (ckey,)).fetchone() and any((data.get(k) or "").strip() for k in ("bill_street","bill_city","bill_state","bill_zip")):
        con.execute("INSERT INTO customer_locations(customer_id,location_name,street,street2,city,state,zip,is_primary) VALUES (?,?,?,?,?,?,?,1)",
                     (ckey, "Primary / Billing", data.get("bill_street") or "", data.get("bill_street2") or "", data.get("bill_city") or "", data.get("bill_state") or "", data.get("bill_zip") or ""))
    con.commit()
    return cid
def report_invoicing(con: sqlite3.Connection) -> dict:
    today = date.today()
    ready_rows = []
    ready_amt = 0.0
    for t in con.execute(
        """SELECT t.ticket_id, t.customer_id, c.account_name, a.unit_no, t.status
           FROM tickets t
           JOIN customers c ON c.id = t.customer_id
           JOIN assets a ON a.id = t.asset_id
           WHERE t.status IN ('Ready to Bill','Off Rent')
             AND t.invoice_id IS NULL
           ORDER BY t.customer_id"""
    ):
        m = ticket_money(con, t["ticket_id"])
        ready_rows.append({
            "ticket_id": t["ticket_id"],
            "account_name": t["account_name"],
            "unit_no": t["unit_no"],
            "status": t["status"],
            "total": m["total"],
        })
        ready_amt += m["total"]

    buckets = {"Current": 0.0, "1–30": 0.0, "31–60": 0.0, "61–90": 0.0, "90+": 0.0}
    invoices = []
    for inv in con.execute(
        """SELECT i.invoice_no, i.invoice_date, i.customer_id, i.terms, i.status,
                  c.account_name
           FROM invoices i JOIN customers c ON c.id = i.customer_id
           ORDER BY i.invoice_date"""
    ):
        tot = invoice_totals(con, inv["invoice_no"])
        d0 = _parse(inv["invoice_date"]) or today
        due = d0 + timedelta(days=terms_days(inv["terms"]))
        late = (today - due).days if tot["balance"] > 0.009 else 0
        if tot["balance"] <= 0.009:
            bucket = "Paid"
        elif today <= due:
            bucket = "Current"
        elif late <= 30:
            bucket = "1–30"
        elif late <= 60:
            bucket = "31–60"
        elif late <= 90:
            bucket = "61–90"
        else:
            bucket = "90+"
        if bucket in buckets:
            buckets[bucket] += tot["balance"]
        invoices.append({
            "invoice_no": inv["invoice_no"],
            "account_name": inv["account_name"],
            "invoice_date": str(inv["invoice_date"])[:10],
            "due": due.isoformat(),
            "terms": inv["terms"],
            "status": inv["status"],
            "total": tot["total"],
            "paid": tot["paid"],
            "balance": tot["balance"],
            "bucket": bucket,
            "days_late": max(late, 0) if tot["balance"] > 0.009 else 0,
        })
    return {
        "ready": ready_rows,
        "ready_amt": round(ready_amt, 2),
        "invoices": invoices,
        "buckets": {k: round(v, 2) for k, v in buckets.items()},
        "open_ar": round(sum(buckets.values()), 2),
    }
def report_revenue(con: sqlite3.Connection, kind: str = "mtd") -> dict:
    start, end, label = period_bounds(kind)
    billed = 0.0
    cash = 0.0
    by_cust: dict[str, dict] = {}
    by_unit: dict[str, dict] = {}
    by_month: dict[str, dict] = {}

    def bucket_cust(cid, name):
        if cid not in by_cust:
            by_cust[cid] = {"customer_id": cid, "account_name": name, "billed": 0.0, "cash": 0.0, "invoices": 0}
        return by_cust[cid]

    def bucket_unit(aid, unit, desc):
        if aid not in by_unit:
            by_unit[aid] = {"asset_id": aid, "unit_no": unit, "description": desc, "billed": 0.0, "tickets": 0}
        return by_unit[aid]

    for inv in con.execute(
        """SELECT i.id, i.invoice_no, i.invoice_date, i.customer_id, c.account_name
           FROM invoices i JOIN customers c ON c.id = i.customer_id"""
    ):
        d = _parse(inv["invoice_date"])
        if not d or d < start or d > end:
            continue
        tot = invoice_totals(con, inv["invoice_no"])
        billed += tot["total"]
        bc = bucket_cust(cust_code(con, inv["customer_id"]), inv["account_name"])
        bc["billed"] += tot["total"]
        bc["invoices"] += 1
        key = d.strftime("%Y-%m")
        by_month.setdefault(key, {"month": key, "billed": 0.0, "cash": 0.0})
        by_month[key]["billed"] += tot["total"]
        for t in con.execute(
            """SELECT t.ticket_id, a.asset_id AS asset_code, a.unit_no, a.description
               FROM tickets t JOIN assets a ON a.id = t.asset_id
               WHERE t.invoice_id=?""",
            (inv["id"],),
        ):
            line = con.execute("SELECT COALESCE(SUM(amount + tax_amount),0) FROM invoice_lines WHERE invoice_id=? AND source_type='ticket' AND source_id=?", (inv["id"], t["ticket_id"])).fetchone()
            bu = bucket_unit(t["asset_code"], t["unit_no"], t["description"] or "")
            bu["billed"] += float(line[0] or 0)
            bu["tickets"] += 1

    for p in con.execute(
        """SELECT c.pay_date, c.amount, i.customer_id, cu.account_name
           FROM collections c
           JOIN invoices i ON i.id = c.invoice_id
           JOIN customers cu ON cu.id = i.customer_id
           WHERE c.kind='payment'"""
    ):
        d = _parse(p["pay_date"])
        if not d or d < start or d > end:
            continue
        cash += float(p["amount"] or 0)
        bc = bucket_cust(cust_code(con, p["customer_id"]), p["account_name"])
        bc["cash"] += float(p["amount"] or 0)
        key = d.strftime("%Y-%m")
        by_month.setdefault(key, {"month": key, "billed": 0.0, "cash": 0.0})
        by_month[key]["cash"] += float(p["amount"] or 0)

    customers = sorted(by_cust.values(), key=lambda x: -x["billed"])
    units = sorted(by_unit.values(), key=lambda x: -x["billed"])
    months = sorted(by_month.values(), key=lambda x: x["month"])
    for row in customers + units + months:
        for k in ("billed", "cash"):
            if k in row:
                row[k] = round(row[k], 2)
    return {
        "kind": kind,
        "label": label,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "billed": round(billed, 2),
        "cash": round(cash, 2),
        "customers": customers,
        "units": units,
        "months": months,
    }
def report_recap(con: sqlite3.Connection, kind: str = "mtd") -> dict:
    start, end, label = period_bounds(kind)
    new_tix = []
    for t in con.execute(
        """SELECT t.ticket_id, t.status, t.on_rent, t.customer_id, a.unit_no, c.account_name
           FROM tickets t
           JOIN assets a ON a.id = t.asset_id
           JOIN customers c ON c.id = t.customer_id
           ORDER BY t.on_rent"""
    ):
        d = _parse(t["on_rent"])
        if d and start <= d <= end:
            r = dict(t)
            r["customer_id"] = cust_code(con, r["customer_id"])
            new_tix.append(r)
    offed = []
    for t in con.execute(
        """SELECT t.ticket_id, t.status, t.off_rent, a.unit_no, c.account_name
           FROM tickets t
           JOIN assets a ON a.id = t.asset_id
           JOIN customers c ON c.id = t.customer_id
           WHERE t.off_rent IS NOT NULL AND t.off_rent != ''"""
    ):
        d = _parse(t["off_rent"])
        if d and start <= d <= end:
            offed.append(dict(t))
    fail_open = 0
    for t in con.execute(
        "SELECT ticket_id FROM tickets WHERE status IN ('Quoted','Reserved','Dispatched','On Rent','Standby')"
    ):
        if ticket_money(con, t["ticket_id"]).get("fit") != "PASS":
            fail_open += 1
    rev = report_revenue(con, kind)
    on_now = con.execute(
        "SELECT COUNT(*) FROM tickets WHERE status IN ('On Rent','Standby')"
    ).fetchone()[0]
    return {
        "label": label,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "new_tickets": new_tix,
        "new_n": len(new_tix),
        "off_n": len(offed),
        "offs": offed,
        "billed": rev["billed"],
        "cash": rev["cash"],
        "fail_open": fail_open,
        "on_now": on_now,
        "cust_n": len(rev["customers"]),
    }


