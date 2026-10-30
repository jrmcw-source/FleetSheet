from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import html
from datetime import date, timedelta
from urllib.parse import parse_qs, quote, quote_plus, urlparse

import engine

"""FleetSheet views — certification/calibration flow: compliance packs and per-unit checklists."""

from views_core import (
    page,
    tabs,
    tabs_reports,
    tabs_boards,
    weekly_tabs,
    tabs_admin,
    tabs_invoice,
    tabs_quotes,
    tabs_money,
    _cstat,
    _trigger_opts,
    lookup_select,
    enabled_values,
    opts,
    lan_urls,
    _nav_section,
    money_val,
    note_pop_html,
    quote_expiry_panel,
    task_nudge,
    more_link,
    DASH_CAP,
    view_button,
    AUDIT_TABLE_JS,
    combo_field,
    combo_opts,
    fmt_date,
    PRINTMENU_JS,
    CoreViews,)


class ComplianceViews(CoreViews):
    """FleetSheet views views mixed into Handler."""

    def _eqc_asset(self, con, eqc_id):
        try:
            eid = int(eqc_id)
        except (TypeError, ValueError):
            return ""
        r = con.execute("SELECT asset_id FROM equipment_compliance WHERE eqc_id=?", (eid,)).fetchone()
        # Build 'v': the column holds the engine key; routes and
        # redirects address the unit by its code.
        return engine.asset_code(con, r["asset_id"]) if r else ""

    def _watch_item_row(self, w, show_unit=True):
        unit_cell = (f"<td>{html.escape(w['unit_no'])}</td>"
                     if show_unit else "")
        perf = (f"{html.escape(w['performer_name'])}"
                + (f" <span class='hint'>{html.escape(w['performer_phone'])}</span>"
                   if w.get('performer_phone') else "")
                if w.get('performer_name') else "<span class='hint'>ourselves</span>")
        return (f"<tr><td><b class='{'fail' if w['status'] == 'overdue' else ''}'>"
                f"{w['status'].upper()}</b></td>"
                f"{unit_cell}"
                f"<td>{html.escape(w['item'])}</td>"
                f"<td>{html.escape(fmt_date(w['next_due'], '—'))}</td>"
                f"<td>{perf}</td>"
                f"<td><a href='/ucompliance/{html.escape(w['asset_id'], quote=True)}"
                f"?focus={w['eqc_id']}'>Open</a></td></tr>")

    def _grouped_watch_html(self, con, by="unit"):
        """The full dated watch, GROUPED (Batch 3 #18). by="unit": one
        header row per unit (worst first, the ticker's order), its
        items beneath. by="vendor": the call sheet — one header per
        performer (vendor/crew), blank performer grouped as
        "Ourselves". Per-shift rows are never in the watch."""
        watch = engine.fleet_compliance_watch(con)
        if not watch:
            return "<p class='mute'>Nothing due.</p>"
        if by == "vendor":
            groups = {}
            for w in watch:
                groups.setdefault(w.get("performer_name") or "", []).append(w)
            ordered = sorted(
                groups.items(),
                key=lambda kv: (kv[0] == "", kv[0].lower()))
            parts = []
            for name, items in ordered:
                items.sort(key=lambda w: (0 if w["status"] == "overdue" else 1,
                                          w["next_due"] or "9999"))
                phone = next((w["performer_phone"] for w in items
                              if w.get("performer_phone")), "")
                label = (f"{html.escape(name)}"
                         + (f" — {html.escape(phone)}" if phone else "")) \
                    if name else "Ourselves"
                parts.append(
                    f"<tr class='grouphd'><td colspan=6><b>{label}</b> "
                    f"<span class='mute'>{len(items)} item"
                    f"{'s' if len(items) != 1 else ''}</span></td></tr>")
                parts += [self._watch_item_row(w) for w in items]
            head = ("<tr><th>Status</th><th>Unit</th><th>Item</th>"
                    "<th>Due date</th><th>Who does this</th><th></th></tr>")
            return (f"<table class='audit'>{head}{''.join(parts)}</table>")
        parts = []
        for g in engine.compliance_groups(con):
            parts.append(
                f"<tr class='grouphd'><td colspan=5><b>"
                f"{html.escape(g['unit_no'])}</b> <span class='mute'>"
                f"{g['n_due']} due, {g['n_overdue']} overdue</span> "
                f"<a href='/ucompliance/{html.escape(g['asset_id'], quote=True)}'>Open unit</a>"
                f"</td></tr>")
            parts += [self._watch_item_row(w, show_unit=False)
                      for w in g["items"]]
        head = ("<tr><th>Status</th><th>Item</th><th>Due date</th>"
                "<th>Who does this</th><th></th></tr>")
        return f"<table class='audit'>{head}{''.join(parts)}</table>"

    def view_compliance(self, con, q=None):
        """The compliance work list (Batch 3 #18): the grouped full
        list, upload, done. Attention lives ONLY in the global ticker
        now — this page carries no ticker of its own and no ranked
        attention list. Grouping toggles Unit / Vendor (call sheet)."""
        if not engine.module_on(con, "compliance"):
            # The route never dies (shop-flow, Jason 2026-10-21): with
            # the switch off the page is a plain note plus the View door.
            # The records behind it are untouched and return, intact,
            # when the switch flips back on.
            return ("<p>Compliance paperwork is off.</p>"
                    + self._view_door("/compliance/all", "Compliance — all"))
        engine.stamp_module_seen(con, "compliance")
        by = "vendor" if (q or {}).get("group") == "vendor" else "unit"
        toggle = ("<p class='actions'>Group: "
                  + ("<b>Unit</b> · <a href='/compliance?group=vendor'>Vendor</a>"
                     if by == "unit" else
                     "<a href='/compliance'>Unit</a> · <b>Vendor</b>")
                  + "</p>")
        return (toggle + self._grouped_watch_html(con, by) +
                "<h2>Upload Certificate</h2>" + self._cert_upload_form(con) +
                self._view_door("/compliance/all", "Compliance — all"))

    def view_compliance_all(self, con):
        """Every overdue/due checklist item — the audit list, grouped
        by unit (Batch 3 #18): unit header rows, items beneath."""
        body = self._grouped_watch_html(con, "unit")
        return f"""
        <p class="hint"><input id="auditq" placeholder="Filter" size="30"
        oninput="document.querySelectorAll('table.audit').forEach(t=>auditFilter(t,this.value))">
        </p>
        {body}
        """ + AUDIT_TABLE_JS

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
        kopts = lookup_select(con, "comp_doc", "doc_type",
                              vals=enabled_values(con, "comp_doc"), add_option=True)
        return f"""
        <form method=post action="/compliance/doc/upload" enctype="multipart/form-data">
          <div class="row">
            <div>{unit_combo}</div>
            <div><label>Document</label>{kopts}
            <div class="hint"><b>Other</b> = one-off · <b>-Add-</b> = new type</div></div>
          </div>
          <div class="row">
            <div><label>Title</label><input name=title placeholder="Optional — defaults to the document type"></div>
            <div><label>File</label><input type=file name=doc_file required></div>
          </div>
          <div class="row">
            <div><label><input type=checkbox name=replace value=1>
            Replace the existing document of this type for this unit</label></div>
          </div>
          <p><button>Upload Certificate</button></p>
        </form>
        """

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

    def _fixit_form(self, con, aid, it, today):
        """The fix-it form (walkthrough #3): pre-filled with the item's info,
        visual cert status, DNV/USCG present-absent, attach documents,
        data-book check, change status, save."""
        eid = it["eqc_id"]
        status = it["status"]
        st_badge = {"overdue": "<b class='fail'>OVERDUE</b>",
                    "due": "<b>Due</b>",
                    "ok": "<span class='ok'>Compliant</span>"}.get(status, status)
        nd = fmt_date(it["next_due_live"], "—")
        # DNV / USCG: present when any cert or doc on the unit names them.
        certs = engine.list_certs(con, aid)
        docs = con.execute(
            "SELECT title, filename FROM unit_docs WHERE asset_id=?",
            (engine.asset_key(con, aid),)).fetchall()
        blob = " ".join([(c.get("title") or "") for c in certs] +
                        [(d["title"] or "") + " " + (d["filename"] or "") for d in docs]).lower()
        dnv = "present" if "dnv" in blob else "absent"
        uscg = "present" if "uscg" in blob else "absent"
        cert_rows = "".join(
            f"<div class='todo'><span class='{'fail' if c.get('status')=='expired' else 'ok'}'>"
            f"{html.escape(c.get('status','').upper())}</span> "
            f"{html.escape(c.get('title') or c.get('kind',''))} "
            f"<span class='mute'>exp {html.escape(fmt_date(c.get('expiry_date'), '—'))}</span></div>"
            for c in certs[:5])
        hist = "".join(
            f"<tr><td>{html.escape(fmt_date(h['done_date']))}</td><td>{html.escape(h['result'])}</td>"
            f"<td>{html.escape(h['evidence'] or '')}</td><td>{html.escape(h['clerk'] or '')}</td></tr>"
            for h in engine.item_history(con, eid, 5))
        return f"""
        <fieldset><legend>Fix it — {html.escape(it['display_name'])}</legend>
        <p>{st_badge} · next due {html.escape(nd)} · last done {html.escape(fmt_date(it['last_done'], '—'))}</p>
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
          <label>Evidence (CERT #, Reading)</label><input name=evidence>
          <div class="row">
            <div><label>Attach Document</label><input type=file name=doc_file></div>
            <div><label>Notes</label><input name=notes></div>
          </div>
          <div class="row">
            <div><label><input type=checkbox name=data_book_ok value=1> Data book checked</label></div>
          </div>
          <p><button>Save</button></p>
        </form>
        <p class="hint">History</p>
        <table><tr><th>Date</th><th>Result</th><th>Evidence</th><th>Input by:</th></tr>
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
              <button>Assign Pack</button>
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
            nd = fmt_date(it["next_due_live"], "—")
            pack = html.escape(it["pack_name"]) if it["pack_name"] else "<span class='hint'>custom</span>"
            hrows = "".join(
                f"<tr><td>{html.escape(fmt_date(h['done_date']))}</td><td>{html.escape(h['result'])}</td>"
                f"<td>{html.escape(h['evidence'] or '')}</td><td>{note_pop_html(h['notes'])}</td>"
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
            warn = ("<br><b style='color:#b26a00'>No backstop — check never due.</b>"
                    if no_alert else "")
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
              <td><b>{html.escape(it['display_name'])}</b><br><span class="hint">{pack}</span>{warn}</td>
              <td>{html.escape(trig)}</td><td>{iv}</td><td>{bs}</td>
              <td>{html.escape(fmt_date(it['last_done'], '—'))}</td><td>{nd}</td>
              <td>{_cstat(it['status'])}</td>
              <td>{who}</td>
              <td><details><summary>Manage</summary>
                <form method=post action="/compliance/item/done">
                  <input type=hidden name=eqc_id value="{eid}">
                  <div class="row">
                    <div><label>Done Date</label><input type=date name=done_date value="{today}" required></div>
                    <div><label>Result</label><select name=result><option value="pass">Pass</option><option value="fail">Fail</option></select></div>
                  </div>
                  <label>Evidence (CERT #, Reading)</label><input name=evidence>
                  <label>Notes</label><input name=notes>
                  <p><button>Record Done</button></p>
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
                  <p class="hint">Performer: "call them" when due. Blank = yard.</p>
                  <p><button>Save</button></p>
                </form>
                <p class="hint" style="margin:8px 0 4px"><b>History</b></p>
                <table><tr><th>Date</th><th>Result</th><th>Evidence</th><th>Notes</th><th>Input by:</th></tr>
                {hrows or '<tr><td colspan=5>Nothing recorded yet.</td></tr>'}</table>
                <form method=post action="/compliance/item/delete" style="margin-top:8px">
                  <input type=hidden name=eqc_id value="{eid}">
                  <button>Remove Check</button>
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
                   f"next due {html.escape(fmt_date(focused['next_due_live'], '—'))}, "
                   f"last done {html.escape(fmt_date(focused['last_done'], '—'))}.</p>")
        fixit = self._fixit_form(con, aid, focused, today) if focused else ""
        # Build 'ae' rebuild (Phase 4): ONE Print menu for the full
        # pack — the four standalone print controls and the tick-box
        # selective-print machinery are gone (selection printing
        # lives in the Paperwork popup, whose menu carries it).
        pmenu = self._print_menu(
            f"/print/compliance/{html.escape(aid)}",
            f"/print/compliance/{html.escape(aid)}.pdf")
        return f"""
        <h1>Compliance · {html.escape(a['unit_no'])}</h1>
        <p class="hint">{html.escape(a['description'] or '')} — {badge} ({summ['total']} checks).
        <a href="/unit/{html.escape(aid)}">Back to Unit</a></p>
        {why}
        {fixit}
        <p class="actions">
          {pmenu}
        </p>
        <p class="actions">
          <button type="button" class="vbtn" data-audit="/unit/paperwork?unit={html.escape(aid, quote=True)}" data-title="Paperwork — {html.escape(a['unit_no'])}">Paperwork</button>
        </p>
        <h2>Assign a Pack</h2>
        {assign}
        <h2>Add Check</h2>
        <form method=post action="/compliance/custom">
          <input type=hidden name=asset_id value="{html.escape(aid)}">
          <label>Check Name</label><input name=name required placeholder="e.g. Yard function test">
          <label>Trigger</label><select name=trigger>{_trigger_opts('per_job')}</select>
          <div class="row">
            <div><label>Interval (Months)</label><input name=interval_months placeholder="calendar only"></div>
            <div><label>Deployed Backstop (Months)</label><input name=backstop_months placeholder="required for per-job / manufacturer"></div>
          </div>
          <label>Notes</label><input name=notes>
          <p><button>Add Check</button></p>
        </form>
        <h2>Checklist</h2>
        <table><tr><th>Check</th><th>Trigger</th><th>Interval</th><th>Backstop</th><th>Last done</th><th>Next due</th><th>Status</th><th>Who</th><th></th></tr>
        {''.join(rows) or '<tr><td colspan=9>No checks yet — assign a pack or add one.</td></tr>'}</table>
        {self._cert_section(con, aid)}
        """

    def _cert_asset(self, con, cert_id):
        try:
            cid = int(cert_id)
        except (TypeError, ValueError):
            return ""
        r = con.execute("SELECT asset_id FROM asset_certs WHERE cert_id=?",
                        (cid,)).fetchone()
        # Build 'v': the column holds the engine key; routes address
        # the unit by its code.
        return engine.asset_code(con, r["asset_id"]) if r else ""

    def _cert_status_chip(self, status):
        if status == "expired":
            return "<b class='fail'>expired</b>"
        if status == "valid":
            return "<b class='ok'>valid</b>"
        if status == "superseded":
            return "<span class='hint'>superseded</span>"
        return "<span class='hint'>no expiry</span>"

    def _cert_section(self, con, aid):
        """Certifications, calibrations, and function tests — every
        record names this unit. Evidence paperwork attaches to the
        record itself. (Restored in build 'v': the section and its
        /compliance/cert/* posts predate the 'l' tree in the product's
        other line; the engine records never left.)"""
        certs = engine.list_certs(con, aid)
        kind_vals = engine.lookups(con, "cert_kind")
        kind_opts = "".join(
            f"<option value='{html.escape(k)}'>{html.escape(k)}</option>"
            for k in kind_vals)
        docs = con.execute(
            "SELECT doc_id, title, filename FROM unit_docs "
            "WHERE asset_id=? ORDER BY doc_id",
            (engine.asset_key(con, aid),)).fetchall()
        cards = []
        for c in certs:
            cid = c["cert_id"]
            if c.get("evidence_doc_id"):
                ev = (f"<a href='/doc/{c['evidence_doc_id']}'>"
                      f"{html.escape(c['doc_title'] or c['doc_filename'] or 'document')}</a>")
            else:
                ev = "<span class='hint'>none attached</span>"
            if not c["superseded"]:
                sup_btn = f"""
                    <form method=post action="/compliance/cert/supersede" style="display:inline">
                      <input type=hidden name=cert_id value="{cid}">
                      <button class="secondary">Mark Superseded</button>
                    </form>"""
            else:
                sup_btn = f"""
                    <form method=post action="/compliance/cert/supersede" style="display:inline">
                      <input type=hidden name=cert_id value="{cid}">
                      <input type=hidden name=restore value="1">
                      <button class="secondary">Restore</button>
                    </form>"""
            doc_combo_opts = [(str(d["doc_id"]),
                               str(d["title"] or d["filename"] or d["doc_id"]),
                               str(d["doc_id"])) for d in docs]
            doc_combo = (
                combo_field(f"f_doc_{cid}", "doc_id_text", doc_combo_opts,
                            label="Attach evidence",
                            placeholder="Type to search documents…")
                + f'<input type=hidden id="f_doc_{cid}_id" name=doc_id value="">'
            )
            cur_kind = c['kind'] if c['kind'] in kind_vals else c['kind_label']
            sel_vals = list(kind_vals)
            if cur_kind not in sel_vals:
                sel_vals.insert(0, cur_kind)
            kind_sel = "".join(
                f"<option value='{html.escape(k)}'{' selected' if cur_kind == k else ''}>{html.escape(k)}</option>"
                for k in sel_vals)
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
                  <div><label>Kind</label><select name=kind class="w-sm">{kind_sel}</select></div>
                </div>
                <div class="row">
                  <div><label>Certificate #</label><input name=cert_number value="{html.escape(c['cert_number'] or '')}"></div>
                  <div><label>Issuer</label><input name=issuer value="{html.escape(c['issuer'] or '')}"></div>
                </div>
                <div class="row">
                  <div><label>Issued</label><input type=date class="w-sm" name=issued_date value="{html.escape(c['issued_date'] or '')}"></div>
                  <div><label>Expires</label><input type=date class="w-sm" name=expiry_date value="{html.escape(c['expiry_date'] or '')}"></div>
                </div>
                <label>Notes</label><input name=notes value="{html.escape(c['notes'] or '')}">
                <p><button>Save</button>
                {sup_btn}
                </p>
              </form>
              <form method=post action="/compliance/cert/evidence" class="actions">
                <input type=hidden name=cert_id value="{cid}">
                <div class="row">
                  <div>{doc_combo}</div>
                  <div style="align-self:end"><button>Attach</button></div>
                </div>
              </form>
              <form method=post action="/compliance/cert/delete">
                <input type=hidden name=cert_id value="{cid}">
                <button class="secondary">Delete Record</button>
              </form>
            </details>""")
        return f"""
        <h2>Certifications &amp; Calibrations</h2>
        <details style="margin:8px 0"><summary><b>Add a Certificate Record</b></summary>
        <form method=post action="/compliance/cert/save" enctype="multipart/form-data" style="margin-top:8px">
          <input type=hidden name=asset_id value="{html.escape(aid)}">
          <div class="row">
            <div><label>Title *</label><input name=title required maxlength=120
              placeholder="e.g. DNV recertification"></div>
            <div><label>Kind</label><select name=kind class="w-sm">{kind_opts}</select></div>
          </div>
          <div class="row">
            <div><label>Certificate #</label><input name=cert_number maxlength=60></div>
            <div><label>Issuer</label><input name=issuer maxlength=120 placeholder="e.g. DNV, shop lab"></div>
          </div>
          <div class="row">
            <div><label>Issued</label><input type=date class="w-sm" name=issued_date value="{date.today().isoformat()}"></div>
            <div><label>Expires</label><input type=date class="w-sm" name=expiry_date></div>
          </div>
          <label>Evidence File</label><input type=file name=doc_file>
          <label>Notes</label><input name=notes>
          <p><button>Add Certificate</button></p>
        </form>
        </details>
        {''.join(cards) or '<p class="hint">No cert records yet — migrated expiries land here too.</p>'}
        """
        """Unit paperwork print (build 'o', Jason 2026-10-24): "make a
        toggle popup on a unit that shows what paperwork is attached
        to that unit and they can toggle on or off which ones they
        want and click a normal print button - print or print to
        screen or print to location."

        What the record model attaches to a unit is exactly what the
        compliance pack assembles: the checklist items, the
        certification records, and the data book documents
        (unit_docs). Each stands here with a toggle, default on; the
        print action is the standard three-choice menu, aimed at the
        selective pack route carrying the ticked set (c / d / r), so
        the selected set prints as one job. The menu that leads to
        the full pack is untouched — the default Print behavior does
        not change anywhere. Ticket-side files (job attachments and
        condition photos) are NOT listed: the model files them
        against the ticket and offers no read path into a pack (see
        PHASEO-REPORT.md).

        Rendered through the popup shell (?frag=1) from the unit
        page and the unit compliance page; the same view answers
        the full page. The toggle form is a plain GET form — ticking
        a box resubmits and the menu below is rebuilt for the ticked
        set — so it works inside the fragment, which carries no
        script bundle; PRINTMENU_JS rides along in that case only,
        to work the menu's Print to Location choice.
        """
        q = q or {}
        aid = q.get("unit") or ""
        a = con.execute("SELECT * FROM assets WHERE asset_id=?",
                        (aid,)).fetchone()
        if not a:
            return '<div class="err">Unknown unit.</div>'
        in_frag = q.get("frag") == "1"

        submitted = q.get("set") == "1"

        def _picked(name):
            # First open (no set marker): the default — everything
            # on (None). A form submission (set=1) states its ticked
            # ids exactly; an unticked group submits nothing at all,
            # so an absent name then means none ticked, never the
            # default.
            if name not in q:
                return set() if submitted else None
            out = set()
            for part in str(q.get(name) or "").split(","):
                part = part.strip()
                if part.isdigit():
                    out.add(int(part))
            return out

        pick_c = _picked("c")
        pick_d = _picked("d")
        pick_r = _picked("r")
        checks = engine.unit_checklist(con, aid)
        certs = engine.list_certs(con, aid)
        docs = engine.list_unit_docs(con, aid)

        def _rows(kind, entries, name_of, meta_of):
            if not entries:
                return (f"<p class='mute'>None on file.</p>")
            out = []
            for e in entries:
                eid = int(e[kind[1]])
                on = (kind[2] is None or eid in kind[2])
                out.append(
                    f"<div class='todo'><label>"
                    f"<input type=checkbox name={kind[0]} value={eid}"
                    f"{' checked' if on else ''} onchange='this.form.submit()'> "
                    f"{html.escape(name_of(e))}</label> "
                    f"<span class='mute'>{html.escape(meta_of(e))}</span></div>")
            return "".join(out)

        checks_html = _rows(
            ("c", "eqc_id", pick_c), checks,
            lambda it: it["display_name"],
            lambda it: f"{it['status']} · next due {fmt_date(it['next_due_live'], '—')}")
        certs_html = _rows(
            ("r", "cert_id", pick_r), certs,
            lambda c: c.get("title") or c["kind_label"],
            lambda c: f"{c['kind_label']} · exp {fmt_date(c.get('expiry_date'), '—')} · {c.get('status', '')}")
        docs_html = _rows(
            ("d", "doc_id", pick_d), docs,
            lambda d: d["title"] or d["filename"],
            lambda d: f"{engine.DOC_KINDS.get(d['kind'], d['kind'])} · {d['filename']}")

        sel_c = [int(it["eqc_id"]) for it in checks
                 if pick_c is None or int(it["eqc_id"]) in pick_c]
        sel_r = [int(c["cert_id"]) for c in certs
                 if pick_r is None or int(c["cert_id"]) in pick_r]
        sel_d = [int(d["doc_id"]) for d in docs
                 if pick_d is None or int(d["doc_id"]) in pick_d]
        if sel_c or sel_r or sel_d:
            parts = []
            if sel_c:
                parts.append("c=" + ",".join(str(i) for i in sel_c))
            if sel_d:
                parts.append("d=" + ",".join(str(i) for i in sel_d))
            if sel_r:
                parts.append("r=" + ",".join(str(i) for i in sel_r))
            qs = "?" + "&".join(parts)
            menu = self._print_menu(
                f"/print/compliance/{html.escape(aid, quote=True)}/sel{qs}",
                f"/print/compliance/{html.escape(aid, quote=True)}/sel.pdf{qs}")
            menu_block = (f"<p class='actions' style='margin-top:14px'>"
                          f"{menu}</p>")
        elif checks or certs or docs:
            menu_block = "<p class='hint' style='margin-top:14px'>Nothing ticked.</p>"
        else:
            menu_block = ""
        frag_field = ('<input type=hidden name=frag value=1>'
                      if in_frag else "")
        return f"""
        <h1>Paperwork · {html.escape(a['unit_no'])}</h1>
        <p class="hint">{html.escape(a['description'] or '')} — ticked items print as one job.
        <a href="/unit/{html.escape(aid, quote=True)}">Back to Unit</a></p>
        <form method=get action="/unit/paperwork" target="_self">
          <input type=hidden name=unit value="{html.escape(aid, quote=True)}">
          <input type=hidden name=set value=1>
          {frag_field}
          <h2 style="font-size:16px;color:var(--frame)">Checks</h2>
          {checks_html}
          <h2 style="font-size:16px;color:var(--frame)">Certifications</h2>
          {certs_html}
          <h2 style="font-size:16px;color:var(--frame)">Documents</h2>
          {docs_html}
        </form>
        {menu_block}
        {PRINTMENU_JS if in_frag else ''}
        """
