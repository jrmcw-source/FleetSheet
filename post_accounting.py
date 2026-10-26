"""FleetSheet POST actions — accounting flow: invoices, payments, credit, quotes, petty cash, customers, export."""
from datetime import date

import engine
from urllib.parse import quote_plus
# Part D: the print-toggle helper lives in engine_accounting; the engine
# facade does not re-export it yet, so import it from its home module.
from engine_accounting import set_invoice_doc_print

from views_core import chain_advance


def _desk(handler, con):
    """Desk-session identity for silent attribution stamps (Batch 3
    #13): the handler's desk identity, never a posted form field."""
    try:
        return (handler.desk(con) or "").strip()[:40]
    except Exception:
        return ""


def _post_invoice_create(handler, con, data, u):
    # Universal button row (Jason 2026-10-21): the form's only commit
    # is its row Save (action=save) — the Create Invoice top commit was
    # removed from the form entirely later that day (Jason's grandma
    # walk: the door is New Invoice, the act is Save, the paper is
    # Print; the button was never wanted in any position). action=create
    # stays accepted here for legacy posts, landing on the invoice page
    # as it always did. Save writes the invoice and lands back on the
    # SAME editor (?edit=<no>) so work in progress is never lost; a
    # later Save updates that invoice in place instead of duplicating
    # it. The update path is licensed ONLY by the editing=1 hidden
    # field the edit form carries — a new-invoice form always creates,
    # so its previewed number can never collide with (or overwrite)
    # an invoice another tab saved first. Posts with no action field
    # (old bookmarks, other flows) keep the original behavior:
    # create, then land on the invoice page.
    action = (data.get("action") or "create").strip().lower()
    ino = None
    replace = False
    stored_terms = None
    if data.get("editing") == "1" and (data.get("invoice_no") or "").strip():
        _want = data["invoice_no"].strip()
        _ex = con.execute(
            "SELECT customer_id, terms FROM invoices WHERE invoice_no=?",
            (_want,)).fetchone()
        if _ex:
            if engine.invoice_locked(con, _want):
                raise ValueError(
                    "Invoice is locked (sent, paid, or has payments)")
            if (data.get("customer_id") or "") != engine.cust_code(con, _ex["customer_id"]):
                raise ValueError(
                    "The customer can't change on a saved invoice — "
                    "void it and write a new one")
            ino = _want
            replace = True
            stored_terms = _ex["terms"]
    if ino is None:
        tids = [k[3:] for k, v in data.items() if k.startswith("t__") and v == "1"]
        wids = [k[3:] for k, v in data.items() if k.startswith("w__") and v == "1"]
        # Check-in condition gate (shop-flow ruling, Jason 2026-10-21):
        # picked tickets with no check-in condition on record. The
        # condition switch OFF skips the gate; ON, the form's "Proceed
        # anyway" checkbox is the escape — and the bypass is audited per
        # ticket below. Without either, create_invoice refuses as before.
        _cond_on = engine.module_on(con, "condition")
        _blocked = []
        if tids:
            _ph = ",".join("?" for _ in tids)
            _blocked = [r[0] for r in con.execute(
                f"SELECT ticket_id FROM tickets WHERE ticket_id IN ({_ph}) "
                "AND (in_condition IS NULL OR in_condition='')", tids)]
        _proceed = data.get("proceed") == "1"
        _skip = (not _cond_on) or _proceed
        ino = engine.create_invoice(
            con, data["customer_id"], tids, data.get("invoice_date") or None, wids,
            data.get("quote_no") or None, data.get("po") or None,
            po_expire=data.get("po_expire") or None,
            po_cost_code=data.get("po_cost_code") or None,
            po_notes=data.get("po_notes") or None,
            terms=data.get("terms") or None,
            skip_condition=_skip,
            invoice_no=data.get("invoice_no") or None,
        )
        if _blocked and _skip and _cond_on and _proceed:
            for _tid in _blocked:
                engine.add_done_manual(
                    con,
                    f"Billed {_tid} on {ino} without a check-in condition (proceeded anyway)",
                    f"/ticket/{_tid}", _desk(handler, con))
    # Save ref_ticket + tax. (The quick_* columns stay for legacy rows;
    # nothing reads them — line rows go to invoice_lines now.)
    icols = [r[1] for r in con.execute("PRAGMA table_info(invoices)")]
    for col, ddl in [("ref_ticket", "TEXT"), ("quick_item", "TEXT"),
                     ("quick_desc", "TEXT"), ("quick_qty", "REAL DEFAULT 1"),
                     ("quick_rate", "REAL DEFAULT 0"),
                     ("tax_rate", "REAL DEFAULT 0"),
                     ("adjustment", "REAL DEFAULT 0"),
                     ("adj_label", "TEXT DEFAULT ''"),
                     ("adj_taxable", "INTEGER DEFAULT 0"),
                     ("tax_exempt_op", "INTEGER DEFAULT 0"),
                     ("shipped_by", "TEXT DEFAULT ''"),
                     ("contact_name", "TEXT DEFAULT ''"),
                     ("bar_text", "TEXT DEFAULT ''")]:
        if col not in icols:
            con.execute(f"ALTER TABLE invoices ADD COLUMN {col} {ddl}")
    # Server-side totals from the posted lines + tax_rate + adjustment
    # (never trust client math). Every posted line row — row 0 included —
    # becomes a real invoice line with its own Type/Unit. Row 0 used to
    # live only in the quick_* columns, which nothing reads, so a typed
    # row-0 amount silently dropped out of the invoice total.
    def _f(v):
        try:
            return float(v or 0)
        except (TypeError, ValueError):
            return 0.0
    q0, r0 = _f(data.get("qty")), _f(data.get("rate"))
    sub = round(q0 * r0, 2)
    rows = []
    # A row with no Item text, no Description, and a $0 rate is an
    # untouched form row (the form defaults Qty to 1) — skip it, never
    # a $0 junk line. A $0 line with text is real (warranty/goodwill).
    tax_ui = data.get("tax_ui") == "1"
    it0 = (data.get("item") or "").strip()
    ds0 = (data.get("item_desc") or "").strip()
    if it0 or ds0 or r0:
        rows.append((it0, ds0, q0, r0,
                     engine.clean_line_type(con, data.get("type")),
                     engine.clean_line_uom(con, data.get("uom")),
                     (data.get("taxable") == "1") if tax_ui else True))
    for i in range(1, 61):
        qi, ri = _f(data.get(f"qty{i}")), _f(data.get(f"rate{i}"))
        it = (data.get(f"item{i}") or "").strip()
        ds = (data.get(f"item_desc{i}") or "").strip()
        if not it and not ds and not ri:
            continue
        sub = round(sub + qi * ri, 2)
        rows.append((it, ds, qi, ri,
                     engine.clean_line_type(con, data.get(f"type{i}")),
                     engine.clean_line_uom(con, data.get(f"uom{i}")),
                     (data.get(f"taxable{i}") == "1") if tax_ui else True))
    tr = _f(data.get("tax_rate")) / 100.0
    adj = _f(data.get("adjustment"))
    # Invoice-round tax model (Jason 2026-10-20): the operator's
    # tax-exempt click zeroes this invoice's tax on their say-so, and
    # the write-in carries its own taxable toggle. Per-line toggles
    # ride in the rows tuples (7th element) when the editor's tax_ui
    # sentinel posted; legacy posts keep every line taxable, as before.
    op_exempt = data.get("tax_exempt_op") == "1"
    adj_taxable = 1 if data.get("adj_taxable") == "1" else 0
    try:
        _cx = con.execute("SELECT tax_exempt FROM customers WHERE customer_id=?",
                          (data["customer_id"],)).fetchone()
        exempt = bool(_cx and _cx[0])
    except Exception:
        exempt = False
    exempt = exempt or op_exempt
    tax = 0.0 if exempt else round(sub * tr, 2)
    if replace:
        # Update in place (Save pressed on a saved invoice): the form
        # owns the free-typed lines, so they are replaced wholesale
        # with the posted rows — recomputed by the same block below,
        # same math, same totals. Ticket / work-order lines are not
        # the form's and stay untouched. The header fields the create
        # path sets at insert (date, terms, PO) are updated here, and
        # the shared PO record is kept current as create_invoice does.
        con.execute(
            "DELETE FROM invoice_lines WHERE invoice_id=? AND source_type='quick'",
            (engine.doc_key(con, "invoice", ino),))
        con.execute(
            "UPDATE invoices SET invoice_date=?, terms=?, po=? WHERE invoice_no=?",
            (data.get("invoice_date") or None,
             (data.get("terms") or "").strip() or stored_terms,
             (data.get("po") or "").strip() or None, ino))
        engine.upsert_po_record(
            con, data["customer_id"], data.get("po") or None,
            data.get("po_expire") or None, data.get("po_cost_code") or None,
            data.get("po_notes") or None, asset_id=None)
    con.execute(
        "UPDATE invoices SET ref_ticket=?, tax_rate=?, adjustment=?, adj_label=?, adj_taxable=?, tax_exempt_op=?, shipped_by=?, contact_name=?, bar_text=? WHERE invoice_no=?",
        ((data.get("ref_ticket") or "").strip(), tr, adj,
         (data.get("adj_label") or "").strip()[:120], adj_taxable,
         1 if op_exempt else 0,
         (data.get("shipped_by") or "").strip()[:120],
         (data.get("contact_name") or "").strip()[:120],
         (data.get("bar_text") or "").strip()[:500], ino))
    for it, ds, qi, ri, cat, uom, txable in rows:
        amt = round(qi * ri, 2)
        line_exempt = exempt or not txable
        ltax = 0.0 if line_exempt else round(amt * tr, 2)
        con.execute(
            """INSERT INTO invoice_lines(invoice_id,po_line,category,item,description,qty,uom,rate,amount,
               clerk,tax_rate,tax_amount,tax_exempt,tax_name,tax_loc,source_type,source_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (engine.doc_key(con, "invoice", ino), "", cat, it, ds or "Item", qi, uom, ri, amt, "",
             0.0 if line_exempt else tr, ltax, int(line_exempt),
             "" if line_exempt else "Tax", "", "quick", ""))
    con.commit()
    if not replace:
        # A create is an explicit operator action — Done Today gets
        # it (look-see batch 2, 2026-10-21). The replace path (Save
        # on an already-saved invoice) is an edit and does not log.
        engine.add_done_manual(
            con, f"Created invoice {ino}", f"/invoice/{ino}",
            _desk(handler, con))
    up = (handler._files or {}).get("job_attach")
    if up and up[2]:
        engine.save_job_attachment(con, "invoice", ino, up[0], up[2], _desk(handler, con))
    if action == "save":
        # Stay on the form: the same editor, now editing this invoice.
        handler._redirect(f"/invoice/new?edit={ino}&msg=Invoice+{ino}+saved")
    else:
        handler._redirect(f"/invoice/{ino}?msg=Invoice+{ino}+created")


def _post_invoice_po(handler, con, data, u):
    ino = u.path.split("/")[2]
    try:
        po_total = float(data.get("po_total") or 0) or None
    except (TypeError, ValueError):
        po_total = None
    engine.set_invoice_po(
        con, ino, data.get("po") or "", _desk(handler, con),
        po_expire=data.get("po_expire") or None,
        po_cost_code=data.get("po_cost_code") or None,
        po_notes=data.get("po_notes") or None,
        po_total=po_total,
        po_status=data.get("po_status") or None,
    )
    handler._redirect(f"/invoice/{ino}?msg=PO+saved")


def _post_invoice_doc(handler, con, data, u):
    ino = u.path.split("/")[2]
    up = (handler._files or {}).get("doc_file")
    try:
        if not up or not up[2]:
            raise ValueError("Choose a file to attach")
        engine.save_invoice_doc(con, ino, data.get("kind") or "",
                                up[0] or "", up[2], _desk(handler, con),
                                title=data.get("doc_title"))
        handler._redirect(f"/invoice/{ino}?msg=" + quote_plus("Paperwork attached"))
    except ValueError as e:
        handler._redirect(f"/invoice/{ino}?err=" + quote_plus(str(e)))


def _post_invoice_docdel(handler, con, data, u):
    ino = u.path.split("/")[2]
    if engine.delete_invoice_doc(con, ino, data.get("kind") or ""):
        handler._redirect(f"/invoice/{ino}?msg=" + quote_plus("Paperwork removed"))
    else:
        handler._redirect(f"/invoice/{ino}?err=" + quote_plus("Nothing attached"))


def _post_invoice_docprint(handler, con, data, u):
    # Print-with-invoice toggle (Part D): the slot's checkbox posts
    # print_with=1 when ticked and omits the field when unticked —
    # absence is the OFF state, same convention as the form's other
    # checkboxes.
    ino = u.path.split("/")[2]
    if set_invoice_doc_print(con, ino, data.get("kind") or "",
                             data.get("print_with") == "1"):
        handler._redirect(f"/invoice/{ino}?msg=" + quote_plus("Print setting saved"))
    else:
        handler._redirect(f"/invoice/{ino}?err=" + quote_plus("Nothing attached"))


def _post_invoice_line(handler, con, data, u):
    ino = u.path.split("/")[2]
    engine.add_invoice_line(con, ino, {
        "po_line": data.get("po_line"),
        "category": data.get("category") or data.get("category_text"),
        "item": data.get("item"),
        "description": data.get("description"),
        "qty": data.get("qty"),
        "uom": data.get("uom") or data.get("uom_text"),
        "rate": data.get("rate"),
        "clerk": _desk(handler, con),
        "tax_ui": data.get("tax_ui"),
        "taxable": data.get("taxable"),
    })
    handler._redirect(f"/invoice/{ino}?msg=Line+added")


def _post_invoice_linedel(handler, con, data, u):
    engine.drop_invoice_line(con, int(data.get("line_id") or 0), _desk(handler, con))
    ino = data.get("invoice_no") or ""
    handler._redirect(f"/invoice/{ino}?msg=Line+removed")


def _post_invoice_linenote(handler, con, data, u):
    ino = u.path.split("/")[2]
    engine.set_invoice_line_note(
        con, ino, data.get("line_id") or 0, data.get("note") or "")
    handler._redirect(f"/invoice/{ino}?msg=Line+note+saved")


def _line_allocs_from(data, prefix):
    """<prefix>__<invoice_no>__<line_id> amount fields ->
    {invoice_no: [(line_id, amount)]}. The line id rides last, so an
    invoice number containing '__' still parses."""
    out = {}
    for k, v in data.items():
        if not k.startswith(prefix + "__") or not v:
            continue
        ino, sep, lid = k[len(prefix) + 2:].rpartition("__")
        if not sep or not ino:
            continue
        try:
            amt = float(v)
            lid_i = int(lid)
        except (TypeError, ValueError):
            continue
        if amt > 0:
            out.setdefault(ino, []).append((lid_i, amt))
    return out


def _post_pay(handler, con, data, u):
    pcols = [r[1] for r in con.execute("PRAGMA table_info(collections)")]
    for col, ddl in [("pay_ref", "TEXT"), ("user_name", "TEXT")]:
        if col not in pcols:
            con.execute(f"ALTER TABLE collections ADD COLUMN {col} {ddl}")
    # Multi-invoice payment (Jason 2026-10-15): p__<invoice> splits —
    # one payment across several invoices. All splits must belong to
    # one customer (the picked invoice's customer); the form's JS
    # filters the table to that customer, the backend enforces it.
    splits = []
    for k, v in data.items():
        if k.startswith("p__") and v:
            try:
                amt = float(v)
            except (TypeError, ValueError):
                continue
            if amt > 0:
                splits.append((k[3:], amt))
    # Change Order splits (build 'v', Jason 2026-10-25 — the
    # amended-PO exception): pco__<co_no> amounts ride the SAME
    # payment event (one batch id), recorded as per-document
    # allocations against the Change Order. The documents never
    # merge; the money event is one.
    co_splits = []
    for k, v in data.items():
        if k.startswith("pco__") and v:
            try:
                amt = float(v)
            except (TypeError, ValueError):
                continue
            if amt > 0:
                co_splits.append((k[5:], amt))
    # No splits and no invoice: the form has no invoice to attach to.
    # (The invoice picker is no longer HTML-required — a customer +
    # Apply amounts is a complete payment — so this is enforced here.)
    if not splits and not co_splits and not (data.get("invoice_no") or "").strip():
        raise ValueError("Pick an invoice or enter an Apply amount")
    # Optional line breakdown (Jason 2026-10-23): pl__<invoice>__<line>
    # amounts distribute that invoice's Apply amount across its lines.
    # A breakdown for an invoice with no Apply amount is refused, not
    # silently dropped.
    allocs = _line_allocs_from(data, "pl")
    if splits or co_splits:
        split_inos = {ino for ino, _a in splits}
        for ino in allocs:
            if ino not in split_inos:
                raise ValueError(
                    f"Line amounts entered for {ino} with no Apply amount")
        custs = set()
        for ino, _amt in splits:
            r = con.execute(
                "SELECT customer_id FROM invoices WHERE invoice_no=?",
                (ino,)).fetchone()
            if not r:
                raise ValueError(f"Unknown invoice {ino}")
            custs.add(engine.cust_code(con, r["customer_id"]))
        for cno, _amt in co_splits:
            r = con.execute(
                "SELECT customer_id FROM change_orders WHERE co_no=?",
                (cno,)).fetchone()
            if not r:
                raise ValueError(f"Unknown change order {cno}")
            custs.add(engine.cust_code(con, r["customer_id"]))
        if len(custs) > 1:
            raise ValueError(
                "One payment covers one customer — the documents span "
                "several customers")
        # The form's Customer picker is a filter + reference: when it
        # posts a customer, the splits must belong to that customer —
        # a mismatch is refused, never silently re-attributed.
        posted_cust = (data.get("customer_id") or "").strip()
        if posted_cust and posted_cust not in custs:
            raise ValueError(
                "Payment customer does not match the invoices")
        # One batch: a shared batch id + one commit for all splits. A
        # mid-batch failure raises before the commit, and con.close()
        # without commit discards the open transaction — no partial post.
        batch_id = engine.next_batch_id(con)
        pay_ids, applied_rows, cms = [], [], []
        for ino, amt in splits:
            res = engine.record_payment(
                con, ino, amt,
                data.get("pay_date") or date.today().isoformat(),
                data.get("method") or "", data.get("ref") or "",
                _desk(handler, con),
                batch_id=batch_id, commit=False,
                line_allocs=allocs.get(ino),
            )
            if res["pay_id"]:
                pay_ids.append(res["pay_id"])
            applied_rows.append((ino, res["applied"]))
            if res.get("credit_memo"):
                cms.append((res["credit_memo"], res["credit_amount"]))
        # Change Order splits under the same batch (build 'v'): the
        # CO portion posts to the doc ledger with this payment's
        # batch id — one payment event, per-document allocations.
        co_applied_rows = []
        for cno, amt in co_splits:
            res = engine.record_doc_payment(
                con, "change", cno, amt,
                data.get("pay_date") or date.today().isoformat(),
                data.get("method") or "", data.get("ref") or "",
                _desk(handler, con),
                batch_id=batch_id, commit=False,
            )
            co_applied_rows.append((cno, res["applied"]))
            if res.get("credit_memo"):
                cms.append((res["credit_memo"], res["credit_amount"]))
        # Shared payment fields land on every posted split row (same
        # payment). A split against a settled invoice posts no row —
        # its money went to an open credit memo instead (Jason
        # 2026-10-23); it still counts in the batch totals here.
        for pid in pay_ids:
            con.execute(
                "UPDATE collections SET pay_ref=?, user_name=?, notes=? "
                "WHERE pay_id=?",
                ((data.get("ref") or "").strip(),
                 _desk(handler, con),
                 (data.get("notes") or "").strip(),
                 pid))
        con.commit()
        up = (handler._files or {}).get("pay_upload")
        if up and up[2] and pay_ids:
            engine.save_job_attachment(
                con, "pay", str(pay_ids[0]), up[0], up[2],
                _desk(handler, con))
        total = (sum(a for _ino, a in applied_rows)
                 + sum(a for _cno, a in co_applied_rows))
        _parts = [f"{ino} ${a:,.2f}" for ino, a in applied_rows]
        _parts += [f"Change Order {cno} ${a:,.2f}"
                   for cno, a in co_applied_rows]
        msg = (f"Payment {batch_id} recorded: ${total:,.2f} across "
               f"{len(applied_rows) + len(co_applied_rows)} document(s): "
               + ", ".join(_parts) + ".")
        for cm_no, cm_amt in cms:
            msg += (f" ${cm_amt:,.2f} overpayment kept as open credit "
                    f"{cm_no}.")
        handler._redirect("/money?tab=pay&msg=" + quote_plus(msg))
        return
    # Legacy single-invoice path (no p__ splits posted) — still one
    # batch (of one), so the audit groups it like any other payment.
    # Same customer check as the splits path. One transaction like the
    # splits path: the payment, its line breakdown, any overpayment
    # credit memo, and the shared fields post at a single commit — a
    # failure anywhere before it leaves nothing posted.
    _posted_cust = (data.get("customer_id") or "").strip()
    if _posted_cust:
        _row = con.execute(
            "SELECT customer_id FROM invoices WHERE invoice_no=?",
            (data.get("invoice_no") or "",)).fetchone()
        if _row and engine.cust_code(con, _row["customer_id"]) != _posted_cust:
            raise ValueError(
                "Payment customer does not match the invoice")
    _single_ino = (data.get("invoice_no") or "").strip()
    for ino in allocs:
        if ino != _single_ino:
            raise ValueError(
                f"Line amounts entered for {ino} with no Apply amount")
    res = engine.record_payment(
        con, _single_ino, float(data.get("amount") or 0),
        data.get("pay_date") or date.today().isoformat(),
        data.get("method") or "", data.get("ref") or "", _desk(handler, con),
        batch_id=engine.next_batch_id(con), commit=False,
        line_allocs=allocs.get(_single_ino),
    )
    # Save extra fields (a settled-invoice payment posts no row —
    # its money is the open credit memo — but the commit still has
    # to happen, so it sits outside the row check).
    if res.get("pay_id"):
        con.execute(
            "UPDATE collections SET pay_ref=?, user_name=?, notes=? WHERE pay_id=?",
            ((data.get("ref") or "").strip(),
             _desk(handler, con),
             (data.get("notes") or "").strip(),
             res["pay_id"]))
    con.commit()
    if res.get("pay_id"):
        up = (handler._files or {}).get("pay_upload")
        if up and up[2]:
            engine.save_job_attachment(con, "pay", str(res["pay_id"]), up[0], up[2], _desk(handler, con))
    ino2 = data.get("invoice_no") or ""
    if res["credit_memo"]:
        msg = (f"Payment recorded: ${res['applied']:,.2f} applied to {ino2} (paid in full); "
               f"${res['credit_amount']:,.2f} overpayment kept as open credit {res['credit_memo']}.")
    else:
        msg = "Payment recorded"
    handler._redirect("/money?tab=pay&msg=" + quote_plus(msg))


def _credit_allocs_checked(data, applies):
    """ca__<invoice>__<line> amounts -> {invoice: [(line_id, amount)]}.
    A breakdown for an invoice with no Apply amount is refused, not
    silently dropped (same rule as payments)."""
    allocs = _line_allocs_from(data, "ca")
    applied = set()
    for ino, raw in applies:
        try:
            if float(raw) > 0:
                applied.add(ino)
        except (TypeError, ValueError):
            continue
    for ino in allocs:
        if ino not in applied:
            raise ValueError(
                f"Line amounts entered for {ino} with no Apply amount")
    return allocs


def _doc_applies_from(data, amt_prefix="cd", line_prefix="cdl"):
    """Credit-against-documents fields (Jason 2026-10-23,
    universality): cd__<kind>__<ref> apply amounts plus
    cdl__<kind>__<ref>__<line> breakdowns -> the engine's doc_applies
    list [(kind, ref, amount, line_allocs|None)]. A breakdown for a
    document with no Apply amount is refused, as everywhere else."""
    applies = []
    for k, v in data.items():
        if k.startswith(amt_prefix + "__") and v:
            parts = k.split("__")
            if len(parts) == 3 and float(v or 0) > 0:
                applies.append((parts[1], parts[2], v, None))
    line_map: dict = {}
    for k, v in data.items():
        if k.startswith(line_prefix + "__") and v:
            parts = k.split("__")
            if len(parts) != 4:
                continue
            try:
                amt = float(v)
                lid = int(parts[3])
            except (TypeError, ValueError):
                continue
            if amt > 0:
                line_map.setdefault((parts[1], parts[2]), []).append(
                    (lid, amt))
    out = []
    applied_keys = {(k2, r2) for k2, r2, _a, _l in applies}
    for key in line_map:
        if key not in applied_keys:
            raise ValueError(
                f"Line amounts entered for {key[1]} with no Apply amount")
    for kind, ref, amt, _none in applies:
        out.append((kind, ref, amt, line_map.get((kind, ref))))
    return out


# Build 'u' (Jason 2026-10-25): money worked from a summary's
# Payment popup returns to the summary (record links land on
# summaries); ticket and sale record routes ARE their summaries.
_DOC_RETURN = {"wo": "/summary/wo/{ref}", "ticket": "/ticket/{ref}",
               "sale": "/sale/{ref}", "quote": "/summary/quote/{ref}",
               "change": "/summary/change/{ref}"}


def _post_docmoney(handler, con, data, u):
    """Money in against a work order, rental ticket, sale, or quote
    (Jason 2026-10-23, universality): any tender, blanket or line by
    line, overpayment to open credit — record_doc_payment owns the
    rules; this is the form door on the document's own page."""
    kind = (data.get("doc_kind") or "").strip()
    ref = (data.get("doc_ref") or "").strip()
    if kind not in _DOC_RETURN or not ref:
        raise ValueError("Pick a work order, rental ticket, sale, quote, or change order")
    res = engine.record_doc_payment(
        con, kind, ref, float(data.get("amount") or 0),
        data.get("pay_date") or date.today().isoformat(),
        data.get("method") or "", data.get("ref") or "",
        _desk(handler, con),
        line_allocs=_line_allocs_from(data, "dl").get(ref),
    )
    msg = (f"Payment recorded: ${res['applied']:,.2f} applied to "
           f"{engine.DOC_LABELS[kind]} {ref}")
    if res.get("credit_memo"):
        msg += (f"; ${res['credit_amount']:,.2f} overpayment kept as "
                f"open credit {res['credit_memo']}")
    handler._redirect(_DOC_RETURN[kind].format(ref=ref)
                      + "?msg=" + quote_plus(msg))


def _post_doccredit(handler, con, data, u):
    """Apply open credit against a work order, rental ticket, sale,
    or quote from the document's own page (the /credit page covers
    it too)."""
    kind = (data.get("doc_kind") or "").strip()
    ref = (data.get("doc_ref") or "").strip()
    if kind not in _DOC_RETURN or not ref:
        raise ValueError("Pick a work order, rental ticket, sale, quote, or change order")
    engine.apply_doc_credit(
        con, data.get("cm_no") or "", kind, ref,
        float(data.get("amount") or 0),
        data.get("pay_date") or None, _desk(handler, con),
        line_allocs=_line_allocs_from(data, "dl").get(ref),
    )
    handler._redirect(_DOC_RETURN[kind].format(ref=ref)
                      + "?msg=Credit+applied")


def _post_doc_linenote(handler, con, data, u):
    """Dispute note on a work order / rental ticket / sale / quote /
    change order line — the same annotation as an invoice line's, on
    the document's own page."""
    seg = u.path.split("/")
    kind = {"wo": "wo", "ticket": "ticket", "sale": "sale",
            "quote": "quote", "change": "change"}[seg[1]]
    ref = seg[2]
    engine.set_doc_line_note(
        con, kind, ref, data.get("line_id") or "",
        data.get("note") or "")
    handler._redirect(_DOC_RETURN[kind].format(ref=ref)
                      + "?msg=Line+note+saved")


def _post_credit(handler, con, data, u):
    applies = []
    for k, v in data.items():
        if k.startswith("a__") and v:
            applies.append((k[3:], v))
    credit_allocs = _credit_allocs_checked(data, applies)
    # Multi-line grid (credit memo multi-line build): parse exactly
    # like _post_invoice_create parses its rows — row 0 uses the
    # unprefixed field names, rows 1..60 use suffixed names. The
    # engine owns the lines now (credit_memo_lines); when rows are
    # posted it derives the face from SUM(qty*rate), and when no rows
    # are posted it keeps the legacy face_amount behaviour.
    def _f(v):
        try:
            return float(v or 0)
        except (TypeError, ValueError):
            return 0.0

    def _i(v):
        try:
            return int(v or 0)
        except (TypeError, ValueError):
            return 0
    tax_ui = data.get("tax_ui") == "1"
    rows = []
    for i in range(0, 61):
        sfx = "" if i == 0 else str(i)
        it = (data.get(f"item{sfx}") or "").strip()
        ds = (data.get(f"item_desc{sfx}") or "").strip()
        ri = _f(data.get(f"rate{sfx}"))
        # Skip an untouched row (no item text, no description text,
        # rate == 0) — the form defaults Qty to 1, so qty alone
        # never makes a row real.
        if not it and not ds and not ri:
            continue
        rows.append({
            "category": data.get(f"type{sfx}"),
            "item": it,
            "description": ds,
            "qty": _f(data.get(f"qty{sfx}")),
            "rate": ri,
            "uom": data.get(f"uom{sfx}"),
            "tax_exempt": (not (data.get(f"taxable{sfx}") == "1")) if tax_ui else False,
            "source_invoice_no": data.get(f"srcinv{sfx}") or "",
            "source_line_id": _i(data.get(f"srcline{sfx}")),
        })
    cno = engine.issue_credit_memo(
        con,
        data.get("customer_id") or "",
        data.get("face_amount") or 0,
        data.get("reason") or "",
        applies,
        data.get("cm_date") or None,
        data.get("notes") or "",
        _desk(handler, con),
        lines=rows,
        cm_no=data.get("cm_no") or None,
        line_allocs_map=credit_allocs,
        doc_applies=_doc_applies_from(data),
    )
    up = (handler._files or {}).get("job_attach")
    if up and up[2]:
        engine.save_job_attachment(con, "credit", cno, up[0], up[2], _desk(handler, con))
    up2 = (handler._files or {}).get("cm_upload")
    if up2 and up2[2]:
        engine.save_job_attachment(con, "credit", cno, up2[0], up2[2], _desk(handler, con))
    handler._redirect(f"/money?tab=credit&msg=Credit+memo+{cno}+saved")


def _post_credit_apply(handler, con, data, u):
    applies = []
    for k, v in data.items():
        if k.startswith("a__") and v:
            applies.append((k[3:], v))
    credit_allocs = _credit_allocs_checked(data, applies)
    engine.apply_open_credit(
        con, data.get("cm_no") or "", applies, data.get("pay_date") or None,
        _desk(handler, con), line_allocs_map=credit_allocs,
        doc_applies=_doc_applies_from(data),
    )
    handler._redirect("/money?tab=credit&msg=Credit+applied")


def _post_quote_save(handler, con, data, u):
    lines = []
    for i in range(8):
        lines.append({
            "kind": data.get(f"k{i}") or "other",
            "asset_id": data.get(f"a{i}") or "",
            "item": data.get(f"a{i}_text") or "",
            "description": data.get(f"d{i}") or "",
            "qty": data.get(f"q{i}") or 0,
            "rate": data.get(f"r{i}") or 0,
            "uom": data.get(f"u{i}") or "",
        })
    _qn_in = (data.get("quote_no") or "").strip()
    _q_existed = bool(_qn_in and con.execute(
        "SELECT 1 FROM quotes WHERE quote_no=?", (_qn_in,)).fetchone())
    qn = engine.save_quote(con, {
        "quote_no": data.get("quote_no") or None,
        "customer_id": data.get("customer_id"),
        "site_id": data.get("site_id"),
        "job_name": data.get("job_name"),
        "afe": data.get("afe"),
        "po": data.get("po"),
        "quote_date": data.get("quote_date"),
        "valid_until": data.get("valid_until"),
        "notes": data.get("notes"),
        "status": data.get("status") or "Draft",
        "clerk": _desk(handler, con),
    }, lines)
    # Against picker (2026-10-15): attach the picked WO/ticket to this
    # quote — the "type up a quote against that work order" step.
    # _set_quote_link validates the quote exists, isn't void, and belongs
    # to the same customer; a mismatch raises ValueError and the
    # dispatcher lands back on /quotes?err=. The pick is deliberate, so
    # it overwrites any earlier link on that WO/ticket.
    against = (data.get("against") or "").strip()
    if against:
        kind, _, rid = against.partition(":")
        table, idcol = (("work_orders", "wo_id") if kind == "wo" else
                        ("tickets", "ticket_id") if kind == "ticket" else
                        (None, None))
        if table and rid:
            engine._set_quote_link(con, table, idcol, rid, qn,
                                   data.get("customer_id") or "")
            con.commit()
    if not _q_existed:
        engine.add_done_manual(
            con, f"Created quote {qn}", f"/summary/quote/{qn}",
            _desk(handler, con))
    up = (handler._files or {}).get("job_attach")
    if up and up[2]:
        engine.save_job_attachment(con, "quote", qn, up[0], up[2], _desk(handler, con))
    handler._redirect(f"/quotes?msg=Quote+saved")


def _post_quote_status(handler, con, data, u):
    qn = u.path.split("/")[2]
    engine.set_quote_status(con, qn, data.get("status") or "")
    handler._redirect(f"/summary/quote/{qn}?msg=Status+updated")


def _post_quote_convert(handler, con, data, u):
    qn = u.path.split("/")[2]
    made = engine.convert_quote(con, qn, data.get("on_rent") or None)
    msg = "Rental+Tickets+" + "+".join(made) if made else "Quote+converted"
    handler._redirect(f"/summary/quote/{qn}?msg={msg}")


def _post_change_save(handler, con, data, u):
    # Build 'v' (Jason 2026-10-25): the Change Order is a standalone
    # money document — customer + reason + its own lines; the
    # association (one money document, kind:number in assoc_ref) is
    # optional. Direction rides the qty sign (the form's convention:
    # a negative qty subtracts). An existing co_no edits through
    # save_change_order (refused once money has settled against it);
    # a new one issues. D-T1 dies here: the old handler called the
    # engine with a quote_no the form never sent.
    lines = []
    for i in range(6):
        try:
            qty = float(data.get(f"q{i}") or 0)
        except (TypeError, ValueError):
            qty = 0.0
        lines.append({
            "direction": "subtract" if qty < 0 else "add",
            "kind": data.get(f"k{i}") or "Other",
            "item": data.get(f"item{i}") or "",
            "description": data.get(f"d{i}") or "",
            "qty": abs(qty),
            "rate": data.get(f"r{i}") or 0,
            "uom": data.get(f"u{i}") or "",
        })
    assoc_kind = assoc_ref = None
    _ar = (data.get("assoc_ref") or "").strip()
    if _ar:
        assoc_kind, _, assoc_ref = _ar.partition(":")
    co_no = (data.get("co_no") or "").strip()
    exists = bool(co_no and con.execute(
        "SELECT 1 FROM change_orders WHERE co_no=?", (co_no,)).fetchone())
    if exists:
        cno = engine.save_change_order(
            con, co_no, data.get("customer_id") or "",
            data.get("reason") or "", lines,
            data.get("co_date") or None, data.get("notes") or "",
            _desk(handler, con), data.get("po") or "",
            assoc_kind=assoc_kind, assoc_ref=assoc_ref)
        _verb = "saved"
    else:
        cno = engine.issue_change_order(
            con, data.get("customer_id") or "",
            data.get("reason") or "", lines,
            data.get("co_date") or None, data.get("notes") or "",
            _desk(handler, con), data.get("po") or "",
            co_no=co_no or None,
            assoc_kind=assoc_kind, assoc_ref=assoc_ref)
        _verb = "issued"
    up = (handler._files or {}).get("job_attach")
    if up and up[2]:
        engine.save_job_attachment(con, "change", cno, up[0], up[2], _desk(handler, con))
    handler._redirect(f"/summary/change/{cno}?msg=Change+order+{cno}+{_verb}")


def _post_petty(handler, con, data, u):
    engine.record_petty(
        con,
        data.get("direction") or "",
        data.get("amount") or 0,
        data.get("category") or "",
        data.get("txn_date") or None,
        data.get("payee") or "",
        data.get("ref_no") or "",
        data.get("notes") or "",
        _desk(handler, con),
    )
    # Drawer under Administration (Jason 2026-10-24): the save lands
    # back on the drawer — inside the popup fragment when posted from
    # there (frag=1), else the full drawer page.
    if (data.get("frag") or "") == "1":
        handler._redirect("/petty?frag=1&msg=Petty+cash+saved")
    else:
        handler._redirect("/petty?msg=Petty+cash+saved")


def _post_cash_save(handler, con, data, u):
    # Optional line breakdown (Jason 2026-10-23; generalized the same
    # day): cl__<doc_ref>__<line> amounts, only against the entry's
    # attachment — whichever document kind it is. The attachment's
    # kind rides in cash_doc_kind so a ref is never guessed at.
    _cash_allocs = _line_allocs_from(data, "cl")
    _att = {
        "invoice": (data.get("invoice_no") or "").strip(),
        "wo": (data.get("wo_no") or "").strip(),
        "ticket": (data.get("ticket_id") or "").strip(),
        "sale": (data.get("sale_group") or "").strip(),
        "quote": (data.get("quote_no") or "").strip(),
        "change": (data.get("co_no") or "").strip(),
    }
    _cash_ref = next((v for v in _att.values() if v), "")
    for ref in _cash_allocs:
        if ref != _cash_ref:
            raise ValueError(
                "Line breakdown does not match the attachment")
    eid = engine.record_cash_entry(
        con,
        entry_date=data.get("entry_date") or None,
        direction=data.get("direction") or "",
        method=data.get("method") or "",
        amount=data.get("amount") or 0,
        customer_id=data.get("customer_id") or "",
        invoice_no=data.get("invoice_no") or "",
        wo_no=data.get("wo_no") or "",
        ticket_id=data.get("ticket_id") or "",
        asset_id=data.get("asset_id") or "",
        notes=data.get("notes") or "",
        clerk=_desk(handler, con),
        line_allocs=_cash_allocs.get(_cash_ref),
        sale_group=data.get("sale_group") or "",
        quote_no=data.get("quote_no") or "",
        co_no=data.get("co_no") or "",
    )
    engine.add_done_manual(
        con, f"Cash entry {eid} recorded", "/money?tab=cash",
        _desk(handler, con))
    handler._redirect("/money?tab=cash&msg=Cash+entry+saved")


def _post_petty_float(handler, con, data, u):
    engine.set_pc_float(con, float(data.get("pc_float") or 0))
    if (data.get("frag") or "") == "1":
        handler._redirect("/petty?frag=1&msg=Float+saved")
    else:
        handler._redirect("/petty?msg=Float+saved")


def _post_customer_save(handler, con, data, u):
    cid = data.get("customer_id") or None
    # Create vs edit (look-see batch 2, 2026-10-21): a create is an
    # explicit operator action and belongs in Done Today; an edit
    # does not log (the unit-create precedent).
    _existed = bool(cid and con.execute(
        "SELECT 1 FROM customers WHERE customer_id=?", (cid,)).fetchone())
    cid = engine.save_customer(con, {
        "account_name": data.get("account_name"),
        "short_name": data.get("short_name"),
        "bill_to": data.get("bill_to"),
        "phone": data.get("phone"),
        "email": data.get("email"),
        "bill_street": data.get("bill_street"),
        "bill_street2": data.get("bill_street2"),
        "bill_city": data.get("bill_city"),
        "bill_state": data.get("bill_state"),
        "bill_zip": data.get("bill_zip"),
        "terms": data.get("terms") or data.get("terms_text"),
        "tax_exempt": data.get("tax_exempt") == "1",
        "waiver_default": data.get("waiver_default") == "1",
        "credit_limit": data.get("credit_limit"),
        "notes": data.get("notes"),
    }, cid)
    if not _existed:
        engine.add_done_manual(
            con, f"Added customer {(data.get('account_name') or '').strip()} ({cid})"[:200],
            f"/customer/{cid}", _desk(handler, con))
    # Setup chain (Batch 3 #3): advance during a run; after Finished,
    # save stays on the Customers page (Jason 2026-10-21).
    adv = chain_advance(con, "customer", "Customer saved")
    if adv:
        _sep = "&" if "?" in adv[0] else "?"
        handler._redirect(adv[0] + _sep + "from=setup&msg=" + quote_plus(adv[1]))
    else:
        handler._redirect("/customers?msg=Customer+saved")


def _post_customer_contact_save(handler, con, data, u):
    cid=data.get("customer_id") or ""; name=(data.get("name") or "").strip()
    if not cid or not name: raise ValueError("Customer and contact name are required")
    if data.get("is_primary")=="1": con.execute("UPDATE customer_contacts SET is_primary=0 WHERE customer_id=?",(cid,))
    con.execute("INSERT INTO customer_contacts(customer_id,name,role,phone,email,is_primary) VALUES (?,?,?,?,?,?)",(cid,name,data.get("role") or "Other",engine.format_phone_number(data.get("phone") or ""),data.get("email") or "",1 if data.get("is_primary")=="1" else 0))
    con.commit(); handler._redirect(f"/customer/{cid}#contacts")


def _post_customer_contact_delete(handler, con, data, u):
    cid=data.get("customer_id") or ""; con.execute("DELETE FROM customer_contacts WHERE contact_id=? AND customer_id=?",(int(data.get("contact_id") or 0),cid)); con.commit(); handler._redirect(f"/customer/{cid}#contacts")


def _post_customer_location_save(handler, con, data, u):
    cid=data.get("customer_id") or ""; name=(data.get("location_name") or "").strip()
    if not cid or not name: raise ValueError("Customer and location name are required")
    if data.get("is_primary")=="1": con.execute("UPDATE customer_locations SET is_primary=0 WHERE customer_id=?",(cid,))
    con.execute("INSERT INTO customer_locations(customer_id,location_name,street,street2,city,state,zip,is_primary) VALUES (?,?,?,?,?,?,?,?)",(cid,name,data.get("street") or "",data.get("street2") or "",data.get("city") or "",data.get("state") or "",data.get("zip") or "",1 if data.get("is_primary")=="1" else 0))
    con.commit(); handler._redirect(f"/customer/{cid}#locations")


def _post_customer_location_delete(handler, con, data, u):
    cid=data.get("customer_id") or ""; con.execute("DELETE FROM customer_locations WHERE location_id=? AND customer_id=?",(int(data.get("location_id") or 0),cid)); con.commit(); handler._redirect(f"/customer/{cid}#locations")


def _post_export_run(handler, con, data, u):
    what = data.get("what") or "all"
    how = data.get("how") or "csv"
    start, end = handler._export_range(data)
    out, fname = handler._export_build(con, what, how, start, end)
    folder = engine.backup_folder(con)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / fname).write_bytes(out)
    handler._redirect("/export?msg=Saved+" + fname.replace(" ", "+") + "+to+" + str(folder).replace(" ", "+"))


def _post_export_save(handler, con, data, u):
    engine.save_export(
        con,
        data.get("label") or "",
        data.get("what") or "all",
        data.get("when") or "all",
        data.get("from") or "",
        data.get("to") or "",
        data.get("how") or "csv",
    )
    handler._redirect("/export?msg=Preset+saved")


def _post_export_saved_del(handler, con, data, u):
    engine.delete_saved_export(con, data.get("export_id") or "")
    handler._redirect("/export?msg=Preset+removed")


def _post_export_custom_save(handler, con, data, u):
    fields = [k[2:] for k, v in data.items() if k.startswith("f_") and v]
    rid = engine.save_custom_report(
        con,
        data.get("label") or "",
        data.get("ds") or "tickets",
        fields,
        data.get("cfrom") or "",
        data.get("cto") or "",
        data.get("cfield") or "",
        data.get("ctext") or "",
        data.get("csort") or "",
        data.get("cdir") or "asc",
        data.get("how") or "csv",
    )
    handler._redirect("/export?msg=Build+saved")


def _post_export_custom_del(handler, con, data, u):
    try:
        rid = int(data.get("report_id") or 0)
    except (TypeError, ValueError):
        rid = 0
    engine.delete_custom_report(con, rid)
    handler._redirect("/export?msg=Build+removed")


def _post_mixed_save(handler, con, data, u):
    """Save a mixed-report preset by name (re-saving a name updates it).
    kinds rides as one comma field; filter/sort ride from the table's
    current state (JS-filled, empty without JS — the preset still saves
    kinds + timeframe + customer)."""
    kinds = [k.strip() for k in (data.get("kinds") or "").split(",") if k.strip()]
    pid = engine.save_mixed_preset(
        con, data.get("name") or "", kinds,
        time_mode=data.get("time_mode") or "once",
        date_from=data.get("from") or "", date_to=data.get("to") or "",
        month=data.get("month") or "", customer_id=data.get("customer") or "",
        filter_text=data.get("f_q") or "",
        sort_col=data.get("f_sort_col") or 0,
        sort_dir=data.get("f_sort_dir") or "desc")
    handler._redirect(f"/reports/mixed?preset={pid}&msg=Preset+saved")


def _post_mixed_delete(handler, con, data, u):
    try:
        pid = int(data.get("preset_id") or 0)
    except ValueError:
        pid = 0
    if pid:
        engine.delete_mixed_preset(con, pid)
    handler._redirect("/reports/mixed?msg=Preset+deleted")


_POST_ROUTES = {
    "/invoice/create": _post_invoice_create,
    "/pay": _post_pay,
    "/docmoney": _post_docmoney,
    "/doccredit": _post_doccredit,
    "/credit": _post_credit,
    "/credit/apply": _post_credit_apply,
    "/quote/save": _post_quote_save,
    "/change/save": _post_change_save,
    "/petty": _post_petty,
    "/petty/float": _post_petty_float,
    "/cash/save": _post_cash_save,
    "/reports/mixed/save": _post_mixed_save,
    "/reports/mixed/delete": _post_mixed_delete,
    "/customer/save": _post_customer_save,
    "/customer/contact/save": _post_customer_contact_save,
    "/customer/contact/delete": _post_customer_contact_delete,
    "/customer/location/save": _post_customer_location_save,
    "/customer/location/delete": _post_customer_location_delete,
    "/export/run": _post_export_run,
    "/export/save": _post_export_save,
    "/export/saved/del": _post_export_saved_del,
    "/export/custom/save": _post_export_custom_save,
    "/export/custom/del": _post_export_custom_del,
}


_POST_PATTERN_ROUTES = [
    ("/invoice/", "/po", _post_invoice_po),
    ("/invoice/", "/doc", _post_invoice_doc),
    ("/invoice/", "/docdel", _post_invoice_docdel),
    ("/invoice/", "/docprint", _post_invoice_docprint),
    ("/invoice/", "/line", _post_invoice_line),
    ("/invoice/", "/linedel", _post_invoice_linedel),
    ("/invoice/", "/linenote", _post_invoice_linenote),
    ("/wo/", "/linenote", _post_doc_linenote),
    ("/ticket/", "/linenote", _post_doc_linenote),
    ("/sale/", "/linenote", _post_doc_linenote),
    ("/quote/", "/linenote", _post_doc_linenote),
    ("/change/", "/linenote", _post_doc_linenote),
    ("/quote/", "/status", _post_quote_status),
    ("/quote/", "/convert", _post_quote_convert),
]


def handle_post(handler, con, data, u):
    """Handle one POST. Returns True when the path was handled."""
    fn = _POST_ROUTES.get(u.path)
    if fn is not None:
        fn(handler, con, data, u)
        return True
    for prefix, suffix, fn in _POST_PATTERN_ROUTES:
        if u.path.startswith(prefix) and u.path.endswith(suffix):
            fn(handler, con, data, u)
            return True
    return False
