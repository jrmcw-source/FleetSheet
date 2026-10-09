#!/usr/bin/env python3
"""FleetSheet local app. Open http://127.0.0.1:8765 — SQLite is the book."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import html
import json
import os
import socket
import threading
import time
import hmac
import webbrowser
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, quote_plus, urlparse

import engine
import printpack
import exportpack

CSS = """
:root { --frame:#2B3542; --gold:#E8B923; --ink:#1a1a1a; --mute:#5C6B7A; --bg:#f8f9fa; --ok:#0f7a43; --bad:#b42318; }
*{box-sizing:border-box} body{margin:0;font:15px/1.4 Calibri,Segoe UI,sans-serif;background:var(--bg);color:var(--ink)}
header{background:var(--frame);color:#fff;padding:8px 16px;display:flex;align-items:center;flex-wrap:wrap;gap:10px 16px}
header .brand{font-size:14px;margin-right:4px}
header nav.main{display:flex;flex-wrap:wrap;gap:4px 14px;align-items:center}
header nav.main a{padding:4px 8px;border-radius:4px}
header nav.main a.on{background:rgba(255,255,255,.16);font-weight:700}
header nav.aside{margin-left:auto;display:flex;gap:6px;align-items:center}
header a{color:#fff;text-decoration:none;font-size:13px;white-space:nowrap;position:relative}
header .navhome,header .navback{border:1px solid rgba(255,255,255,.35);padding:2px 6px;border-radius:3px;font-size:11px;opacity:.8}
header a[data-tip]::after,.tabs a[data-tip]::after{content:attr(data-tip);position:absolute;left:0;top:calc(100% + 8px);background:#1a1a1a;color:#fff;font-size:11px;line-height:1.35;font-weight:400;letter-spacing:0;padding:8px 10px;border-radius:4px;width:220px;white-space:normal;opacity:0;pointer-events:none;z-index:40;box-shadow:0 4px 12px rgba(0,0,0,.25);transition:opacity .12s linear}
header a[data-tip]:hover::after,.tabs a[data-tip]:hover::after,
button[data-tip]:hover::after,a.btn[data-tip]:hover::after{opacity:1;transition-delay:.7s}
button[data-tip],a.btn[data-tip]{position:relative}
button[data-tip]::after,a.btn[data-tip]::after{content:attr(data-tip);position:absolute;left:0;top:calc(100% + 8px);background:#1a1a1a;color:#fff;font-size:11px;line-height:1.35;font-weight:400;letter-spacing:0;padding:8px 10px;border-radius:4px;width:220px;white-space:normal;opacity:0;pointer-events:none;z-index:40;box-shadow:0 4px 12px rgba(0,0,0,.25);transition:opacity .12s linear}
body.notips [data-tip]::after{display:none !important}
main{max-width:1100px;margin:20px auto;padding:0 16px 48px}
.actions{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:12px 0}
.mark{position:fixed;bottom:8px;right:12px;font-size:11px;letter-spacing:.08em;color:#1B2A4A;opacity:.28;pointer-events:none;z-index:1}
.tabs{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 16px;padding-bottom:10px;border-bottom:1px solid #d0d5dd}
.tabs a{display:inline-block;padding:6px 10px;border-radius:4px;background:#fff;border:1px solid #d0d5dd;color:var(--frame);text-decoration:none;font-size:13px;position:relative}
.tabs a.on{background:var(--frame);color:#fff;border-color:var(--frame)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}
.card{background:#fff;border:1px solid #d0d5dd;border-radius:8px;padding:14px}
.card b{display:block;font-size:22px;color:var(--frame)}
.card span{color:var(--mute);font-size:12px;text-transform:uppercase}
form,table{background:#fff;border:1px solid #d0d5dd;border-radius:8px;padding:16px;width:100%}
label{display:block;font-size:12px;color:var(--mute);margin:10px 0 4px}
label:has(input[type=checkbox]){display:flex;align-items:center;gap:6px;font-size:14px;color:var(--ink,#222)}
input,select{width:100%;padding:8px;border:1px solid #c5cdd6;border-radius:4px;font:inherit}
input[type=checkbox]{width:auto;flex:0 0 auto}
.row{display:grid;grid-template-columns:1fr 1fr;gap:12px}
button,.btn{background:var(--frame);color:#fff;border:0;padding:10px 16px;border-radius:4px;cursor:pointer;font:inherit;display:inline-block;text-decoration:none}
.btn-gold{background:var(--gold);color:#2B3542;font-weight:700;border:0;padding:9px 16px;border-radius:6px;cursor:pointer;font:inherit;display:inline-block;text-decoration:none}
.btn-gold:hover{background:#d4a51f}
button.secondary{background:#fff;color:var(--frame);border:1px solid var(--frame)}
button.danger{background:var(--bad)}
.err{background:#fdecec;color:var(--bad);padding:10px;border-radius:6px;margin:12px 0}
.ok{background:#e7f3ec;color:var(--ok);padding:10px;border-radius:6px;margin:12px 0}
.backup-bar{display:flex;flex-wrap:wrap;align-items:center;gap:10px;padding:8px 12px;margin:0 0 16px;width:auto}
.backup-bar .backup-msg{flex:1 1 260px;font-size:13px}
.backup-bar input{width:140px;padding:6px 8px}
.backup-bar button{padding:6px 12px;font-size:13px}
table{border-collapse:collapse;padding:0}
th,td{padding:8px 10px;border-bottom:1px solid #eee;text-align:left;font-size:13px}
th{background:#e8eef4;color:var(--frame)}
.fail{color:#8a5a00;font-weight:700} /* routine negative: amber, not red (2026-10-06) */
.critical{color:var(--bad);font-weight:700} /* do-or-die only (2026-10-06) */
.pass{color:var(--ok)}
h1{font-size:20px;color:var(--frame)}
.hint{color:var(--mute);font-size:13px}
@media (max-width:640px){
  .row{grid-template-columns:1fr}
  table{display:block;overflow-x:auto;-webkit-overflow-scrolling:touch;white-space:nowrap}
  .backup-bar input{width:100%}
  header{gap:6px 10px;padding:8px 10px}
  header nav.main{flex-wrap:nowrap;overflow-x:auto;max-width:100%;padding-bottom:4px}
  header nav.aside{margin-left:0}
  .mark{display:none}
}
/* Yard device UI: big touch targets, minimal chrome. */
.yd{background:#f4f6f9;color:#1a1a1a;margin:0;font:17px/1.45 Calibri,Segoe UI,sans-serif}
.yd header{background:#1B2A4A;color:#fff;padding:12px 16px;font-size:18px;font-weight:700}
.yd main{max-width:640px;margin:0 auto;padding:12px 12px 48px}
.yd .trow{display:block;background:#fff;border:1px solid #d0d5dd;border-radius:10px;
  padding:16px;margin:10px 0;color:#1B2A4A;text-decoration:none;font-size:18px}
.yd .trow small{display:block;color:#5C6B7A;font-size:14px}
.yd button.big,.yd .bigbtn{display:block;width:100%;text-align:center;padding:18px;
  font-size:20px;margin:10px 0;border-radius:10px}
.yd form{background:#fff;border:1px solid #d0d5dd;border-radius:10px;padding:16px;margin:12px 0}
.yd label{font-size:14px}
.yd input,.yd select{font-size:18px;padding:12px}
.yd .stat{background:#fff;border:1px solid #d0d5dd;border-radius:10px;padding:12px;margin:8px 0}
.yd .qrbox{background:#fff;border:1px solid #d0d5dd;border-radius:10px;padding:20px;
  text-align:center;margin:16px 0;word-break:break-all}
.yd .code{font-family:monospace;font-size:14px;background:#eef1f5;padding:10px;border-radius:6px}
"""

"""FleetSheet views — accounting flow: quotes, invoices, payments, credit, petty cash, reports."""

from views_core import (
    format_phone,
    _ack_forms,
    page,
    tabs,
    tabs_reports,
    tabs_boards,
    weekly_tabs,
    tabs_setup,
    tabs_invoice,
    tabs_quotes,
    tabs_money,
    _cstat,
    _trigger_opts,
    opts,
    lan_urls,
    phone_card,
    _nav_section,
    _local_qr_img,
    money_val,
    quote_expiry_panel,
    task_nudge,
    more_link,
    DASH_CAP,
    view_button,
    AUDIT_TABLE_JS,
    news_strip,
    capped_table,
    combo_field,
    combo_opts,
    CoreViews,)



def _task_from_row(text, link, back):
    """Inline 'make it a task' form for audit rows: user picks the tier."""
    return (
        f"<form method='post' action='/today/task/from' style='display:inline;white-space:nowrap'>"
        f"<input type='hidden' name='text' value='{html.escape(text, quote=True)}'>"
        f"<input type='hidden' name='link' value='{html.escape(link, quote=True)}'>"
        f"<input type='hidden' name='back' value='{html.escape(back, quote=True)}'>"
        f"<select name='tier' title='Which stack' style='width:86px;font-size:11px;padding:2px'>"
        f"<option value='must'>Must</option>"
        f"<option value='can' selected>Can</option>"
        f"<option value='later'>Later</option></select> "
        f"<button class='mini' title='Put this on the Today list'>Task</button></form>"
    )


class AccountingViews(CoreViews):
    """FleetSheet views views mixed into Handler."""

    def _btn_row(self, save_label="Save", jobpop=None, add_item=False, extra=""):
        from views_core import CoreViews
        return CoreViews._btn_row(self, save_label, jobpop, add_item, extra)

    def _job_info_popup(self, pid, vals=None):
        from views_core import CoreViews
        return CoreViews._job_info_popup(self, pid, vals)
    def view_new_invoice(self, con):
        return tabs_money("invoice") + self._money_tab(con, "invoice", {})

    def _frag_invoice_form(self, con):
        ready = con.execute(
            """SELECT t.ticket_id, t.customer_id, c.account_name, a.unit_no
               FROM tickets t JOIN customers c ON c.customer_id=t.customer_id
               JOIN assets a ON a.asset_id=t.asset_id
               WHERE t.status IN ('Ready to Bill','Off Rent') AND (t.invoice_no IS NULL OR t.invoice_no='')
               ORDER BY t.customer_id"""
        ).fetchall()
        wos = engine.ready_work_orders(con)
        if not ready and not wos:
            return '<p>Nothing ready to bill. Off-rent a ticket or complete a billable work order first.</p>'
        boxes = "".join(
            f"<label><input type=checkbox name=t__{html.escape(r['ticket_id'])} value=1> "
            f"{html.escape(r['ticket_id'])} · {html.escape(r['account_name'])} · {html.escape(r['unit_no'])}</label>"
            for r in ready[:5]
        )
        if len(ready) > 5:
            boxes += f"<p class='mute'>+ {len(ready) - 5} more tickets — refine by customer above.</p>"
        wboxes = "".join(
            f"<label><input type=checkbox name=w__{html.escape(r['wo_id'])} value=1> "
            f"{html.escape(r['wo_id'])} · {html.escape(r['account_name'])} · {html.escape(r['unit_no'])} · "
            f"{html.escape(r['work_type'])} · ${float(r['bill_amount']):,.2f}</label>"
            for r in wos
        )
        custs = {r["customer_id"]: r["account_name"] for r in list(ready) + list(wos)}
        cust_combo = (
            combo_field("f_inv_cust", "customer_id_text",
                        [(k, v, k) for k, v in custs.items()],
                        label="Customer", required=True,
                        placeholder="Type to search customers…")
            + '<input type=hidden id="f_inv_cust_id" name=customer_id value="">'
        )
        today = date.today().isoformat()
        _inv = con.execute("SELECT COALESCE(MAX(CAST(SUBSTR(invoice_no, 5) AS INTEGER)), 0) + 1 FROM invoices WHERE invoice_no LIKE 'INV-%'").fetchone()[0]
        inv_no = f"INV-{_inv:04d}"
        # Tax is NEVER prefilled (Jason 2026-10-04): the software does not infer tax.
        # Blank = no tax; the operator enters the rate explicitly.
        tax_pct = ""
        return f"""
        <form method=post action="/invoice/create" enctype="multipart/form-data">
          <input type=hidden name=invoice_no value="{inv_no}">
          <div class="row4">
            <div><label>Invoice #</label><input value="{inv_no}" disabled class=w-xs></div>
            <div>{cust_combo}</div>
            <div><label>Reference Ticket</label><input name=ref_ticket class=w-sm placeholder="Optional"></div>
            <div><label>Date</label><input type=date name=invoice_date value="{today}" class=w-sm></div>
          </div>
          <div class="row4 lineitem-row" id="inv-lines">
            <div class="iline" style="display:contents">
              <div><label>Item</label><input name=item></div>
              <div><label>Description</label><input name=item_desc style="width:100%"></div>
              <div><label>Qty</label><input name=qty class="iqty w-xs" type=number step=0.01 value=1></div>
              <div><label>Rate $</label><input name=rate class="irate w-sm" type=number step=0.01 value=0></div>
            </div>
          </div>
          <div id="inv-totals" style="text-align:right;margin-top:8px">
            <div>Subtotal <b id="inv-sub">$0.00</b></div>
            <div>Tax <input name=tax_rate id="inv-taxrate" type=number step=0.01 value="{tax_pct}" class=w-xs style="width:76px;display:inline-block">% <b id="inv-tax">$0.00</b></div>
            <div>Adjustment <input name=adjustment id="inv-adj" type=number step=0.01 value=0 class=w-xs style="width:96px;display:inline-block"></div>
            <div>Grand total <b id="inv-grand">$0.00</b></div>
          </div>
          <div class="fgrid">
            <div>
              <h2 style="font-size:16px;color:var(--frame)">Rental Tickets</h2>
              {boxes or '<p class="hint">None waiting.</p>'}
            </div>
            <div>
              <h2 style="font-size:16px;color:var(--frame)">Billable Work Orders</h2>
              {wboxes or '<p class="hint">None waiting.</p>'}
            </div>
          </div>
          <div><label>Notes</label><input name=notes style="width:100%"></div>
          {self._btn_row("Create invoice", "invjobpop", add_item=True)}
          {self._job_info_popup('invjobpop')}
        </form>
        <script>
        (function(){{var box=document.getElementById('inv-lines'); if(!box)return; var form=box.closest('form');
        function num(v){{v=parseFloat(v); return isNaN(v)?0:v;}}
        function calc(){{var sub=0; box.querySelectorAll('.iline').forEach(function(r){{var q=r.querySelector('.iqty'),rt=r.querySelector('.irate'); sub+=num(q&&q.value)*num(rt&&rt.value);}}); var tr=num(document.getElementById('inv-taxrate').value)/100; var adj=num(document.getElementById('inv-adj').value); var tax=sub*tr, grand=sub+tax+adj; document.getElementById('inv-sub').textContent='$'+sub.toFixed(2); document.getElementById('inv-tax').textContent='$'+tax.toFixed(2); document.getElementById('inv-grand').textContent='$'+grand.toFixed(2);}}
        form.addEventListener('input',calc); calc(); window.__invCalc=calc;
        var btn=null; form.querySelectorAll('button[type=button]').forEach(function(b){{if(b.textContent.trim()==='Add item')btn=b;}}); if(!btn)return;
        btn.addEventListener('click',function(){{var rows=box.querySelectorAll('.iline'); var n=rows.length; var c=rows[0].cloneNode(true);
        c.querySelectorAll('[name]').forEach(function(el){{var base=el.name.replace(/\\d+$/,''); el.name=base+n;}});
        c.querySelectorAll('input').forEach(function(el){{if(el.classList.contains('iqty'))el.value='1'; else if(el.classList.contains('irate'))el.value='0'; else el.value='';}});
        box.appendChild(c); calc();}});}})();
        </script>
        """

    # --- Money tab: four sub-tabs ------------------------------------
    # New Invoice, Record Payment, Credit Memo, Petty Cash. Each sub-tab
    # runs the same pattern: problem ticker → entry form → capped list
    # with a View-all audit pop-up → coordinated Done box.

    def view_money(self, con, q=None):
        tab = (q or {}).get("tab") or "invoice"
        if tab not in ("invoice", "pay", "credit", "petty"):
            tab = "invoice"
        return tabs_money(tab) + self._money_tab(con, tab, q or {})

    def _money_tab(self, con, tab, q):
        if tab == "pay":
            body = self._money_pay(con)
        elif tab == "credit":
            body = self._money_credit(con, q)
        elif tab == "petty":
            body = self._money_petty(con)
        else:
            body = self._money_invoice(con)
        return body + self._done_box(con, "/money?tab=" + tab)

    def _money_ticker(self, con, items, tab):
        """Problem ticker: every line carries snooze/sleep, capped with
        + N more. Same controls as the top strip."""
        live = [(t, h) for t, h in items if not engine.is_acked(con, f"mt:{h}")]
        if not live:
            return ""
        nxt = f"/money?tab={tab}"
        rows = ""
        for text, href in live[:5]:
            rows += (
                f"<div class='tapbox lv0'><span class='msg'>{text}</span>"
                f"<a class='go' href='{html.escape(href, quote=True)}'>Handle Now</a>"
                f"{_ack_forms(f'mt:{href}', nxt)}"
                f"</div>")
        if len(live) > 5:
            rows += f"<p class='mute'>+ {len(live) - 5} more</p>"
        return f"<div class='news squeeze'>{rows}</div>"

    def _ticker_po_expiry(self, con):
        """POs expired or expiring within 14 days with money still out —
        the problem to see before creating an invoice."""
        out = []
        try:
            pos = con.execute(
                """SELECT p.po_no, p.customer_id, p.expire, c.account_name
                   FROM purchase_orders p
                   JOIN customers c ON c.customer_id = p.customer_id
                   WHERE p.expire IS NOT NULL AND TRIM(p.expire) != ''
                   ORDER BY p.expire""").fetchall()
        except Exception:
            return []
        for p in pos:
            exp = (p["expire"] or "").strip()[:10]
            try:
                delta = (date.fromisoformat(exp) - date.today()).days
            except ValueError:
                continue
            if delta > 14:
                continue
            row = con.execute(
                """SELECT invoice_no FROM invoices
                   WHERE customer_id=? AND TRIM(po)=?
                   AND status NOT IN ('Paid','Write-off','Draft')
                   ORDER BY invoice_date DESC LIMIT 1""",
                (p["customer_id"], (p["po_no"] or "").strip())).fetchone()
            if not row:
                continue
            bal = engine.invoice_totals(con, row["invoice_no"])["balance"]
            if bal <= 0.009:
                continue
            if delta < 0:
                head = f"PO {p['po_no']} expired {exp[5:]}"
            elif delta == 0:
                head = f"PO {p['po_no']} expires today"
            else:
                head = f"PO {p['po_no']} expires in {delta}d"
            out.append((
                f"{html.escape(head)} — {html.escape(p['account_name'])} "
                f"<span class='mute'>${bal:,.2f} unpaid</span>",
                f"/invoice/{row['invoice_no']}"))
        return out

    def _ticker_overdue(self, con):
        """Open invoices past terms, biggest balance first."""
        out = []
        today = date.today()
        for inv in con.execute(
                """SELECT i.invoice_no, i.invoice_date, i.terms, c.account_name
                   FROM invoices i JOIN customers c ON c.customer_id=i.customer_id
                   WHERE i.status NOT IN ('Paid','Write-off','Draft')"""):
            bal = engine.invoice_totals(con, inv["invoice_no"])["balance"]
            if bal <= 0.009:
                continue
            try:
                d0 = date.fromisoformat(str(inv["invoice_date"])[:10])
            except ValueError:
                d0 = today
            try:
                due = d0 + timedelta(days=engine.terms_days(inv["terms"]))
            except Exception:
                due = d0 + timedelta(days=30)
            if today <= due:
                continue
            late = (today - due).days
            out.append((bal,
                f"{html.escape(inv['invoice_no'])} {late}d past due — "
                f"{html.escape(inv['account_name'])} "
                f"<span class='mute'>${bal:,.2f}</span>",
                f"/invoice/{inv['invoice_no']}"))
        out.sort(key=lambda t: -t[0])
        return [(t, h) for _, t, h in out]

    def _ticker_open_credits(self, con):
        """Credit memos with unapplied face — money waiting to move."""
        out = []
        for r in engine.list_open_credits(con):
            out.append((
                f"{html.escape(r['cm_no'])} — {html.escape(r['customer_id'])} "
                f"<span class='mute'>${r['unapplied']:,.2f} unapplied</span>",
                "/money?tab=credit"))
        return out

    def _ticker_petty(self, con):
        """Petty-cash float problems: below target means replenish."""
        book = engine.petty_book(con)
        if book["to_replenish"] > 0.009:
            return [(
                f"Petty cash <span class='mute'>${book['balance']:,.2f} — "
                f"${book['to_replenish']:,.2f} below the ${book['target']:,.2f} float</span>",
                "/money?tab=petty")]
        return []

    def _billables_ticker(self, con):
        """Ready-to-bill jobs as a global-rules ticker: five items, each
        with its action verb, snooze/sleep right-justified, + N more."""
        ready = con.execute(
            """SELECT t.ticket_id, c.account_name, a.unit_no
               FROM tickets t JOIN customers c ON c.customer_id=t.customer_id
               JOIN assets a ON a.asset_id=t.asset_id
               WHERE t.status IN ('Ready to Bill','Off Rent') AND (t.invoice_no IS NULL OR t.invoice_no='')
               ORDER BY t.customer_id""").fetchall()
        wos = engine.ready_work_orders(con)
        items = []
        for r in ready:
            items.append({
                "href": f"/ticket/{html.escape(r['ticket_id'], quote=True)}",
                "key": f"bill:{r['ticket_id']}",
                "verb": "Bill",
                "text": f"{r['ticket_id']} · {r['account_name']} · {r['unit_no']} ready to bill",
            })
        for r in wos:
            items.append({
                "href": f"/wo/{html.escape(r['wo_id'], quote=True)}",
                "key": f"bill:{r['wo_id']}",
                "verb": "Bill",
                "text": f"{r['wo_id']} · {r['account_name']} · {r['unit_no']} · ${float(r['bill_amount']):,.2f}",
            })
        if not items:
            return ""
        total = len(items)
        shown = items[:5]
        more = total - len(shown) if total > len(shown) else None
        return news_strip([], "/money?tab=invoice", shown, more)

    def _money_invoice(self, con):
        ticker = ''
        invs = con.execute(
            """SELECT i.invoice_no, i.invoice_date, i.status, c.account_name
               FROM invoices i JOIN customers c ON c.customer_id=i.customer_id
               ORDER BY i.invoice_date DESC, i.invoice_no DESC LIMIT 5""").fetchall()
        rows = "".join(
            f"<div class='todo'><a href='/invoice/{html.escape(r['invoice_no'], quote=True)}'>"
            f"{html.escape(r['invoice_no'])}</a> — {html.escape(r['account_name'])} "
            f"<span class='mute'>${engine.invoice_totals(con, r['invoice_no'])['balance']:,.2f} · "
            f"{html.escape(r['status'])}</span></div>"
            for r in invs)
        return (ticker + self._frag_invoice_form(con) +
                "<h2>Recent Invoices</h2>" +
                (rows or "<p class='mute'>No invoices yet.</p>") +
                view_button("/money/invoices/audit", "Invoices — audit"))

    def _money_pay(self, con):
        ticker = ''
        pays = con.execute(
            "SELECT pay_date, invoice_no, method, amount, kind FROM collections "
            "ORDER BY pay_date DESC, pay_id DESC LIMIT 5").fetchall()
        rows = "".join(
            f"<div class='todo'><span class='mute'>{html.escape(str(p['pay_date'])[:10])}</span> "
            f"${p['amount']:,.2f} — {html.escape(p['kind'])} "
            f"<a href='/invoice/{html.escape(p['invoice_no'], quote=True)}'>"
            f"{html.escape(p['invoice_no'])}</a></div>"
            for p in pays)
        return (ticker + self._frag_pay_form(con) +
                "<h2>Recent Payments</h2>" +
                (rows or "<p class='mute'>No payments recorded yet.</p>") +
                view_button("/money/payments/audit", "Payments — audit"))

    def _money_credit(self, con, q):
        ticker = ''
        return (ticker + self._frag_credit_form(con, q) +
                view_button("/money/credits/audit", "Credit memos — audit"))

    def _money_petty(self, con):
        ticker = ''
        book = engine.petty_book(con)
        rows = "".join(
            f"<div class='todo'><span class='mute'>{html.escape(r['txn_date'])}</span> "
            f"{html.escape(r['category'])} — {html.escape(r['payee'])} "
            f"<span class='mute'>${r['signed']:,.2f} · bal ${r['running']:,.2f}</span></div>"
            for r in book["rows"][:5])
        cards = (
            f"<div class='cards'>"
            f"<div class='card'><span>In the box</span><b>${book['balance']:,.2f}</b></div>"
            f"<div class='card'><span>Target float</span><b>${book['target']:,.2f}</b> "
            f"<a href='#' style='font-size:11px' onclick=\"document.getElementById('floatpop').style.display=document.getElementById('floatpop').style.display=='none'?'block':'none';return false\">Change</a>"
            f"<div id='floatpop' style='display:none;margin-top:6px'><form method=post action='/petty/float' style='display:flex;gap:4px'>"
            f"<input name=pc_float type=number step=0.01 min=0 class=w-sm value=\"{book['target']:.2f}\" style='width:90px'>"
            f"<button class='mini'>Set</button></form></div></div>"
            f"<div class='card'><span>To replenish</span><b>${book['to_replenish']:,.2f}</b></div>"
            f"</div>")
        return (ticker + cards + self._frag_petty_form(con) +
                "<h2>Recent Box Activity</h2>" +
                (rows or "<p class='mute'>Empty box.</p>") +
                view_button("/money/petty/audit", "Petty cash — audit"))

    def view_money_invoices_audit(self, con):
        rows = "".join(
            f"<tr><td><a href='/invoice/{html.escape(r['invoice_no'], quote=True)}'>"
            f"{html.escape(r['invoice_no'])}</a></td>"
            f"<td>{html.escape(r['account_name'])}</td>"
            f"<td>{html.escape(str(r['invoice_date'])[:10])}</td>"
            f"<td>{html.escape(r['status'])}</td>"
            f"<td>${engine.invoice_totals(con, r['invoice_no'])['balance']:,.2f}</td></tr>"
            for r in con.execute(
                """SELECT i.invoice_no, i.invoice_date, i.status, c.account_name
                   FROM invoices i JOIN customers c ON c.customer_id=i.customer_id
                   ORDER BY i.invoice_date DESC, i.invoice_no DESC"""))
        return f"""
        <p class="hint"><input id="auditq" placeholder="Filter these lists…" size="30"
        oninput="document.querySelectorAll('table.audit').forEach(t=>auditFilter(t,this.value))">
        <span class="mute">Click a column header to sort.</span></p>
        <h2>Invoices</h2>
        <table class="audit"><tr><th>No</th><th>Customer</th><th>Date</th><th>Status</th><th>Balance</th></tr>
        {rows or '<tr><td colspan=5>No invoices.</td></tr>'}</table>
        """ + AUDIT_TABLE_JS

    def view_money_payments_audit(self, con):
        rows = "".join(
            f"<tr><td>{html.escape(str(r['pay_date'])[:10])}</td>"
            f"<td><a href='/invoice/{html.escape(r['invoice_no'], quote=True)}'>"
            f"{html.escape(r['invoice_no'])}</a></td>"
            f"<td>{html.escape(r['method'])}</td><td>${r['amount']:,.2f}</td>"
            f"<td>{html.escape(r['kind'])}</td></tr>"
            for r in con.execute(
                "SELECT pay_date, invoice_no, method, amount, kind FROM collections "
                "ORDER BY pay_date DESC, pay_id DESC"))
        return f"""
        <p class="hint"><input id="auditq" placeholder="Filter these lists…" size="30"
        oninput="document.querySelectorAll('table.audit').forEach(t=>auditFilter(t,this.value))">
        <span class="mute">Click a column header to sort.</span></p>
        <h2>Payments</h2>
        <table class="audit"><tr><th>Date</th><th>Invoice</th><th>Method</th><th>Amount</th><th>Kind</th></tr>
        {rows or '<tr><td colspan=5>No payments.</td></tr>'}</table>
        """ + AUDIT_TABLE_JS

    def view_money_credits_audit(self, con):
        rows = "".join(
            f"<tr><td><a href='/print/credit/{html.escape(r['cm_no'], quote=True)}'>"
            f"{html.escape(r['cm_no'])}</a></td>"
            f"<td>{html.escape(str(r['cm_date'])[:10])}</td>"
            f"<td>{html.escape(r['account_name'])}</td>"
            f"<td>{html.escape(r['reason'] or '')}</td>"
            f"<td>${r['face_amount']:,.2f}</td></tr>"
            for r in con.execute(
                """SELECT m.cm_no, m.cm_date, c.account_name, m.reason, m.face_amount
                   FROM credit_memos m JOIN customers c ON c.customer_id=m.customer_id
                   ORDER BY m.cm_date DESC, m.cm_no DESC"""))
        return f"""
        <p class="hint"><input id="auditq" placeholder="Filter these lists…" size="30"
        oninput="document.querySelectorAll('table.audit').forEach(t=>auditFilter(t,this.value))">
        <span class="mute">Click a column header to sort.</span></p>
        <h2>Credit Memos</h2>
        <table class="audit"><tr><th>CM</th><th>Date</th><th>Customer</th><th>Reason</th><th>Face</th></tr>
        {rows or '<tr><td colspan=5>No credit memos.</td></tr>'}</table>
        """ + AUDIT_TABLE_JS

    def view_money_petty_audit(self, con):
        book = engine.petty_book(con)
        rows = "".join(
            f"<tr><td>{html.escape(r['txn_date'])}</td>"
            f"<td>{html.escape(r['direction'])}</td>"
            f"<td>{html.escape(r['category'])}</td>"
            f"<td>{html.escape(r['payee'])}</td>"
            f"<td>${r['signed']:,.2f}</td><td>${r['running']:,.2f}</td>"
            f"<td>{html.escape(r['ref_no'])}</td><td>{html.escape(r['notes'])}</td></tr>"
            for r in book["rows"])
        return f"""
        <p class="hint"><input id="auditq" placeholder="Filter these lists…" size="30"
        oninput="document.querySelectorAll('table.audit').forEach(t=>auditFilter(t,this.value))">
        <span class="mute">Click a column header to sort.</span></p>
        <h2>Petty Cash Register</h2>
        <table class="audit"><tr><th>Date</th><th>Dir</th><th>Category</th><th>Payee</th><th>Amount</th><th>Running</th><th>Ref</th><th>Notes</th></tr>
        {rows or '<tr><td colspan=8>Empty box.</td></tr>'}</table>
        """ + AUDIT_TABLE_JS

    def view_quotes(self, con, show_all=False, bare=False):
        """Live quotes: the stand-alone estimates, off the money tabs."""
        live_quotes = con.execute(
            """SELECT q.quote_no, q.quote_date, q.status, q.job_name, c.account_name
               FROM quotes q JOIN customers c ON c.customer_id=q.customer_id
               WHERE q.status NOT IN ('Void','Declined','Expired','Converted')
               ORDER BY q.quote_date DESC, q.quote_no DESC"""
        ).fetchall()
        shown = live_quotes if show_all else live_quotes[:DASH_CAP]
        body = "".join(
            f"<tr><td><a href='/quote/{html.escape(r['quote_no'])}'>{html.escape(r['quote_no'])}</a></td>"
            f"<td>{html.escape(r['account_name'])}</td>"
            f"<td>{html.escape(str(r['quote_date'])[:10])}</td>"
            f"<td>{html.escape(r['status'])}</td>"
            f"<td>{html.escape(r['job_name'] or '')}</td>"
            f"<td>${engine.quote_totals(con, r['quote_no'])['face']:,.2f}</td>"
            f"<td><a href='/print/quote/{html.escape(r['quote_no'])}'>Paper</a></td></tr>"
            for r in shown
        )
        nq = len(live_quotes)
        more = "" if show_all else more_link(nq, len(shown), "/quotes?all=1", "All live quotes")
        return ("" if bare else tabs_quotes("/quotes")) + f"""
        <h2>Quotes</h2>
        <p>{nq} live {'quote' if nq == 1 else 'quotes'}.
        <a class="btn" href="/quote/new">New Quote</a></p>
        {("<table><tr><th>No</th><th>Customer</th><th>Date</th><th>Status</th><th>Job</th><th>Face</th><th>Print</th></tr>" + body + "</table>") if body else "<p class='hint' style='margin:4px 0'>None yet.</p>"}
        {more}
        """

    def view_quote_form(self, con, qno, bare=False):
        pack = engine.quote_pack(con, qno) if qno else None
        if qno and not pack:
            return ("" if bare else tabs_quotes("/quotes")) + "<p>Unknown quote.</p>"
        # New quote: pre-generate the number so the user sees it while preparing.
        # (Jason 2026-10-07: "please find quote number XXX attached")
        if not qno:
            qno = engine._next_doc(con, "next_quote", "QT-", "quotes", "quote_no")
        q = pack["q"] if pack else {}
        lines = pack["lines"] if pack else []
        while len(lines) < 3:
            lines.append({"kind": "item", "asset_id": "", "description": "", "qty": 1, "rate": 0})
        cust = con.execute("SELECT customer_id, account_name FROM customers ORDER BY account_name").fetchall()
        sites = con.execute("SELECT site_id, site_name FROM sites ORDER BY site_name").fetchall()
        assets = con.execute("SELECT asset_id, unit_no FROM assets WHERE active=1 ORDER BY unit_no").fetchall()
        today = date.today().isoformat()
        try:
            _base = date.fromisoformat(str(q.get('quote_date') or today)[:10])
        except ValueError:
            _base = date.today()
        try:
            quote_days = max(1, int(engine.get_option(con, "quote_valid_days", "30") or 30))
        except (TypeError, ValueError):
            quote_days = 30
        default_valid = (_base + timedelta(days=quote_days)).isoformat()
        valid_until = str(q.get('valid_until') or '')[:10] or default_valid
        kinds = ("item", "unit", "labor", "freight", "other")
        row_html = []
        for i, ln in enumerate(lines[:3]):
            kopts = "".join(
                f"<option{' selected' if ln.get('kind')==k else ''}>{k}</option>" for k in kinds
            )
            aopts, acur = combo_opts(assets, "asset_id", "unit_no", ln.get("asset_id"),
                                     disp=lambda v, lab: lab)
            acombo = (
                combo_field(f"f_qline_a{i}", f"a{i}_text", aopts, value=acur,
                            placeholder="Type to search units…")
                + f'<input type=hidden id="f_qline_a{i}_id" name=a{i} '
                  f'value="{html.escape(str(ln.get("asset_id") or ""), quote=True)}">'
            )
            # Default line-item row (Jason 2026-10-07): Type | Item | Description | Qty | Rate$
            row_html.append(
                f"<div class='lineitem-row qline' data-i='{i}' style='display:grid;grid-template-columns:104px 1fr 2fr 84px 104px;gap:8px;align-items:end'>"
                f"<div><label>Type</label><select name=k{i} class=qkind>{kopts}</select></div>"
                f"<div><label>Item</label>{acombo}</div>"
                f"<div><label>Description</label><input name=d{i} value='{html.escape(str(ln.get('description') or ''), quote=True)}'></div>"
                f"<div><label>Qty</label><input name=q{i} class='qqty w-xs' type=number step=0.01 value='{float(ln.get('qty') or 1):.2f}'></div>"
                f"<div><label>Rate $</label><input name=r{i} class='qrate w-sm' type=number step=0.01 value='{float(ln.get('rate') or 0):.2f}'></div>"
                f"</div>"
            )
        nxt = ["Sent", "Void"] if not pack else list(engine.QUOTE_NEXT.get(q.get("status"), ()))
        st_btns = "".join(
            f"<button name=status value='{html.escape(s)}'>{html.escape(s)}</button> " for s in nxt
        )
        tot = pack["tot"] if pack else None
        linked = ""
        if pack:
            tix = ", ".join(f"{t['ticket_id']} ({t['status']})" for t in pack["tickets"]) or "none"
            wos = ", ".join(f"{w['wo_id']}" for w in pack["wos"]) or "none"
            inv = ", ".join(f"{i['invoice_no']}" for i in pack["invoices"]) or "none"
            cos = ", ".join(c["header"]["co_no"] for c in pack["cos"]) or "none"
            linked = f"""<p class="hint">Tickets: {html.escape(tix)} · WOs: {html.escape(wos)} ·
            Invoices: {html.escape(inv)} · Change orders: {html.escape(cos)}</p>
            <p>Quoted ${tot['quoted']:,.2f} + CO add ${tot['co_add']:,.2f} − CO sub ${tot['co_sub']:,.2f}
            = face ${tot['face']:,.2f}. Billed ${tot['billed']:,.2f}. Variance ${tot['variance']:,.2f}.</p>"""
        convert = ""
        if pack and q.get("status") in ("Accepted", "Converted"):
            convert = f"""<form method=post action="/quote/{html.escape(qno)}/convert">
              <label>On-Rent for New Reserved Tickets</label>
              <input type=date name=on_rent value="{today}">
              <p><button>Convert Rental Lines to Tickets</button></p>
            </form>"""
        status_form = (
            f"""<form method=post action="/quote/{html.escape(qno)}/status">{st_btns}</form>"""
            if pack and st_btns else ""
        )
        qcust_opts, qcust_cur = combo_opts(cust, "customer_id", "account_name",
                                           q.get("customer_id", ""))
        qcust_combo = (
            combo_field("f_q_cust", "customer_id_text", qcust_opts, value=qcust_cur,
                        label="Customer", required=True,
                        placeholder="Type to search customers…")
            + f'<input type=hidden id="f_q_cust_id" name=customer_id value="'
              f'{html.escape(str(q.get("customer_id") or ""), quote=True)}">'
        )
        qsite_opts, qsite_cur = combo_opts(sites, "site_id", "site_name",
                                           q.get("site_id") or "")
        qsite_combo = (
            combo_field("f_q_site", "site_id_text", qsite_opts, value=qsite_cur,
                        label="Site", placeholder="Type to search sites…")
            + f'<input type=hidden id="f_q_site_id" name=site_id value="'
              f'{html.escape(str(q.get("site_id") or ""), quote=True)}">'
        )
        return ("" if bare else tabs_quotes("/quotes")) + f"""
        {"" if bare else "<h1>" + ('Quote ' + html.escape(qno) if qno else 'New Quote') + "</h1>"}
        {linked}
        {status_form}
        <form method=post action="/quote/save" enctype="multipart/form-data">
          <input type=hidden name=quote_no value="{html.escape(qno or '')}">
          <div class="row4">
            <div><label>Quote #</label><input value="{html.escape(qno)}" disabled class=w-xs></div>
            <div>{qcust_combo}</div>
            <div><label>Contact</label><input name=contact_name value="{html.escape(q.get('contact_name') or '')}"></div>
            <div style="text-align:right"><label>Date</label><input type=date name=quote_date value="{html.escape(str(q.get('quote_date') or today)[:10])}" class=w-sm></div>
          </div>
          <style>.lineitem-row label{{margin:4px 0 2px}}.lineitem-row{{margin-bottom:2px}}</style>
          <div id="quote-lines">
          {''.join(row_html)}
          </div>
          <div class="row3">
            <div><label>Prepared By</label><input name=clerk value="{html.escape(self.desk(con), quote=True)}" class=w-sm maxlength=40></div>
            <div><label>Valid Until</label><input type=date name=valid_until required value="{html.escape(valid_until)}" class=w-sm></div>
            <div><label>Notes</label><input name=notes value="{html.escape(q.get('notes') or '')}" style="width:100%"></div>
          </div>
          <div class="row3">
            <div></div>
            <div style="text-align:center">*taxes not included*</div>
            <div id="quote-total" style="text-align:right;font-weight:700;color:var(--frame)">Total: $0.00</div>
          </div>
          {self._btn_row("Save", "qjobpop", add_item=True)}
          {self._job_info_popup('qjobpop')}
        </form>
        {convert}
        <script>
        (function(){{var t=document.getElementById('quote-lines'); if(!t)return; function calc(){{var total=0; t.querySelectorAll('.qline').forEach(function(r){{var q=r.querySelector('.qqty'), rate=r.querySelector('.qrate'); if(!q||!rate)return; total+=(parseFloat(q.value)||0)*(parseFloat(rate.value)||0);}}); var el=document.getElementById('quote-total'); if(el)el.textContent='Total: $'+total.toFixed(2); }} t.addEventListener('input',calc); calc(); window.__quoteCalc=calc;}})();
        /* Add item: clone a line row, renumber k/d/q/r/a indexes (backend takes k0..k7) */
        (function(){{var box=document.getElementById('quote-lines'); if(!box)return; var form=box.closest('form'); var btn=null; form.querySelectorAll('button[type=button]').forEach(function(b){{if(b.textContent.trim()==='Add item')btn=b;}}); if(!btn)return;
        function bindCombo(inp){{var dl=document.getElementById(inp.getAttribute('list')); if(!dl)return; function sync(){{var t=inp.value.trim(),id=''; Array.prototype.forEach.call(dl.options,function(o){{if(o.value.trim()===t){{id=o.getAttribute('data-id')||'';}}}}); var hid=document.getElementById(inp.id+'_id'); if(hid)hid.value=id;}} inp.addEventListener('input',sync); inp.addEventListener('change',sync); sync();}}
        btn.addEventListener('click',function(){{var rows=box.querySelectorAll('.qline'); if(rows.length>=8)return; var n=rows.length; var c=rows[rows.length-1].cloneNode(true); c.setAttribute('data-i',n);
        c.querySelectorAll('[name]').forEach(function(el){{el.name=el.name.replace(/^(k|a|d|q|r)(\\d+)(_text)?$/,function(m,p1,p2,p3){{return p1+n+(p3||'');}});}});
        c.querySelectorAll('[id]').forEach(function(el){{el.id=el.id.replace(/_a\\d+/, '_a'+n);}});
        var vis=c.querySelector('input[data-combo]'); if(vis&&vis.hasAttribute('list')){{vis.setAttribute('list',vis.getAttribute('list').replace(/_a\\d+_list/,'_a'+n+'_list'));}}
        c.querySelectorAll('input').forEach(function(el){{if(el.type==='hidden'){{el.value='';}} else if(el.classList.contains('qqty')){{el.value='1.00';}} else if(el.classList.contains('qrate')){{el.value='0.00';}} else{{el.value='';}}}});
        c.querySelectorAll('select').forEach(function(el){{el.selectedIndex=0;}});
        box.appendChild(c); if(vis)bindCombo(vis); if(window.__quoteCalc)window.__quoteCalc();}});}})();
        </script>
        """

    def view_changes(self, con, q=None, bare=False):
        q = q or {}
        qn = q.get("quote_no") or ""
        # Change orders reference invoices, not quotes (Jason 2026-10-07)
        invs = con.execute(
            """SELECT invoice_no, invoice_no || ' · ' || customer_id AS label FROM invoices
               ORDER BY invoice_no DESC LIMIT 50"""
        ).fetchall()
        rows = con.execute(
            """SELECT c.co_no, c.quote_no, c.co_date, c.reason, c.status
               FROM change_orders c ORDER BY c.co_date DESC, c.co_no DESC"""
        ).fetchall()
        body = "".join(
            f"<tr><td><a href='/print/change/{html.escape(r['co_no'])}'>{html.escape(r['co_no'])}</a></td>"
            f"<td><a href='/quote/{html.escape(r['quote_no'])}'>{html.escape(r['quote_no'])}</a></td>"
            f"<td>{html.escape(r['po'] or "")}</td>"
            f"<td>{html.escape(str(r['co_date'])[:10])}</td>"
            f"<td>{html.escape(r['reason'])}</td>"
            f"<td>{html.escape(r['status'])}</td></tr>"
            for r in rows
        )
        kinds = ("item", "unit", "labor", "freight", "other")
        line_rows = []
        for i in range(3):
            kopts = "".join(f"<option>{k}</option>" for k in kinds)
            line_rows.append(
                f"<tr><td><select name=k{i}>{kopts}</select></td>"
                f"<td style='min-width:220px'><input name=d{i} style='width:100%'></td>"
                f"<td><input name=q{i} type=number step=0.01 value=1 class=w-xs title='Use -1 to subtract'></td>"
                f"<td><input name=r{i} type=number step=0.01 value=0 class=w-sm></td></tr>"
            )
        _co = con.execute("SELECT COALESCE(MAX(CAST(SUBSTR(co_no, 4) AS INTEGER)), 0) + 1 FROM change_orders WHERE co_no LIKE 'CO-%'").fetchone()[0]
        co_no = f"CO-{_co:04d}"
        isel_opts, isel_cur = combo_opts(invs, "invoice_no", "label", "")
        isel_combo = (
            combo_field("f_co_inv", "invoice_no_text", isel_opts, value=isel_cur,
                        label="Invoice ref", required=True,
                        placeholder="Type to search invoices…")
            + f'<input type=hidden id="f_co_inv_id" name=invoice_no value="">'
        )
        today = date.today().isoformat()
        return ("" if bare else tabs_quotes("/changes")) + f"""
        {"" if bare else "<h1>Change Orders</h1>"}
        <form method=post action="/change/save" enctype="multipart/form-data">
          <input type=hidden name=co_no value="{co_no}">
          <div class="row4">
            <div><label>Co #</label><input value="{co_no}" disabled class=w-xs></div>
            <div>{isel_combo}</div>
            <div><label>Customer Po</label><input name=po class=w-sm></div>
            <div><label>Date</label><input type=date name=co_date value="{today}" class=w-sm></div>
          </div>
          <table><tr><th>Type</th><th style="min-width:220px">Description</th><th>Qty</th><th>Rate</th></tr>
          {''.join(line_rows)}</table>
          <div><label>Notes</label><input name=notes></div>
          {self._btn_row("Save", "cojobpop", add_item=True)}
          {self._job_info_popup('cojobpop')}
        </form>
        <h2 style="font-size:16px;color:var(--frame)">Issued</h2>
        <table><tr><th>CO</th><th>Quote</th><th>PO</th><th>Date</th><th>Reason</th><th>Status</th></tr>
        {body or '<tr><td colspan=5>None yet.</td></tr>'}</table>
        """

    def view_pay(self, con):
        return tabs_money("pay") + self._money_tab(con, "pay", {})

    def _frag_pay_form(self, con):
        open_inv = engine.list_open_invoices(con)
        if not open_inv:
            return "<p>No open invoices with tickets or work orders. Create an invoice first. Payments cannot post to a general account.</p>"
        pay_inv_opts = []
        for r in open_inv:
            v = str(r["invoice_no"])
            d = f"{v} · {r['account_name']} · bal ${float(r['balance']):,.2f}"
            pay_inv_opts.append((v, d, v))
        pay_inv_combo = (
            combo_field("f_pay_inv", "invoice_no_text", pay_inv_opts,
                        label="Invoice", required=True,
                        placeholder="Type to search invoices…")
            + '<input type=hidden id="f_pay_inv_id" name=invoice_no value="">'
        )
        pay_method_opts = [(m, m, m) for m in engine.CASH_METHODS]
        pay_method_combo = (
            combo_field("f_pay_method", "method_text", pay_method_opts,
                        label="Method", placeholder="Type to search methods…")
            + '<input type=hidden id="f_pay_method_id" name=method value="">'
        )
        today = date.today().isoformat()
        _rp = con.execute("SELECT COALESCE(MAX(pay_id), 0) + 1 FROM collections").fetchone()[0]
        rp_no = f"RP-{_rp:04d}"
        return f"""
        <form method=post action="/pay" enctype="multipart/form-data">
          <input type=hidden name=rp_no value="{rp_no}">
          <div class="row4">
            <div><label>Rp #</label><input value="{rp_no}" disabled class=w-xs></div>
            <div>{pay_inv_combo}</div>
            <div><label>Amount</label><input name=amount type=number step=0.01 min=0.01 required class=w-sm></div>
            <div><label>Date</label><input type=date name=pay_date value="{today}" required class=w-sm></div>
          </div>
          <div class="row4">
            <div><label>Payment Reference</label><input name=ref class=w-sm></div>
            <div>{pay_method_combo}</div>
            <div><label>Upload(s)</label><input type=file name=pay_upload></div>
            <div><label>User Name</label><input name=user_name value="{html.escape(self.desk(con))}" class=w-sm></div>
          </div>
          <div><label>Notes</label><input name=notes style="width:100%"></div>
          {self._btn_row("Apply payment", "payjobpop", add_item=True)}
          {self._job_info_popup('payjobpop')}
        </form>
        """

    def view_credit(self, con, q=None):
        return tabs_money("credit") + self._money_tab(con, "credit", q or {})

    def _frag_credit_form(self, con, q):
        q = q or {}
        cid = q.get("customer_id") or ""
        custs = con.execute("SELECT customer_id, account_name FROM customers ORDER BY account_name").fetchall()
        if not custs:
            return "<p>Add a customer first.</p>"
        cust_opts, cust_cur = combo_opts(custs, "customer_id", "account_name", cid)
        cust_hid = html.escape(str(cid), quote=True)
        filt_cust_combo = (
            combo_field("f_cred_filt_cust", "customer_id_text", cust_opts,
                        value=cust_cur, label="Customer",
                        placeholder="Type to search customers…")
            + f'<input type=hidden id="f_cred_filt_cust_id" name=customer_id value="{cust_hid}">'
        )
        issue_cust_combo = (
            combo_field("f_cred_cust", "customer_id_text", cust_opts,
                        value=cust_cur, label="Customer", required=True,
                        placeholder="Type to search customers…")
            + f'<input type=hidden id="f_cred_cust_id" name=customer_id value="{cust_hid}">'
        )
        today = date.today().isoformat()
        open_inv = engine.list_open_invoices(con, cid) if cid else []
        apply_rows = "".join(
            f"<tr><td>{html.escape(r['invoice_no'])}</td>"
            f"<td>{html.escape(r['invoice_date'])}</td>"
            f"<td>${r['total']:,.2f}</td><td>${r['cash']:,.2f}</td>"
            f"<td>${r['credit']:,.2f}</td><td>${r['balance']:,.2f}</td>"
            f"<td><input name=a__{html.escape(r['invoice_no'])} type=number step=0.01 min=0 "
            f"max='{r['balance']:.2f}' placeholder='0.00'></td></tr>"
            for r in open_inv
        )
        leftovers = engine.list_open_credits(con, cid or None)
        cm_opts = []
        for r in leftovers:
            v = str(r["cm_no"])
            d = f"{v} · {r['customer_id']} · unapplied ${float(r['unapplied']):,.2f}"
            cm_opts.append((v, d, v))
        cm_combo = (
            combo_field("f_cm_no", "cm_no_text", cm_opts,
                        label="Open credit memo", required=True,
                        placeholder="Type to search credit memos…")
            + '<input type=hidden id="f_cm_no_id" name=cm_no value="">'
        )
        leftovers_capped = leftovers[:5]
        left_table = "".join(
            f"<tr><td><a href='/print/credit/{html.escape(r['cm_no'])}'>{html.escape(r['cm_no'])}</a></td>"
            f"<td>{html.escape(r['cm_date'])}</td><td>{html.escape(r['customer_id'])}</td>"
            f"<td>{html.escape(r['reason'])}</td>"
            f"<td>${r['face']:,.2f}</td><td>${r['applied']:,.2f}</td><td>${r['unapplied']:,.2f}</td></tr>"
            for r in leftovers_capped
        )
        if len(leftovers) > 5:
            left_table += f"<tr><td colspan=7><a href='/money/credits/audit'>View More ({len(leftovers)-5} More)</a></td></tr>"
        apply_block = (
            f"""<h2 style="font-size:16px;color:var(--frame)">Apply Now (Optional)</h2>
            <table><tr><th>Invoice</th><th>Date</th><th>Total</th><th>Cash</th><th>Credit</th><th>Balance</th><th>Apply</th></tr>
            {apply_rows or '<tr><td colspan=7>Pick a customer with an open invoice.</td></tr>'}</table>"""
            if cid else
            ""
        )
        leftover_form = (
            f"""<h2 style="font-size:16px;color:var(--frame);margin-top:28px">Apply Leftover</h2>
            <p class="hint">Same customer only. Still cannot exceed each invoice balance.</p>
            <form method=post action="/credit/apply">
              {cm_combo}
              {self.clerk_field(con)}
              <label>Date</label><input type=date name=pay_date value="{today}">
              <table><tr><th>Invoice</th><th>Date</th><th>Total</th><th>Cash</th><th>Credit</th><th>Balance</th><th>Apply</th></tr>
              {apply_rows or '<tr><td colspan=7>Load that customer’s invoices first.</td></tr>'}</table>
              <p><button>Apply Leftover</button></p>
            </form>"""
            if leftovers and cid else
            (f"""<h2 style="font-size:16px;color:var(--frame);margin-top:28px">Open Credit Memos</h2>
            <table><tr><th>CM</th><th>Date</th><th>Customer</th><th>Reason</th><th>Face</th><th>Applied</th><th>Unapplied</th></tr>
            {left_table or '<tr><td colspan=7>None waiting.</td></tr>'}</table>""" if leftovers else "")
        )
        _cm = con.execute("SELECT COALESCE(MAX(CAST(SUBSTR(cm_no, 4) AS INTEGER)), 0) + 1 FROM credit_memos WHERE cm_no LIKE 'CM-%'").fetchone()[0]
        cm_no = f"CM-{_cm:04d}"
        # Invoice dropdown for reference
        invs = con.execute("SELECT invoice_no, invoice_date FROM invoices ORDER BY invoice_date DESC LIMIT 20").fetchall()
        inv_opts = "".join(f"<option value='{r[0]}' data-date='{html.escape(str(r[1])[:10], quote=True)}'>{r[0]} · {r[1]}</option>" for r in invs)
        return f"""
        <form method=post action="/credit" enctype="multipart/form-data" class="cmsqueeze">
          <style>.cmsqueeze label{{margin:5px 0 2px}}.cmsqueeze .row4,.cmsqueeze .row3{{margin-bottom:2px}}.cmsqueeze h2{{margin:8px 0 4px}}</style>
          <input type=hidden name=cm_no value="{cm_no}">
          <div class="row4">
            <div><label>Cm #</label><input value="{cm_no}" disabled class=w-xs></div>
            <div><label>Invoice Ref</label><select name=invoice_no id=cm_inv onchange="var d=this.options[this.selectedIndex].getAttribute('data-date');if(d){{document.getElementById('cm_inv_date').value=d}}"><option value="">— Pick or Type —</option>{inv_opts}</select></div>
            <div><label>Inv Date</label><input type=date name=inv_date id=cm_inv_date class=w-sm></div>
            <div><label>Date</label><input type=date name=cm_date value="{today}" required class=w-sm></div>
          </div>
          <div class="row3">
            <div>{issue_cust_combo}</div>
            <div><label>Reason</label><input name=reason required maxlength=160 placeholder="Billed twice / wrong dates / courtesy"></div>
            <div><label>Amount</label><input name=face_amount type=number step=0.01 min=0.01 required class=w-sm></div>
          </div>
          {apply_block}
          <div class="row4 lineitem-row">
            <div><label>Item</label><input name=item></div>
            <div><label>Description</label><input name=item_desc style="width:100%"></div>
            <div><label>Qty</label><input name=qty type=number step=0.01 value=1 class=w-xs></div>
            <div><label>Rate $</label><input name=rate type=number step=0.01 value=0 class=w-sm></div>
          </div>
          <div class="row3">
            <div style="grid-column:span 2"><label>Notes</label><input name=notes style="width:100%"></div>
            <div><label>Upload</label><input type=file name=cm_upload></div>
          </div>
          {self._btn_row("Save", "cmjobpop", add_item=True)}
          {self._job_info_popup('cmjobpop')}
        </form>
        {leftover_form}
        """

    def view_petty(self, con):
        return tabs_money("petty") + self._money_tab(con, "petty", {})

    def _frag_petty_form(self, con):
        book = engine.petty_book(con)
        today = date.today().isoformat()
        desk = html.escape(self.desk(con), quote=True)
        in_opts = "".join(f"<option>{html.escape(c)}</option>" for c in engine.PC_IN_CATS)
        out_cat_combo = (
            combo_field("f_petty_cat_out", "category_text",
                        [(c, c, c) for c in engine.PC_OUT_CATS],
                        label="Category",
                        placeholder="Type to search categories…")
            + '<input type=hidden id="f_petty_cat_out_id" name=category value="">'
        )
        return f"""
        <div class="fgrid">
          <div class="card" style="padding:10px">
            <h2 style="font-size:14px;margin:0 0 6px">Cash Out</h2>
            <form method=post action="/petty" style="margin:0">
              <input type=hidden name=direction value="out">
              <div class="row"><div><label>Date</label><input type=date name=txn_date value="{today}" required class=w-sm></div>
              <div><label>Amount</label><input name=amount type=number step=0.01 min=0.01 required class=w-sm></div></div>
              <div class="row"><div>{out_cat_combo}</div><div><label>Payee</label><input name=payee class=w-sm></div></div>
              <div class="row"><div><label>Ref</label><input name=ref_no class=w-xs></div><div><label>User Name</label><input name=user_name value="{desk}" class=w-sm maxlength=40></div></div>
              <div><label>Notes</label><input name=notes></div>
              {self._btn_row("Cash out", "pettyoutjobpop")}
              {self._job_info_popup('pettyoutjobpop')}
            </form>
          </div>
          <div class="card" style="padding:10px">
            <h2 style="font-size:14px;margin:0 0 6px">Cash in</h2>
            <form method=post action="/petty" style="margin:0">
              <input type=hidden name=direction value="in">
              <div class="row"><div><label>Date</label><input type=date name=txn_date value="{today}" required class=w-sm></div>
              <div><label>Amount</label><input name=amount type=number step=0.01 min=0.01 required class=w-sm></div></div>
              <div class="row"><div><label>Category</label><select name=category class=w-sm>{in_opts}</select></div><div><label>From</label><input name=payee placeholder="Bank / owner" class=w-sm></div></div>
              <div class="row"><div><label>Ref</label><input name=ref_no class=w-xs></div><div><label>User Name</label><input name=user_name value="{desk}" class=w-sm maxlength=40></div></div>
              <div><label>Notes</label><input name=notes></div>
              {self._btn_row("Cash in", "pettyinjobpop")}
              {self._job_info_popup('pettyinjobpop')}
            </form>
          </div>
        </div>
        """

    def view_customers(self, con):
        rows = con.execute(
            "SELECT customer_id, account_name, city_st, terms FROM customers ORDER BY account_name"
        ).fetchall()
        body = [
            f"<tr><td><a href='/customer/{html.escape(r['customer_id'])}'>{html.escape(r['customer_id'])}</a></td>"
            f"<td>{html.escape(r['account_name'])}</td><td>{html.escape(r['city_st'] or '')}</td>"
            f"<td>{html.escape(r['terms'])}</td></tr>"
            for r in rows
        ]
        return tabs_setup("/customers") + f"""<p style="margin:0 0 8px"><a class="btn" href="/customer/new">+ New Customer</a>
        <button type="button" class="vbtn" data-audit="/customers/all" data-title="All customers — audit" style="margin-left:8px">View All Customers</button></p>
        {capped_table(["ID", "Name", "City", "Terms"], body)}
        """ + self._done_box(con, "/customers")

    def view_customers_all(self, con):
        """Every customer — filterable, sortable audit popup."""
        rows = con.execute(
            "SELECT customer_id, account_name, city_st, terms, phone FROM customers ORDER BY account_name"
        ).fetchall()
        body = "".join(
            f"<tr><td><a href='/customer/{html.escape(r['customer_id'])}'>{html.escape(r['customer_id'])}</a></td>"
            f"<td>{html.escape(r['account_name'])}</td><td>{html.escape(r['city_st'] or '')}</td>"
            f"<td>{html.escape(r['terms'] or '')}</td><td>{html.escape(r['phone'] or '')}</td></tr>"
            for r in rows)
        return f"""
        <p class="hint"><input id="auditq" placeholder="Filter this list…" size="30"
        oninput="document.querySelectorAll('table.audit').forEach(t=>auditFilter(t,this.value))">
        <span class="mute">Click a column header to sort.</span></p>
        <table class="audit"><tr><th>ID</th><th>Name</th><th>City</th><th>Terms</th><th>Phone</th></tr>
        {body or '<tr><td colspan=5>No customers.</td></tr>'}</table>
        """ + AUDIT_TABLE_JS

    def view_customer_form(self, con, cid):
        row = None
        if cid:
            row = con.execute("SELECT * FROM customers WHERE customer_id=?", (cid,)).fetchone()
            if not row:
                return '<div class="err">Unknown customer.</div>'
        nxt = cid or engine.next_customer_id(con)
        terms_list = engine.lookups(con, "terms")
        terms_cur = row["terms"] if row else "Net 30"
        terms_combo = (
            combo_field("f_terms", "terms_text", [(t, t, t) for t in terms_list],
                        value=terms_cur, label="Payment terms", required=True, narrow=True,
                        placeholder="Type to search terms…")
            + f'<input type=hidden id="f_terms_id" name=terms value="{html.escape(str(terms_cur), quote=True)}">'
        )
        def v(k, default=""):
            if not row:
                return default
            val = row[k]
            return "" if val is None else str(val)
        contacts=[]; locations=[]
        if cid:
            contacts=con.execute("SELECT * FROM customer_contacts WHERE customer_id=? ORDER BY is_primary DESC, name",(cid,)).fetchall()
            locations=con.execute("SELECT * FROM customer_locations WHERE customer_id=? ORDER BY is_primary DESC, location_name",(cid,)).fetchall()
        contacts_html="".join(
            f"<tr><td>{html.escape(c['name'])}</td><td>{html.escape(c['role'] or '')}</td><td>{html.escape(format_phone(c['phone']))}</td><td>{html.escape(c['email'] or '')}</td>"
            f"<td>{'Primary' if c['is_primary'] else ''}</td><td><form method=post action='/customer/contact/delete' style='display:inline'><input type=hidden name=contact_id value='{c['contact_id']}'><input type=hidden name=customer_id value='{html.escape(cid)}'><button class='secondary'>Remove</button></form></td></tr>"
            for c in contacts) or '<tr><td colspan=6 class="hint">No contacts yet.</td></tr>'
        loc_html="".join(
            f"<tr><td>{html.escape(l['location_name'])}</td><td>{html.escape(l['street'] or '')}{('<br>'+html.escape(l['street2'])) if l['street2'] else ''}</td><td>{html.escape(', '.join(x for x in (l['city'],l['state'],l['zip']) if x))}</td><td>{'Primary' if l['is_primary'] else ''}</td><td><form method=post action='/customer/location/delete' style='display:inline'><input type=hidden name=location_id value='{l['location_id']}'><input type=hidden name=customer_id value='{html.escape(cid)}'><button class='secondary'>Remove</button></form></td></tr>"
            for l in locations) or '<tr><td colspan=5 class="hint">No additional locations yet.</td></tr>'
        contact_block = "" if not cid else f"""
        <section class=card>
          <h2>Contacts</h2><p class=hint>People at this customer who handle different parts of the relationship.</p>
          <table><tr><th>Name</th><th>Role</th><th>Phone</th><th>Email</th><th></th><th></th></tr>{contacts_html}</table>
          <form method=post action="/customer/contact/save" style="margin-top:8px">
            <input type=hidden name=customer_id value="{html.escape(cid)}">
            <div class=row><div><label>Contact Name</label><input name=name required></div><div><label>Role</label><select name=role><option>Main</option><option>Accounting / A/P</option><option>Purchasing</option><option>Service</option><option>Operations</option><option>Commercial / Terms</option><option>Other</option></select></div></div>
            <div class=row><div><label>Phone</label><input name=phone placeholder="+1 (337) 555-0100"></div><div><label>Email</label><input name=email type=email></div></div>
            <label><input type=checkbox name=is_primary value=1> Primary contact</label>
            <p><button class=secondary>Add Contact</button></p>
          </form>
        </section>
        <section class=card>
          <h2>Locations</h2><p class=hint>Addresses and branches associated with this customer. The primary/billing address above remains available for existing documents.</p>
          <table><tr><th>Location</th><th>Address</th><th>City / State / ZIP</th><th></th><th></th></tr>{loc_html}</table>
          <form method=post action="/customer/location/save" style="margin-top:8px">
            <input type=hidden name=customer_id value="{html.escape(cid)}">
            <div class=row><div><label>Location Name</label><input name=location_name placeholder="Main office, Lafayette yard, Houston branch" required></div><div></div></div>
            <label>Address</label><input name=street>
            <input name=street2 placeholder="Suite, building, c/o…">
            <div class=row><div><label>City</label><input name=city></div><div><label>State</label><input name=state maxlength=20></div></div>
            <div class=row><div><label>Zip</label><input name=zip maxlength=12></div><div></div></div>
            <label><input type=checkbox name=is_primary value=1> Make primary location</label>
            <p><button class=secondary>Add Location</button></p>
          </form>
        </section>
        """
        return f"""
        <h1>{'Edit' if row else 'New'} Customer</h1>
        <p class=hint>{'Customer ID: <b>'+html.escape(nxt)+'</b>' if row else 'Customer ID is assigned automatically.'}</p>
        <form method=post action="/customer/save">
          <input type=hidden name=customer_id value="{html.escape(nxt) if row else ''}">
          <section>
            <h2>Business Information</h2>
            <div class=row><div><label>Business Name</label><input name=account_name required value="{html.escape(v('account_name'))}"></div><div><label>DBA / trade name <span class=hint>(optional)</span></label><input name=short_name value="{html.escape(v('short_name'))}"></div></div>
            <div class=row><div><label>Primary Phone</label><input name=phone value="{html.escape(format_phone(v('phone')))}" placeholder="+1 (337) 555-0100"></div><div><label>General Email</label><input name=email type=email value="{html.escape(v('email'))}"></div></div>
          </section>
          <section>
            <h2>Primary / Billing Address</h2>
            <label>Address</label><input name=bill_street value="{html.escape(v('bill_street'))}">
            <input name=bill_street2 value="{html.escape(v('bill_street2'))}" placeholder="Suite, building, c/o…">
            <div class=row><div><label>City</label><input name=bill_city value="{html.escape(v('bill_city'))}"></div><div><label>State</label><input name=bill_state maxlength=20 value="{html.escape(v('bill_state'))}"></div></div>
            <div class=row><div><label>Zip</label><input name=bill_zip maxlength=12 value="{html.escape(v('bill_zip'))}"></div><div></div></div>
          </section>
          <section>
            <h2>Commercial Terms</h2>
            <div class=row><div>{terms_combo}</div><div><label>Credit Limit $</label><input name=credit_limit type=number step=0.01 value="{money_val(v('credit_limit'))}"></div></div>
            <p class=hint>Commercial terms contact is managed below with the other customer contacts.</p>
            <label><input type=checkbox name=waiver_default value=1 {"checked" if (not row) or row["waiver_default"] else ""}> Damage waiver on by default</label>
          </section>
          <section><label>Internal Notes</label><input name=notes value="{html.escape(v('notes'))}"></section>
          <p><button>Save Customer</button> <a class="btn secondary" href="/customers">Cancel</a></p>
        </form>
        {contact_block}
        """

    def view_reports(self, con, days=14, period="mtd", stay_from="", stay_to="", board="avail", show_all=False):
        """Reports: three prebuilts, all recorded actions, done."""
        return (self._reports_prebuilts() +
                "<h2>All Recorded Actions</h2>" + self._reports_actions(con) +
                self._done_box(con, "/reports"))

    def _reports_prebuilts(self):
        """The three weekly-meeting reports. Nothing else."""
        return """
        <div class="cards">
          <div class="card"><span>Billing</span><b style="font-size:16px">
            <a href="/reports/weekly/money">AR Aging</a></b>
            <span class="hint">Who owes what, by age.</span></div>
          <div class="card"><span>Fleet</span><b style="font-size:16px">
            <a href="/reports/weekly/fleet">Utilization</a></b>
            <span class="hint">Time on rent vs idle vs down, per unit.</span></div>
          <div class="card"><span>Pipeline</span><b style="font-size:16px">
            <a href="/reports/weekly/flow">This week's Flow</a></b>
            <span class="hint">What's moving through the shop.</span></div>
        </div>
        """

    def _reports_actions(self, con):
        """Every recorded action, today-on-down, capped with view-all."""
        acts = engine.done_tasks(con, "2000-01-01", date.today().isoformat(), 500)
        rows = "".join(
            f"<div class='todo'><span class='mute'>{html.escape(str(a.get('done_at') or '')[:10])}</span> "
            f"{html.escape(a.get('text') or '')} "
            f"{('<a class=vbtn href=' + html.escape(a['link'], quote=True) + '>Open</a>') if a.get('link') else ''}</div>"
            for a in acts[:5])
        if len(acts) > 5:
            rows += f"<p class='mute'>+ {len(acts) - 5} more</p>"
        return ((rows or "<p class='mute'>Nothing recorded yet.</p>") +
                '<div style="text-align:right;margin:8px 0 0">'
                '<button type="button" class="vbtn" data-audit="/done?period=year" '
                'data-title="All recorded actions — audit">View</button></div>')

    # ------------------------------------------------- Weekly push-button reports

    def _report_destinations(self, base, extra=""):
        """Print / PDF / CSV / Excel buttons for a prebuilt report."""
        return (
            '<p class="actions">'
            f'<a class="btn" href="/print/report/{base}{extra}">Print</a>'
            f'<a class="btn" href="/print/report/{base}.pdf{extra}">Pdf</a>'
            f'<a class="btn" href="/export/report/{base}.csv{extra}">Csv</a>'
            f'<a class="btn" href="/export/report/{base}.xlsx{extra}">Excel</a>'
            f'<a class="btn secondary" href="/export/report/{base}.json{extra}" data-tip="The raw data — plain JSON, nothing formatted.">Json</a>'
            f'<a class="btn secondary" href="/export/report/{base}.zip{extra}" data-tip="A zip with the CSV, the Excel file, and the raw JSON.">Zip</a>'
            "</p>"
        )

    def view_report_weekly_money(self, con):
        """Weekly money = the canonical AR aging table. Nothing else."""
        rep = engine.ar_aging(con)
        nav = tabs_reports("/reports") + weekly_tabs("/reports/weekly/money")
        heads = "".join(
            f"<th class=n>{html.escape(engine.BUCKET_LABELS[b])}</th>"
            for b in engine.BUCKETS)
        rows = "".join(
            f"<tr><td>{html.escape(r['customer'])}</td>"
            + "".join(f"<td class=n>${r[b]:,.2f}</td>" for b in engine.BUCKETS)
            + f"<td class=n><b>${r['total']:,.2f}</b></td></tr>"
            for r in rep["rows"])
        total = "".join(f"<td class=n><b>${rep['total'][b]:,.2f}</b></td>"
                        for b in engine.BUCKETS)
        pct = "".join(f"<td class=n>{rep['pct'][b]:.1f}%</td>" for b in engine.BUCKETS)
        return (nav
                + "<h2 style=\"font-size:19px;color:var(--frame)\">Weekly Money — AR Aging</h2>"
                f"<p class=\"hint\">As of {html.escape(rep['today'])}. Open balances only — no collected/invoiced summary.</p>"
                + self._report_destinations("aging")
                + f"<table class=\"audit\"><tr><th>Customer</th>{heads}<th class=n>Total</th></tr>"
                f"{rows or '<tr><td colspan=7>Nothing owed.</td></tr>'}"
                f"<tr><td><b>Total</b></td>{total}<td class=n><b>${rep['grand']:,.2f}</b></td></tr>"
                f"<tr><td>% of Total</td>{pct}<td></td></tr></table>"
                + AUDIT_TABLE_JS + self._done_box(con, "/reports/weekly/money"))

    def view_report_weekly_fleet(self, con, q):
        try:
            days = max(1, min(365, int(q.get("days") or 30)))
        except (TypeError, ValueError):
            days = 30
        rep = engine.fleet_utilization(con, days)
        nav = tabs_reports("/reports") + weekly_tabs("/reports/weekly/fleet")
        rows = "".join(
            f"<tr><td><b>{html.escape(r['unit_no'])}</b><br><span class=\"hint\">{html.escape(r['category'])}</span></td>"
            f"<td class=n>{r['rent_days']}</td><td class=n>{r['idle_days']}</td>"
            f"<td class=n>{r['down_days']}</td><td class=n>{r['util_pct']:.1f}%</td>"
            f"<td class=n>${r['revenue']:,.2f}</td></tr>"
            for r in rep["rows"])
        return (nav
                + "<h2 style=\"font-size:19px;color:var(--frame)\">Fleet Utilization</h2>"
                f"<p class=\"hint\">Last {rep['days']} days ({html.escape(rep['start'])} to {html.escape(rep['end'])}). "
                "Days only — hours ride with the rate-model redesign."
                + " ".join(f"<a href=\"/reports/weekly/fleet?days={d}\">{d}d</a>" for d in (7, 30, 90))
                + "</p>"
                + self._report_destinations("fleet", f"?days={rep['days']}")
                + "<table class=\"audit\"><tr><th>Unit</th><th class=n>Days on rent</th>"
                "<th class=n>Idle days</th><th class=n>Down (shop)</th><th class=n>Util %</th>"
                f"<th class=n>Revenue</th></tr>{rows}</table>"
                + AUDIT_TABLE_JS + self._done_box(con, "/reports/weekly/fleet"))

    def view_report_weekly_flow(self, con, q):
        span = "month" if (q.get("span") or "") == "month" else "week"
        rep = engine.weeks_flow(con, span)
        nav = tabs_reports("/reports") + weekly_tabs("/reports/weekly/flow")
        label = {k: lab for k, lab, _ in engine.FLOW_SECTIONS}
        sub = {k: s for k, _, s in engine.FLOW_SECTIONS}
        title = ("This week's flow" if span == "week"
                 else "Flow — exceptions, next 30 days")
        head = (nav
                + f"<h2 style=\"font-size:19px;color:var(--frame)\">{title}</h2>"
                + f"<p class=\"hint\">{html.escape(rep['start'])} to {html.escape(rep['end'])}. "
                + ("<a href=\"/reports/weekly/flow?span=week\">This Week</a> · <b>Month (Exceptions)</b>"
                   if span == "month" else
                   "<b>This Week</b> · <a href=\"/reports/weekly/flow?span=month\">Month (Exceptions)</a>")
                + "</p>"
                + self._report_destinations("flow", f"?span={span}"))
        parts = [head]
        for key, items in rep["sections"]:
            why = "<th>Why it flags</th>" if span == "month" else ""
            rows = "".join(
                f"<tr><td><a href=\"{html.escape(i['href'])}\">{html.escape(i['what'])}</a></td>"
                f"<td>{html.escape(i['who'])}</td><td>{html.escape(i['when'] or '')}</td>"
                + (f"<td>{html.escape(i.get('why') or '')}</td>" if span == "month" else "")
                + "</tr>" for i in items)
            parts.append(
                f"<h2 style=\"font-size:16px;color:var(--frame)\">{html.escape(label.get(key, key))} "
                f"<span class=\"hint\">— {html.escape(sub.get(key, ''))}</span></h2>"
                f"<table class=\"audit\"><tr><th>What</th><th>Who</th><th>When</th>{why}</tr>"
                f"{rows or '<tr><td colspan=4>Nothing.</td></tr>'}</table>")
        return "".join(parts) + self._done_box(con, "/reports/weekly/flow" + ("?span=month" if span == "month" else ""))

    def _availability_html(self, con, days, show_all=False):
        avail = engine.report_availability(con)
        up = engine.report_upcoming(con, days)
        counts = {}
        for r in avail:
            counts[r["board"]] = counts.get(r["board"], 0) + 1
        cards = "".join(
            f'<div class="card"><span>{html.escape(k)}</span><b>{v}</b></div>'
            for k,v in sorted(counts.items())
        )
        def row_a(r):
            cls = "pass" if r["rentable"] else ("fail" if r["board"] in ("Cert expired","Unusable") or r["cert_dead"] else "")
            tix = f"<a href='/ticket/{html.escape(r['ticket_id'])}'>{html.escape(r['ticket_id'])}</a>" if r["ticket_id"] else ""
            return (
                f"<tr><td><a href='/unit/{html.escape(r['asset_id'])}'>{html.escape(r['unit_no'])}</a></td>"
                f"<td>{html.escape(r['category'])}</td><td>{html.escape(r['description'])}</td>"
                f"<td class='{cls}'>{html.escape(r['board'])}</td><td>{tix}</td>"
                f"<td>{html.escape(r['customer_id'])}</td><td>{html.escape(r['cert_expire'])}</td></tr>"
            )
        AUDIT = "/reports?b=avail&all=1"
        def capped(items, label):
            """Cap a section at DASH_CAP with a quiet '+ N more' into the full dump."""
            shown = items if show_all else items[:DASH_CAP]
            more = "" if show_all else more_link(len(items), len(shown), AUDIT, label)
            return shown, more
        avail_shown, avail_more = capped(avail, "All units")
        avail_rows = "".join(row_a(r) for r in avail_shown)
        cert_shown, cert_more = capped(up["certs"], "All certs in window")
        cert_rows = "".join(
            f"<tr><td><a href='/unit/{html.escape(r['asset_id'])}'>{html.escape(r['unit_no'])}</a></td>"
            f"<td>{html.escape(r['description'])}</td>"
            f"<td class='{'fail' if r['dead'] else ''}'>{html.escape(r['cert_expire'])}</td>"
            f"<td class='{'fail' if r['dead'] else ''}'>{r['days']}d</td></tr>"
            for r in cert_shown
        )
        off_shown, off_more = capped(up["offs"], "All off-rent in window")
        off_rows = "".join(
            f"<tr><td><a href='/ticket/{html.escape(r['ticket_id'])}'>{html.escape(r['ticket_id'])}</a></td>"
            f"<td>{html.escape(r['unit_no'])}</td><td>{html.escape(r['account_name'])}</td>"
            f"<td>{html.escape(r['status'])}</td><td>{html.escape(r['off_rent'])}</td>"
            f"<td>{r['days']}d</td></tr>"
            for r in off_shown
        )
        miss_shown, miss_more = capped(up["missing_off"], "All open tickets")
        miss_rows = "".join(
            f"<tr><td><a href='/ticket/{html.escape(r['ticket_id'])}'>{html.escape(r['ticket_id'])}</a></td>"
            f"<td>{html.escape(r['unit_no'])}</td><td>{html.escape(r['account_name'])}</td>"
            f"<td class='fail'>{html.escape(r['status'])}</td><td>{html.escape(str(r['on_rent']))}</td></tr>"
            for r in miss_shown
        )
        watch = engine.fleet_compliance_watch(con)
        watch_shown = watch if show_all else watch[:DASH_CAP]
        watch_rows = "".join(
            f"<tr><td><a href='/ucompliance/{html.escape(w['asset_id'])}'>{html.escape(w['unit_no'])}</a></td>"
            f"<td>{html.escape(w['item'])}</td>"
            f"<td class='{'fail' if w['status']=='overdue' else ''}'>{w['status'].title()}</td>"
            f"<td>{html.escape(w['next_due'] or '—')}</td>"
            f"<td>{html.escape(w['last_done'] or 'no record')}</td>"
            f"<td>{html.escape(w['performer_name'] + (' ' + w['performer_phone'] if w['performer_phone'] else '') if w['performer_name'] else '—')}</td></tr>"
            for w in watch_shown
        )
        watch_more = ("" if show_all else
                      more_link(len(watch), len(watch_shown), "/reports?b=avail&all=1", "Compliance watch — everything"))
        return f"""
        <h2 class="rgroup">The Board</h2>
        <h2 style="font-size:16px;color:var(--frame)">Daily Availability</h2>
        <div class="cards">{cards or '<div class="card"><span>Units</span><b>0</b></div>'}</div>
        <table><tr><th>Unit</th><th>Cat</th><th>Description</th><th>Board</th><th>Ticket</th><th>Customer</th><th>Cert</th></tr>
        {avail_rows or '<tr><td colspan=7>No units.</td></tr>'}</table>
        {avail_more}

        <h2 class="rgroup">Upcoming · {days} Days</h2>
        <h2 style="font-size:16px;color:var(--frame)">Certs Due or Expired</h2>
        <table><tr><th>Unit</th><th>Description</th><th>Expire</th><th>Days</th></tr>
        {cert_rows or '<tr><td colspan=4>None in this window.</td></tr>'}</table>
        {cert_more}
        <h2 style="font-size:16px;color:var(--frame)">Checklist Items Due or Overdue</h2>
        <table><tr><th>Unit</th><th>Check</th><th>Status</th><th>Next due</th><th>Last done</th><th>Who to call</th></tr>
        {watch_rows or '<tr><td colspan=6>Nothing due. Assign a pack to a unit to start tracking.</td></tr>'}</table>
        {watch_more}
        <h2 style="font-size:16px;color:var(--frame)">Off-Rent in Window</h2>
        <table><tr><th>Ticket</th><th>Unit</th><th>Customer</th><th>Status</th><th>Off-rent</th><th>Days</th></tr>
        {off_rows or '<tr><td colspan=6>None dated in this window.</td></tr>'}</table>
        {off_more}
        <h2 style="font-size:16px;color:var(--frame)">On Rent With No Off-Rent Date</h2>
        <table><tr><th>Ticket</th><th>Unit</th><th>Customer</th><th>Status</th><th>On-rent</th></tr>
        {miss_rows or '<tr><td colspan=5>All live tickets have an off-rent date.</td></tr>'}</table>
        {miss_more}
        """

    def _invoicing_html(self, inv, show_all=False):
        buck = "".join(
            f'<div class="card"><span>{html.escape(k)}</span><b>${v:,.2f}</b></div>'
            for k,v in inv["buckets"].items()
        )
        AUDIT = "/reports?b=money&all=1"
        ready = inv["ready"] if show_all else inv["ready"][:DASH_CAP]
        ready_more = "" if show_all else more_link(len(inv["ready"]), len(ready), AUDIT, "Ready to invoice — everything")
        ready_rows = "".join(
            f"<tr><td><a href='/ticket/{html.escape(r['ticket_id'])}'>{html.escape(r['ticket_id'])}</a></td>"
            f"<td>{html.escape(r['account_name'])}</td><td>{html.escape(r['unit_no'])}</td>"
            f"<td>{html.escape(r['status'])}</td><td>${r['total']:,.2f}</td></tr>"
            for r in ready
        )
        invoices = inv["invoices"] if show_all else inv["invoices"][:DASH_CAP]
        inv_more = "" if show_all else more_link(len(inv["invoices"]), len(invoices), AUDIT, "Invoices — everything")
        inv_rows = "".join(
            f"<tr><td>{html.escape(r['invoice_no'])}</td><td>{html.escape(r['account_name'])}</td>"
            f"<td>{html.escape(r['invoice_date'])}</td><td>{html.escape(r['due'])}</td>"
            f"<td>{html.escape(r['status'])}</td><td>${r['total']:,.2f}</td><td>${r['paid']:,.2f}</td>"
            f"<td>${r['balance']:,.2f}</td><td class='{'fail' if r['days_late'] else ''}'>{html.escape(r['bucket'])}</td></tr>"
            for r in invoices
        )
        return f"""
        <h2 style="font-size:16px;color:var(--frame)">Invoicing Status</h2>
        <div class="cards">{buck}</div>
        <h2 style="font-size:16px;color:var(--frame)">Ready to Invoice</h2>
        <table class="audit"><tr><th>Ticket</th><th>Customer</th><th>Unit</th><th>Status</th><th>Total</th></tr>
        {ready_rows or '<tr><td colspan=5>Nothing sitting in Off Rent / Ready to Bill.</td></tr>'}</table>
        {ready_more}
        <h2 style="font-size:16px;color:var(--frame)">Invoices</h2>
        <table class="audit"><tr><th>No</th><th>Customer</th><th>Date</th><th>Due</th><th>Status</th><th>Total</th><th>Paid</th><th>Balance</th><th>Aging</th></tr>
        {inv_rows or '<tr><td colspan=9>No invoices.</td></tr>'}</table>
        {inv_more}
        """ + AUDIT_TABLE_JS

    def _recap_html(self, recap, days, period, show_all=False):
        AUDIT = f"/reports?b=money&days={days}&p={period}&all=1"
        new = recap["new_tickets"] if show_all else recap["new_tickets"][:DASH_CAP]
        new_more = "" if show_all else more_link(len(recap["new_tickets"]), len(new), AUDIT, "Tickets started — everything")
        newt = "".join(
            f"<tr><td><a href='/ticket/{html.escape(r['ticket_id'])}'>{html.escape(r['ticket_id'])}</a></td>"
            f"<td>{html.escape(r['account_name'])}</td><td>{html.escape(r['unit_no'])}</td>"
            f"<td>{html.escape(r['status'])}</td><td>{html.escape(str(r['on_rent']))}</td></tr>"
            for r in new
        )
        start = html.escape(recap["start"])
        end = html.escape(recap["end"])
        return f"""
        <h2 style="font-size:19px;color:var(--frame);margin-top:28px">Recap · {html.escape(recap['label'])}</h2>
        <div class="cards">
          <div class="card"><span>New tickets</span><b>{recap['new_n']}</b></div>
          <div class="card"><span>Came off rent</span><b>{recap['off_n']}</b></div>
          <div class="card"><span>Billed</span><b>${recap['billed']:,.2f}</b></div>
          <div class="card"><span>Cash in</span><b>${recap['cash']:,.2f}</b></div>
          <div class="card"><span>On rent now</span><b>{recap['on_now']}</b></div>
          <div class="card"><span>Open fit fails</span><b>{recap['fail_open']}</b></div>
        </div>
        <h2 style="font-size:16px;color:var(--frame)">Tickets Started {start} – {end}</h2>
        <table class="audit"><tr><th>Ticket</th><th>Customer</th><th>Unit</th><th>Status</th><th>On-rent</th></tr>
        {newt or f'<tr><td colspan=5>No new tickets {start} – {end}.</td></tr>'}</table>
        {new_more}
        """ + AUDIT_TABLE_JS

    def _stays_html(self, stays, days, period, show_all=False):
        STAY_CAP = 20
        rows_all = stays["rows"]
        rows_shown = rows_all if show_all else rows_all[:STAY_CAP]
        stay_more = "" if show_all else more_link(
            len(rows_all), len(rows_shown),
            f"/reports?b=stays&days={days}&p={html.escape(period)}"
            f"&from={html.escape(stays['start'])}&to={html.escape(stays['end'])}&all=1",
            "Asset stays — everything")
        rows = "".join(
            f"<tr><td><a href='/unit/{html.escape(r['asset_id'])}'>{html.escape(r['unit_no'])}</a></td>"
            f"<td>{html.escape(r['description'])}</td>"
            f"<td><a href='/ticket/{html.escape(r['ticket_id'])}'>{html.escape(r['ticket_id'])}</a></td>"
            f"<td>{html.escape(r['account_name'])}</td><td>{html.escape(r['site_name'])}</td>"
            f"<td>{html.escape(r['on_rent'])}</td><td>{html.escape(str(r['off_rent']))}</td>"
            f"<td>{r['overlap_days']}</td><td>{html.escape(r['status'])}</td></tr>"
            for r in rows_shown
        )
        return f"""
        <h2 style="font-size:19px;color:var(--frame)">Asset Stays</h2>
        <form method=get action="/reports">
          <input type=hidden name=b value="stays">
          <input type=hidden name=days value="{days}">
          <input type=hidden name=p value="{html.escape(period)}">
          <div class="row">
            <div><label>From</label><input type=date name=from value="{html.escape(stays['start'])}"></div>
            <div><label>To</label><input type=date name=to value="{html.escape(stays['end'])}"></div>
          </div>
          <p><button>Show Stays</button></p>
        </form>
        <table class="audit"><tr><th>Unit</th><th>Description</th><th>Ticket</th><th>Customer</th><th>Site</th><th>On</th><th>Off</th><th>Days in range</th><th>Status</th></tr>
        {rows or '<tr><td colspan=9>No stays in this range.</td></tr>'}</table>
        {stay_more}
        """ + AUDIT_TABLE_JS

    def _maint_html(self, maint, show_all=False):
        AUDIT = "/reports?b=avail&all=1"
        shop_items = maint["shop"] if show_all else maint["shop"][:DASH_CAP]
        shop_more = ("" if show_all else
                     more_link(len(maint["shop"]), len(shop_items), AUDIT, "All units in shop"))
        shop = "".join(
            f"<tr><td><a href='/unit/{html.escape(r['asset_id'])}'>{html.escape(r['unit_no'])}</a></td>"
            f"<td>{html.escape(r['description'])}</td><td>{html.escape(r['condition'])}</td>"
            f"<td>{html.escape(r['yard'])}</td><td>{html.escape(r['cert_expire'])}</td></tr>"
            for r in shop_items
        )
        cert_items = maint["certs"] if show_all else maint["certs"][:DASH_CAP]
        cert_more = ("" if show_all else
                     more_link(len(maint["certs"]), len(cert_items), AUDIT, "All certs in window"))
        certs = "".join(
            f"<tr><td><a href='/unit/{html.escape(r['asset_id'])}'>{html.escape(r['unit_no'])}</a></td>"
            f"<td>{html.escape(r['description'])}</td>"
            f"<td class='{'fail' if r['dead'] else ''}'>{html.escape(r['cert_expire'])}</td>"
            f"<td class='{'fail' if r['dead'] else ''}'>{r['days']}d</td></tr>"
            for r in cert_items
        )
        return f"""
        <h2 class="rgroup">Housekeeping</h2>
        <div class="cards">
          <div class="card"><span>In shop / inactive</span><b>{maint['shop_n']}</b></div>
          <div class="card"><span>Cert expired or ≤30 days</span><b>{maint['cert_n']}</b></div>
        </div>
        <h2 style="font-size:16px;color:var(--frame)">Not Available to Rent</h2>
        <table><tr><th>Unit</th><th>Description</th><th>Condition</th><th>Yard</th><th>Cert</th></tr>
        {shop or '<tr><td colspan=5>No units in the shop.</td></tr>'}</table>
        {shop_more}
        <h2 style="font-size:16px;color:var(--frame)">Cert Window (30 Days)</h2>
        <table><tr><th>Unit</th><th>Description</th><th>Expire</th><th>Days</th></tr>
        {certs or '<tr><td colspan=4>No certs in the 30-day window.</td></tr>'}</table>
        {cert_more}
        """

    def view_money_all(self, con):
        """The Money working page: open invoices and recent payments, capped.
        The full sortable/filterable audit sits behind one quiet View button."""
        big = engine.big_fish_invoices(con)["invoice_nos"]
        open_inv = sorted(engine.list_open_invoices(con),
                          key=lambda r: r["balance"], reverse=True)
        rows = ""
        for r in open_inv[:DASH_CAP]:
            flag = " <b>Key Account</b>" if r["invoice_no"] in big else ""
            rows += (f"<div class='todo'><a href='/invoice/{html.escape(r['invoice_no'], quote=True)}'>"
                     f"{html.escape(r['invoice_no'])} — {html.escape(r['account_name'])}</a> "
                     f"<span class='mute'>${r['balance']:,.2f}</span>{flag}</div>")
        rows += more_link(len(open_inv), min(len(open_inv), DASH_CAP), "/money/audit", "All money — audit")
        pays = con.execute(
            "SELECT pay_date, invoice_no, method, amount, kind FROM collections "
            "ORDER BY pay_date DESC, pay_id DESC LIMIT 5").fetchall()
        prows = "".join(
            f"<div class='todo'><span class='mute'>{html.escape(str(p['pay_date'])[:10])}</span> "
            f"${p['amount']:,.2f} — {html.escape(p['kind'])} "
            f"<a href='/invoice/{html.escape(p['invoice_no'], quote=True)}'>{html.escape(p['invoice_no'])}</a></div>"
            for p in pays)
        return tabs_invoice("/money/all") + f"""
        <h2>Open Invoices ({len(open_inv)})</h2>
        {rows or "<p class='mute'>Nothing outstanding.</p>"}
        <h2>Recent Payments</h2>
        {prows or "<p class='mute'>No payments recorded yet.</p>"}
        {view_button("/money/audit", "All money — audit")}
        """ + self._done_box(con, "/money/all")

    def view_money_audit(self, con):
        """Every money record, as it sits — filterable, sortable."""
        big = engine.big_fish_invoices(con)["invoice_nos"]
        inv_rows = "".join(
            f"<tr><td><a href='/invoice/{html.escape(r['invoice_no'])}'>{html.escape(r['invoice_no'])}</a></td>"
            f"<td>{html.escape(r['account_name'])}</td>"
            f"<td>{html.escape(str(r['invoice_date'])[:10])}</td>"
            f"<td>{html.escape(r['status'])}</td>"
            f"<td>${engine.invoice_totals(con, r['invoice_no'])['balance']:,.2f}</td>"
            f"<td>{'<b>Key Account</b>' if r['invoice_no'] in big else ''}</td>"
            "<td>" + _task_from_row(r['invoice_no'] + " — " + r['account_name'], "/invoice/" + r['invoice_no'], '/money/audit') + "</td></tr>"
            for r in con.execute(
                """SELECT i.invoice_no, i.invoice_date, i.status, c.account_name
                   FROM invoices i JOIN customers c ON c.customer_id=i.customer_id""")
        )
        pay_rows = "".join(
            f"<tr><td>{html.escape(str(r['pay_date'])[:10])}</td>"
            f"<td><a href='/invoice/{html.escape(r['invoice_no'])}'>{html.escape(r['invoice_no'])}</a></td>"
            f"<td>{html.escape(r['method'])}</td><td>${r['amount']:,.2f}</td>"
            f"<td>{html.escape(r['kind'])}</td>"
            "<td>" + _task_from_row(r['kind'] + " $" + ("%.2f" % r['amount']) + " on " + r['invoice_no'], "/invoice/" + r['invoice_no'], '/money/audit') + "</td></tr>"
            for r in con.execute(
                "SELECT pay_date, invoice_no, method, amount, kind FROM collections")
        )
        return tabs_invoice("/money/all") + f"""
        <p class="hint"><input id="auditq" placeholder="Filter these lists…" size="30"
        oninput="document.querySelectorAll('table.audit').forEach(t=>auditFilter(t,this.value))">
        <span class="mute">Click a column header to sort.</span></p>
        <h2>Invoices</h2>
        <table class="audit"><tr><th>No</th><th>Customer</th><th>Date</th><th>Status</th><th>Balance</th><th>Flag</th><th></th></tr>
        {inv_rows or '<tr><td colspan=7>No invoices.</td></tr>'}</table>
        <h2>Payments &amp; Credits</h2>
        <table class="audit"><tr><th>Date</th><th>Invoice</th><th>Method</th><th>Amount</th><th>Kind</th><th></th></tr>
        {pay_rows or '<tr><td colspan=6>No payments.</td></tr>'}</table>
        """ + AUDIT_TABLE_JS

    def view_invoices(self, con):
        rows = con.execute(
            """SELECT i.invoice_no, i.invoice_date, i.status, i.customer_id, c.account_name
               FROM invoices i JOIN customers c ON c.customer_id=i.customer_id
               ORDER BY i.invoice_date DESC"""
        ).fetchall()
        body = "".join(
            f"<tr><td>{html.escape(r['invoice_no'])}</td>"
            f"<td>{html.escape(r['account_name'])}</td>"
            f"<td>{html.escape(str(r['invoice_date'])[:10])}</td>"
            f"<td>{html.escape(r['status'])}</td>"
            f"<td>${engine.invoice_totals(con, r['invoice_no'])['balance']:,.2f}</td>"
            f"<td><a href='/invoice/{html.escape(r['invoice_no'])}'>Po Lines</a> · "
            f"<a href='/print/invoice/{html.escape(r['invoice_no'])}'>On Screen</a> · "
            f"<a href='/print/invoice/{html.escape(r['invoice_no'])}.pdf'>Pdf File</a></td></tr>"
            for r in rows
        )
        return tabs_invoice("/invoices") + f"""<h1>Invoices — Print</h1>
        <table><tr><th>No</th><th>Customer</th><th>Date</th><th>Status</th><th>Balance</th><th>Print</th></tr>
        {body or '<tr><td colspan=6>No invoices.</td></tr>'}</table>"""

    def view_invoice_lines(self, con, ino):
        inv = con.execute(
            """SELECT i.*, c.account_name FROM invoices i
               JOIN customers c ON c.customer_id=i.customer_id WHERE i.invoice_no=?""",
            (ino,),
        ).fetchone()
        if not inv:
            return tabs_invoice("/invoices") + "<p>Unknown invoice.</p>"
        tot = engine.invoice_totals(con, ino)
        locked = engine.invoice_locked(con, ino)
        lines = con.execute(
            "SELECT * FROM invoice_lines WHERE invoice_no=? ORDER BY line_id", (ino,)
        ).fetchall()
        body = "".join(
            f"<tr><td>{html.escape(r['po_line'] or '')}</td>"
            f"<td>{html.escape(r['category'])}</td>"
            f"<td>{html.escape(r['description'])}</td>"
            f"<td>{float(r['qty']):g} {html.escape(r['uom'])}</td>"
            f"<td>${float(r['rate']):,.2f}</td>"
            f"<td>${float(r['amount']):,.2f}</td>"
            f"<td>{html.escape(r['clerk'] or '')}</td>"
            f"<td>{'' if locked else '<form method=post action=/invoice/'+html.escape(ino)+'/linedel>'+self.clerk_field(con)+'<input type=hidden name=invoice_no value='+html.escape(ino)+'><input type=hidden name=line_id value='+str(r['line_id'])+'><button class=secondary>Remove</button></form>'}</td></tr>"
            for r in lines
        )
        line_cat_combo = (
            combo_field("f_line_cat", "category_text",
                        [(v, v, v) for v in engine.lookups(con, "inv_cat")],
                        label="Category", required=True,
                        placeholder="Type to search categories…")
            + '<input type=hidden id="f_line_cat_id" name=category value="">'
        )
        line_uom_combo = (
            combo_field("f_line_uom", "uom_text",
                        [(v, v, v) for v in engine.lookups(con, "inv_uom")],
                        label="Unit", required=True,
                        placeholder="Type to search units…")
            + '<input type=hidden id="f_line_uom_id" name=uom value="">'
        )
        add = "" if locked else f"""
        <h2 style="font-size:16px;color:var(--frame)">Add a Po Line</h2>
        <form method=post action="/invoice/{html.escape(ino)}/line">
          <div class="row">
            <div><label>Po Line #</label><input name=po_line placeholder="10"></div>
            <div>{line_cat_combo}</div>
          </div>
          <label>Description (PO Wording)</label>
          <input name=description required placeholder="4in 1502 pup joint rental — 14 days">
          <div class="row">
            <div><label>Qty</label><input name=qty type=number step=0.01 min=0.01 value=1 required class=w-xs></div>
            <div>{line_uom_combo}</div>
            <div><label>Rate $</label><input name=rate type=number step=0.01 value=0 required class=w-sm></div>
          </div>
          {self.clerk_field(con)}
          <p><button>Add Line</button></p>
        </form>
        """
        po = inv["po"] if "po" in inv.keys() and inv["po"] else ""
        # Q6: PO detail reads through the shared PO record — one PO, one
        # expiry, across every invoice carrying it.
        _pc0 = engine.po_check(con, ino)
        po_expire = _pc0["expire"]
        po_cost_code = _pc0["cost_code"]
        po_notes = _pc0["notes"]
        # Invoice-time PO check: view-only, never blocking. Catches the silent
        # rejection before it costs months — never says "you can't".
        po_panel = ""
        if po and inv["status"] not in ("Paid", "Write-off"):
            pc = _pc0
            warn = ""
            if pc["expired"]:
                warn = (f"<br>PO {html.escape(pc['po'])} expired {html.escape(pc['date_str'])} — "
                        "invoicing against it risks silent rejection and a whole new-PO cycle.")
            elif pc["expiring_soon"]:
                warn = (f"<br>PO {html.escape(pc['po'])} expires {html.escape(pc['date_str'])} "
                        f"({pc['days']} days).")
            po_panel = ""
            if pc["expired"]:
                po_panel = (f"<div class='err'>PO {html.escape(pc['po'])} expired "
                            f"{html.escape(pc['date_str'])} — invoicing against it risks silent rejection.</div>")
            elif pc["expiring_soon"]:
                po_panel = (f"<p class='hint'>PO {html.escape(pc['po'])} expires "
                            f"{html.escape(pc['date_str'])} ({pc['days']} days).</p>")
        qno = inv["quote_no"] if "quote_no" in inv.keys() and inv["quote_no"] else ""
        quote_panel = quote_expiry_panel(con, qno) if inv["status"] not in ("Paid", "Write-off") else ""
        # Upper-right job box: PO#, Well#, Job Location — the three things
        # required to get paid — plus Tax Exempt Cert when the job is exempt.
        # Well/location derive from the invoice's tickets; PO expiry is record
        # data and never appears here or as a line.
        _jb = engine.invoice_job_box(con, ino)
        _well = ", ".join(_jb["wells"]) or "—"
        _loc = ", ".join(_jb["locations"]) or "—"
        _taxline = ("<div>Tax Exempt Cert <b>✓ on File</b></div>"
                    if _jb["tax_exempt"] else "")
        job_box = f"""
        <div style="float:right;border:1px solid #c9a227;border-radius:8px;padding:10px 14px;
                    background:#fffdf5;min-width:230px;margin:0 0 8px 12px;font-size:14px">
          <div style="font-weight:700;color:#1B2A4A;margin-bottom:6px">Job Info</div>
          <div>PO# <b>{html.escape(_jb["po"]) or "—"}</b></div>
          <div>Well# <b>{html.escape(_well)}</b></div>
          <div>Job Location <b>{html.escape(_loc)}</b></div>
          {_taxline}
        </div>"""
        # Paperwork scan-in slots: the PO scan and the tax-exempt certificate
        # attach to the invoice and travel with it (print + PDF pack).
        def _slot(kind, label):
            d = _jb["po_doc"] if kind == "po" else _jb["tax_doc"]
            cur = (f"<div><a href='/invoicedoc/{html.escape(ino, quote=True)}/{kind}'>"
                   f"{html.escape(d['filename'])}</a> "
                   f"<span class='hint'>{d['bytes']/1024:.0f} KB · {html.escape(str(d['uploaded_at'])[:10])}</span> "
                   f"<form method=post action='/invoice/{html.escape(ino, quote=True)}/docdel' style='display:inline'>"
                   f"<input type=hidden name=kind value='{kind}'>"
                   f"{self.clerk_field(con)}<button class=secondary>Remove</button></form></div>"
                   if d else "<div class='hint'>None attached.</div>")
            return f"""
          <div><b>{label}</b>{cur}
            <form method=post action="/invoice/{html.escape(ino, quote=True)}/doc"
                  enctype="multipart/form-data" class="actions">
              <input type=file name=doc_file accept=".pdf,.png,.jpg,.jpeg,.webp,.txt,.csv">
              <input type=hidden name=kind value="{kind}">
              {self.clerk_field(con)}
              <button class=secondary>Attach{' New' if d else ''}</button>
            </form>
          </div>"""
        paperwork = f"""
        <h2 style="font-size:16px;color:var(--frame)">Paperwork</h2>
        <div class="row">{_slot("po", "PO scan")}{_slot("tax_exempt", "Tax-exempt certificate")}</div>"""
        pays = con.execute(
            "SELECT * FROM collections WHERE invoice_no=? ORDER BY pay_date, pay_id",
            (ino,)
        ).fetchall()
        pay_rows = "".join(
            f"<tr><td>{html.escape(p['pay_date'] or '')}</td>"
            f"<td>{'Credit memo' if p['kind']=='credit' else html.escape(p['method'] or '')}</td>"
            f"<td>{html.escape(p['cm_no']) if p['kind']=='credit' and p['cm_no'] else html.escape(p['ref_no'] or '')}</td>"
            f"<td>${float(p['amount']):,.2f}</td>"
            f"<td>${float(p['applied_amount'] if p['applied_amount'] is not None else p['amount']):,.2f}</td>"
            f"<td>{html.escape(p['clerk'] or '')}</td></tr>"
            for p in pays
        )
        payments_html = f"""
        <h2 style="font-size:16px;color:var(--frame)">Payments &amp; Credits</h2>
        <table><tr><th>Date</th><th>Method</th><th>Ref / CM #</th><th>Amount</th><th>Applied</th><th>Clerk</th></tr>
        {pay_rows or '<tr><td colspan=6>No payments or credits applied yet.</td></tr>'}</table>
        """
        invpay_method_combo = (
            combo_field("f_invpay_method", "method_text",
                        [(m, m, m) for m in engine.CASH_METHODS],
                        label="Method", placeholder="Type to search methods…")
            + '<input type=hidden id="f_invpay_method_id" name=method value="">'
        )
        return tabs_invoice("/invoices") + f"""
        {job_box}
        <h1>{html.escape(ino)} · {html.escape(inv['account_name'])}</h1>
        {task_nudge(con, f"/invoice/{ino}")}
        <p>Status {html.escape(inv['status'])} · Subtotal ${tot['subtotal']:,.2f} · Tax ${tot['tax']:,.2f}
           · Total ${tot['total']:,.2f} · Balance ${tot['balance']:,.2f}</p>
        {po_panel}
        {quote_panel}
        <form method=post action="/invoice/{html.escape(ino)}/po">
          <label>Customer Po</label>
          <input name=po value="{html.escape(po)}" {"readonly" if locked else ""}>
          <div class="row">
            <div><label>Po Expires (Optional)</label><input type=date name=po_expire value="{html.escape(po_expire)}" {"readonly" if locked else ""}></div>
            <div><label>Cost Code (Optional)</label><input name=po_cost_code value="{html.escape(po_cost_code)}" placeholder="their cost code" {"readonly" if locked else ""}></div>
          </div>
          <label>Other Po Requirements (Optional)</label>
          <input name=po_notes value="{html.escape(po_notes)}" placeholder="anything else their PO demands" {"readonly" if locked else ""}>
          <p class="hint">Expiry, cost code, and notes live on the PO itself — shared across every invoice carrying this PO.</p>
          {self.clerk_field(con) if not locked else ""}
          {"" if locked else "<p><button>Save Po</button></p>"}
        </form>
        {paperwork}
        <div style="clear:both"></div>
        <table><tr><th>PO line</th><th>Cat</th><th>Description</th><th>Qty</th><th>Rate</th><th>Amount</th><th>Name</th><th></th></tr>
        {body or '<tr><td colspan=8>No extra lines. Ticket and work-order lines still print.</td></tr>'}</table>
        {add}
        {payments_html}
        <h2 id="record-payment" style="font-size:16px;color:var(--frame)">Record Payment</h2>
        <form method=post action="/pay">
          <input type=hidden name=invoice_no value="{html.escape(ino, quote=True)}">
          <div class="row">
            <div><label>Amount</label><input name=amount type=number step=0.01 min=0.01 required class=w-sm></div>
            <div><label>Date</label><input type=date name=pay_date value="{date.today().isoformat()}" required></div>
          </div>
          <div class="row">
            <div><label>Ref / Check #</label><input name=ref></div>
            <div>{invpay_method_combo}</div>
          </div>
          <p><button>Apply Payment</button></p>
        </form>
        <p><a class="btn" href="/print/invoice/{html.escape(ino)}">Print Invoice</a></p>
        """
