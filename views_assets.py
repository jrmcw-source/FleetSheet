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
from views_core import task_nudge, _task_from_row

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

"""FleetSheet views — assets flow: units, sites, tickets, work orders."""

from views_core import (
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
    _ack_forms,
    combo_field,
    combo_opts,
    capped_table,
    CoreViews,)


def _empty_action(title, detail, href, label):
    return (f"<div class='empty-action'><strong>{html.escape(title)}</strong>"
            f"<p>{html.escape(detail)}</p><a class='btn' href='{html.escape(href, quote=True)}'>{html.escape(label)} →</a></div>")


class AssetViews(CoreViews):
    """FleetSheet views views mixed into Handler."""

    def _job_info_popup(self, pid, vals=None):
        """Universal job info popup — duplicated from CoreViews for standalone use."""
        from views_core import CoreViews
        return CoreViews._job_info_popup(self, pid, vals)

    def _btn_row(self, save_label="Save", jobpop=None, add_item=False, extra=""):
        from views_core import CoreViews
        return CoreViews._btn_row(self, save_label, jobpop, add_item, extra)
    def _ticket_kind_bar(self, kind):
        tabs = "".join(
            f'<a class="{"on" if k == kind else ""}" href="/ticket/new?kind={k}">{lab}</a>'
            for k, lab in (("sale", "Sale"),
                           ("rental", "Rental"),
                           ("quote", "Quote"),
                           ("change", "Change Order"),
                           ("workorder", "Work Order"),
                           ("checkinout", "Check In/Out")))
        return f'<div class="tabs">{tabs}</div>'

    def _rentals_done(self, con, kind, label):
        """Completed toggle for a Rentals sub-tab. The done-today log itself
        lives once at the bottom of the Rentals page (aggregating all sub-tabs)."""
        return self._rentals_complete_toggle(con, kind, label)

    def _rentals_complete_toggle(self, con, kind, label):
        # Removed from the working UI: completion is represented by the actual
        # rental/work-order state, not a separate page-level toggle.
        return ""

    def view_new_ticket(self, con, q=None):
        kind = ((q or {}).get("kind") or "sale").strip()
        if kind not in ("sale", "rental", "quote", "change", "workorder", "checkinout"):
            kind = "sale"
        # legacy ?kind=delivery still lands on the Rental sub-tab
        if kind == "delivery":
            kind = "rental"
        # PO soft-reserve conflict: name the stakes, operator picks the winner.
        sc = ((q or {}).get("soft_conflict") or "").strip()
        if sc:
            return self._soft_conflict_page(con, sc)
        bar = self._ticket_kind_bar(kind)
        # One done-today at the bottom of the Rentals page, aggregating every
        # sub-tab's completions (they all log to the same done log).
        done = self._done_box(con, "/ticket/new") if hasattr(self, "_done_box") else ""
        if kind == "sale":
            body = self.view_sale(con, None)
            # view_sale returns full page; extract just the form portion for sub-tab
            return bar + body + self._rentals_done(con, "sale", "Sale") + done
        if kind == "quote":
            body = self.view_quote_form(con, None, bare=True)
            return bar + body + self._rentals_done(con, "quote", "Quote") + done
        if kind == "change":
            body = self.view_changes(con, {"quote_no": (q or {}).get("quote_no", "")}, bare=True)
            return bar + body + self._rentals_done(con, "change", "Change order") + done
        if kind == "workorder":
            body = self.view_wo_form(con, None, bare=True)
            return bar + body + self._rentals_done(con, "workorder", "Work order") + done
        if kind == "checkinout":
            return bar + self._new_ticket_checkinout(con) + self._rentals_done(con, "checkinout", "Check in/out") + done
        return bar + self._new_ticket_delivery(con, q) + self._rentals_done(con, "rental", "Rental") + done

    def _soft_conflict_page(self, con, pending_id):
        """PO soft-reserve conflict: the unit is softly held for one job and
        the operator is booking another. Name the stakes; the operator picks
        which reservation wins. The app only flags — it never auto-blocks."""
        import json
        prow = con.execute("SELECT * FROM pending_bookings WHERE pending_id=?",
                           (pending_id,)).fetchone()
        if not prow:
            return "<h1>Reservation Conflict</h1><p class='hint'>That booking expired. <a href='/ticket/new'>Start Over</a>.</p>"
        booking = json.loads(prow["data_json"])
        soft = con.execute(
            """SELECT t.ticket_id, t.job_name, t.well_or_pad, t.po, t.on_rent, t.off_rent,
                      c.account_name, a.unit_no
               FROM tickets t
               LEFT JOIN customers c ON c.customer_id=t.customer_id
               LEFT JOIN assets a ON a.asset_id=t.asset_id
               WHERE t.ticket_id=?""", (prow["soft_ticket_id"],)).fetchone()
        new_cust = con.execute("SELECT account_name FROM customers WHERE customer_id=?",
                               (booking.get("customer_id"),)).fetchone()
        new_unit = con.execute("SELECT unit_no FROM assets WHERE asset_id=?",
                               (booking.get("asset_id"),)).fetchone()

        def stakes_row(job, cust_name, unit_no, po, on_rent, off_rent):
            dates = (on_rent or "?") + (" → " + off_rent if off_rent else "")
            po_txt = f", PO {po}" if po else ""
            return (f"<b>{html.escape(unit_no or '?')}</b> — "
                    f"<b>{html.escape(job or '—')}</b>, {html.escape(cust_name or '?')}"
                    f"{po_txt}, {html.escape(dates)}")

        soft_job = soft["job_name"] or soft["well_or_pad"] or "—"
        new_job = booking.get("job_name") or booking.get("well_or_pad") or "—"
        body = f"""
        <h1>Which Reservation Wins?</h1>
        <div class='card' style='border-left:4px solid var(--gold)'>
          <p><b>Existing Soft Reservation</b> (ticket {html.escape(soft['ticket_id'])}):<br>
          {stakes_row(soft_job, soft['account_name'], soft['unit_no'], soft['po'], soft['on_rent'], soft['off_rent'])}</p>
          <p><b>New Booking:</b><br>
          {stakes_row(new_job, new_cust['account_name'] if new_cust else None,
                      new_unit['unit_no'] if new_unit else None, booking.get('po'),
                      booking.get('on_rent'), booking.get('off_rent'))}</p>
          <p class='hint'>A PO soft-reserve never blocks an interim job on its own —
          you decide.</p>
        </div>
        <form method='post' action='/ticket/new/override' style='display:inline'>
          <input type='hidden' name='pending_id' value='{html.escape(pending_id, quote=True)}'>
          <button class='btn-gold'>Book the New Job Instead</button>
        </form>
        <form method='post' action='/ticket/new/cancel' style='display:inline;margin-left:12px'>
          <input type='hidden' name='pending_id' value='{html.escape(pending_id, quote=True)}'>
          <button>Keep the Existing Reservation</button>
        </form>"""
        return body

    def _new_ticket_checkinout(self, con):
        """Fast yard movement screen: choose direction first, then identify the unit/ticket."""
        out_now = con.execute(
            """SELECT t.ticket_id, a.unit_no, a.asset_id, c.account_name, t.status
               FROM tickets t JOIN assets a ON a.asset_id=t.asset_id JOIN customers c ON c.customer_id=t.customer_id
               WHERE t.status IN ('Dispatched','On Rent') ORDER BY t.on_rent DESC LIMIT 6""").fetchall()
        in_yard = con.execute(
            """SELECT t.ticket_id, a.unit_no, a.asset_id, c.account_name, t.status
               FROM tickets t JOIN assets a ON a.asset_id=t.asset_id JOIN customers c ON c.customer_id=t.customer_id
               WHERE t.status = 'Reserved' ORDER BY t.on_rent DESC LIMIT 6""").fetchall()
        def row(r, direction):
            return (f"<div class='todo'><a href='#' class='cio-pick' data-tid='{html.escape(r['ticket_id'], quote=True)}' "
                    f"data-label='{html.escape(r['unit_no']+' — '+r['account_name'], quote=True)}' data-dir='{direction}'>"
                    f"{html.escape(r['unit_no'])}</a> — {html.escape(r['account_name'])} <span class='mute'>{html.escape(r['status'])}</span></div>")
        out_rows=''.join(row(r,'in') for r in out_now[:5]); in_rows=''.join(row(r,'out') for r in in_yard[:5])
        out_more = f"<p class='mute'>+ {len(out_now)-5} more</p>" if len(out_now) > 5 else ""
        in_more = f"<p class='mute'>+ {len(in_yard)-5} more</p>" if len(in_yard) > 5 else ""
        conds = ("Excellent","Good","Fair","Poor","Damaged","Other / note")
        return f"""
        <form method=post action="/rentals/checkinout" id="cioform">
          <div class="row">
            <div><label>Movement</label><select name=direction id=cio_dir><option value="in">Check in</option><option value="out">Check Out</option></select></div>
            <div><label>Unit / Asset</label><input id="cio_pick" placeholder="Search or pick a unit below…" readonly><input type=hidden id=cio_tid name=ticket_id required></div>
          </div>
          <div class="row">
            <div><label>Condition</label><select name=condition required><option value="">Select Condition</option>{''.join('<option>'+html.escape(c)+'</option>' for c in conds)}</select></div>
            <div><label>Clerk</label><input name=clerk value="{html.escape(self.desk(con))}"></div>
          </div>
          <div class="row"><div><label>Meter / Hours / Fuel</label><input name=meter></div><div><label>Note</label><input name=note placeholder="Damage, exception, arrival detail…"></div></div>
          {self._btn_row("Save", "ciojobpop", add_item=True)}
          {self._job_info_popup('ciojobpop')}
        </form>
        <div class="row">
          <div><h2>Out Now — Ready to Check in</h2>{out_rows or "<p class='hint'>Nothing out.</p>"}{out_more}</div>
          <div><h2>Reserved — Ready to Check Out</h2>{in_rows or "<p class='hint'>Nothing reserved.</p>"}{in_more}</div>
        </div>
        <script>document.querySelectorAll('.cio-pick').forEach(function(a){{a.addEventListener('click',function(e){{e.preventDefault();document.getElementById('cio_tid').value=a.dataset.tid;document.getElementById('cio_pick').value=a.dataset.label;document.getElementById('cio_dir').value=a.dataset.dir;document.getElementById('cioform').scrollIntoView({{behavior:'smooth',block:'start'}});}});}});</script>
        """

    def _pick_opts(self, rows, value_key, label_key, first_label, selected=""):
        """Select options whose first row names the field in the box."""
        out = [f'<option value="">{html.escape(first_label)}</option>']
        for r in rows:
            sel = " selected" if str(r[value_key]) == str(selected) else ""
            out.append(
                f'<option value="{html.escape(str(r[value_key]), quote=True)}"{sel}>'
                f'{html.escape(str(r[label_key]))}</option>')
        return "\n".join(out)

    def _recent_tickets(self, con, limit=5):
        rows = con.execute(
            """SELECT t.ticket_id, t.status, t.on_rent, c.account_name, a.unit_no
               FROM tickets t
               JOIN customers c ON c.customer_id = t.customer_id
               JOIN assets a ON a.asset_id = t.asset_id
               ORDER BY t.rowid DESC LIMIT ?""", (limit,)).fetchall()
        if not rows:
            return "<p class='mute'>No tickets yet.</p>"
        return "".join(
            f"<div class='todo'><a href='/ticket/{html.escape(r['ticket_id'], quote=True)}'>"
            f"{html.escape(r['ticket_id'])}</a> — {html.escape(r['unit_no'])} · "
            f"{html.escape(r['account_name'])} "
            f"<span class='mute'>{html.escape(r['status'])} · {html.escape(str(r['on_rent'])[:10])}</span></div>"
            for r in rows)

    def _new_ticket_delivery(self, con, q=None):
        cust = con.execute("SELECT customer_id, account_name FROM customers ORDER BY account_name").fetchall()
        # only assets not blocking
        assets = con.execute(
            """SELECT a.asset_id, a.unit_no || ' · ' || COALESCE(a.description,'') AS label,
                      COALESCE(a.rate_unit,'Day') AS rate_unit, COALESCE(a.rate_value,0) AS rate_value
               FROM assets a WHERE a.active=1
               AND a.asset_id NOT IN (
                 SELECT asset_id FROM tickets WHERE status IN ('Reserved','Dispatched','On Rent','Standby')
               ) ORDER BY a.unit_no"""
        ).fetchall()
        unit_rates = {a["asset_id"]: [a["rate_unit"], float(a["rate_value"] or 0)] for a in assets}
        cust_opts, _ = combo_opts(cust, "customer_id", "account_name", "")
        unit_opts, _ = combo_opts(assets, "asset_id", "label", "")
        today = date.today().isoformat()
        if not assets:
            return _empty_action('No rentable equipment yet', 'Add your first equipment unit before creating a rental.', '/unit/new', 'Add equipment')
        haul_combo = combo_field(
            "f_haul", "haul_text",
            [(h, engine.HAUL_LABELS[h], h) for h in engine.HAUL_BY],
            value=engine.HAUL_LABELS["we"], label="Who hauls it",
            placeholder="We deliver, customer, or type a hauler…")
        deliver_combo = combo_field(
            "f_deliver", "deliver_text",
            [(d, engine.DELIVER_LABELS[d], d) for d in ("job_site", "our_yard", "customer_yard", "dock")],
            value=engine.DELIVER_LABELS["job_site"], label="Deliver to",
            placeholder="Job site, yard, or type…")
        # Pre-generate ticket ID (Jason 2026-10-07)
        _tid = con.execute("SELECT COALESCE(MAX(CAST(SUBSTR(ticket_id, 3) AS INTEGER)), 0) + 1 FROM tickets WHERE ticket_id LIKE 'T-%'").fetchone()[0]
        ticket_no = f"T-{_tid}"
        return f"""
        <div id="formerr" role="alert"></div>
        <form method=post action="/ticket/new" id="ticketform" enctype="multipart/form-data">
          <input type=hidden name=ticket_id value="{ticket_no}">
          <p id="ticketsum" class="hint" style="font-size:14px;color:var(--frame);
             background:#eef3fa;border-radius:6px;padding:8px 12px"></p>
          <fieldset style="padding:8px">
          <div class="row4">
            <div><label>Ticket #</label><input value="{ticket_no}" disabled class=w-xs></div>
            <div>{combo_field("f_customer", "customer_text", cust_opts, value="", label="Customer", required=True, placeholder="Type to search customers…")}
            <input type=hidden id="f_customer_id" name=customer_id value=""></div>
            <div><label>Reference Ticket</label><input name=ref_ticket class=w-sm placeholder="Optional"></div>
            <div><label>Date</label><input type=date name=ticket_date value="{today}" class=w-sm></div>
          </div>
          <div class="row4 lineitem-row">
            <div>{combo_field("f_unit", "unit_text", unit_opts, value="", label="Item", required=True, placeholder="Type to search units…")}
            <input type=hidden id="f_unit_id" name=asset_id value="">
            <input type=hidden id="f_unit_free" name=item_text value=""></div>
            <div><label>Description</label><input name=item_desc placeholder="Details"></div>
            <div><label>Qty</label><div style="display:flex;align-items:center;gap:6px"><input name=qty type=number step="any" value=1 class=w-xs style="flex:1;min-width:0"><span class="ratetype-tag mute" style="font-size:12px;white-space:nowrap"></span></div></div>
            <div><label>Rate $</label><input id="f_rateval" name=rate_value type=number step=0.01 placeholder="unit default" data-label="Rate $" class=w-sm>
            <input type=hidden name=rate_type value=""></div>
          </div>
          <div class="row4">
            <div><label>On-Rent</label><input type=date name=on_rent value="{today}" required data-label="On-rent date" class=w-sm></div>
            <div><label>Off-Rent Est</label><input type=date name=off_rent_est class=w-sm></div>
            <div>{haul_combo}</div>
            <div>{deliver_combo}</div>
          </div>
          <div class="row4">
            <div style="grid-column:span 3"><label>Notes</label><input name=location_note data-label="Notes"></div>
            <div><label>Upload</label><input type=file name=ticket_upload></div>
          </div>
          {self._btn_row("Save", "jobpop", add_item=True)}
          </fieldset>
                    {self._job_info_popup('jobpop')}
        </form>
        <h2>Recent Tickets</h2>
        {self._recent_tickets(con)}
        <script>
        (function(){{
          var UR = {json.dumps(unit_rates)};
          var form = document.getElementById('ticketform');
          // Combo sync (local copy of COMBO_JS logic): resolve the visible
          // text to its data-id now, so handlers don't race the footer script.
          function syncCombo(fid){{
            var inp = document.getElementById(fid);
            var dl = inp && document.getElementById(inp.getAttribute('list'));
            if (!dl) return '';
            var t = inp.value.trim(), id = '';
            Array.prototype.forEach.call(dl.options, function(o){{
              if (o.value.trim() === t) id = o.getAttribute('data-id') || '';
            }});
            var hid = document.getElementById(fid + '_id');
            if (hid) hid.value = id;
            return id;
          }}
          function ctxt(fid){{
            syncCombo(fid);
            var hid = document.getElementById(fid + '_id');
            return (hid && hid.value) ? document.getElementById(fid).value : '';
          }}
          // Line-item row: resolve the Item combo, sync the free-text field,
          // and return the picked unit's id ('' when hand-typed).
          function rowUnitId(row){{
            var inp = row.querySelector('input[data-combo]');
            if (!inp) return '';
            var dl = document.getElementById(inp.getAttribute('list'));
            var t = inp.value.trim(), id = '';
            if (dl) Array.prototype.forEach.call(dl.options, function(o){{
              if (o.value.trim() === t) id = o.getAttribute('data-id') || '';
            }});
            var hid = row.querySelector('input[name=asset_id]');
            var hfree = row.querySelector('input[name=item_text]');
            if (hid) hid.value = id;
            if (hfree) hfree.value = id ? '' : t;
            return id;
          }}
          // Rate sync for one line-item row: the unit's rate type shows as a
          // tag behind Qty, its rate value fills Rate $, and the hidden
          // rate_type carries the unit's rate unit to the POST.
          function syncRowRate(row, fromUnit){{
            var r = UR[rowUnitId(row)];
            var tag = row.querySelector('.ratetype-tag');
            var rv = row.querySelector('input[name=rate_value]');
            var rt = row.querySelector('input[name=rate_type]');
            if (tag) tag.textContent = r ? r[0] : '';
            if (rt && r) rt.value = r[0];
            if (fromUnit && r && rv) rv.value = r[1].toFixed(2);
          }}
          // Draft: keep what was typed if the page is left and returned to.
          var DK = 'draft:/ticket/new';
          function saveDraft(){{
            var d = {{}};
            Array.prototype.forEach.call(form.elements, function(el){{
              if (!el.name || el.type === 'submit' || el.type === 'button') return;
              d[el.name] = el.type === 'checkbox' ? (el.checked ? '1' : '') : el.value;
            }});
            try {{ localStorage.setItem(DK, JSON.stringify(d)); }} catch(e){{}}
          }}
          function loadDraft(){{
            var d = null;
            try {{ d = JSON.parse(localStorage.getItem(DK) || 'null'); }} catch(e){{}}
            if (!d) return false;
            Array.prototype.forEach.call(form.elements, function(el){{
              if (!el.name || !(el.name in d)) return;
              if (el.type === 'checkbox') el.checked = !!d[el.name];
              else el.value = d[el.name];
            }});
            return true;
          }}
          function upd(){{
            var sum = document.getElementById('ticketsum');
            var row = document.querySelector('.lineitem-row');
            var uinp = row && row.querySelector('input[data-combo]');
            var c = ctxt('f_customer'), u = uinp ? uinp.value.trim() : '';
            sum.textContent = (c && u) ? ('Ticket: ' + c + ' → ' + u) : '';
          }}
          var fCust = document.getElementById('f_customer');
          if (fCust) {{
            fCust.addEventListener('change', upd);
            fCust.addEventListener('input', upd);
          }}
          var firstRow = document.querySelector('.lineitem-row');
          var fUnit = document.getElementById('f_unit');
          if (fUnit) {{
            fUnit.addEventListener('change', function(){{ syncRowRate(firstRow, true); upd(); }});
            fUnit.addEventListener('input', function(){{ upd(); }});
          }}
          // Add item: clone the line-item row, clear it, wire its combo and
          // rate tag. Cloned rows drop their ids and required flags so they
          // never collide with the first row or block a save when empty.
          function addItemRow(){{
            var proto = document.querySelector('.lineitem-row');
            if (!proto) return;
            var clone = proto.cloneNode(true);
            clone.querySelectorAll('[id]').forEach(function(el){{ el.removeAttribute('id'); }});
            clone.querySelectorAll('input').forEach(function(el){{
              if (el.type === 'hidden') el.value = '';
              else if (el.name === 'qty') el.value = '1';
              else el.value = '';
              el.removeAttribute('required');
            }});
            var tag = clone.querySelector('.ratetype-tag');
            if (tag) tag.textContent = '';
            var inp = clone.querySelector('input[data-combo]');
            if (inp) {{
              inp.addEventListener('input', function(){{ syncRowRate(clone, true); upd(); saveDraft(); }});
              inp.addEventListener('change', function(){{ syncRowRate(clone, true); upd(); saveDraft(); }});
            }}
            proto.parentNode.insertBefore(clone, proto.nextSibling);
            if (inp) inp.focus();
          }}
          // _btn_row's Add item button carries no id — match it by label.
          Array.prototype.forEach.call(form.querySelectorAll('button[type=button]'), function(b){{
            if (b.textContent.trim().toLowerCase() === 'add item') b.addEventListener('click', addItemRow);
          }});
          // Name the missing field instead of a bare browser bubble.
          form.setAttribute('novalidate', '');
          var msg = document.getElementById('formerr');
          form.addEventListener('submit', function(e){{
            // Customer and Item must resolve to real records.
            var bad = null, badLab = null;
            if (!ctxt('f_customer')) {{
              bad = document.getElementById('f_customer');
              badLab = 'Customer — pick one from the list';
            }} else if (!syncCombo('f_unit')) {{
              bad = document.getElementById('f_unit');
              badLab = 'Item — pick a unit from the list';
            }}
            if (bad) {{
              e.preventDefault();
              bad.classList.add('field-err');
              msg.textContent = 'Fill out: ' + badLab;
              msg.style.display = 'block';
              bad.scrollIntoView({{block: 'center'}});
              try {{ bad.focus({{preventScroll: true}}); }} catch(x) {{ bad.focus(); }}
              return;
            }}
            Array.prototype.forEach.call(form.elements, function(el){{
              if (bad || !el.willValidate) return;
              if (!el.checkValidity()) bad = el;
            }});
            if (bad) {{
              e.preventDefault();
              var lab = bad.getAttribute('data-label') || bad.name || 'a field';
              bad.classList.add('field-err');
              msg.textContent = 'Fill out: ' + lab;
              msg.style.display = 'block';
              bad.scrollIntoView({{block: 'center'}});
              try {{ bad.focus({{preventScroll: true}}); }} catch(x) {{ bad.focus(); }}
            }} else {{
              try {{ localStorage.removeItem(DK); }} catch(x){{}}
            }}
          }});
          form.addEventListener('input', function(e){{
            if (e.target && e.target.classList) e.target.classList.remove('field-err');
            saveDraft();
          }});
          form.addEventListener('change', saveDraft);
          loadDraft(); upd();
          document.querySelectorAll('.lineitem-row').forEach(function(r){{ syncRowRate(r, true); }});
        }})();
        </script>
        """

    def _condition_forms(self, con, t, locked):
        tid = t["ticket_id"]
        conds = list(engine.COND_RANK.keys())
        def sel(cur):
            return "".join(
                f"<option{' selected' if cur==c else ''}>{html.escape(c)}</option>" for c in conds
            )
        out_c = self._g(t, "out_condition")
        in_c = self._g(t, "in_condition")
        ro = "disabled" if locked else ""
        btn = "" if locked else "<p><button>Save Check-Out</button></p>"
        btn2 = "" if locked else "<p><button>Save Check-In</button></p>"
        return f"""
        <h2 style="font-size:16px;color:var(--frame)">Check-Out / Check-In</h2>
        {hint}
        <div class="row">
          <form method=post action="/ticket/{html.escape(tid)}/condition" enctype="multipart/form-data">
            <input type=hidden name=side value=out>
            <p class="hint">Out — required before Dispatched or On Rent.</p>
            {self.clerk_field(con)}
            <label>Out Condition</label><select name=condition required {ro}>{sel(out_c)}</select>
            <label>Meter / Hours / Fuel</label><input name=meter value="{html.escape(str(self._g(t,'out_meter')))}" {ro}>
            <label>Hour Meter</label><input name=hours type=number step=0.1 min=0 value="{html.escape(str(self._g(t,'hours_start')))}" {ro}>
            <p class="hint">Hour meter feeds hour-rate billing. Blank = no hour reading.</p>
            {self._photo_field(tid, "out", self._g(t, "out_photo"), locked)}
            <label>Note</label><input name=note value="{html.escape(str(self._g(t,'out_note')))}" {ro}>
            <p class="hint">{html.escape(str(self._g(t,'out_by')))} {html.escape(str(self._g(t,'out_at')))}</p>
            {btn}
          </form>
          <form method=post action="/ticket/{html.escape(tid)}/condition" enctype="multipart/form-data">
            <input type=hidden name=side value=in>
            <p class="hint">In — required before Off Rent.</p>
            {self.clerk_field(con)}
            <label>In Condition</label><select name=condition required {ro}>{sel(in_c)}</select>
            <label>Meter / Hours / Fuel</label><input name=meter value="{html.escape(str(self._g(t,'in_meter')))}" {ro}>
            <label>Hour Meter</label><input name=hours type=number step=0.1 min=0 value="{html.escape(str(self._g(t,'hours_end')))}" {ro}>
            <p class="hint">Check-in hour meter updates the unit's meter and closes hour billing.</p>
            {self._photo_field(tid, "in", self._g(t, "in_photo"), locked)}
            <label>Note</label><input name=note value="{html.escape(str(self._g(t,'in_note')))}" {ro}>
            <p class="hint">{html.escape(str(self._g(t,'in_by')))} {html.escape(str(self._g(t,'in_at')))}</p>
            {btn2}
          </form>
        </div>
        """

    def view_ticket(self, con, tid):
        t = con.execute(
            """SELECT t.*, c.account_name, a.unit_no, a.description
               FROM tickets t JOIN customers c ON c.customer_id=t.customer_id
               JOIN assets a ON a.asset_id=t.asset_id WHERE t.ticket_id=?""",
            (tid,),
        ).fetchone()
        if not t:
            return '<div class="err">No ticket.</div>'
        m = engine.ticket_money(con, tid)
        nxt = engine.ALLOWED_NEXT.get(t["status"], ())
        buttons = "".join(
            f'<button name=status value="{html.escape(s)}">{html.escape(s)}</button> '
            for s in nxt
        )
        fit_cls = "pass" if m.get("fit") == "PASS" else "fail"
        locked = t["status"] in ("Billed", "Closed", "Void") or bool(t["invoice_no"])
        quote_panel = quote_expiry_panel(con, self._g(t, "quote_no"))
        haul = engine.clean_haul_by(self._g(t, "haul_by"))
        dest = engine.clean_deliver_to(self._g(t, "deliver_to"))
        tf = float(t["transport_fee"] or 0) if "transport_fee" in t.keys() else 0
        haul_opts = "".join(
            f"<option value='{h}'{' selected' if haul == h else ''}>"
            f"{html.escape(engine.HAUL_LABELS[h])}</option>" for h in engine.HAUL_BY)
        del_opts = "".join(
            f"<option value='{d}'{' selected' if dest == d else ''}>"
            f"{html.escape(engine.DELIVER_LABELS[d])}</option>" for d in engine.DELIVER_TO)
        tax_locs = con.execute(
            "SELECT loc_id, COALESCE(display_name, loc_id) || ' · ' || printf('%.2f%%', tax_rate*100) AS label FROM jurisdictions ORDER BY display_name"
        ).fetchall()
        current_tax_loc = self._g(t, "tax_loc_id") or ""
        tax_loc_opts, tax_loc_cur = combo_opts(tax_locs, "loc_id", "label", current_tax_loc)
        status_help = {
            "Quoted": "Next: Reserve the unit when the customer commits.",
            "Reserved": "Next: record check-out, then Dispatch when the unit leaves the yard.",
            "Dispatched": "Next: record check-out if needed, then mark On Rent when possession starts.",
            "On Rent": "Next: record check-in, then Off Rent when the rental clock stops.",
            "Standby": "Next: return to On Rent or record check-in and Off Rent.",
            "Off Rent": "Next: Ready to Bill, then create the invoice.",
            "Ready to Bill": "Next: create the invoice. FleetSheet will mark the ticket Billed automatically.",
            "Billed": "Next: Close the ticket after the office has finished its work.",
            "Closed": "This rental is complete.",
            "Void": "This ticket is void and no longer moves through the rental workflow.",
        }.get(t["status"], "")
        off_label = "Off-rent date" if t["status"] in ("On Rent", "Standby", "Dispatched") else "Off-rent date (if needed)"
        status_form = f"""
        <form method=post action="/ticket/{html.escape(tid)}/status">
          {self.clerk_field(con)}
          <p><b>Now:</b> {html.escape(t["status"])}</p>
          {f'<p class="nextstep"><b>Next Step:</b> {html.escape(status_help)}</p>' if status_help else ''}
          <label>{html.escape(off_label)}</label>
          <input type=date name=off_rent value="{html.escape(t['off_rent'] or '')}">
          <p>{buttons or 'No further moves.'}</p>
        </form>
        """
        return f"""
        <h1>{html.escape(tid)} · {html.escape(t['account_name'])}</h1>
          <h2 style="font-size:16px;color:var(--frame)">Transport and Possession</h2>
          <p class="hint">{html.escape(m.get("possession_label") or "")}. {html.escape(m.get("tax_note") or "")}
          Tax: {html.escape(m.get("tax_name") or "")} {m.get("tax_rate", 0):.4f}{" · exempt" if m.get("tax_exempt") else ""}.</p>
          <div class="row">
            <div><label>Who Hauls It</label><select name=haul_by {"disabled" if locked else ""}>{haul_opts}</select></div>
            <div><label>Deliver to</label><select name=deliver_to {"disabled" if locked else ""}>{del_opts}</select></div>
            <div>{"<label>Tax Jurisdiction</label><input value=\"" + html.escape(tax_loc_cur or "—", quote=True) + "\" disabled>" if locked else
              combo_field("t_taxloc", "tax_loc_text", tax_loc_opts, value=tax_loc_cur, label="Tax jurisdiction", placeholder="Your call — pick or leave blank") +
              f"<input type=hidden id=\"t_taxloc_id\" name=tax_loc_id value=\"{html.escape(current_tax_loc, quote=True)}\">"}</div>
          </div>
          <p class="hint">{html.escape(engine.haul_consequence(haul, dest))}</p>
          <div class="row">
            <div><label>Transportation Fee $</label><input name=transport_fee type=number step=0.01 class=w-sm value="{tf:.2f}" {"readonly" if locked else ""}></div>
          </div>
          <div class="row">
            <div><label>Mob $</label><input name=mob type=number step=0.01 class=w-sm value="{float(t['mob'] or 0):.2f}" {"readonly" if locked else ""}></div>
            <div><label>Demob $</label><input name=demob type=number step=0.01 class=w-sm value="{float(t['demob'] or 0):.2f}" {"readonly" if locked else ""}></div>
          </div>
          {"<p class='hint'>Locked on the invoice. Change it on the ticket before you bill.</p>" if locked else "<p><button>Save Transport</button></p>"}
        </form>
        """
        return f"""
        <h1>{html.escape(tid)} · {html.escape(t['account_name'])}</h1>
        {task_nudge(con, f"/ticket/{tid}")}
        <p>{html.escape(t['unit_no'])} — {html.escape(t['description'] or '')}<br>
        Site {html.escape(t['site_id'])} · {html.escape(t['rate_type'])} ·
        <span class="{fit_cls}">{html.escape(m.get('fit',''))}</span></p>
        {quote_panel}
        <div class="cards">
          <div class="card"><span>Days</span><b>{m['days']}</b></div>
          {f"<div class='card'><span>Hours</span><b>{m['hours']:g}</b></div>" if m.get('hours', 0) > 0 else ""}
          <div class="card"><span>Rate</span><b>${m['rate']:,.2f}</b></div>
          <div class="card"><span>Rental</span><b>${m['rental']:,.2f}</b></div>
          <div class="card"><span>Transport</span><b>${m.get('transport', 0):,.2f}</b></div>
          <div class="card"><span>Tax</span><b>${m['tax']:,.2f}</b></div>
          <div class="card"><span>Total</span><b>${m['total']:,.2f}</b></div>
        </div>
        {transport_form}
        {self._condition_forms(con, t, locked)}
        {self._paper_warning(t, m)}
{status_form}
        <p>
          <a class="btn" href="/print/work/{html.escape(tid)}">Work Ticket</a>
          <a class="btn" href="/print/delivery/{html.escape(tid)}">Delivery Ticket</a>
        </p>
        """

    # Open ticket statuses — the Fit column's quiet signal set.
    _OPEN_TICKET = ('Quoted', 'Reserved', 'Dispatched', 'On Rent', 'Standby')
    # Statuses where paper matters: the unit is about to ship (or shipping).
    # Receiving checks the paper once, at the gate.
    _SHIP_TICKET = ('Reserved', 'Dispatched')

    def _ticket_fit_cell(self, con, r):
        """Fit signal for a ticket row: FAIL badge when failing, quiet pass
        for open tickets, blank where fit is meaningless. ticket_money is
        only computed for open tickets (perf)."""
        if r["status"] not in self._OPEN_TICKET:
            return "<td></td>"
        fit = engine.ticket_money(con, r["ticket_id"]).get("fit", "PASS")
        if fit != "PASS":
            return "<td class='fail'>FAIL</td>"
        return "<td class='pass'>pass</td>"

    def _paper_warning(self, t, m):
        """Non-blocking paper heads-up on the ticket page: paper only matters
        at shipping, so this shows only on Reserved/Dispatched tickets whose
        unit fails the job's fit. FleetSheet never says 'you can't' — the
        dispatch buttons stay live underneath."""
        if t["status"] not in self._SHIP_TICKET or m.get("fit") == "PASS":
            return ""
        reason = engine.fit_reason(m.get("fit"), m.get("cert_expiry"))
        return (
            f"<p class='err'><b>Paper:</b> {html.escape(reason)} — "
            f"the site may reject this unit at receiving. "
            f"This is a heads-up, not a block: dispatch anyway if the real world says so.</p>"
        )

    def view_tickets(self, con, flag=None):
        """Ticket list. flag=fit shows exactly the shipping set — Reserved /
        Dispatched tickets failing fit, the only moment paper earns a tap.
        flag=nooff shows exactly the on-rent tickets with no off-rent date.
        Any other flag value falls back to the unfiltered list."""
        rows = con.execute(
            """SELECT t.ticket_id, t.status, t.on_rent, t.off_rent, c.account_name, a.unit_no
               FROM tickets t JOIN customers c ON c.customer_id=t.customer_id
               JOIN assets a ON a.asset_id=t.asset_id
               ORDER BY t.on_rent DESC"""
        ).fetchall()
        head = ""
        if flag == "fit":
            rows = [r for r in rows
                    if r["status"] in self._SHIP_TICKET
                    and engine.ticket_money(con, r["ticket_id"]).get("fit", "PASS") != "PASS"]
            head = (f"<h1>{len(rows)} unit{'s' if len(rows) != 1 else ''} Shipping With Bad Paper</h1>"
                    f"<p class='hint'><a href='/tickets'>All Tickets</a></p>")
        elif flag == "nooff":
            rows = [r for r in rows
                    if r["status"] in ('On Rent', 'Standby') and not (r["off_rent"] or "")]
            head = (f"<h1>{len(rows)} on Rent With No Off-Rent Date</h1>"
                    f"<p class='hint'><a href='/tickets'>All Tickets</a></p>")
        if not head:
            head = ("<h1>Tickets</h1><p class='hint'>Every rental ticket and its status. "
                    "Open one to change status or print.</p>")
        def _off_cell(r):
            if flag == "nooff":
                # Inline date entry: no trip to the ticket page just to type a
                # date. Defaults to today (2026-10-08): the day it came off
                # rent is the honest prefill — edit it if the iron came back
                # earlier.
                tid = html.escape(r['ticket_id'], quote=True)
                return (f"<td><form method='post' action='/ticket/{tid}/offrent' "
                        f"style='display:inline;white-space:nowrap'>"
                        f"<input type='date' name='off_rent' value='{date.today().isoformat()}' required> "
                        f"<button class='vbtn'>Set</button></form></td>")
            return f"<td>{html.escape(str(r['off_rent'] or ''))}</td>"
        body = "".join(
            f"<tr><td><a href='/ticket/{html.escape(r['ticket_id'])}'>{html.escape(r['ticket_id'])}</a></td>"
            f"<td>{html.escape(r['account_name'])}</td><td>{html.escape(r['unit_no'])}</td>"
            f"<td>{html.escape(r['status'])}</td><td>{html.escape(str(r['on_rent']))}</td>"
            f"{_off_cell(r)}"
            f"{self._ticket_fit_cell(con, r)}</tr>"
            for r in rows
        )
        return tabs_reports("/tickets") + head + f"""
        <table class="audit"><tr><th>ID</th><th>Customer</th><th>Unit</th><th>Status</th><th>On</th><th>Off</th><th>Fit</th></tr>{body}</table>
        """ + AUDIT_TABLE_JS + self._done_box(con, "/tickets")

    def _asset_lists(self, con):
        """Shared by the Assets page and the dashboard card: needs-paper + idle."""
        watch = engine.fleet_compliance_watch(con)
        # Cert identity (Q5): expired certs come from the cert records'
        # operative expiry, not the bare legacy column.
        _today = date.today().isoformat()
        expired = []
        for r in con.execute(
                "SELECT asset_id, unit_no FROM assets WHERE active=1 ORDER BY unit_no"):
            _exp = engine.operative_cert_expiry(con, r["asset_id"])
            if _exp and _exp < _today:
                expired.append({"asset_id": r["asset_id"], "unit_no": r["unit_no"],
                                "cert_expire": _exp})
        expired.sort(key=lambda r: r["cert_expire"])
        idle = con.execute(
            """SELECT a.asset_id, a.unit_no, COALESCE(a.description,'') AS description,
                      COALESCE(a.rate_unit,'Day') AS rate_unit,
                      COALESCE(a.rate_value, 0) AS rate_value FROM assets a
               WHERE a.active = 1 AND NOT EXISTS
               (SELECT 1 FROM tickets t WHERE t.asset_id = a.asset_id
                AND t.status NOT IN ('Billed','Closed','Void'))
               ORDER BY a.unit_no"""
        ).fetchall()
        idle_day = sum(engine.day_equivalent(r["rate_unit"], r["rate_value"]) for r in idle)
        idle_other = sum(1 for r in idle if (r["rate_unit"] or "Day") in ("Hour", "Special"))
        paper = ([{"t": f"EXPIRED CERT — {r['unit_no']} (expired {str(r['cert_expire'])[:10]})",
                   "h": f"/ucompliance/{r['asset_id']}"} for r in expired] +
                 [{"t": f"{w['status'].upper()} — {w['unit_no']}: {w['item']}"
                       + (f" → call {w['performer_name']}" if w['performer_name'] else ""),
                   "h": f"/unit/{w['asset_id']}"} for w in watch])
        return paper, idle, idle_day, idle_other

    def view_assets(self, con):
        """The fleet: what needs attention up top, what's moving below."""
        return (self._assets_ticker(con) +
                '<div style="display:flex;justify-content:space-between;align-items:center;margin:8px 0">'
                '<h2 style="margin:0">Latest Changes</h2>'
                '<a class="btn" href="/unit/new">+ New Unit</a></div>' +
                self._assets_latest_changes(con) +
                '<div style="text-align:right;margin:8px 0 0">'
                '<button type="button" class="vbtn" data-audit="/assets/all" data-title="All assets — audit">View All Assets</button>'
                '</div>' +
                self._done_box(con, "/assets"))

    def _assets_ticker(self, con):
        """Prioritized problems in the same gold strip as Today: conflicts
        and expired paper only when a job is coming soon; unacknowledged
        POs; accepted quotes; expected off-rent returns. Idle iron with no
        upcoming job gets no tap. Every row carries snooze/sleep."""
        items = []  # (key, text_html, href_or_None, extra_html)
        for text, href in self._ticker_asset_conflicts(con):
            tid = href.rsplit("/", 1)[-1]
            items.append((f"aconf:{tid}", text, href, ""))
        for text, href, extra, po_no in self._ticker_unacked_pos(con):
            items.append((f"poack:{po_no}", text, href, extra))
        for text, href in self._ticker_accepted_quotes(con):
            qno = href.rsplit("/", 1)[-1]
            items.append((f"aq:{qno}", text, href, ""))
        for text, href in self._ticker_offrent(con):
            tid = href.rsplit("/", 1)[-1]
            items.append((f"aoff:{tid}", text, href, ""))
        for text, href in self._ticker_sole_unit(con):
            aid = href.rsplit("/", 1)[-1]
            items.append((f"asole:{aid}", text, href, ""))
        items = [it for it in items if not engine.is_acked(con, it[0])]
        if not items:
            return ""
        rows = ""
        for key, text, href, extra in items[:5]:
            link = (f"<a class='go' href='{html.escape(href, quote=True)}'>Handle Now</a>"
                    if href else "")
            rows += (
                f"<div class='tapbox lv0'><span class='msg'>{text}</span>"
                f"{link}{extra}"
                f"{_ack_forms(key, '/assets')}"
                f"</div>")
        if len(items) > 5:
            rows += f"<p class='mute'>+ {len(items) - 5} more</p>"
        return f"<div class='news squeeze'>{rows}</div>"


    def _ticker_asset_conflicts(self, con):
        """Expired cert/paper on a unit with a job starting within 14 days."""
        out = []
        today = date.today()
        soon = (today + timedelta(days=14)).isoformat()
        for r in con.execute(
                """SELECT DISTINCT a.asset_id, a.unit_no, t.ticket_id, t.on_rent, c.account_name
                   FROM assets a
                   JOIN tickets t ON t.asset_id = a.asset_id
                   JOIN customers c ON c.customer_id = t.customer_id
                   WHERE a.active = 1
                   AND t.status IN ('Reserved','Dispatched')
                   AND t.on_rent <= ?""", (soon,)):
            exp = engine.operative_cert_expiry(con, r["asset_id"])
            if exp and exp < today.isoformat():
                out.append((
                    f"EXPIRED CERT — {html.escape(r['unit_no'])} ships {html.escape(str(r['on_rent'])[:10])} "
                    f"to {html.escape(r['account_name'])} <span class='mute'>(expired {exp[:10]})</span>",
                    f"/ticket/{r['ticket_id']}"))
        return out

    def _ticker_unacked_pos(self, con):
        """Issued POs waiting for acknowledgement."""
        out = []
        for p in con.execute(
                """SELECT po_no, customer_id, asset_id, expire FROM purchase_orders
                   WHERE ack_at IS NULL ORDER BY rowid DESC LIMIT 10"""):
            unit = ""
            href = None
            if p["asset_id"]:
                u = con.execute("SELECT unit_no, asset_id FROM assets WHERE asset_id=?",
                                (p["asset_id"],)).fetchone()
                if u:
                    unit = f" — {u['unit_no']}"
                    href = f"/unit/{u['asset_id']}"
            # Is the unit in-yard (reserved) or on a job (paperwork only)?
            state = ""
            if p["asset_id"]:
                busy = con.execute(
                    """SELECT ticket_id FROM tickets WHERE asset_id=?
                       AND status IN ('Dispatched','On Rent','Standby')""",
                    (p["asset_id"],)).fetchone()
                state = " <span class='mute'>(on job — paperwork change)</span>" if busy else " <span class='mute'>(reserved)</span>"
            # po_no already carries the "PO-" prefix — don't prepend "PO ".
            # The PO number itself is the link; the Acknowledge button stays.
            po_txt = html.escape(p['po_no'])
            po_link = (f"<a href='{html.escape(href, quote=True)}'>{po_txt}</a>"
                       if href else po_txt)
            out.append((
                f"{po_link}{html.escape(unit)} issued{state} ",
                href,
                # The Ack form lives OUTSIDE any anchor: a <form> nested in
                # an <a> is invalid HTML and renders as stacked-card garbage
                # in some browsers/zooms (seen 2026-10-01).
                f"<form method='post' action='/po/ack' class='ackf'>"
                f"<input type=hidden name=customer_id value='{html.escape(p['customer_id'], quote=True)}'>"
                f"<input type=hidden name=po_no value='{html.escape(p['po_no'], quote=True)}'>"
                f"<button class='vbtn' title='Acknowledge — marks this PO as seen. The unit stays reserved.'>Acknowledge</button></form>",
                p["po_no"]))
        return out

    def _ticker_accepted_quotes(self, con):
        """Accepted quote: recognition tap, with urgency as the date nears."""
        out = []
        today = date.today()
        for q in con.execute(
                """SELECT q.quote_no, q.customer_id, q.valid_until, c.account_name
                   FROM quotes q JOIN customers c ON c.customer_id=q.customer_id
                   WHERE q.status='Accepted' ORDER BY q.valid_until"""):
            vu = (q["valid_until"] or "").strip()[:10]
            try:
                delta = (date.fromisoformat(vu) - today).days if vu else None
            except ValueError:
                delta = None
            if delta is None:
                when = ""
            elif delta < 0:
                when = f" <span class='mute'>(validity lapsed {vu[5:]})</span>"
            elif delta <= 7:
                when = f" <span class='mute'>({delta}d left)</span>"
            else:
                when = f" <span class='mute'>(valid to {vu[5:]})</span>"
            out.append((
                f"Quote {html.escape(q['quote_no'])} accepted — {html.escape(q['account_name'])}{when}",
                f"/quote/{q['quote_no']}"))
        return out

    def _ticker_offrent(self, con):
        """Expected off-rent returns within 7 days."""
        out = []
        today = date.today()
        soon = (today + timedelta(days=7)).isoformat()
        for r in con.execute(
                """SELECT t.ticket_id, t.off_rent, a.unit_no, c.account_name
                   FROM tickets t
                   JOIN assets a ON a.asset_id=t.asset_id
                   JOIN customers c ON c.customer_id=t.customer_id
                   WHERE t.status='On Rent' AND t.off_rent IS NOT NULL
                   AND t.off_rent <= ? ORDER BY t.off_rent""", (soon,)):
            out.append((
                f"{html.escape(r['unit_no'])} due back {html.escape(str(r['off_rent'])[:10])} "
                f"<span class='mute'>({html.escape(r['account_name'])})</span>",
                f"/ticket/{r['ticket_id']}"))
        return out

    def _ticker_sole_unit(self, con):
        """Sole available unit of its kind with an issue gets a nudge."""
        out = []
        today = date.today().isoformat()
        for cat in con.execute(
                """SELECT category, COUNT(*) AS n FROM assets
                   WHERE active=1 AND category IS NOT NULL AND TRIM(category)!=''
                   GROUP BY category HAVING n=1"""):
            u = con.execute(
                """SELECT a.asset_id, a.unit_no FROM assets a
                   WHERE a.active=1 AND a.category=?
                   AND NOT EXISTS (SELECT 1 FROM tickets t WHERE t.asset_id=a.asset_id
                       AND t.status NOT IN ('Billed','Closed','Void'))""",
                (cat["category"],)).fetchone()
            if not u:
                continue
            exp = engine.operative_cert_expiry(con, u["asset_id"])
            if exp and exp < today:
                out.append((
                    f"{html.escape(u['unit_no'])} unfit & only available "
                    f"<span class='mute'>(expired {exp[:10]})</span>",
                    f"/unit/{u['asset_id']}"))
        return out

    def _unit_state_badge(self, con, asset_id):
        """Quick cert/fit-state for a unit row."""
        exp = engine.operative_cert_expiry(con, asset_id)
        today = date.today().isoformat()
        if exp and exp < today:
            return f"<span class='fail'>cert expired {exp[:10]}</span>"
        if exp:
            return f"<span class='mute'>cert {exp[:10]}</span>"
        return "<span class='mute'>no cert</span>"

    def _assets_latest_changes(self, con):
        """In/out/reserved movements, newest first, with cert/fit state."""
        moves = []
        for r in con.execute(
                """SELECT t.ticket_id, t.status, t.created_at, a.asset_id, a.unit_no, c.account_name
                   FROM tickets t
                   JOIN assets a ON a.asset_id=t.asset_id
                   JOIN customers c ON c.customer_id=t.customer_id
                   WHERE t.status='Reserved' ORDER BY t.created_at DESC LIMIT 10"""):
            moves.append((r["created_at"], "Reserved",
                          f"{r['unit_no']} reserved — {r['account_name']}",
                          f"/ticket/{r['ticket_id']}", r["asset_id"]))
        for r in con.execute(
                """SELECT t.ticket_id, t.out_at, a.asset_id, a.unit_no, c.account_name
                   FROM tickets t
                   JOIN assets a ON a.asset_id=t.asset_id
                   JOIN customers c ON c.customer_id=t.customer_id
                   WHERE t.out_at IS NOT NULL AND TRIM(t.out_at)!=''
                   ORDER BY t.out_at DESC LIMIT 10"""):
            moves.append((r["out_at"], "Out",
                          f"{r['unit_no']} out — {r['account_name']}",
                          f"/ticket/{r['ticket_id']}", r["asset_id"]))
        for r in con.execute(
                """SELECT t.ticket_id, t.in_at, a.asset_id, a.unit_no, c.account_name
                   FROM tickets t
                   JOIN assets a ON a.asset_id=t.asset_id
                   JOIN customers c ON c.customer_id=t.customer_id
                   WHERE t.in_at IS NOT NULL AND TRIM(t.in_at)!=''
                   ORDER BY t.in_at DESC LIMIT 10"""):
            moves.append((r["in_at"], "In",
                          f"{r['unit_no']} back in — {r['account_name']}",
                          f"/ticket/{r['ticket_id']}", r["asset_id"]))
        moves.sort(key=lambda m: m[0] or "", reverse=True)
        rows = "".join(
            f"<div class='todo'><span class='mute'>{html.escape(str(when)[:10])} · {kind}</span> "
            f"<a href='{html.escape(href, quote=True)}'>{html.escape(text)}</a> "
            f"{self._unit_state_badge(con, aid)}</div>"
            for when, kind, text, href, aid in moves[:5])
        return rows or "<p class='mute'>No movements yet.</p>"

    def view_assets_all(self, con):
        """Every unit, as it sits — no filter, no sort."""
        rows = []
        for r in con.execute(
                """SELECT asset_id, unit_no, category, description, rate_unit, rate_value,
                          active, condition FROM assets"""):
            _exp = engine.operative_cert_expiry(con, r["asset_id"])
            d = dict(r)
            d["cert_expire"] = _exp
            rows.append(d)
        body = "".join(
            f"<tr><td><a href='/unit/{html.escape(r['asset_id'])}'>{html.escape(r['asset_id'])}</a></td>"
            f"<td>{html.escape(r['unit_no'])}</td><td>{html.escape(r['category'] or '')}</td>"
            f"<td>{html.escape(r['description'] or '')}</td>"
            f"<td>${float(r['rate_value'] or 0):,.2f}/{html.escape((r['rate_unit'] or 'Day').lower())}</td>"
            f"<td>{'Yes' if r['active'] else 'No'}</td>"
            f"<td>{html.escape(r['condition'] or '')}</td>"
            f"<td>{html.escape(str(r['cert_expire'])[:10] if r['cert_expire'] else '')}</td>"
            "<td>" + _task_from_row(r['unit_no'] + " — " + (r['description'] or ''),
                                    "/unit/" + r['asset_id'], '/assets/all') + "</td></tr>"
            for r in rows
        )
        return f"""
        <p class="hint"><input id="auditq" placeholder="Filter this list…" size="30"
        oninput="document.querySelectorAll('table.audit').forEach(t=>auditFilter(t,this.value))">
        <span class="mute">Click a column header to sort.</span></p>
        <table class="audit"><tr><th>ID</th><th>Unit #</th><th>Category</th><th>Description</th>
        <th>Daily</th><th>Active</th><th>Condition</th><th>Cert expires</th><th></th></tr>
        {body or '<tr><td colspan=9>No units.</td></tr>'}</table>
        """ + AUDIT_TABLE_JS

    def _unit_compliance_link(self, con, aid):
        summ = engine.compliance_summary(con, aid)
        if not summ["total"]:
            return (f'<p class="hint">No compliance checks on this unit yet. '
                    f'<a href="/ucompliance/{html.escape(aid)}">Assign a Pack</a></p>')
        warn = f" — <b class='fail'>{summ['overdue']} overdue</b>" if summ["overdue"] else ""
        warn += f" — <b>{summ['due']} Due</b>" if summ["due"] else ""
        return (f'<p class="hint">Compliance: {summ["total"]} checks{warn}. '
                f'<a href="/ucompliance/{html.escape(aid)}">Manage Checklist</a></p>')

    def view_unit_form(self, con, aid):
        row = None
        if aid:
            row = con.execute("SELECT * FROM assets WHERE asset_id=?", (aid,)).fetchone()
            if not row:
                return '<div class="err">Unknown unit.</div>'
        nxt = aid or engine.next_asset_id(con)
        def v(k, default=""):
            if not row:
                return default
            val = row[k]
            return "" if val is None else str(val)
        cat_opts = [(c, c, c) for c in engine.lookups(con, "category")]
        yard_opts = [(y, y, y) for y in engine.lookups(con, "yard")]
        cond = self._sel(engine.lookups(con, "condition"), v("condition") or "Available")
        rate_units = self._sel(engine.lookups(con, "rate_type"), v("rate_unit") or "Day")
        live = con.execute(
            "SELECT ticket_id FROM tickets WHERE asset_id=? AND status IN ('Reserved','Dispatched','On Rent','Standby')",
            (aid,),
        ).fetchone() if aid else None
        warn = f"<p class='hint'>On ticket {html.escape(live['ticket_id'])} — you can edit rates and stamps, not the unit number while it is out.</p>" if live else ""
        unit_ro = " readonly" if live else ""
        return f"""
        {('<h1>Edit Unit</h1>' if row else '')}
        {warn}
        <form method=post action="/unit/save">
          <input type=hidden name=asset_id value="{html.escape(aid) if row else ''}">
          <label>Id</label><input value="{html.escape(nxt)}" disabled>
          <div class="row">
            <div><label>Unit Number</label><input name=unit_no required{unit_ro} value="{html.escape(v('unit_no'))}"></div>
            <div>{combo_field("u_cat", "category_text", cat_opts, value=v('category'), label="Category")}
            <input type=hidden id="u_cat_id" name=category value="{html.escape(v('category'), quote=True)}"></div>
          </div>
          <label>Description</label><input name=description required value="{html.escape(v('description'))}">
          <div class="row">
            <div><label>Serial</label><input name=serial_no value="{html.escape(v('serial_no'))}"></div>
            <div>{combo_field("u_yard", "yard_text", yard_opts, value=v('yard'), label="Yard")}
            <input type=hidden id="u_yard_id" name=yard value="{html.escape(v('yard'), quote=True)}"></div>
          </div>
          <div class="row">
            <div><label>Rate</label><select name=rate_unit>{rate_units}</select></div>
            <div><label>Rate $</label><input name=rate_value type=number step=0.01 class=w-sm value="{money_val(v('rate_value'))}"></div>
          </div>
          <div class="row">
            <div><label>Hour Meter</label><input name=meter_hours type=number step=0.1 value="{html.escape(v('meter_hours') or '0')}"></div>
            <div><label>Replacement $</label><input name=replacement_cost type=number step=0.01 value="{money_val(v('replacement_cost'))}"></div>
          </div>
          <div class="row">
            <div><label>Certificates</label><p class="hint">
            {f'Certifications, calibrations, and function tests live on the unit’s '
             f'<a href="/ucompliance/{html.escape(aid, quote=True)}">Compliance Page</a> — '
             f'every record names this unit and carries its own expiry.'
             if row else
             'After saving, add certifications, calibrations, and function tests on the '
             'unit’s compliance page — every record names the unit and carries its own expiry.'}
            </p></div>
          </div>
          <div class="row">
            <div><label>Condition</label><select name=condition>{cond}</select></div>
            <div><label style="margin-top:22px"><input type=checkbox name=active value=1 {"checked" if (not row) or row["active"] else ""}> Active — rentable</label></div>
          </div>
          <label>Ownership</label><input name=ownership value="{html.escape(v('ownership') or 'Owned')}">
          <label><input type=checkbox name=uscg_ok value=1 {"checked" if row and row["uscg_ok"] else ""}> USCG stamp</label>
          <label><input type=checkbox name=dnv_ok value=1 {"checked" if row and row["dnv_ok"] else ""}> DNV stamp</label>
          <label><input type=checkbox name=abs_ok value=1 {"checked" if row and row["abs_ok"] else ""}> ABS stamp</label>
          <label><input type=checkbox name=cert_operator value=1 {"checked" if row and row["cert_operator"] else ""}> Requires certified operator</label>
          <label>Notes</label><input name=notes value="{html.escape(v('notes'))}">
          {self.clerk_field(con)}
          <p><button>Save Unit</button> <a href="/assets/all">Cancel</a></p>
        </form>
        {self._unit_compliance_link(con, aid) if row else ""}
        """



    def view_sites(self, con):
        rows = con.execute(
            """SELECT s.site_id, s.site_name, s.operator, s.rig_name, s.loc_id, s.tax_exempt,
                      c.account_name, j.display_name, j.tax_rate, j.req_uscg, j.req_dnv, j.req_abs
               FROM sites s
               LEFT JOIN customers c ON c.customer_id = s.customer_id
               LEFT JOIN jurisdictions j ON j.loc_id = s.loc_id
               ORDER BY s.site_name"""
        ).fetchall()
        body = [
            f"<tr><td><a href='/site/{html.escape(r['site_id'])}'>{html.escape(r['site_id'])}</a></td>"
            f"<td>{html.escape(r['site_name'])} <a href='/site/{html.escape(r['site_id'])}/edit' style='font-size:11px'>Edit</a></td>"
            f"<td>{html.escape(r['account_name'] or '')}</td>"
            f"<td>{html.escape(r['operator'] or '')}</td>"
            f"<td>{html.escape(r['rig_name'] or '')}</td>"
            f"<td>{html.escape(r['display_name'] or r['loc_id'] or 'Not set')} ({float(r['tax_rate'] or 0)*100:.2f}%)</td>"
            f"<td>{'Exempt' if r['tax_exempt'] else 'Taxable'}</td>"
            f"<td>{'U' if r['req_uscg'] else ''}{'D' if r['req_dnv'] else ''}{'A' if r['req_abs'] else ''}</td></tr>"
            for r in rows
        ]
        return tabs_setup("/sites") + f"""<p style="margin:0 0 8px"><a class="btn" href="/site/new">+ New Site</a>
        <button type="button" class="vbtn" data-audit="/sites/all" data-title="Job sites — all">View All Sites</button></p>
        {capped_table(["ID", "Site", "Customer", "Operator", "Rig", "Tax location", "Exempt", "Req"], body)}
        """ + self._done_box(con, "/sites")

    def view_sites_all(self, con):
        """Every job site, filterable/sortable — the audit popup for Setup → Sites."""
        rows = con.execute(
            """SELECT s.site_id, s.site_name, s.operator, s.rig_name, s.loc_id, s.tax_exempt,
                      c.account_name, j.display_name, j.tax_rate, j.req_uscg, j.req_dnv, j.req_abs
               FROM sites s
               LEFT JOIN customers c ON c.customer_id = s.customer_id
               LEFT JOIN jurisdictions j ON j.loc_id = s.loc_id
               ORDER BY s.site_name"""
        ).fetchall()
        body = "".join(
            f"<tr><td><a href='/site/{html.escape(r['site_id'])}'>{html.escape(r['site_id'])}</a></td>"
            f"<td>{html.escape(r['site_name'])}</td>"
            f"<td>{html.escape(r['account_name'] or '')}</td>"
            f"<td>{html.escape(r['operator'] or '')}</td>"
            f"<td>{html.escape(r['rig_name'] or '')}</td>"
            f"<td>{html.escape(r['display_name'] or r['loc_id'] or 'Not set')} ({float(r['tax_rate'] or 0)*100:.2f}%)</td>"
            f"<td>{'Exempt' if r['tax_exempt'] else 'Taxable'}</td>"
            f"<td>{'U' if r['req_uscg'] else ''}{'D' if r['req_dnv'] else ''}{'A' if r['req_abs'] else ''}</td></tr>"
            for r in rows
        )
        return f"""
        <p class="hint"><input id="auditq" placeholder="Filter this list…" size="30"
        oninput="document.querySelectorAll('table.audit').forEach(t=>auditFilter(t,this.value))">
        <span class="mute">Click a column header to sort.</span></p>
        <table class="audit"><tr><th>ID</th><th>Site</th><th>Customer</th><th>Operator</th>
        <th>Rig</th><th>Tax location</th><th>Exempt</th><th>Req</th></tr>
        {body or '<tr><td colspan=8>No sites.</td></tr>'}</table>
        """ + AUDIT_TABLE_JS

    def view_site_route(self, con, sid):
        # /site/<id> is a quiet read page; the edit form lives at /site/<id>/edit.
        if sid.endswith("/edit"):
            real = sid[:-5]
            return (real, self.view_site_form(con, real))
        return (sid, self.view_site(con, sid))

    def view_site(self, con, sid):
        s = con.execute(
            """SELECT s.*, c.account_name, j.display_name
               FROM sites s
               LEFT JOIN customers c ON c.customer_id = s.customer_id
               LEFT JOIN jurisdictions j ON j.loc_id = s.loc_id
               WHERE s.site_id = ?""",
            (sid,),
        ).fetchone()
        if not s:
            return '<div class="err">Unknown site.</div>'
        wells = con.execute(
            """SELECT COALESCE(NULLIF(TRIM(well_or_pad), ''), '(unnamed)') AS w,
                      COUNT(*) AS n
               FROM tickets WHERE site_id = ? GROUP BY w ORDER BY MAX(on_rent) DESC""",
            (sid,),
        ).fetchall()
        tkts = con.execute(
            """SELECT t.ticket_id, t.status, t.on_rent, t.well_or_pad, a.unit_no
               FROM tickets t JOIN assets a ON a.asset_id = t.asset_id
               WHERE t.site_id = ? ORDER BY t.on_rent DESC LIMIT 11""",
            (sid,),
        ).fetchall()
        info = (
            ("Customer", s["account_name"] or "—"),
            ("Tax location", s["display_name"] or s["loc_id"] or "Not set — your call"),
            ("Operator", s["operator"] or "—"),
            ("Rig", s["rig_name"] or "—"),
            ("Flag / waters", f"{s['flag_state'] or '—'} / {s['waters'] or '—'}"),
            ("Regime", s["primary_regime"] or "—"),
            ("Tax", "Exempt" if s["tax_exempt"] else "Taxable"),
            ("Notes", s["notes"] or "—"),
        )
        info_html = "".join(
            f"<tr><th style='width:130px'>{html.escape(k)}</th><td>{html.escape(v)}</td></tr>"
            for k, v in info
        )
        wells_html = "".join(
            f"<tr><td>{html.escape(w['w'])}</td><td>{w['n']} ticket{'s' if w['n'] != 1 else ''}</td></tr>"
            for w in wells
        ) or '<tr><td colspan=2>No wells recorded on this pad yet.</td></tr>'
        tkt_rows = "".join(
            f"<tr><td><a href='/ticket/{html.escape(t['ticket_id'])}'>{html.escape(t['ticket_id'])}</a></td>"
            f"<td>{html.escape(t['unit_no'])}</td>"
            f"<td>{html.escape(t['well_or_pad'] or '—')}</td>"
            f"<td>{html.escape(t['status'])}</td>"
            f"<td>{html.escape(str(t['on_rent'])[:10])}</td></tr>"
            for t in tkts[:5]
        )
        more = f"<p class='hint'>+ {len(tkts) - 5} more</p>" if len(tkts) > 5 else ""
        return f"""
        <h1>{html.escape(s['site_name'])}</h1>
        <p class="hint">{html.escape(s['site_id'])}</p>
        <table>{info_html}</table>
        <h2 style="font-size:15px;color:var(--frame);margin:10px 0 5px">Wells on This Pad</h2>
        <table><tr><th>Well</th><th>Tickets</th></tr>{wells_html}</table>
        <h2 style="font-size:15px;color:var(--frame);margin:10px 0 5px">Tickets Here</h2>
        <table><tr><th>Ticket</th><th>Unit</th><th>Well</th><th>Status</th><th>On rent</th></tr>
        {tkt_rows or '<tr><td colspan=5>None yet.</td></tr>'}</table>
        {more}
        <p class="hint" style="margin-top:16px">
          <a href="/site/{html.escape(s['site_id'])}/edit">Edit</a>
          &nbsp;·&nbsp; <a href="/ticket/new?site={html.escape(s['site_id'])}">Add Well</a>
          &nbsp;·&nbsp; <a href="/site/new?from={html.escape(s['site_id'])}">New site from this one</a>
        </p>
        """

    def view_site_form(self, con, sid, q=None):
        row = None
        if sid:
            row = con.execute("SELECT * FROM sites WHERE site_id=?", (sid,)).fetchone()
            if not row:
                return '<div class="err">Unknown site.</div>'
        # Carry-forward: ?from=<site_id> pre-fills the common fields for a new
        # site nearby; the name (and notes) stay blank — that's what changes.
        carried = None
        if not row and q and q.get("from"):
            carried = con.execute("SELECT * FROM sites WHERE site_id=?",
                                  (q["from"],)).fetchone()
        _CARRY = ("customer_id", "loc_id", "operator", "rig_name", "flag_state",
                  "waters", "primary_regime")
        def v(k, default=""):
            src = row or (carried if k in _CARRY else None)
            if not src:
                return default
            val = src[k]
            return "" if val is None else str(val)
        exempt = (row["tax_exempt"] if row
                  else (carried["tax_exempt"] if carried else 0))
        nxt = sid or engine.next_site_id(con)
        locs = con.execute(
            "SELECT loc_id, COALESCE(display_name, loc_id) || ' · ' || printf('%.2f%%', tax_rate*100) AS label FROM jurisdictions ORDER BY display_name"
        ).fetchall()
        # Tax treatment is associated with the physical site but is optional at site creation;
        # a site may be created before a jurisdiction has been configured or selected.
        custs = con.execute("SELECT customer_id, account_name FROM customers ORDER BY account_name").fetchall()
        cust_opts, cust_cur = combo_opts(custs, "customer_id", "account_name", v("customer_id"))
        loc_opts, loc_cur = combo_opts(locs, "loc_id", "label", v("loc_id"))
        flag_opts = [(f, f, f) for f in engine.lookups(con, "flag_state")]
        waters_opts = [(w, w, w) for w in engine.lookups(con, "waters")]
        regime_opts = [(r, r, r) for r in engine.lookups(con, "regime")]
        return f"""
        <h1>{'Edit' if row else 'New'} Site</h1>
        {f'<p class="hint">Carried forward from {html.escape(carried["site_id"])} — name the new site.</p>' if carried else ''}
        <form method=post action="/site/save">
          <input type=hidden name=site_id value="{html.escape(sid) if row else ''}">
          <p class=hint>Enter the physical location first. Tax treatment is associated with this location and can be selected now or later.</p>
          <label>Site Name</label><input name=site_name required value="{html.escape(v('site_name'))}" class=w-md>
          <label>Address</label><input name=street value="{html.escape(v('street'))}" class=w-md>
          <input name=street2 value="{html.escape(v('street2'))}" placeholder="Suite, building, dock, c/o…" class=w-md>
          <div class="row"><div><label>City</label><input name=city value="{html.escape(v('city'))}"></div><div><label>State</label><input name=state maxlength=20 value="{html.escape(v('state'))}"></div></div>
          <div class="row"><div><label>Zip</label><input name=zip maxlength=12 value="{html.escape(v('zip'))}"></div><div>{combo_field("s_loc", "loc_text", loc_opts, value=loc_cur, label="Tax location (optional)", placeholder="Select when known…")}<input type=hidden id="s_loc_id" name=loc_id value="{html.escape(v('loc_id'), quote=True)}"></div></div>
          <div class="row">
            <div>{combo_field("s_cust", "customer_text", cust_opts, value=cust_cur, label="Customer (optional)")}<input type=hidden id="s_cust_id" name=customer_id value="{html.escape(v('customer_id'), quote=True)}"></div>
            <div><label>Operator / Company</label><input name=operator value="{html.escape(v('operator'))}"></div>
          </div>
          <div class="row"><div><label>Rig / Unit Name</label><input name=rig_name value="{html.escape(v('rig_name'))}"></div><div></div></div>
          <details><summary>Regulatory details</summary>
            <div class="row"><div>{combo_field("s_flag", "flag_state_text", flag_opts, value=v('flag_state'), label="Flag state")}<input type=hidden id="s_flag_id" name=flag_state value="{html.escape(v('flag_state'), quote=True)}"></div><div>{combo_field("s_waters", "waters_text", waters_opts, value=v('waters'), label="Waters")}<input type=hidden id="s_waters_id" name=waters value="{html.escape(v('waters'), quote=True)}"></div></div>
            {combo_field("s_regime", "primary_regime_text", regime_opts, value=v('primary_regime'), label="Primary regulatory regime")}<input type=hidden id="s_regime_id" name=primary_regime value="{html.escape(v('primary_regime'), quote=True)}">
          </details>
          <label><input type=checkbox name=tax_exempt value=1 {"checked" if exempt else ""}> Tax exempt at this site</label>
          <label>Notes</label><input name=notes value="{html.escape(v('notes'))}">
          <p><button>Save Site</button> <a class="btn secondary" href="{'/site/' + html.escape(sid) if row else '/sites'}">Cancel</a></p>
        </form>
        """


    def _wo_tax_html(self, wot):
        rows = "".join(
            f"<tr><td><a href='/wo/{html.escape(r['wo_id'])}'>{html.escape(r['wo_id'])}</a></td>"
            f"<td>{html.escape(r['unit_no'])}</td><td>{html.escape(r['work_type'])}</td>"
            f"<td>{'Billable' if r['charge_to']=='customer' else 'Internal'}</td>"
            f"<td>{html.escape(r['account_name'])}</td><td>{html.escape(r['status'])}</td>"
            f"<td>${r['cost']:,.2f}</td><td>${r['bill']:,.2f}</td><td>${r['net']:,.2f}</td></tr>"
            for r in wot["rows"]
        )
        return f"""
        <h2 style="font-size:19px;color:var(--frame)">Work Orders Vs Income · {html.escape(wot['label'])}</h2>
        <div class="cards">
          <div class="card"><span>Billable income</span><b>${wot['income']:,.2f}</b></div>
          <div class="card"><span>Net</span><b>${wot['net']:,.2f}</b></div>
        </div>
        <table><tr><th>WO</th><th>Unit</th><th>Type</th><th>Charge</th><th>Who</th><th>Status</th><th>Cost</th><th>Bill</th><th>Net</th></tr>
        {rows or f"<tr><td colspan=9>No work orders {html.escape(wot['start'])} to {html.escape(wot['end'])}.</td></tr>"}</table>
        """

    def view_wos(self, con, q=None):
        """The shop's open work — open work orders only, done box below.
        ?all=1 shows the full history (Complete/Void included)."""
        show_all = bool(q) and q.get("all") == "1"
        where = "" if show_all else "WHERE w.status IN ('Open','In progress')"
        rows = con.execute(
            f"""SELECT w.wo_id, w.work_type, w.status, w.charge_to, w.open_date,
                      w.labor, w.parts, w.other_cost, w.bill_amount, w.invoice_no,
                      a.unit_no, c.account_name
               FROM work_orders w
               JOIN assets a ON a.asset_id = w.asset_id
               LEFT JOIN customers c ON c.customer_id = w.customer_id
               {where}
               ORDER BY w.open_date DESC"""
        ).fetchall()
        body = "".join(
            f"<tr><td><a href='/wo/{html.escape(r['wo_id'])}'>{html.escape(r['wo_id'])}</a></td>"
            f"<td>{html.escape(r['unit_no'])}</td><td>{html.escape(r['work_type'])}</td>"
            f"<td>{'Billable' if r['charge_to']=='customer' else 'Internal'}</td>"
            f"<td>{html.escape(r['account_name'] or 'Yard')}</td>"
            f"<td>{html.escape(str(r['open_date'])[:10])}</td>"
            f"<td>{html.escape(r['status'])}</td>"
            f"<td>${engine.wo_cost(r['labor'], r['parts'], r['other_cost']):,.2f}</td>"
            f"<td>${float(r['bill_amount'] or 0):,.2f}</td>"
            f"<td>{html.escape(r['invoice_no'] or '')}</td></tr>"
            for r in rows
        )
        tax = engine.report_work_orders(con, "ytd")
        toggle = ('<a href="/wos">Open Only</a>' if show_all
                  else '<a href="/wos?all=1">Show all (incl. Complete/Void)</a>')
        return ("" if bare else self._ticket_kind_bar("workorder")) + f"""
        <h1>Work Orders</h1>
        <p style="margin:0 0 8px"><a class="btn" href="/wo/new">+ New Work Order</a></p>
        <div class="cards">
          <div class="card"><span>YTD billable</span><b>${tax['income']:,.2f}</b></div>
          <div class="card"><span>YTD net (bill − cost)</span><b>${tax['net']:,.2f}</b></div>
          <div class="card"><span>Open / in progress</span><b>{tax['open_n']}</b></div>
        </div>
        <p class="hint">{toggle}</p>
        <table><tr><th>WO</th><th>Unit</th><th>Type</th><th>Charge</th><th>Who</th><th>Opened</th><th>Status</th><th>Cost</th><th>Bill</th><th>Invoice</th></tr>
        {body or '<tr><td colspan=9>None yet.</td></tr>'}</table>
        """ + self._done_box(con, "/wos")

    def view_wo_form(self, con, wid, bare=False):
        row = None
        if wid:
            row = con.execute("SELECT * FROM work_orders WHERE wo_id=?", (wid,)).fetchone()
            if not row:
                return '<div class="err">Unknown work order.</div>'
        nxt = wid or engine.next_wo_id(con)
        def v(k, default=""):
            if not row:
                return default
            val = row[k]
            return "" if val is None else str(val)
        assets = con.execute(
            "SELECT asset_id, unit_no || ' · ' || COALESCE(description,'') AS label FROM assets ORDER BY unit_no"
        ).fetchall()
        custs = con.execute("SELECT customer_id, account_name FROM customers ORDER BY account_name").fetchall()
        tix = con.execute(
            """SELECT ticket_id, ticket_id || ' · ' || customer_id AS label FROM tickets
               WHERE status NOT IN ('Void','Closed') ORDER BY ticket_id DESC"""
        ).fetchall()
        wo_unit_opts, wo_unit_cur = combo_opts(assets, "asset_id", "label", v("asset_id"))
        wo_type_opts = [(t, t, t) for t in engine.lookups(con, "wo_type")]
        wo_cust_opts, wo_cust_cur = combo_opts(custs, "customer_id", "account_name", v("customer_id"))
        wo_tix_opts, wo_tix_cur = combo_opts(tix, "ticket_id", "label", v("ticket_id"))
        today = date.today().isoformat()
        quote_panel = quote_expiry_panel(con, v("quote_no")) if row else ""
        return ("" if bare else self._ticket_kind_bar("workorder")) + f"""
        {"" if bare else "<h1>" + ('Edit' if row else 'New') + " Work Order</h1>"}
        {quote_panel}
        <form method=post action="/wo/save" enctype="multipart/form-data">
          <input type=hidden name=wo_id value="{html.escape(wid) if row else ''}">
          <div class="row4">
            <div><label>Wo #</label><input value="{html.escape(nxt)}" disabled class=w-xs></div>
            <div>{combo_field("wo_unit", "asset_text", wo_unit_opts, value=wo_unit_cur, label="Unit", required=True)}
            <input type=hidden id="wo_unit_id" name=asset_id value="{html.escape(v('asset_id'), quote=True)}"></div>
            <div>{combo_field("wo_type", "work_type_text", wo_type_opts, value=v('work_type'), label="Type", required=True)}
            <input type=hidden id="wo_type_id" name=work_type value="{html.escape(v('work_type'), quote=True)}"></div>
            <div><label>Reference Ticket</label><input name=ref_ticket value="{html.escape(v('ref_ticket'))}" class=w-sm placeholder="Optional"></div>
            <div><label>Date</label><input type=date name=wo_date value="{html.escape(v('wo_date')[:10] if v('wo_date') else today)}" class=w-sm></div>
          </div>
          <div class="row4">
            <div><label>Charge to</label>
              <select name=charge_to class=w-sm>
                <option value=internal {"selected" if (not row) or row["charge_to"]=="internal" else ""}>Internal</option>
                <option value=customer {"selected" if row and row["charge_to"]=="customer" else ""}>Customer</option>
              </select>
            </div>
            <div><label>&nbsp;</label><label><input type=checkbox name=warranty value=1 {"checked" if row and row["warranty"] else ""}> Warranty</label></div>
            <div>{combo_field("wo_cust", "customer_text", wo_cust_opts, value=wo_cust_cur, label="Customer")}
            <input type=hidden id="wo_cust_id" name=customer_id value="{html.escape(v('customer_id'), quote=True)}"></div>
            <div><label>Status</label><select name=status class=w-sm>{self._sel(engine.lookups(con,'wo_status'), v('status') or 'Open')}</select></div>
          </div>
          <div class="row3">
            <div><label>Crew / Vendor</label><input name=vendor value="{html.escape(v('vendor'))}" class=w-sm></div>
            <div><label>Open Date</label><input type=date name=open_date required value="{html.escape(v('open_date')[:10] if v('open_date') else today)}" class=w-sm></div>
            <div><label>Close Date</label><input type=date name=close_date value="{html.escape(v('close_date')[:10] if v('close_date') else '')}" class=w-sm></div>
          </div>
          <div class="row4 lineitem-row">
            <div><label>Item</label><input name=item value="{html.escape(v('item'))}"></div>
            <div><label>Description</label><input name=description value="{html.escape(v('description'))}"></div>
            <div><label>Qty</label><input name=qty type=number step="any" value="{html.escape(v('qty') or '1')}" class=w-xs></div>
            <div><label>Rate $</label><input name=cost type=number step=0.01 value="{html.escape(v('cost') or '0')}" class=w-sm></div>
          </div>
          <div class="row3">
            <div style="grid-column:span 2"><label>Notes</label><input name=notes value="{html.escape(v('notes'))}" style="width:100%"></div>
            <div><label>Uploads</label><input type=file name=wo_upload></div>
          </div>
          {self._btn_row("Save", "wojobpop", add_item=True)}
          {self._job_info_popup('wojobpop')}
        </form>
        <script>
        (function(){{
          var form = document.querySelector('form[action="/wo/save"]');
          if (!form) return;
          function addItemRow(){{
            var proto = form.querySelector('.lineitem-row');
            if (!proto) return;
            var clone = proto.cloneNode(true);
            clone.querySelectorAll('[id]').forEach(function(el){{ el.removeAttribute('id'); }});
            clone.querySelectorAll('input').forEach(function(el){{
              el.value = (el.name === 'qty') ? '1' : '';
              el.removeAttribute('required');
            }});
            proto.parentNode.insertBefore(clone, proto.nextSibling);
            var inp = clone.querySelector('input');
            if (inp) inp.focus();
          }}
          // _btn_row's Add item button carries no id — match it by label.
          Array.prototype.forEach.call(form.querySelectorAll('button[type=button]'), function(b){{
            if (b.textContent.trim().toLowerCase() === 'add item') b.addEventListener('click', addItemRow);
          }});
        }})();
        </script>
        """

    def view_sale(self, con, q=None):
        """Equipment sales: outright sale of equipment (Jason 2026-10-07).
        Top-level tab, left of Rentals. Records sale, marks asset sold,
        carries to invoice."""
        from datetime import date
        today = date.today().isoformat()
        # Available assets (not sold, active)
        assets = con.execute(
            "SELECT asset_id, unit_no FROM assets WHERE active=1 AND (sold_date IS NULL OR sold_date='') ORDER BY unit_no"
        ).fetchall()
        custs = con.execute(
            "SELECT customer_id, account_name FROM customers ORDER BY account_name"
        ).fetchall()
        aopts = "".join(f"<option value='{r[0]}'>{r[1]}</option>" for r in assets)
        copts = "".join(f"<option value='{r[0]}'>{r[1]}</option>" for r in custs)
        sales = engine.list_sales(con, 5)
        rows = "".join(
            f"<div class='todo'><span class='mute'>{s['sale_date']}</span> "
            f"<b>{s['unit_no']}</b> → {s['account_name'] or '—'} "
            f"<span class='mute'>${s['amount']:,.2f}</span></div>"
            for s in sales
        )
        from datetime import date as _d
        _yr = _d.today().year
        _n = con.execute("SELECT COALESCE(MAX(CAST(SUBSTR(sale_id, 8) AS INTEGER)), 0) + 1 FROM sales WHERE sale_id LIKE ?", (f"S-{_yr}-%",)).fetchone()[0]
        sale_no = f"S-{_yr}-{_n:04d}"
        desk = html.escape(self.desk(con))
        return f"""
        <h2>Record a Sale</h2>
        <form method=post action="/sale/save" class="card" enctype="multipart/form-data">
          <input type=hidden name=sale_id value="{sale_no}">
          <div class="row4">
            <div><label>Sale #</label><input value="{sale_no}" disabled class=w-xs></div>
            <div><label>Customer</label><select name=customer_id required><option value="">— Pick —</option>{copts}</select></div>
            <div><label>Reference #</label><input name=ref_no class=w-sm placeholder="Optional"></div>
            <div><label>Date</label><input type=date name=sale_date value="{today}" required class=w-sm></div>
          </div>
          <div class="row" style="grid-template-columns:1fr 2fr 0.5fr 1fr">
            <div><label>Item</label><select name=asset_id required><option value="">— Pick —</option>{aopts}</select></div>
            <div><label>Description</label><input name=item_desc placeholder="Details"></div>
            <div><label>Qty</label><input name=qty type=number min=1 value=1 required class=w-xs></div>
            <div><label>Price</label><input name=amount type=number step=0.01 min=0.01 required class=w-sm></div>
          </div>
          <div class="row4">
            <div><label>Condition</label><input name=condition placeholder="As-is, good, etc."></div>
            <div style="grid-column:span 3"><label>Notes</label><input name=notes></div>
          </div>
          {self._btn_row("Save", "salejobpop", add_item=True)}
          {self._job_info_popup('salejobpop')}
          <input type=hidden name=clerk value="{desk}">
        </form>
        <h2>Recent Sales</h2>
        {rows or "<p class='hint'>No sales yet.</p>"}
        """
