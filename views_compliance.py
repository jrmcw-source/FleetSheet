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

"""FleetSheet views — certification/calibration flow: compliance packs and per-unit checklists."""

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
    CoreViews,)


class ComplianceViews(CoreViews):
    """FleetSheet views views mixed into Handler."""
    def _data_book_section(self, con, aid, clerk):
        docs = engine.list_unit_docs(con, aid)
        if docs:
            drows = "".join(
                f"<tr><td><input type=checkbox class=psel data-k=d data-id=\"{d['doc_id']}\""
                f" title=\"Tick to include this document in a selective print\"> "
                f"<b>{html.escape(d['title'])}</b></td>"
                f"<td>{html.escape(engine.DOC_KINDS.get(d['kind'], d['kind']))}</td>"
                f"<td>{html.escape(d['filename'])}</td>"
                f"<td>{(d['bytes'] or 0) / 1024:.0f} KB</td>"
                f"<td>{html.escape(str(d['uploaded_at'] or '')[:10])}</td>"
                f"<td><a class='btn secondary' style='padding:4px 10px' "
                f"href='/doc/{d['doc_id']}'>Open</a> "
                f"<form method=post action='/compliance/doc/delete' style='display:inline'>"
                f"<input type=hidden name=doc_id value='{d['doc_id']}'>"
                f"<button class='danger' style='padding:4px 10px' "
                f"data-tip='Removes this document from the data book.'>Delete</button>"
                f"</form></td></tr>"
                for d in docs)
            table = (f"<table><tr><th>Title</th><th>Type</th><th>File</th>"
                     f"<th>Size</th><th>Added</th><th></th></tr>{drows}</table>")
        else:
            table = "<p class='hint'>Nothing in this unit's data book yet.</p>"
        kind_opts = "".join(
            f"<option value='{k}'>{html.escape(v)}</option>"
            for k, v in engine.DOC_KINDS.items())
        return f"""
        <h2 style="font-size:16px;color:var(--frame);margin-top:20px">Data Book — Documents</h2>
        {table}
        <form method=post action="/compliance/doc/upload" enctype="multipart/form-data" class="actions">
          <input type=hidden name=asset_id value="{html.escape(aid)}">
          <div class="row">
            <div><label>Title</label><input name=title required maxlength=120
              placeholder="e.g. Purge panel data book"></div>
            <div><label>Type</label><select name=kind>{kind_opts}</select></div>
          </div>
          <label>File</label><input type=file name=doc_file required
            accept=".pdf,.png,.jpg,.jpeg,.webp,.txt,.csv">
          <div><label>Clerk</label><input name=clerk value="{clerk}" maxlength=40></div>
          <p><button data-tip="Attaches this document to the unit's data book.">Add Document</button></p>
        </form>
        """

    def _eqc_asset(self, con, eqc_id):
        try:
            eid = int(eqc_id)
        except (TypeError, ValueError):
            return ""
        r = con.execute("SELECT asset_id FROM equipment_compliance WHERE eqc_id=?", (eid,)).fetchone()
        return r["asset_id"] if r else ""

    def _cert_asset(self, con, cert_id):
        try:
            cid = int(cert_id)
        except (TypeError, ValueError):
            return ""
        r = con.execute("SELECT asset_id FROM asset_certs WHERE cert_id=?", (cid,)).fetchone()
        return r["asset_id"] if r else ""

    def _cert_status_chip(self, status):
        if status == "expired":
            return "<b class='fail'>expired</b>"
        if status == "valid":
            return "<b class='ok'>valid</b>"
        if status == "superseded":
            return "<span class='hint'>superseded</span>"
        return "<span class='hint'>no expiry</span>"

    def _cert_section(self, con, aid, clerk):
        """Certifications, calibrations, and function tests — every record
        names this unit. Evidence paperwork attaches to the record itself."""
        certs = engine.list_certs(con, aid)
        kind_opts = "".join(
            f"<option value='{k}'>{v}</option>" for k, v in engine.CERT_KINDS.items())
        docs = con.execute(
            "SELECT doc_id, title, filename FROM unit_docs WHERE asset_id=? ORDER BY doc_id",
            (aid,)).fetchall()
        doc_combo_opts = [(str(d["doc_id"]), str(d["title"] or d["filename"] or d["doc_id"]),
                           str(d["doc_id"])) for d in docs]
        doc_combo = (
            combo_field(f"f_doc_{cid}", "doc_id_text", doc_combo_opts,
                        label="Attach evidence",
                        placeholder="Type to search documents…")
            + f'<input type=hidden id="f_doc_{cid}_id" name=doc_id value="">'
        )
        cards = []
        for c in certs:
            cid = c["cert_id"]
            if c.get("evidence_doc_id"):
                ev = (f"<a href='/doc/{c['evidence_doc_id']}'>"
                      f"{html.escape(c['doc_title'] or c['doc_filename'] or 'document')}</a>")
            else:
                ev = "<span class='hint'>none attached</span>"
            sup_btn = (
                f"""<form method=post action="/compliance/cert/supersede" style="display:inline">
                      <input type=hidden name=cert_id value="{cid}">
                      <button class="secondary" data-tip="Keeps this record as history, but it no longer drives expiry alerts.">Mark Superseded</button>
                    </form>"""
                if not c["superseded"] else
                f"""<form method=post action="/compliance/cert/supersede" style="display:inline">
                      <input type=hidden name=cert_id value="{cid}">
                      <input type=hidden name=restore value="1">
                      <button class="secondary" data-tip="Makes this record live again.">Restore</button>
                    </form>""")
            cards.append(f"""
            <details style="margin:8px 0;border:1px solid var(--line,#ddd);border-radius:8px;padding:8px 12px">
              <summary><b>{html.escape(c['kind_label'])}</b> — {html.escape(c['title'])}
                <span class="hint">{html.escape(c['cert_number'] or '')}</span>
                · expires {html.escape(c['expiry_date'] or '—')} · {self._cert_status_chip(c['status'])}
                <br><span class="hint">evidence: {ev}</span></summary>
              <form method=post action="/compliance/cert/save" style="margin-top:8px">
                <input type=hidden name=cert_id value="{cid}">
                <div class="row">
                  <div><label>Title</label><input name=title value="{html.escape(c['title'])}" required></div>
                  <div><label>Kind</label><select name=kind>{
                    "".join(f"<option value='{k}'{' selected' if c['kind']==k else ''}>{v}</option>"
                            for k, v in engine.CERT_KINDS.items())}</select></div>
                </div>
                <div class="row">
                  <div><label>Certificate #</label><input name=cert_number value="{html.escape(c['cert_number'] or '')}"></div>
                  <div><label>Issuer</label><input name=issuer value="{html.escape(c['issuer'] or '')}"></div>
                </div>
                <div class="row">
                  <div><label>Issued</label><input type=date name=issued_date value="{html.escape(c['issued_date'] or '')}"></div>
                  <div><label>Expires</label><input type=date name=expiry_date value="{html.escape(c['expiry_date'] or '')}"></div>
                </div>
                <label>Notes</label><input name=notes value="{html.escape(c['notes'] or '')}">
                <p><button data-tip="Saves changes to this certificate record.">Save</button>
                {sup_btn}
                </p>
              </form>
              <form method=post action="/compliance/cert/evidence" class="actions">
                <input type=hidden name=cert_id value="{cid}">
                <div class="row">
                  <div>{doc_combo}</div>
                  <div style="align-self:end"><button data-tip="Ties this data-book document to the certificate record above.">Attach</button></div>
                </div>
                <p class="hint">Only documents from <b>This unit's</b> data book can attach — the evidence always names its unit.</p>
              </form>
              <form method=post action="/compliance/cert/delete">
                <input type=hidden name=cert_id value="{cid}">
                <button class="secondary" data-tip="Removes the record. Attached paperwork stays in the unit's data book.">Delete Record</button>
              </form>
            </details>""")
        return f"""
        <h2 style="font-size:16px;color:var(--frame)">Certifications &amp; Calibrations</h2>
        {''.join(cards) or '<p class="hint">No cert records yet — migrated expiries land here too.</p>'}
        <details style="margin:8px 0"><summary><b>Add a Certificate Record</b></summary>
        <form method=post action="/compliance/cert/save" enctype="multipart/form-data" style="margin-top:8px">
          <input type=hidden name=asset_id value="{html.escape(aid)}">
          <div class="row">
            <div><label>Title *</label><input name=title required maxlength=120
              placeholder="e.g. DNV recertification"></div>
            <div><label>Kind</label><select name=kind>{kind_opts}</select></div>
          </div>
          <div class="row">
            <div><label>Certificate #</label><input name=cert_number maxlength=60></div>
            <div><label>Issuer</label><input name=issuer maxlength=120 placeholder="e.g. DNV, shop lab"></div>
          </div>
          <div class="row">
            <div><label>Issued</label><input type=date name=issued_date value="{date.today().isoformat()}"></div>
            <div><label>Expires</label><input type=date name=expiry_date></div>
          </div>
          <label>Notes</label><input name=notes maxlength=200>
          <label>Evidence File (Optional)</label><input type=file name=doc_file
            accept=".pdf,.png,.jpg,.jpeg,.webp,.txt,.csv">
          <p class="hint">The file lands in this unit's data book and attaches straight to this record.</p>
          <div><label>Clerk</label><input name=clerk value="{clerk}" maxlength=40></div>
          <p><button data-tip="Saves the certificate record. A unit is required — always.">Add Certificate</button></p>
        </form></details>
        """

    def view_compliance(self, con):
        """Spare: ranked list, upload, done. No ticker (global covers it),
        no links, no explanations. (Jason 2026-10-07: ticker redundant)"""
        return ("<h2>Needs Attention</h2>" + self._compliance_ranked(con) +
                '<p><button type="button" class="vbtn" data-audit="/compliance/all" '
                'data-title="Compliance — all">View All</button></p>' +
                "<h2>Upload Certificate</h2>" + self._cert_upload_form(con) +
                self._done_box(con, "/compliance"))

    def view_compliance_all(self, con):
        """Every overdue/due checklist item — filterable, sortable audit list."""
        watch = engine.fleet_compliance_watch(con)
        watch.sort(key=lambda w: (0 if w["status"] == "overdue" else 1, w["next_due"] or "9999"))
        body = "".join(
            f"<tr><td><b class='{'fail' if w['status'] == 'overdue' else ''}'>"
            f"{w['status'].upper()}</b></td>"
            f"<td>{html.escape(w['unit_no'])}</td>"
            f"<td>{html.escape(w['item'])}</td>"
            f"<td>{html.escape((w['next_due'] or '—')[:10])}</td>"
            f"<td><a href='/ucompliance/{html.escape(w['asset_id'], quote=True)}"
            f"?focus={w['eqc_id']}'>Open</a></td></tr>"
            for w in watch)
        return f"""
        <p class="hint"><input id="auditq" placeholder="Filter this list…" size="30"
        oninput="document.querySelectorAll('table.audit').forEach(t=>auditFilter(t,this.value))">
        <span class="mute">Click a column header to sort.</span></p>
        <table class="audit"><tr><th>Status</th><th>Unit</th><th>Item</th><th>Due date</th><th></th></tr>
        {body or '<tr><td colspan=5>Nothing due.</td></tr>'}</table>
        """ + AUDIT_TABLE_JS

    def _compliance_ticker(self, con):
        """Problems tied to upcoming jobs: overdue/due items on units with
        a job starting within 14 days. Walkthrough #3: always rendered
        (quiet when nothing qualifies), 5 items, every item carries its
        action button plus snooze/sleep."""
        out = []
        today = date.today()
        soon = (today + timedelta(days=14)).isoformat()
        job_units = {r["asset_id"]: r for r in con.execute(
            """SELECT t.asset_id, t.ticket_id, t.on_rent, c.account_name
               FROM tickets t JOIN customers c ON c.customer_id=t.customer_id
               WHERE t.status IN ('Reserved','Dispatched')
               AND t.on_rent <= ?""", (soon,))}
        for w in engine.fleet_compliance_watch(con):
            j = job_units.get(w["asset_id"])
            if not j:
                continue
            out.append((
                f"{w['status'].upper()} — {html.escape(w['unit_no'])}: {html.escape(w['item'])} "
                f"<span class='mute'>ships {html.escape(str(j['on_rent'])[:10])} to {html.escape(j['account_name'])}</span>",
                f"/ucompliance/{w['asset_id']}?focus={w['eqc_id']}",
                f"comp:{w['asset_id']}:{w['item']}"))
        if not out:
            return ("<div class='news squeeze'><div class='tap calm'>"
                    "<span class='msg'>Nothing due on units with upcoming jobs.</span>"
                    "</div></div>")
        rows = "".join(
            f"<div class='tapbox lv0'><span class='msg'>{text}</span>"
            f"<a class='go' href='{html.escape(href, quote=True)}'>Fix It</a>"
            f"{_ack_forms(key, '/compliance')}"
            f"</div>"
            for text, href, key in out[:5])
        if len(out) > 5:
            rows += f"<p class='mute'>+ {len(out) - 5} more</p>"
        return f"<div class='news squeeze'>{rows}</div>"

    def _cert_upload_form(self, con):
        """Visible cert upload — not buried on the unit page."""
        units = con.execute(
            "SELECT asset_id, unit_no FROM assets WHERE active=1 ORDER BY unit_no").fetchall()
        uopts, _ = combo_opts(units, "asset_id", "unit_no", "",
                              disp=lambda v, lab: lab)
        unit_combo = (
            combo_field("f_upl_unit", "asset_id_text", uopts,
                        label="Unit", required=True,
                        placeholder="Type to search units…")
            + '<input type=hidden id="f_upl_unit_id" name=asset_id value="">'
        )
        kopts = "".join(
            f"<option value='{k}'>{v}</option>" for k, v in engine.CERT_KINDS.items())
        return f"""
        <form method=post action="/compliance/doc/upload" enctype="multipart/form-data">
          <div class="row">
            <div>{unit_combo}</div>
            <div><label>Kind</label><select name=kind>{kopts}</select></div>
          </div>
          <div class="row">
            <div><label>Title</label><input name=title required placeholder="Annual cert — GEN-063"></div>
            <div><label>File</label><input type=file name=doc_file required></div>
          </div>
          {self.clerk_field(con)}
          <p><button>Upload Certificate</button></p>
        </form>
        """

    def _compliance_ranked(self, con):
        """Overdue/due checklist items, ranked today-on-down."""
        watch = engine.fleet_compliance_watch(con)
        # Overdue first, then by due date.
        watch.sort(key=lambda w: (0 if w["status"] == "overdue" else 1, w["next_due"] or "9999"))
        rows = "".join(
            f"<div class='todo'><span class='{('fail' if w['status']=='overdue' else '')}'>"
            f"{w['status'].upper()}</span> "
            f"<a href='/ucompliance/{html.escape(w['asset_id'], quote=True)}'>"
            f"{html.escape(w['unit_no'])}</a> — {html.escape(w['item'])} "
            f"<span class='mute'>due {html.escape((w['next_due'] or '—')[:10])}</span> "
            f"<a class='vbtn' href='/print/compliance/{html.escape(w['asset_id'], quote=True)}.pdf'>Print</a></div>"
            for w in watch[:5])
        if len(watch) > 5:
            rows += f"<p class='mute'>+ {len(watch) - 5} more</p>"
        return rows or "<p class='mute'>Everything's current.</p>"

    def view_pack(self, con, pack_id):
        pack, reqs = engine.get_pack(con, pack_id)
        if not pack:
            return "" + '<div class="err">Unknown pack.</div>'
        cards = []
        for r in reqs:
            trig = engine.TRIGGER_LABELS.get(r["trigger"], r["trigger"])
            iv = f'{r["interval_months"]:g} months' if r["interval_months"] else "—"
            bs = f'{r["deployed_backstop_months"]:g} months' if r["deployed_backstop_months"] else "—"
            basis = engine.BASIS_LABELS.get(r["basis"], r["basis"])
            note = f"<p class='hint'>Note: {html.escape(r['note'])}</p>" if r["note"] else ""
            cards.append(f"""
            <div class="card" style="margin:10px 0">
              <b>{html.escape(r['name'])}</b>
              <p class="hint">{html.escape(trig)} · interval {iv} · deployed backstop {bs} · {html.escape(basis)}</p>
              <p>Accept: {html.escape(r['criterion'] or '—')}</p>
              <p class="hint">Evidence: {html.escape(r['evidence'] or '—')} · Source: {html.escape(r['source'] or '—')}</p>
              {note}
            </div>""")
        return "" + f"""
        <h1>{html.escape(pack['name'])}</h1>
        <p class="hint">{html.escape(pack['blurb'] or '')}</p>
        <p class="actions"><a class="btn" href="/compliance">All Packs</a></p>
        {''.join(cards)}
        """

    def _fixit_form(self, con, aid, it, clerk, today):
        """The fix-it form (walkthrough #3): pre-filled with the item's info,
        visual cert status, DNV/USCG present-absent, attach documents,
        data-book check, change status, save."""
        eid = it["eqc_id"]
        status = it["status"]
        st_badge = {"overdue": "<b class='fail'>OVERDUE</b>",
                    "due": "<b>Due</b>",
                    "ok": "<span class='ok'>Compliant</span>"}.get(status, status)
        nd = it["next_due_live"].isoformat() if it["next_due_live"] else "—"
        # DNV / USCG: present when any cert or doc on the unit names them.
        certs = engine.list_certs(con, aid)
        docs = con.execute(
            "SELECT title, filename FROM unit_docs WHERE asset_id=?", (aid,)).fetchall()
        blob = " ".join([(c.get("title") or "") for c in certs] +
                        [(d["title"] or "") + " " + (d["filename"] or "") for d in docs]).lower()
        dnv = "present" if "dnv" in blob else "absent"
        uscg = "present" if "uscg" in blob else "absent"
        cert_rows = "".join(
            f"<div class='todo'><span class='{'fail' if c.get('status')=='expired' else 'ok'}'>"
            f"{html.escape(c.get('status','').upper())}</span> "
            f"{html.escape(c.get('title') or c.get('kind',''))} "
            f"<span class='mute'>exp {html.escape(str(c.get('expiry_date') or '—')[:10])}</span></div>"
            for c in certs[:5])
        hist = "".join(
            f"<tr><td>{html.escape(h['done_date'])}</td><td>{html.escape(h['result'])}</td>"
            f"<td>{html.escape(h['evidence'] or '')}</td><td>{html.escape(h['clerk'] or '')}</td></tr>"
            for h in engine.item_history(con, eid, 5))
        return f"""
        <fieldset><legend>Fix it — {html.escape(it['display_name'])}</legend>
        <p>{st_badge} · next due {html.escape(nd)} · last done {html.escape(it['last_done'] or '—')}</p>
        <div class="row">
          <div><b>Certifications / Calibrations</b>
            {cert_rows or "<p class='mute'>None on file.</p>"}</div>
          <div><b>Ratings</b>
            <p>DNV: <b class='{'ok' if dnv=='present' else 'fail'}'>{dnv}</b><br>
               USCG: <b class='{'ok' if uscg=='present' else 'fail'}'>{uscg}</b></p></div>
        </div>
        <form method=post action="/compliance/item/done" enctype="multipart/form-data">
          <input type=hidden name=eqc_id value="{eid}">
          <input type=hidden name=next value="/ucompliance/{html.escape(aid)}?focus={eid}">
          <div class="row">
            <div><label>Done Date</label><input type=date name=done_date value="{today}" required class=w-sm></div>
            <div><label>Result</label><select name=result class=w-sm>
              <option value="pass">Pass</option><option value="fail">Fail</option></select></div>
          </div>
          <label>Evidence (cert #, Reading)</label><input name=evidence>
          <div class="row">
            <div><label>Attach Document</label><input type=file name=doc_file></div>
            <div><label>Notes</label><input name=notes></div>
          </div>
          <div class="row">
            <div><label>Clerk</label><input name=clerk value="{clerk}" class=w-sm></div>
            <div><label><input type=checkbox name=data_book_ok value=1> Data book checked</label></div>
          </div>
          <p><button>Save</button></p>
        </form>
        <p class="hint">History</p>
        <table><tr><th>Date</th><th>Result</th><th>Evidence</th><th>Clerk</th></tr>
        {hist or '<tr><td colspan=4>Nothing recorded yet.</td></tr>'}</table>
        </fieldset>
        """

    def view_unit_compliance(self, con, aid, focus=None):
        a = con.execute("SELECT * FROM assets WHERE asset_id=?", (aid,)).fetchone()
        if not a:
            return '<div class="err">Unknown unit.</div>'
        items = engine.unit_checklist(con, aid)
        summ = engine.compliance_summary(con, aid)
        today = date.today().isoformat()
        clerk = html.escape(self.desk(con))
        have = set(engine.unit_packs(con, aid))
        rest = [p for p in engine.list_packs(con) if p["pack_id"] not in have]
        if rest:
            pack_combo_opts = [(str(p["pack_id"]),
                                f"{p['name']} ({p['n_reqs']} checks)",
                                str(p["pack_id"])) for p in rest]
            pack_combo = (
                combo_field("f_pack_id", "pack_id_text", pack_combo_opts,
                            placeholder="Type to search packs…")
                + '<input type=hidden id="f_pack_id_id" name=pack_id value="">'
            )
            assign = f"""
            <form method=post action="/compliance/assign" class="actions">
              <input type=hidden name=asset_id value="{html.escape(aid)}">
              {pack_combo}
              <button data-tip="Copies the pack's checks onto this unit. Intervals stay adjustable per unit.">Assign Pack</button>
            </form>"""
        else:
            assign = '<p class="hint">Every pack is on this unit already.</p>'
        rows = []
        vendors = engine.list_vendors(con)
        for it in items:
            eid = it["eqc_id"]
            trig = engine.TRIGGER_LABELS.get(it["trigger"], it["trigger"])
            iv = f'{it["interval_months"]:g} mo' if it["interval_months"] else "—"
            bs = f'{it["deployed_backstop_months"]:g} mo' if it["deployed_backstop_months"] else "—"
            nd = it["next_due_live"].isoformat() if it["next_due_live"] else "—"
            pack = html.escape(it["pack_name"]) if it["pack_name"] else "<span class='hint'>custom</span>"
            hrows = "".join(
                f"<tr><td>{html.escape(h['done_date'])}</td><td>{html.escape(h['result'])}</td>"
                f"<td>{html.escape(h['evidence'] or '')}</td><td>{html.escape(h['notes'] or '')}</td>"
                f"<td>{html.escape(h['clerk'] or '')}</td></tr>"
                for h in engine.item_history(con, eid, 10))
            name_field = (
                f'<label>Check Name</label>'
                f'<input name=custom_name value="{html.escape(it["custom_name"] or "")}">'
                if it["req_id"] is None else "")
            # Legacy custom per-job/manufacturer rows saved before the backstop rule:
            # flag them so they can't sit silently in "info" forever.
            no_alert = (it["req_id"] is None and it["trigger"] in ("per_job", "manufacturer")
                        and not it["deployed_backstop_months"])
            warn = ("<br><b style='color:#b26a00'>No backstop — this check can never "
                    "come due. Edit it and set one.</b>" if no_alert else "")
            who = (f"{html.escape(it['performer_name'])}"
                   f"<br><span class='hint'>{html.escape(it['performer_phone'])}</span>"
                   if it.get("performer_name") else "<span class='hint'>ourselves</span>")
            perf_opts, perf_cur = combo_opts(
                [{"vendor_id": v["vendor_id"],
                  "label": f"{v['name']} ({v['kind']})"} for v in vendors],
                "vendor_id", "label", it.get("performer_id") or "")
            perf_combo = (
                combo_field(f"f_perf_{eid}", "performer_id_text", perf_opts,
                            value=perf_cur, label="Who does this check",
                            placeholder="Type to search vendors…")
                + f'<input type=hidden id="f_perf_{eid}_id" name=performer_id value="'
                  f'{html.escape(str(it.get("performer_id") or ""), quote=True)}">'
            )
            rows.append(f"""
            <tr>
              <td><input type=checkbox class=psel data-k=c data-id="{eid}"
                   title="Tick to include this check in a selective print">
                  <b>{html.escape(it['display_name'])}</b><br><span class="hint">{pack}</span>{warn}</td>
              <td>{html.escape(trig)}</td><td>{iv}</td><td>{bs}</td>
              <td>{html.escape(it['last_done'] or '—')}</td><td>{nd}</td>
              <td>{_cstat(it['status'])}</td>
              <td>{who}</td>
              <td><details><summary>Manage</summary>
                <form method=post action="/compliance/item/done">
                  <input type=hidden name=eqc_id value="{eid}">
                  <div class="row">
                    <div><label>Done Date</label><input type=date name=done_date value="{today}" required></div>
                    <div><label>Result</label><select name=result><option value="pass">Pass</option><option value="fail">Fail</option></select></div>
                  </div>
                  <label>Evidence (cert #, Reading)</label><input name=evidence>
                  <div class="row">
                    <div><label>Notes</label><input name=notes></div>
                    <div><label>Clerk</label><input name=clerk value="{clerk}"></div>
                  </div>
                  <p><button data-tip="Logs this check done and moves the next due date.">Record Done</button></p>
                </form>
                <form method=post action="/compliance/item/save">
                  <input type=hidden name=eqc_id value="{eid}">
                  {name_field}
                  <label>Trigger</label><select name=trigger>{_trigger_opts(it['trigger'])}</select>
                  <div class="row">
                    <div><label>Interval (Months)</label><input name=interval_months value="{it['interval_months'] or ''}" placeholder="calendar only"></div>
                    <div><label>Deployed Backstop (Months)</label><input name=backstop_months value="{it['deployed_backstop_months'] or ''}" placeholder="per-job only"></div>
                  </div>
                  <label>Notes</label><input name=notes value="{html.escape(it['notes'] or '')}">
                  {perf_combo}
                  <p class="hint">A vendor or crew name here puts "call them" next to the check wherever it comes due. Blank means the yard does it.</p>
                  <p><button data-tip="Adjusts this unit's trigger, interval, or backstop. The pack template is unchanged.">Save Changes</button></p>
                </form>
                <p class="hint" style="margin:8px 0 4px"><b>History</b></p>
                <table><tr><th>Date</th><th>Result</th><th>Evidence</th><th>Notes</th><th>Clerk</th></tr>
                {hrows or '<tr><td colspan=5>Nothing recorded yet.</td></tr>'}</table>
                <form method=post action="/compliance/item/delete" style="margin-top:8px">
                  <input type=hidden name=eqc_id value="{eid}">
                  <button data-tip="Removes this check and its history from the unit.">Remove Check</button>
                </form>
              </details></td>
            </tr>""")
        badge = ((f"<b class='fail'>{summ['overdue']} overdue</b> · ") if summ['overdue'] else "") + \
                ((f"<b>{summ['due']} Due</b> · ") if summ['due'] else "") + \
                f"{summ['ok']} ok · {summ['info']} info"
        # Focus: the item the ticker sent us to, else the most urgent.
        rank = {"overdue": 0, "due": 1, "ok": 2, "info": 3}
        ordered = sorted(items, key=lambda it: (rank.get(it["status"], 9),
                         str(it["next_due_live"] or "9999")))
        focused = next((it for it in items if str(it["eqc_id"]) == str(focus or "")), None)
        focused = focused or (ordered[0] if ordered else None)
        why = ""
        if focused:
            why = (f"<p><b class='{'fail' if focused['status']=='overdue' else ''}'>"
                   f"{focused['status'].upper()}</b> — {html.escape(focused['display_name'])}: "
                   f"next due {html.escape(str(focused['next_due_live'] or '—')[:10])}, "
                   f"last done {html.escape(focused['last_done'] or '—')}.</p>")
        fixit = self._fixit_form(con, aid, focused, clerk, today) if focused else ""
        return f"""
        <h1>Compliance · {html.escape(a['unit_no'])}</h1>
        <p class="hint">{html.escape(a['description'] or '')} — {badge} ({summ['total']} checks).
        <a href="/unit/{html.escape(aid)}">Back to Unit</a></p>
        {why}
        {fixit}
        <p class="actions">
          <a class="btn" href="/print/compliance/{html.escape(aid)}"
             data-tip="One-button print: this unit's full certifications & calibrations record plus its data-book documents.">Print Pack</a>
          <a class="btn secondary" href="/print/compliance/{html.escape(aid)}.pdf"
             data-tip="One file: the checklist, embedded images, and the full pages of every attached PDF and text document.">Pack Pdf</a>
          <button class="btn secondary" onclick="selPrint(false)"
             data-tip="Prints only the checks and documents you ticked below.">Print Selected</button>
          <button class="btn secondary" onclick="selPrint(true)"
             data-tip="One PDF file: the selected checks plus the full pages of the selected documents.">Selected Pdf</button>
        </p>
        <p class="actions">
          <button class="secondary" onclick="selAll(true)" style="padding:4px 10px">Tick All</button>
          <button class="secondary" onclick="selAll(false)" style="padding:4px 10px">Clear</button>
        </p>
        <script>
        function selPrint(pdf){{
          var c=[],d=[];
          document.querySelectorAll('.psel:checked').forEach(function(el){{
            (el.dataset.k=='c'?c:d).push(el.dataset.id);}});
          if(!c.length&&!d.length){{alert('Tick at least one check or document first.');return;}}
          window.open('/print/compliance/{html.escape(aid)}/sel'+(pdf?'.pdf':'')+'?c='+c.join(',')+'&d='+d.join(','),'_blank');
        }}
        function selAll(on){{
          document.querySelectorAll('.psel').forEach(function(el){{el.checked=on;}});
        }}
        </script>
        <h2 style="font-size:16px;color:var(--frame)">Assign a Pack</h2>
        {assign}
        <h2 style="font-size:16px;color:var(--frame)">Checklist</h2>
        <table><tr><th>Check</th><th>Trigger</th><th>Interval</th><th>Backstop</th><th>Last done</th><th>Next due</th><th>Status</th><th>Who</th><th></th></tr>
        {''.join(rows) or '<tr><td colspan=9>No checks yet — assign a pack or add one below.</td></tr>'}</table>
        <h2 style="font-size:16px;color:var(--frame);margin-top:20px">Add Your Own Check</h2>
        <form method=post action="/compliance/custom">
          <input type=hidden name=asset_id value="{html.escape(aid)}">
          <label>Check Name</label><input name=name required placeholder="e.g. Yard function test">
          <label>Trigger</label><select name=trigger>{_trigger_opts('per_job')}</select>
          <div class="row">
            <div><label>Interval (Months)</label><input name=interval_months placeholder="calendar only"></div>
            <div><label>Deployed Backstop (Months)</label><input name=backstop_months placeholder="required for per-job / manufacturer"></div>
          </div>
          <label>Notes</label><input name=notes>
          <p><button data-tip="Adds a shop-built check to this unit's list.">Add Check</button></p>
        </form>
        {self._done_box(con, f"/ucompliance/{html.escape(aid)}")}
        """
