from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import html
import json
import re
from datetime import date, timedelta
from urllib.parse import parse_qs, quote, quote_plus, urlparse

import engine
from views_core import task_nudge, _task_from_row, ticker_details, chain_banner, chain_banner_rerun

"""FleetSheet views — assets flow: units, sites, tickets, work orders."""

from views_core import (
    page,
    tabs,
    tabs_boards,
    weekly_tabs,
    tabs_admin,
    tabs_invoice,
    tabs_quotes,
    tabs_money,
    _cstat,
    _trigger_opts,
    lookup_select,
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
    news_strip,
    _ack_forms,
    combo_field,
    combo_opts,
    state_field,
    capped_table,
    fmt_date,
    fmt_datetime,
    enabled_values,
    CoreViews,)


def _empty_action(title, detail, href, label):
    return (f"<div class='empty-action'><strong>{html.escape(title)}</strong>"
            f"<p>{html.escape(detail)}</p><a class='btn' href='{html.escape(href, quote=True)}'>{html.escape(label)} →</a></div>")


class AssetViews(CoreViews):
    """FleetSheet views views mixed into Handler."""

    def _job_info_popup(self, pid, vals=None, extra=""):
        """Universal job info popup — duplicated from CoreViews for standalone use."""
        from views_core import CoreViews
        return CoreViews._job_info_popup(self, pid, vals, extra)

    def _btn_row(self, save_label="Save", jobpop=None, add_item=False, extra="",
                 submit_name="", submit_value="", print_menu=None):
        from views_core import CoreViews
        return CoreViews._btn_row(self, save_label, jobpop, add_item, extra,
                                  submit_name, submit_value, print_menu)

    def _top_commit(self, label, name="", value=""):
        from views_core import CoreViews
        return CoreViews._top_commit(self, label, name, value)
    def _ticket_kind_bar(self, con, kind):
        # Shop flow (Jason, 2026-10-21): a module switched OFF loses its
        # kind-bar entries — surfaces only; the routes stay live. Sale
        # and Assets always ride. Change Order hangs off rentals.
        # Strip order (Jason, 2026-10-25, build 'v'): Sale, Rental,
        # Quote, Work Order, Change Order, Check In/Out — the Change
        # Order is the last of the money forms; Assets stays far right.
        _entries = (("sale", "Sale", True),
                    ("rental", "Rental", engine.module_on(con, "rentals")),
                    ("quote", "Quote", engine.module_on(con, "quotes")),
                    ("workorder", "Work Order", engine.module_on(con, "work_orders")),
                    ("change", "Change Order", engine.module_on(con, "rentals")),
                    ("checkinout", "Check In/Out", engine.module_on(con, "rentals")))
        tabs = "".join(
            f'<a class="{"on" if k == kind else ""}" href="/ticket/new?kind={k}">{lab}</a>'
            for k, lab, on in _entries if on)
        # Assets rides at the right end of the Equipment subheader row
        # (tweak round 2026-10-20, Jason): it is part of Equipment now —
        # no header tab of its own — and it sits apart from the
        # day-to-day action subheaders because adding/removing iron is
        # the occasional job, not the daily one.
        assets_link = (f'<span class="tabright"><a class="{"on" if kind == "assets" else ""}" '
                       f'href="/assets">Assets</a></span>')
        return f'<div class="tabs">{tabs}{assets_link}</div>'

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
        # Discovery-nudge bookkeeping (shop-flow, Jason 2026-10-21):
        # opening a module's home kind stamps the module seen today.
        _seen_mod = {"rental": "rentals", "checkinout": "rentals",
                     "change": "rentals", "quote": "quotes",
                     "workorder": "work_orders"}.get(kind)
        if _seen_mod:
            engine.stamp_module_seen(con, _seen_mod)
        # PO soft-reserve conflict: name the stakes, operator picks the winner.
        sc = ((q or {}).get("soft_conflict") or "").strip()
        if sc:
            return self._soft_conflict_page(con, sc)
        bar = self._ticket_kind_bar(con, kind)
        # Done Today lives on the Today page only (Jason 2026-10-24).
        # Universal View row (build 'r', Jason 2026-10-25): every
        # sub-tab form page ends with the View button, bottom left.
        # Sale and (non-bare) Work Order forms render their own row;
        # the shell adds it here for the kinds whose form is bare.
        if kind == "change":
            done = self._view_door("/changes/all", "Change orders — audit")
        elif kind == "quote":
            done = self._view_door("/quotes/all", "Quotes")
        elif kind == "workorder":
            done = self._view_door("/wos/all", "Work Orders")
        elif kind in ("rental", "checkinout"):
            done = self._view_door("/tickets", "Rental Tickets")
        else:
            done = ""
        if kind == "sale":
            body = self.view_sale(con, None)
            # view_sale returns full page; extract just the form portion for sub-tab
            return bar + body + self._rentals_done(con, "sale", "Sale") + done
        if kind == "quote":
            body = self.view_quote_form(con, None, bare=True)
            return bar + body + self._rentals_done(con, "quote", "Quote") + done
        if kind == "change":
            body = self.view_changes(con, {"co_no": (q or {}).get("co_no", "")}, bare=True)
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
        # Pending format (2026-10-16): {"tickets": [...], "conflict": i} for
        # multi-row bookings; a bare ticket dict for older single-row rows.
        if isinstance(booking, dict) and "tickets" in booking:
            ticket_dicts = booking["tickets"]
            conflict_row = ticket_dicts[booking.get("conflict", 0)]
        else:
            ticket_dicts = [booking]
            conflict_row = booking
        soft = con.execute(
            """SELECT t.ticket_id, t.job_name, t.well_or_pad, t.po, t.on_rent, t.off_rent,
                      c.account_name, a.unit_no
               FROM tickets t
               LEFT JOIN customers c ON c.id = t.customer_id
               LEFT JOIN assets a ON a.id = t.asset_id
               WHERE t.id=?""", (prow["soft_ticket_id"],)).fetchone()
        new_cust = con.execute("SELECT account_name FROM customers WHERE customer_id=?",
                               (conflict_row.get("customer_id"),)).fetchone()
        new_unit = con.execute("SELECT unit_no FROM assets WHERE asset_id=?",
                               (conflict_row.get("asset_id"),)).fetchone()

        def stakes_row(job, cust_name, unit_no, po, on_rent, off_rent):
            dates = fmt_date(on_rent, "?") + ((" → " + fmt_date(off_rent)) if off_rent else "")
            po_txt = f", PO {po}" if po else ""
            return (f"<b>{html.escape(unit_no or '?')}</b> — "
                    f"<b>{html.escape(job or '—')}</b>, {html.escape(cust_name or '?')}"
                    f"{po_txt}, {html.escape(dates)}")

        soft_job = soft["job_name"] or soft["well_or_pad"] or "—"
        new_job = conflict_row.get("job_name") or conflict_row.get("well_or_pad") or "—"
        multi_note = (f"<p class='hint'>{len(ticket_dicts)} units — "
                      "new job: all · keep existing: none.</p>"
                      if len(ticket_dicts) > 1 else "")
        body = f"""
        <h1>Which Reservation Wins?</h1>
        <div class='card' style='border-left:4px solid var(--gold)'>
          <p><b>Existing Soft Reservation</b> (Rental Ticket {html.escape(soft['ticket_id'])}):<br>
          {stakes_row(soft_job, soft['account_name'], soft['unit_no'], soft['po'], soft['on_rent'], soft['off_rent'])}</p>
          <p><b>New Booking:</b><br>
          {stakes_row(new_job, new_cust['account_name'] if new_cust else None,
                      new_unit['unit_no'] if new_unit else None, conflict_row.get('po'),
                      conflict_row.get('on_rent'), conflict_row.get('off_rent'))}</p>
          {multi_note}
          <p class='hint'>PO soft-reserve — no block.</p>
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
               FROM tickets t JOIN assets a ON a.id = t.asset_id JOIN customers c ON c.id = t.customer_id
               WHERE t.status IN ('Dispatched','On Rent') ORDER BY t.on_rent DESC LIMIT 6""").fetchall()
        in_yard = con.execute(
            """SELECT t.ticket_id, a.unit_no, a.asset_id, c.account_name, t.status
               FROM tickets t JOIN assets a ON a.id = t.asset_id JOIN customers c ON c.id = t.customer_id
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
            <div><label>Unit / Asset</label><input id="cio_pick" placeholder="Search or pick a unit below…" readonly><input type=hidden id=cio_tid name=ticket_id required></div>
            <div><label>Movement</label><select name=direction id=cio_dir class=w-sm><option value="in">Check in</option><option value="out">Check Out</option></select></div>
          </div>
          <div class="row">
            <div><label>Condition</label><select name=condition required class=w-sm><option value="">Select Condition</option>{''.join('<option>'+html.escape(c)+'</option>' for c in conds)}</select></div>
            <div><label>Meter / Hours / Fuel</label><input name=meter></div>
          </div>
          <div class="row"><div><label>Note</label><input name=note placeholder="Damage, exception, arrival detail…"></div></div>
          <p style="margin:4px 0 0"><label><input type=checkbox name=proceed value=1>
          Proceed anyway — check out, FIT not PASS.</label></p>
          {self._btn_row("Save", "ciojobpop", add_item=False)}
          {self._job_info_popup('ciojobpop')}
        </form>
        <div class="row">
          <div><h2>Out Now — Ready to Check in</h2>{out_rows or "<p class='hint'>Nothing out.</p>"}{out_more}</div>
          <div><h2>Reserved — Ready to Check Out</h2>{in_rows or "<p class='hint'>Nothing reserved.</p>"}{in_more}</div>
        </div>
        <script>document.querySelectorAll('.cio-pick').forEach(function(a){{a.addEventListener('click',function(e){{e.preventDefault();document.getElementById('cio_tid').value=a.dataset.tid;document.getElementById('cio_pick').value=a.dataset.label;document.getElementById('cio_dir').value=a.dataset.dir;document.getElementById('cioform').scrollIntoView({{behavior:'smooth',block:'start'}});}});}});</script>
        """

    def _new_ticket_form_data(self, con):
        # Data for the new-rental-ticket form: options, rates, ticket #.
        # Returns None when no rentable equipment exists yet.
        cust = con.execute("SELECT customer_id, account_name FROM customers ORDER BY account_name").fetchall()
        # only assets not blocking
        assets = con.execute(
            """SELECT a.asset_id, a.unit_no || ' · ' || COALESCE(a.description,'') AS label,
                      COALESCE(a.rate_unit,'Day') AS rate_unit, COALESCE(a.rate_value,0) AS rate_value
               FROM assets a WHERE a.active=1
               AND COALESCE(a.designation,'Fleet') NOT IN ('Plant','Stock')
               AND COALESCE(a.status,'Active')='Active'
               AND a.asset_id NOT IN (
                 SELECT asset_id FROM tickets WHERE status IN ('Reserved','Dispatched','On Rent','Standby')
               ) ORDER BY a.unit_no"""
        ).fetchall()
        unit_rates = {a["asset_id"]: [a["rate_unit"], float(a["rate_value"] or 0)] for a in assets}
        cust_opts, _ = combo_opts(cust, "customer_id", "account_name", "")
        unit_opts, _ = combo_opts(assets, "asset_id", "label", "")
        today = date.today().isoformat()
        if not assets:
            return None
        haul_combo = combo_field(
            "f_haul", "haul_text",
            [("customer", engine.HAUL_LABELS["customer"], "customer"),
             ("we", engine.HAUL_LABELS["we"], "we")],
            value=engine.HAUL_LABELS["we"], label="Transport",
            placeholder="Company, customer, or type a hauler…")
        deliver_combo = combo_field(
            "f_deliver", "deliver_text",
            [(d, engine.DELIVER_LABELS[d], d) for d in ("job_site", "our_yard", "customer_yard", "dock")],
            value=engine.DELIVER_LABELS["job_site"], label="Deliver to",
            placeholder="Job site, yard, or type…")
        # Preview ticket number (peek, don't burn — Batch 3 #14: the
        # operator may overwrite it at creation; save validates it).
        ticket_no = engine.peek_next_ticket_no(con)
        return {
            "cust_opts": cust_opts,
            "unit_opts": unit_opts,
            "unit_rates": unit_rates,
            "today": today,
            "ticket_no": ticket_no,
            "haul_combo": haul_combo,
            "deliver_combo": deliver_combo,
        }

    def _new_ticket_form_script(self, unit_rates):
        # Client-side JS for the new-rental-ticket form.
        return f"""
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
          // and return the picked unit's id ('' when hand-typed). Row-scoped
          // (name prefixes), so cloned rows resolve their own unit.
          function rowUnitId(row){{
            var inp = row.querySelector('input[data-combo]');
            if (!inp) return '';
            var dl = document.getElementById(inp.getAttribute('list'));
            var t = inp.value.trim(), id = '';
            if (dl) Array.prototype.forEach.call(dl.options, function(o){{
              if (o.value.trim() === t) id = o.getAttribute('data-id') || '';
            }});
            var hid = row.querySelector('input[type=hidden][name^="asset_id"]');
            var hfree = row.querySelector('input[type=hidden][name^="item_text"]');
            if (hid) hid.value = id;
            if (hfree) hfree.value = id ? '' : t;
            return id;
          }}
          // Rate sync for one line-item row: the unit's rate type shows as a
          // tag behind Qty, its rate value fills Rate $, and the hidden
          // rate_type carries the unit's rate unit to the POST. The Unit
          // select shows the same rate in inv_uom words (Day→Days, …);
          // Special/Standby/Yard have no inv_uom word, so Unit shows Each
          // and the original rate_type is stashed on the select — a manual
          // Unit change back to Each restores it, never silently re-rates
          // a special unit to Day.
          var RATE_TO_UOM = {{Day:'Days', Week:'Weeks', Monthly:'Months', Hour:'Hours'}};
          var UOM_TO_RATE = {{Days:'Day', Weeks:'Week', Months:'Monthly', Hours:'Hour'}};
          function syncRowRate(row, fromUnit){{
            var r = UR[rowUnitId(row)];
            var tag = row.querySelector('.ratetype-tag');
            var rv = row.querySelector('input.line-rate');
            var rt = row.querySelector('input.line-ratetype');
            var uom = row.querySelector('select.line-uom');
            if (tag) tag.textContent = r ? r[0] : '';
            if (rt && r) rt.value = r[0];
            if (fromUnit && r && rv) rv.value = r[1].toFixed(2);
            if (uom){{
              uom.value = (r && RATE_TO_UOM[r[0]]) ? RATE_TO_UOM[r[0]] : 'Each';
              uom.dataset.origRateType = r ? r[0] : 'Day';
            }}
          }}
          // A manual Unit change re-rates the ticket; Each restores the
          // unit's own rate type (stashed by syncRowRate).
          function onUomChange(row){{
            var uom = row.querySelector('select.line-uom');
            var rt = row.querySelector('input.line-ratetype');
            var tag = row.querySelector('.ratetype-tag');
            if (!uom) return;
            var val = UOM_TO_RATE[uom.value] || uom.dataset.origRateType || 'Day';
            if (rt) rt.value = val;
            if (tag) tag.textContent = val;
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
          // A row counts as filled when it names a unit, carries typed
          // text, a description, or a nonzero rate — same rule the
          // backend uses to skip untouched rows.
          function rowHasContent(row){{
            if (rowUnitId(row)) return true;
            var inp = row.querySelector('input[data-combo]');
            if (inp && inp.value.trim()) return true;
            var desc = row.querySelector('input[name^="item_desc"]');
            if (desc && desc.value.trim()) return true;
            var rate = row.querySelector('input.line-rate');
            if (rate && (parseFloat(rate.value) || 0)) return true;
            return false;
          }}
          function loadDraft(){{
            var d = null;
            try {{ d = JSON.parse(localStorage.getItem(DK) || 'null'); }} catch(e){{}}
            if (!d) return false;
            // Rebuild cloned rows the draft references (asset_id1, ...) so
            // a multi-row draft restores every row, not just row 0.
            var maxIdx = 0;
            Object.keys(d).forEach(function(k){{
              var m = k.match(/^(asset_id|item_desc|qty|uom|rate_value|rate_type|unit_text|item_text)(\\d+)$/);
              if (m) maxIdx = Math.max(maxIdx, parseInt(m[2], 10));
            }});
            while (form.querySelectorAll('.lineitem-row').length <= maxIdx) {{
              if (!addRow(true)) break;
            }}
            Array.prototype.forEach.call(form.elements, function(el){{
              if (!el.name || !(el.name in d)) return;
              if (el.type === 'checkbox') el.checked = !!d[el.name];
              else el.value = d[el.name];
            }});
            return true;
          }}
          function upd(){{
            var sum = document.getElementById('ticketsum');
            var rows = form.querySelectorAll('.lineitem-row');
            var uinp = rows[0] && rows[0].querySelector('input[data-combo]');
            var c = ctxt('f_customer'), u = uinp ? uinp.value.trim() : '';
            var extra = 0;
            for (var i = 1; i < rows.length; i++) {{ if (rowHasContent(rows[i])) extra++; }}
            var tail = extra ? (' (+' + extra + ' more unit' + (extra > 1 ? 's' : '') + ')') : '';
            sum.textContent = (c && u) ? ('Rental Ticket: ' + c + ' → ' + u + tail) : '';
            sum.hidden = !sum.textContent;
          }}
          // Add Item (2026-10-16): clone the last line row, renumber names
          // + ids to the next index, clear values. Capped at 8 rows: the
          // backend reads rows 0..7, so a 9th row would silently drop.
          function addRow(silent){{
            var rows = form.querySelectorAll('.lineitem-row');
            if (rows.length >= 8) return null;
            var n = rows.length;
            var c = rows[rows.length - 1].cloneNode(true);
            c.querySelectorAll('[name]').forEach(function(el){{
              el.name = el.name.replace(/\\d+$/, '') + n;
            }});
            c.querySelectorAll('select[data-field]').forEach(function(el){{ el.dataset.field = el.name; }});
            c.querySelectorAll('[id]').forEach(function(el){{
              el.id = el.id.replace(/\\d+$/, '') + n;
            }});
            var vis = c.querySelector('input[data-combo]');
            if (vis && vis.hasAttribute('list')) {{
              vis.setAttribute('list', vis.getAttribute('list').replace(/\\d+$/, '') + n);
            }}
            c.querySelectorAll('input').forEach(function(el){{
              if (el.type === 'hidden') el.value = '';
              else if (el.name && el.name.indexOf('qty') === 0) el.value = '1';
              else if (el.classList.contains('line-rate')) el.value = '';
              else el.value = '';
            }});
            c.querySelectorAll('select').forEach(function(el){{ el.selectedIndex = 0; }});
            var tag = c.querySelector('.ratetype-tag');
            if (tag) tag.textContent = '';
            // The clone copies the lookup widget's mode (Other/-Add- inputs
            // if the source row was mid-Other/-Add-) — reset to plain list.
            c.querySelectorAll('[data-lookup-input]').forEach(function(el){{
              el.hidden = true; el.disabled = true; el.value = '';
              el.removeAttribute('name'); el.dataset.mode = 'list';
            }});
            c.querySelectorAll('[data-lookup-add],[data-lookup-list]').forEach(function(el){{ el.hidden = true; }});
            c.querySelectorAll('select[data-lookup]').forEach(function(el){{
              el.hidden = false; el.disabled = false;
            }});
            var last = rows[rows.length - 1];
            last.parentNode.insertBefore(c, last.nextSibling);
            syncRowRate(c, true);
            if (!silent && vis) {{ try {{ vis.focus(); }} catch (e) {{}} }}
            upd();
            return c;
          }}
          var addBtn = null;
          form.querySelectorAll('button[type=button]').forEach(function(b){{
            if (b.textContent.trim().toLowerCase() === 'add item') addBtn = b;
          }});
          if (addBtn) addBtn.addEventListener('click', function(){{ addRow(false); }});
          var fCust = document.getElementById('f_customer');
          if (fCust) {{
            fCust.addEventListener('change', upd);
            fCust.addEventListener('input', upd);
          }}
          // Delegated row listeners: cloned rows rate-sync and validate
          // exactly like row 0, with no per-row binding to forget.
          form.addEventListener('change', function(e){{
            var row = e.target.closest ? e.target.closest('.lineitem-row') : null;
            if (row) {{
              if (e.target.classList && e.target.classList.contains('line-uom')) onUomChange(row);
              else if (e.target.hasAttribute && e.target.hasAttribute('data-combo')) {{ syncRowRate(row, true); upd(); }}
            }}
            saveDraft();
          }});
          // Name the missing field instead of a bare browser bubble.
          form.setAttribute('novalidate', '');
          var msg = document.getElementById('formerr');
          form.addEventListener('submit', function(e){{
            // Customer and every filled row's Item must resolve to real records.
            var bad = null, badLab = null;
            if (!ctxt('f_customer')) {{
              bad = document.getElementById('f_customer');
              badLab = 'Customer — pick one from the list';
            }} else {{
              var rows = form.querySelectorAll('.lineitem-row');
              var seen = {{}};
              var anyRow = false;
              for (var ri = 0; ri < rows.length; ri++) {{
                var row = rows[ri];
                var id = rowUnitId(row);
                if (!rowHasContent(row)) continue;
                anyRow = true;
                if (!id) {{
                  bad = row.querySelector('input[data-combo]');
                  badLab = 'Item — pick a unit from the list';
                  break;
                }}
                if (seen[id]) {{
                  bad = row.querySelector('input[data-combo]');
                  badLab = 'Item — that unit is already on this Rental Ticket';
                  break;
                }}
                seen[id] = true;
              }}
              if (!bad && !anyRow) {{
                bad = document.getElementById('f_unit');
                badLab = 'Item — pick a unit from the list';
              }}
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
            var row = e.target.closest ? e.target.closest('.lineitem-row') : null;
            if (row && e.target.hasAttribute && e.target.hasAttribute('data-combo')) {{ syncRowRate(row, true); upd(); }}
            saveDraft();
          }});
          var hadDraft = loadDraft(); upd();
          document.querySelectorAll('.lineitem-row').forEach(function(r){{
            if (hadDraft) {{
              // The draft already holds the rate + unit; refresh only the
              // rate-type tag so a drafted manual rate is never clobbered.
              var tag = r.querySelector('.ratetype-tag');
              if (tag) {{
                var rr = UR[rowUnitId(r)];
                tag.textContent = rr ? rr[0] : ((r.querySelector('input.line-ratetype') || {{}}).value || '');
              }}
            }} else {{
              syncRowRate(r, true);
            }}
          }});
        }})();
        </script>
        """

    def _new_ticket_delivery(self, con, q=None):
        data = self._new_ticket_form_data(con)
        if data is None:
            return _empty_action('No rentable equipment yet', 'No rentable equipment.', '/unit/new', 'Add equipment')
        cust_opts = data["cust_opts"]
        unit_opts = data["unit_opts"]
        unit_rates = data["unit_rates"]
        today = data["today"]
        ticket_no = data["ticket_no"]
        haul_combo = data["haul_combo"]
        deliver_combo = data["deliver_combo"]
        uom_opts = lookup_select(con, "inv_uom", "uom", extra='id="f_unit_uom"', css="line-uom",
                                 vals=enabled_values(con, "inv_uom"),
                                 add_option=False)  # editors: enabled set only (Spec 7)
        # Charge lines on the booking form: REMOVED (build 's',
        # Jason 2026-10-25). Charges on tickets end as a capability —
        # a freight or extra charge is a line item on the invoice,
        # typed there with its description and its own Tax flag.
        # Nothing on this form writes ticket_lines anymore.
        # Header zone (build 'r', Jason 2026-10-25, facelift item 4;
        # two-row form build 't', same day, universal form law):
        # Company block, Ticket # + Date, bar, Customer left, Job
        # Info box right, lines. Reference Ticket lives in the Job
        # Info popup (same name; the booking save reads ref_ticket
        # from the posted form). Build 't': On-Rent, Off-Rent Est,
        # Transport, Deliver to, and Upload move into the Job Info
        # popup too (route (b) — the ticket's dates and transport
        # are ticket data, the same home build 's' gave them on the
        # ticket page); below the lines only Notes remains. The live
        # ticket summary strip moves below the line rows (the
        # totals zone) and stays hidden while empty, so the line
        # band starts where every other form's starts.
        _tk_cust = (combo_field("f_customer", "customer_text", cust_opts, value="", label="Customer", required=True, placeholder="Type to search customers…")
                    + '<input type=hidden id="f_customer_id" name=customer_id value="">')
        _tk_extra = ('<div class="row"><div><label>Reference Ticket</label>'
                     '<input name=ref_ticket class=w-sm placeholder="Optional"></div>'
                     f'<div><label>On-Rent</label><input type=date name=on_rent value="{today}" required data-label="On-rent date" class=w-sm></div>'
                     '<div><label>Off-Rent Est</label><input type=date name=off_rent_est class=w-sm></div></div>'
                     f'<div class="row"><div>{haul_combo}</div>'
                     f'<div>{deliver_combo}</div></div>'
                     '<div><label>Upload</label><input type=file name=ticket_upload></div>')
        _tk_job_lines = [("PO #", ""), ("Job Name", ""), ("Well #", "")]
        _tk_doc = f'Rental Ticket # <input name=ticket_id value="{ticket_no}" class=w-xs>'
        _tk_date = f'<label>Date</label> <input type=date name=ticket_date value="{today}" class=w-sm>'
        return f"""
        <div id="formerr" role="alert"></div>
        <form method=post action="/ticket/new" id="ticketform" enctype="multipart/form-data">

          {self._form_head(con, _tk_doc, _tk_date, _tk_cust, _tk_job_lines)}
          <fieldset>
          {self._line_head()}
          <div class="lineitem-row" style="display:grid;grid-template-columns:104px 1fr 2fr 84px 104px 104px;gap:8px;align-items:start">
            <div><label>Type</label><select disabled><option selected>Rental</option></select></div>
            <div>{combo_field("f_unit", "unit_text", unit_opts, value="", label="Item", required=True, placeholder="Type to search units…")}
            <input type=hidden id="f_unit_id" name=asset_id value="">
            <input type=hidden id="f_unit_free" name=item_text value=""></div>
            <div><label>Description</label><textarea name=item_desc class=ldesc rows=1 placeholder="Details"></textarea></div>
            <div><label>Qty</label><div style="display:flex;align-items:center;gap:6px"><input name=qty type=number step="any" value=1 class=w-xs style="flex:1;min-width:0"><span class="ratetype-tag mute" style="font-size:12px;white-space:nowrap"></span></div></div>
            <div><label>Unit</label>{uom_opts}</div>
            <div><label>Rate $</label><span class="rate-x"><input id="f_rateval" name=rate_value type=number step=0.01 placeholder="unit default" data-label="Rate $" class="w-sm line-rate">
            <input type=hidden name=rate_type value="" class="line-ratetype"><button type=button class=line-del title="Delete line item">✕</button></span></div>
          </div>
          <p id="ticketsum" class="hint" hidden style="font-size:14px;color:var(--frame);
             background:#eef3fa;border-radius:6px;padding:8px 12px"></p>
          <div><label>Notes</label><input name=location_note data-label="Notes" style="width:100%"></div>
          {self._btn_row("Save", "jobpop", add_item=True)}
          </fieldset>
                    {self._job_info_popup('jobpop', None, _tk_extra)}
        </form>
        """ + self._new_ticket_form_script(unit_rates)

    def _condition_popups(self, con, t, locked):
        """Check-Out / Check-In (build 'u', Jason 2026-10-25,
        universal summary pattern): the two condition forms ride in
        popups on the rental summary — same fields, same
        /ticket/<tid>/condition post, same lock behavior. The
        recorded conditions state as facts on the summary itself."""
        tid = t["ticket_id"]
        conds = list(engine.COND_RANK.keys())
        def sel(cur):
            # A stepped-past gate stamps COND_NOT_RECORDED, which is not a
            # rank: show it as the selected value so the decision is
            # visible; saving the form still demands a real pick.
            pre = (f"<option selected>{html.escape(engine.COND_NOT_RECORDED)}</option>"
                   if cur == engine.COND_NOT_RECORDED else "")
            return pre + "".join(
                f"<option{' selected' if cur==c else ''}>{html.escape(c)}</option>" for c in conds
            )
        out_c = self._g(t, "out_condition")
        in_c = self._g(t, "in_condition")
        ro = "disabled" if locked else ""
        btn = "" if locked else "<p><button>Save Check-Out</button></p>"
        btn2 = "" if locked else "<p><button>Save Check-In</button></p>"
        form_out = f"""
          <form method=post action="/ticket/{html.escape(tid)}/condition" enctype="multipart/form-data">
            <input type=hidden name=side value=out>
            <p class="hint">Out — required before Dispatched or On Rent.</p>
            <label>Out Condition</label><select name=condition required class=w-sm {ro}>{sel(out_c)}</select>
            <label>Meter / Hours / Fuel</label><input name=meter value="{html.escape(str(self._g(t,'out_meter')))}" {ro}>
            <label>Hour Meter</label><input name=hours type=number class=w-sm step=0.1 min=0 value="{html.escape(str(self._g(t,'hours_start')))}" {ro}>
            <p class="hint">Blank = no hour reading.</p>
            {self._photo_field(tid, "out", self._g(t, "out_photo"), locked)}
            <label>Note</label><input name=note value="{html.escape(str(self._g(t,'out_note')))}" {ro}>
            <p class="hint">Input by: {html.escape(str(self._g(t,'out_by')))} {html.escape(fmt_datetime(self._g(t,'out_at')))}</p>
            {btn}
          </form>"""
        form_in = f"""
          <form method=post action="/ticket/{html.escape(tid)}/condition" enctype="multipart/form-data">
            <input type=hidden name=side value=in>
            <p class="hint">In — required before Off Rent.</p>
            <label>In Condition</label><select name=condition required class=w-sm {ro}>{sel(in_c)}</select>
            <label>Meter / Hours / Fuel</label><input name=meter value="{html.escape(str(self._g(t,'in_meter')))}" {ro}>
            <label>Hour Meter</label><input name=hours type=number class=w-sm step=0.1 min=0 value="{html.escape(str(self._g(t,'hours_end')))}" {ro}>
            <p class="hint">Meter update · hour billing close.</p>
            {self._photo_field(tid, "in", self._g(t, "in_photo"), locked)}
            <label>Note</label><input name=note value="{html.escape(str(self._g(t,'in_note')))}" {ro}>
            <p class="hint">Input by: {html.escape(str(self._g(t,'in_by')))} {html.escape(fmt_datetime(self._g(t,'in_at')))}</p>
            {btn2}
          </form>"""
        doors = (self._pop_door("outpop", "Check-Out")
                 + self._pop_door("inpop", "Check-In"))
        popups = (self._pop_wrap("outpop", "Check-Out", form_out)
                  + self._pop_wrap("inpop", "Check-In", form_in))
        return doors, popups

    def view_ticket(self, con, tid):
        """Summary of Rental# (build 'u', Jason 2026-10-25,
        universal summary pattern): the ticket page IS the rental's
        summary — its facts stated (customer, unit, site, status,
        next step, dates, rate, FIT, conditions, money), its stored
        charge lines read-only, and every act behind a popup door:
        Job Info (transport fields + uploads, build 's'), Payment
        (the money panel), Check-Out, Check-In, Status, Move with
        note. The Work Ticket / Delivery Ticket print doors stay."""
        t = con.execute(
            """SELECT t.*, c.account_name, a.unit_no, a.description
               FROM tickets t JOIN customers c ON c.id = t.customer_id
               JOIN assets a ON a.id = t.asset_id WHERE t.ticket_id=?""",
            (tid,),
        ).fetchone()
        if not t:
            return '<div class="err">No Rental Ticket.</div>'
        # Build 'v': the row's reference columns hold engine keys —
        # this page reads them as the operator's numbers/codes.
        t = dict(t)
        t["invoice_no"] = engine.doc_num(con, "invoice", t.get("invoice_id"))
        t["quote_no"] = engine.doc_num(con, "quote", t.get("quote_id"))
        t["customer_id"] = engine.cust_code(con, t.get("customer_id")) or ""
        t["site_id"] = engine.site_code(con, t.get("site_id"))
        t["tax_loc_id"] = engine.loc_code(con, t.get("tax_loc_id"))
        m = engine.ticket_money(con, tid)
        nxt = engine.ALLOWED_NEXT.get(t["status"], ())
        # Billing OFF (shop flow, Jason 2026-10-21): the desk offers
        # Close as a normal next step from Off Rent / Ready to Bill —
        # the same lifecycle exception set_status applies (no invoice
        # will ever exist to bill this ticket).
        _billing_off = not engine.module_on(con, "billing")
        if (_billing_off and t["status"] in ("Off Rent", "Ready to Bill")
                and "Closed" not in nxt):
            nxt = tuple(nxt) + ("Closed",)
        buttons = "".join(
            f'<button name=status value="{html.escape(s)}">{html.escape(s)}</button> '
            for s in nxt
        )
        fit_cls = "pass" if m.get("fit") == "PASS" else "fail"
        locked = t["status"] in ("Billed", "Closed", "Void") or bool(t["invoice_no"])
        quote_panel = quote_expiry_panel(con, self._g(t, "quote_no"))
        haul = engine.clean_haul_by(self._g(t, "haul_by"))
        dest = engine.clean_deliver_to(self._g(t, "deliver_to"))
        haul_text = engine.transport_display(
            haul, self._g(t, "haul_note") if "haul_note" in t.keys() else "")
        del_opts = "".join(
            f"<option value='{d}'{' selected' if dest == d else ''}>"
            f"{html.escape(engine.DELIVER_LABELS[d])}</option>" for d in engine.DELIVER_TO)
        tax_locs = con.execute(
            "SELECT loc_id, COALESCE(display_name, loc_id) || ' · ' || printf('%.2f%%', tax_rate*100) AS label FROM jurisdictions ORDER BY display_name"
        ).fetchall()
        current_tax_loc = self._g(t, "tax_loc_id") or ""
        tax_loc_opts, tax_loc_cur = combo_opts(tax_locs, "loc_id", "label", current_tax_loc)
        status_help = {
            "Quoted": "Reserve unit",
            "Reserved": "Check-out · Dispatch",
            "Dispatched": "Check-out · On Rent",
            "On Rent": "Check-in · Off Rent",
            "Standby": "On Rent · Check-in · Off Rent",
            "Off Rent": "Ready to Bill · Invoice",
            "Ready to Bill": "Invoice",
            "Billed": "Close Rental Ticket",
            "Closed": "Complete",
            "Void": "Void — closed",
        }.get(t["status"], "")
        if _billing_off and t["status"] in ("Off Rent", "Ready to Bill"):
            # No billing language nags a shop that doesn't bill.
            status_help = "Close Rental Ticket"
        off_label = "Off-rent date" if t["status"] in ("On Rent", "Standby", "Dispatched") else "Off-rent date (if needed)"
        # The deliberate escape (shop-flow, Jason 2026-10-21): one
        # "Proceed anyway" checkbox covering whichever gates this move
        # would hit — a missing condition (switch ON) and/or a non-PASS
        # FIT (either switch mode). Nothing renders when nothing blocks,
        # so an all-clear ticket page is unchanged. Build 'u': the
        # checkbox rides in the Status popup with the move it covers.
        _dispatch_moves = [s for s in nxt if s in ("Dispatched", "On Rent")]
        _off_moves = [s for s in nxt if s in ("Off Rent", "Ready to Bill")]
        _parts = []
        if engine.module_on(con, "condition"):
            if _dispatch_moves and not self._g(t, "out_condition"):
                _parts.append("move without a check-out condition")
            if _off_moves and not self._g(t, "in_condition"):
                _parts.append("move without a check-in condition")
        if _dispatch_moves and m.get("fit") and m.get("fit") != "PASS":
            _parts.append(f"dispatch with FIT {m['fit']} on file")
        proceed_row = (
            f'<p><label><input type=checkbox name=proceed value=1> '
            f'Proceed anyway — {" and ".join(_parts)}.</label></p>'
            if _parts else "")
        status_form = f"""
        <form method=post action="/ticket/{html.escape(tid)}/status">
          <label>{html.escape(off_label)}</label>
          <input type=date name=off_rent class=w-sm value="{html.escape(t['off_rent'] or '')}">
          {proceed_row}
          <p>{buttons or 'No further moves.'}</p>
        </form>
        """
        # Transport lock wording (Jason, 2026-10-21): name the document
        # that holds the lock — never a bare "the ticket" / "the invoice"
        # the reader has to guess at. Verified in code: the ticket's
        # transport fields (haul, deliver-to, tax jurisdiction) are
        # written ONLY by update_ticket_transport, which refuses once
        # the ticket is Billed/Closed/Void or carries an invoice number —
        # so after billing they cannot be changed anywhere, and the line
        # says so instead of pointing at another page. Build 's'
        # (Jason, 2026-10-25): the line renders inside the Job Info
        # popup, where the transport fields now live.
        if not locked:
            transport_lock_line = ""
        elif t["invoice_no"]:
            transport_lock_line = (
                "<p class='hint'>Locked — billed on invoice "
                f"{html.escape(t['invoice_no'])}. Transport and possession "
                "can't be changed after billing.</p>")
        elif t["status"] == "Billed" and self._g(t, "billed_note"):
            transport_lock_line = (
                "<p class='hint'>Locked — marked Billed without an invoice "
                "(out of flow). See the note above. Transport and "
                "possession can't be changed after billing.</p>")
        else:
            transport_lock_line = (
                "<p class='hint'>Locked — this Rental Ticket is "
                f"{html.escape(t['status'].lower())}. Transport and "
                "possession can't be changed now.</p>")
        # Stored charge lines (census, build 's'): lines typed before
        # build 's' stay on the record — counted in this ticket's
        # total, never editable, never deleted. Build 'u': they are
        # this summary's lines, stated read-only on the summary
        # itself (they rode in the Job Info popup in build 's only
        # because the page had no lines section; a summary does).
        _stored = engine.ticket_lines(con, tid)
        if _stored:
            _srows = "".join(
                f"<tr><td>{html.escape(_ln['category'])}</td>"
                f"<td>{html.escape(_ln['item'])}</td>"
                f"<td>{html.escape(_ln['description'])}</td>"
                f"<td style='text-align:right'>{_ln['qty']:g} "
                f"{html.escape(_ln['uom'])}</td>"
                f"<td style='text-align:right'>${_ln['rate']:,.2f}</td>"
                f"<td style='text-align:right'>${_ln['amount']:,.2f}</td>"
                f"<td>{'Tax' if _ln['taxed'] else ''}</td>"
                f"<td>{html.escape(_ln['note'] or '')}</td></tr>"
                for _ln in _stored)
            stored_lines_html = (
                "<p class=\"hint\">Charge lines on this Rental (record — "
                "read only)</p>"
                "<table><tr><th>Type</th><th>Item</th>"
                "<th>Description</th><th>Qty</th><th>Rate</th><th>Amount</th>"
                f"<th></th><th>Note</th></tr>{_srows}</table>")
        else:
            stored_lines_html = ""
        # Job Info (build 's', Jason 2026-10-25): Transport, Deliver
        # to, and Tax Jurisdiction are ticket data and live in the
        # Job Info popup; the popup's own form posts to the transport
        # route, whose engine write keeps the lock rules.
        _ro = " disabled" if locked else ""
        if locked:
            taxloc_field = (
                "<label>Tax Jurisdiction</label><input value=\""
                + html.escape(tax_loc_cur or "—", quote=True) + "\" disabled>")
        else:
            taxloc_field = (
                combo_field("t_taxloc", "tax_loc_text", tax_loc_opts,
                            value=tax_loc_cur, label="Tax jurisdiction",
                            placeholder="Pick or leave blank")
                + f"<input type=hidden id=\"t_taxloc_id\" name=tax_loc_id "
                  f"value=\"{html.escape(current_tax_loc, quote=True)}\">")
        jobinfo_popup = f"""
        <div id="tktjobpop" style="display:none;position:fixed;top:8%;left:8%;right:8%;background:white;border:2px solid #333;padding:18px;z-index:1000;max-height:84%;overflow:auto">
          <h3 style="margin-top:0">Job info <span style="float:right"><button type=button onclick="document.getElementById('tktjobpop').style.display='none'">Close</button></span></h3>
          <form method=post action="/ticket/{html.escape(tid)}/transport" enctype="multipart/form-data">
          <div class="row">
            <div><label>Transport</label><input name=haul_by list="ticket-haul-list" value="{html.escape(haul_text, quote=True)}" autocomplete="off"{_ro}><datalist id="ticket-haul-list"><option value="Customer Transport"><option value="Company Transport"></datalist></div>
            <div><label>Deliver to</label><select name=deliver_to class=w-sm{_ro}>{del_opts}</select></div>
            <div>{taxloc_field}</div>
          </div>
          <p class="hint">{html.escape(m.get("possession_label") or "")}. {html.escape(m.get("tax_note") or "")}
          Tax: {html.escape(m.get("tax_name") or "")} {m.get("tax_rate", 0):.4f}{" · exempt" if m.get("tax_exempt") else ""}.</p>
          <p class="hint">{html.escape(engine.haul_consequence(haul, dest))}</p>
          <div><label>Attach File</label><input type=file name=ticket_upload{_ro}></div>
          {transport_lock_line}
          {"" if locked else '<p><button>Save</button></p>'}
          </form>
        </div>
        """
        # Noted passage (Jason, 2026-10-21): a secondary control that can
        # move this ticket to ANY other status — outside the usual next
        # steps, and to Billed with no invoice behind it — when the
        # operator writes the note that puts the move on the record.
        # Build 'u': the form rides in its own popup on the summary.
        _all_statuses = ("Quoted", "Reserved", "Dispatched", "On Rent",
                         "Standby", "Off Rent", "Ready to Bill", "Billed",
                         "Closed", "Void")
        jump_opts = "".join(
            f'<option value="{html.escape(s)}">{html.escape(s)}</option>'
            for s in _all_statuses if s != t["status"])
        jump_form = f"""
        <form method=post action="/ticket/{html.escape(tid)}/jump">
          <p class="hint">Any status, incl. Billed without invoice. Note required.</p>
          <p><label>Move to</label> <select name=status class=w-sm>{jump_opts}</select></p>
          <p><label>Note (required)</label>
          <input name=note required maxlength=2000 style="width:100%"></p>
          <p><button>Move with note</button></p>
        </form>
        """
        # Money (Jason 2026-10-23, universality): before invoicing,
        # the rental ticket itself takes money — blanket or by stored
        # line, any tender, credits applied; at invoicing the
        # settlements carry onto the invoice. Build 'u': the panel
        # rides in the Payment popup; the summary states the figures.
        # Once billed, the money lives on the invoice and the summary
        # states the pointer instead.
        if t["invoice_no"]:
            _tset = engine.doc_settled(con, "ticket", tid)
            _tset_txt = (
                f"Settled ${float(_tset['total']):,.2f} on this Rental, "
                f"carried to " if float(_tset["total"]) > 0 else "")
            money_fact = (
                f"{_tset_txt}<a href=\"/invoice/"
                f"{html.escape(t['invoice_no'])}\">Invoice "
                f"{html.escape(t['invoice_no'])}</a> carries the money.")
            pay_door, pay_popup = "", ""
            money_rows = []
        else:
            money_fact = None
            pay_door, pay_popup = self._money_popup(
                con, "ticket", tid, t["customer_id"])
            _set = engine.doc_settled(con, "ticket", tid)
            money_rows = [
                ("Settled", f"${float(_set['total']):,.2f}"),
                ("Balance", f"${float(engine.doc_balance(con, 'ticket', tid)):,.2f}"),
            ]
        # The out-of-flow mark: Billed with nothing behind it shows its
        # passage note (note · who · when) right where the status shows.
        billed_mark = (
            f"<p><span class='fail'><b>Billed without an invoice — out of "
            f"flow.</b></span> {html.escape(self._g(t, 'billed_note'))}</p>"
            if t["status"] == "Billed" and not t["invoice_no"]
            and self._g(t, "billed_note") else "")
        def _cond_fact(side):
            c = self._g(t, f"{side}_condition")
            if not c:
                return "Not recorded"
            bits = [html.escape(str(c))]
            meter = self._g(t, f"{side}_meter")
            if meter:
                bits.append(f"Meter {html.escape(str(meter))}")
            hrs = self._g(t, "hours_start" if side == "out" else "hours_end")
            if hrs not in (None, ""):
                bits.append(f"Hours {hrs}")
            note = self._g(t, f"{side}_note")
            if note:
                bits.append(html.escape(str(note)))
            by, at = self._g(t, f"{side}_by"), self._g(t, f"{side}_at")
            if by or at:
                bits.append(f"Input by: {html.escape(str(by))} "
                            f"{html.escape(fmt_datetime(at))}")
            return " · ".join(bits)
        facts = [
            ("Customer", html.escape(t["account_name"])),
            ("Unit", f"{html.escape(t['unit_no'])} — "
                     f"{html.escape(t['description'] or '')}"),
            ("Site", html.escape(t["site_id"] or "—")),
            ("Status", html.escape(t["status"])),
            ("Next Step", html.escape(status_help) if status_help else None),
            ("On Rent", html.escape(fmt_date(t["on_rent"]))),
            ("Off Rent", html.escape(fmt_date(t["off_rent"])) if t["off_rent"] else "—"),
            ("Rate", f"{html.escape(t['rate_type'])} · ${m['rate']:,.2f}"),
            ("FIT", f"<span class=\"{fit_cls}\">{html.escape(m.get('fit', ''))}</span>"
                    + (f" · <span class='fail'>FIT override: "
                       f"{html.escape(self._g(t, 'fit_override'))}</span>"
                       if self._g(t, "fit_override") else "")),
            ("PO #", html.escape(self._g(t, "po")) if (self._g(t, "po") or "").strip() else None),
            ("Quote #", (f"<a href=\"/summary/quote/{html.escape(self._g(t, 'quote_no'), quote=True)}\">"
                         f"{html.escape(self._g(t, 'quote_no'))}</a>")
                        if (self._g(t, "quote_no") or "").strip() else None),
            ("Invoice #", (f"<a href=\"/invoice/{html.escape(t['invoice_no'], quote=True)}\">"
                           f"{html.escape(t['invoice_no'])}</a>")
                          if t["invoice_no"] else None),
            ("Associated", self._assoc_co_fact(con, "ticket", tid)),
            ("Job Name", html.escape(self._g(t, "job_name")) if (self._g(t, "job_name") or "").strip() else None),
            ("AFE #", html.escape(self._g(t, "afe")) if (self._g(t, "afe") or "").strip() else None),
            ("Transport", html.escape(haul_text)),
            ("Deliver to", html.escape(engine.DELIVER_LABELS.get(dest, dest))),
            ("Tax Jurisdiction", html.escape(tax_loc_cur or "—")),
            ("Check-Out", _cond_fact("out")),
            ("Check-In", _cond_fact("in")),
            ("Days", str(m["days"])),
            ("Hours", f"{m['hours']:g}" if m.get("hours", 0) > 0 else None),
            ("Rental", f"${m['rental']:,.2f}"),
            ("Transport $", f"${m.get('transport', 0):,.2f}"),
            ("Tax", f"${m['tax']:,.2f}"),
            ("Total", f"${m['total']:,.2f}"),
        ] + money_rows + [
            ("Money", money_fact),
            ("Notes", html.escape(self._g(t, "location_note")) if (self._g(t, "location_note") or "").strip() else None),
            ("Input by:", f"{html.escape(str(self._g(t, 'clerk') or ''))} "
                           f"{html.escape(fmt_datetime(self._g(t, 'created_at')))}".strip()),
        ]
        cond_doors, cond_popups = self._condition_popups(con, t, locked)
        doors = (
            self._pop_door("tktjobpop", "Job Info")
            + pay_door + cond_doors
            + self._pop_door("statpop", "Status")
            + self._pop_door("jumppop", "Move with note")
            + f"<a class=\"btn\" href=\"/print/work/{html.escape(tid)}\">Work Ticket</a> "
            + f"<a class=\"btn\" href=\"/print/delivery/{html.escape(tid)}\">Delivery Ticket</a>")
        popups = (
            jobinfo_popup + pay_popup + cond_popups
            + self._pop_wrap("statpop", "Status", status_form)
            + self._pop_wrap("jumppop", "Move with note", jump_form))
        extra_top = (billed_mark + task_nudge(con, f"/ticket/{tid}")
                     + quote_panel + self._paper_warning(t, m))
        return self._sum_page(
            "Rental", tid, facts, stored_lines_html, doors, popups,
            "/tickets", "Rental Tickets", extra_top=extra_top)


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
            if "fit_override" in r.keys() and r["fit_override"]:
                return "<td class='fail'>FAIL — overridden</td>"
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
            f"the site may reject this unit at receiving.</p>"
        )

    def view_tickets(self, con, flag=None):
        """Ticket list. flag=fit shows exactly the shipping set — Reserved /
        Dispatched tickets failing fit, the only moment paper earns a tap.
        flag=nooff shows exactly the on-rent tickets with no off-rent date.
        Any other flag value falls back to the unfiltered list."""
        rows = con.execute(
            """SELECT t.ticket_id, t.status, t.on_rent, t.off_rent, c.account_name, a.unit_no
               FROM tickets t JOIN customers c ON c.id = t.customer_id
               JOIN assets a ON a.id = t.asset_id
               ORDER BY t.on_rent DESC"""
        ).fetchall()
        head = ""
        if flag == "fit":
            rows = [r for r in rows
                    if r["status"] in self._SHIP_TICKET
                    and engine.ticket_money(con, r["ticket_id"]).get("fit", "PASS") != "PASS"]
            head = (f"<h1>{len(rows)} unit{'s' if len(rows) != 1 else ''} Shipping With Bad Paper</h1>"
                    f"<p class='hint'><a href='/tickets'>All Rental Tickets</a></p>")
        elif flag == "nooff":
            rows = [r for r in rows
                    if r["status"] in ('On Rent', 'Standby') and not (r["off_rent"] or "")]
            head = (f"<h1>{len(rows)} on Rent With No Off-Rent Date</h1>"
                    f"<p class='hint'><a href='/tickets'>All Rental Tickets</a></p>")
        if not head:
            head = "<h1>Rental Tickets</h1>"
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
            return f"<td>{html.escape(fmt_date(r['off_rent']))}</td>"
        body = "".join(
            f"<tr><td><a href='/ticket/{html.escape(r['ticket_id'])}'>{html.escape(r['ticket_id'])}</a></td>"
            f"<td>{html.escape(r['account_name'])}</td><td>{html.escape(r['unit_no'])}</td>"
            f"<td>{html.escape(r['status'])}</td><td>{html.escape(fmt_date(r['on_rent']))}</td>"
            f"{_off_cell(r)}"
            f"{self._ticket_fit_cell(con, r)}</tr>"
            for r in rows
        )
        # No Reports sub-row here (Jason 2026-10-24): Reports is
        # read-only, and this is a work page — its header tab is
        # Equipment (see _NAV_SECTIONS). The Reports tab itself still
        # links here from its own sub-row; this page carries no
        # second row claiming otherwise.
        return head + f"""
        <table class="audit"><tr><th>ID</th><th>Customer</th><th>Unit</th><th>Status</th><th>On</th><th>Off</th><th>Fit</th></tr>{body}</table>
        """ + AUDIT_TABLE_JS

    def _asset_lists(self, con):
        """Shared by the Assets page and the dashboard card: needs-paper + idle."""
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
               WHERE a.active = 1 AND COALESCE(a.designation,'Fleet') NOT IN ('Plant','Stock')
               AND COALESCE(a.status,'Active')='Active'
               AND NOT EXISTS
               (SELECT 1 FROM tickets t WHERE t.asset_id = a.id
                AND t.status NOT IN ('Billed','Closed','Void'))
               ORDER BY a.unit_no"""
        ).fetchall()
        idle_day = sum(engine.day_equivalent(r["rate_unit"], r["rate_value"]) for r in idle)
        idle_other = sum(1 for r in idle if (r["rate_unit"] or "Day") in ("Hour", "Special"))
        # Batch 3 #18: expired certs are an Assets fact and stay
        # per-unit; the checklist watch shrinks to ONE pointer (grouped
        # count + worst unit) — no per-row echoes here either.
        groups = engine.compliance_groups(con)
        pointer = []
        if groups:
            total = sum(g["total"] for g in groups)
            pointer = [{"t": f"Compliance — {len(groups)} units · {total} items "
                             f"(worst {groups[0]['unit_no']})",
                        "h": "/compliance"}]
        paper = ([{"t": f"EXPIRED CERT — {r['unit_no']} (expired {fmt_date(r['cert_expire'])})",
                   "h": f"/ucompliance/{r['asset_id']}"} for r in expired] + pointer)
        return paper, idle, idle_day, idle_other

    def view_assets(self, con):
        """The fleet: what needs attention up top, what's moving below."""
        return (chain_banner_rerun(con, "equipment") +
                self._ticket_kind_bar(con, "assets") +
                '<div style="display:flex;justify-content:space-between;align-items:center;margin:8px 0">'
                '<h2 style="margin:0">Latest Changes</h2>'
                '<a class="btn" href="/unit/new">+ Add Asset</a></div>' +
                self._assets_latest_changes(con) +
                self._view_door("/assets/all", "All assets — audit"))

    def _unit_state_badge(self, con, asset_id):
        """Quick cert/fit-state for a unit row."""
        exp = engine.operative_cert_expiry(con, asset_id)
        today = date.today().isoformat()
        if exp and exp < today:
            return f"<span class='fail'>cert expired {html.escape(fmt_date(exp))}</span>"
        if exp:
            return f"<span class='mute'>cert {html.escape(fmt_date(exp))}</span>"
        return "<span class='mute'>no cert</span>"

    def _assets_latest_changes(self, con):
        """In/out/reserved movements, newest first, with cert/fit state."""
        moves = []
        for r in con.execute(
                """SELECT t.ticket_id, t.status, t.created_at, a.asset_id, a.unit_no, c.account_name
                   FROM tickets t
                   JOIN assets a ON a.id = t.asset_id
                   JOIN customers c ON c.id = t.customer_id
                   WHERE t.status='Reserved' ORDER BY t.created_at DESC LIMIT 10"""):
            moves.append((r["created_at"], "Reserved",
                          f"{r['unit_no']} reserved — {r['account_name']}",
                          f"/ticket/{r['ticket_id']}", r["asset_id"]))
        for r in con.execute(
                """SELECT t.ticket_id, t.out_at, a.asset_id, a.unit_no, c.account_name
                   FROM tickets t
                   JOIN assets a ON a.id = t.asset_id
                   JOIN customers c ON c.id = t.customer_id
                   WHERE t.out_at IS NOT NULL AND TRIM(t.out_at)!=''
                   ORDER BY t.out_at DESC LIMIT 10"""):
            moves.append((r["out_at"], "Out",
                          f"{r['unit_no']} out — {r['account_name']}",
                          f"/ticket/{r['ticket_id']}", r["asset_id"]))
        for r in con.execute(
                """SELECT t.ticket_id, t.in_at, a.asset_id, a.unit_no, c.account_name
                   FROM tickets t
                   JOIN assets a ON a.id = t.asset_id
                   JOIN customers c ON c.id = t.customer_id
                   WHERE t.in_at IS NOT NULL AND TRIM(t.in_at)!=''
                   ORDER BY t.in_at DESC LIMIT 10"""):
            moves.append((r["in_at"], "In",
                          f"{r['unit_no']} back in — {r['account_name']}",
                          f"/ticket/{r['ticket_id']}", r["asset_id"]))
        moves.sort(key=lambda m: m[0] or "", reverse=True)
        rows = "".join(
            f"<div class='todo'><span class='mute'>{html.escape(fmt_date(when))} · {kind}</span> "
            f"<a href='{html.escape(href, quote=True)}'>{html.escape(text)}</a> "
            f"{self._unit_state_badge(con, aid)}</div>"
            for when, kind, text, href, aid in moves[:5])
        return rows or "<p class='mute'>No movements yet.</p>"

    def view_assets_all(self, con):
        """Every asset, as it sits — grouped by class (pack 'm',
        Jason's 'l' look): Fleet, Stock, Plant, then the operator's
        own designations. No filter, no sort within a class."""
        rows = []
        for r in con.execute(
                """SELECT asset_id, unit_no, category, description, rate_unit, rate_value,
                          active, condition, designation,
                          COALESCE(status,'Active') AS status FROM assets"""):
            _exp = engine.operative_cert_expiry(con, r["asset_id"])
            d = dict(r)
            d["cert_expire"] = _exp
            rows.append(d)

        def _row(r):
            return (
                f"<tr><td><a href='/unit/{html.escape(r['asset_id'])}'>{html.escape(r['asset_id'])}</a></td>"
                f"<td>{html.escape(r['unit_no'])}</td><td>{html.escape(r['category'] or '')}</td>"
                f"<td>{html.escape(r['description'] or '')}</td>"
                f"<td>${float(r['rate_value'] or 0):,.2f}/{html.escape((r['rate_unit'] or 'Day').lower())}</td>"
                f"<td>{'Yes' if r['active'] else 'No'}</td>"
                f"<td>{html.escape(r['condition'] or '')}</td>"
                f"<td>{html.escape(r['designation'] or 'Fleet')}</td>"
                f"<td>{html.escape(r['status'] or 'Active')}</td>"
                f"<td>{html.escape(fmt_date(r['cert_expire']))}</td>"
                "<td>" + _task_from_row(r['unit_no'] + " — " + (r['description'] or ''),
                                        "/unit/" + r['asset_id'], '/assets/all') + "</td></tr>")

        groups = {}
        for r in rows:
            groups.setdefault(r["designation"] or "Fleet", []).append(r)
        order = [c for c in ("Fleet", "Stock", "Plant") if c in groups]
        order += sorted(c for c in groups if c not in ("Fleet", "Stock", "Plant"))
        sections = "".join(
            f"<h3 style='margin:12px 0 4px'>{html.escape(cls)}</h3>"
            f"<table class=\"audit\"><tr><th>ID</th><th>Asset #</th><th>Category</th><th>Description</th>"
            f"<th>Daily</th><th>Active</th><th>Condition</th><th>Designation</th><th>Status</th><th>Cert expires</th><th></th></tr>"
            + "".join(_row(r) for r in groups[cls]) + "</table>"
            for cls in order)
        return f"""
        <p class="hint"><input id="auditq" placeholder="Filter" size="30"
        oninput="document.querySelectorAll('table.audit').forEach(t=>auditFilter(t,this.value))">
        </p>
        {sections or '<p class="mute">No assets.</p>'}
        """ + AUDIT_TABLE_JS

    def _unit_compliance_link(self, con, aid):
        summ = engine.compliance_summary(con, aid)
        if not summ["total"]:
            return (f'<p class="hint">No compliance checks on this asset yet. '
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
                return '<div class="err">Unknown asset.</div>'
        nxt = aid or engine.next_asset_id(con)
        def v(k, default=""):
            if not row:
                return default
            val = row[k]
            return "" if val is None else str(val)
        cat_opts = [(c, c, c) for c in engine.lookups(con, "category")]
        yard_opts = [(y, y, y) for y in engine.lookups(con, "yard")]
        cond = lookup_select(con, "condition", "condition", current=v("condition") or "Available", css="w-sm")
        # Designation is NOT a curated kind: the full master list is
        # the offer (lookup_select default), like Condition above.
        desig = lookup_select(con, "designation", "designation",
                              current=v("designation") or "Fleet", css="w-sm")
        # Lifecycle status (Phase 5, Oct 24): a closed set — Active /
        # Retired / De-listed — picked beside the class, switched in
        # place, and recorded in the Done record when it changes
        # (save_asset carries the audit).
        status_opts = self._sel(list(engine.ASSET_STATUSES), v("status") or "Active")
        rate_units = self._sel(engine.lookups(con, "rate_type"), v("rate_unit") or "Day")
        live = con.execute(
            "SELECT ticket_id FROM tickets WHERE asset_id=? AND status IN ('Reserved','Dispatched','On Rent','Standby')",
            (engine.asset_key(con, aid),),
        ).fetchone() if aid else None
        warn = f"<p class='hint'>On Rental Ticket {html.escape(live['ticket_id'])} — unit number locked while out.</p>" if live else ""
        unit_ro = " readonly" if live else ""
        # While-out switch note (build 'o', Jason 2026-10-24): a
        # Designation or Status change on a unit that is out proceeds
        # only with a note; the engine enforces it and the Done
        # record carries the note and the ticket. The field stands
        # on the form only while the unit is out.
        switch_note_row = ""
        if live:
            switch_note_row = f"""
          <div class="row">
            <div><label>Switch Note</label><input name=switch_note>
            <p class="hint">Required to change Designation or Status while the unit is out.</p></div>
          </div>"""
        # PO register on the unit (Batch 3 #15): POs recorded against
        # this unit, with their stored status.
        po_hist = ""
        if row:
            try:
                _urows = con.execute(
                    """SELECT po_no, status, expire FROM purchase_orders
                       WHERE asset_id=? ORDER BY po_no""", (engine.asset_key(con, aid),)).fetchall()
            except Exception:
                _urows = []
            if _urows:
                _uh = "".join(
                    f"<tr><td>{html.escape(r['po_no'])}</td>"
                    f"<td>{html.escape(r['status'] or 'Open')}</td>"
                    f"<td>{html.escape(fmt_date(r['expire']))}</td></tr>"
                    for r in _urows)
                po_hist = (
                    f'<h2 style="font-size:16px;color:var(--frame)">Purchase Orders</h2>'
                    f"<table><tr><th>PO #</th><th>Status</th><th>Expires</th></tr>{_uh}</table>")
        return chain_banner(con, "equipment") + f"""
        {warn}
        <form method=post action="/unit/save">
          <input type=hidden name=asset_id value="{html.escape(aid) if row else ''}">
          <label>Id</label><input value="{html.escape(nxt)}" disabled>
          <div class="row">
            <div><label>Asset #</label><input name=unit_no required{unit_ro} value="{html.escape(v('unit_no'))}"></div>
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
            <div><label>Rate</label><select name=rate_unit class=w-xs>{rate_units}</select></div>
            <div><label>Rate $</label><input name=rate_value type=number step=0.01 class=w-sm value="{money_val(v('rate_value'))}"></div>
          </div>
          <div class="row">
            <div><label>Hour Meter</label><input name=meter_hours type=number class=w-sm step=0.1 value="{html.escape(v('meter_hours') or '0')}"></div>
            <div><label>Replacement $</label><input name=replacement_cost type=number class=w-sm step=0.01 value="{money_val(v('replacement_cost'))}"></div>
          </div>
          <div class="row">
            <div><label>Certificates</label><p class="hint">
            {f'<a href="/ucompliance/{html.escape(aid, quote=True)}">Compliance Page</a>'
             if row else
             'Compliance Page — after save.'}
            </p></div>
            <div><label>Paperwork</label><p class="hint">
            {f'<button type="button" class="vbtn" data-audit="/unit/paperwork?unit={html.escape(aid, quote=True)}" data-title="Paperwork — {html.escape(v("unit_no"))}">Paperwork</button>'
             if row else
             'Paperwork — after save.'}
            </p></div>
          </div>
          <div class="row">
            <div><label>Condition</label>{cond}</div>
            <div><label>Designation</label>{desig}</div>
          </div>
          <div class="row">
            <div><label>Status</label><select name=status class=w-sm>{status_opts}</select></div>
            <div><label style="margin-top:22px"><input type=checkbox name=active value=1 {"checked" if (not row) or row["active"] else ""}> Active</label></div>
          </div>{switch_note_row}
          <label>Ownership</label><input name=ownership value="{html.escape(v('ownership') or 'Owned')}">
          <label><input type=checkbox name=uscg_ok value=1 {"checked" if row and row["uscg_ok"] else ""}> USCG stamp</label>
          <label><input type=checkbox name=dnv_ok value=1 {"checked" if row and row["dnv_ok"] else ""}> DNV stamp</label>
          <label><input type=checkbox name=abs_ok value=1 {"checked" if row and row["abs_ok"] else ""}> ABS stamp</label>
          <label><input type=checkbox name=cert_operator value=1 {"checked" if row and row["cert_operator"] else ""}> Requires certified operator</label>
          <label>Notes</label><input name=notes value="{html.escape(v('notes'))}">
          <p><button>Save Asset</button> <a href="/assets/all">Cancel</a></p>
        </form>
        {self._unit_compliance_link(con, aid) if row else ""}
        {po_hist}
        {self._view_row("/assets/all", "Assets")}
        """

    def view_sites(self, con):
        # No inline index list (Jason 2026-10-21, look-see batch 2 —
        # same universal form rule as Customers): Done Today is the
        # recent list; the full list lives behind View (/sites/all,
        # rows open the site).
        return chain_banner_rerun(con, "site") + tabs_admin("/sites") + """<p style="margin:0 0 8px"><a class="btn" href="/site/new">+ New Site</a></p>
        """ + self._view_door("/sites/all", "Job sites — all")

    def view_sites_all(self, con):
        """Every job site, filterable/sortable — the audit popup for Admin → Job Sites."""
        rows = con.execute(
            """SELECT s.site_id, s.site_name, s.operator, s.rig_name,
                      j.loc_id AS loc_code, s.tax_exempt,
                      c.account_name, j.display_name, j.tax_rate, j.req_uscg, j.req_dnv, j.req_abs
               FROM sites s
               LEFT JOIN customers c ON c.id = s.customer_id
               LEFT JOIN jurisdictions j ON j.id = s.loc_id
               ORDER BY s.site_name"""
        ).fetchall()
        body = "".join(
            f"<tr><td><a href='/site/{html.escape(r['site_id'])}'>{html.escape(r['site_id'])}</a></td>"
            f"<td>{html.escape(r['site_name'])}</td>"
            f"<td>{html.escape(r['account_name'] or '')}</td>"
            f"<td>{html.escape(r['operator'] or '')}</td>"
            f"<td>{html.escape(r['rig_name'] or '')}</td>"
            f"<td>{html.escape(r['display_name'] or r['loc_code'] or 'Not set')} ({float(r['tax_rate'] or 0)*100:.2f}%)</td>"
            f"<td>{'Exempt' if r['tax_exempt'] else 'Taxable'}</td>"
            f"<td>{'U' if r['req_uscg'] else ''}{'D' if r['req_dnv'] else ''}{'A' if r['req_abs'] else ''}</td></tr>"
            for r in rows
        )
        return f"""
        <p class="hint"><input id="auditq" placeholder="Filter" size="30"
        oninput="document.querySelectorAll('table.audit').forEach(t=>auditFilter(t,this.value))">
        </p>
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
               LEFT JOIN customers c ON c.id = s.customer_id
               LEFT JOIN jurisdictions j ON j.id = s.loc_id
               WHERE s.site_id = ?""",
            (sid,),
        ).fetchone()
        if not s:
            return '<div class="err">Unknown site.</div>'
        wells = con.execute(
            """SELECT COALESCE(NULLIF(TRIM(well_or_pad), ''), '(unnamed)') AS w,
                      COUNT(*) AS n
               FROM tickets WHERE site_id = ? GROUP BY w ORDER BY MAX(on_rent) DESC""",
            (engine.site_key(con, sid),),
        ).fetchall()
        tkts = con.execute(
            """SELECT t.ticket_id, t.status, t.on_rent, t.well_or_pad, a.unit_no
               FROM tickets t JOIN assets a ON a.id = t.asset_id
               WHERE t.site_id = ? ORDER BY t.on_rent DESC LIMIT 11""",
            (engine.site_key(con, sid),),
        ).fetchall()
        _loc_disp = s["display_name"]
        if not _loc_disp and s["loc_id"]:
            _lr = con.execute("SELECT loc_id FROM jurisdictions WHERE id=?",
                              (s["loc_id"],)).fetchone()
            _loc_disp = _lr["loc_id"] if _lr else None
        info = (
            ("Customer", s["account_name"] or "—"),
            ("Tax location", _loc_disp or "Not set"),
            ("Operator", s["operator"] or "—"),
            ("Rig", s["rig_name"] or "—"),
            ("Flag / waters", f"{s['flag_state'] or '—'} / {s['waters'] or '—'}"),
            ("Regime", s["primary_regime"] or "—"),
            ("Tax", "Exempt" if s["tax_exempt"] else "Taxable"),
            ("Notes", note_pop_html(s["notes"]) if s["notes"] else "—"),
        )
        info_html = "".join(
            f"<tr><th style='width:130px'>{html.escape(k)}</th><td>{html.escape(v)}</td></tr>"
            for k, v in info
        )
        wells_html = "".join(
            f"<tr><td>{html.escape(w['w'])}</td><td>{w['n']} Rental Ticket{'s' if w['n'] != 1 else ''}</td></tr>"
            for w in wells
        ) or '<tr><td colspan=2>No wells recorded on this pad yet.</td></tr>'
        tkt_rows = "".join(
            f"<tr><td><a href='/ticket/{html.escape(t['ticket_id'])}'>{html.escape(t['ticket_id'])}</a></td>"
            f"<td>{html.escape(t['unit_no'])}</td>"
            f"<td>{html.escape(t['well_or_pad'] or '—')}</td>"
            f"<td>{html.escape(t['status'])}</td>"
            f"<td>{html.escape(fmt_date(t['on_rent']))}</td></tr>"
            for t in tkts[:5]
        )
        more = f"<p class='hint'>+ {len(tkts) - 5} more</p>" if len(tkts) > 5 else ""
        return f"""
        <h1>{html.escape(s['site_name'])}</h1>
        <p class="hint">{html.escape(s['site_id'])}</p>
        <table>{info_html}</table>
        <h2 style="font-size:15px;color:var(--frame);margin:10px 0 5px">Wells on This Pad</h2>
        <table><tr><th>Well</th><th>Rental Tickets</th></tr>{wells_html}</table>
        <h2 style="font-size:15px;color:var(--frame);margin:10px 0 5px">Rental Tickets Here</h2>
        <table><tr><th>Rental Ticket</th><th>Unit</th><th>Well</th><th>Status</th><th>On rent</th></tr>
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
        return chain_banner(con, "site") + f"""
        {f'<p class="hint">Carried forward from {html.escape(carried["site_id"])} — name the new site.</p>' if carried else ''}
        <form method=post action="/site/save">
          <input type=hidden name=site_id value="{html.escape(sid) if row else ''}">
          <label>Site Name</label><input name=site_name required value="{html.escape(v('site_name'))}" class=w-md>
          <label>Address</label><input name=street value="{html.escape(v('street'))}" class=w-md>
          <input name=street2 value="{html.escape(v('street2'))}" placeholder="Suite, building, dock, c/o…" class=w-md>
          <div class="row"><div><label>City</label><input name=city value="{html.escape(v('city'))}"></div><div><label>State</label>{state_field("state", v('state'), 'maxlength=20')}</div></div>
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
        {self._view_row("/sites/all", "Sites")}
        """

    def view_wo_form(self, con, wid, bare=False):
        row = None
        if wid:
            row = con.execute("SELECT * FROM work_orders WHERE wo_id=?", (wid,)).fetchone()
            if not row:
                return '<div class="err">Unknown work order.</div>'
            # Build 'v': reference columns hold engine keys; the
            # form's pickers read the operator's codes/numbers.
            row = dict(row)
            row["asset_id"] = engine.asset_code(con, row.get("asset_id")) or ""
            row["customer_id"] = engine.cust_code(con, row.get("customer_id")) or ""
            row["ticket_id"] = engine.doc_num(con, "ticket", row.get("ticket_id"))
            row["invoice_no"] = engine.doc_num(con, "invoice", row.get("invoice_id"))
            row["quote_no"] = engine.doc_num(con, "quote", row.get("quote_id"))
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
            """SELECT t.ticket_id, t.ticket_id || ' · ' || c.customer_id AS label
               FROM tickets t JOIN customers c ON c.id = t.customer_id
               WHERE t.status NOT IN ('Void','Closed') ORDER BY t.ticket_id DESC"""
        ).fetchall()
        wo_unit_opts, wo_unit_cur = combo_opts(assets, "asset_id", "label", v("asset_id"))
        wo_type_opts = [(t, t, t) for t in engine.lookups(con, "wo_type")]
        wo_cust_opts, wo_cust_cur = combo_opts(custs, "customer_id", "account_name", v("customer_id"))
        wo_tix_opts, wo_tix_cur = combo_opts(tix, "ticket_id", "label", v("ticket_id"))
        today = date.today().isoformat()
        quote_panel = quote_expiry_panel(con, v("quote_no")) if row else ""
        # Line items (2026-10-15): one WO, many lines. Edit renders the
        # stored lines; new renders one blank row.
        wo_lines = engine.wo_lines(con, wid) if row else []
        if not wo_lines:
            wo_lines = [{"item": "", "description": "", "category": "", "qty": 1, "rate": 0, "uom": ""}]
        line_rows = "".join(
            f"""<div class="lineitem-row" style="display:grid;grid-template-columns:104px 1fr 2fr 84px 104px 104px;gap:8px;align-items:start">
            <div><label>Type</label>{lookup_select(con, 'inv_cat', f'type{i}', current=(ln['category'] if 'category' in ln.keys() else '') or '', blank=True)}</div>
            <div><label>Item</label><input name=item{i} value="{html.escape(str(ln['item'] or ''), quote=True)}"></div>
            <div><label>Description</label><textarea name=description{i} class=ldesc rows=1>{html.escape(str(ln['description'] or ''))}</textarea></div>
            <div><label>Qty</label><input name=qty{i} type=number step="any" value="{html.escape(str(ln['qty'] if ln['qty'] is not None else 1))}" class=w-xs></div>
            <div><label>Unit</label>{lookup_select(con, 'inv_uom', f'uom{i}', current=(ln['uom'] if 'uom' in ln.keys() else '') or '', blank=True, vals=enabled_values(con, 'inv_uom'), add_option=False)}</div>
            <div><label>Rate $</label><span class="rate-x"><input name=cost{i} type=number step=0.01 value="{html.escape(str(ln['rate'] if ln['rate'] is not None else 0))}" class=w-sm><button type=button class=line-del title="Delete line item">✕</button></span></div>
          </div>"""
            for i, ln in enumerate(wo_lines))
        # Header zone (build 'r', Jason 2026-10-25, facelift item 4 —
        # his worked example; two-row form build 't', same day,
        # universal form law): Company block, WO # larger and bold,
        # Date, bar, Customer left, Job Info box right (the WO's
        # PO #), then the lines. The Unit / Type / Reference
        # Ticket area and the Charge to / Status / dates rows live
        # in the Job Info popup (extra — same names, save with the
        # form); build 't' moves Uploads there too, so below the
        # lines only Notes remains. The combos render without the
        # HTML required flag inside the hidden popup (a required
        # control in a hidden panel blocks submit as
        # non-focusable); the requirement itself is unchanged and
        # enforced server-side.
        _wo_cust = (combo_field("wo_cust", "customer_text", wo_cust_opts, value=wo_cust_cur, label="Customer")
                    + f'<input type=hidden id="wo_cust_id" name=customer_id value="{html.escape(v("customer_id"), quote=True)}">')
        _wo_extra = f"""
            <div class="row">
              <div>{combo_field("wo_unit", "asset_text", wo_unit_opts, value=wo_unit_cur, label="Unit")}
              <input type=hidden id="wo_unit_id" name=asset_id value="{html.escape(v('asset_id'), quote=True)}"></div>
              <div>{combo_field("wo_type", "work_type_text", wo_type_opts, value=v('work_type'), label="Type")}
              <input type=hidden id="wo_type_id" name=work_type value="{html.escape(v('work_type'), quote=True)}"></div>
            </div>
            <div class="row">
              <div><label>Reference Ticket</label><input name=ref_ticket value="{html.escape(v('ref_ticket'))}" class=w-sm placeholder="Optional"></div>
              <div><label>Charge to</label>
                <select name=charge_to class=w-sm>
                  <option value=internal {"selected" if (not row) or row["charge_to"]=="internal" else ""}>Internal</option>
                  <option value=customer {"selected" if row and row["charge_to"]=="customer" else ""}>Customer</option>
                </select>
              </div>
              <div><label>Status</label><select name=status class=w-sm>{self._sel(engine.lookups(con,'wo_status'), v('status') or 'Open')}</select></div>
            </div>
            <div class="row">
              <div><label>Crew / Vendor</label><input name=vendor value="{html.escape(v('vendor'))}" class=w-sm></div>
              <div><label>Open Date</label><input type=date name=open_date value="{html.escape(v('open_date')[:10] if v('open_date') else today)}" class=w-sm></div>
              <div><label>Close Date</label><input type=date name=close_date value="{html.escape(v('close_date')[:10] if v('close_date') else '')}" class=w-sm></div>
            </div>
            <div><label><input type=checkbox name=warranty value=1 {"checked" if row and row["warranty"] else ""}> Warranty</label></div>
            <div><label>Uploads</label><input type=file name=wo_upload></div>"""
        _wo_doc = f'WO # <input value="{html.escape(nxt)}" disabled class=w-xs>'
        _wo_date = f'<label>Date</label> <input type=date name=wo_date value="{html.escape(v("wo_date")[:10] if v("wo_date") else today)}" class=w-sm>'
        return ("" if bare else self._ticket_kind_bar(con, "workorder")) + f"""
        {quote_panel}
        <form method=post action="/wo/save" enctype="multipart/form-data">
          <input type=hidden name=wo_id value="{html.escape(wid) if row else ''}">
          {self._form_head(con, _wo_doc, _wo_date, _wo_cust, [("PO #", v("po"))])}
          {self._line_head()}
          {line_rows}
          <div><label>Notes</label><input name=notes value="{html.escape(v('notes'))}" style="width:100%"></div>
          {self._btn_row("Save", "wojobpop", add_item=True)}
          {self._job_info_popup('wojobpop', {"po": v("po")}, _wo_extra)}
        </form>
        """ + ("""<script>
        (function(){
          var form = document.querySelector('form[action="/wo/save"]');
          if (!form) return;
          // Work-order Add Item (2026-10-15): each line row is one
          // line item on the single WO. Clone the last line row,
          // renumber type/item/description/qty/cost/uom to the next index,
          // clear values. Capped at 8 rows: the backend reads
          // item0..item7, so a 9th row would silently drop.
          function addItemRow(){
            var rows = form.querySelectorAll('.lineitem-row');
            if (rows.length >= 8) return;
            var proto = rows[rows.length - 1];
            var clone = proto.cloneNode(true);
            var n = rows.length;
            clone.querySelectorAll('[name]').forEach(function(el){
              el.name = el.name.replace(/\\d+$/, '') + n;
              if (el.name === 'qty' + n) el.value = '1';
              else if (el.name === 'cost' + n) el.value = '0';
              else el.value = '';
            });
            clone.querySelectorAll('select[data-field]').forEach(function(el){ el.dataset.field = el.name; });
            proto.parentNode.insertBefore(clone, proto.nextSibling);
            var inp = clone.querySelector('input');
            if (inp) inp.focus();
          }
          Array.prototype.forEach.call(form.querySelectorAll('button[type=button]'), function(b){
            if (b.textContent.trim().toLowerCase() === 'add item') b.addEventListener('click', addItemRow);
          });
        })();
        </script>""") + (
            # Build 'u' (Jason 2026-10-25, universal summary pattern;
            # disposes of PHASET JC-T4): the money panel no longer
            # stands below this form — a customer work order's money
            # is worked from its summary's Payment popup. The form
            # keeps the document's own work only.
            ""
        ) + ("" if bare else self._view_row("/wos/all", "Work Orders"))

    def view_wo_summary(self, con, wid):
        """Summary of Work Order# (build 'u', Jason 2026-10-25,
        universal summary pattern): the work order's facts stated —
        customer, date, status, type, unit, charge, its lines, its
        totals, its notes and Job Info values — with doors: Edit (to
        the form), Payment (the money panel in its popup, customer
        work orders), Print (the page print menu; a work order has
        no print pack), View (the Work Orders list). The quote-expiry
        panel that stood on the form is information: it states here
        as a fact line."""
        row = con.execute(
            """SELECT w.*, COALESCE(c.account_name, '') AS cust,
                      COALESCE(a.unit_no, '') AS unit_no
               FROM work_orders w
               LEFT JOIN customers c ON c.id = w.customer_id
               LEFT JOIN assets a ON a.id = w.asset_id
               WHERE w.wo_id = ?""", (wid,)).fetchone()
        if not row:
            return '<div class="err">Unknown work order.</div>'
        # Build 'v': reference columns hold engine keys; state the
        # operator's codes/numbers.
        row = dict(row)
        row["customer_id"] = engine.cust_code(con, row.get("customer_id")) or ""
        row["asset_id"] = engine.asset_code(con, row.get("asset_id")) or ""
        row["ticket_id"] = engine.doc_num(con, "ticket", row.get("ticket_id"))
        row["invoice_no"] = engine.doc_num(con, "invoice", row.get("invoice_id"))
        row["quote_no"] = engine.doc_num(con, "quote", row.get("quote_id"))
        def v(k, default=""):
            if k not in row:
                return default
            val = row[k]
            return "" if val is None else str(val)
        lines = engine.wo_lines(con, wid)
        lrows = "".join(
            f"<tr><td>{html.escape(ln['category'] or '')}</td>"
            f"<td>{html.escape(ln['item'] or '')}</td>"
            f"<td>{html.escape(ln['description'] or '')}</td>"
            f"<td>{float(ln['qty'] or 0):g}</td>"
            f"<td>{html.escape(ln['uom'] or '')}</td>"
            f"<td>${float(ln['rate'] or 0):,.2f}</td>"
            f"<td>${float(ln['qty'] or 0) * float(ln['rate'] or 0):,.2f}</td></tr>"
            for ln in lines)
        lines_html = (
            "<table><tr><th>Type</th><th>Item</th><th>Description</th>"
            "<th>Qty</th><th>Unit</th><th>Rate</th><th>Amount</th></tr>"
            f"{lrows}</table>" if lrows else "")
        quote_fact = None
        if v("quote_no"):
            quote_fact = (
                f"<a href=\"/summary/quote/{html.escape(v('quote_no'), quote=True)}\">"
                f"{html.escape(v('quote_no'))}</a>")
            _qc = engine.quote_check(con, v("quote_no"))
            if _qc["expired"]:
                quote_fact += (f" · Quote check: expired "
                               f"{html.escape(_qc['date_str'])}")
        _ref_t = v("ref_ticket") or v("ticket_id")
        facts = [
            ("Customer", html.escape(v("cust"))),
            ("Date", html.escape(fmt_date(v("wo_date")))),
            ("Status", html.escape(v("status"))),
            ("Type", html.escape(v("work_type"))),
            ("Unit", html.escape(v("unit_no")) if v("unit_no") else None),
            ("Charge to", html.escape(v("charge_to"))),
            ("Reference Ticket",
             (f"<a href=\"/ticket/{html.escape(_ref_t, quote=True)}\">"
              f"{html.escape(_ref_t)}</a>") if _ref_t else None),
            ("Quote #", quote_fact),
            ("Invoice #",
             (f"<a href=\"/invoice/{html.escape(v('invoice_no'), quote=True)}\">"
              f"{html.escape(v('invoice_no'))}</a>") if v("invoice_no") else None),
            ("PO #", html.escape(v("po")) if v("po") else None),
            ("Associated", self._assoc_co_fact(con, "wo", wid)),
            ("Crew / Vendor", html.escape(v("vendor")) if v("vendor") else None),
            ("Open Date", html.escape(fmt_date(v("open_date"))) if v("open_date") else None),
            ("Close Date", html.escape(fmt_date(v("close_date"))) if v("close_date") else None),
            ("Warranty", "Yes" if v("warranty") == "1" else None),
        ]
        if v("charge_to") == "customer":
            _set = engine.doc_settled(con, "wo", wid)
            facts += [
                ("Total", f"${float(engine.doc_total(con, 'wo', wid)):,.2f}"),
                ("Settled", f"${float(_set['total']):,.2f}"),
                ("Balance", f"${float(engine.doc_balance(con, 'wo', wid)):,.2f}"),
            ]
            pay_door, pay_popup = self._money_popup(
                con, "wo", wid, v("customer_id"))
        else:
            facts += [
                ("Labor", f"${float(v('labor') or 0):,.2f}"),
                ("Parts", f"${float(v('parts') or 0):,.2f}"),
                ("Other", f"${float(v('other_cost') or 0):,.2f}"),
            ]
            pay_door, pay_popup = "", ""
        facts.append(("Notes", html.escape(v("notes")) if v("notes") else None))
        doors = (pay_door
                 + f"<a class=\"btn\" href=\"/wo/{html.escape(wid, quote=True)}\">Edit</a> "
                 + self._print_menu(page=True))
        return (self._ticket_kind_bar(con, "workorder")
                + self._sum_page("Work Order", wid, facts, lines_html,
                                 doors, pay_popup,
                                 "/wos/all", "Work Orders"))

    def view_wos_all(self, con):
        """Work Orders list fragment — the universal View popup's
        content for the Work Order pages (build 'r', Jason
        2026-10-25). Same audit chrome as the other list fragments:
        filter box, sortable columns, rows link to the record."""
        rows = con.execute(
            """SELECT w.wo_id, w.wo_date, w.status, w.work_type,
                      c.account_name, a.unit_no
               FROM work_orders w
               LEFT JOIN customers c ON c.id = w.customer_id
               LEFT JOIN assets a ON a.id = w.asset_id
               ORDER BY w.wo_date DESC, w.wo_id DESC""").fetchall()
        body = "".join(
            f"<tr><td><a href='/summary/wo/{html.escape(r['wo_id'], quote=True)}'>"
            f"{html.escape(r['wo_id'])}</a></td>"
            f"<td>{html.escape(fmt_date(r['wo_date']))}</td>"
            f"<td>{html.escape(r['account_name'] or '')}</td>"
            f"<td>{html.escape(r['unit_no'] or '')}</td>"
            f"<td>{html.escape(r['work_type'] or '')}</td>"
            f"<td>{html.escape(r['status'] or '')}</td></tr>"
            for r in rows)
        return (f"<input id=auditq placeholder='Filter…' oninput='auditFilter(this)'>"
                f"<h2>Work Orders</h2>"
                f"<table class=audit><tr><th>WO #</th><th>Date</th>"
                f"<th>Customer</th><th>Unit</th><th>Type</th><th>Status</th></tr>"
                f"{body or '<tr><td colspan=6>No work orders.</td></tr>'}</table>"
                + AUDIT_TABLE_JS)

    def view_sales_all(self, con):
        """Sales list fragment — the universal View popup's content
        for the Sale page (build 'r', Jason 2026-10-25). The register
        table that used to render below the sale form, in the audit
        chrome (same rows as _sales_list_html, incl. balance)."""
        try:
            groups = con.execute(
                """SELECT s.sale_group AS grp, MIN(s.sale_date) AS d,
                          COUNT(*) AS n, COALESCE(SUM(s.amount),0) AS tot,
                          COALESCE(c.account_name, s.customer_id) AS cust
                   FROM sales s
                   LEFT JOIN customers c ON c.id = s.customer_id
                   GROUP BY s.sale_group
                   ORDER BY d DESC, grp DESC LIMIT 50""").fetchall()
        except Exception:
            groups = []
        rows_html = ""
        for g in groups:
            bal = float(engine.doc_balance(con, "sale", g["grp"]))
            rows_html += (
                f"<tr><td><a href='/sale/{html.escape(g['grp'], quote=True)}'>"
                f"{html.escape(g['grp'])}</a></td>"
                f"<td>{html.escape(fmt_date(g['d'] or ''))}</td>"
                f"<td>{html.escape(g['cust'] or '')}</td>"
                f"<td>{int(g['n'])}</td>"
                f"<td>${float(g['tot']):,.2f}</td>"
                f"<td>${bal:,.2f}</td></tr>")
        return (f"<input id=auditq placeholder='Filter…' oninput='auditFilter(this)'>"
                f"<h2>Sales</h2>"
                f"<table class=audit><tr><th>Sale</th><th>Date</th>"
                f"<th>Customer</th><th>Lines</th><th>Total</th><th>Balance</th></tr>"
                f"{rows_html or '<tr><td colspan=6>No sales.</td></tr>'}</table>"
                + AUDIT_TABLE_JS)

    def view_sale(self, con, q=None):
        """Equipment sales: outright sale of equipment (Jason 2026-10-07).
        Top-level tab, left of Rentals. Records sale, marks asset sold,
        carries to invoice."""
        from datetime import date
        today = date.today().isoformat()
        # Available assets (not sold, active, in service). Sale draw
        # (Jason 2026-10-24 ruling, amended the same day): NO class
        # is excluded — Fleet sells too, because long-rent customers
        # buy the unit. Plant and Fleet are marked in the list, and
        # picking one raises its own confirm check on this form; each
        # confirm is enforced again at save and at the engine.
        # Retired / De-listed units are not offered (lifecycle).
        assets = con.execute(
            "SELECT asset_id, unit_no, COALESCE(designation,'Fleet') FROM assets WHERE active=1 AND (sold_date IS NULL OR sold_date='') "
            "AND COALESCE(status,'Active') = 'Active' ORDER BY unit_no"
        ).fetchall()
        custs = con.execute(
            "SELECT customer_id, account_name FROM customers ORDER BY account_name"
        ).fetchall()
        aopts = "".join(
            f"<option value='{r[0]}' data-desig='{html.escape(r[2])}'>"
            f"{html.escape(r[1])}{' — Plant' if r[2] == 'Plant' else ' — Fleet' if r[2] == 'Fleet' else ''}</option>"
            for r in assets)
        copts = "".join(f"<option value='{r[0]}'>{r[1]}</option>" for r in custs)
        from datetime import date as _d
        _yr = _d.today().year
        _n = con.execute("SELECT COALESCE(MAX(CAST(SUBSTR(sale_id, 8) AS INTEGER)), 0) + 1 FROM sales WHERE sale_id LIKE ?", (f"S-{_yr}-%",)).fetchone()[0]
        sale_no = f"S-{_yr}-{_n:04d}"
        # Header zone (build 'r', Jason 2026-10-25, facelift item 4;
        # two-row form build 't', same day, universal form law):
        # Company block, Sale # + Date, bar, Customer left, Job Info
        # box right (Reference #), lines. Reference # and Condition
        # live in the Job Info popup (same names). The Plant/Fleet
        # confirm checks stand in the confirm-and-sign popup
        # (#saleconfpop) — saving an unconfirmed Plant/Fleet sale
        # opens it; the checks, the stamps, and the server's refusal
        # are unchanged.
        _sale_cust = (f'<div><label>Customer</label><select name=customer_id required>'
                      f'<option value="">— Pick —</option>{copts}</select></div>')
        _sale_extra = ('<div class="row"><div><label>Reference #</label>'
                       '<input name=ref_no class=w-sm placeholder="Optional"></div>'
                       '<div><label>Condition</label>'
                       '<input name=condition placeholder="As-is, good, etc."></div></div>')
        _sale_doc = f'Sale # <input value="{sale_no}" disabled class=w-xs>'
        _sale_date = f'<label>Date</label> <input type=date name=sale_date value="{today}" required class=w-sm>'
        return f"""
        <form method=post action="/sale/save" enctype="multipart/form-data">
          <input type=hidden name=sale_id value="{sale_no}">
          {self._form_head(con, _sale_doc, _sale_date, _sale_cust, [("Reference #", "")])}
          {self._line_head("Price")}
          <div class="lineitem-row" style="display:grid;grid-template-columns:104px 1fr 2fr 84px 104px 104px;gap:8px;align-items:start">
            <div><label>Type</label><select disabled><option selected>Item</option></select></div>
            <div><label>Item</label><select name=asset_id required><option value="">— Pick —</option>{aopts}</select></div>
            <div><label>Description</label><textarea name=item_desc class=ldesc rows=1 placeholder="Details"></textarea></div>
            <div><label>Qty</label><input name=qty type=number min=1 value=1 required class=w-xs></div>
            <div><label>Unit</label><select disabled><option selected>Each</option></select></div>
            <div><label>Price</label><span class="rate-x"><input name=amount type=number step=0.01 min=0.01 required class=w-sm><button type=button class=line-del title="Delete line item">✕</button></span></div>
          </div>
          <div><label>Notes</label><input name=notes style="width:100%"></div>
          {self._btn_row("Save", "salejobpop", add_item=True)}
          {self._job_info_popup('salejobpop', None, _sale_extra)}
          <div id="saleconfpop" style="display:none;position:fixed;top:8%;left:8%;right:8%;background:white;border:2px solid #333;padding:18px;z-index:1000;max-height:84%;overflow:auto">
            <h3 style="margin-top:0">Confirm sale <span style="float:right"><button type="button" onclick="document.getElementById('saleconfpop').style.display='none'">Close</button></span></h3>
            <p id="plant-confirm" hidden><label><input type=checkbox name=plant_confirm value=1>
            Confirm Plant sale — a Plant (fixed) asset is in this sale.</label></p>
            <p id="fleet-confirm" hidden><label><input type=checkbox name=fleet_confirm value=1>
            Confirm Fleet sale — a Fleet (rental) unit is in this sale.</label></p>
            <p><button type="submit" name="op" value="save">Confirm &amp; Save</button></p>
          </div>
        </form>
        {self._view_row("/sales/all", "Sales")}
        <script>
        (function(){{
          var form = document.querySelector('form[action="/sale/save"]');
          if (!form) return;
          // Sale Add Item (2026-10-16): each line row is one unit sold.
          // Clone the last line row, renumber asset_id/item_desc/qty/amount
          // to the next index, clear values. Capped at 8 rows: the backend
          // reads rows 0..7, so a 9th row would silently drop.
          function addItemRow(){{
            var rows = form.querySelectorAll('.lineitem-row');
            if (rows.length >= 8) return;
            var proto = rows[rows.length - 1];
            var clone = proto.cloneNode(true);
            var n = rows.length;
            clone.querySelectorAll('[name]').forEach(function(el){{
              el.name = el.name.replace(/\\d+$/, '') + n;
              if (el.name === 'qty' + n) el.value = '1';
              else if (el.tagName === 'SELECT') el.selectedIndex = 0;
              else el.value = '';
            }});
            clone.querySelectorAll('select[data-field]').forEach(function(el){{ el.dataset.field = el.name; }});
            proto.parentNode.insertBefore(clone, proto.nextSibling);
            var inp = clone.querySelector('input');
            if (inp) inp.focus();
            refreshConfirms();
          }}
          Array.prototype.forEach.call(form.querySelectorAll('button[type=button]'), function(b){{
            if (b.textContent.trim().toLowerCase() === 'add item') b.addEventListener('click', addItemRow);
          }});
          // Plant-sale and Fleet-sale double checks (Jason
          // 2026-10-24): each confirm row shows only while an asset
          // of its class is picked in some row, and hides (and
          // clears) when none is. The server enforces the same rules
          // at save, so neither check can be skipped by a crafted
          // post.
          var pcRow = document.getElementById('plant-confirm');
          var fcRow = document.getElementById('fleet-confirm');
          function refreshConfirms(){{
            var anyPlant = false, anyFleet = false;
            form.querySelectorAll('select[name^="asset_id"]').forEach(function(sel){{
              var opt = sel.options[sel.selectedIndex];
              if (opt && opt.getAttribute('data-desig') === 'Plant') anyPlant = true;
              if (opt && opt.getAttribute('data-desig') === 'Fleet') anyFleet = true;
            }});
            if (pcRow) pcRow.hidden = !anyPlant;
            if (!anyPlant && pcRow){{
              var cb = pcRow.querySelector('input[name=plant_confirm]');
              if (cb) cb.checked = false;
            }}
            if (fcRow) fcRow.hidden = !anyFleet;
            if (!anyFleet && fcRow){{
              var cb2 = fcRow.querySelector('input[name=fleet_confirm]');
              if (cb2) cb2.checked = false;
            }}
          }}
          form.addEventListener('change', function(e){{
            if (e.target.name && e.target.name.indexOf('asset_id') === 0) refreshConfirms();
          }});
          refreshConfirms();
          // Confirm-and-sign popup (Jason 2026-10-25, build 't',
          // universal form law): the Plant/Fleet confirms no longer
          // stand on the form — saving a sale that carries an
          // unconfirmed Plant or Fleet line opens the popup instead
          // of submitting; its Confirm & Save button submits with
          // the checks set. The server enforces the same rules, so
          // a crafted post without a check is still refused.
          var confPop = document.getElementById('saleconfpop');
          form.addEventListener('submit', function(e){{
            var pc = form.querySelector('input[name=plant_confirm]');
            var fc = form.querySelector('input[name=fleet_confirm]');
            var needP = pcRow && !pcRow.hidden && !(pc && pc.checked);
            var needF = fcRow && !fcRow.hidden && !(fc && fc.checked);
            if (needP || needF) {{
              e.preventDefault();
              if (confPop) confPop.style.display = 'block';
            }}
          }});
        }})();
        </script>
        """
        # Build 'r' (Jason 2026-10-25): the sales register no longer
        # renders below the form — it is the View popup's content
        # (/sales/all). _sales_list_html remains for other callers.

    def _sales_list_html(self, con):
        """Recorded sales by group (Jason 2026-10-23, universality):
        each sale — one submission, one or more unit rows — with its
        total and open balance; the row opens the sale's page, where
        money is taken against it."""
        try:
            groups = con.execute(
                """SELECT s.sale_group AS grp, MIN(s.sale_date) AS d,
                          COUNT(*) AS n, COALESCE(SUM(s.amount),0) AS tot,
                          COALESCE(c.account_name, s.customer_id) AS cust
                   FROM sales s
                   LEFT JOIN customers c ON c.id = s.customer_id
                   GROUP BY s.sale_group
                   ORDER BY d DESC, grp DESC LIMIT 50""").fetchall()
        except Exception:
            return ""
        if not groups:
            return ""
        rows = []
        for g in groups:
            bal = float(engine.doc_balance(con, "sale", g["grp"]))
            rows.append(
                f"<tr><td><a href=\"/sale/{html.escape(g['grp'], quote=True)}\">"
                f"{html.escape(g['grp'])}</a></td>"
                f"<td>{html.escape(fmt_date(g['d'] or ''))}</td>"
                f"<td>{html.escape(g['cust'] or '')}</td>"
                f"<td>{int(g['n'])}</td>"
                f"<td>${float(g['tot']):,.2f}</td>"
                f"<td>${bal:,.2f}</td></tr>")
        return ("<h2 style='font-size:16px;color:var(--frame)'>Sales</h2>"
                "<table><tr><th>Sale</th><th>Date</th><th>Customer</th>"
                "<th>Lines</th><th>Total</th><th>Balance</th></tr>"
                + "".join(rows) + "</table>")

    def view_sale_detail(self, con, grp):
        """Summary of Sale# (build 'u', Jason 2026-10-25, universal
        summary pattern): the sale's facts stated — customer, date,
        ref, its unit rows, totals, notes (the confirm stamps ride
        in the rows' notes), record stamps — and its money panel
        behind the Payment popup door. A sale has no edit form (the
        Sale tab is a creation form), so the summary carries no Edit
        door; its Print door is the page print menu, as on the Sale
        form (a sale has no print pack)."""
        try:
            rows = con.execute(
                """SELECT s.*, COALESCE(a.unit_no,'') AS unit_no,
                          COALESCE(c.account_name, '') AS cust
                   FROM sales s
                   LEFT JOIN assets a ON a.id = s.asset_id
                   LEFT JOIN customers c ON c.id = s.customer_id
                   WHERE s.group_id=? ORDER BY s.seq, s.id""",
                (engine.doc_key(con, "sale", grp),)).fetchall()
        except Exception:
            rows = []
        if not rows:
            return '<div class="err">Unknown sale.</div>'
        head = rows[0]
        body = "".join(
            f"<tr><td>{html.escape(r['unit_no'] or '')}</td>"
            f"<td>{html.escape(r['item_desc'] or '')}</td>"
            f"<td>{float(r['qty'] or 0):g}</td>"
            f"<td>${float(r['amount'] or 0):,.2f}</td></tr>"
            for r in rows)
        lines_html = ("<table><tr><th>Unit</th><th>Description</th>"
                      f"<th>Qty</th><th>Price</th></tr>{body}</table>")
        _set = engine.doc_settled(con, "sale", grp)
        _notes = []
        for r in rows:
            _n = (r["notes"] or "").strip() if "notes" in r.keys() else ""
            if _n and _n not in _notes:
                _notes.append(_n)
        facts = [
            ("Customer", html.escape(head["cust"] or "")),
            ("Date", html.escape(fmt_date(head["sale_date"] or ""))),
            ("Associated", self._assoc_co_fact(con, "sale", grp)),
            ("Ref", html.escape(self._g(head, "ref_no"))
             if self._g(head, "ref_no") else None),
            ("Total", f"${float(engine.doc_total(con, 'sale', grp)):,.2f}"),
            ("Settled", f"${float(_set['total']):,.2f}"),
            ("Balance", f"${float(engine.doc_balance(con, 'sale', grp)):,.2f}"),
            ("Notes", html.escape(" · ".join(_notes)) if _notes else None),
            ("Input by:", f"{html.escape(str(self._g(head, 'clerk') or ''))} "
                          f"{html.escape(fmt_datetime(self._g(head, 'created_at')))}".strip()),
        ]
        pay_door, pay_popup = self._money_popup(
            con, "sale", grp,
            engine.cust_code(con, head["customer_id"]) or "")
        doors = pay_door + self._print_menu(page=True)
        return self._sum_page(
            "Sale", grp, facts, lines_html, doors, pay_popup,
            "/sales/all", "Sales")
