"""FleetSheet POST actions — accounting flow: invoices, payments, credit, quotes, petty cash, customers, export."""
import re
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
        # Void-and-revise (build 'ab', Jason 2026-10-26): a saved
        # invoice is a record — it never updates in place. The one
        # licensed in-place save is a REVISION's own form completing
        # under the session marker the revise act set (edit_target
        # names the revision the form was loaded with; the posted
        # invoice_no is the operator's number for it, renames
        # included). The old invoice_locked refusal is superseded:
        # money recorded against the chain resolves to the head, so
        # a revised invoice keeps its payments as chain facts.
        _target = (data.get("edit_target") or "").strip() \
            or data["invoice_no"].strip()
        _ex = con.execute(
            "SELECT customer_id, terms FROM invoices WHERE invoice_no=?",
            (_target,)).fetchone()
        if _ex:
            _key = engine.doc_key(con, "invoice", _target)
            if not engine.revision_pending(con, "invoice", _key):
                raise ValueError(
                    f"Invoice {_target} is posted — revise it (Edit "
                    f"on its form) to change it")
            if (data.get("customer_id") or "") != engine.cust_code(con, _ex["customer_id"]):
                raise ValueError(
                    "The customer can't change on a saved invoice — "
                    "void it and write a new one")
            ino = _target
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
    if replace:
        # The revision's first Save completes it (build 'ab'): an
        # operator-renamed number validates against the kind's whole
        # history — voided numbers stay taken — then the session
        # marker clears; the form reopens locked from here on.
        _new_no = (data.get("invoice_no") or "").strip()
        if _new_no and _new_no != ino:
            engine.validate_new_doc_no(con, "invoices", "invoice_no",
                                       _new_no, "invoice")
            con.execute("UPDATE invoices SET invoice_no=? "
                        "WHERE invoice_no=?", (_new_no, ino))
            ino = _new_no
        engine.clear_revision_pending(
            con, "invoice", engine.doc_key(con, "invoice", ino))
        # The completed revision is a new issuance (redirect #3):
        # it wears the company identity current at this posting.
        engine.stamp_company_snapshot(
            con, "invoices", engine.doc_key(con, "invoice", ino))
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


def _pay_add_splits(data, splits, co_splits):
    """Add Item rows on the payment form (build 'af', Jason
    2026-10-28): adddoc__N names a document ("invoice:<no>" /
    "change:<co_no>" — the picker's open documents, the same
    source the splits table lists) and addamt__N its amount; the
    pair merges into the batch's splits. A document that already
    holds an allocation row in this batch — a standing split with
    an amount, or a second added row naming it — is refused with
    a plain error."""
    have_inv = {ref for ref, _a in splits}
    have_co = {ref for ref, _a in co_splits}
    seen = set()
    for k in sorted(data.keys()):
        if not k.startswith("adddoc__"):
            continue
        n = k[len("adddoc__"):]
        spec = (data.get(k) or "").strip()
        raw = (data.get(f"addamt__{n}") or "").strip()
        if not spec or not raw:
            continue
        try:
            amt = float(raw)
        except (TypeError, ValueError):
            continue
        if amt <= 0:
            continue
        kind, _, ref = spec.partition(":")
        ref = ref.strip()
        label = {"invoice": "Invoice",
                 "change": "Change Order"}.get(kind)
        if label is None or not ref:
            continue
        if (kind, ref) in seen or (kind == "invoice" and ref in have_inv) \
                or (kind == "change" and ref in have_co):
            raise ValueError(
                f"{label} {ref} already has a row in this payment")
        seen.add((kind, ref))
        if kind == "invoice":
            splits.append((ref, amt))
            have_inv.add(ref)
        else:
            co_splits.append((ref, amt))
            have_co.add(ref)
    return splits, co_splits


def _post_pay_correction(handler, con, data, u):
    """Apply the payment revision (build 'ab', void-and-revise —
    the correction model, approved by Jason 2026-10-26: "the
    payment mechanic is sound... The records must stay"). The
    original was voided at the revise CONFIRM (signed with the
    reason, the operator's name, the timestamp; JC-AB0) and its
    replacement batch '<original> Rev. N' minted there; this post
    is the revision form's Apply, licensed by the session marker
    the confirm set (target_batch names the minted batch, the
    marker names the original). The splits post into the minted
    batch through the ordinary record paths — balance reads
    already exclude the voided original, so they validate against
    the restored state. The posted pay_no may rename the batch
    (a free-text number under the same law); the void's
    replaced-by stamp follows the final name. The batch names
    the original (void_corrects); Done carries the posting (the
    void's Done entry was written at the confirm)."""
    target = (data.get("target_batch") or "").strip()
    orig = engine.get_option(con, f"revtarget:payment:{target}") \
        if target else ""
    if not target or not orig:
        raise ValueError(
            "That payment is posted — revise it (Edit on its form) "
            "to change it")
    info = engine.payment_batch_info(con, orig)
    ocust = info["customer_id"]
    pdate = data.get("pay_date") or date.today().isoformat()
    method = data.get("method") or ""
    ref = data.get("ref") or ""
    notes = (data.get("notes") or "").strip()
    clerk = _desk(handler, con)
    splits = []
    for k, v in data.items():
        if k.startswith("p__") and v:
            try:
                amt = float(v)
            except (TypeError, ValueError):
                continue
            if amt > 0:
                splits.append((k[3:], amt))
    co_splits = []
    for k, v in data.items():
        if k.startswith("pco__") and v:
            try:
                amt = float(v)
            except (TypeError, ValueError):
                continue
            if amt > 0:
                co_splits.append((k[5:], amt))
    doc_splits = _doc_applies_from(data, "pd", "pdl")
    splits, co_splits = _pay_add_splits(data, splits, co_splits)
    if not splits and not co_splits and not doc_splits:
        raise ValueError(
            "Enter an Apply amount — a correction posts the payment "
            "somewhere, or it is not a correction")
    # Chain-head resolution (JC-AB26): a document the original
    # payment settled may itself have been revised since — the
    # correction's money belongs on the live head of its chain,
    # never on the voided ancestor the form was prefilled from.
    # Line breakdowns do not translate (the revision's lines are
    # new rows); a translated document's split posts without its
    # original breakdown.
    _moved = set()

    def _head(kind, ref):
        h = engine.chain_head_ref(con, kind, ref)
        if h and h != ref:
            _moved.add((kind, ref))
            return h
        return ref

    splits = [(_head("invoice", ino), amt) for ino, amt in splits]
    co_splits = [(_head("change", cno), amt) for cno, amt in co_splits]
    doc_splits = [
        (k2, _head(k2, r2), a2, None if (k2, r2) in _moved else l2)
        for k2, r2, a2, l2 in doc_splits]
    allocs = _line_allocs_from(data, "pl")
    allocs = {ino: v for ino, v in allocs.items()
              if ("invoice", ino) not in _moved}
    _split_inos = {ino for ino, _a in splits}
    for ino in allocs:
        if ino not in _split_inos:
            raise ValueError(
                f"Line amounts entered for {ino} with no Apply amount")
    # A correction cannot move money to another customer (JC-AB12):
    # every split must belong to the original payment's customer.
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
    _doc_cust_q = {
        "wo": "SELECT customer_id FROM work_orders WHERE wo_id=?",
        "ticket": "SELECT customer_id FROM tickets WHERE ticket_id=?",
        "sale": "SELECT customer_id FROM sales WHERE sale_id=?",
        "quote": "SELECT customer_id FROM quotes WHERE quote_no=?",
    }
    for kind, ref2, _a, _l in doc_splits:
        r = con.execute(_doc_cust_q[kind], (ref2,)).fetchone()
        if not r:
            raise ValueError(f"Unknown {engine.DOC_LABELS[kind]} {ref2}")
        custs.add(engine.cust_code(con, r["customer_id"]))
    if custs != {ocust}:
        raise ValueError(
            "A correction keeps the payment on its customer — the "
            "documents span another customer")
    posted_cust = (data.get("customer_id") or "").strip()
    if posted_cust and posted_cust != ocust:
        raise ValueError(
            "A correction keeps the payment on its customer")
    new_batch = target
    _pay_no = (data.get("pay_no") or "").strip()
    if _pay_no and _pay_no != target:
        _taken = False
        for _tbl in ("collections", "doc_collections"):
            try:
                _taken = _taken or bool(con.execute(
                    f"SELECT 1 FROM {_tbl} "
                    f"WHERE COALESCE(batch_id, pay_id)=? LIMIT 1",
                    (_pay_no,)).fetchone())
            except Exception:
                pass
        if _taken:
            raise ValueError(f"Payment number {_pay_no} is taken")
        new_batch = _pay_no
    orig_inos = []
    for r in info["crows"]:
        ino = engine.doc_num(con, "invoice", r["invoice_id"])
        if ino:
            orig_inos.append(ino)
    try:
        if new_batch != target:
            for _tbl in ("collections", "doc_collections"):
                con.execute(
                    f"UPDATE {_tbl} SET void_replaced_by=? "
                    f"WHERE voided=1 AND void_replaced_by=?",
                    (new_batch, target))
        pay_ids = []
        for ino, amt in splits:
            res = engine.record_payment(
                con, ino, amt, pdate, method, ref, clerk,
                batch_id=new_batch, commit=False,
                line_allocs=allocs.get(ino))
            if res["pay_id"]:
                pay_ids.append(res["pay_id"])
        for cno, amt in co_splits:
            res = engine.record_doc_payment(
                con, "change", cno, amt, pdate, method, ref, clerk,
                batch_id=new_batch, commit=False)
            if res["pay_id"]:
                pay_ids.append(res["pay_id"])
        for kind, ref2, amt, lns in doc_splits:
            res = engine.record_doc_payment(
                con, kind, ref2, float(amt), pdate, method, ref,
                clerk, batch_id=new_batch, commit=False,
                line_allocs=lns)
            if res["pay_id"]:
                pay_ids.append(res["pay_id"])
        for pid in pay_ids:
            con.execute(
                "UPDATE collections SET ref_no=?, clerk=?, "
                "notes=? WHERE pay_id=?",
                (ref.strip(), clerk, notes, pid))
            con.execute(
                "UPDATE doc_collections SET ref_no=?, clerk=?, "
                "notes=? WHERE pay_id=?",
                (ref.strip(), clerk, notes, pid))
        engine.stamp_payment_correction(con, new_batch, orig)
        # Invoices the correction moved money OFF of need their
        # status recomputed against the void (record_payment
        # already refreshed the ones it re-applied to).
        for ino in orig_inos:
            engine._refresh_invoice_status(con, ino)
        con.commit()
    except Exception:
        con.rollback()
        raise
    engine.set_option(con, f"revtarget:payment:{target}", "")
    engine.add_done_manual(
        con, f"Payment {new_batch} recorded — correction of {orig}",
        f"/summary/payment/{new_batch}", clerk)
    up = (handler._files or {}).get("pay_upload")
    if up and up[2] and pay_ids:
        engine.save_job_attachment(
            con, "pay", str(pay_ids[0]), up[0], up[2], clerk)
    handler._redirect(
        f"/summary/payment/{new_batch}?msg=" + quote_plus(
            f"Payment {new_batch} recorded — correction of {orig}; "
            f"the original stands void"))
    return


def _post_pay(handler, con, data, u):
    if (data.get("revising") or "") == "1":
        return _post_pay_correction(handler, con, data, u)
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
    # Add Item rows (build 'af'): picker rows merge into the same
    # splits before every check below — one batch, one customer.
    splits, co_splits = _pay_add_splits(data, splits, co_splits)
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
    # Void-and-revise (build 'ab', Jason 2026-10-26): an existing
    # quote never saves in place — except a fresh revision
    # completing under its session marker (edit_target names the
    # revision the form was loaded with; a renamed number
    # validates against the whole history and lands first, so the
    # save updates the revision row itself).
    _q_target = (data.get("edit_target") or "").strip()
    if _q_target:
        _qk = engine.doc_key(con, "quote", _q_target)
        if not engine.revision_pending(con, "quote", _qk):
            raise ValueError(
                f"Quote {_q_target} is posted — revise it (Edit on "
                f"its form) to change it")
        if _qn_in and _qn_in != _q_target:
            engine.validate_new_doc_no(con, "quotes", "quote_no",
                                       _qn_in, "quote")
            con.execute("UPDATE quotes SET quote_no=? "
                        "WHERE quote_no=?", (_qn_in, _q_target))
            con.commit()
    elif _qn_in and con.execute(
            "SELECT 1 FROM quotes WHERE quote_no=?",
            (_qn_in,)).fetchone():
        raise ValueError(
            f"Quote {_qn_in} is posted — revise it (Edit on its "
            f"form) to change it")
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
    if _q_target:
        engine.clear_revision_pending(
            con, "quote", engine.doc_key(con, "quote", qn))
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
    # Void-and-revise (build 'ab', Jason 2026-10-26): an existing
    # Change Order never saves in place — except a fresh revision
    # completing under its session marker (edit_target names the
    # revision the form was loaded with; a renamed number
    # validates against the whole history and lands first).
    _co_target = (data.get("edit_target") or "").strip()
    _co_session = False
    if _co_target:
        _ck = engine.doc_key(con, "change", _co_target)
        if not engine.revision_pending(con, "change", _ck):
            raise ValueError(
                f"Change Order {_co_target} is issued — revise it "
                f"(Edit on its form) to change it")
        _co_session = True
        if co_no and co_no != _co_target:
            engine.validate_new_doc_no(con, "change_orders", "co_no",
                                       co_no, "change order")
            con.execute("UPDATE change_orders SET co_no=? "
                        "WHERE co_no=?", (co_no, _co_target))
            con.commit()
    exists = bool(co_no and con.execute(
        "SELECT 1 FROM change_orders WHERE co_no=?", (co_no,)).fetchone())
    if exists and not _co_session:
        raise ValueError(
            f"Change Order {co_no} is issued — revise it (Edit on "
            f"its form) to change it")
    if exists:
        cno = engine.save_change_order(
            con, co_no, data.get("customer_id") or "",
            data.get("reason") or "", lines,
            data.get("co_date") or None, data.get("notes") or "",
            _desk(handler, con), data.get("po") or "",
            assoc_kind=assoc_kind, assoc_ref=assoc_ref,
            revision=_co_session)
        if _co_session:
            engine.clear_revision_pending(
                con, "change", engine.doc_key(con, "change", cno))
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
    # Revision session (build 'ab', redirect #2): the loaded entry
    # is a revision shell in the petty log; its Save completes it in
    # place (complete_petty_revision) under the marker's license.
    if (data.get("revising") or "") == "1":
        _tgt = (data.get("target") or "").strip()
        _shell = con.execute(
            "SELECT * FROM petty_cash WHERE pc_id=?", (_tgt,)).fetchone()
        if (not _shell or not engine.revision_pending(
                con, "petty", _shell["id"])):
            handler._redirect(
                "/petty?err=" + quote_plus(
                    f"Petty cash entry {_tgt} is posted — revise it "
                    f"(Edit on its register row) to change it"))
            return True
        _new_no = engine.complete_petty_revision(
            con, _shell["id"],
            data.get("direction") or "",
            data.get("amount") or 0,
            data.get("category") or "",
            data.get("txn_date") or None,
            data.get("payee") or "",
            data.get("ref_no") or "",
            data.get("notes") or "",
            _desk(handler, con),
            pc_id=data.get("pc_id") or "")
        engine.clear_revision_pending(con, "petty", _shell["id"])
        engine.add_done_manual(
            con, f"Petty cash entry {_new_no} recorded — revision",
            "/petty", _desk(handler, con))
        if (data.get("frag") or "") == "1":
            handler._redirect("/petty?frag=1&msg=Petty+cash+saved")
        else:
            handler._redirect("/petty?msg=Petty+cash+saved")
        return True
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
        pc_id=data.get("pc_id") or "",
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
    # Revision session (build 'ab', redirect #2): the loaded entry
    # is a revision shell standing under its marker; completing it
    # re-posts the entry fresh (complete_cash_revision) — full
    # validation, fresh settlement, chain re-pointed.
    _target = (data.get("edit_target") or "").strip()
    if _target:
        _shell = con.execute(
            "SELECT * FROM cash_entries WHERE entry_no=?",
            (_target,)).fetchone()
        if (not _shell or not engine.revision_pending(
                con, "cash", _shell["entry_id"])):
            handler._redirect(
                "/money?tab=cash&err=" + quote_plus(
                    f"Cash entry {_target} is posted — revise it "
                    f"(Edit on its form) to change it"))
            return True
        _orig = con.execute(
            "SELECT entry_no FROM cash_entries WHERE entry_id=?",
            (_shell["revises_id"],)).fetchone()
        _att2 = {
            "invoice": (data.get("invoice_no") or "").strip(),
            "wo": (data.get("wo_no") or "").strip(),
            "ticket": (data.get("ticket_id") or "").strip(),
            "sale": (data.get("sale_group") or "").strip(),
            "quote": (data.get("quote_no") or "").strip(),
            "change": (data.get("co_no") or "").strip(),
        }
        _ref2 = next((v for v in _att2.values() if v), "")
        _new_id = engine.complete_cash_revision(
            con, _shell["entry_id"],
            entry_no=data.get("entry_no") or "",
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
            line_allocs=_cash_allocs.get(_ref2),
            sale_group=data.get("sale_group") or "",
            quote_no=data.get("quote_no") or "",
            co_no=data.get("co_no") or "")
        engine.clear_revision_pending(con, "cash", _shell["entry_id"])
        engine.add_done_manual(
            con, f"Cash entry {data.get('entry_no') or _target} "
                 f"recorded — revision of "
                 f"{_orig[0] if _orig else _target}",
            "/money?tab=cash", _desk(handler, con))
        handler._redirect("/money?tab=cash&msg=Cash+entry+saved")
        return True
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
        entry_no=data.get("entry_no") or "",
    )
    engine.add_done_manual(
        con, f"Cash entry {data.get('entry_no') or eid} recorded",
        "/money?tab=cash", _desk(handler, con))
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
    # Build 'ae' rebuild (Phase 3, JC-AE4): Contacts + Locations ride this one
    # Save — sync the posted in-form rows against the customer's sets,
    # the syncs resolve the code to the customer's engine id
    # (the schema's FK key), then one commit. Deletions happen ONLY via the explicit
    # in-form Remove flag (ct_del/lc_del), never by omission; existing
    # ids never posted are left standing.
    _sync_customer_contacts(con, cid, data)
    _sync_customer_locations(con, cid, data)
    con.commit()
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


def _posted_row_indices(data, pfx):
    """Indices of the in-form rows posted under a prefix (ct_/lc_),
    collected by key scan — the app.py indexed-name pattern."""
    out = set()
    for k in data:
        m = re.match(pfx + r"[a-z0-9]+_(\d+)$", k)
        if m:
            out.add(int(m.group(1)))
    return sorted(out)


def _sync_customer_contacts(con, cid, data):
    """Build 'ae' rebuild Phase 3 sync (JC-AE4): row with id + del flag →
    DELETE; row with id → UPDATE (a blank Name falls back to the
    stored name — a filled row never loses its name to an accidental
    clear); row without id + non-blank Name → INSERT (phone through
    engine.format_phone_number, as the retired add handler); blank
    new rows are skipped. A saved row carrying the primary flag
    first clears is_primary on the customer's other rows — the last
    primary-checked row in form order wins, deterministically."""
    # Children key by the customer's ENGINE id (schema FK +
    # enforced pragma; see the view-side note in
    # views_accounting.view_customer_form).
    _kr = con.execute(
        "SELECT id FROM customers WHERE customer_id=?", (cid,)).fetchone()
    if not _kr:
        return
    cid = _kr[0]
    for i in _posted_row_indices(data, "ct_"):
        rid = (data.get(f"ct_id_{i}") or "").strip()
        name = (data.get(f"ct_name_{i}") or "").strip()
        if rid and data.get(f"ct_del_{i}") == "1":
            con.execute(
                "DELETE FROM customer_contacts WHERE contact_id=? AND customer_id=?",
                (int(rid), cid))
            continue
        if not rid and not name:
            continue
        primary = 1 if data.get(f"ct_primary_{i}") == "1" else 0
        if primary:
            con.execute(
                "UPDATE customer_contacts SET is_primary=0 WHERE customer_id=?",
                (cid,))
        role = data.get(f"ct_role_{i}") or "Other"
        phone = engine.format_phone_number(data.get(f"ct_phone_{i}") or "")
        email = data.get(f"ct_email_{i}") or ""
        if rid:
            if not name:
                _r = con.execute(
                    "SELECT name FROM customer_contacts WHERE contact_id=? AND customer_id=?",
                    (int(rid), cid)).fetchone()
                name = _r["name"] if _r else ""
            con.execute(
                "UPDATE customer_contacts SET name=?, role=?, phone=?, email=?, is_primary=? "
                "WHERE contact_id=? AND customer_id=?",
                (name, role, phone, email, primary, int(rid), cid))
        else:
            con.execute(
                "INSERT INTO customer_contacts(customer_id,name,role,phone,email,is_primary) "
                "VALUES (?,?,?,?,?,?)",
                (cid, name, role, phone, email, primary))


def _sync_customer_locations(con, cid, data):
    """Build 'ae' rebuild Phase 3 sync (JC-AE4): the locations mirror of
    _sync_customer_contacts, same semantics over customer_locations."""
    _kr = con.execute(
        "SELECT id FROM customers WHERE customer_id=?", (cid,)).fetchone()
    if not _kr:
        return
    cid = _kr[0]
    for i in _posted_row_indices(data, "lc_"):
        rid = (data.get(f"lc_id_{i}") or "").strip()
        name = (data.get(f"lc_name_{i}") or "").strip()
        if rid and data.get(f"lc_del_{i}") == "1":
            con.execute(
                "DELETE FROM customer_locations WHERE location_id=? AND customer_id=?",
                (int(rid), cid))
            continue
        if not rid and not name:
            continue
        primary = 1 if data.get(f"lc_primary_{i}") == "1" else 0
        if primary:
            con.execute(
                "UPDATE customer_locations SET is_primary=0 WHERE customer_id=?",
                (cid,))
        vals = (name, data.get(f"lc_street_{i}") or "",
                data.get(f"lc_street2_{i}") or "",
                data.get(f"lc_city_{i}") or "",
                data.get(f"lc_state_{i}") or "",
                data.get(f"lc_zip_{i}") or "", primary)
        if rid:
            if not name:
                _r = con.execute(
                    "SELECT location_name FROM customer_locations WHERE location_id=? AND customer_id=?",
                    (int(rid), cid)).fetchone()
                name = _r["location_name"] if _r else ""
                vals = (name,) + vals[1:]
            con.execute(
                "UPDATE customer_locations SET location_name=?, street=?, street2=?, city=?, "
                "state=?, zip=?, is_primary=? WHERE location_id=? AND customer_id=?",
                vals + (int(rid), cid))
        else:
            con.execute(
                "INSERT INTO customer_locations(customer_id,location_name,street,street2,city,state,zip,is_primary) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (cid,) + vals)


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
    # Build 'ae' rebuild Phase 3: /customer/contact|location
    # save+delete retired with their cards — contacts/locations
    # post inside /customer/save now (one step, one form).
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
