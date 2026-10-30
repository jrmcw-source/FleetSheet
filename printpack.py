"""Print sheets: on-screen HTML (browser Print / Save as PDF) and file PDF."""
from __future__ import annotations

import base64
import html
import re
from datetime import datetime
from urllib.parse import quote as _urlquote
from io import BytesIO
from pathlib import Path

import engine
from logo_data import LOGO_JPEG

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    HAS_PDF = True
except ImportError:
    HAS_PDF = False
    colors = letter = ParagraphStyle = getSampleStyleSheet = inch = None
    Image = Paragraph = SimpleDocTemplate = Spacer = Table = TableStyle = None

LOGO_BYTES = base64.b64decode(LOGO_JPEG)
LEGAL = (
    "FleetSheet · Yard book. One file. Amounts are computed from locked rates, dates, "
    "and tax location. This sheet is a billing instrument, not a tax opinion. "
    "Payment is due per stated terms. Disputes in writing within 10 days of invoice date."
)

# Invoice-only legalese (Item C, as amended): SEPARATE from the shared
# LEGAL above, which every non-invoice document keeps verbatim. Only
# invoice outputs (invoice HTML print, invoice PDF footer,
# invoice pack pages) use this. Its FIRST sentence is derived from the
# invoice's resolved terms (invoice terms, falling back to customer
# terms — the same _invoice_terms resolution the Terms strip uses);
# the remainder is Jason's dictated paragraph verbatim, parameterized
# only by the current book's company name.
INVOICE_LEGAL_REST_TEMPLATE = (
    "A late charge of 1.5% per month will be assessed on all past-due "
    "balances. Any objections to this invoice must be communicated in "
    "writing within 7 business days of receipt. Title to all "
    "merchandise/services remains the property of {company} until paid "
    "in full. By paying this invoice, the client agrees to these terms."
)


def _revto_for(con, kind, row) -> str:
    """Build 'al' (Jason 2026-10-28): the revision a voided
    original was revised into, or "" — the printed document of an
    original carries *Revised to: <number> across its top, so a
    reprint states where its money went."""
    if row is None:
        return ""
    try:
        info = engine.revision_info(con, kind, row)
    except Exception:
        return ""
    return str(info.get("revised_by") or "")


def _invoice_due_sentence(terms) -> str:
    """First legalese sentence, derived from the resolved terms:
    a 'Net N' value anywhere in the terms (including discount forms
    like '1/10 Net 30') → due within N days; 'Due on Receipt' /
    'Upon Receipt' → due on receipt; empty/unresolvable → the
    historical 30-day default; anything else (COD, Cash in Advance,
    EOM, 15 MFI, custom text) → due according to the terms of this
    invoice, with the terms text printed exactly as stored."""
    _t = str(terms or "").strip()
    if not _t:
        return "Payment is due within 30 days of the invoice date."
    _m = re.search(r"\bnet\s*(\d+)\b", _t, re.IGNORECASE)
    if _m:
        return (f"Payment is due within {int(_m.group(1))} days of "
                f"the invoice date.")
    if _t.lower() in ("due on receipt", "upon receipt"):
        return "Payment is due on receipt."
    _end = "" if _t[-1] in ".!?" else "."
    return f"Payment is due according to the terms of this invoice: {_t}{_end}"


def invoice_legal_text(company_name, terms=None) -> str:
    """The invoice footer paragraph: the terms-derived due sentence,
    then the dictated remainder with the book's company name in place
    of [Business Name] — no brackets ever reach the page."""
    _name = str(company_name or "").strip() or "the company"
    return (f"{_invoice_due_sentence(terms)} "
            + INVOICE_LEGAL_REST_TEMPLATE.format(company=_name))


def _invoice_legal_for(pack) -> str:
    """Invoice legalese for a pack: company name from the pack's
    company row (Setup/company data already in the pack), terms from
    the pack's invoice via the Terms strip's own resolution."""
    _co = (pack or {}).get("co") if isinstance(pack, dict) else None
    _inv = (pack or {}).get("inv") if isinstance(pack, dict) else None
    try:
        _terms = _invoice_terms(_inv) if _inv is not None else None
    except Exception:
        _terms = None
    return invoice_legal_text(_rowval(_co, "name"), _terms)


_FMT_DATE_RE = re.compile(
    r"^(\d{4}-\d{1,2}-\d{1,2}|\d{4}/\d{1,2}/\d{1,2}|\d{1,2}/\d{1,2}/\d{4})"
    r"(?:[ T](\d{1,2}:\d{2}(?::\d{2})?(?:\s*[AaPp][Mm])?))?$")


def _fmt_date(value) -> str:
    """Central printed-date formatter (Item A): every user-visible
    date printed by this module renders MM/DD/YYYY, zero-padded.

    Accepts ISO / slash dates and datetimes (a datetime keeps its
    time, verbatim, after the reformatted date). Preserves blanks,
    '—', 'open' and any non-date text exactly as given; stored data
    and non-date identifiers are never touched — this only formats
    values at print time, using engine._parse for the parse."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        _d = value.strftime("%m/%d/%Y")
        if value.hour or value.minute or value.second:
            return f"{_d} {value.strftime('%H:%M')}"
        return _d
    _s = str(value)
    _t = _s.strip()
    if not _t or _t in ("—", "–", "-") or _t.lower() == "open":
        return _s
    _m = _FMT_DATE_RE.match(_t)
    if not _m:
        return _s
    try:
        _d = engine._parse(_m.group(1))
    except Exception:
        _d = None
    if _d is None:
        return _s
    _out = _d.strftime("%m/%d/%Y")
    if _m.group(2):
        _out += " " + _m.group(2)
    return _out


def invoice_pack(con, invoice_no: str, selected=None) -> dict | None:
    inv = con.execute(
        """SELECT i.*, c.account_name, c.bill_to, c.phone, c.email, c.city_st, c.terms AS cust_terms,
           c.bill_street, c.bill_street2
           FROM invoices i JOIN customers c ON c.id = i.customer_id
           WHERE i.invoice_no=?""",
        (invoice_no,),
    ).fetchone()
    if not inv:
        return None
    co = _doc_company(con, _rowval(inv, "co_snapshot"))
    tot = engine.invoice_totals(con, invoice_no)
    # Operator tax-exempt click (guarded — the column may not exist on
    # pre-migration books): when set, NO line counts as taxed for the
    # asterisk, whatever its stored tax_amount says.
    _opex_raw = _rowval(inv, "tax_exempt_op")
    if isinstance(_opex_raw, str):
        _op_exempt = _opex_raw.strip() in ("1", "true", "True")
    else:
        _op_exempt = bool(_opex_raw)
    # The write-in's typed description (guarded, same reason).
    _adj_label = _rowval(inv, "adj_label") or ""
    lines = []
    # B2: stored invoice_lines are the immutable record. When they exist,
    # print ONLY them — the live-recomputed ticket/work-order rows below
    # describe the same lines and would print everything twice.
    try:
        _stored = engine.invoice_has_lines(con, invoice_no)
    except Exception:
        _stored = False
    if not _stored:
        for t in con.execute(
            """SELECT t.ticket_id, t.on_rent, t.off_rent, t.rate_type, t.job_name,
                      a.unit_no, a.description, s.site_name
               FROM tickets t
               JOIN assets a ON a.id = t.asset_id
               LEFT JOIN sites s ON s.id = t.site_id
               WHERE t.invoice_id=? ORDER BY t.ticket_id""",
            (inv["id"],),
        ):
            m = engine.ticket_money(con, t["ticket_id"])
            pos = m.get("possession_label") or ""
            tax_bit = (
                f"{m.get('tax_name') or 'Tax'} @ {m.get('tax_rate', 0):.4f}"
                + (" · exempt" if m.get("tax_exempt") else "")
            )
            # The ticket's real lines (2026-10-23): the computed
            # rental line keeps the rich ticket wording; every other
            # line — waiver, environmental fee, and the stored charge
            # lines — prints as itself, with its own Tax flag.
            for _ln in (m.get("lines") or []):
                if _ln.get("computed") and _ln["category"] == "Rental" \
                        and _ln["description"] == (t["description"] or ""):
                    lines.append({
                        "kind": "Rental",
                        "id": t["ticket_id"],
                        "ref": t["unit_no"] or "",
                        "desc": t["description"] or "",
                        "detail": t["description"] or "",
                        "when": (
                            f"{_fmt_date(t['on_rent'])} – {_fmt_date(t['off_rent'] or 'open')} · "
                            f"{t['rate_type']} × {m['days']}d · {pos} · {tax_bit}"
                        ),
                        "amount": _ln["amount"],
                        # Restyle (tweak round 2): UNIT | QTY +
                        # DESCRIPTION | unit price | line total columns.
                        # Qty/rate are the ticket's own billable days
                        # and applied rate.
                        "unit": t["rate_type"] or "Rental",
                        "qty": m.get("days"),
                        "rate": m.get("rate"),
                        "taxed": (not _op_exempt)
                                 and float(m.get("tax") or 0) > 0,
                    })
                else:
                    _ld = _ln["description"] or _ln["category"]
                    lines.append({
                        "kind": _ln["category"],
                        "id": t["ticket_id"],
                        "ref": t["unit_no"] or "",
                        "desc": _ld,
                        "detail": _ld,
                        "when": "",
                        "amount": _ln["amount"],
                        "unit": _ln["uom"], "qty": _ln["qty"],
                        "rate": _ln["rate"],
                        # Per-line tax: the asterisk follows the
                        # line's own Tax flag.
                        "taxed": (not _op_exempt) and bool(_ln["taxed"])
                                 and not m.get("tax_exempt")
                                 and float(m.get("tax_rate") or 0) > 0,
                    })
        for w in con.execute(
            """SELECT w.wo_id, w.work_type, w.description, w.bill_amount, a.unit_no
               FROM work_orders w JOIN assets a ON a.id = w.asset_id
               WHERE w.invoice_id=? ORDER BY w.wo_id""",
            (inv["id"],),
        ):
            # Description is the line text; the work type prefixes it
            # only when it adds information the description lacks
            # (none of its words already appear in the description).
            _wt = (w["work_type"] or "").strip()
            _wdesc = (w["description"] or "").strip()
            _wt_words = ["".join(ch for ch in tok.lower() if ch.isalnum())
                         for tok in _wt.split()]
            _wt_words = [x for x in _wt_words if x]
            _wdesc_words = {"".join(ch for ch in tok.lower() if ch.isalnum())
                            for tok in _wdesc.split()}
            if _wt and _wdesc and _wt.lower() not in _wdesc.lower() \
                    and not (_wt_words
                             and all(x in _wdesc_words for x in _wt_words)):
                _wdesc = f"{_wt} — {_wdesc}"
            elif not _wdesc:
                _wdesc = _wt
            lines.append({
                "kind": "Service",
                "id": w["wo_id"],
                "ref": w["unit_no"] or "",
                "desc": _wdesc,
                "detail": _wdesc,
                "when": "Work order",
                "amount": float(w["bill_amount"] or 0),
                # bill_amount is a total, not a unit rate — price blank.
                "unit": "Service", "qty": None, "rate": None,
                # Work-order tax is not computed in the live path.
                "taxed": False,
            })
    try:
        extras = con.execute(
            "SELECT * FROM invoice_lines WHERE invoice_id=? ORDER BY line_id", (inv["id"],)
        ).fetchall()
    except Exception:
        extras = []
    # ITEM slot resolution (round 2, incl. Jason's broadening): the
    # stored/typed item wins; then the type default from the line's
    # category (Labor / Part / Freight); then, for rental/asset lines,
    # the equipment number via the line's source ticket / work order.
    def _type_default(cat):
        _c = (cat or "").strip().lower()
        if _c == "labor":
            return "Labor"
        if _c in ("part", "parts"):
            return "Part"
        if _c == "freight":
            return "Freight"
        if "labor" in _c:
            return "Labor"
        if "freight" in _c:
            return "Freight"
        if "part" in _c:
            return "Part"
        return ""

    _src_unit = {}
    try:
        _tids = sorted({str(x["source_id"]) for x in extras
                        if "source_type" in x.keys()
                        and x["source_type"] == "ticket"
                        and "source_id" in x.keys() and x["source_id"]})
        if _tids:
            _ph = ",".join("?" * len(_tids))
            for _r in con.execute(
                    "SELECT t.ticket_id, a.unit_no FROM tickets t "
                    "JOIN assets a ON a.id = t.asset_id "
                    f"WHERE t.ticket_id IN ({_ph})", _tids):
                _src_unit[("ticket", str(_r[0]))] = _r[1] or ""
        _wids = sorted({str(x["source_id"]) for x in extras
                        if "source_type" in x.keys()
                        and x["source_type"] == "work_order"
                        and "source_id" in x.keys() and x["source_id"]})
        if _wids:
            _ph = ",".join("?" * len(_wids))
            for _r in con.execute(
                    "SELECT w.wo_id, a.unit_no FROM work_orders w "
                    "JOIN assets a ON a.id = w.asset_id "
                    f"WHERE w.wo_id IN ({_ph})", _wids):
                _src_unit[("work_order", str(_r[0]))] = _r[1] or ""
    except Exception:
        _src_unit = {}
    for x in extras:
        _item = x["item"] if "item" in x.keys() and x["item"] else ""
        _ref = _item or _type_default(x["category"])
        if not _ref:
            try:
                _ref = _src_unit.get(
                    (x["source_type"], str(x["source_id"])), "") or ""
            except Exception:
                _ref = ""
        try:
            _line_tax = float(x["tax_amount"] or 0) \
                if "tax_amount" in x.keys() else 0.0
        except (TypeError, ValueError):
            _line_tax = 0.0
        lines.append({
            "kind": x["category"],
            "id": x["uom"],
            "ref": _ref,
            "desc": x["description"] or "",
            "detail": x["description"] or "",
            "when": f"{float(x['qty']):g} {x['uom']} × ${float(x['rate']):,.2f}",
            "amount": float(x["amount"]),
            "unit": x["uom"] or x["category"],
            "qty": float(x["qty"]),
            "rate": float(x["rate"]),
            "stored": True,
            # Taxed-line asterisk: a stored line is taxed when its
            # stored tax_amount is positive (suppressed entirely by
            # the operator tax-exempt click).
            "taxed": (not _op_exempt) and _line_tax > 0,
        })
    # Invoice paperwork (2026-09-27): the PO scan and tax-exempt certificate
    # ride with the invoice — the HTML print embeds images, the PDF pack
    # merges the documents' real pages via _merge_doc_pages.
    job = engine.invoice_job_box(con, invoice_no)
    _jf = (engine.get_option(con, "inv_jobinfo_fields",
                             "po,job,well,location,taxexempt") or "")
    job_fields = [t.strip() for t in _jf.split(",")
                  if t.strip() in JOBINFO_KEYS]
    # Ship To (restyle, tweak round 2): the job site(s) behind the
    # invoice's tickets (and the tickets behind its work orders).
    # Distinct, in ticket order; empty list = no Ship To block prints.
    ship_to = []
    _seen_sites = set()
    try:
        _site_rows = con.execute(
            """SELECT s.* FROM tickets t JOIN sites s ON s.id=t.site_id
               WHERE t.invoice_id=?
               UNION
               SELECT s.* FROM work_orders w
               JOIN tickets t ON t.id=w.ticket_id
               JOIN sites s ON s.id=t.site_id
               WHERE w.invoice_id=?""",
            (inv["id"], inv["id"])).fetchall()
    except Exception:
        _site_rows = []
    for s in _site_rows:
        if s["site_id"] in _seen_sites:
            continue
        _seen_sites.add(s["site_id"])
        def _sc(key, _s=s):
            try:
                return (_s[key] or "") if key in _s.keys() else ""
            except Exception:
                return ""
        ship_to.append({
            "site_name": _sc("site_name"), "operator": _sc("operator"),
            "rig_name": _sc("rig_name"), "street": _sc("street"),
            "street2": _sc("street2"), "city": _sc("city"),
            "state": _sc("state"), "zip": _sc("zip"),
        })
    # Tax rows print only from the totals engine's tax: the distinct
    # name/rate carried on the invoice's own lines (tax comes only
    # from each ticket's explicit jurisdiction — never inferred here).
    tax_info = []
    try:
        for r in con.execute(
                """SELECT DISTINCT tax_name, tax_rate FROM invoice_lines
                   WHERE invoice_id=? AND COALESCE(tax_rate,0) != 0""",
                (inv["id"],)):
            tax_info.append({"name": r["tax_name"] or "",
                             "rate": float(r["tax_rate"] or 0)})
    except Exception:
        tax_info = []
    attachments = invoice_attachments(con, invoice_no)
    if selected is None:
        # Default print set: the typed slots' print-with-invoice
        # toggles govern (invoice_docs.print_with); job-attachment
        # files carry no toggle and default on. An explicit ?docs=
        # selection at print time overrides the toggles.
        docs = [d for d in attachments if d.get("print_with", 1)]
    else:
        _sel = set(selected)
        docs = [d for d in attachments if d.get("aid") in _sel]
    # Stored write-in ("adjustment" on the invoice row, added by the
    # create POST path; absent on older books). engine.invoice_totals
    # NOW folds the write-in — and its tax, when its taxable toggle is
    # set — into tot['total'] / tot['tax'], and exposes it as
    # tot['adjustment']: the printed Grand Total is tot['total']
    # EXACTLY (adding the write-in again here would double-count it).
    # The typed description rides in invoices.adj_label (guarded).
    if tot.get("adjustment") is not None:
        try:
            _adj = float(tot.get("adjustment") or 0)
        except (TypeError, ValueError):
            _adj = 0.0
    else:
        try:
            _adj = float(_rowval(inv, "adjustment") or 0)
        except (TypeError, ValueError):
            _adj = 0.0
    return {"inv": inv, "co": co, "tot": tot, "lines": lines,
            "job": job, "docs": docs, "job_fields": job_fields,
            "ship_to": ship_to, "tax_info": tax_info,
            "attachments": attachments, "adjustment": _adj,
            "adj_label": _adj_label,
            "revised_to": _revto_for(con, "invoice", inv),
            "grand_total": float(tot["total"])}


# ---------------------------------------------------------------------------
# Invoice attachments (print-time selection, invoice round 2026-10-20).
# Every attachment that can ride with an invoice, each with a stable
# "aid": the invoice's own paperwork slots, the catch-all job-attachment
# files saved for the invoice / its tickets, and the job-attachment
# files saved for any credit memo applied to this invoice (credits link
# through collections: kind='credit' rows carry the cm_no they applied).
_EXT_MIME = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".txt": "text/plain",
    ".csv": "text/csv",
}
_JOB_ATT_KIND = {
    "invoice": "Invoice attachment",
    "ticket": "Rental Ticket attachment",
    "credit": "Credit memo attachment",
}


def _doc_entry(title, kind, filename, mime, blob, aid, size_bytes=None):
    return {
        "title": title,
        "kind": kind,
        "filename": filename,
        "mime": mime or "",
        "size_kb": ((size_bytes if size_bytes is not None else len(blob))
                    or 0) / 1024,
        "data_uri": _doc_data_uri(mime or "", blob),
        "blob": blob if (mime or "").startswith("image/") else b"",
        "merge_blob": blob if ((mime or "") == "application/pdf"
                               or (mime or "").startswith("text/")
                               or (mime or "").startswith("image/")) else b"",
        "aid": aid,
    }


def invoice_attachments(con, invoice_no: str) -> list:
    """All attachments available for this invoice's print pack.

    (a) invoice_docs paperwork (po / tax_exempt / shipping / custom —
    the typed Job Info slots, Jason update 8), aid "invdoc:<kind>".
    Each carries its slot's print_with toggle; the pack's default
    print set (selected=None) is the toggled-on documents.
    (b) Job-attachment files in engine.doc_dir() written by
        engine.save_job_attachment ("<ref>_<refid>_<yyyymmdd>_<hhmmss>_"
        "<filename>"): ref "invoice" with this invoice number, and ref
        "ticket" for every ticket linked to the invoice — directly, or
        behind one of its work orders. Aid "job:<stored filename>".
    (c) The same job-attachment files for ref "credit" with each cm_no
        applied to this invoice (collections kind='credit').
    Display filename is the stored trailing name as-is, after the
    timestamp. Mime is sniffed from the bytes via engine.doc_ext_for.
    """
    atts = []
    for _kind in tuple(engine.INV_DOC_KINDS):
        try:
            _got = engine.read_invoice_doc(con, invoice_no, _kind)
        except Exception:
            _got = None
        if not _got:
            continue
        _row, _blob = _got
        _entry = _doc_entry(
            _row["title"], engine.INV_DOC_KINDS.get(_kind, _kind),
            _row["filename"], _row["mime"] or "", _blob,
            f"invdoc:{_kind}", _row["bytes"])
        _entry["print_with"] = 0 if _row.get("print_with") == 0 else 1
        atts.append(_entry)
    pairs = [("invoice", invoice_no)]
    _tids = []
    try:
        for r in con.execute(
                "SELECT ticket_id FROM tickets WHERE invoice_id="
                "(SELECT id FROM invoices WHERE invoice_no=?) "
                "ORDER BY ticket_id", (invoice_no,)):
            if r[0] and r[0] not in _tids:
                _tids.append(r[0])
        for r in con.execute(
                "SELECT t.ticket_id FROM work_orders w "
                "JOIN tickets t ON t.id = w.ticket_id "
                "WHERE w.invoice_id="
                "(SELECT id FROM invoices WHERE invoice_no=?) "
                "ORDER BY t.ticket_id", (invoice_no,)):
            if r[0] and r[0] not in _tids:
                _tids.append(r[0])
    except Exception:
        pass
    pairs += [("ticket", t) for t in _tids]
    try:
        for r in con.execute(
                "SELECT DISTINCT cm.cm_no FROM collections c "
                "JOIN credit_memos cm ON cm.id = c.cm_id "
                "WHERE c.invoice_id="
                "(SELECT id FROM invoices WHERE invoice_no=?) "
                "AND c.kind='credit' ORDER BY cm.cm_no",
                (invoice_no,)):
            pairs.append(("credit", r[0]))
    except Exception:
        pass
    try:
        _ddir = engine.doc_dir()
        _files = sorted(p.name for p in _ddir.iterdir() if p.is_file())
    except Exception:
        _files = []
        _ddir = None
    if _ddir is not None:
        for _ref, _refid in pairs:
            _prefix = f"{_ref}_{_refid}_"
            for _name in _files:
                if not _name.startswith(_prefix):
                    continue
                _parts = _name[len(_prefix):].split("_")
                if len(_parts) < 3 \
                        or not (len(_parts[0]) == 8 and _parts[0].isdigit()) \
                        or not (len(_parts[1]) == 6 and _parts[1].isdigit()):
                    continue
                _display = "_".join(_parts[2:])
                if not _display:
                    continue
                try:
                    _blob = (_ddir / _name).read_bytes()
                except OSError:
                    continue
                try:
                    _ext = engine.doc_ext_for(_blob)
                except Exception:
                    _ext = None
                _mime = _EXT_MIME.get(_ext or "", "")
                if _ext == ".txt" and _display.lower().endswith(".csv"):
                    _mime = "text/csv"
                if not _mime:
                    _mime = _EXT_MIME.get(
                        Path(_display).suffix.lower(), "")
                _entry = _doc_entry(
                    _display,
                    f"{_JOB_ATT_KIND.get(_ref, 'Attachment')} · {_refid}",
                    _display, _mime, _blob, f"job:{_name}")
                _entry["stored"] = _name
                _entry["ref"] = _ref
                _entry["ref_id"] = _refid
                atts.append(_entry)
    return atts


def _company_addr_lines(co):
    """The company's own address as separate lines for the invoice
    header (invoice-only caller — verified: html_invoice/pdf_invoice
    are its only callers): street, street2 only when non-blank, then
    "City, ST ZIP" on one row, then the company phone on its own row
    when non-blank, then the company's general (billing) email on
    its own row when non-blank. Falls back to the legacy single
    address when the split fields are empty."""
    street = (_rowval(co, "addr_street") or "").strip()
    street2 = (_rowval(co, "addr_street2") or "").strip()
    city = (_rowval(co, "addr_city") or "").strip()
    state_zip = " ".join(x for x in ((_rowval(co, "addr_state") or "").strip(),
                                      (_rowval(co, "addr_zip") or "").strip())
                         if x)
    cityline = f"{city}, {state_zip}" if city and state_zip \
        else (city or state_zip)
    lines = [x for x in (street, street2, cityline) if x]
    if not lines:
        legacy = (_rowval(co, "address") or "").strip()
        lines = [legacy] if legacy else []
    phone = (_rowval(co, "phone") or "").strip()
    if phone:
        lines.append(phone)
    email = (_rowval(co, "billing_email") or "").strip()
    if email:
        lines.append(email)
    return lines


def _customer_addr_lines(inv):
    """The customer's address lines under the bold account name:
    bill_to when it differs from the account name, street, street2
    only when non-blank, then city_st. No phone, no email."""
    lines = []

    def _add(v):
        # A line identical to the one directly above it is a data echo
        # (a street typed into the bill-to line), not an address line.
        if v and str(v).strip() and (not lines or lines[-1] != v):
            lines.append(v)

    try:
        if inv["bill_to"] and inv["bill_to"] != inv["account_name"]:
            _add(inv["bill_to"])
    except Exception:
        pass
    for key in ("bill_street", "bill_street2", "city_st"):
        try:
            v = inv[key]
        except Exception:
            v = ""
        _add(v)
    return lines


def _invoice_terms(inv):
    return _rowval(inv, "terms") or _rowval(inv, "cust_terms")


def _pack_adjustment(pack) -> float:
    """The invoice's stored write-in amount, 0 when none is stored.
    The totals engine's tot['adjustment'] is authoritative (it is the
    same stored value, read by the engine); fall back to the pack /
    inv row for packs built by hand in tests."""
    tot = pack.get("tot") or {}
    if tot.get("adjustment") is not None:
        try:
            return float(tot["adjustment"] or 0)
        except (TypeError, ValueError):
            return 0.0
    if pack.get("adjustment") is not None:
        try:
            return float(pack["adjustment"] or 0)
        except (TypeError, ValueError):
            return 0.0
    try:
        return float(_rowval(pack.get("inv"), "adjustment") or 0)
    except (TypeError, ValueError):
        return 0.0


def _pack_adj_label(pack) -> str:
    """The write-in's typed description (invoices.adj_label), '' when
    none was typed or the column predates the migration. User data —
    callers escape it for their medium."""
    if pack.get("adj_label") is not None:
        return str(pack["adj_label"] or "")
    return _rowval(pack.get("inv"), "adj_label") or ""


def _pack_has_taxed(pack) -> bool:
    """True when at least one printed line carries the taxed flag —
    that is what earns the '* Taxes included' footnote."""
    return any(L.get("taxed") for L in (pack.get("lines") or []))


def _pack_grand_total(pack) -> float:
    """Printed Grand Total: tot['total'] EXACTLY — the totals engine
    already folds the stored write-in and its tax into it, so nothing
    is added here."""
    try:
        return float(pack["tot"]["total"])
    except (KeyError, TypeError, ValueError):
        pass
    if pack.get("grand_total") is not None:
        try:
            return float(pack["grand_total"])
        except (TypeError, ValueError):
            pass
    return float(pack["tot"]["total"])


def _invoice_bar_data(pack) -> dict:
    """Data for the header bar under the header zone (round 2 redo):
    LEFT is the invoice's stored free-text bar_text (invoices.bar_text,
    guarded — '' when the column does not exist yet; an empty value
    prints as a blank fill-in box), MIDDLE is the Contact Name from
    the job box data (pack job contact_name), RIGHT is Shipped by
    from the invoice row (blank fill-in when unset). Credit Code,
    AFE and the identification lines are NOT in the bar any more —
    they print only inside the Job Info box when toggled."""
    inv = pack["inv"]
    jb = pack.get("job") or {}
    _ship = (_rowval(inv, "shipped_by") or "").strip()
    # Build 'am' (Jason 2026-10-28): the two preset wordings print
    # as the hauler's own name — the company's dba/name when the
    # company hauls, the customer's name when the customer hauls.
    # Any other stored text is the operator's own words and prints
    # exactly as stored.
    if _ship == "Company Transport":
        _co_name = (_rowval(pack["co"], "dba")
                    or _rowval(pack["co"], "name") or "")
        if _co_name:
            _ship = f"{_co_name} Transport"
    elif _ship == "Customer Transport":
        if inv["account_name"]:
            _ship = f"{inv['account_name']} Transport"
    return {
        "bar_text": (_rowval(inv, "bar_text") or "").strip(),
        "contact_name": (jb.get("contact_name") or "").strip(),
        "shipped_by": _ship,
    }


# Every printable Job Info field, in Jason's fixed print order
# (docs pass, 2026-10-20 — this ruling supersedes the follow-up
# order and the Job Info card order used in tweak round 2):
# PO # always top when selected; Well # / AFE # / Cost Code
# follow PO in that sequence; Job Name and the contact /
# ticket / notes fields sit in the middle; Job Location sits
# directly above Tax-exempt, which is always bottom. Attach
# File is excluded: it is an upload, not a printable line — its
# documents already ride with the invoice as attached paperwork.
JOBINFO_FIELDS = (
    ("po", "PO #"),
    ("well", "Well #"),
    ("afe", "AFE #"),
    ("cost_code", "Cost Code"),
    ("job", "Job Name"),
    ("contact_name", "Contact Name"),
    ("contact_phone", "Phone"),
    ("contact_email", "Email"),
    ("ticket_ref", "Reference Ticket #"),
    ("job_notes", "Notes"),
    ("location", "Job Location"),
    ("taxexempt", "Tax-exempt"),
)
JOBINFO_KEYS = tuple(k for k, _label in JOBINFO_FIELDS)


def _jobinfo_lines(pack):
    """(label, value) pairs for the invoice Job Info box, in
    JOBINFO_FIELDS' fixed print order (see the ruling above it),
    limited to the operator's chosen fields
    (pack['job_fields']). Empty list = no box prints at all.
    Blank-value choice: the original five keep their established
    rendering (PO #/Job Name/Well #/Job Location show "—" when empty,
    Tax-exempt shows Cert on file / No); the fields added in tweak
    round 2 print their label with an empty value — a toggled field
    prints even when blank, as a blank (ruled) line."""
    jb = pack.get("job") or {}
    fields = pack.get("job_fields")
    if fields is None:
        fields = ["po", "job", "well", "location", "taxexempt"]
    # Tax-exempt value (round 2): derived from the exemption SOURCE —
    # "cert" → "Cert on file", "customer"/"operator" → "Yes", "" or
    # missing → "No" — so a taxed invoice never prints "Cert on file"
    # merely because one line was exempt. Fallback for old pack
    # builders with no tax_exempt_source key at all: the old bool.
    if "tax_exempt_source" in jb:
        _src = (jb.get("tax_exempt_source") or "").strip()
        _taxexempt = {"cert": "Cert on file",
                      "customer": "Yes",
                      "operator": "Yes"}.get(_src, "No")
    else:
        _taxexempt = "Cert on file" if jb.get("tax_exempt") else "No"
    vals = {
        "po": jb.get("po") or "—",
        "job": ", ".join(jb.get("jobs") or []) or "—",
        "well": ", ".join(jb.get("wells") or []) or "—",
        "location": ", ".join(jb.get("locations") or []) or "—",
        "taxexempt": _taxexempt,
        "afe": jb.get("afe") or ", ".join(jb.get("afes") or []),
        "contact_name": jb.get("contact_name") or "",
        "contact_phone": jb.get("contact_phone") or "",
        "contact_email": jb.get("contact_email") or "",
        "cost_code": jb.get("cost_code") or "",
        "ticket_ref": jb.get("ticket_ref") or ", ".join(jb.get("ticket_refs") or []),
        "job_notes": _fit_note(jb.get("job_notes")),
    }
    # Print cap (polish round, 2026-10-20): AT MOST 7 pairs print —
    # the first 7 selected fields in JOBINFO_FIELDS' fixed order,
    # however many the operator stored. This one function feeds the
    # PDF box, the HTML box and the editor preview, so the cap
    # lives here only; the factory default (5 fields) is unchanged.
    return [(label, vals[key]) for key, label in JOBINFO_FIELDS
            if key in fields][:7]


def credit_pack(con, cm_no: str) -> dict | None:
    try:
        info = engine.credit_open(con, cm_no)
    except ValueError:
        return None
    cm = con.execute("SELECT * FROM credit_memos WHERE cm_no=?", (cm_no,)).fetchone()
    if not cm:
        return None
    cust = con.execute("SELECT * FROM customers WHERE id=?", (cm["customer_id"],)).fetchone()
    co = _doc_company(con, _rowval(cm, "co_snapshot"))
    lines = []
    for r in con.execute(
        """SELECT c.pay_id, c.pay_date, i.invoice_no, c.amount
           FROM collections c JOIN invoices i ON i.id = c.invoice_id
           WHERE c.cm_id=? AND c.kind='credit' ORDER BY c.pay_date, c.pay_id""",
        (cm["id"],),
    ):
        lines.append({
            "pay_id": r["pay_id"],
            "pay_date": _fmt_date(r["pay_date"]),
            "invoice_no": r["invoice_no"],
            "amount": -float(r["amount"]),
        })
    return {"cm": cm, "info": info, "cust": cust, "co": co, "lines": lines,
            "revised_to": _revto_for(con, "credit", cm),
            "items": engine.credit_lines(con, cm_no)}


def html_credit(pack) -> str:
    cm, info, cust, co, lines = pack["cm"], pack["info"], pack["cust"], pack["co"], pack["lines"]
    items = pack.get("items") if isinstance(pack, dict) else None
    if items is None and isinstance(info, dict):
        items = info.get("lines")
    items = items or []

    def _iget(L, key, default=None):
        try:
            return L.get(key, default)
        except Exception:
            pass
        try:
            return L[key]
        except Exception:
            return default

    def _itaxed(L):
        _t = _iget(L, "taxed")
        if _t is not None:
            return bool(_t)
        _te = _iget(L, "tax_exempt")
        if _te is not None:
            return not bool(_te)
        return False

    def _irow(L):
        _item = str(_iget(L, "item") or "").strip() \
            or str(_iget(L, "category") or "")
        _desc = str(_iget(L, "description") or "")
        _qty = _iget(L, "qty")
        try:
            _qty_txt = f"{float(_qty):g}" if _qty is not None else ""
        except (TypeError, ValueError):
            _qty_txt = str(_qty or "")
        _uom = str(_iget(L, "uom") or "")
        _rate = _iget(L, "rate")
        try:
            _rate_txt = f"${float(_rate):,.2f}" if _rate is not None else ""
        except (TypeError, ValueError):
            _rate_txt = ""
        _amt_v = _iget(L, "amount")
        try:
            _amt_txt = f"${float(_amt_v):,.2f}" if _amt_v is not None else ""
        except (TypeError, ValueError):
            _amt_txt = ""
        if _itaxed(L):
            _amt_txt += " *"
        return (
            f"<tr><td>{html.escape(_item)}</td>"
            f"<td>{html.escape(_desc)}</td>"
            f"<td style='text-align:right'>{html.escape(_qty_txt)}</td>"
            f"<td>{html.escape(_uom)}</td>"
            f"<td style='text-align:right'>{_rate_txt}</td>"
            f"<td style='text-align:right'>{_amt_txt}</td></tr>"
        )

    item_rows = "".join(_irow(L) for L in items) or (
        f"<tr><td colspan=6>{html.escape(cm['reason'] or '')}</td></tr>")
    _any_taxed = any(_itaxed(L) for L in items)
    rows = "".join(
        f"<tr><td>{html.escape(L['pay_date'])}</td>"
        f"<td>{html.escape(L['invoice_no'])}</td>"
        f"<td>{html.escape(L['pay_id'])}</td>"
        f"<td style='text-align:right'>${L['amount']:,.2f}</td></tr>"
        for L in lines
    ) or "<tr><td colspan=4>No invoices applied yet. Remainder is unapplied on this memo.</td></tr>"
    _cust_lines = [x for x in [
        (cust["bill_to"] if cust else "") or "",
        (cust["city_st"] if cust else "") or "",
        (cust["phone"] if cust else "") or "",
    ] if x]
    _header = _form_header_html(
        co, "Credit Memo", cm["cm_no"], _fmt_date(info['cm_date']),
        cust=(cust["account_name"] if cust else cm["customer_id"],
              _cust_lines),
        info_rows=[
            ("Reason", cm['reason'] or ""),
            ("Face", f"−${info['face']:,.2f}"),
            ("Applied", f"−${info['applied']:,.2f}"),
            ("Unapplied", f"−${info['unapplied']:,.2f}"),
        ],
        revto=pack.get("revised_to") or "",
    )
    body = _doc_wrap(_header, f"""
    <table><thead><tr><th>ITEM</th><th>DESCRIPTION</th><th style='text-align:right'>QTY</th><th>UNIT</th><th style='text-align:right'>UNIT PRICE</th><th style='text-align:right'>LINE TOTAL</th></tr></thead><tbody>{item_rows}</tbody></table>
    <table class="tot">
      <tr><td></td><td class="n">Credit total</td><td class="n">−${info['face']:,.2f}</td></tr>
      <tr><td></td><td class="n">Applied</td><td class="n">−${info['applied']:,.2f}</td></tr>
      <tr><td></td><td class="n">Unapplied</td><td class="n">−${info['unapplied']:,.2f}</td></tr>
    </table>
    <table><tr><th>Date</th><th>Applied to invoice</th><th>Event</th><th>Amount</th></tr>{rows}</table>
    <p>{html.escape(_fit_note(cm['notes']))}</p>
    {('<div>* Taxes included</div>' if _any_taxed else '')}
    <div class="sign"><div>{html.escape(_output_by(co))}</div><div>Customer acknowledgement</div></div>
    <footer class="legal">{html.escape(LEGAL)}</footer>
    <div class="fs-mark">FleetSheet</div>
    """)
    actions = _doc_actions(f"/print/credit/{cm['cm_no']}", None, "/credit")
    return _sheet(f"Credit memo {cm['cm_no']}", body, actions)


def html_quote(con, quote_no: str):
    pack = engine.quote_pack(con, quote_no)
    if not pack:
        return None
    q, tot = pack["q"], pack["tot"]
    co = _doc_company(con, _rowval(q, "co_snapshot"))
    rows = "".join(
        f"<tr><td>{html.escape(L['kind'])}</td><td>{html.escape(L['description'])}</td>"
        f"<td>{float(L['qty']):.2f} × ${float(L['rate']):,.2f}</td>"
        f"<td style='text-align:right'>${float(L['amount']):,.2f}</td></tr>"
        for L in pack["lines"]
    ) or "<tr><td colspan=4>No lines.</td></tr>"
    # Build 'v' (Jason 2026-10-25): a quote's numbers are its own —
    # associated Change Orders are separate documents with their
    # own print; they no longer fold into the quote's lines or
    # totals (the quote_pack cos entries are not rendered here).
    _header = _form_header_html(
        co, "Quote", q["quote_no"], _fmt_date(q['quote_date']),
        revto=_revto_for(con, "quote", q),
        cust=(q["account_name"],
              [x for x in [q.get("bill_to") or "",
                           q.get("city_st") or ""] if x]),
        info_rows=[
            ("Job", q.get('job_name') or ""),
            ("PO #", q.get('po') or ""),
            ("Valid until", _fmt_date(q.get('valid_until') or '') or "—"),
            ("Status", q['status'] or ""),
        ],
    )
    body = _doc_wrap(_header, f"""
    <table><tr><th>Type</th><th>Detail</th><th>Qty × rate</th><th>Amount</th></tr>{rows}</table>
    <table class="tot">
      <tr><td></td><td class="n">Quoted</td><td class="n">${tot['quoted']:,.2f}</td></tr>
      <tr><td></td><td class="n">Face</td><td class="n">${tot['face']:,.2f}</td></tr>
    </table>
    <p>{html.escape(_fit_note(q.get('notes')))}</p>
    <p>Estimate only. Invoice follows actual rental days and completed work orders.</p>
    <div class="sign"><div>Yard</div><div>Customer acceptance</div></div>
    <footer class="legal">{html.escape(LEGAL)}</footer>
    """)
    actions = _doc_actions(f"/print/quote/{quote_no}", None,
                           f"/quote/{quote_no}")
    return _sheet(f"Quote {quote_no}", body, actions)


def html_change(con, co_no: str):
    co = con.execute("SELECT * FROM change_orders WHERE co_no=?", (co_no,)).fetchone()
    if not co:
        return None
    # Build 'v' (Jason 2026-10-25): the Change Order prints as what
    # it is — a standalone money document for its customer, with its
    # optional associated document stated as a fact. No quote is
    # involved.
    cust = con.execute("SELECT * FROM customers WHERE id=?",
                       (co["customer_id"],)).fetchone()
    company = _doc_company(con, _rowval(co, "co_snapshot"))
    lines = con.execute("SELECT * FROM change_order_lines WHERE co_id=? ORDER BY line_id", (co["id"],)).fetchall()
    rows = "".join(
        f"<tr><td>{html.escape(L['direction'])}</td><td>{html.escape(L['kind'])}</td>"
        f"<td>{html.escape(L['description'])}</td>"
        f"<td style='text-align:right'>${float(L['amount']):,.2f}</td></tr>"
        for L in lines
    )
    adds = sum(float(L["amount"] or 0) for L in lines if L["direction"] == "add")
    subs = sum(float(L["amount"] or 0) for L in lines if L["direction"] == "subtract")
    _assoc = engine.change_order_assoc(con, co_no)
    _assoc_txt = (f"{engine.DOC_LABELS.get(_assoc[0], _assoc[0])} {_assoc[1]}"
                  if _assoc else "")
    _header = _form_header_html(
        company, "Change Order", co["co_no"], _fmt_date(co['co_date']),
        revto=_revto_for(con, "change", co),
        cust=((cust["account_name"] if cust else ""),
              [x for x in [(cust["bill_to"] or "") if cust else "",
                           (cust["city_st"] or "") if cust else ""] if x]),
        info_rows=[
            ("Reason", co['reason'] or ""),
            ("PO #", co['po'] or ""),
            ("Associated", _assoc_txt),
            ("Status", co['status'] or ""),
        ],
    )
    body = _doc_wrap(_header, f"""
    <table><tr><th>Dir</th><th>Type</th><th>Detail</th><th>Amount</th></tr>{rows}</table>
    <table class="tot">
      <tr><td></td><td class="n">Adds</td><td class="n">${adds:,.2f}</td></tr>
      <tr><td></td><td class="n">Subtracts</td><td class="n">${subs:,.2f}</td></tr>
      <tr><td></td><td class="n">Total</td><td class="n">${adds - subs:,.2f}</td></tr>
    </table>
    <p>{html.escape(_fit_note(co['notes']))}</p>
    <p>A standalone document, settled on its own. An associated document settles separately.</p>
    <div class="sign"><div>Yard</div><div>Customer acknowledgement</div></div>
    <footer class="legal">{html.escape(LEGAL)}</footer>
    """)
    actions = _doc_actions(f"/print/change/{co_no}", None, "/changes")
    return _sheet(f"Change order {co_no}", body, actions)


def html_petty(con) -> str:
    book = engine.petty_book(con)
    co = _company_for_print(con)
    rows = "".join(
        f"<tr><td>{html.escape(_fmt_date(r['txn_date']))}</td><td>{html.escape(r['pc_id'])}</td>"
        f"<td>{html.escape(r['category'])}</td><td>{html.escape(r['payee'])}</td>"
        f"<td style='text-align:right'>${r['signed']:,.2f}</td>"
        f"<td style='text-align:right'>{('$' + format(r['running'], ',.2f')) if r['running'] is not None else '—'}</td></tr>"
        for r in book["rows"]
    ) or "<tr><td colspan=6>Empty box.</td></tr>"
    _header = _form_header_html(
        co, "Petty Cash", "Register",
        _fmt_date(datetime.now().strftime("%Y-%m-%d")),
        info_rows=[
            ("In the box", f"${book['balance']:,.2f}"),
            ("Target float", f"${book['target']:,.2f}"),
            ("To replenish", f"${book['to_replenish']:,.2f}"),
        ],
    )
    body = _doc_wrap(_header, f"""
    <table><tr><th>Date</th><th>ID</th><th>Category</th><th>Payee</th><th>Amount</th><th>Running</th></tr>{rows}</table>
    <table class="tot">
      <tr><td></td><td class="n">Balance</td><td class="n">${book['balance']:,.2f}</td></tr>
      <tr><td></td><td class="n">To replenish</td><td class="n">${book['to_replenish']:,.2f}</td></tr>
    </table>
    <footer class="legal">{html.escape(LEGAL)}</footer>
    """)
    actions = _doc_actions("/print/petty", None, "/petty")
    return _sheet("Petty cash register", body, actions)


def html_done(con, period: str = "week") -> str:
    """Printable done-log: explicit completions + payments collected, this
    today/week/year. Answers 'what did I do this week?' on paper."""
    if period not in ("today", "week", "year"):
        period = "week"
    start, end, label = engine.done_period(con, period)
    co = _company_for_print(con)
    tasks = engine.done_tasks(con, start, end)
    pays = engine.done_payments(con, start, end)
    trows = "".join(
        f"<tr><td>{html.escape(_fmt_date((t['done_at'] or '')[:16]))}</td>"
        f"<td>{html.escape(t['text'])}</td>"
        f"<td>{html.escape(t['tier'])}</td>"
        f"<td>{html.escape(t['done_by'] or '—')}</td></tr>"
        for t in tasks) or "<tr><td colspan=4>Nothing logged.</td></tr>"
    prows = "".join(
        f"<tr><td>{html.escape(_fmt_date((p['pay_date'] or '')[:16]))}</td>"
        f"<td>{html.escape(p['invoice_no'])}</td>"
        f"<td>{html.escape(p['account_name'])}</td>"
        f"<td style='text-align:right'>${p['amount']:,.2f}</td>"
        f"<td>{html.escape(p['clerk'] or '—')}</td></tr>"
        for p in pays) or "<tr><td colspan=5>No payments collected.</td></tr>"
    ptotal = sum(p["amount"] for p in pays)
    _header = _form_header_html(
        co, "Done Log", label, _fmt_date(end),
        info_rows=[
            ("Period", f"{_fmt_date(start)} to {_fmt_date(end)}"),
            ("Completed", str(len(tasks))),
            ("Payments", f"{len(pays)} — ${ptotal:,.2f}"),
        ],
    )
    body = _doc_wrap(_header, f"""
    <h3>Completed ({len(tasks)})</h3>
    <table><tr><th>When</th><th>Task</th><th>Tier</th><th>By</th></tr>{trows}</table>
    <h3>Payments collected ({len(pays)}) — ${ptotal:,.2f}</h3>
    <table><tr><th>When</th><th>Invoice</th><th>Customer</th>
    <th style='text-align:right'>Amount</th><th>By</th></tr>{prows}</table>
    <div class="sign"><div>{html.escape(_output_by(co))}</div><div>Received</div></div>
    <footer class="legal">{html.escape(LEGAL)}</footer>
    """)
    actions = _doc_actions(f"/print/done?period={period}", None,
                           f"/done?period={period}")
    return _sheet(f"Done log — {label}", body, actions)


def ticket_pack(con, ticket_id: str) -> dict | None:
    # Site-less tickets print too (Jason 2026-10-24): LEFT JOIN — the
    # sheet builders already state a missing site name as blank.
    t = con.execute(
        """SELECT t.*, c.account_name, c.bill_to, c.phone, c.city_st,
                  a.unit_no, a.description, a.serial_no,
                  s.site_name, s.operator, s.rig_name
           FROM tickets t
           JOIN customers c ON c.id = t.customer_id
           JOIN assets a ON a.id = t.asset_id
           LEFT JOIN sites s ON s.id = t.site_id
           WHERE t.ticket_id=?""",
        (ticket_id,),
    ).fetchone()
    if not t:
        return None
    co = _doc_company(con, _rowval(t, "co_snapshot"))
    m = engine.ticket_money(con, ticket_id)
    return {"t": t, "co": co, "m": m,
            "revised_to": _revto_for(con, "ticket", t)}


def _doc_actions(html_path, pdf_path, back_href, back_label="Back"):
    """The print-page action bar (Jason 2026-10-24, 'm' look-see item
    3c — supersedes the 2026-10-18 two-button bar): ONE Print button
    opening the standard three-choice menu — Print to Screen (this
    sheet), PRINT (browser dialog), Print to Location (files the
    document, PDF where one exists else this HTML, into the
    operator's print folder via POST /print/save) — plus Back. The
    standalone PRINT and standalone Print to Location buttons are
    gone: one Print per surface, three choices behind it."""
    doc = pdf_path or html_path
    return (f'<details class="pmenu"><summary>Print</summary>'
            f'<span class="popts">'
            f'<a href="{html.escape(html_path, quote=True)}">Print to Screen</a>'
            f'<button type="button" onclick="window.print()">PRINT</button>'
            f'<button type="button" data-doc="{html.escape(doc, quote=True)}" onclick="fsSaveLoc(this)">Print to Location</button>'
            f'</span></details>'
            f'<a href="{html.escape(back_href, quote=True)}">{html.escape(back_label)}</a>'
            f'<span class="pstat"></span>')


def _sheet(title, body, actions=""):
    return f"""<!doctype html><html><head><meta charset=utf-8>
<title>{html.escape(title)}</title>
<style>
:root {{ --navy:#1B2A4A; --gold:#E8B923; }}
body {{ margin:0; font:13px/1.4 Calibri,Segoe UI,sans-serif; color:#1a1a1a; }}
.bar {{ background:#1B2A4A; color:#fff; padding:10px 16px; display:flex; justify-content:space-between; align-items:center; }}
.bar a, .bar button {{ color:#fff; margin-left:12px; background:none; border:1px solid #fff; padding:6px 10px; text-decoration:none; cursor:pointer; font:inherit; }}
.page {{ max-width:800px; margin:20px auto; padding:0 16px 40px; }}
.head {{ display:flex; justify-content:space-between; gap:24px; border-bottom:3px solid #1B2A4A; padding-bottom:12px; }}
.head img {{ height:56px; }}
.cust {{ border:1px solid #c5cdd6; padding:10px; min-width:240px; }}
.cust span {{ display:block; font-size:10px; color:#5C6B7A; text-transform:uppercase; }}
h1 {{ color:#1B2A4A; font-size:20px; margin:16px 0 8px; }}
.revto {{ font-weight:700; font-size:15px; margin:0 0 8px; text-align:center; }}
table {{ width:100%; border-collapse:collapse; margin:12px 0; }}
th {{ background:#1B2A4A; color:#fff; text-align:left; padding:6px 8px; font-size:11px; }}
td {{ border-bottom:1px solid #e5e7eb; padding:6px 8px; vertical-align:top; }}
.tot td {{ border:0; }}
.tot .n {{ text-align:right; font-weight:700; }}
.sign {{ display:grid; grid-template-columns:1fr 1fr; gap:32px; margin-top:36px; }}
.sign div {{ border-top:1px solid #1a1a1a; padding-top:6px; font-size:11px; color:#5C6B7A; }}
footer.legal {{ margin-top:28px; font-size:9px; color:#5C6B7A; border-top:1px solid #d0d5dd; padding-top:8px; }}
.fs-mark {{ text-align:right; font-size:9px; letter-spacing:.12em; color:#1B2A4A; opacity:.28; margin-top:4px; }}
.docwrap{{width:100%;border-collapse:collapse}}
.docwrap>thead>tr>td,.docwrap>tbody>tr>td{{border:0;padding:0}}
.fh-zone{{display:flex;justify-content:space-between;gap:24px;align-items:flex-start}}
.fh-left{{text-align:left}}
.fh-right{{text-align:right}}
.fh-label{{font-size:12px;line-height:20px}}
.fh-co-name{{font-weight:700;color:#1B2A4A;font-size:15px}}
.fh-addr{{font-size:12px}}
.fh-block{{font-size:12px;margin-top:10px}}
.fh-info{{margin-top:10px;text-align:right}}
/* Print page margins match the invoice's HTML treatment (cleanup
   round): @page letter with a uniform 0.4in margin, and the .page
   print padding zeroed exactly as the invoice's print rule does, so
   the rendered content starts at the 0.4in page margin. Screen
   styles above are untouched. */
@page {{ size: letter; margin: 0.4in; }}
@media print {{
  .bar {{ display:none; }}
  .page {{ margin:0; max-width:none; padding:0; }}
  a {{ color:#000; text-decoration:none; }}
}}
.bar .pstat {{ color:#ffd766; border:0; margin-left:12px; font-size:12px; }}
.bar .pmenu {{ display:inline-block; position:relative; margin-left:12px; }}
.bar .pmenu summary {{ color:#fff; border:1px solid #fff; padding:6px 10px; cursor:pointer; list-style:none; display:inline-block; }}
.bar .pmenu summary::-webkit-details-marker {{ display:none; }}
.bar .popts {{ position:absolute; left:0; top:calc(100% + 6px); background:#fff; border:1px solid #c5cdd6; border-radius:8px; box-shadow:0 8px 24px rgba(0,0,0,.25); padding:6px; z-index:50; min-width:200px; }}
.bar .popts a, .bar .popts button {{ display:block; width:100%; box-sizing:border-box; color:#1a1a1a; background:none; border:0; margin:0; padding:7px 10px; text-align:left; text-decoration:none; cursor:pointer; font:inherit; }}
.bar .popts a:hover, .bar .popts button:hover {{ background:#eef1f4; }}
</style></head>
<body>
<div class="bar"><span>{actions}</span></div>
<div class="page">{body}</div>
<script>
function fsSaveLoc(btn){{
  var d = btn.closest('details'); if (d) d.removeAttribute('open');
  var st = document.querySelector('.bar .pstat');
  if (st) st.textContent = 'Saving\u2026';
  var body = new URLSearchParams(); body.set('doc', btn.getAttribute('data-doc'));
  fetch('/print/save', {{method:'POST', body: body}}).then(function(r){{ return r.json(); }})
    .then(function(j){{ if (st) st.textContent = j.ok ? ('Saved to ' + j.path) : ('Could not save: ' + (j.error || 'error')); }})
    .catch(function(e){{ if (st) st.textContent = 'Could not save.'; }});
}}
document.addEventListener('click', function(e){{
  document.querySelectorAll('details.pmenu[open]').forEach(function(d){{
    if (!d.contains(e.target)) d.removeAttribute('open');
  }});
}});
if (/[?&]autoprint=1/.test(location.search)) {{
  window.addEventListener('load', function(){{ setTimeout(function(){{ window.print(); }}, 60); }});
}}
</script>
</body></html>"""


def _rowval(row, key):
    """Row value by key, '' when the column is absent (older DBs lack
    the split-address / physical-address columns)."""
    try:
        return (row[key] or "") if row is not None and key in row.keys() else ""
    except Exception:
        return ""


def _company_for_print(con):
    """The company row for print (Batch 3 #5, following the _output_by
    pattern): documents read the operator-picked main phone — the
    phone list is the one store of truth. When the list exists, its
    main (main_company_phone) replaces the legacy company.phone
    column; when no phone list exists, the legacy column stands."""
    row = con.execute("SELECT * FROM company WHERE id=1").fetchone()
    if row is None:
        return row
    try:
        main = engine.main_company_phone(con)
    except Exception:
        main = None
    if main:
        num = (main["number"] or "").strip()
        if num:
            d = dict(row)
            d["phone"] = num
            return d
    return row


def _doc_company(con, snapshot):
    """A document's company identity for print (build 'ab',
    redirect #3 — Jason: "reprint is fixed as originally issued"):
    the snapshot frozen on the document at its posting, never the
    live Company record. Documents issued before the snapshot
    existed carry none — they print from the live record (the
    legacy behavior, named in PHASEAB-REPORT)."""
    if snapshot:
        try:
            import json as _json
            d = _json.loads(snapshot)
            if isinstance(d, dict) and d:
                return d
        except Exception:
            pass
    return _company_for_print(con)


def _output_by(co) -> str:
    """Printed attribution (Batch 3 #13): 'Output by:' + the desk
    identity — the company DBA when filled, else the legal name (the
    same identity the desk session stamps in-app as 'Input by:')."""
    name = _rowval(co, "dba") or _rowval(co, "name")
    return f"Output by: {name}" if name else "Output by:"


def _company_blocks(co):
    """(remit_lines, distribution_lines) for the invoice top band.
    Remit = the company's billing address (split addr_* columns, else
    the legacy single address). Distribution = the company's physical
    address (phys_* columns — the only second address the company
    record has); empty list when no physical address is on file, and
    the block then does not render at all. County is tax-only and
    never prints as mailing (migration note, 2026-10-06)."""
    remit = []
    street = " ".join(x for x in (_rowval(co, "addr_street"),
                                  _rowval(co, "addr_street2")) if x)
    cityline = ", ".join(x for x in (
        _rowval(co, "addr_city"),
        " ".join(y for y in (_rowval(co, "addr_state"),
                              _rowval(co, "addr_zip")) if y)) if x)
    if street or cityline:
        remit = [x for x in (street, cityline) if x]
    elif _rowval(co, "address"):
        remit = [_rowval(co, "address")]
    dist = []
    dstreet = " ".join(x for x in (_rowval(co, "phys_street"),
                                    _rowval(co, "phys_street2")) if x)
    dcityline = ", ".join(x for x in (
        _rowval(co, "phys_city"),
        " ".join(y for y in (_rowval(co, "phys_state"),
                              _rowval(co, "phys_zip")) if y)) if x)
    if dstreet or dcityline:
        dist = [x for x in (dstreet, dcityline) if x]
    return remit, dist


def _tax_rate_text(pack):
    """'Name 8.25%' style text from the pack's tax_info, or ''."""
    bits = []
    for t in pack.get("tax_info") or []:
        pct = ("%f" % (float(t.get("rate") or 0) * 100)).rstrip("0").rstrip(".")
        bits.append(f"{t.get('name') or 'Tax'} {pct}%".strip())
    return ", ".join(bits)


def _inv_totals_rows_html(pack):
    """The right-hand totals column (invoice round, 2026-10-20; order
    refined in Part A2, round 2): (1) the write-in row FIRST — only
    when filled (a label or a non-zero amount); a completely empty
    write-in is OMITTED entirely (no box, no underline, no blank
    bordered cell), and a filled one renders exactly like the
    Subtotal row (plain label cell + plain amount cell); (2)
    Subtotal = the lines subtotal PLUS the write-in; (3) Tax Rate
    only when rate text exists, then Sales Tax ALWAYS (even $0.00);
    (4) Grand Total = tot['total'] exactly — the engine already
    folds in the write-in and its tax. No payment/credit/balance
    rows and no shipping row print."""
    tot = pack["tot"]
    _adj = _pack_adjustment(pack)
    _label = _pack_adj_label(pack)
    rows = []
    if _label or _adj != 0:
        rows.append(
            f"<tr><td class='n'>{html.escape(_label)}</td>"
            f"<td class='n'>${_adj:,.2f}</td></tr>")
    rows.append(
        f"<tr><td class='n'>Subtotal</td>"
        f"<td class='n'>${float(tot['subtotal']) + _adj:,.2f}</td></tr>")
    rate_txt = _tax_rate_text(pack)
    if rate_txt:
        rows.append(
            f"<tr><td class='n'>Tax Rate</td><td class='n'>{html.escape(rate_txt)}</td></tr>")
    rows.append(
        f"<tr><td class='n'>Sales Tax</td>"
        f"<td class='n'>${float(tot.get('tax') or 0):,.2f}</td></tr>")
    rows.append(
        f"<tr><td class='n'>Grand Total</td>"
        f"<td class='n'>${_pack_grand_total(pack):,.2f}</td></tr>")
    return ("<table class='tot' style='margin:0;min-width:230px'>"
            + "".join(rows) + "</table>")


_INVOICE_CSS = """<style>
@page { size: letter; margin: 0.4in;
  @bottom-center { content: "Page " counter(page) " of " counter(pages);
                   font-size: 9px; color: #5C6B7A; } }
.inv-wrap { padding: 0; display: flex; flex-direction: column; }
.revto { font-weight:700; font-size:15px; margin:0 0 8px; text-align:center; }
.inv-foot { margin-top: 28px; font-size: 10px; color: #5C6B7A;
            border-top: 1px solid #d0d5dd; padding-top: 8px;
            background: #fff; }
@media print {
  .noprint { display: none !important; }
  .page { margin: 0 !important; max-width: none !important; padding: 0 !important; }
  .inv-wrap { padding-bottom: 0.9in; min-height: 9.15in; }
  .inv-foot { position: fixed; bottom: 0; left: 0; right: 0; margin-top: 0; }
  .inv-tfoot-space td { height: 1.05in; }
}
</style>"""


def _invoice_selection_panel_html(pack) -> str:
    """Screen-only attachment picker (never prints): one checkbox per
    available attachment, checked when it is in the current selection.
    Submitting reloads this print view with ?docs=…; the PDF download
    button carries the same selection."""
    atts = pack.get("attachments")
    if atts is None:
        atts = pack.get("docs") or []
    if not atts:
        return ""
    inv = pack["inv"]
    _sel = {d.get("aid") for d in (pack.get("docs") or []) if d.get("aid")}
    _boxes = []
    for d in atts:
        _aid = d.get("aid") or ""
        _checked = " checked" if _aid in _sel else ""
        _label_bits = [x for x in dict.fromkeys(
            [d.get("title") or "", d.get("kind") or ""]) if x]
        _label = " · ".join(_label_bits)
        if d.get("filename") and d["filename"] not in _label:
            _label = f"{_label} · {d['filename']}" if _label \
                else d["filename"]
        _boxes.append(
            f"<label style='display:block;margin:2px 0'>"
            f"<input type=checkbox name=docs "
            f"value=\"{html.escape(_aid, quote=True)}\"{_checked}> "
            f"{html.escape(_label)}</label>")
    return f"""
    <div class="noprint" style="border:1px solid #c5cdd6;padding:10px 14px;margin:0 0 14px;background:#f7f8fa">
      <form method="get" action="/print/invoice/{html.escape(inv['invoice_no'], quote=True)}">
        <b>Attachments to include</b>
        {''.join(_boxes)}
        <button type="submit">Update print view</button>
      </form>
    </div>"""


def _invoice_signature_html(pack) -> str:
    """Plain signature / notes block under the lines (not boxed):
    Print Name is a BLANK write-in line (the receiver prints their
    name by hand — it is never pre-filled; the contact name lives
    only in the header bar), a blank Sign Name line with a short
    Date line, and a long blank Notes line."""
    _line = ("display:inline-block;border-bottom:1px solid #1a1a1a;"
             "min-height:1em;vertical-align:bottom")
    # Template round, coordinator fix: each row is a flex row and
    # the write-in spans flex to fill it — the fixed 300/400px
    # min-widths wrapped onto their own lines under narrower flex
    # sizing (WeasyPrint proof), detaching line from label. Flexed
    # spans keep the lines long (>= the old fixed widths wherever
    # the block is at its intended size) and always attached.
    _row = "display:flex;align-items:flex-end;gap:8px"
    return f"""
      <div style="font-size:12px;line-height:2">
        <div style="{_row}"><span>Print Name</span> <span style="{_line};flex:1 1 0">&nbsp;</span></div>
        <div style="{_row}"><span>Sign Name</span> <span style="{_line};flex:1.8 1 0">&nbsp;</span>
             <span>Date</span> <span style="{_line};flex:1 1 0">&nbsp;</span></div>
        <div style="{_row}"><span>Notes</span> <span style="{_line};flex:1 1 0">&nbsp;</span></div>
      </div>"""


def _form_header_html(co, doc_label, doc_no, doc_date, cust=None,
                      subject=None, info_rows=None, revto="") -> str:
    """Shared form header (template round): mirrors the invoice
    header zone for every non-invoice form. LEFT column: a
    "Remit To:" label (12px, blank line under it, like the invoice's
    label divs), the company name (15px, 700, navy) and the company
    address lines (12px) from _company_addr_lines, then the
    customer block (cust = (name, [lines]) under "Billing Address:")
    or, when there is no customer, the subject block
    (subject = (caption, name, [lines])) in the same position.
    RIGHT column (text-align:right): "{doc_label}: <b 20px>{doc_no}</b>"
    (just the bold label when doc_no is empty), then
    "Date: <b>{doc_date}</b>" (doc_date arrives PRE-FORMATTED —
    callers format with _fmt_date), then the info box with exactly
    _jobinfo_box_html's styling when info_rows is given. No
    horizontal rule / border-bottom under the zone."""
    co_name = _rowval(co, "name")
    if not co_name and co is not None:
        try:
            co_name = co["name"] or ""
        except Exception:
            co_name = ""
    co_addr_html = "<br>".join(
        html.escape(str(x)) for x in _company_addr_lines(co) if x)
    second = ""
    _blk = None
    if cust is not None:
        _blk = ("Billing Address:", cust[0], list(cust[1] or []))
    elif subject is not None:
        _blk = (subject[0], subject[1], list(subject[2] or []))
    if _blk is not None:
        _cap, _nm, _lns = _blk
        _lns_html = "<br>".join(
            html.escape(str(x)) for x in _lns if x and str(x).strip())
        _nm_html = (f"<b>{html.escape(str(_nm or ''))}</b>"
                    + (f"<br>{_lns_html}" if _lns_html else ""))
        second = (f"<div class=\"fh-label\" style=\"font-size:12px;line-height:20px\">"
                  f"{html.escape(str(_cap))}<br>&nbsp;</div>"
                  f"<div class=\"fh-block\" style=\"font-size:12px\">{_nm_html}</div>")
    if doc_no:
        _title_html = (f"{html.escape(str(doc_label))}: "
                       f"<b style=\"font-size:20px\">{html.escape(str(doc_no))}</b>")
    else:
        _title_html = f"<b style=\"font-size:20px\">{html.escape(str(doc_label))}</b>"
    _date_html = (f"<div class=\"fh-date\">Date: "
                  f"<b>{html.escape(str(doc_date or ''))}</b></div>")
    _info_html = ""
    if info_rows:
        _rows = "".join(
            f"<div>{html.escape(str(label))} <b>{html.escape(str(value))}</b></div>"
            for label, value in info_rows)
        _info_html = f"""
        <div class="fh-info" style="margin-top:10px;text-align:right">
        <div style="display:inline-block;border:1px solid #1B2A4A;border-radius:8px;padding:10px 14px;
                    min-width:230px;font-size:14px;text-align:left">
          {_rows}
        </div></div>"""
    return f"""
    {(f'<div class="revto">*Revised to: {html.escape(str(revto))}</div>' if revto else '')}
    <div class="fh-zone" style="display:flex;justify-content:space-between;gap:24px;align-items:flex-start">
      <div class="fh-left">
        <div class="fh-label" style="font-size:12px;line-height:20px">Remit To:<br>&nbsp;</div>
        <div class="fh-co-name" style="font-weight:700;color:#1B2A4A;font-size:15px">{html.escape(str(co_name or ''))}</div>
        <div class="fh-addr" style="font-size:12px">{co_addr_html}</div>
        {second}
      </div>
      <div class="fh-right" style="text-align:right">
        <div class="fh-docno">{_title_html}</div>
        {_date_html}
        {_info_html}
      </div>
    </div>"""


def _fit_note(t, limit=160):
    """Notes doctrine (Jason 2026-10-24): print shows what fits the
    form — a long note prints truncated with an ellipsis, never
    spilling the layout. Raw text (callers escape); the full text
    lives in the app pop-up."""
    t = str(t or "")
    return t[:limit] + ("…" if len(t) > limit else "")


def _form_bar_html(left_text, contact_name, shipped_by) -> str:
    """The bordered three-box bar (template round): the invoice
    header bar parameterized — LEFT is left_text (the text when
    present, else an empty blank fill-in area), MIDDLE is Contact
    Name (pre-printed when given, else a blank fill-in line),
    RIGHT is Shipped by (value or blank fill-in). Same markup and
    styles as the invoice bar: boxed cells, flex:1 1 0 thirds,
    bold 8px uppercase captions."""
    _fill = ("display:inline-block;min-width:74px;"
             "border-bottom:1px solid #1a1a1a")
    _lab = ("font-size:8px;color:#5C6B7A;text-transform:uppercase;"
            "letter-spacing:.04em;font-weight:700")
    _box = "border:1px solid #1B2A4A;padding:0 6px"

    def _field(label, value):
        _val = (f"<b>{html.escape(value)}</b>" if value
                else f"<span style='{_fill}'>&nbsp;</span>")
        return (f"<div><span style='{_lab}'>{label}</span><br>{_val}</div>")

    # Build 'am' (Jason 2026-10-28): the left cell carries the same
    # two-line anatomy as its siblings (caption line over value
    # line) whether or not it holds text. An empty left cell stood
    # as a bare &nbsp; — shorter than the Contact/Transport cells
    # beside it, a misshaped box. Empty prints the fill-in line.
    _left_html = (
        f"<div><span style='{_lab}'>&nbsp;</span><br>"
        + (f"<b>{html.escape(left_text)}</b>" if left_text
           else f"<span style='{_fill}'>&nbsp;</span>")
        + "</div>")
    return f"""
    <div style="display:flex;flex-wrap:wrap;gap:2px;margin:0 0 1px;font-size:10px;line-height:0.95;align-items:flex-start">
      <div style="flex:1 1 0;min-width:180px;{_box}">{_left_html}</div>
      <div style="flex:1 1 0;{_box}">{_field("Contact Name", contact_name)}</div>
      <div style="flex:1 1 0;{_box}">{_field("Transport", shipped_by)}</div>
    </div>"""


def _doc_wrap(header_html, body_html) -> str:
    """Wrap a form in the repeating-header table: the header rides
    in the <thead> (printed pages repeat it — the same mechanism
    the invoice HTML uses), everything else in the <tbody>."""
    return (f'<table class="docwrap"><thead><tr><td>{header_html}</td></tr></thead>'
            f'<tbody><tr><td>{body_html}</td></tr></tbody></table>')


def _invoice_bar_html(pack) -> str:
    """The bordered header bar directly under the header zone,
    above the line items (round 2 redo). Three boxes in one compact
    row: LEFT is the stored bar_text (the text when present, else an
    empty blank fill-in area), MIDDLE is Contact Name (pre-printed
    when the job box has one, else a blank fill-in line), RIGHT is
    Shipped by (value or blank fill-in). Small-caps labels and the
    thin border of the round-3 bar; heights stay tight. Polish round
    (2026-10-20): squeezed to match the PDF bar (tighter font /
    line-height / margins) and each of the three sections carries
    its OWN border, so the bar reads as three distinct boxes.
    Template round: delegates to _form_bar_html with the values
    from _invoice_bar_data — output identical to before."""
    bar = _invoice_bar_data(pack)
    return _form_bar_html(bar["bar_text"], bar["contact_name"],
                          bar["shipped_by"])


# ------------------------------------------------------------------
# Invoice header address placement (standing).
# On the printed invoice the COMPANY block is the RETURN address,
# at the top of the header zone, and the CUSTOMER block is the
# MAILING address below it, indented. Both blocks sit at fixed
# page coordinates (inches from the page's top-left corner);
# neither rides the flow, and the placement does not change at
# print time. Provenance: set in Invoice Round 2 (Jason
# 2026-10-20) so a tri-folded invoice aligns with the windows of
# a #10 double-window business envelope (manufacturer geometry
# config W-9914: top window 3.5 x 0.875 at 1/2 Left, 2-5/8 from
# Bottom; bottom window 4 x 1.125 at 3/4 Left, 1 from Bottom).
# Build 'o' (Jason 2026-10-24): the envelope selection system --
# the on-screen picker, the preset switching, and the plain-paper
# envelope print -- is removed. The placement stands as the
# header layout. mail_cap caps the mailing block's text width so
# it can never reach the right column.
ADDRESS_PLACEMENT = {
    "ret_left": 0.62, "ret_top": 0.70, "ret_cap": 3.2,
    "mail_left": 0.90, "mail_top": 2.08, "mail_cap": 3.35,
}



def html_invoice(pack) -> str:
    # Invoice round layout (2026-10-20, Jason's dictation; identical
    # anatomy in pdf_invoice): small margins; the company block sits
    # at the top of the header zone (the return address) and the
    # customer block below it (the mailing address), at the fixed
    # placement of ADDRESS_PLACEMENT, Date /
    # Invoice # and the Job Info box on the right; the six-column
    # lines table directly below the header; signature/notes at
    # bottom-left beside the totals; and a Terms + Page footer with
    # the Terms & Conditions paragraph on every page. No title word,
    # no status, no Ship To. (Round 2: the company block gained the
    # company phone + general email rows — see _company_addr_lines;
    # the customer block still prints no phone/email.)
    # Polish round (2026-10-20): the header zone, the bar and the
    # column-header row ride INSIDE the lines table's <thead> (the
    # zone in one borderless colspan cell), so a print engine that
    # repeats <thead> on table page breaks (WeasyPrint and browsers
    # do) repeats the full header on every printed page and the
    # flow below it is reserved by the table itself — the same
    # repetition the PDF path builds with its 'Later' template.
    # On screen the thead renders once, at the top, as before. The
    # table's one-row <tfoot> is a print-only spacer (see
    # _INVOICE_CSS): a repeating tfoot reserves the fixed Terms
    # footer's zone at the bottom of every table fragment, so a
    # full page of lines can no longer run under that footer
    # (WeasyPrint proof renders showed the last rows of a full
    # page under the footer text without it).
    # Built inline — _head/_sheet stay untouched for the other docs.
    inv, co, tot, lines = pack["inv"], pack["co"], pack["tot"], pack["lines"]
    co_addr_html = "<br>".join(
        html.escape(x) for x in _company_addr_lines(co) if x)
    bill_html = "<br>".join(
        html.escape(x) for x in _customer_addr_lines(inv) if x)
    bill_block = (f"<b>{html.escape(inv['account_name'])}</b>"
                  + (f"<br>{bill_html}" if bill_html else ""))
    # Header address placement (standing): the company block is the
    # return address (top of the zone) and the customer block the
    # mailing address below it; coordinates are relative to the
    # @page content box, whose origin sits 0.4in from the page edges.
    _envp = ADDRESS_PLACEMENT
    _env_ret_l = f"{_envp['ret_left'] - 0.4:.2f}"
    _env_ret_t = f"{_envp['ret_top'] - 0.4:.2f}"
    _env_mail_l = f"{_envp['mail_left'] - 0.4:.2f}"
    _env_mail_t = f"{_envp['mail_top'] - 0.4:.2f}"
    _env_mail_w = f"{_envp['mail_cap']:.2f}"
    _env_zone_h = f"{_envp['mail_top'] - 0.4 + 0.9:.2f}"
    # Follow-up labels (2026-10-20): "Remit To:" / "Billing Address:"
    # sit in SEPARATE absolute divs stacked above their blocks, so
    # the blocks' own window coordinates never move. Each label div
    # holds the label plus a blank line (~0.42in at 12px), so its top
    # sits that far above the block top it labels.
    _env_ret_label_t = f"{_envp['ret_top'] - 0.4 - 0.42:.2f}"
    _env_mail_label_t = f"{_envp['mail_top'] - 0.4 - 0.42:.2f}"
    # Lines table: ITEM | DESCRIPTION | QTY | UNIT | UNIT PRICE |
    # LINE TOTAL — the description cell is the desc text only, and
    # there are exactly len(lines) body rows (no filler rows).
    def _line_row(L):
        qty = L.get("qty")
        # QTY format verified (round 2): f"{float(qty):g}" — 5 prints
        # "5", 5.57 prints "5.57". This and the pdf_invoice loop are
        # the only qty formatters in the invoice paths.
        qty_txt = f"{float(qty):g}" if qty is not None else ""
        price = (f"${float(L['rate']):,.2f}"
                 if L.get("rate") is not None else "")
        _amt = f"${L['amount']:,.2f}" + (" *" if L.get("taxed") else "")
        return (f"<tr><td>{html.escape(str(L.get('ref') or ''))}</td>"
                f"<td>{html.escape(str(L.get('desc') or ''))}</td>"
                f"<td style='text-align:right'>{qty_txt}</td>"
                f"<td>{html.escape(str(L.get('unit') or ''))}</td>"
                f"<td style='text-align:right'>{price}</td>"
                f"<td style='text-align:right'>{_amt}</td></tr>")
    rows = "".join(_line_row(L) for L in lines)
    if not lines:
        rows = "<tr><td colspan=6>No lines.</td></tr>"
    body = f"""
    {_INVOICE_CSS}
    <div class="inv-wrap">
    {_invoice_selection_panel_html(pack)}
    {(f'<div class="revto">*Revised to: {html.escape(str(pack.get("revised_to")))}</div>' if pack.get("revised_to") else '')}
    <table style="margin-top:0"><thead>
    <tr><td colspan="6" style="border:0;padding:0">
    <div style="position:relative;min-height:{_env_zone_h}in;padding-bottom:2px">
      <div style="position:absolute;left:{_env_ret_l}in;top:{_env_ret_label_t}in;font-size:12px;line-height:20px">Remit To:<br>&nbsp;</div>
      <div style="position:absolute;left:{_env_ret_l}in;top:{_env_ret_t}in">
        <div style="font-weight:700;color:#1B2A4A;font-size:15px">{html.escape(co['name'])}</div>
        <div style="font-size:12px">{co_addr_html}</div>
      </div>
      <div style="text-align:right">
        <div>Invoice #: <b style="font-size:20px">{html.escape(inv['invoice_no'])}</b></div>
        <div>Date: <b>{html.escape(_fmt_date(inv['invoice_date']))}</b></div>
        <div style="margin-top:10px;text-align:right">{_jobinfo_box_html(pack)}</div>
      </div>
      <div style="position:absolute;left:{_env_mail_l}in;top:{_env_mail_label_t}in;width:{_env_mail_w}in;font-size:12px;line-height:20px">Billing Address:<br>&nbsp;</div>
      <div style="position:absolute;left:{_env_mail_l}in;top:{_env_mail_t}in;width:{_env_mail_w}in;font-size:12px">{bill_block}</div>
    </div>
    {_invoice_bar_html(pack)}
    </td></tr>
    <tr><th>ITEM</th><th>DESCRIPTION</th><th style='text-align:right'>QTY</th><th>UNIT</th><th style='text-align:right'>UNIT PRICE</th><th style='text-align:right'>LINE TOTAL</th></tr></thead>
    <tfoot><tr class="inv-tfoot-space"><td colspan="6" style="border:0;padding:0"></td></tr></tfoot>
    <tbody>{rows}</tbody></table>
    <div style="display:flex;flex-wrap:wrap;gap:24px;align-items:flex-start;margin-top:auto">
      <div style="flex:1 1 430px;min-width:340px">{_invoice_signature_html(pack)}</div>
      <div style="margin-left:auto">{_inv_totals_rows_html(pack)}</div>
    </div>
    <div class="inv-foot">
      {('<div>* Taxes included</div>' if _pack_has_taxed(pack) else '')}
      <b>Terms &amp; Conditions</b>
      <p style="margin:4px 0">{html.escape(_invoice_legal_for(pack))}</p>
    </div>
    </div>
    {_invoice_paperwork_html(pack.get("docs") or [])}
    """
    _atts = pack.get("attachments")
    if _atts is None:
        _atts = pack.get("docs") or []
    _sel_aids = [d.get("aid") for d in (pack.get("docs") or []) if d.get("aid")]
    _pdf_href = f"/print/invoice/{inv['invoice_no']}.pdf"
    if _atts and set(_sel_aids) != {d.get("aid") for d in _atts if d.get("aid")}:
        _pdf_href += "?docs=" + ",".join(
            _urlquote(a, safe="") for a in _sel_aids)
    actions = _doc_actions(f"/print/invoice/{inv['invoice_no']}",
                           _pdf_href,
                           "/invoices")
    return _sheet(f"Invoice {inv['invoice_no']}", body, actions)


def _jobinfo_box_html(pack) -> str:
    lines = _jobinfo_lines(pack)
    if not lines:
        return ""
    rows = "".join(
        f"<div>{html.escape(label)} <b>{html.escape(str(value))}</b></div>"
        for label, value in lines)
    # Job Info box, no caption (invoice round 2026-10-20): just the
    # box with its toggled fields. The signature / print-name lines
    # live in the signature block below the lines, not in this box.
    return f"""
        <div style="display:inline-block;border:1px solid #1B2A4A;border-radius:8px;padding:10px 14px;
                    min-width:230px;font-size:14px;text-align:left">
          {rows}
        </div>"""


def _invoice_paperwork_html(docs) -> str:
    """Attached PO scan / tax-exempt certificate for the printed
    invoice. Attachments NEVER sit on the invoice page: the whole
    paperwork block starts on a fresh printed page, and each image
    block gets its own fresh page too. Images embed; PDF and text
    documents are listed — their full pages ride in the PDF pack
    download. NOTE: html_invoice renders this block OUTSIDE the
    .inv-wrap flex column on purpose — break-before is ignored on
    flex items, which would strand the heading on the invoice page."""
    if not docs:
        return ""
    _img_docs = [d for d in docs if d["data_uri"]]
    _has_others = any(not d["data_uri"] for d in docs)
    _img_divs = []
    for _i, d in enumerate(_img_docs):
        # The first attachment block shares the paperwork heading's
        # page; every later image starts its own page.
        _brk = ("page-break-before:always;break-before:page;"
                if _i > 0 or _has_others else "")
        _img_divs.append(
            f"<div style='page-break-inside:avoid;{_brk}margin:14px 0'>"
            f"<b>{html.escape(d['title'])}</b> "
            f"<span style='font-size:10px;color:#5C6B7A'>{html.escape(d['kind'])} · {html.escape(d['filename'])}</span><br>"
            f"<img src=\"{d['data_uri']}\" style='max-width:100%;max-height:9in;border:1px solid #d0d5dd;margin-top:6px'>"
            f"</div>")
    imgs = "".join(_img_divs)
    others = "".join(
        f"<tr><td><b>{html.escape(d['title'])}</b></td><td>{html.escape(d['kind'])}</td>"
        f"<td>{html.escape(d['filename'])}</td><td>{d['size_kb']:.0f} KB</td></tr>"
        for d in docs if not d["data_uri"])
    table = (f"<table><tr><th>Document</th><th>Type</th><th>File</th><th>Size</th></tr>{others}</table>"
             if others else "")
    return (f"<div style='page-break-before:always;break-before:page'>"
            f"<h1>Attached paperwork</h1>{table}{imgs}</div>")


def html_ticket(pack, kind: str) -> str:
    t, co, m = pack["t"], pack["co"], pack["m"]
    title = "WORK TICKET" if kind == "work" else "DELIVERY TICKET"
    sig = (
        '<div class="sign"><div>Dispatched by</div><div>Received by — print / sign / date</div></div>'
        if kind == "delivery"
        else '<div class="sign"><div>Yard / mechanic</div><div>Customer / operator</div></div>'
    )
    _doc_label = "Work Ticket" if kind == "work" else "Delivery Ticket"
    _unit_val = t["unit_no"] + (
        f" — {t['description']}" if t["description"] else "")
    _header = _form_header_html(
        co, _doc_label, t["ticket_id"], _fmt_date(t['on_rent']),
        revto=pack.get("revised_to") or "",
        cust=(t["account_name"],
              [x for x in [t["bill_to"], t["city_st"], t["phone"]] if x]),
        info_rows=[
            ("Job", t["job_name"] or ""),
            ("Site", t["site_name"] or ""),
            ("Unit", _unit_val),
            ("PO #", t["po"] or ""),
            ("AFE #", t["afe"] or ""),
            ("Well / Pad", t["well_or_pad"] or ""),
        ],
    )
    _bar = _form_bar_html(
        t["site_name"] or "", t["operator"] or "",
        _fit_note(engine.transport_display(
            m.get("haul_by"), m.get("haul_note"),
            company_name=(_rowval(co, "dba") or _rowval(co, "name") or ""),
            customer_name=t["account_name"]), 120))
    # Charges (2026-10-23): the ticket's real line items, each with its
    # own Tax flag (asterisk), then the per-line tax on the total.
    _lrows = "".join(
        f"<tr><td>{html.escape(_ln['category'])}</td>"
        f"<td>{html.escape(_ln['description'] or _ln['category'])}</td>"
        f"<td style=\"text-align:right\">{_ln['qty']:g}</td>"
        f"<td>{html.escape(_ln['uom'])}</td>"
        f"<td style=\"text-align:right\">${_ln['rate']:,.2f}</td>"
        f"<td style=\"text-align:right\">${_ln['amount']:,.2f}"
        f"{' *' if _ln['taxed'] and not m.get('tax_exempt') else ''}</td></tr>"
        for _ln in (m.get("lines") or []))
    _charges = (f"""<table>
      <tr><th>Type</th><th>Description</th><th>Qty</th><th>Unit</th><th>Rate</th><th>Amount</th></tr>
      {_lrows}
      <tr><td colspan=5><b>Subtotal</b></td><td style="text-align:right"><b>${m['subtotal']:,.2f}</b></td></tr>
      <tr><td colspan=5>{html.escape(m.get('tax_name') or 'Tax')}</td><td style="text-align:right">${m['tax']:,.2f}</td></tr>
    </table>""" if _lrows else "")
    body = _doc_wrap(_header, _bar + f"""
    <table>
      <tr><th>Unit</th><th>Serial</th><th>Site / rig</th><th>Fit</th></tr>
      <tr><td>{html.escape(t['unit_no'])}<br>{html.escape(t['description'] or '')}</td>
          <td>{html.escape(t['serial_no'] or '')}</td>
          <td>{html.escape(t['site_name'] or '')}<br>{html.escape(t['operator'] or '')} {html.escape(t['rig_name'] or '')}</td>
          <td>{html.escape(m.get('fit') or '')}{(" — override: " + html.escape(t["fit_override"])) if ("fit_override" in t.keys() and t["fit_override"]) else ""}</td></tr>
    </table>
    <table>
      <tr><th>On rent</th><th>Off rent</th><th>Rate</th><th>Days</th><th>Status</th></tr>
      <tr><td>{html.escape(_fmt_date(t['on_rent']))}</td>
          <td>{html.escape(_fmt_date(t['off_rent'] or '—'))}</td>
          <td>{html.escape(t['rate_type'])} ${m['rate']:,.2f}</td>
          <td>{m['days']}</td>
          <td>{html.escape(t['status'])}</td></tr>
    </table>
    <table>
      <tr><th>Who transports</th><th>Possession</th><th>Tax situs</th></tr>
      <tr>
        <td>{html.escape(_fit_note(engine.transport_display(
            m.get("haul_by"), m.get("haul_note"),
            company_name=(_rowval(co, "dba") or _rowval(co, "name") or ""),
            customer_name=t["account_name"]), 120))}</td>
        <td>{html.escape(m.get("possession_label") or "")}</td>
        <td>{html.escape(m.get("tax_name") or "")} {m.get("tax_rate", 0):.4f}
            {" · exempt" if m.get("tax_exempt") else ""}<br>
            <small>{html.escape(m.get("tax_note") or "")}</small></td>
      </tr>
    </table>
    <table>
      <tr><th></th><th>Condition</th><th>Meter</th><th>By</th><th>Note</th></tr>
      <tr><td>Out</td><td>{html.escape(str(t['out_condition'] if 'out_condition' in t.keys() else '') or '—')}</td>
          <td>{html.escape(str(t['out_meter'] if 'out_meter' in t.keys() else '') or '')}</td>
          <td>{html.escape(str(t['out_by'] if 'out_by' in t.keys() else '') or '')} {html.escape(_fmt_date(str(t['out_at'] if 'out_at' in t.keys() else '') or ''))}</td>
          <td>{html.escape(_fit_note(str(t['out_note'] if 'out_note' in t.keys() else '') or '', 80))}</td></tr>
      <tr><td>In</td><td>{html.escape(str(t['in_condition'] if 'in_condition' in t.keys() else '') or '—')}</td>
          <td>{html.escape(str(t['in_meter'] if 'in_meter' in t.keys() else '') or '')}</td>
          <td>{html.escape(str(t['in_by'] if 'in_by' in t.keys() else '') or '')} {html.escape(_fmt_date(str(t['in_at'] if 'in_at' in t.keys() else '') or ''))}</td>
          <td>{html.escape(_fit_note(str(t['in_note'] if 'in_note' in t.keys() else '') or '', 80))}</td></tr>
    </table>
    {_charges}
    {"<p><b>Estimated Rental Ticket total (not an invoice): $%s</b></p>" % f"{m['total']:,.2f}" if kind=="work" else "<p>Delivery acknowledgement. Receiver confirms who took possession and where. Transportation and tax follow this Rental Ticket onto the invoice.</p>"}
    {sig}
    <footer class="legal">{html.escape(LEGAL)}</footer>
    <div class="fs-mark">FleetSheet</div>
    """)
    actions = _doc_actions(f"/print/{kind}/{t['ticket_id']}",
                           f"/print/{kind}/{t['ticket_id']}.pdf",
                           f"/ticket/{t['ticket_id']}")
    return _sheet(f"{title} {t['ticket_id']}", body, actions)


# ------------------------------------------------------------------
# Shared PDF form machinery (template round): the non-invoice PDFs
# get the invoice PDF's template — 0.4in margins (bottom 0.85in),
# a First/Later BaseDocTemplate whose Later frame reserves the
# measured header zone and redraws a fresh header there, and a
# numbered canvas that draws the footer (LEGAL + Page X of Y) in
# the bottom margin of every page at save() time.
# ------------------------------------------------------------------

def _form_styles() -> dict:
    """Fresh ParagraphStyle objects for the shared form machinery.
    Constructed standalone on every call — never registered into a
    shared stylesheet, so their names cannot collide."""
    from reportlab.lib.enums import TA_RIGHT
    return {
        "num": ParagraphStyle(
            name="FormNum", fontName="Helvetica-Bold", fontSize=14,
            leading=17, alignment=TA_RIGHT),
        "body": ParagraphStyle(
            name="FormBody", fontSize=9.5, leading=12.5),
        "bodyR": ParagraphStyle(
            name="FormBodyR", fontSize=9.5, leading=12.5,
            alignment=TA_RIGHT),
        "cell": ParagraphStyle(
            name="FormCell", fontSize=8.5, leading=10.5),
        "bar": ParagraphStyle(
            name="FormBar", fontSize=7.5, leading=6.6),
        "tiny": ParagraphStyle(
            name="FormTiny", fontSize=7, leading=9,
            textColor=colors.HexColor("#5C6B7A")),
    }


def _form_header_factory(co, doc_label, doc_no, doc_date, cust=None,
                         subject=None, info_rows=None, bar=None,
                         raw_date=False):
    """Return a zero-arg callable building a FRESH header zone
    (a list of flowables) on every call — continuation pages need
    new instances, exactly as pdf_invoice's header factories do.

    The zone is a two-column Table, colWidths [3.85in, 3.85in], all
    paddings 0, VALIGN TOP. LEFT: "Remit To:" label, the company
    paragraph (bold navy name + _company_addr_lines), a Spacer,
    then the customer block (cust = (name, [lines]), captioned
    "Billing Address:") or, with no customer, the subject block
    (subject = (caption, name, [lines])). RIGHT: "{doc_label}:
    {doc_no}" in the num style (just doc_label when doc_no is
    empty), "Date: <b>{doc_date}</b>" right-aligned (doc_date
    arrives PRE-FORMATTED; raw_date=True prints doc_date alone as
    the line, with no "Date:" prefix and no bold — the reports'
    subtitle line), then the info box built exactly like the
    invoice's job box when info_rows is given.

    bar = (left_text, contact_name, shipped_by) adds, under the
    header table, the transport bar: three per-cell BOX 1.0 navy
    cells in equal thirds of the 7.7in doc width — bold left_text
    (or a blank) at left, then Contact Name / Shipped by caption
    paragraphs (bold value or a fill-in line)."""
    _co_name = _rowval(co, "name")
    if not _co_name and co is not None:
        try:
            _co_name = co["name"] or ""
        except Exception:
            _co_name = ""
    _addr_lines = [str(x) for x in _company_addr_lines(co) if x]

    def _make():
        _st = _form_styles()
        _co_addr = "<br/>".join(html.escape(x) for x in _addr_lines)
        _co_para = Paragraph(
            f"<b><font color='#1B2A4A'>{html.escape(str(_co_name or ''))}</font></b>"
            + (f"<br/>{_co_addr}" if _co_addr else ""), _st["body"])
        _left = [Paragraph("Remit To:<br/>&nbsp;", _st["body"]),
                 _co_para,
                 Spacer(1, 10)]
        _blk = None
        if cust is not None:
            _blk = ("Billing Address", cust[0], list(cust[1] or []))
        elif subject is not None:
            _blk = (subject[0], subject[1], list(subject[2] or []))
        if _blk is not None:
            _cap, _nm, _lns = _blk
            _lns = [str(x) for x in _lns if x and str(x).strip()]
            _lns_html = "<br/>".join(html.escape(x) for x in _lns)
            _left.append(Paragraph(
                f"{html.escape(str(_cap))}:<br/>&nbsp;", _st["body"]))
            _left.append(Paragraph(
                f"<b>{html.escape(str(_nm or ''))}</b>"
                + (f"<br/>{_lns_html}" if _lns_html else ""),
                _st["body"]))
        if doc_no:
            _title_para = Paragraph(
                f"{html.escape(str(doc_label))}: "
                f"{html.escape(str(doc_no))}", _st["num"])
        else:
            _title_para = Paragraph(
                html.escape(str(doc_label)), _st["num"])
        if raw_date:
            _date_para = Paragraph(
                html.escape(str(doc_date or "")), _st["bodyR"])
        else:
            _date_para = Paragraph(
                f"Date: <b>{html.escape(str(doc_date or ''))}</b>",
                _st["bodyR"])
        _right = [_title_para, _date_para]
        if info_rows:
            _info_tab = Table(
                [[label, str(value)] for label, value in info_rows],
                colWidths=[1.25 * inch, 2.35 * inch])
            _info_tab.setStyle(TableStyle([
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#1B2A4A")),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))
            _info_wrap = Table([[_info_tab]], colWidths=[3.85 * inch])
            _info_wrap.setStyle(TableStyle([
                ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]))
            _right += [Spacer(1, 8), _info_wrap]
        _head = Table([[_left, _right]],
                      colWidths=[3.85 * inch, 3.85 * inch])
        _head.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        _zone = [_head]
        if bar is not None:
            _left_text, _contact, _shipped = (
                str(bar[0] or ""), str(bar[1] or ""), str(bar[2] or ""))

            def _bar_field(label, value):
                _val = (f"<b>{html.escape(value)}</b>" if value
                        else "______________")
                return Paragraph(
                    f"<b><font size=6 color='#5C6B7A'>{label}</font></b>"
                    f"<br/>{_val}", _st["bar"])

            _left_para = Paragraph(
                (f"<b>{html.escape(_left_text)}</b>"
                 if _left_text else " "), _st["bar"])
            _bar_tab = Table(
                [[_left_para,
                  _bar_field("Contact Name", _contact),
                  _bar_field("Transport", _shipped)]],
                colWidths=[7.7 * inch / 3] * 3)
            _bar_tab.setStyle(TableStyle([
                ("BOX", (0, 0), (0, 0), 1.0, colors.HexColor("#1B2A4A")),
                ("BOX", (1, 0), (1, 0), 1.0, colors.HexColor("#1B2A4A")),
                ("BOX", (2, 0), (2, 0), 1.0, colors.HexColor("#1B2A4A")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]))
            _zone += [Spacer(1, 0.5), _bar_tab, Spacer(1, 1)]
        return _zone

    return _make


def _form_canvasmaker(legal_text):
    """A canvasmaker modeled on pdf_invoice's _NumberedCanvas:
    collects pages and, at save() time, draws the footer in the
    bottom margin of every page with the invoice footer's exact
    geometry — legal lines wrapped at 6.8pt Helvetica in #5C6B7A
    starting at y = 0.14in + (n-1)*8.2, the #d0d5dd strip line at
    strip_y + 10 where strip_y = 0.14in + n*8.2 + 5, and
    "Page X of Y" right-aligned at strip_y. Empty legal_text draws
    only the strip line + Page X of Y, positioned as if n=1 (the
    same formula with n=1, but no legal text is drawn)."""
    from reportlab.pdfgen.canvas import Canvas as _Canvas
    from reportlab.lib.utils import simpleSplit as _split
    _legal = str(legal_text or "")

    class _FormCanvas(_Canvas):
        def __init__(self, *args, **kwargs):
            _Canvas.__init__(self, *args, **kwargs)
            self._saved_pages = []

        def showPage(self):
            self._saved_pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            _total = len(self._saved_pages)
            for _num, _state in enumerate(self._saved_pages, 1):
                self.__dict__.update(_state)
                self._draw_form_footer(_num, _total)
                _Canvas.showPage(self)
            _Canvas.save(self)

        def _draw_form_footer(self, num, total):
            _w, _h = letter
            _mx = 0.4 * inch
            _maxw = _w - 2 * _mx
            self.saveState()
            self.setFillColor(colors.HexColor("#5C6B7A"))
            if _legal:
                _legal_lines = _split(_legal, "Helvetica", 6.8, _maxw)
            else:
                _legal_lines = []
            _n = len(_legal_lines) if _legal_lines else 1
            _lead = 8.2
            _y = 0.14 * inch + (_n - 1) * _lead
            self.setFont("Helvetica", 6.8)
            for _ln in _legal_lines:
                self.drawString(_mx, _y, _ln)
                _y -= _lead
            _strip_y = 0.14 * inch + _n * _lead + 5
            self.setStrokeColor(colors.HexColor("#d0d5dd"))
            self.line(_mx, _strip_y + 10, _w - _mx, _strip_y + 10)
            self.setFont("Helvetica", 7.5)
            self.drawRightString(_w - _mx, _strip_y,
                                 f"Page {num} of {total}")
            self.restoreState()

    def _maker(*args, **kwargs):
        return _FormCanvas(*args, **kwargs)

    return _maker


def _build_form_pdf(header_factory, story, legal_text) -> bytes:
    """Build a form PDF on the shared template: BaseDocTemplate
    (letter; margins L/R/T 0.4in, bottom 0.85in), a 'First' frame
    with the full frame geometry and a 'Later' frame whose top is
    lowered by the measured header-zone height; the Later onPage
    hook drawOn()s a FRESH header zone into the reserved zone,
    mirroring pdf_invoice's _draw_later_header walk. The story
    built is NextPageTemplate('Later') + the page-1 header zone +
    the caller's story; the footer rides _form_canvasmaker."""
    if not HAS_PDF:
        raise RuntimeError("pip install reportlab")
    from reportlab.platypus import (BaseDocTemplate as _BaseDoc,
                                    Frame as _Frame,
                                    NextPageTemplate as _NextPageTemplate,
                                    PageTemplate as _PageTemplate)
    buf = BytesIO()
    doc = _BaseDoc(buf, pagesize=letter, leftMargin=0.4 * inch,
                   rightMargin=0.4 * inch,
                   topMargin=0.4 * inch, bottomMargin=0.85 * inch)
    _header_zone_h = 0.0
    for _f in header_factory():
        _w, _h = _f.wrap(doc.width, doc.height)
        _header_zone_h += _h

    def _draw_later_header(canv, _doc):
        _x = doc.leftMargin
        _y = doc.bottomMargin + doc.height - 6
        for _f in header_factory():
            _w, _h = _f.wrap(doc.width, doc.height)
            _f.drawOn(canv, _x, _y - _h)
            _y -= _h

    doc.addPageTemplates([
        _PageTemplate(
            id="First",
            frames=[_Frame(doc.leftMargin, doc.bottomMargin,
                           doc.width, doc.height, id="first")],
            pagesize=letter),
        _PageTemplate(
            id="Later",
            frames=[_Frame(doc.leftMargin, doc.bottomMargin,
                           doc.width, doc.height - _header_zone_h,
                           id="later")],
            onPage=_draw_later_header, pagesize=letter),
    ])
    _full = ([_NextPageTemplate("Later")] + header_factory()
             + list(story))
    doc.build(_full, canvasmaker=_form_canvasmaker(legal_text))
    return buf.getvalue()


def pdf_invoice(pack) -> bytes:
    if not HAS_PDF:
        raise RuntimeError("pip install reportlab")
    inv, co, tot, lines = pack["inv"], pack["co"], pack["tot"], pack["lines"]
    buf = BytesIO()
    # Invoice round layout (2026-10-20) — same anatomy as html_invoice:
    # 0.4in margins (bottom 0.85in leaves room for the footer drawn on
    # every page by the numbered canvas); two-column header; the
    # bordered header bar; the six-column lines table with exactly
    # len(lines) rows; signature/notes beside the totals (with the
    # Grand Total); attached documents — images included — merge as
    # their own pages after, never inline on the invoice page.
    # Polish round (2026-10-20): a BaseDocTemplate with two page
    # templates replaces the SimpleDocTemplate — 'First' keeps the
    # full frame page 1 has always had, 'Later' lowers its frame
    # top by the exact measured header-zone height so the full
    # header repeats on every continuation page (see the template
    # setup at the end of the header build below). Frame geometry
    # otherwise mirrors SimpleDocTemplate's exactly (same margins,
    # default frame paddings), so page 1's flow does not move.
    from reportlab.platypus import (BaseDocTemplate as _BaseDoc,
                                    Frame as _Frame,
                                    NextPageTemplate as _NextPageTemplate,
                                    PageTemplate as _PageTemplate)
    doc = _BaseDoc(buf, pagesize=letter, leftMargin=0.4 * inch,
                   rightMargin=0.4 * inch,
                   topMargin=0.4 * inch, bottomMargin=0.85 * inch)
    from reportlab.lib.enums import TA_RIGHT
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Tiny", fontSize=7, textColor=colors.HexColor("#5C6B7A"), leading=9))
    styles.add(ParagraphStyle(name="InvBody", fontSize=9.5, leading=12.5))
    styles.add(ParagraphStyle(name="InvBodyR", fontSize=9.5, leading=12.5,
                              alignment=TA_RIGHT))
    # Invoice # rides a couple of sizes up (round 2, Jason): visibly
    # bigger than the surrounding text.
    styles.add(ParagraphStyle(name="InvNum", fontName="Helvetica-Bold",
                              fontSize=14, leading=17, alignment=TA_RIGHT))
    styles.add(ParagraphStyle(name="InvCell", fontSize=8.5, leading=10.5))
    # Polish round (2026-10-20): the header bar is squeezed —
    # fontSize 8/leading 7.5 (strip 15.00pt measured by wrapping the
    # built table) becomes 7.5/6.6 (strip 13.20pt). The two bar
    # lines are a 6pt small-caps label over a 7.5pt value, so the
    # 6.6pt baseline spacing still clears both glyph rows.
    styles.add(ParagraphStyle(name="InvBar", fontSize=7.5, leading=6.6))
    _has_taxed = _pack_has_taxed(pack)

    from reportlab.pdfgen.canvas import Canvas as _Canvas
    from reportlab.lib.utils import simpleSplit as _split

    class _NumberedCanvas(_Canvas):
        """Draws the footer zone — the strip with Page X of Y,
        above the Terms & Conditions paragraph — in the bottom
        margin of every invoice page at save() time, when the page
        count is known. When the invoice has taxed lines, the strip
        also carries the '* Taxes included' footnote (the flag is
        passed in through the canvasmaker below)."""

        taxed_note = False

        def __init__(self, *args, **kwargs):
            _Canvas.__init__(self, *args, **kwargs)
            self._saved_pages = []

        def showPage(self):
            self._saved_pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            _total = len(self._saved_pages)
            for _num, _state in enumerate(self._saved_pages, 1):
                self.__dict__.update(_state)
                self._draw_invoice_footer(_num, _total)
                _Canvas.showPage(self)
            _Canvas.save(self)

        def _draw_invoice_footer(self, num, total):
            _w, _h = letter
            _mx = 0.4 * inch
            _maxw = _w - 2 * _mx
            self.saveState()
            self.setFillColor(colors.HexColor("#5C6B7A"))
            _legal_lines = _split(_invoice_legal_for(pack), "Helvetica", 6.8, _maxw)
            _lead = 8.2
            _y = 0.14 * inch + (len(_legal_lines) - 1) * _lead
            self.setFont("Helvetica", 6.8)
            for _ln in _legal_lines:
                self.drawString(_mx, _y, _ln)
                _y -= _lead
            _strip_y = 0.14 * inch + len(_legal_lines) * _lead + 5
            self.setStrokeColor(colors.HexColor("#d0d5dd"))
            self.line(_mx, _strip_y + 10, _w - _mx, _strip_y + 10)
            self.setFont("Helvetica", 7.5)
            if getattr(self, "taxed_note", False):
                self.drawString(_mx, _strip_y, "* Taxes included")
            self.drawRightString(_w - _mx, _strip_y,
                                 f"Page {num} of {total}")
            self.restoreState()

    def _invoice_canvasmaker(*args, **kwargs):
        _can = _NumberedCanvas(*args, **kwargs)
        _can.taxed_note = _has_taxed
        return _can

    from reportlab.platypus import Flowable as _Flowable
    from reportlab.platypus import KeepTogether as _KeepTogether

    class _BottomFill(_Flowable):
        """Filler that leaves exactly zone_h of height on the page
        for the bottom zone that follows it: it consumes the rest of
        the available height when there is more than the zone needs,
        and consumes whatever little remains (pushing the zone to
        the next page, where _SettleFill anchors it) when there is
        not more than the zone needs."""

        def __init__(self, zone_h):
            super().__init__()
            self.zone_h = zone_h

        def wrap(self, availWidth, availHeight):
            if availHeight > self.zone_h + 2:
                _h = availHeight - self.zone_h
            else:
                # Too tight for the zone (or just a sliver left):
                # consume what remains so the zone starts on a
                # fresh page, where _SettleFill anchors it.
                _h = availHeight
            self.width = availWidth
            self.height = _h
            return (availWidth, _h)

        def draw(self):
            pass

    class _SettleFill(_Flowable):
        """Second half of the bottom-anchor pair: when _BottomFill
        left exactly zone_h on the page this fill is 0; when
        _BottomFill pushed the zone to a fresh page, this fill sees
        the full frame there and consumes everything above the zone,
        so the zone still lands at the bottom of that page."""

        def __init__(self, zone_h):
            super().__init__()
            self.zone_h = zone_h

        def wrap(self, availWidth, availHeight):
            _h = availHeight - self.zone_h \
                if availHeight > self.zone_h + 2 else 0
            self.width = availWidth
            self.height = _h
            return (availWidth, _h)

        def draw(self):
            pass

    story = []
    _co_addr = "<br/>".join(
        html.escape(x) for x in _company_addr_lines(co) if x)
    _bill = "<br/>".join(
        html.escape(x) for x in _customer_addr_lines(inv) if x)
    # Follow-up labels (2026-10-20): "Remit To:" above the company
    # block and "Billing Address:" above the customer block, each
    # with a blank line under it. They are SEPARATE paragraphs drawn
    # by _draw_env_blocks with their BOTTOM at the block's top edge,
    # so the blocks' window positions do not move. Polish round:
    # the four paragraphs are built fresh by this factory on every
    # call — page 1 draws one set, and every continuation page's
    # repeated header draws another, so no paragraph is re-drawn.
    def _make_env_paras():
        _co_p = Paragraph(
            f"<b><font color='#1B2A4A'>{html.escape(co['name'] or '')}</font></b>"
            + (f"<br/>{_co_addr}" if _co_addr else ""), styles["InvBody"])
        _cust_p = Paragraph(
            f"<b>{html.escape(inv['account_name'] or '')}</b>"
            + (f"<br/>{_bill}" if _bill else ""), styles["InvBody"])
        _remit_p = Paragraph("Remit To:<br/>&nbsp;", styles["InvBody"])
        _bill_lab_p = Paragraph("Billing Address:<br/>&nbsp;",
                                styles["InvBody"])
        return _remit_p, _bill_lab_p, _co_p, _cust_p
    # Header address placement (standing): the company block lands
    # at the top of the header zone, the customer block below it —
    # see ADDRESS_PLACEMENT. Neither block rides the flow:
    # both are drawn at absolute page coordinates on page 1 by
    # _draw_env_blocks (an onFirstPage hook), so their placement
    # never depends on the header's height. The header table's left
    # cell stays empty; the flow only reserves the zone's height.
    _envp = ADDRESS_PLACEMENT
    _job_rows = [[label, str(value)] for label, value in _jobinfo_lines(pack)]
    # Header tables are built by factories, not one-off variables:
    # page 1 consumes one set through the story, and the 'Later'
    # page template's onPage hook builds a FRESH set for every
    # continuation page and drawOn()s it into the reserved zone —
    # a drawn table cannot be re-drawn reliably, so no instance is
    # ever shared between pages.
    def _make_head_tab():
        _job_tab = ""
        if _job_rows:
            _job_tab = Table(_job_rows,
                             colWidths=[1.25 * inch, 2.35 * inch])
            _job_tab.setStyle(TableStyle([
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#1B2A4A")),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))
        _right_cell = [
            Paragraph(f"Invoice #: {html.escape(inv['invoice_no'])}",
                      styles["InvNum"]),
            Paragraph(f"Date: <b>{html.escape(_fmt_date(inv['invoice_date']))}</b>",
                      styles["InvBodyR"]),
        ]
        if _job_tab:
            # Wrap the job-info table so it sits at the right edge
            # of the 3.85in right cell (its own width is 3.6in).
            _job_wrap = Table([[_job_tab]], colWidths=[3.85 * inch])
            _job_wrap.setStyle(TableStyle([
                ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]))
            _right_cell += [Spacer(1, 8), _job_wrap]
        _t = Table([[[Spacer(1, 1)], _right_cell]],
                   colWidths=[3.85 * inch, 3.85 * inch])
        _t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        return _t

    # Header bar (round 2 redo; polish round squeezed + boxed):
    # three boxes in one compact row — LEFT = the stored bar_text
    # (text when present, else a blank fill-in area); MIDDLE =
    # Contact Name; RIGHT = Shipped by. Polish round: a BOX around
    # EACH cell (not one outer box), so the three read as distinct
    # boxes with divider lines between them.
    _bar = _invoice_bar_data(pack)

    def _make_bar_tab():
        def _bar_field(label, value):
            _val = (f"<b>{html.escape(value)}</b>" if value
                    else "______________")
            return Paragraph(
                f"<b><font size=6 color='#5C6B7A'>{label}</font></b><br/>{_val}",
                styles["InvBar"])

        _left_bar_para = Paragraph(
            (f"<b>{html.escape(_bar['bar_text'])}</b>"
             if _bar["bar_text"] else " "), styles["InvBar"])
        _t = Table(
            [[_left_bar_para,
              _bar_field("Contact Name", _bar["contact_name"]),
              _bar_field("Transport", _bar["shipped_by"])]],
            colWidths=[doc.width / 3] * 3)
        _t.setStyle(TableStyle([
            ("BOX", (0, 0), (0, 0), 1.0, colors.HexColor("#1B2A4A")),
            ("BOX", (1, 0), (1, 0), 1.0, colors.HexColor("#1B2A4A")),
            ("BOX", (2, 0), (2, 0), 1.0, colors.HexColor("#1B2A4A")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        return _t

    _head_tab = _make_head_tab()
    _bar_tab = _make_bar_tab()
    # Reserve the header zone: the flow runs at least to the bottom
    # of the mailing block (mail_top + a 0.85in allowance for its
    # lines) so the bar and everything below clear both windows;
    # a taller right column (many Job Info fields) just runs longer.
    _head_h = _head_tab.wrap(doc.width, doc.height)[1]
    _zone_gap = (_envp["mail_top"] + 0.85 - 0.4) * inch - _head_h
    _bar_h = _bar_tab.wrap(doc.width, doc.height)[1]
    # Spacers adjacent to the bar (polish round squeeze): 1pt above
    # + 2pt below (footprint 18.00pt with the old 15.00pt strip)
    # become 0.5pt + 1pt around the 13.20pt strip — footprint
    # 14.70pt, all measured by wrapping the built tables above.
    _BAR_TOP_GAP = 0.5
    _BAR_BOT_GAP = 1
    # Exact height of everything above the lines table on page 1 —
    # this is the space the 'Later' frame reserves at the top of
    # every continuation page for the repeated header.
    _header_zone_h = (_head_h + (max(_zone_gap, 0))
                      + _BAR_TOP_GAP + _bar_h + _BAR_BOT_GAP)
    story.append(_NextPageTemplate("Later"))
    story.append(_head_tab)
    if _zone_gap > 0:
        story.append(Spacer(1, _zone_gap))
    story.append(Spacer(1, _BAR_TOP_GAP))
    story.append(_bar_tab)
    story.append(Spacer(1, _BAR_BOT_GAP))
    if pack.get("revised_to"):
        # Build 'al' (Jason 2026-10-28): the voided original's
        # reprint names its revision at the top of the document,
        # above its lines. (In the flow here, not in the header
        # zone: the header's frames are measured for the envelope
        # window and a flowable there collides with them.)
        story.append(Paragraph(
            f"<para alignment=\"center\"><b>*Revised to: {html.escape(str(pack['revised_to']))}</b></para>",
            styles["InvBody"]))
    # Lines table: ITEM | DESCRIPTION | QTY | UNIT | UNIT PRICE |
    # LINE TOTAL — description is the desc text only, and there are
    # exactly len(lines) body rows (no filler rows).
    data = [["ITEM", "DESCRIPTION", "QTY", "UNIT", "UNIT PRICE", "LINE TOTAL"]]
    for L in lines:
        _qty = L.get("qty")
        # QTY format verified (round 2): f"{float(qty):g}" — see the
        # matching note in html_invoice's _line_row.
        _qty_txt = f"{float(_qty):g}" if _qty is not None else ""
        _price = (f"${float(L['rate']):,.2f}"
                  if L.get("rate") is not None else "")
        _amt = f"${L['amount']:,.2f}" + (" *" if L.get("taxed") else "")
        data.append([Paragraph(html.escape(str(L.get("ref") or "")),
                               styles["InvCell"]),
                     Paragraph(html.escape(str(L.get("desc") or "")),
                               styles["InvCell"]),
                     _qty_txt,
                     Paragraph(html.escape(str(L.get("unit") or "")),
                               styles["InvCell"]),
                     _price,
                     _amt])
    if not lines:
        data.append(["", "No lines.", "", "", "", ""])
    tbl = Table(data, colWidths=[1.0 * inch, 3.2 * inch, 0.6 * inch,
                                 0.7 * inch, 1.0 * inch, 1.2 * inch],
                repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1B2A4A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (2, 0), (2, -1), "RIGHT"),
        ("ALIGN", (4, 0), (5, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, 0), 0.3, colors.HexColor("#1B2A4A")),
        ("LINEBELOW", (0, 1), (-1, -1), 0.2, colors.HexColor("#e5e7eb")),
    ]))
    story.append(tbl)
    # Bottom zone: the plain signature/notes block at left (Print
    # Name blank — never pre-filled — Sign Name blank, a short Date
    # line, a long Notes line; ruled lines drawn by the table style)
    # beside the totals column at right. The lines run to the edge
    # of their block, stopping short of the totals: Print Name and
    # Notes 3.70in, Sign Name 2.55in, Date 0.75in.
    # Build 'o' correction (Jason 2026-10-24): the 'n' round moved
    # this block below the totals at full width (lines to 6.90in)
    # under his 'm' look-see item 4; his correction the same day —
    # "dont extend them that long... still want that one block,
    # totals right justified, signatures left justified stretching
    # right until they'll get too close to the totals" — restores
    # the side-by-side block as it stood.
    _sig_tab = Table(
        [["Print Name", "", "", ""],
         ["Sign Name", "", "Date", ""],
         ["Notes", "", "", ""]],
        colWidths=[0.80 * inch, 2.55 * inch, 0.40 * inch, 0.75 * inch])
    _sig_tab.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (1, 0), (3, 0), 0.5, colors.black),
        ("LINEBELOW", (1, 1), (1, 1), 0.5, colors.black),
        ("LINEBELOW", (3, 1), (3, 1), 0.5, colors.black),
        ("LINEBELOW", (1, 2), (3, 2), 0.5, colors.black),
        ("SPAN", (1, 0), (3, 0)),
        ("SPAN", (1, 2), (3, 2)),
    ]))
    # Totals order (Part A2, round 2): (1) the write-in row FIRST,
    # only when filled (a label or a non-zero amount) — a completely
    # empty write-in is OMITTED entirely, and a filled one renders
    # exactly like the Subtotal row (plain cells, standard padding,
    # no rule/box styling); (2) Subtotal = lines subtotal + write-in;
    # (3) Tax Rate only when rate text exists, then Sales Tax ALWAYS
    # (even $0.00); (4) Grand Total = tot['total'].
    _adj = _pack_adjustment(pack)
    _adj_label = _pack_adj_label(pack)
    totdata = []
    if _adj_label or _adj != 0:
        totdata.append([_adj_label, f"${_adj:,.2f}"])
    totdata.append(["Subtotal", f"${float(tot['subtotal']) + _adj:,.2f}"])
    _rate_txt = _tax_rate_text(pack)
    if _rate_txt:
        totdata.append(["Tax Rate", _rate_txt])
    totdata.append(["Sales Tax", f"${float(tot.get('tax') or 0):,.2f}"])
    totdata.append(["Grand Total", f"${_pack_grand_total(pack):,.2f}"])
    tottab = Table(totdata, colWidths=[1.5 * inch, 1.2 * inch])
    tottab.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    _bottom_tab = Table([[_sig_tab, tottab]],
                        colWidths=[4.55 * inch, 3.15 * inch])
    _bottom_tab.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        # The totals column bottom-aligns in the zone so the Grand
        # Total row sits on the zone's bottom edge next to the
        # signature block's last line, however many rows it has.
        ("VALIGN", (1, 0), (1, 0), "BOTTOM"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("LEFTPADDING", (1, 0), (1, 0), 32.4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    # Bottom anchoring (round 2): measure the built bottom zone, then
    # the _BottomFill + _SettleFill pair between the lines table and
    # the zone (wrapped in KeepTogether) anchors the zone at the
    # bottom of the last content page, just above the canvas-drawn
    # footer zone (bottomMargin 0.85in already reserves the footer).
    # _BottomFill leaves exactly zone_h on the current page when
    # there is room, or pushes the zone whole to the next page when
    # there is not; _SettleFill is 0 in the first case and fills the
    # fresh page down to the zone in the second, so the zone sits at
    # a page bottom either way.
    _zone_h = _bottom_tab.wrap(doc.width, doc.height)[1]
    story.append(Spacer(1, 6))
    story.append(_BottomFill(_zone_h))
    story.append(_SettleFill(_zone_h))
    story.append(_KeepTogether([_bottom_tab]))
    def _draw_env_blocks(canv, _doc):
        # The two address blocks at their standing header positions,
        # in absolute page coordinates (PDF origin is bottom-left;
        # placement tops measure from the page's top edge). Page 1's
        # 'First' template calls this as its onPage hook (that IS
        # the header placement); the 'Later' hook below calls it
        # too, so the repeated print header carries the same blocks
        # at the same coordinates.
        _remit_para, _bill_label_para, _co_para, _cust_para = \
            _make_env_paras()
        _ph = letter[1]
        # Labels first, each with its bottom exactly at its block's
        # top edge (drawOn's y is the paragraph's bottom), so the
        # block draws below are unchanged.
        _remit_para.wrap(_envp["ret_cap"] * inch, _ph)
        _remit_para.drawOn(canv, _envp["ret_left"] * inch,
                           _ph - _envp["ret_top"] * inch)
        _bill_label_para.wrap(_envp["mail_cap"] * inch, _ph)
        _bill_label_para.drawOn(canv, _envp["mail_left"] * inch,
                                _ph - _envp["mail_top"] * inch)
        _w1, _h1 = _co_para.wrap(_envp["ret_cap"] * inch, _ph)
        _co_para.drawOn(canv, _envp["ret_left"] * inch,
                        _ph - _envp["ret_top"] * inch - _h1)
        _w2, _h2 = _cust_para.wrap(_envp["mail_cap"] * inch, _ph)
        _cust_para.drawOn(canv, _envp["mail_left"] * inch,
                          _ph - _envp["mail_top"] * inch - _h2)

    def _draw_later_header(canv, _doc):
        # Continuation-page hook (polish round): draw the FULL
        # header in the zone the 'Later' frame reserves at the top
        # of the page, in the same layout as page 1 — the address
        # blocks at their page-1 coordinates, then fresh copies of
        # the header table (Invoice #/Date + Job Info box) and
        # the boxed bar, walked down from the same flow
        # top page 1 starts at (frame top = bottomMargin + height,
        # less the frame's default 6pt top padding; flow x is the
        # left margin itself — verified against page 1's rendered
        # positions, where cell paddings supply the inset). The
        # walk consumes exactly _header_zone_h, so it ends
        # precisely where the 'Later' frame's flow begins and the
        # lines table's repeated column header lands directly
        # under the bar — no second column header is drawn here.
        _draw_env_blocks(canv, _doc)
        _x = doc.leftMargin
        _y = doc.bottomMargin + doc.height - 6
        _ht = _make_head_tab()
        _hh = _ht.wrap(doc.width, doc.height)[1]
        _ht.drawOn(canv, _x, _y - _hh)
        _y -= _hh
        if _zone_gap > 0:
            _y -= _zone_gap
        _y -= _BAR_TOP_GAP
        _bt = _make_bar_tab()
        _bh = _bt.wrap(doc.width, doc.height)[1]
        _bt.drawOn(canv, _x, _y - _bh)
        _y -= _bh
        _y -= _BAR_BOT_GAP

    # Page templates (polish round): 'First' = the full frame
    # page 1 has always had, its onPage hook placing the address
    # blocks; 'Later' = the same frame shortened at the top by
    # _header_zone_h (frame bottom unchanged, so the _BottomFill /
    # _SettleFill bottom anchoring still measures against a frame
    # whose bottom is the page's bottom margin), its onPage hook
    # drawing the repeated header into the reserved zone. The
    # story's leading NextPageTemplate('Later') switches every
    # page after page 1 to 'Later'.
    doc.addPageTemplates([
        _PageTemplate(
            id="First",
            frames=[_Frame(doc.leftMargin, doc.bottomMargin,
                           doc.width, doc.height, id="first")],
            onPage=_draw_env_blocks, pagesize=letter),
        _PageTemplate(
            id="Later",
            frames=[_Frame(doc.leftMargin, doc.bottomMargin,
                           doc.width, doc.height - _header_zone_h,
                           id="later")],
            onPage=_draw_later_header, pagesize=letter),
    ])

    # Attached paperwork rides with the invoice as merged pages only
    # — PDF, text and image documents alike (images are converted to
    # their own pages by _merge_doc_pages); nothing attaches inline
    # on the invoice page. The Terms strip + Terms & Conditions
    # footer is drawn by the numbered canvas on every invoice page —
    # it is not part of the story.
    doc.build(story, canvasmaker=_invoice_canvasmaker)
    return _merge_doc_pages(buf.getvalue(), pack.get("docs") or [])


def pdf_ticket(pack, kind: str) -> bytes:
    if not HAS_PDF:
        raise RuntimeError("pip install reportlab")
    t, co, m = pack["t"], pack["co"], pack["m"]
    _st = _form_styles()
    _doc_label = "Work Ticket" if kind == "work" else "Delivery Ticket"
    _unit_val = t["unit_no"] + (
        f" — {t['description']}" if t["description"] else "")
    _factory = _form_header_factory(
        co, _doc_label, t["ticket_id"], _fmt_date(t['on_rent']),
        cust=(t["account_name"],
              [x for x in [t["bill_to"], t["city_st"], t["phone"]] if x]),
        info_rows=[
            ("Job", t["job_name"] or ""),
            ("Site", t["site_name"] or ""),
            ("Unit", _unit_val),
            ("PO #", t["po"] or ""),
            ("AFE #", t["afe"] or ""),
            ("Well / Pad", t["well_or_pad"] or ""),
        ],
        bar=(t["site_name"] or "", t["operator"] or "",
             engine.transport_display(
                 m.get("haul_by"), m.get("haul_note"),
                 company_name=(_rowval(co, "dba") or _rowval(co, "name") or ""),
                 customer_name=t["account_name"])),
    )
    story = []
    data = [
        ["Unit", t["unit_no"], t["description"] or ""],
        ["Serial", t["serial_no"] or "", ""],
        ["On / off", _fmt_date(t["on_rent"]), _fmt_date(t["off_rent"] or "open")],
        ["Rate / days", f"{t['rate_type']} ${m['rate']:,.2f}", str(m["days"])],
        ["Fit / status", (m.get("fit") or "") + (f" (override: {t['fit_override']})" if ("fit_override" in t.keys() and t["fit_override"]) else ""), t["status"]],
        ["Transport", engine.transport_display(
            m.get("haul_by"), m.get("haul_note"),
            company_name=(_rowval(co, "dba") or _rowval(co, "name") or ""),
            customer_name=t["account_name"]), m.get("possession_label") or ""],
        ["Tax situs", m.get("tax_name") or "", f"{m.get('tax_rate', 0):.4f}" + (" exempt" if m.get("tax_exempt") else "")],
    ]
    # The ticket's real charge lines (2026-10-23), then its tax.
    for _ln in (m.get("lines") or []):
        data.append([_ln["description"] or _ln["category"],
                     f"{_ln['qty']:g} {_ln['uom']} @ ${_ln['rate']:,.2f}",
                     f"${_ln['amount']:,.2f}"])
    if m.get("lines"):
        data.append(["Tax", m.get("tax_name") or "", f"${m['tax']:,.2f}"])
    tbl = Table(data, colWidths=[1.4 * inch, 2.6 * inch, 3.2 * inch])
    tbl.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#e8eef4")),
        ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#1B2A4A")),
        ("INNERGRID", (0, 0), (-1, -1), 0.2, colors.HexColor("#c5cdd6")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
    ]))
    if pack.get("revised_to"):
        # Build 'al' (Jason 2026-10-28): the voided original's
        # reprint names its revision at the top of the document.
        story.append(Paragraph(
            f"<para alignment=\"center\"><b>*Revised to: {html.escape(str(pack['revised_to']))}</b></para>",
            _st["body"]))
    story.append(tbl)
    story.append(Spacer(1, 10))
    if kind == "work":
        story.append(Paragraph(f"Estimated Rental Ticket total (not an invoice): <b>${m['total']:,.2f}</b>", _st["body"]))
    else:
        story.append(Paragraph(
            (m.get("tax_note") or "") + " Delivery acknowledgement. Receiver confirms who took possession and where. Transportation and tax follow this Rental Ticket onto the invoice.",
            _st["body"],
        ))
    story.append(Spacer(1, 28))
    _sig_labels = (("Dispatched by", "Received by") if kind == "delivery"
                   else ("Yard / mechanic", "Customer / operator"))
    _sig_tab = Table(
        [[_sig_labels[0], "", _sig_labels[1], ""]],
        colWidths=[1.5 * inch, 2.2 * inch, 1.3 * inch, 2.2 * inch])
    _sig_tab.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (1, 0), (1, 0), 0.5, colors.black),
        ("LINEBELOW", (3, 0), (3, 0), 0.5, colors.black),
    ]))
    story.append(_sig_tab)
    return _build_form_pdf(_factory, story, LEGAL)


# Compliance / data-book packs — one-button print of a unit's full
# certifications & calibrations record plus its attached documents.
# ---------------------------------------------------------------------------
_CSTAT_LABEL = {"overdue": "OVERDUE", "due": "DUE", "ok": "OK", "info": "INFO"}


def _doc_data_uri(mime: str, blob: bytes) -> str | None:
    """Base64 data URI for an image doc, resized for print. None for others."""
    if not (mime or "").startswith("image/"):
        return None
    try:
        from PIL import Image
        img = Image.open(BytesIO(blob))
        img.thumbnail((1200, 1200))
        buf = BytesIO()
        fmt = "JPEG" if (mime or "").endswith("jpeg") else "PNG"
        img.convert("RGB").save(buf, fmt)
        return f"data:image/{fmt.lower()};base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None


def _text_doc_pdf(title: str, text: str) -> bytes:
    """Render a plain-text document as PDF pages for merging into the pack."""
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.lib.pagesizes import letter
    buf = BytesIO()
    # Margins match the invoice's PDF margins (cleanup round).
    d = SimpleDocTemplate(buf, pagesize=letter,
                          leftMargin=0.4 * inch, rightMargin=0.4 * inch,
                          topMargin=0.4 * inch, bottomMargin=0.85 * inch)
    styles = getSampleStyleSheet()
    safe = html.escape(text).replace("\n", "<br/>")
    d.build([Paragraph(f"<b>{html.escape(title)}</b>", styles["Heading2"]),
             Spacer(1, 8),
             Paragraph(f"<font face='Courier' size='9'>{safe}</font>",
                       styles["Normal"])])
    return buf.getvalue()


def _doc_divider_pdf(title: str, kind: str, filename: str) -> bytes:
    """One divider page naming the document whose own pages follow."""
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.lib.pagesizes import letter
    buf = BytesIO()
    d = SimpleDocTemplate(buf, pagesize=letter, leftMargin=inch, rightMargin=inch,
                          topMargin=3.2 * inch, bottomMargin=inch)
    styles = getSampleStyleSheet()
    d.build([
        Paragraph("<font size=14 color='#5C6B7A'>Data book document</font>",
                  styles["Normal"]),
        Spacer(1, 18),
        Paragraph(f"<b><font size=20>{html.escape(title)}</font></b>",
                  styles["Normal"]),
        Spacer(1, 12),
        Paragraph(f"<font size=11 color='#5C6B7A'>{html.escape(kind)} · "
                  f"{html.escape(filename)}</font>", styles["Normal"]),
        Spacer(1, 30),
        Paragraph("<font size=11 color='#5C6B7A'>The document's own pages "
                  "follow.</font>", styles["Normal"]),
    ])
    return buf.getvalue()


def _image_doc_pdf(title: str, blob: bytes) -> bytes:
    """Render ONE image as a letter page of its own for merging into
    a pack: the image fitted proportionally inside the invoice's
    margins (0.4in, bottom 0.85in — cleanup round) under a title
    line. Attachments are never embedded inline on a document
    page — they always ride as their own pages."""
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.platypus import Image as RLImage
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.lib.pagesizes import letter
    buf = BytesIO()
    d = SimpleDocTemplate(buf, pagesize=letter,
                          leftMargin=0.4 * inch, rightMargin=0.4 * inch,
                          topMargin=0.4 * inch, bottomMargin=0.85 * inch)
    styles = getSampleStyleSheet()
    # Fit box follows the new margins: full 7.7in frame width, and
    # the 9.75in frame height less the title line + spacer (~0.31in).
    _maxw, _maxh = 7.7 * inch, 9.4 * inch
    _w, _h = _maxw, _maxh
    try:
        from PIL import Image as _PILImage
        with _PILImage.open(BytesIO(blob)) as _im:
            _iw, _ih = _im.size
        if _iw and _ih:
            _scale = min(_maxw / _iw, _maxh / _ih)
            _w, _h = _iw * _scale, _ih * _scale
    except Exception:
        _w, _h = _maxw, _maxh
    d.build([Paragraph(f"<b>{html.escape(title or '')}</b>",
                       styles["Normal"]),
             Spacer(1, 8),
             RLImage(BytesIO(blob), width=_w, height=_h,
                     kind="proportional")])
    return buf.getvalue()


def _merge_doc_pages(base_pdf: bytes, docs) -> bytes:
    """Append attached documents' real pages to the pack PDF.

    PDF docs contribute their own pages; text docs are rendered as pages;
    image docs are converted via _image_doc_pdf to a page of their own —
    images are never embedded inline on a document page. Each document is
    preceded by a divider page naming it, so a printed pack shows where
    one document ends and the next begins. A damaged document is skipped —
    it never breaks the pack. Without pypdf, the base pack is returned
    unchanged.
    """
    try:
        from pypdf import PdfReader, PdfWriter
        base = PdfReader(BytesIO(base_pdf))
    except Exception:
        return base_pdf
    writer = PdfWriter()
    for pg in base.pages:
        writer.add_page(pg)
    for d in docs:
        blob = d.get("merge_blob") or b""
        if not blob:
            continue
        mime = d.get("mime") or ""
        try:
            if mime == "application/pdf":
                pages = list(PdfReader(BytesIO(blob)).pages)
            elif mime.startswith("text/"):
                txt = blob.decode("utf-8", "replace")
                if len(txt) > 500_000:
                    txt = txt[:500_000] + "\n\n[... truncated for print ...]"
                tpdf = _text_doc_pdf(d["title"], txt)
                pages = list(PdfReader(BytesIO(tpdf)).pages)
            elif mime.startswith("image/"):
                ipdf = _image_doc_pdf(d["title"], blob)
                pages = list(PdfReader(BytesIO(ipdf)).pages)
            else:
                continue
            for pg in PdfReader(BytesIO(_doc_divider_pdf(
                    d["title"], d["kind"], d["filename"]))).pages:
                writer.add_page(pg)
            for pg in pages:
                writer.add_page(pg)
        except Exception:
            continue
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def compliance_pack(con, aid: str, eqc_ids=None, doc_ids=None,
                    cert_ids=None) -> dict | None:
    """Everything a printed compliance pack needs for one unit.

    eqc_ids / doc_ids / cert_ids optionally narrow the pack to selected
    checks, documents, and certification records (the selective print).
    None means the whole package.
    """
    co = _company_for_print(con)
    unit = con.execute("SELECT * FROM assets WHERE asset_id=?", (aid,)).fetchone()
    if not unit:
        return None
    # None = whole category (the one-button pack). A list = exactly those ids,
    # even when empty: ticking only checks prints no documents, and vice versa.
    # Passing any list selects "selective mode": the other categories then
    # default to empty rather than whole.
    selective = eqc_ids is not None or doc_ids is not None or cert_ids is not None
    want_items = set(eqc_ids) if eqc_ids is not None else (set() if selective else None)
    want_docs = set(doc_ids) if doc_ids is not None else (set() if selective else None)
    want_certs = set(cert_ids) if cert_ids is not None else (set() if selective else None)
    items = []
    for it in engine.unit_checklist(con, aid):
        if want_items is not None and it["eqc_id"] not in want_items:
            continue
        hist = engine.item_history(con, it["eqc_id"], 1)
        last = dict(hist[0]) if hist else {}
        items.append({
            "eqc_id": it["eqc_id"],
            "name": it["display_name"],
            "pack": it["pack_name"] or "custom",
            "trigger": engine.TRIGGER_LABELS.get(it["trigger"], it["trigger"]),
            "interval": f'{it["interval_months"]:g} mo' if it["interval_months"] else "—",
            "backstop": (f'{it["deployed_backstop_months"]:g} mo'
                         if it["deployed_backstop_months"] else "—"),
            "criterion": it["criterion"] or "",
            "status": it["status"],
            "last_done": _fmt_date(it["last_done"]) if it["last_done"] else "—",
            "last_result": last.get("result") or "—",
            "last_evidence": last.get("evidence") or "",
            "last_clerk": last.get("clerk") or "",
            "next_due": (_fmt_date(it["next_due_live"].isoformat())
                         if it["next_due_live"] else "—"),
        })
    docs = []
    for d in engine.list_unit_docs(con, aid):
        if want_docs is not None and d["doc_id"] not in want_docs:
            continue
        got = engine.read_unit_doc(con, d["doc_id"])
        blob = got[1] if got else b""
        mime = d["mime"] or ""
        docs.append({
            "doc_id": d["doc_id"],
            "title": d["title"],
            "kind": engine.DOC_KINDS.get(d["kind"], d["kind"]),
            "filename": d["filename"],
            "mime": mime,
            "size_kb": (d["bytes"] or 0) / 1024,
            "uploaded": _fmt_date(str(d["uploaded_at"] or "")[:10]),
            "data_uri": _doc_data_uri(mime, blob),
            "blob": blob if mime.startswith("image/") else b"",
            "merge_blob": blob if (mime == "application/pdf"
                                   or mime.startswith("text/")) else b"",
        })
    return {
        "co": co, "unit": dict(unit), "items": items, "docs": docs,
        "summary": engine.compliance_summary(con, aid),
        # Cert identity (Q5): the pack's cert section shows the asset's real
        # cert records — each one naming this unit. The full pack carries
        # every cert record; a selective print carries the ticked ones
        # (build 'o': the unit paperwork print ticks certs beside checks
        # and documents; callers that pass no cert list get none, as
        # selective prints did before).
        "certs": [c for c in engine.list_certs(con, aid)
                  if want_certs is None or c["cert_id"] in want_certs],
        "selected": selective,
        "printed": _fmt_date(datetime.now().strftime("%Y-%m-%d %H:%M")),
    }


def fleet_compliance_pack(con) -> dict:
    """Fleet-wide compliance summary for the one-button fleet print."""
    co = _company_for_print(con)
    units = []
    for a in con.execute(
            "SELECT asset_id, unit_no, description, condition FROM assets "
            "ORDER BY unit_no").fetchall():
        s = engine.compliance_summary(con, a["asset_id"])
        ndocs = con.execute("SELECT COUNT(*) FROM unit_docs WHERE asset_id=?",
                            (a["asset_id"],)).fetchone()[0]
        ncerts = con.execute("SELECT COUNT(*) FROM asset_certs WHERE asset_id=?",
                             (a["asset_id"],)).fetchone()[0]
        units.append({"unit_no": a["unit_no"], "description": a["description"],
                      "status": a["condition"], "summary": s, "docs": ndocs,
                      "certs": ncerts})
    return {
        "co": co, "units": units,
        "printed": _fmt_date(datetime.now().strftime("%Y-%m-%d %H:%M")),
    }


def html_compliance_pack(pack) -> str:
    co, unit, items = pack["co"], pack["unit"], pack["items"]
    s = pack["summary"]
    title = "Compliance pack (selected)" if pack.get("selected") else "Compliance pack"
    badge = (f"{s['overdue']} overdue · " if s["overdue"] else "") + \
            (f"{s['due']} due · " if s["due"] else "") + \
            f"{s['ok']} ok · {s['info']} info"
    rows = []
    for it in items:
        stat = _CSTAT_LABEL.get(it["status"], it["status"])
        crit = f"<br><span style='font-size:10px;color:#5C6B7A'>Accept: {html.escape(it['criterion'])}</span>" if it["criterion"] else ""
        ev = html.escape(it["last_evidence"]) if it["last_evidence"] else "—"
        rows.append(
            f"<tr><td><b>{html.escape(it['name'])}</b><br>"
            f"<span style='font-size:10px;color:#5C6B7A'>{html.escape(it['pack'])} · {html.escape(it['trigger'])}</span>{crit}</td>"
            f"<td>{html.escape(it['interval'])}<br><span style='font-size:10px'>backstop {html.escape(it['backstop'])}</span></td>"
            f"<td><b>{stat}</b></td>"
            f"<td>{html.escape(it['last_done'])}<br><span style='font-size:10px'>{html.escape(it['last_result'])} · {html.escape(it['last_clerk'])}</span></td>"
            f"<td>{ev}</td>"
            f"<td>{html.escape(it['next_due'])}</td></tr>")
    checks = (f"<table><tr><th>Check</th><th>Interval</th><th>Status</th>"
              f"<th>Last done</th><th>Evidence</th><th>Next due</th></tr>"
              f"{''.join(rows)}</table>" if rows
              else "<p class='hint'>No compliance checks selected.</p>")
    if pack.get("certs"):
        crows = "".join(
            f"<tr><td><b>{html.escape(c['kind_label'])}</b><br>"
            f"{html.escape(c['title'])}</td>"
            f"<td>{html.escape(c['cert_number'] or '—')}</td>"
            f"<td>{html.escape(c['issuer'] or '—')}</td>"
            f"<td>{html.escape(_fmt_date(c['expiry_date']) or '—')}</td>"
            f"<td>{html.escape(c['status'])}</td>"
            f"<td>{html.escape(c['doc_title'] or ('attached' if c.get('evidence_doc_id') else '—'))}</td>"
            f"<td>{html.escape(c['clerk'] or '')}</td></tr>"
            for c in pack["certs"])
        certs_html = (f"<h1>Certifications &amp; calibrations</h1>"
                      f"<table><tr><th>Kind / Title</th><th>CERT #</th><th>Issuer</th>"
                      f"<th>Expires</th><th>Status</th><th>Evidence</th><th>Clerk</th></tr>"
                      f"{crows}</table>")
    else:
        certs_html = ""
    if pack["docs"]:
        imglst = [d for d in pack["docs"] if d["data_uri"]]
        tablerows = "".join(
            f"<tr><td><b>{html.escape(d['title'])}</b></td>"
            f"<td>{html.escape(d['kind'])}</td>"
            f"<td>{html.escape(d['filename'])}</td>"
            f"<td>{d['size_kb']:.0f} KB</td>"
            f"<td>{html.escape(d['uploaded'])}</td></tr>"
            for d in pack["docs"] if not d["data_uri"])
        imgs = "".join(
            f"<div style='page-break-inside:avoid;margin:14px 0'>"
            f"<b>{html.escape(d['title'])}</b> "
            f"<span style='font-size:10px;color:#5C6B7A'>{html.escape(d['kind'])} · {html.escape(d['filename'])}</span><br>"
            f"<img src=\"{d['data_uri']}\" style='max-width:100%;max-height:9in;border:1px solid #d0d5dd;margin-top:6px'>"
            f"</div>"
            for d in imglst)
        docs = "<h1>Data book — attached documents</h1>"
        if tablerows:
            docs += (f"<table><tr><th>Title</th><th>Type</th><th>File</th><th>Size</th><th>Added</th></tr>"
                     f"{tablerows}</table>")
        docs += imgs
    else:
        docs = "<h1>Data book</h1><p class='hint'>No documents selected.</p>"
    _header = _form_header_html(
        co, "Unit", unit["unit_no"], pack["printed"],
        subject=("Unit", unit["unit_no"],
                 [x for x in [unit["description"] or ""] if x]),
        info_rows=[
            ("Document", "Compliance pack"
             + (" (selected)" if pack.get("selected") else "")),
            ("Status", badge),
            ("Checks", str(s['total'])),
        ],
    )
    body = _doc_wrap(
        _header,
        certs_html
        + f"<h1>Checklist</h1>" + checks + docs
        + f'<div class="sign"><div>{html.escape(_output_by(co))}</div><div>Date</div></div>'
        + f'<footer class="legal">{html.escape(LEGAL)}</footer>')
    return _sheet(title + " " + unit["unit_no"], body,
                 actions=_doc_actions(
                     f"/print/compliance/{unit['asset_id']}",
                     f"/print/compliance/{unit['asset_id']}.pdf",
                     "/compliance"))


def html_fleet_compliance_pack(pack) -> str:
    co = pack["co"]
    rows = "".join(
        f"<tr><td><b>{html.escape(u['unit_no'])}</b><br>"
        f"<span style='font-size:10px;color:#5C6B7A'>{html.escape(u['description'] or '')}</span></td>"
        f"<td>{html.escape(u['status'] or '')}</td>"
        f"<td>{u['summary']['overdue']} overdue · {u['summary']['due']} due · "
        f"{u['summary']['ok']} ok · {u['summary']['info']} info</td>"
        f"<td>{u['docs']} doc{'s' if u['docs'] != 1 else ''}</td>"
        f"<td>{u['certs']} cert{'s' if u['certs'] != 1 else ''}</td></tr>"
        for u in pack["units"])
    _header = _form_header_html(
        co, "Fleet Compliance", "All units", pack["printed"],
        info_rows=[("Units", str(len(pack["units"])))],
    )
    body = _doc_wrap(
        _header,
        f"<table><tr><th>Unit</th><th>Status</th><th>Checks</th><th>Data book</th>"
        f"<th>Certs</th></tr>{rows}</table>"
        + f'<div class="sign"><div>{html.escape(_output_by(co))}</div><div>Date</div></div>'
        + f'<footer class="legal">{html.escape(LEGAL)}</footer>')
    return _sheet("Fleet compliance pack", body,
                 actions=_doc_actions("/print/compliance/fleet",
                                      "/print/compliance/fleet.pdf",
                                      "/compliance"))


def _pdf_compliance_table(items):
    data = [["Check", "Status", "Last done", "Next due"]]
    for it in items:
        data.append([
            f"{it['name']}\n{it['pack']} · {it['trigger']}",
            _CSTAT_LABEL.get(it["status"], it["status"]),
            f"{it['last_done']}\n{it['last_result']} {it['last_clerk']}".strip(),
            it["next_due"],
        ])
    return data


def pdf_compliance_pack(pack) -> bytes:
    if not HAS_PDF:
        raise RuntimeError("pip install reportlab")
    from reportlab.lib.units import inch
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle, Paragraph, Spacer
    co, unit = pack["co"], pack["unit"]
    _st = _form_styles()
    _styles_normal = _st["body"]
    _s = pack["summary"]
    _badge = (f"{_s['overdue']} overdue · " if _s["overdue"] else "") + \
             (f"{_s['due']} due · " if _s["due"] else "") + \
             f"{_s['ok']} ok · {_s['info']} info"
    _factory = _form_header_factory(
        co, "Unit", unit["unit_no"], pack["printed"],
        subject=("Unit", unit["unit_no"],
                 [x for x in [unit["description"] or ""] if x]),
        info_rows=[
            ("Document", "Compliance pack"
             + (" (selected)" if pack.get("selected") else "")),
            ("Status", _badge),
            ("Checks", str(_s['total'])),
        ],
    )
    story = [Spacer(1, 12)]
    if pack.get("certs"):
        cdata = [["Kind", "Certificate", "Expires", "Status", "Evidence"]]
        for c in pack["certs"]:
            cdata.append([
                c["kind_label"],
                f"{c['title']}\n{c['cert_number'] or ''} {c['issuer'] or ''}".strip(),
                _fmt_date(c["expiry_date"]) or "—",
                c["status"],
                c["doc_title"] or ("attached" if c.get("evidence_doc_id") else "—"),
            ])
        ctbl = Table(cdata, colWidths=[1.1 * inch, 2.8 * inch, 1.0 * inch, 1.0 * inch, 1.3 * inch])
        ctbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1B2A4A")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, 0), 0.3, colors.HexColor("#1B2A4A")),
            ("LINEBELOW", (0, 1), (-1, -1), 0.2, colors.HexColor("#e5e7eb")),
        ]))
        story.append(Paragraph("<b>Certifications &amp; calibrations</b>", _styles_normal))
        story.append(Spacer(1, 6))
        story.append(ctbl)
        story.append(Spacer(1, 14))
    tbl = Table(_pdf_compliance_table(pack["items"]),
                colWidths=[2.8 * inch, 0.9 * inch, 1.9 * inch, 1.6 * inch])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1B2A4A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, 0), 0.3, colors.HexColor("#1B2A4A")),
        ("LINEBELOW", (0, 1), (-1, -1), 0.2, colors.HexColor("#e5e7eb")),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 14))
    story.append(Paragraph("<b>Data book — attached documents</b>", _styles_normal))
    imgs = [d for d in pack["docs"] if d["blob"]]
    listed = [d for d in pack["docs"] if not d["blob"]]
    if listed:
        ddata = [["Title", "Type", "File"]] + [
            [d["title"], d["kind"], d["filename"]] for d in listed]
        dtab = Table(ddata, colWidths=[2.6 * inch, 1.8 * inch, 2.8 * inch])
        dtab.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1B2A4A")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e5e7eb")),
        ]))
        story.append(dtab)
    # Document pages are NOT flowed in-story: on a 'Later' page the
    # repeated header would be drawn over / onto a document page.
    # Like pdf_invoice, every attached document (PDF, text AND
    # image — image docs previously rode in-story as RLImage) is
    # merged AFTER the main pack is built via _merge_doc_pages, so
    # document pages never see the page templates. The merge list
    # gives image docs their blob as merge_blob (their stored
    # merge_blob is empty by construction in compliance_pack()).
    _merge_docs = []
    for d in pack["docs"]:
        _mb = d.get("merge_blob") or d.get("blob") or b""
        if _mb:
            _entry = dict(d)
            _entry["merge_blob"] = _mb
            _merge_docs.append(_entry)
    if not pack["docs"]:
        story.append(Paragraph("No documents attached.", _styles_normal))
    if listed:
        story.append(Paragraph("The full pages of each PDF and text document below follow this index — one download, one print.", _st["tiny"]))
    if imgs:
        story.append(Paragraph("The full pages of each image document follow this pack — one download, one print.", _st["tiny"]))
    story.append(Spacer(1, 28))
    story.append(Table([[_output_by(co), "Date ________________"]],
                       colWidths=[3.6 * inch, 3.6 * inch]))
    return _merge_doc_pages(
        _build_form_pdf(_factory, story, LEGAL), _merge_docs)


def pdf_fleet_compliance_pack(pack) -> bytes:
    if not HAS_PDF:
        raise RuntimeError("pip install reportlab")
    from reportlab.lib.units import inch
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle, Spacer
    co = pack["co"]
    _factory = _form_header_factory(
        co, "Fleet Compliance", "All units", pack["printed"],
        info_rows=[("Units", str(len(pack["units"])))],
    )
    story = [Spacer(1, 12)]
    data = [["Unit", "Status", "Checks", "Docs"]]
    for u in pack["units"]:
        s = u["summary"]
        data.append([f"{u['unit_no']}\n{u['description'] or ''}", u["status"] or "",
                     f"{s['overdue']} overdue · {s['due']} due · {s['ok']} ok", str(u["docs"])])
    tbl = Table(data, colWidths=[2.4 * inch, 1.2 * inch, 2.4 * inch, 1.2 * inch])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1B2A4A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e5e7eb")),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 28))
    _sig_tab = Table(
        [["Output by:", _rowval(co, "dba") or _rowval(co, "name"), "Date", ""]],
        colWidths=[1.9 * inch, 2.6 * inch, 0.6 * inch, 2.1 * inch])
    _sig_tab.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (1, 0), (1, 0), 0.5, colors.black),
        ("LINEBELOW", (3, 0), (3, 0), 0.5, colors.black),
    ]))
    story.append(_sig_tab)
    return _build_form_pdf(_factory, story, LEGAL)


# ------------------------------------------------------- Weekly reports
# The three push-button reports: AR aging, fleet utilization, week's flow.
# HTML for browser Print / Save as PDF; PDF for a downloadable file.

def _money(v) -> str:
    try:
        return f"${float(v or 0):,.2f}"
    except (TypeError, ValueError):
        return "$0.00"


def _report_actions(pdf_href: str) -> str:
    return _doc_actions(pdf_href[:-4] if pdf_href.endswith(".pdf") else pdf_href,
                        pdf_href, "/reports")


def html_aging(con) -> str:
    rep = engine.ar_aging(con)
    co = _company_for_print(con)
    rows = "".join(
        f"<tr><td>{html.escape(r['customer'])}</td>"
        + "".join(f"<td class=n>{_money(r[b])}</td>" for b in engine.BUCKETS)
        + f"<td class=n><b>{_money(r['total'])}</b></td></tr>"
        for r in rep["rows"])
    total = "".join(f"<td class=n><b>{_money(rep['total'][b])}</b></td>" for b in engine.BUCKETS)
    pct = "".join(f"<td class=n>{rep['pct'][b]:.1f}%</td>" for b in engine.BUCKETS)
    heads = "".join(f"<th class=n>{html.escape(engine.BUCKET_LABELS[b])}</th>" for b in engine.BUCKETS)
    body = (_form_header_html(co, "AR Aging", "", _fmt_date(rep['today']))
            + f"<table><tr><th>Customer</th>{heads}<th class=n>Total</th></tr>{rows}"
            f"<tr class=tot><td><b>TOTAL</b></td>{total}<td class=n><b>{_money(rep['grand'])}</b></td></tr>"
            f"<tr><td>% of Total</td>{pct}<td></td></tr></table>")
    return _sheet("AR aging", body, _report_actions("/print/report/aging.pdf"))


def html_fleet(con, days: int = 30) -> str:
    rep = engine.fleet_utilization(con, days)
    co = _company_for_print(con)
    rows = "".join(
        f"<tr><td><b>{html.escape(r['unit_no'])}</b><br><span class=mute>{html.escape(r['category'])}</span></td>"
        f"<td class=n>{r['rent_days']}</td><td class=n>{r['idle_days']}</td>"
        f"<td class=n>{r['down_days']}</td><td class=n>{r['util_pct']:.1f}%</td>"
        f"<td class=n>{_money(r['revenue'])}</td></tr>"
        for r in rep["rows"])
    body = (_form_header_html(co, "Fleet Utilization", "",
                              _fmt_date(rep['end']))
            + f"<p class=mute>{html.escape(_fmt_date(rep['start']))} to {html.escape(_fmt_date(rep['end']))}</p>"
            "<table><tr><th>Unit</th><th class=n>Days on rent</th><th class=n>Idle days</th>"
            "<th class=n>Down (shop)</th><th class=n>Util %</th><th class=n>Revenue</th></tr>"
            f"{rows}</table>")
    return _sheet("Fleet utilization", body,
                  _report_actions(f"/print/report/fleet.pdf?days={rep['days']}"))


def html_flow(con, span: str = "week") -> str:
    rep = engine.weeks_flow(con, span)
    co = _company_for_print(con)
    label = {k: lab for k, lab, _ in engine.FLOW_SECTIONS}
    sub = {k: s for k, _, s in engine.FLOW_SECTIONS}
    _flow_title = ("This week's flow" if rep["span"] == "week"
                   else "Flow — exceptions, next 30 days")
    parts = [_form_header_html(co, _flow_title, "", _fmt_date(rep['end'])),
             f"<p class=mute>{html.escape(_fmt_date(rep['start']))} to {html.escape(_fmt_date(rep['end']))}</p>"]
    for key, items in rep["sections"]:
        rows = "".join(
            f"<tr><td>{html.escape(i['what'])}</td><td>{html.escape(i['who'])}</td>"
            f"<td>{html.escape(_fmt_date(i['when'] or ''))}</td>"
            + (f"<td>{html.escape(i.get('why') or '')}</td>" if rep["span"] == "month" else "")
            + "</tr>" for i in items) or "<tr><td colspan=4 class=mute>Nothing.</td></tr>"
        why = "<th>Why it flags</th>" if rep["span"] == "month" else ""
        parts.append(
            f"<h2 style='font-size:15px;color:var(--navy)'>{html.escape(label.get(key, key))} "
            f"<span class=mute>— {html.escape(sub.get(key, ''))}</span></h2>"
            f"<table><tr><th>What</th><th>Who</th><th>When</th>{why}</tr>{rows}</table>")
    return _sheet("This week's flow", "".join(parts),
                  _report_actions(f"/print/report/flow.pdf?span={rep['span']}"))


def _pdf_report(title: str, subtitle: str, headers: list, rows: list,
                widths: list, fname: str, co) -> bytes:
    if not HAS_PDF:
        raise RuntimeError("pip install reportlab")
    # Reports carry no legal footer: legal_text="" draws only the
    # strip line + Page X of Y (see _form_canvasmaker). The header's
    # right line is the subtitle itself with a trailing
    # " · {company name}" stripped when present — no "Date:" prefix.
    _co_name = _rowval(co, "name")
    if not _co_name and co is not None:
        try:
            _co_name = co["name"] or ""
        except Exception:
            _co_name = ""
    _sub = str(subtitle or "")
    _suffix = f" · {_co_name}" if _co_name else ""
    if _suffix and _sub.endswith(_suffix):
        _sub = _sub[: -len(_suffix)]
    _factory = _form_header_factory(
        co, title, "", _sub, raw_date=True)
    story = [Spacer(1, 12)]
    data = [headers] + rows
    tbl = Table(data, colWidths=[w * inch for w in widths], repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1B2A4A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e5e7eb")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f8fa")]),
    ]))
    story.append(tbl)
    return _build_form_pdf(_factory, story, "")


def pdf_aging(con) -> bytes:
    rep = engine.ar_aging(con)
    co = _company_for_print(con)
    headers = ["Customer"] + [engine.BUCKET_LABELS[b] for b in engine.BUCKETS] + ["Total"]
    rows = [[r["customer"]] + [_money(r[b]) for b in engine.BUCKETS] + [_money(r["total"])]
            for r in rep["rows"]]
    rows.append(["TOTAL"] + [_money(rep["total"][b]) for b in engine.BUCKETS] + [_money(rep["grand"])])
    rows.append(["% of Total"] + [f"{rep['pct'][b]:.1f}%" for b in engine.BUCKETS] + [""])
    return _pdf_report("AR aging", f"As of {_fmt_date(rep['today'])} · {co['name'] or ''}",
                       headers, rows, [2.2, 0.8, 0.8, 0.8, 0.8, 0.8, 0.9],
                       "ar-aging.pdf", co)


def pdf_fleet(con, days: int = 30) -> bytes:
    rep = engine.fleet_utilization(con, days)
    co = _company_for_print(con)
    headers = ["Unit", "Days on rent", "Idle days", "Down (shop)", "Util %", "Revenue"]
    rows = [[f"{r['unit_no']} ({r['category']})".strip(), str(r["rent_days"]),
             str(r["idle_days"]), str(r["down_days"]), f"{r['util_pct']:.1f}%",
             _money(r["revenue"])] for r in rep["rows"]]
    # Original widths sum 7.8in > the 7.7in doc width — rescale
    # proportionally to sum 7.7in.
    _widths = [w * 7.7 / 7.8 for w in [2.4, 1.1, 1.1, 1.1, 0.9, 1.2]]
    return _pdf_report("Fleet utilization",
                       f"Last {rep['days']} days · {_fmt_date(rep['start'])} to {_fmt_date(rep['end'])} · {co['name'] or ''}",
                       headers, rows, _widths,
                       "fleet-utilization.pdf", co)


def pdf_flow(con, span: str = "week") -> bytes:
    rep = engine.weeks_flow(con, span)
    co = _company_for_print(con)
    label = {k: lab for k, lab, _ in engine.FLOW_SECTIONS}
    title = "This week's flow" if rep["span"] == "week" else "Flow — exceptions, next 30 days"
    headers = ["Section", "What", "Who", "When"] + (["Why"] if rep["span"] == "month" else [])
    rows = []
    for key, items in rep["sections"]:
        for i in items:
            rows.append([label.get(key, key), i["what"], i["who"], _fmt_date(i["when"] or "")]
                        + ([i.get("why") or ""] if rep["span"] == "month" else []))
    # Template round, coordinator fix: the Who column at 1.4in let
    # plain-string customer names overflow into When (ReportLab
    # strings do not wrap). Rebalanced within the 7.7in doc width —
    # Who at 2.4in is at parity with the aging report's accepted
    # 2.2in customer column.
    widths = ([1.1, 2.3, 2.2, 0.9, 1.2] if rep["span"] == "month"
              else [1.2, 2.7, 2.4, 1.0])
    return _pdf_report(title, f"{_fmt_date(rep['start'])} to {_fmt_date(rep['end'])} · {co['name'] or ''}",
                       headers, rows, widths, "weeks-flow.pdf", co)
