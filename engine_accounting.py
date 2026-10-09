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

from engine_assets import create_ticket, ticket_money, clean_rate_unit, RATE_UNITS

"""FleetSheet engine: accounting flow — quotes, invoices, payments, credit memos, petty cash, exports, revenue reports."""

__all__ = ['next_invoice_id', 'create_invoice', 'invoice_has_lines', '_next_pay_id', '_refresh_invoice_status', 'record_payment', 'next_cm_id', 'credit_applied', 'credit_open', '_apply_credit_rows', 'issue_credit_memo', 'apply_open_credit', 'list_open_credits', 'list_open_invoices', 'big_fish_invoices', 'next_quote_id', 'next_co_id', '_line_amount', 'save_quote', 'set_quote_status', 'issue_change_order', 'quote_totals', 'quote_pack', 'convert_quote', 'next_pc_id', 'petty_balance', 'petty_book', 'set_pc_float', 'record_petty', 'invoice_totals', 'invoice_balance', 'invoice_locked', 'set_invoice_po', 'upsert_po_record', 'ack_po_record', 'po_record', 'backfill_po_records', 'po_check', 'quote_check',
 'save_invoice_doc', 'get_invoice_doc', 'read_invoice_doc', 'delete_invoice_doc', 'invoice_job_box', 'INV_DOC_KINDS', 'add_invoice_line', 'drop_invoice_line', '_ensure_saved_exports', 'list_saved_exports', 'save_export', 'delete_saved_export', 'next_customer_id', 'save_customer', 'report_invoicing', 'report_revenue', 'report_recap']

def next_invoice_id(con: sqlite3.Connection) -> str:
    prefix = con.execute("SELECT invoice_prefix FROM company WHERE id=1").fetchone()[0]
    while True:
        n = _reserve_counter(con, "next_invoice", 1001)
        ino = f"{prefix}-{n}"
        if not con.execute("SELECT 1 FROM invoices WHERE invoice_no=?", (ino,)).fetchone():
            return ino
def create_invoice(con: sqlite3.Connection, customer_id: str, ticket_ids: list[str], inv_date: str|None=None, wo_ids: list[str]|None=None, quote_no: str|None=None, po: str|None=None, po_expire: str|None=None, po_cost_code: str|None=None, po_notes: str|None=None) -> str:
    ticket_ids=list(dict.fromkeys(ticket_ids or [])); wo_ids=list(dict.fromkeys(wo_ids or []))
    if not ticket_ids and not wo_ids and not customer_id:
        raise ValueError("Pick a customer")
    # Standalone invoice is legal: no ticket, no work order, no quote. The
    # chain is a chain, not a cage — an invoice alone must always be possible.
    ts=[]; ws=[]
    for tid in ticket_ids:
        t=con.execute("SELECT * FROM tickets WHERE ticket_id=?",(tid,)).fetchone()
        if not t: raise ValueError(tid)
        if t["customer_id"]!=customer_id: raise ValueError(f"{tid} belongs to another customer")
        if t["invoice_no"]: raise ValueError(f"{tid} already belongs to {t['invoice_no']}")
        if t["status"] not in ("Ready to Bill","Off Rent"): raise ValueError(f"{tid} is {t['status']}, not ready")
        if not t["in_condition"]: raise ValueError(f"{tid} has no check-in condition")
        ts.append(t)
    for wid in wo_ids:
        w=con.execute("SELECT * FROM work_orders WHERE wo_id=?",(wid,)).fetchone()
        if not w: raise ValueError(wid)
        if w["customer_id"]!=customer_id: raise ValueError(f"{wid} belongs to another customer")
        if w["charge_to"]!="customer" or w["status"]!="Complete" or _money(w["bill_amount"])<=0: raise ValueError(f"{wid} is not a completed billable work order")
        if w["invoice_no"]: raise ValueError(f"{wid} already on {w['invoice_no']}")
        ws.append(w)
    terms=con.execute("SELECT terms FROM customers WHERE customer_id=?",(customer_id,)).fetchone()["terms"]; ino=next_invoice_id(con); d=inv_date or date.today().isoformat(); qn=(quote_no or "").strip() or None
    if qn:
        q=con.execute("SELECT customer_id,status FROM quotes WHERE quote_no=?",(qn,)).fetchone()
        if not q: raise ValueError("Unknown quote")
        if q["customer_id"]!=customer_id: raise ValueError("Quote belongs to another customer")
        if q["status"]=="Void": raise ValueError("Cannot bill a void quote")
    try:
        con.execute("INSERT INTO invoices(invoice_no,invoice_date,customer_id,terms,status,quote_no,po,po_expire,po_cost_code,po_notes) VALUES (?,?,?,?,?,?,?,?,?,?)",(ino,d,customer_id,terms,"Ready",qn,(po or "").strip() or None,(po_expire or "").strip() or None,(po_cost_code or "").strip() or None,(po_notes or "").strip() or None))
        for t in ts:
            m=ticket_money(con,t["ticket_id"])
            desc=f"{t['ticket_id']} — {m['unit_no']} {m['description'] or ''}".strip()
            if t["rate_type"]=="Hour" and m.get("hours",0)>0:
                desc=f"{desc} — {m['hours']:g} hrs @ ${m['rate']:,.2f}/hr"
            con.execute("""INSERT INTO invoice_lines(invoice_no,po_line,category,description,qty,uom,rate,amount,clerk,tax_rate,tax_amount,tax_exempt,tax_name,tax_loc,source_type,source_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(ino,t["po"] or "","Rental",desc,1,"Each",m["subtotal"],m["subtotal"],"",m["tax_rate"],m["tax"],int(bool(m["tax_exempt"])),m["tax_name"],m["tax_loc"],"ticket",t["ticket_id"]))
            con.execute("UPDATE tickets SET invoice_no=?,status='Billed' WHERE ticket_id=?",(ino,t["ticket_id"]))
        cust_exempt=bool(con.execute("SELECT tax_exempt FROM customers WHERE customer_id=?",(customer_id,)).fetchone()[0])
        for w in ws:
            amt=_money(w["bill_amount"]); exempt=cust_exempt; rate=_money(0); tax_name=""; tax_loc=""
            if w["ticket_id"]:
                tm=ticket_money(con,w["ticket_id"]); exempt=bool(tm["tax_exempt"]); rate=_money(tm["tax_rate"]); tax_name=tm["tax_name"]; tax_loc=tm["tax_loc"]
            tax=Decimal("0.00") if exempt else (amt*rate).quantize(CENT,rounding=ROUND_HALF_UP)
            con.execute("""INSERT INTO invoice_lines(invoice_no,po_line,category,description,qty,uom,rate,amount,clerk,tax_rate,tax_amount,tax_exempt,tax_name,tax_loc,source_type,source_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(ino,"","Labor",f"{w['wo_id']} — {w['description']}",1,"Each",float(amt),float(amt),"",float(0 if exempt else rate),float(tax),int(exempt),tax_name,tax_loc,"work_order",w["wo_id"]))
            con.execute("UPDATE work_orders SET invoice_no=? WHERE wo_id=?",(ino,w["wo_id"]))
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
    return con.execute("SELECT 1 FROM invoice_lines WHERE invoice_no=? LIMIT 1",(invoice_no,)).fetchone() is not None
def _next_pay_id(con) -> str:
    row=con.execute("SELECT next_payment FROM company WHERE id=1").fetchone(); n=int(row["next_payment"] or 1)
    con.execute("UPDATE company SET next_payment=? WHERE id=1",(n+1,)); return f"P-{n:03d}"
def _refresh_invoice_status(con, invoice_no: str) -> None:
    tot=invoice_totals(con,invoice_no); cur=con.execute("SELECT status FROM invoices WHERE invoice_no=?",(invoice_no,)).fetchone()
    if not cur: return
    st="Paid" if tot["balance"]<=0.009 else ("Partial" if tot["paid"]>0.009 else (cur["status"] if cur["status"] not in ("Paid","Partial") else "Ready"))
    con.execute("UPDATE invoices SET status=? WHERE invoice_no=?",(st,invoice_no))
def record_payment(con: sqlite3.Connection, invoice_no: str, amount: float, pay_date: str, method: str, ref: str="", clerk: str="") -> dict:
    """Apply cash to an invoice. Best practice for overpayments: the invoice
    is paid in full and the excess is kept as an OPEN customer credit memo
    (auto-issued, unapplied) that the clerk can apply to other invoices on
    the /credit page. Returns {"pay_id","applied","credit_memo","credit_amount"}."""
    inv=con.execute("SELECT invoice_no, customer_id FROM invoices WHERE invoice_no=?",(invoice_no,)).fetchone()
    if not inv: raise ValueError("Payment must attach to an existing invoice")
    if not invoice_has_lines(con,invoice_no): raise ValueError("Invoice has no invoice lines — cannot take payment")
    amount=_money(amount)
    if amount<=0: raise ValueError("Payment amount must be positive")
    method=(method or "").strip()
    if method not in CASH_METHODS: raise ValueError("Pick ACH, Check, Wire, Card, Cash, or Petty cash")
    who=require_clerk(clerk)
    bal=_money(invoice_balance(con,invoice_no))
    applied=min(amount,bal); excess=amount-applied
    pid=_next_pay_id(con)
    con.execute("""INSERT INTO collections(pay_id,pay_date,invoice_no,method,amount,ref_no,kind,clerk,applied_amount,unapplied_amount) VALUES (?,?,?,?,?,?, 'payment',?,?,?)""",(pid,pay_date,invoice_no,method,float(applied),ref,who,float(applied),0.0))
    cm_no=None
    if excess>Decimal("0.009"):
        cm_no=next_cm_id(con)
        con.execute("""INSERT INTO credit_memos(cm_no, cm_date, customer_id, face_amount, reason, notes, clerk) VALUES (?,?,?,?,?,?,?)""",
            (cm_no, pay_date or date.today().isoformat(), inv["customer_id"], float(excess),
             f"Overpayment on {invoice_no}",
             f"Auto-created: customer paid ${amount:,.2f}; ${applied:,.2f} applied to {invoice_no} (payment {pid}), ${excess:,.2f} kept as open credit.",
             who))
    _refresh_invoice_status(con,invoice_no); con.commit()
    return {"pay_id":pid,"applied":float(applied),"credit_memo":cm_no,"credit_amount":float(excess)}
def next_cm_id(con: sqlite3.Connection) -> str:
    while True:
        n = _reserve_counter(con, "next_cm", 1001)
        cno = f"CM-{n:04d}"
        if not con.execute("SELECT 1 FROM credit_memos WHERE cm_no=?", (cno,)).fetchone():
            return cno
def credit_applied(con: sqlite3.Connection, cm_no: str) -> float:
    row = con.execute(
        "SELECT COALESCE(SUM(COALESCE(applied_amount,amount)),0) FROM collections WHERE cm_no=? AND kind='credit'",
        (cm_no,),
    ).fetchone()
    return float(row[0] or 0)
def credit_open(con: sqlite3.Connection, cm_no: str) -> dict:
    cm = con.execute("SELECT * FROM credit_memos WHERE cm_no=?", (cm_no,)).fetchone()
    if not cm:
        raise ValueError("Unknown credit memo")
    applied = credit_applied(con, cm_no)
    face = float(cm["face_amount"])
    return {
        "cm_no": cm["cm_no"],
        "cm_date": str(cm["cm_date"])[:10],
        "customer_id": cm["customer_id"],
        "reason": cm["reason"],
        "notes": cm["notes"] or "",
        "face": round(face, 2),
        "applied": round(applied, 2),
        "unapplied": round(face - applied, 2),
    }
def _apply_credit_rows(con, cm_no: str, customer_id: str, applies: list, pay_date: str,
                      clerk: str = "") -> float:
    """applies = [(invoice_no, amount), ...]. Returns total applied this call."""
    used = 0.0
    seen = set()
    for invoice_no, raw in applies:
        invoice_no = (invoice_no or "").strip()
        if not invoice_no:
            continue
        try:
            amt = float(raw)
        except (TypeError, ValueError):
            raise ValueError(f"Bad apply amount on {invoice_no}") from None
        if amt <= 0:
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
        if inv["customer_id"] != customer_id:
            raise ValueError(f"{invoice_no} belongs to another customer")
        if not invoice_has_lines(con, invoice_no):
            raise ValueError(f"{invoice_no} has no tickets or work orders")
        bal = invoice_balance(con, invoice_no)
        if amt - bal > 0.009:
            raise ValueError(f"{invoice_no} balance is ${bal:,.2f}")
        pid = _next_pay_id(con)
        con.execute(
            """INSERT INTO collections(pay_id, pay_date, invoice_no, method, amount, ref_no, kind, cm_no, clerk)
               VALUES (?,?,?,?,?,?, 'credit', ?, ?)""",
            (pid, pay_date, invoice_no, "Credit memo", amt, cm_no, cm_no, clerk or ""),
        )
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
) -> str:
    """Open a credit memo. Apply all, part, or none to existing invoices of that customer."""
    cust = con.execute("SELECT customer_id FROM customers WHERE customer_id=?", (customer_id,)).fetchone()
    if not cust:
        raise ValueError("Unknown customer")
    try:
        face = float(face_amount)
    except (TypeError, ValueError):
        raise ValueError("Credit amount must be a number") from None
    if face <= 0:
        raise ValueError("Credit amount must be positive")
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("Reason is required")
    d = cm_date or date.today().isoformat()
    applies = applies or []
    who = require_clerk(clerk)
    cm_no = next_cm_id(con)
    con.execute(
        """INSERT INTO credit_memos(cm_no, cm_date, customer_id, face_amount, reason, notes, clerk)
           VALUES (?,?,?,?,?,?,?)""",
        (cm_no, d, customer_id, face, reason, notes or "", who),
    )
    used = _apply_credit_rows(con, cm_no, customer_id, applies, d, who)
    if used - face > 0.009:
        raise ValueError("Applied more than the credit memo face")
    con.commit()
    return cm_no
def apply_open_credit(
    con: sqlite3.Connection,
    cm_no: str,
    applies: list,
    pay_date: str | None = None,
    clerk: str = "",
) -> float:
    """Use leftover credit against more invoices of the same customer."""
    info = credit_open(con, cm_no)
    if info["unapplied"] <= 0.009:
        raise ValueError("This credit memo is fully applied")
    who = require_clerk(clerk)
    d = pay_date or date.today().isoformat()
    used = _apply_credit_rows(con, cm_no, info["customer_id"], applies, d, who)
    if used <= 0:
        raise ValueError("Enter at least one apply amount")
    if used - info["unapplied"] > 0.009:
        raise ValueError(f"Only ${info['unapplied']:,.2f} left on {cm_no}")
    con.commit()
    return used
def list_open_credits(con: sqlite3.Connection, customer_id: str | None = None) -> list[dict]:
    q = "SELECT cm_no FROM credit_memos"
    args: list = []
    if customer_id:
        q += " WHERE customer_id=?"
        args.append(customer_id)
    q += " ORDER BY cm_date DESC, cm_no DESC"
    out = []
    for r in con.execute(q, args):
        info = credit_open(con, r["cm_no"])
        if info["unapplied"] > 0.009:
            out.append(info)
    return out
def list_open_invoices(con: sqlite3.Connection, customer_id: str | None = None) -> list[dict]:
    q = """SELECT i.invoice_no, i.invoice_date, i.status, i.customer_id, c.account_name
           FROM invoices i JOIN customers c ON c.customer_id=i.customer_id"""
    args: list = []
    if customer_id:
        q += " WHERE i.customer_id=?"
        args.append(customer_id)
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
            "customer_id": r["customer_id"],
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
        kind = ln.get("kind") or "other"
        # Line types (Jason 2026-10-07): item, unit, labor, freight, other.
        # "rental"/"service"/"transport" are legacy values still in old rows.
        if kind not in ("item", "unit", "labor", "freight", "other",
                        "rental", "service", "transport"):
            raise ValueError("Bad line type")
        qty = float(ln.get("qty") or 0)
        rate = float(ln.get("rate") or 0)
        if qty <= 0:
            continue
        aid = (ln.get("asset_id") or "").strip() or None
        if aid and not con.execute("SELECT 1 FROM assets WHERE asset_id=?", (aid,)).fetchone():
            raise ValueError(f"Unknown unit {aid}")
        clean.append((kind, aid, desc, qty, rate, clean_rate_unit(ln.get("rate_unit")), _line_amount(qty, rate)))
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
    qno = header.get("quote_no") or next_quote_id(con)
    exists = con.execute("SELECT status FROM quotes WHERE quote_no=?", (qno,)).fetchone()
    if exists and exists["status"] in ("Accepted", "Converted", "Void"):
        raise ValueError("Cannot edit an accepted, converted, or void quote")
    vals = (
        header.get("quote_date") or date.today().isoformat(),
        cid, site, header.get("job_name") or "", header.get("afe") or "",
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
        con.execute("DELETE FROM quote_lines WHERE quote_no=?", (qno,))
    else:
        con.execute(
            """INSERT INTO quotes(quote_date, customer_id, site_id, job_name, afe, po,
               valid_until, status, notes, clerk, quote_no) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            vals,
        )
    con.executemany(
        """INSERT INTO quote_lines(quote_no, kind, asset_id, description, qty, rate, rate_unit, amount)
           VALUES (?,?,?,?,?,?,?,?)""",
        [(qno,) + row for row in clean],
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
def issue_change_order(con, quote_no: str, reason: str, lines: list, co_date: str | None = None, notes: str = "", clerk: str = "", po: str = "") -> str:
    q = con.execute("SELECT status FROM quotes WHERE quote_no=?", (quote_no,)).fetchone()
    if not q:
        raise ValueError("Unknown quote")
    if q["status"] in ("Void", "Declined"):
        raise ValueError("Cannot change a void or declined quote")
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("Reason is required")
    clean = []
    for ln in lines:
        desc = (ln.get("description") or "").strip()
        if not desc:
            continue
        direction = ln.get("direction") or "add"
        if direction not in ("add", "subtract"):
            raise ValueError("Change is add or subtract")
        kind = ln.get("kind") or "other"
        # Same line types as quotes (Jason 2026-10-07); legacy values kept for old rows.
        if kind not in ("item", "unit", "labor", "freight", "other",
                        "rental", "service", "transport"):
            raise ValueError("Bad line type")
        qty = float(ln.get("qty") or 0)
        rate = float(ln.get("rate") or 0)
        if qty <= 0:
            continue
        amt = _line_amount(qty, rate)
        clean.append((direction, kind, desc, qty, rate, amt))
    if not clean:
        raise ValueError("Add at least one change line")
    cno = next_co_id(con)
    who = require_clerk(clerk)
    con.execute(
        """INSERT INTO change_orders(co_no, quote_no, po, co_date, reason, status, notes, clerk)
           VALUES (?,?,?,?,?, 'Issued', ?, ?)""",
        (cno, quote_no or None, (po or "").strip(), co_date or date.today().isoformat(), reason, notes or "", who),
    )
    con.executemany(
        """INSERT INTO change_order_lines(co_no, direction, kind, description, qty, rate, amount)
           VALUES (?,?,?,?,?,?,?)""",
        [(cno,) + row for row in clean],
    )
    con.commit()
    return cno
def quote_totals(con, quote_no: str) -> dict:
    base = float(con.execute(
        "SELECT COALESCE(SUM(amount),0) FROM quote_lines WHERE quote_no=?", (quote_no,)
    ).fetchone()[0] or 0)
    add = sub = 0.0
    for r in con.execute(
        """SELECT l.direction, l.amount FROM change_order_lines l
           JOIN change_orders c ON c.co_no=l.co_no
           WHERE c.quote_no=? AND c.status='Issued'""",
        (quote_no,),
    ):
        if r["direction"] == "add":
            add += float(r["amount"])
        else:
            sub += float(r["amount"])
    face = round(base + add - sub, 2)
    billed = 0.0
    for inv in con.execute("SELECT invoice_no FROM invoices WHERE quote_no=?", (quote_no,)):
        billed += invoice_totals(con, inv["invoice_no"])["total"]
    return {
        "quoted": round(base, 2),
        "co_add": round(add, 2),
        "co_sub": round(sub, 2),
        "face": face,
        "billed": round(billed, 2),
        "variance": round(billed - face, 2),
    }
def quote_pack(con, quote_no: str) -> dict | None:
    q = con.execute(
        """SELECT q.*, c.account_name, c.bill_to, c.phone, c.email, c.city_st
           FROM quotes q JOIN customers c ON c.customer_id=q.customer_id
           WHERE q.quote_no=?""",
        (quote_no,),
    ).fetchone()
    if not q:
        return None
    lines = [dict(r) for r in con.execute(
        "SELECT * FROM quote_lines WHERE quote_no=? ORDER BY line_id", (quote_no,)
    )]
    cos = []
    for co in con.execute(
        "SELECT * FROM change_orders WHERE quote_no=? ORDER BY co_date, co_no", (quote_no,)
    ):
        cl = [dict(r) for r in con.execute(
            "SELECT * FROM change_order_lines WHERE co_no=? ORDER BY line_id", (co["co_no"],)
        )]
        cos.append({"header": dict(co), "lines": cl})
    tickets = [dict(r) for r in con.execute(
        "SELECT ticket_id, status, invoice_no FROM tickets WHERE quote_no=? ORDER BY ticket_id", (quote_no,)
    )]
    wos = [dict(r) for r in con.execute(
        "SELECT wo_id, status, bill_amount, invoice_no FROM work_orders WHERE quote_no=? ORDER BY wo_id", (quote_no,)
    )]
    invs = [dict(r) for r in con.execute(
        "SELECT invoice_no, status, invoice_date FROM invoices WHERE quote_no=? ORDER BY invoice_date", (quote_no,)
    )]
    return {"q": dict(q), "lines": lines, "cos": cos, "tickets": tickets, "wos": wos, "invoices": invs, "tot": quote_totals(con, quote_no)}
def convert_quote(con, quote_no: str, on_rent: str | None = None) -> list[str]:
    """Accepted quote → Reserved tickets for rental lines that name a free unit. Does not invent invoice totals."""
    pack = quote_pack(con, quote_no)
    if not pack:
        raise ValueError("Unknown quote")
    q = pack["q"]
    if q["status"] not in ("Accepted", "Converted"):
        raise ValueError("Accept the quote before converting")
    if not q.get("site_id"):
        raise ValueError("Set a site on the quote before converting rental lines")
    made = []
    on = on_rent or date.today().isoformat()
    for ln in pack["lines"]:
        # "unit" is the current line type for rentable units; "rental" is the
        # legacy value in older quote rows (Jason 2026-10-07 line types).
        if ln["kind"] not in ("rental", "unit") or not ln.get("asset_id"):
            continue
        already = con.execute(
            "SELECT ticket_id FROM tickets WHERE quote_no=? AND asset_id=?",
            (quote_no, ln["asset_id"]),
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
def invoice_totals(con: sqlite3.Connection, invoice_no: str) -> dict:
    rows=con.execute("SELECT amount,tax_amount,source_type FROM invoice_lines WHERE invoice_no=? ORDER BY line_id",(invoice_no,)).fetchall()
    sub=sum((_money(r["amount"]) for r in rows),Decimal("0.00")); tax=sum((_money(r["tax_amount"]) for r in rows),Decimal("0.00")); total=_ms(sub,tax)
    cash=_money(con.execute("SELECT COALESCE(SUM(COALESCE(applied_amount,amount)),0) FROM collections WHERE invoice_no=? AND kind='payment'",(invoice_no,)).fetchone()[0])
    credit=_money(con.execute("SELECT COALESCE(SUM(COALESCE(applied_amount,amount)),0) FROM collections WHERE invoice_no=? AND kind='credit'",(invoice_no,)).fetchone()[0])
    paid=_ms(cash,credit); bal=_ms(total,-paid)
    return {"subtotal":float(sub),"tax":float(tax),"total":float(total),"cash":float(cash),"credit":float(credit),"paid":float(paid),"balance":float(bal),"count":sum(r["source_type"]=="ticket" for r in rows),"wo_count":sum(r["source_type"]=="work_order" for r in rows),"wo_sub":float(sum((_money(r["amount"]) for r in rows if r["source_type"]=="work_order"),Decimal("0.00"))),"extra_sub":float(sum((_money(r["amount"]) for r in rows if r["source_type"]=="extra"),Decimal("0.00"))),"line_count":len(rows)}
@ttl_cached()
def invoice_totals_batch(con: sqlite3.Connection) -> dict:
    """Full totals for every invoice in 2 queries (N+1 killer for Today/alerts).
    Returns {invoice_no: {subtotal,tax,total,cash,credit,paid,balance}}. Uses the
    same Decimal math as invoice_totals so figures match exactly."""
    line_totals = {}
    for ino, sub, tax in con.execute(
        "SELECT invoice_no, COALESCE(SUM(amount),0), COALESCE(SUM(tax_amount),0) "
        "FROM invoice_lines GROUP BY invoice_no"):
        sub_d, tax_d = _money(sub), _money(tax)
        line_totals[ino] = (sub_d, tax_d, _ms(sub_d, tax_d))
    paid_totals = {}
    for ino, cash, credit in con.execute(
        "SELECT invoice_no, "
        "COALESCE(SUM(CASE WHEN kind='payment' THEN COALESCE(applied_amount,amount) ELSE 0 END),0), "
        "COALESCE(SUM(CASE WHEN kind='credit' THEN COALESCE(applied_amount,amount) ELSE 0 END),0) "
        "FROM collections GROUP BY invoice_no"):
        cash_d, credit_d = _money(cash), _money(credit)
        paid_totals[ino] = (cash_d, credit_d, _ms(cash_d, credit_d))
    out = {}
    zero = Decimal("0.00")
    for ino, (sub, tax, total) in line_totals.items():
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
    return con.execute("SELECT 1 FROM collections WHERE invoice_no=? LIMIT 1",(invoice_no,)).fetchone() is not None
def set_invoice_po(con, invoice_no: str, po: str, clerk: str = "", po_expire: str|None=None, po_cost_code: str|None=None, po_notes: str|None=None) -> None:
    if invoice_locked(con, invoice_no):
        raise ValueError("Invoice is locked (sent, paid, or has payments)")
    require_clerk(clerk)
    con.execute("UPDATE invoices SET po=?, po_expire=?, po_cost_code=?, po_notes=? WHERE invoice_no=?", ((po or "").strip(), (po_expire or "").strip() or None, (po_cost_code or "").strip() or None, (po_notes or "").strip() or None, invoice_no))
    # Q6: keep the shared PO record current alongside the invoice snapshot.
    _cid = con.execute("SELECT customer_id FROM invoices WHERE invoice_no=?", (invoice_no,)).fetchone()
    upsert_po_record(con, _cid["customer_id"] if _cid else "", po, po_expire, po_cost_code, po_notes)
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

def upsert_po_record(con: sqlite3.Connection, customer_id: str, po_no: str,
                     expire: str | None = None, cost_code: str | None = None,
                     notes: str | None = None, asset_id: str | None = None) -> bool:
    """Keep the shared PO record current. Q6: the expiry lives on the PO
    itself, not scattered per-invoice — every invoice carrying this PO reads
    the same record. Non-blank values win; blanks never clear: a form left
    blank is "didn't specify", not "remove". Free-text throughout.
    Returns True when the PO record is newly created (an issued PO)."""
    po_no = (po_no or "").strip()
    if not po_no or not customer_id:
        return False
    _ensure_po_table(con)
    exp = (expire or "").strip() or None
    cc = (cost_code or "").strip() or None
    nt = (notes or "").strip() or None
    aid = (asset_id or "").strip() or None
    if not con.execute("SELECT 1 FROM purchase_orders WHERE customer_id=? AND po_no=?",
                       (customer_id, po_no)).fetchone():
        con.execute("INSERT INTO purchase_orders(po_no,customer_id,expire,cost_code,notes,asset_id) VALUES (?,?,?,?,?,?)",
                    (po_no, customer_id, exp, cc, nt, aid))
        return True
    else:
        con.execute("""UPDATE purchase_orders
                       SET expire=COALESCE(?,expire), cost_code=COALESCE(?,cost_code), notes=COALESCE(?,notes),
                           asset_id=COALESCE(?,asset_id)
                       WHERE customer_id=? AND po_no=?""", (exp, cc, nt, aid, customer_id, po_no))
        return False

def ack_po_record(con: sqlite3.Connection, customer_id: str, po_no: str, by: str = "") -> None:
    """Acknowledge an issued PO — the tap goes quiet."""
    _ensure_po_table(con)
    con.execute("UPDATE purchase_orders SET ack_at=datetime('now'), ack_by=? WHERE customer_id=? AND po_no=?",
                ((by or "").strip() or None, customer_id, (po_no or "").strip()))
    con.commit()

def _auto_reserve_for_po(con: sqlite3.Connection, customer_id: str, po_no: str,
                         asset_id: str, src_ticket) -> str | None:
    """Issued PO for an in-yard unit: auto-reserve until shipped. The
    reservation is soft — it never blocks an interim job that fits the gap;
    that's the customer's judgment call, not the app's. Returns the new
    Reserved ticket id, or None when the unit is already on a job (then the
    PO is a paperwork change only)."""
    busy = con.execute(
        """SELECT ticket_id FROM tickets WHERE asset_id=?
           AND status IN ('Reserved','Dispatched','On Rent','Standby')""",
        (asset_id,)).fetchone()
    if busy:
        return None
    return create_ticket(con, {
        "customer_id": customer_id,
        "site_id": src_ticket["site_id"],
        "asset_id": asset_id,
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
                           (customer_id, po_no)).fetchone()
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
           "days": None, "date_str": "", "expire": "", "cost_code": "", "notes": ""}
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
    else:
        exp = (inv["po_expire"] or "").strip()
        out["cost_code"] = (inv["po_cost_code"] or "").strip()
        out["notes"] = (inv["po_notes"] or "").strip()
    out["expire"] = exp
    if not exp:
        return out
    d = _parse(exp)
    out["date_str"] = d.strftime("%a %-m/%-d") if d else exp
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
INV_DOC_KINDS = {"po": "PO scan", "tax_exempt": "Tax-exempt certificate"}

def _ensure_invoice_docs(con: sqlite3.Connection) -> None:
    """Compatibility assertion; schema.sql owns current table DDL."""
    if not con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='invoice_docs'").fetchone():
        raise RuntimeError("Database schema is incomplete: invoice_docs is missing")

def _new_invoice_doc_name(ext: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    return f"doc-{stamp}-{secrets.token_hex(4)}{ext}"

def save_invoice_doc(con: sqlite3.Connection, invoice_no: str, kind: str,
                     filename: str, blob: bytes, clerk: str = "") -> int:
    """Attach paperwork to an invoice. One slot per kind — a new upload
    replaces the old scan (the old file is removed). Returns doc_id."""
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
               (invoice_no, kind, title, filename, stored, bytes, mime, clerk)
               VALUES (?,?,?,?,?,?,?,?)""",
            (invoice_no, kind, title, (filename or stored)[:120], stored,
             len(blob), mime, clerk or ""))
        doc_id = cur.lastrowid
    con.commit()
    return doc_id

def get_invoice_doc(con: sqlite3.Connection, invoice_no: str, kind: str):
    """The attached paperwork row for (invoice, kind), or None."""
    try:
        _ensure_invoice_docs(con)
        r = con.execute(
            """SELECT doc_id, invoice_no, kind, title, filename, stored, bytes,
                      mime, uploaded_at, clerk
               FROM invoice_docs WHERE invoice_no=? AND kind=?""",
            (invoice_no, kind)).fetchone()
    except sqlite3.Error:
        return None
    return dict(r) if r else None

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
    """The upper-right invoice box: PO#, Well#, Job Location — the three
    things required to get paid — plus 'Tax Exempt Cert' when the job is
    tax-exempt. Well/location derive from the invoice's tickets (and the
    tickets behind its work orders); the invoice carries no duplicate copy.
    PO expiry is record data, never a line — it is not in this box."""
    out = {"po": "", "wells": [], "locations": [], "tax_exempt": False,
           "po_doc": None, "tax_doc": None}
    try:
        inv = con.execute("SELECT po FROM invoices WHERE invoice_no=?",
                          (invoice_no,)).fetchone()
    except Exception:
        return out
    if not inv:
        return out
    out["po"] = (inv["po"] or "").strip()
    wells: list = []
    locs: list = []
    def _add(tid: str):
        t = con.execute("""SELECT t.well_or_pad, s.site_name FROM tickets t
                           JOIN sites s ON s.site_id=t.site_id
                           WHERE t.ticket_id=?""", (tid,)).fetchone()
        if not t:
            return
        w = (t["well_or_pad"] or "").strip()
        s = (t["site_name"] or "").strip()
        if w and w not in wells:
            wells.append(w)
        if s and s not in locs:
            locs.append(s)
    try:
        for (tid,) in con.execute("SELECT ticket_id FROM tickets WHERE invoice_no=?",
                                  (invoice_no,)):
            _add(tid)
        for (tid,) in con.execute("""SELECT ticket_id FROM work_orders
                                    WHERE invoice_no=? AND ticket_id IS NOT NULL
                                    AND TRIM(ticket_id) != ''""", (invoice_no,)):
            _add(tid)
    except Exception:
        pass
    out["wells"] = wells
    out["locations"] = locs
    out["po_doc"] = get_invoice_doc(con, invoice_no, "po")
    out["tax_doc"] = get_invoice_doc(con, invoice_no, "tax_exempt")
    try:
        exempt_line = con.execute(
            "SELECT 1 FROM invoice_lines WHERE invoice_no=? AND tax_exempt=1 LIMIT 1",
            (invoice_no,)).fetchone()
    except Exception:
        exempt_line = None
    out["tax_exempt"] = bool(out["tax_doc"]) or bool(exempt_line)
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
    out["date_str"] = d.strftime("%a %-m/%-d") if d else exp
    if d:
        out["days"] = (d - date.today()).days
        out["expired"] = out["days"] < 0
    return out
def add_invoice_line(con, invoice_no: str, data: dict) -> int:
    if not con.execute("SELECT 1 FROM invoices WHERE invoice_no=?",(invoice_no,)).fetchone(): raise ValueError("Unknown invoice")
    if invoice_locked(con,invoice_no): raise ValueError("Invoice is locked (sent, paid, or has payments)")
    if not invoice_has_lines(con,invoice_no): raise ValueError("Invoice must contain a billed ticket or work order before extra lines")
    desc=(data.get("description") or "").strip(); cat=(data.get("category") or "").strip(); uom=(data.get("uom") or "").strip()
    if not desc: raise ValueError("Description must match the PO wording")
    if cat not in lookups(con,"inv_cat"): raise ValueError("Pick a line category")
    if uom not in lookups(con,"inv_uom"): raise ValueError("Pick a unit")
    qty=_money(data.get("qty") or 0); rate=_money(data.get("rate") or 0)
    if qty<=0: raise ValueError("Qty must be greater than zero")
    amt=(qty*rate).quantize(CENT,rounding=ROUND_HALF_UP); inv=con.execute("SELECT customer_id FROM invoices WHERE invoice_no=?",(invoice_no,)).fetchone()
    src=con.execute("SELECT DISTINCT tax_rate,tax_exempt,tax_name,tax_loc FROM invoice_lines WHERE invoice_no=? AND source_type IN ('ticket','work_order')",(invoice_no,)).fetchall()
    if data.get("tax_rate") not in (None,""):
        tr=_money(data.get("tax_rate")); tax_name=(data.get("tax_name") or "Tax").strip(); tax_loc=(data.get("tax_loc") or "MANUAL").strip(); exempt=bool(data.get("tax_exempt"))
    elif len({(r["tax_loc"],float(r["tax_rate"]),int(r["tax_exempt"] or 0)) for r in src})==1 and src:
        tr=_money(src[0]["tax_rate"]); tax_name=src[0]["tax_name"] or "Tax"; tax_loc=src[0]["tax_loc"] or ""; exempt=bool(src[0]["tax_exempt"])
    else:
        cust=con.execute("SELECT tax_exempt FROM customers WHERE customer_id=?",(inv["customer_id"],)).fetchone(); exempt=bool(cust and cust["tax_exempt"]); tr=_money(0); tax_name=""; tax_loc=""
        if len(src)>1: raise ValueError("Invoice has multiple tax jurisdictions; specify tax_rate and tax_loc for the extra line")
    tax=Decimal("0.00") if exempt else (amt*tr).quantize(CENT,rounding=ROUND_HALF_UP)
    # B4: source_id is NOT NULL, so a manual ("extra") line can't insert with
    # source_id=None. Point it at its own line_id — traceable and unique.
    cur=con.execute("""INSERT INTO invoice_lines(invoice_no,po_line,category,description,qty,uom,rate,amount,clerk,tax_rate,tax_amount,tax_exempt,tax_name,tax_loc,source_type,source_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(invoice_no,(data.get("po_line") or "").strip(),cat,desc,float(qty),uom,float(rate),float(amt),require_clerk(data.get("clerk")),float(0 if exempt else tr),float(tax),int(exempt),tax_name,tax_loc,"extra","pending")); con.commit()
    lid=int(cur.lastrowid)
    con.execute("UPDATE invoice_lines SET source_id=? WHERE line_id=?",(f"extra-{lid}",lid)); con.commit(); return lid
def drop_invoice_line(con, line_id: int, clerk: str = "") -> None:
    require_clerk(clerk)
    row = con.execute("SELECT invoice_no FROM invoice_lines WHERE line_id=?", (line_id,)).fetchone()
    if not row:
        raise ValueError("Unknown line")
    if invoice_locked(con, row["invoice_no"]):
        raise ValueError("Invoice is locked (sent, paid, or has payments)")
    src=con.execute("SELECT source_type FROM invoice_lines WHERE line_id=?",(line_id,)).fetchone()
    if src and src["source_type"] not in (None,"","extra"):
        raise ValueError("Billed source lines are immutable; use a credit memo for an adjustment")
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
        raise ValueError("Name the preset (e.g. Monthly AR for bookkeeper)")
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
    terms = data.get("terms") or "Net 30"
    if terms not in lookups(con, "terms"):
        raise ValueError("Pick terms from the list")
    cid = customer_id or next_customer_id(con)
    # Keep the legacy city_st column in sync as "City, ST" for letterhead/print reads.
    city_st = ", ".join(p for p in ((data.get("bill_city") or "").strip(),
                                    (data.get("bill_state") or "").strip()) if p)
    row = (
        name, data.get("short_name") or "", data.get("bill_to") or "",
        data.get("phone") or "", data.get("email") or "",
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
    if (data.get("bill_to") or "").strip():
        con.execute("UPDATE customer_contacts SET is_primary=0 WHERE customer_id=?", (cid,))
        con.execute("DELETE FROM customer_contacts WHERE customer_id=? AND is_primary=1", (cid,))
        con.execute("INSERT INTO customer_contacts(customer_id,name,role,phone,email,is_primary) VALUES (?,?,?,?,?,1)",
                     (cid, (data.get("bill_to") or "").strip(), "Accounting / Billing", data.get("phone") or "", data.get("email") or ""))
    if not con.execute("SELECT 1 FROM customer_locations WHERE customer_id=?", (cid,)).fetchone() and any((data.get(k) or "").strip() for k in ("bill_street","bill_city","bill_state","bill_zip")):
        con.execute("INSERT INTO customer_locations(customer_id,location_name,street,street2,city,state,zip,is_primary) VALUES (?,?,?,?,?,?,?,1)",
                     (cid, "Primary / Billing", data.get("bill_street") or "", data.get("bill_street2") or "", data.get("bill_city") or "", data.get("bill_state") or "", data.get("bill_zip") or ""))
    con.commit()
    return cid
def report_invoicing(con: sqlite3.Connection) -> dict:
    today = date.today()
    ready_rows = []
    ready_amt = 0.0
    for t in con.execute(
        """SELECT t.ticket_id, t.customer_id, c.account_name, a.unit_no, t.status
           FROM tickets t
           JOIN customers c ON c.customer_id = t.customer_id
           JOIN assets a ON a.asset_id = t.asset_id
           WHERE t.status IN ('Ready to Bill','Off Rent')
             AND (t.invoice_no IS NULL OR t.invoice_no='')
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
           FROM invoices i JOIN customers c ON c.customer_id = i.customer_id
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
        """SELECT i.invoice_no, i.invoice_date, i.customer_id, c.account_name
           FROM invoices i JOIN customers c ON c.customer_id = i.customer_id"""
    ):
        d = _parse(inv["invoice_date"])
        if not d or d < start or d > end:
            continue
        tot = invoice_totals(con, inv["invoice_no"])
        billed += tot["total"]
        bc = bucket_cust(inv["customer_id"], inv["account_name"])
        bc["billed"] += tot["total"]
        bc["invoices"] += 1
        key = d.strftime("%Y-%m")
        by_month.setdefault(key, {"month": key, "billed": 0.0, "cash": 0.0})
        by_month[key]["billed"] += tot["total"]
        for t in con.execute(
            """SELECT t.ticket_id, t.asset_id, a.unit_no, a.description
               FROM tickets t JOIN assets a ON a.asset_id = t.asset_id
               WHERE t.invoice_no=?""",
            (inv["invoice_no"],),
        ):
            line = con.execute("SELECT COALESCE(SUM(amount + tax_amount),0) FROM invoice_lines WHERE invoice_no=? AND source_type='ticket' AND source_id=?", (inv["invoice_no"], t["ticket_id"])).fetchone()
            bu = bucket_unit(t["asset_id"], t["unit_no"], t["description"] or "")
            bu["billed"] += float(line[0] or 0)
            bu["tickets"] += 1

    for p in con.execute(
        """SELECT c.pay_date, c.amount, i.customer_id, cu.account_name
           FROM collections c
           JOIN invoices i ON i.invoice_no = c.invoice_no
           JOIN customers cu ON cu.customer_id = i.customer_id
           WHERE c.kind='payment'"""
    ):
        d = _parse(p["pay_date"])
        if not d or d < start or d > end:
            continue
        cash += float(p["amount"] or 0)
        bc = bucket_cust(p["customer_id"], p["account_name"])
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
           JOIN assets a ON a.asset_id = t.asset_id
           JOIN customers c ON c.customer_id = t.customer_id
           ORDER BY t.on_rent"""
    ):
        d = _parse(t["on_rent"])
        if d and start <= d <= end:
            new_tix.append(dict(t))
    offed = []
    for t in con.execute(
        """SELECT t.ticket_id, t.status, t.off_rent, a.unit_no, c.account_name
           FROM tickets t
           JOIN assets a ON a.asset_id = t.asset_id
           JOIN customers c ON c.customer_id = t.customer_id
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
