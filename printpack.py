"""Print sheets: on-screen HTML (browser Print / Save as PDF) and file PDF."""
from __future__ import annotations

import base64
import html
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
LOGO = Path(__file__).resolve().parent.parent / "FleetSheet_logo.jpg"  # archive only; runtime uses LOGO_BYTES
NAVY = "#1B2A4A"
LEGAL = (
    "FleetSheet · Yard book. One file. Amounts are computed from locked rates, dates, "
    "and tax location. This sheet is a billing instrument, not a tax opinion. "
    "Payment is due per stated terms. Disputes in writing within 10 days of invoice date."
)


def invoice_pack(con, invoice_no: str) -> dict | None:
    inv = con.execute(
        """SELECT i.*, c.account_name, c.bill_to, c.phone, c.email, c.city_st, c.terms AS cust_terms,
           c.bill_street, c.bill_street2
           FROM invoices i JOIN customers c ON c.customer_id = i.customer_id
           WHERE i.invoice_no=?""",
        (invoice_no,),
    ).fetchone()
    if not inv:
        return None
    co = con.execute("SELECT * FROM company WHERE id=1").fetchone()
    tot = engine.invoice_totals(con, invoice_no)
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
               JOIN assets a ON a.asset_id = t.asset_id
               JOIN sites s ON s.site_id = t.site_id
               WHERE t.invoice_no=? ORDER BY t.ticket_id""",
            (invoice_no,),
        ):
            m = engine.ticket_money(con, t["ticket_id"])
            pos = m.get("possession_label") or ""
            tax_bit = (
                f"{m.get('tax_name') or 'Tax'} @ {m.get('tax_rate', 0):.4f}"
                + (" · exempt" if m.get("tax_exempt") else "")
            )
            lines.append({
                "kind": "Rental",
                "id": t["ticket_id"],
                "detail": f"{t['unit_no']} · {t['description'] or ''} · {t['site_name'] or ''}",
                "when": (
                    f"{str(t['on_rent'])[:10]} – {str(t['off_rent'] or 'open')[:10]} · "
                    f"{t['rate_type']} × {m['days']}d · {pos} · {tax_bit}"
                ),
                "amount": m.get("rental_sub", m["subtotal"]),
            })
            if m.get("transport", 0) > 0:
                bits = []
                if m.get("mob"):
                    bits.append(f"Mob ${m['mob']:,.2f}")
                if m.get("demob"):
                    bits.append(f"Demob ${m['demob']:,.2f}")
                if m.get("transport_fee"):
                    bits.append(f"Transport ${m['transport_fee']:,.2f}")
                lines.append({
                    "kind": "Transportation",
                    "id": t["ticket_id"],
                    "detail": f"Transportation — {t['unit_no']} · {pos}",
                    "when": " · ".join(bits) or "Transportation",
                    "amount": m["transport"],
                })
            if m.get("other", 0) > 0:
                lines.append({
                    "kind": "Other",
                    "id": t["ticket_id"],
                    "detail": f"Fuel / parts / other — {t['unit_no']}",
                    "when": "",
                    "amount": m["other"],
                })
        for w in con.execute(
            """SELECT w.wo_id, w.work_type, w.description, w.bill_amount, a.unit_no
               FROM work_orders w JOIN assets a ON a.asset_id = w.asset_id
               WHERE w.invoice_no=? ORDER BY w.wo_id""",
            (invoice_no,),
        ):
            lines.append({
                "kind": "Service",
                "id": w["wo_id"],
                "detail": f"{w['unit_no']} · {w['work_type']} · {w['description']}",
                "when": "Work order",
                "amount": float(w["bill_amount"] or 0),
            })
    try:
        extras = con.execute(
            "SELECT * FROM invoice_lines WHERE invoice_no=? ORDER BY line_id", (invoice_no,)
        ).fetchall()
    except Exception:
        extras = []
    for x in extras:
        pl = f"PO line {x['po_line']} · " if x["po_line"] else ""
        lines.append({
            "kind": x["category"],
            "id": pl + x["uom"],
            "detail": x["description"],
            "when": f"{float(x['qty']):g} {x['uom']} × ${float(x['rate']):,.2f}",
            "amount": float(x["amount"]),
        })
    # Invoice paperwork (2026-09-27): the PO scan and tax-exempt certificate
    # ride with the invoice — the HTML print embeds images, the PDF pack
    # merges the documents' real pages via _merge_doc_pages.
    job = engine.invoice_job_box(con, invoice_no)
    docs = []
    for _kind in ("po", "tax_exempt"):
        _got = engine.read_invoice_doc(con, invoice_no, _kind)
        if not _got:
            continue
        _row, _blob = _got
        _mime = _row["mime"] or ""
        docs.append({
            "title": _row["title"],
            "kind": engine.INV_DOC_KINDS.get(_kind, _kind),
            "filename": _row["filename"],
            "mime": _mime,
            "size_kb": (_row["bytes"] or 0) / 1024,
            "data_uri": _doc_data_uri(_mime, _blob),
            "blob": _blob if _mime.startswith("image/") else b"",
            "merge_blob": _blob if (_mime == "application/pdf"
                                    or _mime.startswith("text/")) else b"",
        })
    return {"inv": inv, "co": co, "tot": tot, "lines": lines,
            "job": job, "docs": docs}


def credit_pack(con, cm_no: str) -> dict | None:
    try:
        info = engine.credit_open(con, cm_no)
    except ValueError:
        return None
    cm = con.execute("SELECT * FROM credit_memos WHERE cm_no=?", (cm_no,)).fetchone()
    if not cm:
        return None
    cust = con.execute("SELECT * FROM customers WHERE customer_id=?", (cm["customer_id"],)).fetchone()
    co = con.execute("SELECT * FROM company WHERE id=1").fetchone()
    lines = []
    for r in con.execute(
        """SELECT pay_id, pay_date, invoice_no, amount FROM collections
           WHERE cm_no=? AND kind='credit' ORDER BY pay_date, pay_id""",
        (cm_no,),
    ):
        lines.append({
            "pay_id": r["pay_id"],
            "pay_date": str(r["pay_date"])[:10],
            "invoice_no": r["invoice_no"],
            "amount": -float(r["amount"]),
        })
    return {"cm": cm, "info": info, "cust": cust, "co": co, "lines": lines}


def html_credit(pack) -> str:
    cm, info, cust, co, lines = pack["cm"], pack["info"], pack["cust"], pack["co"], pack["lines"]
    rows = "".join(
        f"<tr><td>{html.escape(L['pay_date'])}</td>"
        f"<td>{html.escape(L['invoice_no'])}</td>"
        f"<td>{html.escape(L['pay_id'])}</td>"
        f"<td style='text-align:right'>${L['amount']:,.2f}</td></tr>"
        for L in lines
    ) or "<tr><td colspan=4>No invoices applied yet. Remainder is unapplied on this memo.</td></tr>"
    body = _head(
        co, "CREDIT MEMO", cm["cm_no"], cust["account_name"] if cust else cm["customer_id"],
        [
            (cust["bill_to"] if cust else "") or "",
            (cust["city_st"] if cust else "") or "",
            (cust["phone"] if cust else "") or "",
            f"Reason: {cm['reason']}",
        ],
    ) + f"""
    <p>Memo date {html.escape(info['cm_date'])} · Face −${info['face']:,.2f}</p>
    <table><tr><th>Date</th><th>Applied to invoice</th><th>Event</th><th>Amount</th></tr>{rows}</table>
    <table class="tot">
      <tr><td></td><td class="n">Credit face</td><td class="n">−${info['face']:,.2f}</td></tr>
      <tr><td></td><td class="n">Applied</td><td class="n">−${info['applied']:,.2f}</td></tr>
      <tr><td></td><td class="n">Unapplied</td><td class="n">−${info['unapplied']:,.2f}</td></tr>
    </table>
    <p>{html.escape(cm['notes'] or '')}</p>
    <div class="sign"><div>Yard / prepared</div><div>Customer acknowledgement</div></div>
    <footer class="legal">{html.escape(LEGAL)}</footer>
    <div class="fs-mark">FleetSheet</div>
    """
    actions = (
        f'<button onclick="window.print()">Print / Save PDF</button>'
        f'<a href="/credit">Back</a>'
    )
    return _sheet(f"Credit memo {cm['cm_no']}", body, actions)


def html_quote(con, quote_no: str):
    pack = engine.quote_pack(con, quote_no)
    if not pack:
        return None
    q, tot = pack["q"], pack["tot"]
    co = con.execute("SELECT * FROM company WHERE id=1").fetchone()
    rows = "".join(
        f"<tr><td>{html.escape(L['kind'])}</td><td>{html.escape(L['description'])}</td>"
        f"<td>{float(L['qty']):.2f} × ${float(L['rate']):,.2f}</td>"
        f"<td style='text-align:right'>${float(L['amount']):,.2f}</td></tr>"
        for L in pack["lines"]
    ) or "<tr><td colspan=4>No lines.</td></tr>"
    co_rows = ""
    for block in pack["cos"]:
        if block["header"]["status"] != "Issued":
            continue
        co_rows += f"<tr><td colspan=4><b>{html.escape(block['header']['co_no'])}</b> {html.escape(block['header']['reason'])}</td></tr>"
        for L in block["lines"]:
            sign = "+" if L["direction"] == "add" else "−"
            co_rows += (
                f"<tr><td>{sign} {html.escape(L['kind'])}</td><td>{html.escape(L['description'])}</td>"
                f"<td>{float(L['qty']):.2f} × ${float(L['rate']):,.2f}</td>"
                f"<td style='text-align:right'>{sign}${float(L['amount']):,.2f}</td></tr>"
            )
    body = _head(
        co, "QUOTE", q["quote_no"], q["account_name"],
        [q.get("bill_to") or "", q.get("city_st") or "", f"Job: {q.get('job_name') or ''}", f"PO: {q.get('po') or ''}"],
    ) + f"""
    <p>Date {html.escape(str(q['quote_date'])[:10])} · Valid until {html.escape(str(q.get('valid_until') or '')[:10] or '—')} · {html.escape(q['status'])}</p>
    <table><tr><th>Type</th><th>Detail</th><th>Qty × rate</th><th>Amount</th></tr>{rows}{co_rows}</table>
    <table class="tot">
      <tr><td></td><td class="n">Quoted</td><td class="n">${tot['quoted']:,.2f}</td></tr>
      <tr><td></td><td class="n">Change orders</td><td class="n">${tot['co_add'] - tot['co_sub']:,.2f}</td></tr>
      <tr><td></td><td class="n">Face</td><td class="n">${tot['face']:,.2f}</td></tr>
    </table>
    <p>{html.escape(q.get('notes') or '')}</p>
    <p>Estimate only. Invoice follows actual rental days and completed work orders.</p>
    <div class="sign"><div>Yard</div><div>Customer acceptance</div></div>
    <footer class="legal">{html.escape(LEGAL)}</footer>
    """
    actions = (
        f'<button onclick="window.print()">Print / Save PDF</button>'
        f'<a href="/quote/{html.escape(quote_no)}">Back</a>'
    )
    return _sheet(f"Quote {quote_no}", body, actions)


def html_change(con, co_no: str):
    co = con.execute("SELECT * FROM change_orders WHERE co_no=?", (co_no,)).fetchone()
    if not co:
        return None
    pack = engine.quote_pack(con, co["quote_no"])
    q = pack["q"] if pack else {"account_name": "", "quote_no": co["quote_no"]}
    company = con.execute("SELECT * FROM company WHERE id=1").fetchone()
    lines = con.execute("SELECT * FROM change_order_lines WHERE co_no=? ORDER BY line_id", (co_no,)).fetchall()
    rows = "".join(
        f"<tr><td>{html.escape(L['direction'])}</td><td>{html.escape(L['kind'])}</td>"
        f"<td>{html.escape(L['description'])}</td>"
        f"<td style='text-align:right'>${float(L['amount']):,.2f}</td></tr>"
        for L in lines
    )
    body = _head(
        company, "CHANGE ORDER", co["co_no"], q.get("account_name") or "",
        [f"Quote {co['quote_no']}", co["reason"]],
    ) + f"""
    <p>Date {html.escape(str(co['co_date'])[:10])} · {html.escape(co['status'])}</p>
    <table><tr><th>Dir</th><th>Type</th><th>Detail</th><th>Amount</th></tr>{rows}</table>
    <p>{html.escape(co['notes'] or '')}</p>
    <p>Amends the quote face. Does not rewrite a posted invoice.</p>
    <div class="sign"><div>Yard</div><div>Customer acknowledgement</div></div>
    <footer class="legal">{html.escape(LEGAL)}</footer>
    """
    actions = (
        '<button onclick="window.print()">Print / Save PDF</button>'
        '<a href="/changes">Back</a>'
    )
    return _sheet(f"Change order {co_no}", body, actions)


def html_petty(con) -> str:
    book = engine.petty_book(con)
    co = con.execute("SELECT * FROM company WHERE id=1").fetchone()
    rows = "".join(
        f"<tr><td>{html.escape(r['txn_date'])}</td><td>{html.escape(r['pc_id'])}</td>"
        f"<td>{html.escape(r['category'])}</td><td>{html.escape(r['payee'])}</td>"
        f"<td style='text-align:right'>${r['signed']:,.2f}</td>"
        f"<td style='text-align:right'>${r['running']:,.2f}</td></tr>"
        for r in book["rows"]
    ) or "<tr><td colspan=6>Empty box.</td></tr>"
    body = _head(
        co, "PETTY CASH REGISTER", "Box", co["name"],
        [f"In the box ${book['balance']:,.2f}", f"Target float ${book['target']:,.2f}"],
    ) + f"""
    <table><tr><th>Date</th><th>ID</th><th>Category</th><th>Payee</th><th>Amount</th><th>Running</th></tr>{rows}</table>
    <table class="tot">
      <tr><td></td><td class="n">Balance</td><td class="n">${book['balance']:,.2f}</td></tr>
      <tr><td></td><td class="n">To replenish</td><td class="n">${book['to_replenish']:,.2f}</td></tr>
    </table>
    <footer class="legal">{html.escape(LEGAL)}</footer>
    """
    actions = (
        '<button onclick="window.print()">Print / Save PDF</button>'
        '<a href="/petty">Back</a>'
    )
    return _sheet("Petty cash register", body, actions)


def html_done(con, period: str = "week") -> str:
    """Printable done-log: explicit completions + payments collected, this
    today/week/year. Answers 'what did I do this week?' on paper."""
    if period not in ("today", "week", "year"):
        period = "week"
    start, end, label = engine.done_period(con, period)
    co = con.execute("SELECT * FROM company WHERE id=1").fetchone()
    tasks = engine.done_tasks(con, start, end)
    pays = engine.done_payments(con, start, end)
    trows = "".join(
        f"<tr><td>{html.escape((t['done_at'] or '')[:16])}</td>"
        f"<td>{html.escape(t['text'])}</td>"
        f"<td>{html.escape(t['tier'])}</td>"
        f"<td>{html.escape(t['done_by'] or '—')}</td></tr>"
        for t in tasks) or "<tr><td colspan=4>Nothing logged.</td></tr>"
    prows = "".join(
        f"<tr><td>{html.escape((p['pay_date'] or '')[:16])}</td>"
        f"<td>{html.escape(p['invoice_no'])}</td>"
        f"<td>{html.escape(p['account_name'])}</td>"
        f"<td style='text-align:right'>${p['amount']:,.2f}</td>"
        f"<td>{html.escape(p['clerk'] or '—')}</td></tr>"
        for p in pays) or "<tr><td colspan=5>No payments collected.</td></tr>"
    ptotal = sum(p["amount"] for p in pays)
    body = _head(
        co, "DONE LOG", label, co["name"],
        [f"{start} to {end}", f"{len(tasks)} completed",
         f"{len(pays)} payments collected — ${ptotal:,.2f}"],
    ) + f"""
    <h3>Completed ({len(tasks)})</h3>
    <table><tr><th>When</th><th>Task</th><th>Tier</th><th>By</th></tr>{trows}</table>
    <h3>Payments collected ({len(pays)}) — ${ptotal:,.2f}</h3>
    <table><tr><th>When</th><th>Invoice</th><th>Customer</th>
    <th style='text-align:right'>Amount</th><th>By</th></tr>{prows}</table>
    <div class="sign"><div>Yard / prepared</div><div>Received</div></div>
    <footer class="legal">{html.escape(LEGAL)}</footer>
    """
    actions = (
        '<button onclick="window.print()">Print / Save PDF</button>'
        f'<a href="/done?period={period}">Back</a>'
    )
    return _sheet(f"Done log — {label}", body, actions)


def ticket_pack(con, ticket_id: str) -> dict | None:
    t = con.execute(
        """SELECT t.*, c.account_name, c.bill_to, c.phone, c.city_st,
                  a.unit_no, a.description, a.serial_no,
                  s.site_name, s.operator, s.rig_name
           FROM tickets t
           JOIN customers c ON c.customer_id = t.customer_id
           JOIN assets a ON a.asset_id = t.asset_id
           JOIN sites s ON s.site_id = t.site_id
           WHERE t.ticket_id=?""",
        (ticket_id,),
    ).fetchone()
    if not t:
        return None
    co = con.execute("SELECT * FROM company WHERE id=1").fetchone()
    m = engine.ticket_money(con, ticket_id)
    return {"t": t, "co": co, "m": m}


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
table {{ width:100%; border-collapse:collapse; margin:12px 0; }}
th {{ background:#1B2A4A; color:#fff; text-align:left; padding:6px 8px; font-size:11px; }}
td {{ border-bottom:1px solid #e5e7eb; padding:6px 8px; vertical-align:top; }}
.tot td {{ border:0; }}
.tot .n {{ text-align:right; font-weight:700; }}
.sign {{ display:grid; grid-template-columns:1fr 1fr; gap:32px; margin-top:36px; }}
.sign div {{ border-top:1px solid #1a1a1a; padding-top:6px; font-size:11px; color:#5C6B7A; }}
footer.legal {{ margin-top:28px; font-size:9px; color:#5C6B7A; border-top:1px solid #d0d5dd; padding-top:8px; }}
.fs-mark {{ text-align:right; font-size:9px; letter-spacing:.12em; color:#1B2A4A; opacity:.28; margin-top:4px; }}
@media print {{
  .bar {{ display:none; }}
  .page {{ margin:0; max-width:none; }}
  a {{ color:#000; text-decoration:none; }}
}}
</style></head>
<body>
<div class="bar"><span>{actions}</span></div>
<div class="page">{body}</div>
</body></html>"""


def _head(co, title, docno, cust_name, cust_bits):
    bits = "<br>".join(html.escape(x) for x in cust_bits if x)
    return f"""
    <div class="head">
      <div>
        <div style="font-weight:700;color:#1B2A4A">{html.escape(co['name'])}</div>
        <div>{html.escape(co['address'] or '')}<br>{html.escape(co['phone'] or '')}<br>{html.escape(co['billing_email'] or '')}</div>
      </div>
      <div>
        <h1 style="margin:0">{html.escape(title)}</h1>
        <div style="font-size:18px;font-weight:700">{html.escape(docno)}</div>
        <div class="cust"><span>Bill to / job</span>
          <b>{html.escape(cust_name)}</b><br>{bits}
        </div>
      </div>
    </div>"""


def html_invoice(pack) -> str:
    inv, co, tot, lines = pack["inv"], pack["co"], pack["tot"], pack["lines"]
    jb = pack.get("job") or {}
    _taxline = ("<div>Tax Exempt Cert <b>&#10003; on file</b></div>"
                if jb.get("tax_exempt") else "")
    po_disp = (inv['po'] if 'po' in inv.keys() and inv['po'] else '—')
    if 'po_cost_code' in inv.keys() and inv['po_cost_code']:
        po_disp += f" · cost code {inv['po_cost_code']}"
    rows = "".join(
        f"<tr><td>{html.escape(L['kind'])}<br><small>{html.escape(L['id'])}</small></td>"
        f"<td>{html.escape(L['detail'])}<br><small>{html.escape(L['when'])}</small></td>"
        f"<td style='text-align:right'>${L['amount']:,.2f}</td></tr>"
        for L in lines
    ) or "<tr><td colspan=3>No lines.</td></tr>"
    cust_bits = "<br>".join(html.escape(x) for x in [
        inv["bill_to"], inv["bill_street"], inv["bill_street2"], inv["city_st"],
        inv["phone"], inv["email"], f"Terms: {inv['terms']}",
        f"Customer PO: {po_disp}"] if x)
    # Invoice header: company (small) + Bill-to block upper left; INVOICE title
    # + number (large, bold) top right with the job info box below it.
    # Built inline — _head stays untouched for the other documents.
    invhead = f"""
    <div class="head">
      <div>
        <div style="font-weight:700;color:#1B2A4A">{html.escape(co['name'])}</div>
        <div style="font-size:12px">{html.escape(co['address'] or '')}<br>{html.escape(co['phone'] or '')}<br>{html.escape(co['billing_email'] or '')}</div>
        <div class="cust" style="margin-top:10px"><span>Bill to</span>
          <b>{html.escape(inv['account_name'])}</b><br>{cust_bits}
        </div>
      </div>
      <div style="text-align:right">
        <h1 style="margin:0">INVOICE</h1>
        <div style="font-size:22px;font-weight:700">{html.escape(inv['invoice_no'])}</div>
        <div style="border:1px solid #c9a227;border-radius:8px;padding:10px 14px;
                    background:#fffdf5;min-width:230px;margin-top:10px;font-size:14px;text-align:left">
          <div style="font-weight:700;color:#1B2A4A;margin-bottom:6px">Job info</div>
          <div>PO# <b>{html.escape(jb.get('po') or '') or '&mdash;'}</b></div>
          <div>Well# <b>{html.escape(', '.join(jb.get('wells') or [])) or '&mdash;'}</b></div>
          <div>Job Location <b>{html.escape(', '.join(jb.get('locations') or [])) or '&mdash;'}</b></div>
          {_taxline}
        </div>
      </div>
    </div>"""
    body = invhead + f"""
    <div style="clear:both"></div>
    <p>Invoice date {html.escape(str(inv['invoice_date'])[:10])} · Status {html.escape(inv['status'])}
       · PO {html.escape(po_disp)}</p>
    <table><tr><th>Type</th><th>Detail</th><th>Amount</th></tr>{rows}</table>
    <table class="tot">
      <tr><td></td><td class="n">Subtotal</td><td class="n">${tot['subtotal']:,.2f}</td></tr>
      <tr><td></td><td class="n">Tax</td><td class="n">${tot['tax']:,.2f}</td></tr>
      <tr><td></td><td class="n">Total</td><td class="n">${tot['total']:,.2f}</td></tr>
      <tr><td></td><td class="n">Cash / petty cash</td><td class="n">${tot.get('cash', tot['paid']):,.2f}</td></tr>
      <tr><td></td><td class="n">Credit memos</td><td class="n">${tot.get('credit', 0):,.2f}</td></tr>
      <tr><td></td><td class="n">Applied</td><td class="n">${tot['paid']:,.2f}</td></tr>
      <tr><td></td><td class="n">Balance due</td><td class="n">${tot['balance']:,.2f}</td></tr>
    </table>
    {_invoice_paperwork_html(pack.get("docs") or [])}
    <div class="sign"><div>Yard / prepared</div><div>Customer receipt</div></div>
    <footer class="legal">{html.escape(LEGAL)}</footer>
    <div class="fs-mark">FleetSheet</div>
    """
    actions = (
        f'<button onclick="window.print()">Print / Save PDF</button>'
        f'<a href="/print/invoice/{html.escape(inv["invoice_no"])}.pdf">Download PDF file</a>'
        f'<a href="/invoices">Back</a>'
    )
    return _sheet(f"Invoice {inv['invoice_no']}", body, actions)


def _invoice_paperwork_html(docs) -> str:
    """Attached PO scan / tax-exempt certificate on the printed invoice.
    Images embed inline; PDF and text documents are listed — their full
    pages ride in the PDF pack download."""
    if not docs:
        return ""
    imgs = "".join(
        f"<div style='page-break-inside:avoid;margin:14px 0'>"
        f"<b>{html.escape(d['title'])}</b> "
        f"<span style='font-size:10px;color:#5C6B7A'>{html.escape(d['kind'])} · {html.escape(d['filename'])}</span><br>"
        f"<img src=\"{d['data_uri']}\" style='max-width:100%;max-height:9in;border:1px solid #d0d5dd;margin-top:6px'>"
        f"</div>"
        for d in docs if d["data_uri"])
    others = "".join(
        f"<tr><td><b>{html.escape(d['title'])}</b></td><td>{html.escape(d['kind'])}</td>"
        f"<td>{html.escape(d['filename'])}</td><td>{d['size_kb']:.0f} KB</td></tr>"
        for d in docs if not d["data_uri"])
    table = (f"<table><tr><th>Document</th><th>Type</th><th>File</th><th>Size</th></tr>{others}</table>"
             f"<p class='hint'>Full pages are included in the invoice PDF download — one file, one print.</p>"
             if others else "")
    return f"<h1>Attached paperwork</h1>{table}{imgs}"


def html_ticket(pack, kind: str) -> str:
    t, co, m = pack["t"], pack["co"], pack["m"]
    title = "WORK TICKET" if kind == "work" else "DELIVERY TICKET"
    sig = (
        '<div class="sign"><div>Dispatched by</div><div>Received by — print / sign / date</div></div>'
        if kind == "delivery"
        else '<div class="sign"><div>Yard / mechanic</div><div>Customer / operator</div></div>'
    )
    body = _head(
        co, title, t["ticket_id"], t["account_name"],
        [t["bill_to"], t["city_st"], t["phone"], f"Job: {t['job_name'] or ''}", f"Site: {t['site_name']}"],
    ) + f"""
    <table>
      <tr><th>Unit</th><th>Serial</th><th>Site / rig</th><th>Fit</th></tr>
      <tr><td>{html.escape(t['unit_no'])}<br>{html.escape(t['description'] or '')}</td>
          <td>{html.escape(t['serial_no'] or '')}</td>
          <td>{html.escape(t['site_name'] or '')}<br>{html.escape(t['operator'] or '')} {html.escape(t['rig_name'] or '')}</td>
          <td>{html.escape(m.get('fit') or '')}</td></tr>
    </table>
    <table>
      <tr><th>On rent</th><th>Off rent</th><th>Rate</th><th>Days</th><th>Status</th></tr>
      <tr><td>{html.escape(str(t['on_rent'])[:10])}</td>
          <td>{html.escape(str(t['off_rent'] or '—')[:10])}</td>
          <td>{html.escape(t['rate_type'])} ${m['rate']:,.2f}</td>
          <td>{m['days']}</td>
          <td>{html.escape(t['status'])}</td></tr>
    </table>
    <table>
      <tr><th>Who transports</th><th>Possession</th><th>Tax situs</th></tr>
      <tr>
        <td>{"Customer" if m.get("customer_transport") else "Company"}</td>
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
          <td>{html.escape(str(t['out_by'] if 'out_by' in t.keys() else '') or '')} {html.escape(str(t['out_at'] if 'out_at' in t.keys() else '') or '')}</td>
          <td>{html.escape(str(t['out_note'] if 'out_note' in t.keys() else '') or '')}</td></tr>
      <tr><td>In</td><td>{html.escape(str(t['in_condition'] if 'in_condition' in t.keys() else '') or '—')}</td>
          <td>{html.escape(str(t['in_meter'] if 'in_meter' in t.keys() else '') or '')}</td>
          <td>{html.escape(str(t['in_by'] if 'in_by' in t.keys() else '') or '')} {html.escape(str(t['in_at'] if 'in_at' in t.keys() else '') or '')}</td>
          <td>{html.escape(str(t['in_note'] if 'in_note' in t.keys() else '') or '')}</td></tr>
    </table>
    {"" if m.get("transport", 0) <= 0 else f'''<table>
      <tr><th>Transportation</th><th>Amount</th></tr>
      <tr><td>Mob</td><td style="text-align:right">${m.get("mob", 0):,.2f}</td></tr>
      <tr><td>Demob</td><td style="text-align:right">${m.get("demob", 0):,.2f}</td></tr>
      <tr><td>Transportation fee</td><td style="text-align:right">${m.get("transport_fee", 0):,.2f}</td></tr>
      <tr><td><b>Transportation total</b></td><td style="text-align:right"><b>${m.get("transport", 0):,.2f}</b></td></tr>
    </table>'''}
    {"<p><b>Estimated ticket total (not an invoice): $%s</b></p>" % f"{m['total']:,.2f}" if kind=="work" else "<p>Delivery acknowledgement. Receiver confirms who took possession and where. Transportation and tax follow this ticket onto the invoice.</p>"}
    {sig}
    <footer class="legal">{html.escape(LEGAL)}</footer>
    <div class="fs-mark">FleetSheet</div>
    """
    actions = (
        f'<button onclick="window.print()">Print / Save PDF</button>'
        f'<a href="/print/{kind}/{html.escape(t["ticket_id"])}.pdf">Download PDF file</a>'
        f'<a href="/ticket/{html.escape(t["ticket_id"])}">Back</a>'
    )
    return _sheet(f"{title} {t['ticket_id']}", body, actions)


def _pdf_header_flow(co, styles):
    return [Paragraph(
        f"<b>{co['name']}</b><br/>{co['address'] or ''}<br/>{co['phone'] or ''} · {co['billing_email'] or ''}",
        styles["Normal"],
    )]


def pdf_invoice(pack) -> bytes:
    if not HAS_PDF:
        raise RuntimeError("pip install reportlab")
    inv, co, tot, lines = pack["inv"], pack["co"], pack["tot"], pack["lines"]
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=0.6 * inch, rightMargin=0.6 * inch,
                            topMargin=0.5 * inch, bottomMargin=0.6 * inch)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Doc", fontSize=16, textColor=colors.HexColor("#1B2A4A"), leading=20, spaceAfter=6))
    styles.add(ParagraphStyle(name="Tiny", fontSize=7, textColor=colors.HexColor("#5C6B7A"), leading=9))
    story = []
    left = _pdf_header_flow(co, styles)
    # Street lines print only when used — a blank line 2 stays off the page.
    street_html = "".join(
        f"{html.escape(s)}<br/>"
        for s in (inv["bill_street"], inv["bill_street2"])
        if (s or "").strip()
    )
    right = Paragraph(
        f"<b>INVOICE</b><br/>{inv['invoice_no']}<br/>{str(inv['invoice_date'])[:10]}<br/>"
        f"<br/><b>Bill to</b><br/>{inv['account_name']}<br/>{inv['bill_to'] or ''}<br/>"
        f"{street_html}{inv['city_st'] or ''}<br/>Terms: {inv['terms']}",
        styles["Normal"],
    )
    story.append(Table([[left, right]], colWidths=[3.6 * inch, 3.6 * inch]))
    story.append(Spacer(1, 12))
    # Upper-right job box: PO#, Well#, Job Location — the three things
    # required to get paid — plus Tax Exempt Cert when the job is exempt.
    # PO expiry is record data and never appears on the printed invoice.
    jb = pack.get("job") or {}
    boxdata = [
        ["PO#", jb.get("po") or "—"],
        ["Well#", ", ".join(jb.get("wells") or []) or "—"],
        ["Job Location", ", ".join(jb.get("locations") or []) or "—"],
    ]
    if jb.get("tax_exempt"):
        boxdata.append(["Tax Exempt Cert", "on file"])
    boxtab = Table(boxdata, colWidths=[1.4 * inch, 2.2 * inch])
    boxtab.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#c9a227")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#fffdf5")),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(Table([["", boxtab]], colWidths=[3.6 * inch, 3.6 * inch]))
    story.append(Spacer(1, 12))
    data = [["Type", "Detail", "Amount"]]
    for L in lines:
        data.append([L["kind"], f"{L['id']}\n{L['detail']}\n{L['when']}", f"${L['amount']:,.2f}"])
    data.append(["", "Subtotal", f"${tot['subtotal']:,.2f}"])
    data.append(["", "Tax", f"${tot['tax']:,.2f}"])
    data.append(["", "Total", f"${tot['total']:,.2f}"])
    data.append(["", "Paid", f"${tot['paid']:,.2f}"])
    data.append(["", "Balance due", f"${tot['balance']:,.2f}"])
    tbl = Table(data, colWidths=[1.1 * inch, 4.6 * inch, 1.5 * inch])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1B2A4A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (2, 1), (2, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, 0), 0.3, colors.HexColor("#1B2A4A")),
        ("LINEBELOW", (0, 1), (-1, -6), 0.2, colors.HexColor("#e5e7eb")),
        ("FONTNAME", (1, -5), (-1, -1), "Helvetica-Bold"),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 28))
    # Attached paperwork rides with the invoice: images print inline, PDF
    # and text documents merge as real pages below.
    from reportlab.platypus import Image as RLImage
    for d in pack.get("docs") or []:
        if d.get("blob"):
            story.append(Spacer(1, 8))
            story.append(Paragraph(
                f"<b>{d['title']}</b>  {d['kind']} · {d['filename']}",
                styles["Normal"]))
            story.append(RLImage(BytesIO(d["blob"]), width=6.5 * inch,
                                 height=6.5 * inch, kind="proportional"))
    story.append(Table([["Yard / prepared ________________", "Customer ________________"]], colWidths=[3.6 * inch, 3.6 * inch]))
    story.append(Spacer(1, 16))
    story.append(Paragraph(LEGAL, styles["Tiny"]))
    doc.build(story)
    return _merge_doc_pages(buf.getvalue(), pack.get("docs") or [])


def pdf_ticket(pack, kind: str) -> bytes:
    if not HAS_PDF:
        raise RuntimeError("pip install reportlab")
    t, co, m = pack["t"], pack["co"], pack["m"]
    title = "WORK TICKET" if kind == "work" else "DELIVERY TICKET"
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=0.6 * inch, rightMargin=0.6 * inch,
                            topMargin=0.5 * inch, bottomMargin=0.6 * inch)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Tiny", fontSize=7, textColor=colors.HexColor("#5C6B7A"), leading=9))
    left = _pdf_header_flow(co, styles)
    right = Paragraph(
        f"<b>{title}</b><br/>{t['ticket_id']}<br/><br/><b>{t['account_name']}</b><br/>"
        f"{t['city_st'] or ''}<br/>{t['site_name'] or ''}",
        styles["Normal"],
    )
    story = [Table([[left, right]], colWidths=[3.6 * inch, 3.6 * inch]), Spacer(1, 12)]
    data = [
        ["Unit", t["unit_no"], t["description"] or ""],
        ["Serial", t["serial_no"] or "", ""],
        ["On / off", str(t["on_rent"])[:10], str(t["off_rent"] or "open")[:10]],
        ["Rate / days", f"{t['rate_type']} ${m['rate']:,.2f}", str(m["days"])],
        ["Fit / status", m.get("fit") or "", t["status"]],
        ["Transport", "Customer" if m.get("customer_transport") else "Company", m.get("possession_label") or ""],
        ["Tax situs", m.get("tax_name") or "", f"{m.get('tax_rate', 0):.4f}" + (" exempt" if m.get("tax_exempt") else "")],
    ]
    if m.get("transport", 0) > 0:
        data.append(["Transportation", f"Mob ${m.get('mob', 0):,.2f} · Demob ${m.get('demob', 0):,.2f}", f"${m.get('transport', 0):,.2f}"])
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
    story.append(tbl)
    story.append(Spacer(1, 10))
    if kind == "work":
        story.append(Paragraph(f"Estimated ticket total (not an invoice): <b>${m['total']:,.2f}</b>", styles["Normal"]))
    else:
        story.append(Paragraph(
            (m.get("tax_note") or "") + " Delivery acknowledgement. Receiver confirms who took possession and where. Transportation and tax follow this ticket onto the invoice.",
            styles["Normal"],
        ))
    story.append(Spacer(1, 28))
    story.append(Table(
        [["Dispatched / yard ________________", "Received by ________________"]],
        colWidths=[3.6 * inch, 3.6 * inch],
    ))
    story.append(Spacer(1, 16))
    story.append(Paragraph(LEGAL, styles["Tiny"]))
    doc.build(story)
    return buf.getvalue()


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
    d = SimpleDocTemplate(buf, pagesize=letter,
                          leftMargin=0.7 * inch, rightMargin=0.7 * inch,
                          topMargin=0.6 * inch, bottomMargin=0.6 * inch)
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


def _merge_doc_pages(base_pdf: bytes, docs) -> bytes:
    """Append attached documents' real pages to the pack PDF.

    PDF docs contribute their own pages; text docs are rendered as pages.
    Images are already embedded inline in the base pack. Each document is
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


def compliance_pack(con, aid: str, eqc_ids=None, doc_ids=None) -> dict | None:
    """Everything a printed compliance pack needs for one unit.

    eqc_ids / doc_ids optionally narrow the pack to selected checks and
    documents (the selective print). None means the whole package.
    """
    co = con.execute("SELECT * FROM company WHERE id=1").fetchone()
    unit = con.execute("SELECT * FROM assets WHERE asset_id=?", (aid,)).fetchone()
    if not unit:
        return None
    # None = whole category (the one-button pack). A list = exactly those ids,
    # even when empty: ticking only checks prints no documents, and vice versa.
    # Passing either list selects "selective mode": the other category then
    # defaults to empty rather than whole.
    selective = eqc_ids is not None or doc_ids is not None
    want_items = set(eqc_ids) if eqc_ids is not None else (set() if selective else None)
    want_docs = set(doc_ids) if doc_ids is not None else (set() if selective else None)
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
            "last_done": it["last_done"] or "—",
            "last_result": last.get("result") or "—",
            "last_evidence": last.get("evidence") or "",
            "last_clerk": last.get("clerk") or "",
            "next_due": (it["next_due_live"].isoformat()
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
            "uploaded": str(d["uploaded_at"] or "")[:10],
            "data_uri": _doc_data_uri(mime, blob),
            "blob": blob if mime.startswith("image/") else b"",
            "merge_blob": blob if (mime == "application/pdf"
                                   or mime.startswith("text/")) else b"",
        })
    return {
        "co": co, "unit": dict(unit), "items": items, "docs": docs,
        "summary": engine.compliance_summary(con, aid),
        # Cert identity (Q5): the pack's cert section shows the asset's real
        # cert records — each one naming this unit. Selective tick-printing
        # covers checks/docs; the full pack carries the cert records.
        "certs": [] if selective else engine.list_certs(con, aid),
        "selected": selective,
        "printed": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def fleet_compliance_pack(con) -> dict:
    """Fleet-wide compliance summary for the one-button fleet print."""
    co = con.execute("SELECT * FROM company WHERE id=1").fetchone()
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
        "printed": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def _compliance_head(co, title, docno, sub):
    return f"""
    <div class="head">
      <div>
        <div style="font-weight:700;color:#1B2A4A">{html.escape(co['name'])}</div>
        <div>{html.escape(co['address'] or '')}<br>{html.escape(co['phone'] or '')}<br>{html.escape(co['billing_email'] or '')}</div>
      </div>
      <div>
        <h1 style="margin:0">{html.escape(title)}</h1>
        <div style="font-size:18px;font-weight:700">{html.escape(docno)}</div>
        <div class="cust"><span>Printed</span><b>{html.escape(sub)}</b></div>
      </div>
    </div>"""


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
            f"<td>{html.escape(c['expiry_date'] or '—')}</td>"
            f"<td>{html.escape(c['status'])}</td>"
            f"<td>{html.escape(c['doc_title'] or ('attached' if c.get('evidence_doc_id') else '—'))}</td>"
            f"<td>{html.escape(c['clerk'] or '')}</td></tr>"
            for c in pack["certs"])
        certs_html = (f"<h1>Certifications &amp; calibrations</h1>"
                      f"<table><tr><th>Kind / Title</th><th>Cert #</th><th>Issuer</th>"
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
                     f"{tablerows}</table>"
                     f"<p class='hint'>PDF and text documents are listed above — their full pages are included in the Pack PDF download, one file, one print.</p>")
        docs += imgs
    else:
        docs = "<h1>Data book</h1><p class='hint'>No documents selected.</p>"
    body = (_compliance_head(co, title, unit["unit_no"], pack["printed"])
            + f"<p>{html.escape(unit['description'] or '')} — {badge} ({s['total']} checks)</p>"
            + certs_html
            + f"<h1>Checklist</h1>" + checks + docs
            + '<div class="sign"><div>Prepared by / signature</div><div>Date</div></div>'
            + f'<footer class="legal">{html.escape(LEGAL)}</footer>')
    return _sheet(title + " " + unit["unit_no"], body,
                 actions=(f'<a href="/print/compliance/{html.escape(unit["asset_id"])}.pdf">PDF</a>'
                          '<button onclick="window.print()">Print</button>'))


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
    body = (_compliance_head(co, "Fleet compliance pack", "All units", pack["printed"])
            + f"<table><tr><th>Unit</th><th>Status</th><th>Checks</th><th>Data book</th>"
            f"<th>Certs</th></tr>{rows}</table>"
            + '<div class="sign"><div>Prepared by / signature</div><div>Date</div></div>'
            + f'<footer class="legal">{html.escape(LEGAL)}</footer>')
    return _sheet("Fleet compliance pack", body,
                 actions=('<a href="/print/compliance/fleet.pdf">PDF</a>'
                          '<button onclick="window.print()">Print</button>'))


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
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.pagesizes import letter
    co, unit = pack["co"], pack["unit"]
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=0.6 * inch, rightMargin=0.6 * inch,
                            topMargin=0.5 * inch, bottomMargin=0.6 * inch)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Doc", fontSize=16, textColor=colors.HexColor("#1B2A4A"), leading=20, spaceAfter=6))
    styles.add(ParagraphStyle(name="Tiny", fontSize=7, textColor=colors.HexColor("#5C6B7A"), leading=9))
    sel = " (selected)" if pack.get("selected") else ""
    story = [Paragraph(f"<b>COMPLIANCE PACK{sel}</b> — {unit['unit_no']}<br/>Printed {pack['printed']}", styles["Doc"])]
    story.extend(_pdf_header_flow(co, styles))
    story.append(Spacer(1, 12))
    story.append(Paragraph(f"<b>{unit['description'] or ''}</b>", styles["Normal"]))
    if pack.get("certs"):
        cdata = [["Kind", "Certificate", "Expires", "Status", "Evidence"]]
        for c in pack["certs"]:
            cdata.append([
                c["kind_label"],
                f"{c['title']}\n{c['cert_number'] or ''} {c['issuer'] or ''}".strip(),
                c["expiry_date"] or "—",
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
        story.append(Paragraph("<b>Certifications &amp; calibrations</b>", styles["Normal"]))
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
    story.append(Paragraph("<b>Data book — attached documents</b>", styles["Normal"]))
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
    from reportlab.platypus import Image as RLImage
    for d in imgs:
        story.append(Spacer(1, 8))
        story.append(Paragraph(f"<b>{d['title']}</b>  {d['kind']} · {d['filename']}", styles["Normal"]))
        story.append(RLImage(BytesIO(d["blob"]), width=6.5 * inch, height=6.5 * inch, kind="proportional"))
    if not pack["docs"]:
        story.append(Paragraph("No documents attached.", styles["Normal"]))
    if listed:
        story.append(Paragraph("The full pages of each PDF and text document below follow this index — one download, one print.", styles["Tiny"]))
    story.append(Spacer(1, 28))
    story.append(Table([["Prepared / signature ________________", "Date ________________"]],
                       colWidths=[3.6 * inch, 3.6 * inch]))
    story.append(Spacer(1, 16))
    story.append(Paragraph(LEGAL, styles["Tiny"]))
    doc.build(story)
    return _merge_doc_pages(buf.getvalue(), pack["docs"])


def pdf_fleet_compliance_pack(pack) -> bytes:
    if not HAS_PDF:
        raise RuntimeError("pip install reportlab")
    from reportlab.lib.units import inch
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.pagesizes import letter
    co = pack["co"]
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=0.6 * inch, rightMargin=0.6 * inch,
                            topMargin=0.5 * inch, bottomMargin=0.6 * inch)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Doc", fontSize=16, textColor=colors.HexColor("#1B2A4A"), leading=20, spaceAfter=6))
    styles.add(ParagraphStyle(name="Tiny", fontSize=7, textColor=colors.HexColor("#5C6B7A"), leading=9))
    story = [Paragraph(f"<b>FLEET COMPLIANCE PACK</b><br/>Printed {pack['printed']}", styles["Doc"])]
    story.extend(_pdf_header_flow(co, styles))
    story.append(Spacer(1, 12))
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
    story.append(Table([["Prepared / signature ________________", "Date ________________"]],
                       colWidths=[3.6 * inch, 3.6 * inch]))
    story.append(Spacer(1, 16))
    story.append(Paragraph(LEGAL, styles["Tiny"]))
    doc.build(story)
    return buf.getvalue()


# ------------------------------------------------------- Weekly reports
# The three push-button reports: AR aging, fleet utilization, week's flow.
# HTML for browser Print / Save as PDF; PDF for a downloadable file.

def _money(v) -> str:
    try:
        return f"${float(v or 0):,.2f}"
    except (TypeError, ValueError):
        return "$0.00"


def _report_actions(pdf_href: str) -> str:
    return (f"<a href=\"{pdf_href}\">Download PDF</a>"
            "<button onclick=\"window.print()\">Print</button>")


def html_aging(con) -> str:
    rep = engine.ar_aging(con)
    co = con.execute("SELECT * FROM company WHERE id=1").fetchone()
    rows = "".join(
        f"<tr><td>{html.escape(r['customer'])}</td>"
        + "".join(f"<td class=n>{_money(r[b])}</td>" for b in engine.BUCKETS)
        + f"<td class=n><b>{_money(r['total'])}</b></td></tr>"
        for r in rep["rows"])
    total = "".join(f"<td class=n><b>{_money(rep['total'][b])}</b></td>" for b in engine.BUCKETS)
    pct = "".join(f"<td class=n>{rep['pct'][b]:.1f}%</td>" for b in engine.BUCKETS)
    heads = "".join(f"<th class=n>{html.escape(engine.BUCKET_LABELS[b])}</th>" for b in engine.BUCKETS)
    body = (f"<h1>AR aging — as of {html.escape(rep['today'])}</h1>"
            f"<table><tr><th>Customer</th>{heads}<th class=n>Total</th></tr>{rows}"
            f"<tr class=tot><td><b>TOTAL</b></td>{total}<td class=n><b>{_money(rep['grand'])}</b></td></tr>"
            f"<tr><td>% of Total</td>{pct}<td></td></tr></table>"
            f"<p class=mute>{html.escape(co['name'] or '')}</p>")
    return _sheet("AR aging", body, _report_actions("/print/report/aging.pdf"))


def html_fleet(con, days: int = 30) -> str:
    rep = engine.fleet_utilization(con, days)
    co = con.execute("SELECT * FROM company WHERE id=1").fetchone()
    rows = "".join(
        f"<tr><td><b>{html.escape(r['unit_no'])}</b><br><span class=mute>{html.escape(r['category'])}</span></td>"
        f"<td class=n>{r['rent_days']}</td><td class=n>{r['idle_days']}</td>"
        f"<td class=n>{r['down_days']}</td><td class=n>{r['util_pct']:.1f}%</td>"
        f"<td class=n>{_money(r['revenue'])}</td></tr>"
        for r in rep["rows"])
    body = (f"<h1>Fleet utilization — last {rep['days']} days</h1>"
            f"<p class=mute>{html.escape(rep['start'])} to {html.escape(rep['end'])}</p>"
            "<table><tr><th>Unit</th><th class=n>Days on rent</th><th class=n>Idle days</th>"
            "<th class=n>Down (shop)</th><th class=n>Util %</th><th class=n>Revenue</th></tr>"
            f"{rows}</table><p class=mute>{html.escape(co['name'] or '')}</p>")
    return _sheet("Fleet utilization", body,
                  _report_actions(f"/print/report/fleet.pdf?days={rep['days']}"))


def html_flow(con, span: str = "week") -> str:
    rep = engine.weeks_flow(con, span)
    co = con.execute("SELECT * FROM company WHERE id=1").fetchone()
    label = {k: lab for k, lab, _ in engine.FLOW_SECTIONS}
    sub = {k: s for k, _, s in engine.FLOW_SECTIONS}
    parts = [f"<h1>This week's flow</h1>" if rep["span"] == "week"
             else f"<h1>Flow — exceptions, next 30 days</h1>",
             f"<p class=mute>{html.escape(rep['start'])} to {html.escape(rep['end'])}</p>"]
    for key, items in rep["sections"]:
        rows = "".join(
            f"<tr><td>{html.escape(i['what'])}</td><td>{html.escape(i['who'])}</td>"
            f"<td>{html.escape(i['when'] or '')}</td>"
            + (f"<td>{html.escape(i.get('why') or '')}</td>" if rep["span"] == "month" else "")
            + "</tr>" for i in items) or "<tr><td colspan=4 class=mute>Nothing.</td></tr>"
        why = "<th>Why it flags</th>" if rep["span"] == "month" else ""
        parts.append(
            f"<h2 style='font-size:15px;color:var(--navy)'>{html.escape(label.get(key, key))} "
            f"<span class=mute>— {html.escape(sub.get(key, ''))}</span></h2>"
            f"<table><tr><th>What</th><th>Who</th><th>When</th>{why}</tr>{rows}</table>")
    parts.append(f"<p class=mute>{html.escape(co['name'] or '')}</p>")
    return _sheet("This week's flow", "".join(parts),
                  _report_actions(f"/print/report/flow.pdf?span={rep['span']}"))


def _pdf_report(title: str, subtitle: str, headers: list, rows: list,
                widths: list, fname: str, co) -> bytes:
    if not HAS_PDF:
        raise RuntimeError("pip install reportlab")
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=0.6 * inch,
                            rightMargin=0.6 * inch, topMargin=0.5 * inch,
                            bottomMargin=0.6 * inch)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Doc", fontSize=16,
                             textColor=colors.HexColor("#1B2A4A"), leading=20, spaceAfter=2))
    styles.add(ParagraphStyle(name="Sub", fontSize=9,
                             textColor=colors.HexColor("#5C6B7A"), leading=11, spaceAfter=8))
    story = [_pdf_header_flow(co, styles)[0],
             Paragraph(title, styles["Doc"]),
             Paragraph(subtitle, styles["Sub"])]
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
    doc.build(story)
    return buf.getvalue()


def pdf_aging(con) -> bytes:
    rep = engine.ar_aging(con)
    co = con.execute("SELECT * FROM company WHERE id=1").fetchone()
    headers = ["Customer"] + [engine.BUCKET_LABELS[b] for b in engine.BUCKETS] + ["Total"]
    rows = [[r["customer"]] + [_money(r[b]) for b in engine.BUCKETS] + [_money(r["total"])]
            for r in rep["rows"]]
    rows.append(["TOTAL"] + [_money(rep["total"][b]) for b in engine.BUCKETS] + [_money(rep["grand"])])
    rows.append(["% of Total"] + [f"{rep['pct'][b]:.1f}%" for b in engine.BUCKETS] + [""])
    return _pdf_report("AR aging", f"As of {rep['today']} · {co['name'] or ''}",
                       headers, rows, [2.2, 0.8, 0.8, 0.8, 0.8, 0.8, 0.9],
                       "ar-aging.pdf", co)


def pdf_fleet(con, days: int = 30) -> bytes:
    rep = engine.fleet_utilization(con, days)
    co = con.execute("SELECT * FROM company WHERE id=1").fetchone()
    headers = ["Unit", "Days on rent", "Idle days", "Down (shop)", "Util %", "Revenue"]
    rows = [[f"{r['unit_no']} ({r['category']})".strip(), str(r["rent_days"]),
             str(r["idle_days"]), str(r["down_days"]), f"{r['util_pct']:.1f}%",
             _money(r["revenue"])] for r in rep["rows"]]
    return _pdf_report("Fleet utilization",
                       f"Last {rep['days']} days · {rep['start']} to {rep['end']} · {co['name'] or ''}",
                       headers, rows, [2.4, 1.1, 1.1, 1.1, 0.9, 1.2],
                       "fleet-utilization.pdf", co)


def pdf_flow(con, span: str = "week") -> bytes:
    rep = engine.weeks_flow(con, span)
    co = con.execute("SELECT * FROM company WHERE id=1").fetchone()
    label = {k: lab for k, lab, _ in engine.FLOW_SECTIONS}
    title = "This week's flow" if rep["span"] == "week" else "Flow — exceptions, next 30 days"
    headers = ["Section", "What", "Who", "When"] + (["Why"] if rep["span"] == "month" else [])
    rows = []
    for key, items in rep["sections"]:
        for i in items:
            rows.append([label.get(key, key), i["what"], i["who"], i["when"] or ""]
                        + ([i.get("why") or ""] if rep["span"] == "month" else []))
    widths = [1.2, 2.6, 1.4, 0.9] + ([1.1] if rep["span"] == "month" else [])
    return _pdf_report(title, f"{rep['start']} to {rep['end']} · {co['name'] or ''}",
                       headers, rows, widths, "weeks-flow.pdf", co)
