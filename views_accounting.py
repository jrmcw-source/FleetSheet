from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import html
import json
from datetime import date, timedelta
from urllib.parse import parse_qs, quote, quote_plus, urlparse

import engine

"""FleetSheet views — accounting flow: quotes, invoices, payments, credit, petty cash, reports."""

from views_core import (
    format_phone,
    _ack_forms,
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
    opts,
    lan_urls,
    _nav_section,
    money_val,
    note_pop_html,
    quote_expiry_panel,
    task_nudge,
    _task_from_row,
    more_link,
    DASH_CAP,
    view_button,
    AUDIT_TABLE_JS,
    AUDIT_POPUP_HTML,
    AUDIT_POPUP_JS,
    NOTE_POPUP_JS,
    COMBO_JS,
    news_strip,
    capped_table,
    combo_field,
    combo_opts,
    state_field,
    fmt_date,
    fmt_datetime,
    enabled_values,
    chain_banner,
    chain_banner_rerun,
    CoreViews,)


# ---------------------------------------------------------------- Item
# suggestions (Items E/F, Spec Update 7): curation lives in Setup. The
# MASTER inv_item list (47 seeded presets + operator-added values) lives
# in the book's lookups table; editors suggest only the book's ENABLED
# subset (views_core.enabled_values — book option "enabled_inv_item",
# factory-on core when unset), plus active assets' unit numbers (the
# equipment pull-up — the book's own equipment, not curation), plus the
# record's current value when it is off-set, so a stored string is
# never hidden. The Item field stays free text; the datalist is a
# suggestion list, never a cage. Adding values happens in Setup only.
ITEM_LIST_ID = "fs_item_list"


def _item_suggestions(con, current=""):
    """Item datalist values for editors: enabled inv_item values, then
    active assets' unit numbers, then the current value if off-set.
    De-duplicated, order preserved."""
    vals = list(enabled_values(con, "inv_item"))
    try:
        vals += [r["unit_no"] for r in con.execute(
            "SELECT unit_no FROM assets WHERE active=1 "
            "AND COALESCE(status,'Active')='Active' ORDER BY unit_no")]
    except Exception:
        pass
    cur = (current or "").strip()
    if cur:
        vals.append(cur)
    seen, out = set(), []
    for v in vals:
        v = (v or "").strip()
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _item_datalist(con, current=""):
    opts = "".join(
        f"<option value=\"{html.escape(v, quote=True)}\"></option>"
        for v in _item_suggestions(con, current))
    return f'<datalist id="{ITEM_LIST_ID}" data-item-list>{opts}</datalist>'


def _item_extras(con, current=""):
    """The shared Item datalist. It lives OUTSIDE any cloned line row —
    the Add Item JS clones the row; a datalist inside would duplicate
    ids. Cloned rows keep the same list attribute and keep working."""
    return _item_datalist(con, current)


class AccountingViews(CoreViews):
    """FleetSheet views views mixed into Handler."""

    def _btn_row(self, save_label="Save", jobpop=None, add_item=False, extra="",
                 submit_name="", submit_value="", print_menu=None):
        from views_core import CoreViews
        return CoreViews._btn_row(self, save_label, jobpop, add_item, extra,
                                  submit_name, submit_value, print_menu)

    def _top_commit(self, label, name="", value=""):
        from views_core import CoreViews
        return CoreViews._top_commit(self, label, name, value)

    def _job_info_popup(self, pid, vals=None, extra=""):
        from views_core import CoreViews
        return CoreViews._job_info_popup(self, pid, vals, extra)

    def _frag_invoice_form(self, con, edit_ino=None):
        # Edit mode (2026-10-21): Save on this form lands back here with
        # ?edit=<invoice_no> — the same editor, prefilled with the saved
        # invoice, so a further Save updates it in place (the bathroom
        # test: work in progress is never lost, never duplicated).
        inv = None
        if edit_ino:
            inv = con.execute("SELECT * FROM invoices WHERE invoice_no=?",
                              (edit_ino,)).fetchone()
            if not inv:
                return f"<p>Unknown invoice {html.escape(edit_ino)}.</p>"
            # Build 'v': the row's customer_id is the engine key; the
            # form's customer combo speaks the customer's code.
            inv = dict(inv)
            inv["customer_id"] = (engine.cust_code(con, inv["customer_id"])
                                  or "")
            if engine.invoice_locked(con, edit_ino):
                return (f"<p>Invoice {html.escape(edit_ino)} is locked (sent, paid, "
                        f"or has payments) and can't be edited here. "
                        f"<a href=\"/invoice/{html.escape(edit_ino, quote=True)}\">"
                        f"Open the invoice</a>.</p>")
        ready = con.execute(
            """SELECT t.ticket_id, t.customer_id, c.account_name, a.unit_no, t.in_condition
               FROM tickets t JOIN customers c ON c.id = t.customer_id
               JOIN assets a ON a.id = t.asset_id
               WHERE t.status IN ('Ready to Bill','Off Rent') AND t.invoice_id IS NULL
               ORDER BY t.customer_id"""
        ).fetchall()
        wos = engine.ready_work_orders(con)
        # No gate (Jason 2026-10-14): the form always renders, and a
        # standalone invoice is legal at the engine level — the chain
        # is a chain, not a cage. Shop-flow round (2026-10-21): the form
        # no longer introduces itself with the chain's leftovers — no
        # "nothing ready to bill" hint above the form. Build 'r'
        # (2026-10-25): the ready-work pickers render INSIDE the form,
        # above the button row — the form ends at its button row, and
        # only the universal View row stands below it.
        hint = ""
        # Tickets whose return condition was never recorded are named
        # right on their checkbox (only while the condition switch is
        # on — with it off, the gate never fires and the note is noise).
        _cond_on = engine.module_on(con, "condition")
        def _tlabel(r):
            note = (" — no check-in condition"
                    if _cond_on and not r["in_condition"] else "")
            return (f"<label><input type=checkbox name=t__{html.escape(r['ticket_id'])} value=1> "
                    f"{html.escape(r['ticket_id'])} · {html.escape(r['account_name'])} · {html.escape(r['unit_no'])}{note}</label>")
        boxes = "".join(_tlabel(r) for r in ready[:5])
        if len(ready) > 5:
            boxes += f"<p class='mute'>+ {len(ready) - 5} more</p>"
        _any_nocond = _cond_on and any(not r["in_condition"] for r in ready)
        wboxes = "".join(
            f"<label><input type=checkbox name=w__{html.escape(r['wo_id'])} value=1> "
            f"{html.escape(r['wo_id'])} · {html.escape(r['account_name'])} · {html.escape(r['unit_no'])} · "
            f"{html.escape(r['work_type'])} · ${float(r['bill_amount']):,.2f}</label>"
            for r in wos
        )
        # Global line-item row (2026-10-15): Type (inv_cat) + Unit (inv_uom)
        # on the quick lines; row 0 is a real invoice line now, not
        # quick_* columns nothing reads.
        type_opts = lookup_select(con, "inv_cat", "type", blank=True)
        uom_opts = lookup_select(con, "inv_uom", "uom", blank=True,
                                 vals=enabled_values(con, "inv_uom"),
                                 add_option=False)  # editors: enabled set only (Spec 7)
        # Customer picker lists ALL customers, not just ones with ready
        # work — otherwise the form is unusable on a fresh database.
        custs = {r["customer_id"]: r["account_name"] for r in con.execute(
            "SELECT customer_id, account_name FROM customers ORDER BY account_name").fetchall()}
        # Tax-toggle defaults (Invoice Round Part C, Jason update 6):
        # a customer is exempt when EITHER source says so — (a) the
        # customer-wide flag customers.tax_exempt, or (b) a tax-exempt
        # certificate on the customer's file. The certificate store
        # the app has is invoice_docs: a doc of kind='tax_exempt'
        # attached to any invoice of that customer (there is no
        # customer-level certificate table/column in the schema).
        # Rendered into the form's script as a {customer_id: bool} map;
        # picking an exempt customer defaults every line's Tax toggle
        # OFF, everyone else defaults ON.
        _cust_exempt = {cid: False for cid in custs}
        try:
            for r in con.execute(
                    "SELECT customer_id, tax_exempt FROM customers"):
                if r["customer_id"] in _cust_exempt and r["tax_exempt"]:
                    _cust_exempt[r["customer_id"]] = True
        except Exception:
            pass
        try:
            for r in con.execute(
                    """SELECT DISTINCT c.customer_id AS cid
                       FROM invoices i
                       JOIN customers c ON c.id = i.customer_id
                       JOIN invoice_docs d ON d.invoice_id=i.id
                       WHERE d.kind='tax_exempt'"""):
                if r["cid"] in _cust_exempt:
                    _cust_exempt[r["cid"]] = True
        except Exception:
            pass
        _cust_exempt_js = json.dumps(_cust_exempt)
        _cust_terms = {}
        try:
            _cust_terms = {r["customer_id"]: (r["terms"] or "")
                           for r in con.execute(
                               "SELECT customer_id, terms FROM customers")}
        except Exception:
            _cust_terms = {}
        _cust_terms_js = json.dumps(_cust_terms)
        if not custs:
            hint += '<p class="hint">No customers yet. <a href="/customer/new">→ Add a customer</a> before creating an invoice.</p>'
        cust_combo = (
            combo_field("f_inv_cust", "customer_id_text",
                        [(k, v, k) for k, v in custs.items()],
                        value=(custs.get(inv["customer_id"], "")
                               if inv is not None else ""),
                        label="Customer", required=True,
                        placeholder="Type to search customers…")
            + (f'<input type=hidden id="f_inv_cust_id" name=customer_id '
               f'value="{html.escape(inv["customer_id"], quote=True) if inv is not None else ""}">')
        )
        today = date.today().isoformat()
        inv_no = engine.peek_next_invoice_no(con)
        if inv is not None:
            inv_no = inv["invoice_no"]
        date_val = inv["invoice_date"] if inv is not None else today
        # Tax is NEVER prefilled (Jason 2026-10-04): the software does not infer tax.
        # Blank = no tax; the operator enters the rate explicitly.
        tax_pct = ""
        # Document layout (Invoice Round Part B): the editor page
        # mirrors the NEW printed invoice's arrangement — company band
        # (name + address only, no remit label, no phone / billing
        # email), no centered "Invoice" title, Date / number line with
        # the Job Info preview box in the right column under it, a
        # Bill To panel only (no Ship To panel), and a signature /
        # notes preview block bottom-left beside the totals column.
        # All input names and form mechanics are unchanged.
        _co = self.company(con)
        _def_terms = (self._g(_co, "default_terms") or "Net 30")
        terms_sel = lookup_select(con, "terms", "terms",
                                  current=(inv["terms"] if inv is not None and inv["terms"] else _def_terms),
                                  vals=enabled_values(con, "terms"),
                                  add_option=False)  # editors: enabled set only (Spec 7)
        # The on-screen Job Info PREVIEW box is gone (build 'r',
        # Jason 2026-10-25): it rendered the configured field labels
        # with permanently empty values — decoration, not data. The
        # real fields live in the Job Info popup; the printed Job
        # Info box is unchanged.
        # Line rows + pick section + prefill values (2026-10-21). New
        # mode renders exactly what it always did: one blank row and the
        # ticket / work-order pick panels. Edit mode renders the saved
        # invoice's own free-typed lines (source_type='quick' — the
        # lines this form owns), and the pick panels give way to a
        # read-only list of the lines that arrived from tickets / work
        # orders: those were billed in at create time and stay as they
        # are, exactly as before this form could be re-opened.
        def _iline(i, ln=None):
            sfx = "" if i == 0 else str(i)
            tsel = lookup_select(con, "inv_cat", f"type{sfx}", blank=True,
                                 current=(self._g(ln, "category") if ln else ""))
            usel = lookup_select(con, "inv_uom", f"uom{sfx}", blank=True,
                                 vals=enabled_values(con, "inv_uom"),
                                 add_option=False,
                                 current=(self._g(ln, "uom") if ln else ""))
            item = html.escape(self._g(ln, "item"), quote=True) if ln else ""
            desc = html.escape(self._g(ln, "description")) if ln else ""
            qty = f"{float(ln['qty']):g}" if ln else "1"
            rate = f"{float(ln['rate']):g}" if ln else "0"
            tax = " checked" if (ln is None or not ln["tax_exempt"]) else ""
            return (f'<div class="iline">'
                    f'<div><label>Type</label>{tsel}</div>'
                    f'<div><label>Item</label><input name=item{sfx} list="fs_item_list" value="{item}"></div>'
                    f'<div><label>Description</label><textarea name=item_desc{sfx} class=ldesc rows=1>{desc}</textarea></div>'
                    f'<div><label>Qty</label><input name=qty{sfx} class="iqty w-xs" type=number step=0.01 value={qty}></div>'
                    f'<div><label>Unit</label>{usel}</div>'
                    f'<div><label>Rate $</label><span class="rate-x"><input name=rate{sfx} class="irate w-sm" type=number step=0.01 value={rate}><button type=button class=line-del title="Delete line item">✕</button></span><label style="display:block;margin-top:4px"><input type=checkbox name=taxable{sfx} value=1{tax} class=itaxable> Tax</label></div>'
                    f'</div>')
        def _invf(key):
            try:
                return float(inv[key] or 0)
            except Exception:
                return 0.0
        if inv is not None:
            hint = ""
            _el = con.execute(
                "SELECT * FROM invoice_lines WHERE invoice_id=? "
                "AND source_type='quick' ORDER BY line_id",
                (inv["id"],)).fetchall()
            line_rows_html = ("".join(_iline(i, ln) for i, ln in enumerate(_el))
                              or _iline(0))
            _src = con.execute(
                "SELECT description, amount FROM invoice_lines "
                "WHERE invoice_id=? AND source_type IN ('ticket','work_order') "
                "ORDER BY line_id", (inv["id"],)).fetchall()
            if _src:
                _items = "".join(
                    f"<div>{html.escape(r['description'] or '')} — "
                    f"${float(r['amount']):,.2f}</div>" for r in _src)
                pick_section = (
                    f'<div style="border:1px solid #c5cdd6;padding:10px">'
                    f'<div style="font-size:10px;color:#5C6B7A;text-transform:uppercase">'
                    f'Already on this invoice — from Rental Tickets / Work Orders</div>'
                    f'{_items}'
                    f'<p class="hint" style="margin:6px 0 0">Read-only.</p></div>')
            else:
                pick_section = ""
            editing_hidden = '<input type=hidden name=editing value="1">'
            tax_pct = f"{_invf('tax_rate') * 100:g}"
            job_vals = {"po": self._g(inv, "po"),
                        "contact_name": self._g(inv, "contact_name")}
        else:
            line_rows_html = _iline(0)
            # "Add from ready work" (shop-flow round, Jason 2026-10-21):
            # the pickers move BELOW the button row (the template slot
            # moved with them), under their own quiet heading, and each
            # panel renders only when its module is on AND it has
            # something in it — no more "None waiting" panels. Both
            # empty/off = the whole section is gone and New Invoice is
            # a clean, single-purpose form.
            _panels = ""
            if engine.module_on(con, "rentals") and boxes:
                _panels += f"""
            <div>
              <h2 style="font-size:16px;color:var(--frame)">Rental Tickets</h2>
              {boxes}
            </div>"""
            if engine.module_on(con, "work_orders") and wboxes:
                _panels += f"""
            <div>
              <h2 style="font-size:16px;color:var(--frame)">Billable Work Orders</h2>
              {wboxes}
            </div>"""
            _proceed = ("""
            <p style="margin:8px 0 0"><label><input type=checkbox name=proceed value=1>
            Proceed anyway — bill a ticket marked "no check-in condition" without one.</label></p>"""
                        if _any_nocond and _panels else "")
            # Collapsed by default (Jason 2026-10-24, 'm' look-see
            # item 10): the pick list is a door, not a box spread
            # under the form — one line until the operator opens it.
            pick_section = (f"""
          <details style="margin-top:16px">
            <summary style="font-size:16px;color:var(--frame);font-weight:700;cursor:pointer">Add from ready work</summary>
            <div class="fgrid">{_panels}
            </div>{_proceed}
          </details>""" if _panels else "")
            editing_hidden = ""
            job_vals = None
        ref_attr = (f' value="{html.escape(self._g(inv, "ref_ticket"), quote=True)}"'
                    if inv is not None else "")
        bar_attr = (f' value="{html.escape(self._g(inv, "bar_text"), quote=True)}"'
                    if inv is not None else "")
        ship_attr = (f' value="{html.escape(self._g(inv, "shipped_by"), quote=True)}"'
                     if inv is not None else "")
        adj_val = f"{_invf('adjustment'):g}" if inv is not None else "0"
        adj_label_attr = (f' value="{html.escape(self._g(inv, "adj_label"), quote=True)}"'
                          if inv is not None else "")
        adj_tax_chk = " checked" if (inv is not None and self._g(inv, "adj_taxable")) else ""
        exempt_chk = " checked" if (inv is not None and self._g(inv, "tax_exempt_op")) else ""
        # Header zone (build 'r', Jason 2026-10-25, facelift item 4;
        # two-row form build 't', same day, universal form law):
        # Company block, Invoice # + Date, bar, Customer block left,
        # Job Info box right — then the lines. Reference Ticket,
        # Terms, Header bar note, and Transport live in the Job Info
        # popup (extra, same names, save with the form). The
        # display-only Contact Name span is removed — it was never an
        # input; the popup's Contact Name field is the live one the
        # save reads.
        _inv_extra = f"""
            <div class="row">
              <div><label>Reference Ticket</label><input name=ref_ticket class=w-sm placeholder="Optional"{ref_attr}></div>
              <div><label>Terms</label>{terms_sel}</div>
            </div>
            <div class="row">
              <div><label>Header bar note</label><input name=bar_text placeholder="Header note"{bar_attr}></div>
              <div><label>Transport</label><input name=shipped_by list="inv-shipped-by" placeholder="Customer, company, or carrier…"{ship_attr}><datalist id="inv-shipped-by"><option value="Customer Transport"></option><option value="Company Transport"></option></datalist></div>
            </div>"""
        _inv_doc = (f'Invoice # <a href="/invoice/{inv_no}">{inv_no}</a>'
                    if inv is not None else
                    f'Invoice # <input name=invoice_no value="{inv_no}" class=w-xs>')
        _inv_date = f'<label>Date</label> <input type=date name=invoice_date value="{date_val}" class=w-sm>'
        _inv_cust = ('<div style="font-size:10px;color:#5C6B7A;'
                     'text-transform:uppercase">Billing Address</div>'
                     + cust_combo)
        # Header Row 2 right (build 't', Jason 2026-10-25, universal
        # form law): the Job Info box — the same fields the printed
        # box carries, from the same source (invoice_job_box: the
        # invoice's own PO; job/well/location derived from its
        # tickets). A new invoice has none yet — dashes, the printed
        # box's convention. The Job Info popup edits what this form
        # owns (PO # among them).
        if inv is not None:
            _jb = engine.invoice_job_box(con, inv_no)
            _inv_job_lines = [
                ("PO #", _jb.get("po") or ""),
                ("Job Name", ", ".join(_jb.get("jobs") or [])),
                ("Job Location", ", ".join(_jb.get("locations") or [])),
                ("Well #", ", ".join(_jb.get("wells") or []))]
        else:
            _inv_job_lines = [("PO #", ""), ("Job Name", ""),
                              ("Job Location", ""), ("Well #", "")]
        return f"""
        {hint}
        <form method=post action="/invoice/create" enctype="multipart/form-data">
          {f'<input type=hidden name=invoice_no value="{inv_no}">' if inv is not None else ''}
          <input type=hidden name=tax_ui value="1">
          {editing_hidden}
          {self._form_head(con, _inv_doc, _inv_date, _inv_cust, _inv_job_lines)}
          <div id="inv-lines">
            {self._line_head()}
            {line_rows_html}
          </div>
          <div style="display:flex;flex-wrap:wrap;gap:24px;align-items:flex-start;margin-top:8px">
            <div id="inv-totals" style="text-align:right;margin-left:auto">
              <div>Write-in <input name=adj_label placeholder="Describe (optional)" class=w-sm style="width:150px;display:inline-block"{adj_label_attr}> <input name=adjustment id="inv-adj" type=number step=0.01 value={adj_val} class=w-xs style="width:96px;display:inline-block"> <label><input type=checkbox name=adj_taxable id="inv-adjtax" value=1{adj_tax_chk}> Tax</label></div>
              <div>Subtotal <b id="inv-sub">$0.00</b></div>
              <div>Tax <input name=tax_rate id="inv-taxrate" type=number step=0.01 value="{tax_pct}" class=w-xs style="width:76px;display:inline-block">% <b id="inv-tax">$0.00</b></div>
              <div><label><input type=checkbox name=tax_exempt_op id="inv-taxexempt" value=1{exempt_chk}> Tax-exempt</label></div>
              <div>Total <b id="inv-grand">$0.00</b></div>
            </div>
          </div>
          <div><label>Notes</label><input name=notes style="width:100%"></div>
          {pick_section}
          {self._btn_row("Save", "invjobpop", add_item=True, submit_name="action", submit_value="save", print_menu=(self._print_menu(screen=f"/print/invoice/{inv_no}", pdf=f"/print/invoice/{inv_no}.pdf") if inv is not None else None))}
          {self._job_info_popup('invjobpop', job_vals, _inv_extra)}
        </form>
        {self._view_row("/money/invoices/audit", "Invoices")}
        <script>
        (function(){{var box=document.getElementById('inv-lines'); if(!box)return; var form=box.closest('form');
        var custExempt={_cust_exempt_js}; var custTerms={_cust_terms_js}; var curCustExempt=false;
        function num(v){{v=parseFloat(v); return isNaN(v)?0:v;}}
        function isFreight(v){{return (v||'').trim().toLowerCase().indexOf('freight')===0;}}
        function rowType(r){{var s=r.querySelector('select[data-kind="inv_cat"]'); return s?s.value:'';}}
        function applyRowDefault(r){{var cb=r.querySelector('.itaxable'); if(!cb)return; cb.checked=isFreight(rowType(r))?false:!curCustExempt;}}
        function calc(){{var sub=0, base=0; box.querySelectorAll('.iline').forEach(function(r){{var q=r.querySelector('.iqty'),rt=r.querySelector('.irate'); var amt=num(q&&q.value)*num(rt&&rt.value); sub+=amt; var cb=r.querySelector('.itaxable'); if(cb&&cb.checked)base+=amt;}}); var adj=num(document.getElementById('inv-adj').value); sub+=adj; var atx=document.getElementById('inv-adjtax'); if(atx&&atx.checked)base+=adj; var tr=num(document.getElementById('inv-taxrate').value)/100; var exop=document.getElementById('inv-taxexempt'); var tax=(exop&&exop.checked)?0:base*tr, grand=sub+tax; document.getElementById('inv-sub').textContent='$'+sub.toFixed(2); document.getElementById('inv-tax').textContent='$'+tax.toFixed(2); document.getElementById('inv-grand').textContent='$'+grand.toFixed(2);}}
        form.addEventListener('input',calc); form.addEventListener('change',calc); calc(); window.__invCalc=calc;
        form.addEventListener('change',function(e){{var t=e.target; if(t&&t.matches&&t.matches('select[data-kind="inv_cat"]')){{var r=t.closest('.iline'); if(r){{applyRowDefault(r); calc();}}}}}});
        var custText=document.getElementById('f_inv_cust');
        function syncCust(){{setTimeout(function(){{var hid=document.getElementById('f_inv_cust_id'); var cid=hid?hid.value:''; if(!cid&&custText){{var dl=document.getElementById('f_inv_cust_list'); if(dl){{Array.prototype.forEach.call(dl.options,function(o){{if(o.value.trim()===custText.value.trim())cid=o.getAttribute('data-id')||'';}});}}}} curCustExempt=!!(cid&&custExempt[cid]); var tsel=document.querySelector('select[name="terms"]'); if(tsel&&cid&&custTerms[cid]){{var tv=custTerms[cid]; var has=false; Array.prototype.forEach.call(tsel.options,function(o){{if(o.value===tv)has=true;}}); if(!has){{var no=document.createElement('option'); no.value=tv; no.text=tv; tsel.appendChild(no);}} tsel.value=tv; tsel.dispatchEvent(new Event('change',{{bubbles:true}}));}} box.querySelectorAll('.iline').forEach(applyRowDefault); calc();}},0);}}
        if(custText){{custText.addEventListener('input',syncCust); custText.addEventListener('change',syncCust);}}
        var btn=null; form.querySelectorAll('button[type=button]').forEach(function(b){{if(b.textContent.trim().toLowerCase()==='add item')btn=b;}}); if(!btn)return;
        btn.addEventListener('click',function(){{var rows=box.querySelectorAll('.iline'); var n=rows.length; var c=rows[0].cloneNode(true);
        c.querySelectorAll('[name]').forEach(function(el){{var base=el.name.replace(/\\d+$/,''); el.name=base+n;}});
        c.querySelectorAll('input,textarea').forEach(function(el){{if(el.classList.contains('itaxable')){{el.checked=!curCustExempt; el.value='1';}} else if(el.classList.contains('iqty'))el.value='1'; else if(el.classList.contains('irate'))el.value='0'; else el.value='';}});
        c.querySelectorAll('select').forEach(function(el){{el.selectedIndex=0;}});
        box.appendChild(c); calc();}});}})();
        </script>
        """ + _item_extras(con)

    # --- Billing: the place row is Invoices, Payments, Credit Memos,
    # Cash (Jason 2026-10-24 door grammar: tabs are places, creating
    # is an action). Petty Cash is not here — it lives under
    # Administration. Each place runs: form → capped list with a
    # View-all audit pop-up behind its View door.

    def view_invoice_new(self, con, q=None):
        """The invoice editor page: the blank invoice editor — the
        full page, nothing else on it. The Invoices place
        (/money?tab=invoice) lands on this same blank editor (build
        't', Jason 2026-10-25 — the tab is the door; there is no New
        Invoice button anywhere). ?edit=<invoice_no> re-opens the
        SAME editor on a saved invoice (the Save landing,
        2026-10-21)."""
        edit = ((q or {}).get("edit") or "").strip()
        engine.stamp_module_seen(con, "billing")
        return tabs_money("invoice", con) + self._frag_invoice_form(con, edit or None)

    def view_money(self, con, q=None):
        tab = (q or {}).get("tab") or "invoice"
        # Petty left the money tabs (Jason 2026-10-24): the drawer
        # lives under Administration now — one door, /petty.
        if tab == "petty":
            return self._redirect("/petty")
        if tab not in ("invoice", "pay", "credit", "cash"):
            tab = "invoice"
        if not engine.module_on(con, "billing"):
            # The route never dies (shop-flow, Jason 2026-10-21): with
            # billing off the section home is a plain note plus the Done
            # box, same as Compliance. Invoices, payments, credits and
            # petty-cash records are untouched and return, intact, when
            # the switch flips back on; the audit lists stay reachable
            # behind the View button below.
            return ("<p>Billing is off.</p>"
                    + self._view_door("/money/audit", "All money — audit"))
        engine.stamp_module_seen(con, "billing")
        if tab == "invoice":
            # Landing (Jason 2026-10-25, build 't' — SUPERSEDES the
            # 2026-10-24 'm'/'n' landing on the most recent invoice):
            # the Invoices place opens to a BLANK invoice, the way
            # Payments and Credit Memos open to their blank forms.
            # The tab is the door — there is no New Invoice button
            # anywhere; existing invoices open through the View list.
            # (The form fragment carries the universal View row
            # itself; no second door stands on the tab page.)
            return (tabs_money(tab, con)
                    + self._frag_invoice_form(con, None))
        return tabs_money(tab, con) + self._money_tab(con, tab, q or {})

    def _money_tab(self, con, tab, q):
        if tab == "pay":
            body = self._money_pay(con)
            view_url, view_title = "/money/payments/audit", "Payments — audit"
        elif tab == "credit":
            body = self._money_credit(con, q)
            view_url, view_title = "/money/credits/audit", "Credit memos — audit"
        elif tab == "cash":
            body = self._money_cash(con)
            view_url, view_title = "/money/cash/audit", "Cash — audit"
        else:
            body = self._money_picture(con)
            view_url, view_title = "/money/invoices/audit", "Invoices — audit"
        return body + self._view_door(view_url, view_title)

    def _money_picture(self, con):
        ticker = ''
        # The money picture (review Finding B; human framework —
        # judge first, then dig in), at the top of the Invoices list
        # page since 2026-10-24: the register it summarizes. The
        # create form is the dig-in step, reached from the Invoices
        # tab itself (build 't', Jason 2026-10-25: the tab is the
        # door — the New Invoice button that stood in this picture
        # is removed; the Invoices place opens to a blank invoice).
        ag = engine.ar_aging(con)
        open_total = ag["grand"]
        overdue_total = open_total - ag["total"].get("current", 0.0)
        open_count = sum(
            1 for r in con.execute(
                "SELECT invoice_no FROM invoices "
                "WHERE status NOT IN ('Paid','Write-off','Draft')")
            if engine.invoice_totals(con, r["invoice_no"])["balance"] > 0.009)
        overdue_cls = " class='fail'" if overdue_total > 0.009 else ""
        # Open Change Orders in the money picture (build 'v', Jason
        # 2026-10-25): a Change Order is a receivable alongside the
        # invoices — its open balance states here as its own card.
        _co_open = 0
        _co_total = 0.0
        try:
            for r in con.execute(
                    "SELECT co_no FROM change_orders WHERE status='Issued'"):
                _b = float(engine.doc_balance(con, "change", r["co_no"]))
                if _b > 0.009:
                    _co_open += 1
                    _co_total += _b
        except Exception:
            _co_open, _co_total = 0, 0.0
        _co_card = (
            f"<div class='card'><span>Open change orders</span>"
            f"<b>{_co_open} · ${_co_total:,.2f}</b></div>"
            if _co_open else "")
        picture = (
            "<div class='cards'>"
            f"<div class='card'><span>Open balance</span><b>${open_total:,.2f}</b></div>"
            f"<div class='card'><span>Overdue</span><b{overdue_cls}>${overdue_total:,.2f}</b></div>"
            f"<div class='card'><span>Open invoices</span><b>{open_count}</b></div>"
            f"{_co_card}"
            "</div>")
        return ticker + picture

    def _money_pay(self, con):
        ticker = ''
        return ticker + self._frag_pay_form(con)

    def _money_credit(self, con, q):
        ticker = ''
        return ticker + self._frag_credit_form(con, q)

    def view_petty(self, con, q=None):
        """Petty cash drawer (Jason 2026-10-24): sealed from the money
        system — reached from Administration's Petty Cash button (the
        standard popup, ?frag=1). The full-page render of this route
        stands (direct address), but the popup carries no Full Page
        door (Jason 2026-10-25, build 'w'). Never a money tab, never
        under Billing."""
        frag = (q or {}).get("frag") == "1"
        # Full page only: the drawer is an Admin-section working page, so
        # it carries the Admin sub-tab row with Administration lit
        # (Jason 2026-10-24). The fragment is chrome-less by design.
        tabs = "" if frag else tabs_admin("/petty")
        return tabs + self._money_petty(con, frag=frag)

    def _money_petty(self, con, frag=False):
        ticker = ''
        book = engine.petty_book(con)
        # Fragment mode (the Admin popup iframe) has no page bundle:
        # forms stay in the frame (target=_self + frag=1 so the save
        # redirects back into it), the float popover's Refresh/Close
        # mini buttons become a plain inline Close (the popup bar
        # already carries Refresh), and the Done box's buttons become
        # plain links (no nested audit popup inside a fragment).
        _ftarget = ' target="_self"' if frag else ''
        _fhidden = '<input type=hidden name=frag value="1">' if frag else ''
        _float_btns = (
            "<button type='button' class='mini' "
            "onclick=\"document.getElementById('floatpop').style.display='none'\">Close</button>"
            if frag else
            "<button type='button' class='mini' onclick='refreshFloatpop()'>Refresh</button>"
            "<button type='button' class='mini' onclick='closeFloatpop()'>Close</button>")
        # Slim strip, no company band — the popup bar already titles
        # the drawer, and the full page's title does the same.
        header = (
            "<div style=\"display:flex;flex-wrap:wrap;gap:24px\">"
            + "<div style=\"margin-left:auto;text-align:right\">"
            + ("<p class='actions' style='margin:0 0 6px'><a class='btn secondary' href='/print/petty' target='_blank' rel='noopener'>Print</a></p>" if not frag else "")
            + "<div style=\"font-size:10px;color:#5C6B7A;text-transform:uppercase\">Next entry</div>"
            + f"<div style=\"font-size:20px;font-weight:700\">{html.escape(engine.next_pc_id(con))}</div>"
            + f"<div>{html.escape(fmt_date(date.today()))}</div>"
            + "</div></div>")
        cards = (
            f"<div class='cards'>"
            f"<div class='card'><span>In the box</span><b>${book['balance']:,.2f}</b></div>"
            f"<div class='card'><span>Target float</span><b>${book['target']:,.2f}</b> "
            f"<a href='#' style='font-size:11px' onclick=\"document.getElementById('floatpop').style.display=document.getElementById('floatpop').style.display=='none'?'block':'none';return false\">Change</a>"
            f"<div id='floatpop' style='display:none;margin-top:6px'><form method=post action='/petty/float'{_ftarget} style='display:flex;gap:4px'>"
            f"{_fhidden}"
            f"<input name=pc_float type=number step=0.01 min=0 class=w-sm value=\"{book['target']:.2f}\" style='width:90px'>"
            f"<button class='mini'>Set</button>"
            f"{_float_btns}</form></div></div>"
            f"<div class='card'><span>To replenish</span><b>${book['to_replenish']:,.2f}</b></div>"
            f"</div>")
        # Register in the drawer (Jason 2026-10-24, screenshot read):
        # the Cash tab lists its entries right under its form, but
        # Petty showed balances + blank forms only — the drawer's
        # contents lived solely on the audit page. A drawer shows
        # what's in the drawer. Same rows as the audit register,
        # filterable + sortable like every audit table.
        _reg_rows = "".join(
            f"<tr><td>{html.escape(fmt_date(r['txn_date']))}</td>"
            f"<td>{html.escape(r['direction'])}</td>"
            f"<td>{html.escape(r['category'])}</td>"
            f"<td>{html.escape(r['payee'])}</td>"
            f"<td>${r['signed']:,.2f}</td><td>${r['running']:,.2f}</td>"
            f"<td>{html.escape(r['ref_no'])}</td><td>{note_pop_html(r['notes'])}</td></tr>"
            for r in book["rows"])
        register = (
            "<h2 style=\"font-size:16px;color:var(--frame)\">Petty cash register</h2>"
            "<p class=\"hint\"><input id=\"auditq\" placeholder=\"Filter\" size=\"30\" "
            "oninput=\"document.querySelectorAll('table.audit').forEach(t=>auditFilter(t,this.value))\"></p>"
            "<table class=\"audit\"><tr><th>Date</th><th>Dir</th><th>Category</th><th>Payee</th>"
            "<th>Amount</th><th>Running</th><th>Ref</th><th>Notes</th></tr>"
            f"{_reg_rows or '<tr><td colspan=8>Empty box.</td></tr>'}</table>")
        done = self._view_door("/petty/audit", "Petty cash — audit",
                               links=frag)
        scripts = AUDIT_TABLE_JS
        if frag:
            # Note pops inside the popup iframe need the overlay +
            # its JS in this document (the fragment shell carries
            # neither). The audit-popup JS is safe here: the drawer
            # fragment carries no data-audit buttons, so no nested
            # popup can open. COMBO_JS likewise: the Cash Out
            # category is a combo_field whose hidden field only the
            # combo sync fills — without it in the fragment, a
            # Cash Out from the popup could never post (found in
            # the Phase 3/4 health-care walk, 2026-10-24). Any
            # fragment carrying data-combo inputs must carry it.
            scripts += AUDIT_POPUP_HTML + AUDIT_POPUP_JS + NOTE_POPUP_JS + COMBO_JS
        return ticker + header + cards + self._frag_petty_form(con, frag=frag) + register + done + scripts

    def _money_cash(self, con):
        return self._frag_cash_form(con) + self._cash_list_html(con)

    def _frag_cash_form(self, con):
        today = date.today().isoformat()
        custs = con.execute(
            "SELECT customer_id, account_name FROM customers "
            "ORDER BY account_name").fetchall()
        cust_opts = "".join(
            f"<option value='{html.escape(r['customer_id'], quote=True)}'>"
            f"{html.escape(r['account_name'])}</option>" for r in custs)
        inv_opts = "".join(
            f"<option value='{html.escape(r[0], quote=True)}'>"
            f"{html.escape(r[0])}</option>"
            for r in con.execute(
                "SELECT invoice_no FROM invoices ORDER BY invoice_no DESC"))
        wo_opts = "".join(
            f"<option value='{html.escape(r[0], quote=True)}'>"
            f"{html.escape(r[0])}</option>"
            for r in con.execute(
                "SELECT wo_id FROM work_orders ORDER BY wo_id DESC"))
        tick_opts = "".join(
            f"<option value='{html.escape(r[0], quote=True)}'>"
            f"{html.escape(r[0])}</option>"
            for r in con.execute(
                "SELECT ticket_id FROM tickets ORDER BY ticket_id DESC"))
        sale_opts = "".join(
            f"<option value='{html.escape(r[0], quote=True)}'>"
            f"{html.escape(r[0])}</option>"
            for r in con.execute(
                "SELECT DISTINCT sale_id FROM sales ORDER BY sale_id DESC"))
        quote_opts = "".join(
            f"<option value='{html.escape(r[0], quote=True)}'>"
            f"{html.escape(r[0])}</option>"
            for r in con.execute(
                "SELECT quote_no FROM quotes ORDER BY quote_no DESC"))
        co_opts = "".join(
            f"<option value='{html.escape(r[0], quote=True)}'>"
            f"{html.escape(r[0])}</option>"
            for r in con.execute(
                "SELECT co_no FROM change_orders ORDER BY co_no DESC"))
        asset_opts = "".join(
            f"<option value='{html.escape(r['asset_id'], quote=True)}'>"
            f"{html.escape(r['unit_no'])}</option>"
            for r in con.execute(
                "SELECT asset_id, unit_no FROM assets WHERE active=1 "
                "ORDER BY unit_no"))
        method_opts = "".join(
            f"<option>{html.escape(m)}</option>"
            for m in engine.CASH_ENTRY_METHODS)
        # Optional line breakdown (Jason 2026-10-23; generalized the
        # same day): against any attachment, the entry may be broken
        # down by that document's lines — one hidden block per
        # document, shown when it is picked. A Cash In settles the
        # document, so Full fills a line's open remainder; the input
        # still allows up to the line's total for a Cash Out record.
        cash_blocks = []

        def _cash_block(kind, ref):
            _st = engine.doc_line_states(con, kind, ref)
            if _st:
                cash_blocks.append(
                    f"<div class='cash-lines' "
                    f"id=\"cash-lines-{html.escape(ref, quote=True)}\" "
                    f"style='display:none'>"
                    + self._alloc_table_html(_st, "cl", ref, "remaining",
                                             max_key="total",
                                             dis_key="total")
                    + "</div>")

        for r in con.execute(
                "SELECT invoice_no FROM invoices ORDER BY invoice_no DESC"):
            _cash_block("invoice", r[0])
        for r in con.execute(
                "SELECT wo_id FROM work_orders WHERE charge_to='customer' "
                "ORDER BY wo_id DESC"):
            _cash_block("wo", r[0])
        for r in con.execute(
                "SELECT ticket_id FROM tickets WHERE invoice_id IS NULL "
                "ORDER BY ticket_id DESC"):
            _cash_block("ticket", r[0])
        for r in con.execute(
                "SELECT DISTINCT sale_id FROM sales ORDER BY sale_id DESC"):
            _cash_block("sale", r[0])
        for r in con.execute(
                "SELECT quote_no FROM quotes "
                "WHERE status NOT IN ('Converted','Void') "
                "ORDER BY quote_no DESC"):
            _cash_block("quote", r[0])
        for r in con.execute(
                "SELECT co_no FROM change_orders WHERE status = 'Issued' "
                "ORDER BY co_no DESC"):
            _cash_block("change", r[0])
        cash_blocks_html = "".join(cash_blocks)
        return f"""
        <form method=post action="/cash/save">
          <!-- Compact (Jason 2026-10-24, screenshot read): the old
               2-col .row grid gave every field half the screen — a
               3-character Direction select sat in a half-screen track.
               .frow rows size each field to its content instead: the
               whole entry form is three short rows, not a tall stack.
               Field order and names unchanged. -->
          <div class="frow">
            <div><label>Date</label><input type=date name=entry_date value="{today}" required class=w-sm></div>
            <div><label>Direction</label><select name=direction class=w-xs><option value="in">In</option><option value="out">Out</option></select></div>
            <div><label>Method</label><select name=method class=w-sm>{method_opts}</select></div>
            <div><label>Amount</label><input name=amount type=number step=0.01 min=0.01 required class=w-sm></div>
          </div>
          <div class="frow">
            <div style="flex:1 1 240px"><label>Customer</label><select name=customer_id><option value="">— From attachment —</option>{cust_opts}</select></div>
            <div><label>Asset</label><select name=asset_id class=w-sm><option value="">—</option>{asset_opts}</select></div>
            <div style="flex:1 1 240px"><label>Notes</label><input name=notes></div>
          </div>
          <div class="frow">
            <div><label>Quote #</label><select name=quote_no class=w-sm><option value="">—</option>{quote_opts}</select></div>
            <div><label>Invoice #</label><select name=invoice_no class=w-sm><option value="">—</option>{inv_opts}</select></div>
            <div><label>WO #</label><select name=wo_no class=w-sm><option value="">—</option>{wo_opts}</select></div>
            <div><label>Rental Ticket #</label><select name=ticket_id class=w-sm><option value="">—</option>{tick_opts}</select></div>
            <div><label>Sale #</label><select name=sale_group class=w-sm><option value="">—</option>{sale_opts}</select></div>
            <div><label>Change Order #</label><select name=co_no class=w-sm><option value="">—</option>{co_opts}</select></div>
          </div>
          <p class="hint">Attach: one of Invoice / WO / Rental Ticket / Quote / Sale / Change Order</p>
          {cash_blocks_html}
          {self._btn_row("Save")}
        </form>
        <script>
        (function(){{
          var form = document.querySelector('form[action="/cash/save"]');
          if (!form) return;
          var sels = ['invoice_no','wo_no','ticket_id','sale_group','quote_no','co_no'].map(
            function(n){{ return form.querySelector('select[name=' + n + ']'); }});
          function sync(){{
            form.querySelectorAll('.cash-lines').forEach(function(d){{ d.style.display = 'none'; }});
            for (var i = 0; i < sels.length; i++) {{
              if (sels[i] && sels[i].value) {{
                var d = document.getElementById('cash-lines-' + sels[i].value);
                if (d) d.style.display = '';
                break;
              }}
            }}
          }}
          form.querySelectorAll('.alloc-full').forEach(function(cb){{
            cb.addEventListener('change', function(){{
              var inp = form.querySelector('input[name="' + cb.dataset.name + '"]');
              if (inp) inp.value = cb.checked ? cb.dataset.rem : '';
            }});
          }});
          sels.forEach(function(s){{ if (s) s.addEventListener('change', sync); }});
          sync();
        }})();
        </script>
        """

    def _cash_list_html(self, con):
        entries = engine.list_cash_entries(con)
        total_in = sum(float(e["amount"]) for e in entries
                       if e["direction"] == "in")
        total_out = sum(float(e["amount"]) for e in entries
                        if e["direction"] == "out")
        def _cash_row(e):
            row = (
                f"<tr><td>{e['entry_id']}</td>"
                f"<td>{html.escape(fmt_date(e['entry_date']))}</td>"
                f"<td>{html.escape(e['method'])}</td>"
                f"<td>{html.escape(e['account_name'] or e['customer_id'] or '')}</td>"
                f"<td>{html.escape(e['attached'])}</td>"
                f"<td>{html.escape(e['direction'])}</td>"
                f"<td>${float(e['amount']):,.2f}</td>"
                f"<td>{html.escape(e['unit_no'] or '')}</td>"
                f"<td>{html.escape(e['clerk'] or '')}</td></tr>")
            # Settlement identity + line breakdown (Jason 2026-10-23)
            # under the entry's row: a settling Cash In names its one
            # payment record — the same money event, seen from the
            # Cash side — and a broken-down entry shows the split.
            _al = engine.list_payment_allocations(
                con, cash_entry_id=e["entry_id"], source="cash")
            _segs = []
            if e.get("settle_pay_id"):
                _segs.append(
                    f"Settles {html.escape(e['attached'] or '')} — "
                    f"payment {html.escape(str(e['settle_pay_id']))}")
            elif e.get("settle_cm_no"):
                _segs.append(
                    f"Kept as open credit "
                    f"{html.escape(str(e['settle_cm_no']))}")
            for a in _al:
                _seg = (f"{html.escape(a['line_label'])} "
                        f"${float(a['amount']):,.2f}")
                if a["line_note"]:
                    _seg += f" — {note_pop_html(a['line_note'])}"
                _segs.append(_seg)
            if _segs:
                row += (f"<tr><td></td><td colspan=8 class=hint>"
                        + " · ".join(_segs) + "</td></tr>")
            return row

        rows = "".join(_cash_row(e) for e in entries)
        total_row = (
            f"<tr><td colspan=5 style='text-align:right'><b>Total</b></td>"
            f"<td colspan=2>In <b>${total_in:,.2f}</b> · Out "
            f"<b>${total_out:,.2f}</b> · Net "
            f"<b>${total_in - total_out:,.2f}</b></td><td colspan=2></td></tr>"
            if entries else "")
        # Also on record: the same cash the operator already recorded
        # elsewhere — collections rows paid by Cash (in, on their
        # invoice). Read-only; those rows live in their own store and
        # are not re-entered. Settling Cash In rows are excluded: they
        # already show above as cash entries — one money event, one
        # row here. (Petty cash is never read here — sealed universe,
        # Jason 2026-10-23.)
        also = []
        _link = ""
        try:
            if any(r[1] == "cash_entry_id" for r in con.execute(
                    "PRAGMA table_info(collections)")):
                _link = " AND c.cash_entry_id IS NULL"
        except Exception:
            pass
        try:
            for r in con.execute(
                    f"""SELECT c.pay_id, c.pay_date, c.amount, i.invoice_no,
                              cu.account_name
                       FROM collections c
                       JOIN invoices i ON i.id = c.invoice_id
                       JOIN customers cu ON cu.id = i.customer_id
                       WHERE c.method = 'Cash' AND c.kind = 'payment'{_link}
                       ORDER BY c.pay_date DESC, c.pay_id DESC"""):
                also.append(
                    f"<tr><td>{html.escape(r['pay_id'])}</td>"
                    f"<td>{html.escape(fmt_date(r['pay_date']))}</td>"
                    f"<td>Cash</td>"
                    f"<td>{html.escape(r['account_name'] or '')}</td>"
                    f"<td>Invoice {html.escape(r['invoice_no'])}</td>"
                    f"<td>in</td><td>${float(r['amount']):,.2f}</td>"
                    f"<td colspan=2>Payment</td></tr>")
        except Exception:
            pass
        # Petty cash rows are NOT read here (Jason 2026-10-23,
        # petty-cash seal): the drawer is its own universe; its rows
        # appear only on its own tab and audit, never mixed into the
        # system money ledger.
        also_html = ""
        if also:
            also_html = f"""
        <h2 style="font-size:16px;color:var(--frame)">Also on record</h2>
        <table><tr><th>ID</th><th>Date</th><th>Method</th><th>Customer</th><th>Attached</th><th>Dir</th><th>Amount</th><th colspan=2>Source</th></tr>
        {''.join(also)}</table>"""
        return f"""
        <h2 style="font-size:16px;color:var(--frame)">Cash entries</h2>
        <table><tr><th>ID</th><th>Date</th><th>Method</th><th>Customer</th><th>Attached</th><th>Dir</th><th>Amount</th><th>Asset</th><th>Input by:</th></tr>
        {rows or '<tr><td colspan=9>No cash entries yet.</td></tr>'}{total_row}</table>
        {also_html}
        """

    def view_money_cash_audit(self, con):
        return f"""
        <p class="hint"><input id="auditq" placeholder="Filter" size="30"
        oninput="document.querySelectorAll('table.audit').forEach(t=>auditFilter(t,this.value))">
        </p>
        <h2>Cash</h2>
        """ + self._cash_list_html(con) + AUDIT_TABLE_JS

    def view_money_invoices_audit(self, con):
        rows = "".join(
            f"<tr><td><a href='/invoice/{html.escape(r['invoice_no'], quote=True)}'>"
            f"{html.escape(r['invoice_no'])}</a></td>"
            f"<td>{html.escape(r['account_name'])}</td>"
            f"<td>{html.escape(fmt_date(r['invoice_date']))}</td>"
            f"<td>{html.escape(r['status'])}</td>"
            f"<td>${engine.invoice_totals(con, r['invoice_no'])['balance']:,.2f}</td></tr>"
            for r in con.execute(
                """SELECT i.invoice_no, i.invoice_date, i.status, c.account_name
                   FROM invoices i JOIN customers c ON c.id = i.customer_id
                   ORDER BY i.invoice_date DESC, i.invoice_no DESC"""))
        return f"""
        <p class="hint"><input id="auditq" placeholder="Filter" size="30"
        oninput="document.querySelectorAll('table.audit').forEach(t=>auditFilter(t,this.value))">
        </p>
        <h2>Invoices</h2>
        <table class="audit"><tr><th>No</th><th>Customer</th><th>Date</th><th>Status</th><th>Balance</th></tr>
        {rows or '<tr><td colspan=5>No invoices.</td></tr>'}</table>
        """ + AUDIT_TABLE_JS

    def view_money_payments_audit(self, con, q=None):
        # Grouped by payment batch: one received payment across one or
        # many invoices reads as ONE row (2026-10-15). Legacy rows with
        # no batch_id group by their own pay_id — a batch of one.
        # Customer + date-range filter (2026-10-15): answers "which
        # payments did we receive from customer X in month Y". A batch
        # is one customer by backend enforcement, so the customer is
        # exact, not an approximation. No new customer column on
        # collections — it comes from the invoice join.
        q = q or {}
        cust = (q.get("customer_id") or "").strip()
        d_from = (q.get("date_from") or "").strip()
        d_to = (q.get("date_to") or "").strip()
        custs = con.execute(
            "SELECT customer_id, account_name FROM customers "
            "ORDER BY account_name").fetchall()
        cust_opts, cust_cur = combo_opts(
            custs, "customer_id", "account_name", cust)
        filt_cust = (
            combo_field("f_pay_aud_cust", "customer_id_text", cust_opts,
                        value=cust_cur, label="Customer",
                        placeholder="Type to search customers…")
            + f'<input type=hidden id="f_pay_aud_cust_id" '
              f'name=customer_id value="{html.escape(cust, quote=True)}">'
        )
        # Carried mirrors (settlements mirrored onto an invoice when
        # its work order / ticket was invoiced) are NOT money events —
        # the event is the source document's row, listed with the doc
        # batches below. Excluding them here keeps the audit one
        # ledger with no double count (Jason 2026-10-23).
        conds = ["COALESCE(c.carried_from,'')=''"]
        args: list = []
        if cust:
            conds.append("i.customer_id=?")
            args.append(engine.cust_key(con, cust))
        if d_from:
            conds.append("c.pay_date>=?")
            args.append(d_from)
        if d_to:
            conds.append("c.pay_date<=?")
            args.append(d_to)
        out = []
        total = 0.0
        for r in con.execute(
                f"""SELECT COALESCE(c.batch_id, c.pay_id) AS batch,
                          MIN(c.pay_date) AS pay_date,
                          MIN(c.method) AS method,
                          SUM(c.amount) AS total,
                          GROUP_CONCAT(i.invoice_no, ', ') AS invoices,
                          MIN(c.kind) AS kind,
                          MIN(cm.cm_no) AS cm_no,
                          MIN(c.clerk) AS input_by,
                          MIN(cu.account_name) AS customer_name
                   FROM collections c
                   JOIN invoices i ON i.id = c.invoice_id
                   JOIN customers cu ON cu.id = i.customer_id
                   LEFT JOIN credit_memos cm ON cm.id = c.cm_id
                   WHERE {' AND '.join(conds)} GROUP BY batch
                   ORDER BY pay_date DESC, MIN(c.id) DESC""", args):
            total += float(r["total"] or 0)
            inv_links = ", ".join(
                f"<a href='/invoice/{html.escape(ino, quote=True)}'>"
                f"{html.escape(ino)}</a>"
                for ino in (r["invoices"] or "").split(", ") if ino)
            # A negative credit batch (Jason 2026-10-23) reads
            # plainly as one, with its memo's note — the record.
            _kind_cell = html.escape(r['kind'])
            if r['kind'] == 'credit' and float(r['total'] or 0) < 0:
                _cmn = con.execute(
                    "SELECT notes FROM credit_memos WHERE cm_no=?",
                    (r['cm_no'],)).fetchone() if r['cm_no'] else None
                _kind_cell += (f" · negative credit "
                               f"{html.escape(r['cm_no'] or '')}"
                               + (f" — {html.escape(_cmn[0])}"
                                  if _cmn and _cmn[0] else ""))
            out.append(
                f"<tr><td>{html.escape(fmt_date(r['pay_date']))}</td>"
                f"<td>{html.escape(r['customer_name'] or '')}</td>"
                f"<td><a href='/summary/payment/{html.escape(r['batch'], quote=True)}'>"
                f"{html.escape(r['batch'])}</a></td>"
                f"<td>{inv_links}</td>"
                f"<td>{html.escape(r['method'])}</td><td>${r['total']:,.2f}</td>"
                f"<td>{_kind_cell}</td>"
                f"<td>{html.escape(r['input_by'] or '')}</td></tr>")
            # Line breakdown (Jason 2026-10-23): a batch broken down by
            # line shows the split under its row. A noted line the
            # batch paid nothing toward still shows — that is the
            # short-pay case the breakdown exists for.
            _allocs = engine.list_payment_allocations(
                con, batch_id=r["batch"])
            if not _allocs:
                _allocs = engine.list_payment_allocations(
                    con, pay_id=r["batch"])
            if _allocs:
                _by_inv: dict = {}
                _states: dict = {}
                for a in _allocs:
                    _seg = (f"{html.escape(a['line_label'])} "
                            f"${float(a['amount']):,.2f}")
                    if a["source"] == "credit" and a["cm_no"]:
                        _seg += (f" (negative credit "
                                 f"{html.escape(a['cm_no'])})"
                                 if float(a["amount"]) < 0 else
                                 f" (credit {html.escape(a['cm_no'])})")
                    if a["source"] == "cash":
                        _seg += " (cash in)"
                    if a["line_note"]:
                        _seg += f" — {note_pop_html(a['line_note'])}"
                        # A noted line this batch only partly covered:
                        # state the open remainder on the segment
                        # itself — the short-pay case stays plain.
                        if a["invoice_no"] not in _states:
                            _states[a["invoice_no"]] = {
                                s["line_id"]: s
                                for s in engine.invoice_line_states(
                                    con, a["invoice_no"])}
                        _st = _states[a["invoice_no"]].get(
                            a["invoice_line_id"] or 0)
                        if _st and _st["remaining"] > 0.005:
                            _seg += (f" — ${_st['remaining']:,.2f} "
                                     "open")
                    _by_inv.setdefault(a["invoice_no"], []).append(_seg)
                _alloc_lines = {a["invoice_line_id"] for a in _allocs}
                for _ino2 in list(_by_inv):
                    for _st in engine.invoice_line_states(con, _ino2):
                        if (_st["note"]
                                and _st["line_id"] not in _alloc_lines
                                and _st["remaining"] > 0.005):
                            _lbl = (_st["item"] or _st["description"]
                                    or _st["category"])
                            _by_inv[_ino2].append(
                                f"{html.escape(_lbl)} "
                                f"${_st['remaining']:,.2f} open — "
                                f"{html.escape(_st['note'])}")
                _bd = "<br>".join(
                    f"{html.escape(_i)}: " + " · ".join(_s)
                    for _i, _s in _by_inv.items())
                out.append(
                    f"<tr><td></td><td colspan=7 class=hint>{_bd}</td></tr>")
        # Document batches (Jason 2026-10-23, universality): money
        # taken against work orders, rental tickets, sales, and
        # quotes reads in the same audit — payments +, credits − by
        # kind, cash marked by source — one ledger across all five
        # document kinds.
        try:
            _dconds = ["1=1"]
            _dargs: list = []
            if cust:
                _dconds.append("dc.customer_id=?")
                _dargs.append(engine.cust_key(con, cust))
            if d_from:
                _dconds.append("dc.pay_date>=?")
                _dargs.append(d_from)
            if d_to:
                _dconds.append("dc.pay_date<=?")
                _dargs.append(d_to)
            _drows = con.execute(
                f"""SELECT COALESCE(dc.batch_id, dc.pay_id) AS batch,
                          MIN(dc.pay_date) AS pay_date,
                          MIN(dc.method) AS method,
                          SUM(dc.amount) AS total,
                          MIN(dc.kind) AS kind,
                          MIN(cm.cm_no) AS cm_no,
                          MIN(dc.clerk) AS input_by,
                          MIN(cu.account_name) AS customer_name,
                          MAX(dc.cash_entry_id) AS cash_eid
                   FROM doc_collections dc
                   LEFT JOIN customers cu ON cu.id = dc.customer_id
                   LEFT JOIN credit_memos cm ON cm.id = dc.cm_id
                   WHERE {' AND '.join(_dconds)} GROUP BY batch
                   ORDER BY pay_date DESC, MIN(dc.id) DESC""",
                _dargs).fetchall()
        except Exception:
            _drows = []
        for r in _drows:
            total += float(r["total"] or 0)
            _doc_links = []
            for _dr in con.execute(
                    "SELECT DISTINCT doc_kind, doc_id FROM doc_collections "
                    "WHERE COALESCE(batch_id, pay_id) = ?",
                    (r["batch"],)):
                _k = _dr["doc_kind"]
                _ref = engine.doc_num(con, _k, _dr["doc_id"]) or ""
                if not _ref:
                    continue
                _href = {"wo": "/summary/wo/", "ticket": "/ticket/",
                         "sale": "/sale/", "quote": "/summary/quote/",
                         "change": "/summary/change/"}.get(_k, "/")
                _doc_links.append(
                    f"{engine.DOC_LABELS.get(_k, _k)} "
                    f"<a href='{_href}{html.escape(_ref, quote=True)}'>"
                    f"{html.escape(_ref)}</a>")
            _kind_txt = r["kind"] + (" · cash" if r["cash_eid"] else "")
            if r["kind"] == 'credit' and float(r["total"] or 0) < 0:
                _cmn = con.execute(
                    "SELECT notes FROM credit_memos WHERE cm_no=?",
                    (r['cm_no'],)).fetchone() if r['cm_no'] else None
                _kind_txt += (f" · negative credit "
                              f"{html.escape(r['cm_no'] or '')}"
                              + (f" — {html.escape(_cmn[0])}"
                                 if _cmn and _cmn[0] else ""))
            out.append(
                f"<tr><td>{html.escape(fmt_date(r['pay_date']))}</td>"
                f"<td>{html.escape(r['customer_name'] or '')}</td>"
                f"<td><a href='/summary/payment/{html.escape(r['batch'], quote=True)}'>"
                f"{html.escape(r['batch'])}</a></td>"
                f"<td>{', '.join(_doc_links)}</td>"
                f"<td>{html.escape(r['method'])}</td>"
                f"<td>${r['total']:,.2f}</td>"
                f"<td>{html.escape(_kind_txt)}</td>"
                f"<td>{html.escape(r['input_by'] or '')}</td></tr>")
            _allocs = engine.list_payment_allocations(
                con, batch_id=r["batch"], carried=0)
            if _allocs:
                _by_doc: dict = {}
                for a in _allocs:
                    _seg = (f"{html.escape(a['line_label'])} "
                            f"${float(a['amount']):,.2f}")
                    if a["source"] == "credit" and a["cm_no"]:
                        _seg += (f" (negative credit "
                                 f"{html.escape(a['cm_no'])})"
                                 if float(a["amount"]) < 0 else
                                 f" (credit {html.escape(a['cm_no'])})")
                    if a["source"] == "cash":
                        _seg += " (cash in)"
                    if a["line_note"]:
                        _seg += f" — {note_pop_html(a['line_note'])}"
                    _by_doc.setdefault(a["doc_ref"], []).append(_seg)
                _bd = "<br>".join(
                    f"{html.escape(_i)}: " + " · ".join(_s)
                    for _i, _s in _by_doc.items())
                out.append(
                    f"<tr><td></td><td colspan=7 class=hint>{_bd}</td></tr>")
        rows = "".join(out)
        filtered = bool(cust or d_from or d_to)
        total_row = ""
        if filtered and out:
            total_row = (
                f"<tr><td colspan=5 style='text-align:right'>"
                f"<b>Total (filtered)</b></td>"
                f"<td><b>${total:,.2f}</b></td><td></td><td></td></tr>")
        clear = (" <a href='/money/payments/audit'>Clear</a>"
                 if filtered else "")
        return f"""
        <form method=get action="/money/payments/audit">
          <div class="frow">
            <div>{filt_cust}</div>
            <div><label>From</label><input type=date name=date_from value="{html.escape(d_from, quote=True)}"></div>
            <div><label>To</label><input type=date name=date_to value="{html.escape(d_to, quote=True)}"></div>
            <div><button>Filter</button>{clear}</div>
          </div>
        </form>
        <p class="hint"><input id="auditq" placeholder="Filter" size="30"
        oninput="document.querySelectorAll('table.audit').forEach(t=>auditFilter(t,this.value))">
        </p>
        <h2>Payments</h2>
        <table class="audit"><tr><th>Date</th><th>Customer</th><th>Batch</th><th>Documents</th><th>Method</th><th>Amount</th><th>Kind</th><th>Input by:</th></tr>
        {rows or '<tr><td colspan=8>No payments.</td></tr>'}{total_row}</table>
        """ + AUDIT_TABLE_JS

    def view_money_credits_audit(self, con):
        rows = "".join(
            f"<tr><td><a href='/summary/credit/{html.escape(r['cm_no'], quote=True)}'>"
            f"{html.escape(r['cm_no'])}</a></td>"
            f"<td>{html.escape(fmt_date(r['cm_date']))}</td>"
            f"<td>{html.escape(r['account_name'])}</td>"
            f"<td>{'Negative credit — ' if r['face_amount'] < 0 else ''}{html.escape(r['reason'] or '')}</td>"
            f"<td>${r['face_amount']:,.2f}</td>"
            f"</tr>"
            for r in con.execute(
                """SELECT m.cm_no, m.cm_date, c.account_name, m.reason, m.face_amount
                   FROM credit_memos m JOIN customers c ON c.id = m.customer_id
                   ORDER BY m.cm_date DESC, m.cm_no DESC"""))
        return f"""
        <p class="hint"><input id="auditq" placeholder="Filter" size="30"
        oninput="document.querySelectorAll('table.audit').forEach(t=>auditFilter(t,this.value))">
        </p>
        <h2>Credit Memos</h2>
        <table class="audit"><tr><th>CM</th><th>Date</th><th>Customer</th><th>Reason</th><th>Face</th></tr>
        {rows or '<tr><td colspan=5>No credit memos.</td></tr>'}</table>
        """ + AUDIT_TABLE_JS

    def view_money_petty_audit(self, con):
        book = engine.petty_book(con)
        rows = "".join(
            f"<tr><td>{html.escape(fmt_date(r['txn_date']))}</td>"
            f"<td>{html.escape(r['direction'])}</td>"
            f"<td>{html.escape(r['category'])}</td>"
            f"<td>{html.escape(r['payee'])}</td>"
            f"<td>${r['signed']:,.2f}</td><td>${r['running']:,.2f}</td>"
            f"<td>{html.escape(r['ref_no'])}</td><td>{note_pop_html(r['notes'])}</td></tr>"
            for r in book["rows"])
        return f"""
        <p class="hint"><input id="auditq" placeholder="Filter" size="30"
        oninput="document.querySelectorAll('table.audit').forEach(t=>auditFilter(t,this.value))">
        </p>
        <h2>Petty Cash Register</h2>
        <table class="audit"><tr><th>Date</th><th>Dir</th><th>Category</th><th>Payee</th><th>Amount</th><th>Running</th><th>Ref</th><th>Notes</th></tr>
        {rows or '<tr><td colspan=8>Empty box.</td></tr>'}</table>
        """ + AUDIT_TABLE_JS

    def view_quote_form(self, con, qno, bare=False):
        pack = engine.quote_pack(con, qno) if qno else None
        if qno and not pack:
            return ("" if bare else tabs_quotes("/quotes")) + "<p>Unknown quote.</p>"
        # New quote: PREVIEW the number so the user sees it while preparing
        # (Jason 2026-10-07: "please find quote number XXX attached") — but
        # peek, never reserve: rendering this form must not burn a sequence
        # number. The real reservation happens at save time in save_quote.
        # The hidden quote_no field below stays EMPTY for new quotes so the
        # preview is display-only; two open new-quote tabs can never
        # overwrite each other by submitting the same previewed number.
        if not qno:
            qno = engine.peek_next_doc(con, "next_quote", "QT", "quotes", "quote_no")
        q = pack["q"] if pack else {}
        lines = pack["lines"] if pack else []
        # New quotes default to ONE blank line row (2026-10-16); Add Item
        # adds more. Edits render every saved line (backend takes k0..k7).
        while len(lines) < 1:
            lines.append({"kind": "", "asset_id": "", "item": "", "description": "", "qty": 1, "rate": 0, "uom": ""})
        cust = con.execute("SELECT customer_id, account_name FROM customers ORDER BY account_name").fetchall()
        sites = con.execute("SELECT site_id, site_name FROM sites ORDER BY site_name").fetchall()
        # Quote picker draw (Jason 2026-10-24 ruling): the quote form
        # draws from the rentable class by the same draw-point mechanics
        # as the rental/new-ticket picker — Plant and Stock are not
        # offered; Fleet, Other, and the operator's own designations are.
        assets = con.execute(
            "SELECT asset_id, unit_no FROM assets WHERE active=1 "
            "AND COALESCE(designation,'Fleet') NOT IN ('Plant','Stock') "
            "AND COALESCE(status,'Active')='Active' "
            "ORDER BY unit_no").fetchall()
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
        # Global line-item row (2026-10-15): Type (inv_cat) | Item | Description
        # | Qty | Unit (inv_uom) | Rate$. The Item combo suggests units but
        # never forces one — on non-Rental Types the typed text is the item
        # (labor name, gate-to-gate, freight method, misc part).
        _q_asset_units = {a["unit_no"] for a in assets}
        _q_item_opts = [(v, v, "") for v in _item_suggestions(con)
                        if v not in _q_asset_units]
        row_html = []
        for i, ln in enumerate(lines[:8]):
            aopts, acur = combo_opts(assets, "asset_id", "unit_no", ln.get("asset_id"),
                                     disp=lambda v, lab: lab)
            # ITEM E: the 47 inv_item presets ride the same datalist as
            # (preset, preset, "") tuples — no data-id, so picking one
            # submits it as Item text with NO asset_id; picking an asset
            # still syncs its asset_id exactly as before. Asset unit
            # numbers are excluded here (already present as assets).
            aopts = aopts + _q_item_opts
            # Stored-value rule (Spec 7): the row's current Item text
            # rides the datalist even when it is off the enabled set.
            _cur_item = (ln.get("item") or "").strip()
            if (_cur_item and _cur_item not in _q_asset_units
                    and _cur_item not in {o[0] for o in aopts}):
                aopts = aopts + [(_cur_item, _cur_item, "")]
            acombo = (
                combo_field(f"f_qline_a{i}", f"a{i}_text", aopts, value=(ln.get("item") or acur),
                            placeholder="Type to search units…")
                + f'<input type=hidden id="f_qline_a{i}_id" name=a{i} '
                  f'value="{html.escape(str(ln.get("asset_id") or ""), quote=True)}">'
            )
            # Default line-item row (Jason 2026-10-07): Type | Item | Description | Qty | Unit | Rate$
            row_html.append(
                f"<div class='lineitem-row qline' data-i='{i}' style='display:grid;grid-template-columns:104px 1fr 2fr 84px 104px 104px;gap:8px;align-items:start'>"
                f"<div><label>Type</label>{lookup_select(con, 'inv_cat', f'k{i}', current=ln.get('kind') or '', blank=True, css='qkind')}</div>"
                f"<div><label>Item</label>{acombo}</div>"
                f"<div><label>Description</label><textarea name=d{i} class=ldesc rows=1>{html.escape(str(ln.get('description') or ''))}</textarea></div>"
                f"<div><label>Qty</label><input name=q{i} class='qqty w-xs' type=number step=0.01 value='{float(ln.get('qty') or 1):.2f}'></div>"
                f"<div><label>Unit</label>{lookup_select(con, 'inv_uom', f'u{i}', current=ln.get('uom') or '', blank=True, vals=enabled_values(con, 'inv_uom'), add_option=False)}</div>"
                f"<div><label>Rate $</label><span class=\"rate-x\"><input name=r{i} class='qrate w-sm' type=number step=0.01 value='{float(ln.get('rate') or 0):.2f}'><button type=button class=line-del title='Delete line item'>✕</button></span></div>"
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
            Invoices: {html.escape(inv)} · Associated change orders: {html.escape(cos)}</p>
            <p>Quoted ${tot['quoted']:,.2f} = face ${tot['face']:,.2f}. Billed ${tot['billed']:,.2f}. Variance ${tot['variance']:,.2f}.</p>"""
        convert = ""
        if pack and q.get("status") in ("Accepted", "Converted"):
            convert = f"""<form method=post action="/quote/{html.escape(qno)}/convert">
              <label>On-Rent for New Reserved Rental Tickets</label>
              <input type=date name=on_rent value="{today}">
              <p><button>Convert Rental Lines to Rental Tickets</button></p>
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
        # Against picker (2026-10-15): the WO or ticket this quote was
        # written against — the signed WO you came back with. Attach-only:
        # picking one sets its quote link to this quote; already-linked
        # items show in the linked line above. Blank on edit.
        def _against_opts():
            wo_rows = con.execute(
                """SELECT w.wo_id, COALESCE(c.account_name, '') AS cust,
                   COALESCE(w.description, '') AS d FROM work_orders w
                   LEFT JOIN customers c ON c.id = w.customer_id
                   WHERE w.status != 'Void' AND w.customer_id IS NOT NULL
                   ORDER BY w.wo_id DESC"""
            ).fetchall()
            t_rows = con.execute(
                """SELECT t.ticket_id, COALESCE(c.account_name, '') AS cust,
                   COALESCE(t.job_name, '') AS d FROM tickets t
                   JOIN customers c ON c.id = t.customer_id
                   WHERE t.status NOT IN ('Void', 'Closed')
                   ORDER BY t.ticket_id DESC"""
            ).fetchall()
            def _opt(val, cust, d):
                lab = f"{val} · {cust}" + (f" · {d[:40]}" if (d or "").strip() else "")
                return (f'<option value="{html.escape(val, quote=True)}">'
                        f"{html.escape(lab)}</option>")
            wo = "".join(_opt(f"wo:{r['wo_id']}", r["cust"], r["d"]) for r in wo_rows)
            tk = "".join(_opt(f"ticket:{r['ticket_id']}", r["cust"], r["d"]) for r in t_rows)
            return (f'<option value="">—</option>'
                    f'<optgroup label="Work orders">{wo}</optgroup>'
                    f'<optgroup label="Rental Tickets">{tk}</optgroup>')
        against_sel = (
            f'<div><label>Against</label><select name=against>'
            f'{_against_opts()}</select></div>'
        )
        # Build 'u' (Jason 2026-10-25, universal summary pattern;
        # disposes of PHASET JC-T4): the money panel no longer stands
        # below this form — a live quote's money is worked from its
        # summary's Payment popup, and a closed quote's money block
        # states there as a fact. The form keeps its own work only.
        money_panel = ""
        # Header zone (build 'r', Jason 2026-10-25, facelift item 4;
        # two-row form build 't', same day, universal form law):
        # Company block, Quote # + Date, bar, Customer left, Job
        # Info box right — then the lines. The Contact field lives
        # in the Job Info popup — the popup's Contact Name field IS
        # this form's contact_name (same name; the stored value
        # rides in job_vals below, so an edit-save no longer drops
        # it). Build 't': Valid Until, Against, and Site move into
        # the Job Info popup (route (b)); Site's combo was built but
        # never rendered in build 's' — an edit-save posted no
        # site_id and silently cleared the quote's site; the popup
        # is its home under the law and the field works again. The
        # Input by line and the linked-documents block (information)
        # ride in the popup as read-only lines. The status buttons
        # and the convert form (actions) move into their own popups
        # below the form (the universal off-form pattern); the money
        # panel stays — a working section, flagged in PHASET-REPORT.
        _q_extra = (
            f'<div class="row">'
            f'<div><label>Valid Until</label><input type=date name=valid_until value="{html.escape(valid_until)}" class=w-sm></div>'
            f'{against_sel}'
            f'</div>'
            f'<div class="row"><div>{qsite_combo}</div></div>'
            f'<div class="row"><div><label>Input by:</label>'
            f'<div>{html.escape((q.get("clerk") if pack else "") or self.desk(con))}</div></div></div>'
            + (f'<div>{linked}</div>' if linked else "")
        )
        _q_job_lines = [("PO #", q.get("po") or ""),
                        ("Job Name", q.get("job_name") or ""),
                        ("AFE #", q.get("afe") or ""),
                        ("Contact Name", q.get("contact_name") or "")]
        _q_doors = ""
        _q_popups = ""
        if status_form or convert:
            _doors = ""
            if status_form:
                _doors += ('<button type="button" class="vbtn" '
                           'onclick="document.getElementById(\'qstatpop\').style.display=\'block\'">Status</button> ')
                _q_popups += (
                    f'<div id="qstatpop" style="display:none;position:fixed;top:8%;left:8%;right:8%;background:white;border:2px solid #333;padding:18px;z-index:1000;max-height:84%;overflow:auto">'
                    f'<h3 style="margin-top:0">Status <span style="float:right"><button type="button" onclick="document.getElementById(\'qstatpop\').style.display=\'none\'">Close</button></span></h3>'
                    f'{status_form}</div>')
            if convert:
                _doors += ('<button type="button" class="vbtn" '
                           'onclick="document.getElementById(\'qconvpop\').style.display=\'block\'">Convert</button> ')
                _q_popups += (
                    f'<div id="qconvpop" style="display:none;position:fixed;top:8%;left:8%;right:8%;background:white;border:2px solid #333;padding:18px;z-index:1000;max-height:84%;overflow:auto">'
                    f'<h3 style="margin-top:0">Convert <span style="float:right"><button type="button" onclick="document.getElementById(\'qconvpop\').style.display=\'none\'">Close</button></span></h3>'
                    f'{convert}</div>')
            _q_doors = f'<div class="viewrow">{_doors}</div>'
        _q_doc = (f'Quote # <input value="{html.escape(qno)}" disabled class=w-xs>'
                  if pack else
                  f'Quote # <input name=quote_no value="{html.escape(qno)}" class=w-xs>')
        _q_date = (f'<label>Date</label> <input type=date name=quote_date '
                   f'value="{html.escape(str(q.get("quote_date") or today)[:10])}" class=w-sm>')
        _q_cust = ('<div style="font-size:10px;color:#5C6B7A;'
                   'text-transform:uppercase">Billing Address</div>' + qcust_combo)
        return ("" if bare else tabs_quotes("/quotes")) + f"""
        <form method=post action="/quote/save" enctype="multipart/form-data">
          {f'<input type=hidden name=quote_no value="{html.escape(qno)}">' if pack else ''}
          {self._form_head(con, _q_doc, _q_date, _q_cust, _q_job_lines)}
          <style>.lineitem-row label{{margin:4px 0 2px}}.lineitem-row{{margin-bottom:2px}}</style>
          <div id="quote-lines">
          {self._line_head()}
          {''.join(row_html)}
          </div>
          <div><label>Notes</label><input name=notes value="{html.escape(q.get('notes') or '')}" style="width:100%"></div>
          <div class="row3">
            <div></div>
            <div style="text-align:center">*taxes not included*</div>
            <div id="quote-total" style="text-align:right;font-weight:700;color:var(--frame)">Total: $0.00</div>
          </div>
          {self._btn_row("Save", "qjobpop", add_item=True)}
          {self._job_info_popup('qjobpop', {"po": q.get("po") or "", "job_name": q.get("job_name") or "", "afe": q.get("afe") or "", "contact_name": q.get("contact_name") or ""}, _q_extra)}
        </form>
        {_q_doors}
        {_q_popups}
        {"" if bare else self._view_row("/quotes/all", "Quotes")}
        <script>
        (function(){{var t=document.getElementById('quote-lines'); if(!t)return; function calc(){{var total=0; t.querySelectorAll('.qline').forEach(function(r){{var q=r.querySelector('.qqty'), rate=r.querySelector('.qrate'); if(!q||!rate)return; total+=(parseFloat(q.value)||0)*(parseFloat(rate.value)||0);}}); var el=document.getElementById('quote-total'); if(el)el.textContent='Total: $'+total.toFixed(2); }} t.addEventListener('input',calc); calc(); window.__quoteCalc=calc;}})();
        /* Add item: clone a line row, renumber k/d/q/r/a/u indexes (backend takes k0..k7) */
        (function(){{var box=document.getElementById('quote-lines'); if(!box)return; var form=box.closest('form'); var btn=null; form.querySelectorAll('button[type=button]').forEach(function(b){{if(b.textContent.trim().toLowerCase()==='add item')btn=b;}}); if(!btn)return;
        function bindCombo(inp){{var dl=document.getElementById(inp.getAttribute('list')); if(!dl)return; function sync(){{var t=inp.value.trim(),id=''; Array.prototype.forEach.call(dl.options,function(o){{if(o.value.trim()===t){{id=o.getAttribute('data-id')||'';}}}}); var hid=document.getElementById(inp.id+'_id'); if(hid)hid.value=id;}} inp.addEventListener('input',sync); inp.addEventListener('change',sync); sync();}}
        btn.addEventListener('click',function(){{var rows=box.querySelectorAll('.qline'); if(rows.length>=8)return; var n=rows.length; var c=rows[rows.length-1].cloneNode(true); c.setAttribute('data-i',n);
        c.querySelectorAll('[name]').forEach(function(el){{el.name=el.name.replace(/^(k|a|d|q|r|u)(\\d+)(_text)?$/,function(m,p1,p2,p3){{return p1+n+(p3||'');}});}});
        c.querySelectorAll('select[data-field]').forEach(function(el){{el.dataset.field=el.name;}});
        c.querySelectorAll('[id]').forEach(function(el){{el.id=el.id.replace(/_a\\d+/, '_a'+n);}});
        var vis=c.querySelector('input[data-combo]'); if(vis&&vis.hasAttribute('list')){{vis.setAttribute('list',vis.getAttribute('list').replace(/_a\\d+_list/,'_a'+n+'_list'));}}
        c.querySelectorAll('input').forEach(function(el){{if(el.type==='hidden'){{el.value='';}} else if(el.classList.contains('qqty')){{el.value='1.00';}} else if(el.classList.contains('qrate')){{el.value='0.00';}} else{{el.value='';}}}});
        c.querySelectorAll('select').forEach(function(el){{el.selectedIndex=0;}});
        box.appendChild(c); if(vis)bindCombo(vis); if(window.__quoteCalc)window.__quoteCalc();}});}})();
        </script>
        """

    def view_quote_summary(self, con, qno):
        """Summary of Quote# (build 'u', Jason 2026-10-25, universal
        summary pattern): the quote's facts stated — customer, date,
        status, valid until, site, Job Info values, its lines, the
        quote totals (quoted = face, billed, variance — a quote's
        numbers are its own; build 'v' removed the change-order
        folding), its money figures, its linked documents — with
        doors: Edit (to the form), Payment (the money panel in its
        popup, while the quote's money is live), Status and Convert
        (the same popup forms the quote form carries), Print (the
        quote's three-choice print), View (the Quotes list)."""
        pack = engine.quote_pack(con, qno)
        if not pack:
            return tabs_quotes("/quotes") + "<p>Unknown quote.</p>"
        q = pack["q"]
        tot = pack["tot"]
        lrows = "".join(
            f"<tr><td>{html.escape(ln.get('kind') or '')}</td>"
            f"<td>{html.escape(ln.get('item') or '')}</td>"
            f"<td>{html.escape(ln.get('description') or '')}</td>"
            f"<td>{float(ln.get('qty') or 0):g}</td>"
            f"<td>{html.escape(ln.get('uom') or '')}</td>"
            f"<td>${float(ln.get('rate') or 0):,.2f}</td>"
            f"<td>${float(ln.get('amount') or 0):,.2f}</td></tr>"
            for ln in pack["lines"])
        lines_html = (
            "<table><tr><th>Type</th><th>Item</th><th>Description</th>"
            "<th>Qty</th><th>Unit</th><th>Rate</th><th>Amount</th></tr>"
            f"{lrows}</table>" if lrows else "")
        site_name = ""
        if q.get("site_id"):
            _sr = con.execute("SELECT site_name FROM sites WHERE site_id=?",
                              (q["site_id"],)).fetchone()
            site_name = (_sr["site_name"] if _sr else "") or q["site_id"]
        linked = []
        for t in pack["tickets"]:
            linked.append(
                f"Rental <a href=\"/ticket/{html.escape(t['ticket_id'], quote=True)}\">"
                f"{html.escape(t['ticket_id'])}</a> ({html.escape(t['status'])})")
        for w in pack["wos"]:
            linked.append(
                f"Work Order <a href=\"/summary/wo/{html.escape(w['wo_id'], quote=True)}\">"
                f"{html.escape(w['wo_id'])}</a>")
        for i in pack["invoices"]:
            linked.append(
                f"Invoice <a href=\"/invoice/{html.escape(i['invoice_no'], quote=True)}\">"
                f"{html.escape(i['invoice_no'])}</a>")
        for c in pack["cos"]:
            linked.append(
                f"Change Order <a href=\"/summary/change/{html.escape(c['header']['co_no'], quote=True)}\">"
                f"{html.escape(c['header']['co_no'])}</a>")
        _blk = engine.quote_money_block(con, qno)
        facts = [
            ("Customer", html.escape(q.get("account_name") or "")),
            ("Date", html.escape(fmt_date(q.get("quote_date") or ""))),
            ("Status", html.escape(q.get("status") or "")),
            ("Valid Until", html.escape(fmt_date(q["valid_until"]))
             if q.get("valid_until") else None),
            ("Site", html.escape(site_name) if site_name else None),
            ("Job Name", html.escape(q["job_name"]) if q.get("job_name") else None),
            ("AFE #", html.escape(q["afe"]) if q.get("afe") else None),
            ("PO #", html.escape(q["po"]) if q.get("po") else None),
            ("Contact Name", html.escape(q["contact_name"])
             if q.get("contact_name") else None),
            ("Quoted", f"${tot['quoted']:,.2f}"),
            ("Face", f"${tot['face']:,.2f}"),
            ("Billed", f"${tot['billed']:,.2f}"),
            ("Variance", f"${tot['variance']:,.2f}"),
            ("Money", html.escape(_blk) + "." if _blk else None),
            ("Linked", " · ".join(linked) if linked else None),
            ("Notes", html.escape(q["notes"]) if q.get("notes") else None),
            ("Input by:", html.escape(q.get("clerk") or "")),
        ]
        doors = ""
        popups = ""
        if not _blk:
            _set = engine.doc_settled(con, "quote", qno)
            facts[13:13] = [
                ("Settled", f"${float(_set['total']):,.2f}"),
                ("Balance", f"${float(engine.doc_balance(con, 'quote', qno)):,.2f}"),
            ]
            pay_door, pay_popup = self._money_popup(
                con, "quote", qno, q.get("customer_id"))
            doors += pay_door
            popups += pay_popup
        nxt = list(engine.QUOTE_NEXT.get(q.get("status"), ()))
        if nxt:
            st_btns = "".join(
                f"<button name=status value='{html.escape(s)}'>"
                f"{html.escape(s)}</button> " for s in nxt)
            status_form = (
                f"<form method=post action=\"/quote/"
                f"{html.escape(qno, quote=True)}/status\">{st_btns}</form>")
            doors += self._pop_door("qstatpop", "Status")
            popups += self._pop_wrap("qstatpop", "Status", status_form)
        if q.get("status") in ("Accepted", "Converted"):
            convert = (
                f"<form method=post action=\"/quote/"
                f"{html.escape(qno, quote=True)}/convert\">"
                f"<label>On-Rent for New Reserved Rental Tickets</label>"
                f"<input type=date name=on_rent "
                f"value=\"{date.today().isoformat()}\">"
                f"<p><button>Convert Rental Lines to Rental Tickets</button></p>"
                f"</form>")
            doors += self._pop_door("qconvpop", "Convert")
            popups += self._pop_wrap("qconvpop", "Convert", convert)
        doors += (f"<a class=\"btn\" href=\"/quote/"
                  f"{html.escape(qno, quote=True)}\">Edit</a> ")
        doors += self._print_menu(screen=f"/print/quote/{qno}",
                                  pdf=f"/print/quote/{qno}.pdf")
        return (tabs_quotes("/quotes")
                + self._sum_page("Quote", qno, facts, lines_html,
                                 doors, popups, "/quotes/all", "Quotes"))

    def view_change_summary(self, con, co_no):
        """Summary of Change Order# (build 'u' pattern; build 'v',
        Jason 2026-10-25: the Change Order is a standalone money
        document — nothing requires anything). Its facts stated:
        customer, date, status, reason, PO, its optional associated
        document (a fact, linked — it changes no totals anywhere),
        its lines with directions, the add/subtract/net totals, its
        money (total / settled / balance), notes, record stamps.
        Doors: Payment (the money popup, while the CO is issued),
        Edit (to the CO form — open only while nothing has settled
        against it), Print, View (the Change orders list)."""
        co = con.execute("SELECT * FROM change_orders WHERE co_no=?",
                         (co_no,)).fetchone()
        if not co:
            return tabs_quotes("/changes") + "<p>Unknown change order.</p>"
        lines = con.execute(
            "SELECT * FROM change_order_lines WHERE co_id=? ORDER BY line_id",
            (co["id"],)).fetchall()
        lrows = "".join(
            f"<tr><td>{html.escape(ln['kind'] or '')}</td>"
            f"<td>{html.escape(ln['item'] or '')}</td>"
            f"<td>{html.escape(ln['description'] or '')}</td>"
            f"<td>{html.escape(ln['direction'] or '')}</td>"
            f"<td>{float(ln['qty'] or 0):g}</td>"
            f"<td>{html.escape(ln['uom'] or '')}</td>"
            f"<td>${float(ln['rate'] or 0):,.2f}</td>"
            f"<td>${float(ln['amount'] or 0):,.2f}</td></tr>"
            for ln in lines)
        lines_html = (
            "<table><tr><th>Type</th><th>Item</th><th>Description</th>"
            "<th>Direction</th><th>Qty</th><th>Unit</th><th>Rate</th>"
            f"<th>Amount</th></tr>{lrows}</table>" if lrows else "")
        adds = sum(float(ln["amount"] or 0) for ln in lines
                   if ln["direction"] == "add")
        subs = sum(float(ln["amount"] or 0) for ln in lines
                   if ln["direction"] == "subtract")
        _cust = con.execute(
            "SELECT account_name, customer_id FROM customers WHERE id=?",
            (co["customer_id"],)).fetchone()
        _cust_name = _cust["account_name"] if _cust else ""
        _cust_code = _cust["customer_id"] if _cust else ""
        _assoc = engine.change_order_assoc(con, co_no)
        _assoc_html = None
        if _assoc and _assoc[0]:
            _ak, _ar = _assoc
            _href = {"invoice": "/invoice/", "sale": "/sale/",
                     "wo": "/summary/wo/", "ticket": "/ticket/",
                     "change": "/summary/change/"}.get(_ak, "/")
            _assoc_html = (
                f"{html.escape(engine.DOC_LABELS.get(_ak, _ak))} "
                f"<a href=\"{_href}{html.escape(_ar, quote=True)}\">"
                f"{html.escape(_ar)}</a>")
        _total = float(engine.doc_total(con, "change", co_no))
        _settled = float(engine.doc_settled(con, "change", co_no)["total"])
        _balance = float(engine.doc_balance(con, "change", co_no))
        facts = [
            ("Customer", html.escape(_cust_name) if _cust_name else None),
            ("Date", html.escape(fmt_date(co["co_date"]))),
            ("Status", html.escape(co["status"] or "")),
            ("Reason", html.escape(co["reason"] or "")),
            ("PO #", html.escape(self._g(co, "po")) if self._g(co, "po") else None),
            ("Associated", _assoc_html),
            ("Change Orders", self._assoc_co_fact(con, "change", co_no)),
            ("Adds", f"${adds:,.2f}"),
            ("Subtracts", f"${subs:,.2f}"),
            ("Total", f"${_total:,.2f}"),
            ("Settled", f"${_settled:,.2f}"),
            ("Balance", f"${_balance:,.2f}"),
            ("Notes", html.escape(co["notes"]) if co["notes"] else None),
            ("Input by:", f"{html.escape(co['clerk'] or '')} "
                          f"{html.escape(fmt_datetime(co['created_at']))}".strip()),
        ]
        doors = ""
        popups = ""
        if (co["status"] or "") == "Issued":
            pay_door, pay_popup = self._money_popup(
                con, "change", co_no, _cust_code)
            doors += pay_door
            popups += pay_popup
            if _settled <= 0.009:
                doors += (f"<a class=\"btn\" href=\"/ticket/new?kind=change"
                          f"&co_no={html.escape(co_no, quote=True)}\">"
                          f"Edit</a> ")
        doors += self._print_menu(screen=f"/print/change/{co_no}",
                                  pdf=f"/print/change/{co_no}.pdf")
        return (tabs_quotes("/changes")
                + self._sum_page("Change Order", co_no, facts, lines_html,
                                 doors, popups, "/changes/all",
                                 "Change orders — audit"))

    def view_payment_summary(self, con, batch):
        """Summary of Payment# (build 'u', Jason 2026-10-25,
        universal summary pattern): one received payment — its
        batch (COALESCE(batch_id, pay_id), the identity the
        payments audit groups by) — stated as facts: date,
        customer, method, kind, ref, the amount, the documents it
        settled (links to their summaries), its line allocations,
        record stamps. A payment is a record: no Edit door exists
        anywhere for one. Print is the page print menu."""
        inv_rows = []
        doc_rows = []
        try:
            inv_rows = con.execute(
                """SELECT c.*, i.invoice_no AS inv_no,
                          cm.cm_no AS cm_number, cu.account_name AS cust
                   FROM collections c
                   JOIN invoices i ON i.id = c.invoice_id
                   JOIN customers cu ON cu.id = i.customer_id
                   LEFT JOIN credit_memos cm ON cm.id = c.cm_id
                   WHERE COALESCE(c.batch_id, c.pay_id) = ?
                     AND COALESCE(c.carried_from, '') = ''
                   ORDER BY c.pay_date, c.pay_id""", (batch,)).fetchall()
        except Exception:
            inv_rows = []
        try:
            doc_rows = con.execute(
                """SELECT dc.*, cm.cm_no AS cm_number,
                          cu.account_name AS cust
                   FROM doc_collections dc
                   LEFT JOIN customers cu ON cu.id = dc.customer_id
                   LEFT JOIN credit_memos cm ON cm.id = dc.cm_id
                   WHERE COALESCE(dc.batch_id, dc.pay_id) = ?
                   ORDER BY dc.pay_date, dc.pay_id""", (batch,)).fetchall()
        except Exception:
            doc_rows = []
        rows = list(inv_rows) + list(doc_rows)
        if not rows:
            return (tabs_money("pay", con)
                    + "<p>Unknown payment.</p>")
        head = rows[0]
        total = sum(float(r["amount"] or 0) for r in rows)
        doc_links = []
        for r in inv_rows:
            doc_links.append(
                f"Invoice <a href=\"/invoice/"
                f"{html.escape(r['inv_no'], quote=True)}\">"
                f"{html.escape(r['inv_no'])}</a>")
        _doc_href = {"wo": "/summary/wo/", "ticket": "/ticket/",
                     "sale": "/sale/", "quote": "/summary/quote/",
                     "change": "/summary/change/"}
        for r in doc_rows:
            _dref = engine.doc_num(con, r["doc_kind"], r["doc_id"]) or ""
            _href = _doc_href.get(r["doc_kind"], "/")
            doc_links.append(
                f"{engine.DOC_LABELS.get(r['doc_kind'], r['doc_kind'])} "
                f"<a href=\"{_href}{html.escape(_dref, quote=True)}\">"
                f"{html.escape(_dref)}</a>")
        _allocs = engine.list_payment_allocations(con, batch_id=batch)
        if not _allocs:
            _allocs = engine.list_payment_allocations(con, pay_id=batch)
        alloc_html = ""
        if _allocs:
            _segs = []
            for a in _allocs:
                _seg = (f"{html.escape(a['doc_ref'])}: "
                        f"{html.escape(a['line_label'])} "
                        f"${float(a['amount']):,.2f}")
                if a["source"] == "credit" and a["cm_no"]:
                    _seg += f" (credit {html.escape(a['cm_no'])})"
                if a["source"] == "cash":
                    _seg += " (cash in)"
                if a["line_note"]:
                    _seg += f" — {note_pop_html(a['line_note'])}"
                _segs.append(_seg)
            alloc_html = ("<table><tr><th>Allocations</th></tr>"
                          + "".join(f"<tr><td>{s}</td></tr>" for s in _segs)
                          + "</table>")
        _refs = []
        for r in rows:
            _ref = (r["cm_number"] if r["kind"] == "credit" and r["cm_number"]
                    else r["ref_no"])
            if _ref and _ref not in _refs:
                _refs.append(_ref)
        _notes = []
        for r in rows:
            _n = (r["notes"] or "").strip() if "notes" in r.keys() else ""
            if _n and _n not in _notes:
                _notes.append(_n)
        facts = [
            ("Customer", html.escape(head["cust"] or "")),
            ("Date", html.escape(fmt_date(head["pay_date"]))),
            ("Method", html.escape(head["method"] or "")),
            ("Kind", html.escape(head["kind"] or "")),
            ("Ref", html.escape(", ".join(_refs)) if _refs else None),
            ("Amount", f"${total:,.2f}"),
            ("Documents", " · ".join(doc_links) if doc_links else None),
            ("Notes", html.escape(" · ".join(_notes)) if _notes else None),
            ("Input by:", html.escape(
                ", ".join(sorted({r["clerk"] for r in rows if r["clerk"]})))) ,
        ]
        doors = self._print_menu(page=True)
        return (tabs_money("pay", con)
                + self._sum_page("Payment", batch, facts, alloc_html,
                                 doors, "", "/money/payments/audit",
                                 "Payments — audit"))

    def view_credit_summary(self, con, cm_no):
        """Summary of Credit Memo# (build 'u', Jason 2026-10-25,
        universal summary pattern): the memo's facts stated —
        customer, date, reason, face, applied / unapplied, the
        documents it settled (links to their summaries), notes,
        record stamps — with doors: Edit (to the Credit Memo form
        for the memo's customer, where its application work lives;
        a posted memo's own fields never change), Print (the memo's
        three-choice print), View (the Credit memos list)."""
        cm = con.execute(
            """SELECT m.*, c.account_name, c.customer_id AS cust_code
               FROM credit_memos m
               JOIN customers c ON c.id = m.customer_id
               WHERE m.cm_no = ?""", (cm_no,)).fetchone()
        if not cm:
            return tabs_money("credit", con) + "<p>Unknown credit memo.</p>"
        _open = {r["cm_no"]: r for r in engine.list_open_credits(con)}
        _ocr = _open.get(cm_no)
        applied = float(_ocr["applied"]) if _ocr else 0.0
        unapplied = (float(_ocr["unapplied"]) if _ocr
                     else float(cm["face_amount"]))
        doc_links = []
        for r in con.execute(
                "SELECT i.invoice_no, c.amount FROM collections c "
                "JOIN invoices i ON i.id = c.invoice_id "
                "WHERE c.cm_id = ? AND c.kind = 'credit' ORDER BY c.pay_date",
                (cm["id"],)):
            doc_links.append(
                f"Invoice <a href=\"/invoice/"
                f"{html.escape(r['invoice_no'], quote=True)}\">"
                f"{html.escape(r['invoice_no'])}</a> "
                f"${float(r['amount']):,.2f}")
        _doc_href = {"wo": "/summary/wo/", "ticket": "/ticket/",
                     "sale": "/sale/", "quote": "/summary/quote/",
                     "change": "/summary/change/"}
        try:
            _drows = con.execute(
                "SELECT doc_kind, doc_id, amount FROM doc_collections "
                "WHERE cm_id = ? AND kind = 'credit' ORDER BY pay_date",
                (cm["id"],)).fetchall()
        except Exception:
            _drows = []
        for r in _drows:
            _dref = engine.doc_num(con, r["doc_kind"], r["doc_id"]) or ""
            _href = _doc_href.get(r["doc_kind"], "/")
            doc_links.append(
                f"{engine.DOC_LABELS.get(r['doc_kind'], r['doc_kind'])} "
                f"<a href=\"{_href}{html.escape(_dref, quote=True)}\">"
                f"{html.escape(_dref)}</a> "
                f"${float(r['amount']):,.2f}")
        _reason = cm["reason"] or ""
        if float(cm["face_amount"]) < 0:
            _reason = "Negative credit — " + _reason
        facts = [
            ("Customer", html.escape(cm["account_name"])),
            ("Date", html.escape(fmt_date(cm["cm_date"]))),
            ("Reason", html.escape(_reason)),
            ("Face", f"${float(cm['face_amount']):,.2f}"),
            ("Applied", f"${applied:,.2f}"),
            ("Unapplied", f"${unapplied:,.2f}"),
            ("Applied to", " · ".join(doc_links) if doc_links else None),
            ("Notes", html.escape(cm["notes"]) if cm["notes"] else None),
            ("Input by:", f"{html.escape(cm['clerk'] or '')} "
                          f"{html.escape(fmt_datetime(cm['created_at']))}".strip()),
        ]
        doors = (
            f"<a class=\"btn\" href=\"/credit?customer_id="
            f"{html.escape(cm['cust_code'], quote=True)}\">Edit</a> "
            + self._print_menu(screen=f"/print/credit/{cm_no}",
                               pdf=f"/print/credit/{cm_no}.pdf"))
        return (tabs_money("credit", con)
                + self._sum_page("Credit Memo", cm_no, facts, "",
                                 doors, "", "/money/credits/audit",
                                 "Credit memos audit"))


    def view_changes(self, con, q=None, bare=False):
        q = q or {}
        # Build 'v' (Jason 2026-10-25): the Change Order form on
        # Jason's settled model — a standalone money document.
        # Nothing requires anything: no quote parent, no required
        # association. The universal form pattern: Company head,
        # CO # + Date, the Customer block left and the Job Info box
        # right (Reason, PO #, and the optional Association ride in
        # the Job Info popup — information, never line rows), its
        # own lines grid, Notes, the button row. Editing an existing
        # CO (co_no given) prefills everything; an edit is refused
        # once money has settled against it (the engine enforces;
        # the form says so instead of rendering a dead form).
        co_no = (q.get("co_no") or "").strip()
        co = None
        co_lines = []
        if co_no:
            co = con.execute("SELECT * FROM change_orders WHERE co_no=?",
                             (co_no,)).fetchone()
            if not co:
                return ("" if bare else tabs_quotes("/changes")) + \
                    "<p>Unknown change order.</p>"
            if float(engine.doc_settled(con, "change", co_no)["total"]) > 0.009:
                return ("" if bare else tabs_quotes("/changes")) + (
                    f"<p>Change Order {html.escape(co_no)} has payments "
                    f"against it; its lines stand as issued. "
                    f"<a href=\"/summary/change/"
                    f"{html.escape(co_no, quote=True)}\">Open its "
                    f"summary</a>.</p>")
            co_lines = con.execute(
                "SELECT * FROM change_order_lines WHERE co_id=? "
                "ORDER BY line_id", (co["id"],)).fetchall()
        cust = con.execute(
            "SELECT customer_id, account_name FROM customers "
            "ORDER BY account_name").fetchall()
        _cust_code = ""
        if co:
            _cr = con.execute("SELECT customer_id FROM customers WHERE id=?",
                              (co["customer_id"],)).fetchone()
            _cust_code = _cr["customer_id"] if _cr else ""
        copts, ccur = combo_opts(cust, "customer_id", "account_name", _cust_code)
        cust_combo = (
            combo_field("f_co_cust", "customer_id_text", copts, value=ccur,
                        label="Customer", required=True,
                        placeholder="Type to search customers…")
            + f'<input type=hidden id="f_co_cust_id" name=customer_id '
              f'value="{html.escape(_cust_code, quote=True)}">'
        )
        # Lines: existing rows prefilled (a subtract line renders its
        # qty negative — the form's one direction convention), else
        # ONE blank row; Add Item adds more, capped at 6 (the backend
        # reads k0..k5).
        _rows_in = [dict(r) for r in co_lines] or [
            {"kind": "", "item": "", "description": "", "qty": 1,
             "rate": 0, "uom": "", "direction": "add"}]
        line_rows = []
        for i, ln in enumerate(_rows_in[:6]):
            _qty = float(ln.get("qty") or 0)
            if ln.get("direction") == "subtract":
                _qty = -abs(_qty)
            line_rows.append(
                f"<div class='lineitem-row co-line' style='display:grid;grid-template-columns:104px 1fr 2fr 84px 104px 104px;gap:8px;align-items:start'>"
                f"<div><label>Type</label>{lookup_select(con, 'inv_cat', f'k{i}', current=ln.get('kind') or '', blank=True)}</div>"
                f"<div><label>Item</label><input name=item{i} list=\"{ITEM_LIST_ID}\" value=\"{html.escape(str(ln.get('item') or ''), quote=True)}\"></div>"
                f"<div><label>Description</label><textarea name=d{i} class=ldesc rows=1>{html.escape(str(ln.get('description') or ''))}</textarea></div>"
                f"<div><label>Qty</label><input name=q{i} type=number step=0.01 value={_qty:g} class=w-xs title='Use a negative qty to subtract'></div>"
                f"<div><label>Unit</label>{lookup_select(con, 'inv_uom', f'u{i}', current=ln.get('uom') or '', blank=True, vals=enabled_values(con, 'inv_uom'), add_option=False)}</div>"
                f"<div><label>Rate $</label><span class=\"rate-x\"><input name=r{i} type=number step=0.01 value={float(ln.get('rate') or 0):g} class=w-sm><button type=button class=line-del title='Delete line item'>✕</button></span></div>"
                f"</div>"
            )
        if not co_no:
            co_no = engine.peek_next_doc(con, "next_co", "CO",
                                         "change_orders", "co_no")
        today = date.today().isoformat()
        _co_date_v = (str(co["co_date"])[:10] if co else today)
        _reason = (co["reason"] or "") if co else ""
        _po = (self._g(co, "po") if co else "") or ""
        _assoc = engine.change_order_assoc(con, co["co_no"]) if co else None
        _assoc_label = ""
        if _assoc:
            _assoc_label = (f"{engine.DOC_LABELS.get(_assoc[0], _assoc[0])} "
                            f"{_assoc[1]}")
        # Job Info popup extras: Reason (required — the CO's reason
        # is its record), and the optional Association: one money
        # document, chosen by kind + number. The popup's own PO #
        # field is the form's one po field.
        _kind_opts = "".join(
            f"<option value=\"{k}\"{' selected' if _assoc and _assoc[0] == k else ''}>"
            f"{html.escape(engine.DOC_LABELS[k])}</option>"
            for k in ("invoice", "sale", "wo", "ticket", "change"))
        _doc_opts = ["<option value=\"\"></option>"]
        for _k, _tbl, _col in (
                ("invoice", "invoices", "invoice_no"),
                ("sale", "sales", "sale_id"),
                ("wo", "work_orders", "wo_id"),
                ("ticket", "tickets", "ticket_id"),
                ("change", "change_orders", "co_no")):
            _seen = set()
            for r in con.execute(
                    f"SELECT {_col} AS n FROM {_tbl} ORDER BY {_col}"):
                if r["n"] in _seen:
                    continue
                _seen.add(r["n"])
                _sel = (" selected" if _assoc and _assoc[0] == _k
                        and _assoc[1] == r["n"] else "")
                _doc_opts.append(
                    f"<option value=\"{_k}:{html.escape(str(r['n']), quote=True)}\"{_sel}>"
                    f"{html.escape(engine.DOC_LABELS[_k])} "
                    f"{html.escape(str(r['n']))}</option>")
        _extra = (
            f"<div><label>Reason (required)</label>"
            f"<input name=reason value=\"{html.escape(_reason, quote=True)}\" required></div>"
            f"<div class=\"row\"><div><label>Associated document (optional)</label>"
            f"<select name=assoc_ref>{''.join(_doc_opts)}</select></div></div>"
        )
        _job_vals = {"po": _po}
        _co_doc = f'CO # <input name=co_no value="{html.escape(co_no, quote=True)}" class=w-xs>'
        _co_date = f'<label>Date</label> <input type=date name=co_date value="{_co_date_v}" class=w-sm>'
        _job_lines = [("Reason", _reason), ("PO #", _po),
                      ("Associated", _assoc_label)]
        return ("" if bare else tabs_quotes("/changes")) + f"""
        <form method=post action="/change/save" enctype="multipart/form-data">
          {self._form_head(con, _co_doc, _co_date, cust_combo, _job_lines)}
          {self._line_head()}
          {''.join(line_rows)}
          <div><label>Notes</label><input name=notes value="{html.escape((co['notes'] or '') if co else '', quote=True)}"></div>
          {self._btn_row("Save", "cojobpop", add_item=True)}
          {self._job_info_popup('cojobpop', _job_vals, _extra)}
        </form>
        <script>
        (function(){{
          // Change-order Add Item: clone the last line row, renumber
          // k/item/d/q/u/r to the next index, clear values. Capped
          // at 6 rows: the backend reads k0..k5.
          var form = document.querySelector('form[action="/change/save"]');
          if (!form) return;
          function addItemRow(){{
            var rows = form.querySelectorAll('.co-line');
            if (rows.length >= 6) return;
            var proto = rows[rows.length - 1];
            var clone = proto.cloneNode(true);
            var n = rows.length;
            clone.querySelectorAll('[name]').forEach(function(el){{
              el.name = el.name.replace(/\\d+$/, '') + n;
              if (el.tagName === 'SELECT') el.selectedIndex = 0;
              else if (el.name === 'q' + n) el.value = '1';
              else if (el.name === 'r' + n) el.value = '0';
              else el.value = '';
            }});
            clone.querySelectorAll('select[data-field]').forEach(function(el){{ el.dataset.field = el.name; }});
            proto.parentNode.insertBefore(clone, proto.nextSibling);
            var inp = clone.querySelector('input');
            if (inp) inp.focus();
          }}
          Array.prototype.forEach.call(form.querySelectorAll('button[type=button]'), function(b){{
            if (b.textContent.trim().toLowerCase() === 'add item') b.addEventListener('click', addItemRow);
          }});
        }})();
        </script>
        """ + _item_extras(con)

    def view_changes_all(self, con):
        """Every change order in the book — the register behind the
        Change Order page's View pop-up (2026-10-21). The "Issued"
        table that used to sit under the CO editor is gone (Jason:
        it came from nowhere, was never asked for, and he had already
        asked for that species to be removed universally); lists live
        behind the page's one View button, never as cards on editor
        pages. Same columns the table had; build 'u': the CO # opens
        the change order's summary, the quote ref the quote's
        summary (record links land on summaries)."""
        rows = []
        for r in con.execute(
                """SELECT co.co_no, co.po, co.co_date, co.reason, co.status,
                          c.account_name
                   FROM change_orders co
                   LEFT JOIN customers c ON c.id = co.customer_id
                   ORDER BY co.co_date DESC, co.co_no DESC"""):
            _assoc = engine.change_order_assoc(con, r["co_no"])
            acell = ""
            if _assoc and _assoc[0]:
                _href = {"invoice": "/invoice/", "sale": "/sale/",
                         "wo": "/summary/wo/", "ticket": "/ticket/",
                         "change": "/summary/change/"}.get(_assoc[0], "/")
                acell = (f"<a href='{_href}"
                         f"{html.escape(_assoc[1], quote=True)}'>"
                         f"{html.escape(engine.DOC_LABELS.get(_assoc[0], _assoc[0]))} "
                         f"{html.escape(_assoc[1])}</a>")
            rows.append(
                f"<tr><td><a href='/summary/change/{html.escape(r['co_no'], quote=True)}'>"
                f"{html.escape(r['co_no'])}</a></td>"
                f"<td>{html.escape(r['account_name'] or '')}</td>"
                f"<td>{acell}</td>"
                f"<td>{html.escape(r['po'] or '')}</td>"
                f"<td>{html.escape(fmt_date(r['co_date']))}</td>"
                f"<td>{html.escape(r['reason'] or '')}</td>"
                f"<td>{html.escape(r['status'] or '')}</td>"
                f"</tr>")
        return f"""
        <p class="hint"><input id="auditq" placeholder="Filter" size="30"
        oninput="document.querySelectorAll('table.audit').forEach(t=>auditFilter(t,this.value))">
        </p>
        <h2>Change Orders</h2>
        <table class="audit"><tr><th>CO</th><th>Customer</th><th>Associated</th><th>PO</th><th>Date</th><th>Reason</th><th>Status</th></tr>
        {''.join(rows) or '<tr><td colspan=7>None yet.</td></tr>'}</table>
        """ + AUDIT_TABLE_JS

    def _alloc_table_html(self, states, prefix, ino, cap_key,
                          max_key=None, dis_key=None):
        """Line-allocation inputs for one invoice (Jason 2026-10-23):
        one row per line — Full fills the line's cap (data-rem), the
        amount posts as <prefix>__<invoice>__<line_id>. cap_key is
        'remaining' for payments and credits (a line takes only what
        is not yet covered). Cash entries pass max_key='total': Full
        still fills the open remainder (a Cash In settles the line),
        while the input itself allows up to the line's total (a Cash
        Out breakdown is a record and may name the whole line)."""
        q = html.escape(ino, quote=True)
        rows = []
        for s in states:
            cap = float(s[cap_key])
            maxv = float(s[max_key]) if max_key else cap
            name = f"{prefix}__{q}__{s['line_id']}"
            label = s["item"] or s["description"] or s["category"]
            if s["item"] and s["description"]:
                label = f"{s['item']} — {s['description']}"
            dis = (" disabled" if float(s[dis_key or cap_key]) <= 0.005
                   else "")
            ph = "Paid" if cap <= 0.005 and not max_key else "0.00"
            rows.append(
                f"<tr><td><input type=checkbox class=alloc-full "
                f"data-rem='{cap:.2f}' data-name=\"{name}\"{dis}></td>"
                f"<td>{html.escape(label)}</td>"
                f"<td>${s['total']:,.2f}</td>"
                f"<td>${s['allocated']:,.2f}</td>"
                f"<td><input name=\"{name}\" class=\"alloc-amt w-sm\" type=number "
                f"step=0.01 min=0 max='{maxv:.2f}' placeholder='{ph}'{dis}></td></tr>")
        return ("<table class=\"alloc-tbl\"><tr><th></th><th>Line</th>"
                "<th>Total</th><th>Paid</th><th>Apply $</th></tr>"
                + "".join(rows) + "</table>")

    def _doc_money_html(self, con, kind, ref, customer_id):
        """Money panel for a work order, rental ticket, sale, or
        quote (Jason 2026-10-23, universality): the document's balance line, its
        lines with per-line covered state and dispute-note forms, a
        money-in form (any tender, blanket or by line), and an
        apply-open-credit form. The invoice's money rules, on every
        money document — blanket money never touches lines; the
        document balance above the lines is the governing figure."""
        label = engine.DOC_LABELS[kind]
        total = float(engine.doc_total(con, kind, ref))
        settled = engine.doc_settled(con, kind, ref)
        bal = total - float(settled["total"])
        states = engine.doc_line_states(con, kind, ref)
        q = html.escape(ref, quote=True)
        seg = "wo" if kind == "wo" else kind
        parts = [
            f"<h3>Money — {label} {html.escape(ref)}</h3>",
            f"<p>Total ${total:,.2f} · Settled "
            f"${float(settled['total']):,.2f} (payments "
            f"${float(settled['payment']):,.2f} · credits "
            f"${float(settled['credit']):,.2f}) · Balance "
            f"${bal:,.2f}</p>"]
        if states:
            rows = []
            for s in states:
                _lbl = s["item"] or s["description"] or s["category"]
                if s["item"] and s["description"]:
                    _lbl = f"{s['item']} — {s['description']}"
                _segs = []
                if s["credited"] > 0:
                    _refs = ", ".join(html.escape(x)
                                      for x in s["credit_refs"])
                    _segs.append(f"credit {_refs} ${s['credited']:,.2f}")
                if s["credited"] < 0:
                    _refs = ", ".join(html.escape(x)
                                      for x in s["credit_refs"])
                    _segs.append(
                        f"negative credit {_refs} −${-s['credited']:,.2f}")
                if s["cash_paid"] > 0:
                    _segs.append(f"cash ${s['cash_paid']:,.2f}")
                _seg = (f" <span class=hint>({' · '.join(_segs)})</span>"
                        if _segs else "")
                _nv = html.escape(s["note"] or "", quote=True)
                rows.append(
                    f"<tr><td>{html.escape(_lbl)}</td>"
                    f"<td>${s['total']:,.2f}</td>"
                    f"<td>${s['allocated']:,.2f}{_seg}</td>"
                    f"<td>${s['remaining']:,.2f}</td>"
                    f"<td><form method=post action=\"/{seg}/{q}/linenote\">"
                    f"<input type=hidden name=line_id "
                    f"value=\"{s['line_id']}\">"
                    f"<input name=note value=\"{_nv}\" class=w-sm> "
                    f"<button class=secondary>Save</button></form></td></tr>")
            parts.append(
                "<table class='alloc-tbl'><tr><th>Line</th><th>Total</th>"
                "<th>Paid</th><th>Open</th><th>Note</th></tr>"
                + "".join(rows) + "</table>")
        method_opts = "".join(
            f"<option>{html.escape(m)}</option>"
            for m in engine.CASH_METHODS)
        alloc_tbl = (self._alloc_table_html(states, "dl", ref, "remaining")
                     if states else "")
        parts.append(f"""
        <form method=post action="/docmoney">
          <input type=hidden name=doc_kind value="{kind}">
          <input type=hidden name=doc_ref value="{q}">
          <div class="row">
            <div><label>Date</label><input type=date name=pay_date value="{date.today().isoformat()}" required class=w-sm></div>
            <div><label>Method</label><select name=method class=w-sm>{method_opts}</select></div>
            <div><label>Ref</label><input name=ref class=w-sm></div>
            <div><label>Amount</label><input name=amount type=number step=0.01 min=0.01 required class=w-sm></div>
          </div>
          {alloc_tbl}
          {self._btn_row("Record payment")}
        </form>""")
        credits = (engine.list_open_credits(con, customer_id)
                   if customer_id else [])
        if credits:
            cm_opts = "".join(
                f"<option value=\"{html.escape(c['cm_no'], quote=True)}\">"
                f"{html.escape(c['cm_no'])} — ${c['unapplied']:,.2f} open"
                f"{' (negative)' if c['unapplied'] < 0 else ''}"
                f"</option>" for c in credits)
            parts.append(f"""
        <form method=post action="/doccredit">
          <input type=hidden name=doc_kind value="{kind}">
          <input type=hidden name=doc_ref value="{q}">
          <!-- row3, not row (density gate 2026-10-24): 3 fields in a
               2-col row stranded Apply alone on row 2. -->
          <div class="row3">
            <div><label>Credit memo</label><select name=cm_no>{cm_opts}</select></div>
            <div><label>Date</label><input type=date name=pay_date value="{date.today().isoformat()}" class=w-sm></div>
            <div><label>Apply</label><input name=amount type=number step=0.01 min=0.01 required class=w-sm></div>
          </div>
          {alloc_tbl}
          {self._btn_row("Apply credit")}
        </form>""")
        if states:
            parts.append("""
        <script>
        document.querySelectorAll(
          'form[action="/docmoney"] .alloc-full, form[action="/doccredit"] .alloc-full'
        ).forEach(function(cb){
          cb.addEventListener('change', function(){
            var inp = cb.closest('form').querySelector(
              'input[name="' + cb.dataset.name + '"]');
            if (inp) inp.value = cb.checked ? cb.dataset.rem : '';
          });
        });
        </script>""")
        return "".join(parts)

    def _frag_pay_form(self, con):
        open_inv = engine.list_open_invoices(con)
        if not open_inv:
            # A Change Order may still be open (build 'v'): it takes
            # its payment on its own summary or in Cash.
            try:
                _any_co = any(
                    float(engine.doc_balance(con, "change", r["co_no"])) > 0.009
                    for r in con.execute(
                        "SELECT co_no FROM change_orders "
                        "WHERE status = 'Issued'"))
            except Exception:
                _any_co = False
            if _any_co:
                return ("<p>No open invoices. Open Change Orders take "
                        "payment on their summaries or in Cash.</p>")
            # Rule stands (payments cannot post to a general account),
            # but the dead end gets a forward path (Jason 2026-10-14).
            return ("<p>No open invoices.</p>"
                    "<p><a class=\"btn\" href=\"/invoice/new\">→ New Invoice</a></p>")
        pay_inv_opts = []
        for r in open_inv:
            v = str(r["invoice_no"])
            d = f"{v} · {r['account_name']} · bal ${float(r['balance']):,.2f}"
            pay_inv_opts.append((v, d, v))
        pay_inv_combo = (
            combo_field("f_pay_inv", "invoice_no_text", pay_inv_opts,
                        label="Invoice",
                        placeholder="Type to search invoices…")
            + '<input type=hidden id="f_pay_inv_id" name=invoice_no value="">'
        )
        # Customer picker (2026-10-15): a filter + reference, NOT a
        # standalone customer payment — payments still attach to
        # invoices. Only customers with open invoices are offered, so
        # every pick lists at least one row. Picking a customer
        # filters the invoice picker to that customer's open invoices
        # and narrows the splits table to the same customer.
        cust_opts = []
        _seen_cust = set()
        for r in open_inv:
            if r["customer_id"] not in _seen_cust:
                _seen_cust.add(r["customer_id"])
                cust_opts.append((r["customer_id"],
                                  f"{r['account_name']} ({r['customer_id']})",
                                  r["customer_id"]))
        pay_cust_combo = (
            combo_field("f_pay_cust", "customer_id_text", cust_opts,
                        label="Customer",
                        placeholder="Type to search customers…")
            + '<input type=hidden id="f_pay_cust_id" name=customer_id value="">'
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
        # Multi-invoice payment (Jason 2026-10-15): one payment can cover
        # several invoices — a company may pay 20 invoices with one
        # check. Pick a customer (or any invoice) to set the customer;
        # the table below narrows to that customer's open invoices,
        # one Apply $ per invoice. The total adds up as amounts are
        # typed. The backend enforces one customer per payment.
        cust_map = json.dumps({r["invoice_no"]: r["customer_id"]
                               for r in open_inv})
        cust_name_map = json.dumps({r["customer_id"]: r["account_name"]
                                    for r in open_inv})
        def _apply_row(r):
            ino = r["invoice_no"]
            q = html.escape(ino, quote=True)
            states = engine.invoice_line_states(con, ino)
            lines_btn = (" <button type=button class=pay-lines-btn "
                         f"data-ino=\"{q}\">Lines</button>"
                         if states else "")
            main = (
                f"<tr data-cust='{html.escape(r['customer_id'])}' style='display:none'>"
                f"<td><input type=checkbox class=pay-full data-bal='{r['balance']:.2f}' title='Pay this invoice in full'></td>"
                f"<td>{html.escape(ino)}</td>"
                f"<td>{html.escape(r['account_name'])}</td>"
                f"<td>{html.escape(fmt_date(r['invoice_date']))}</td>"
                f"<td>${r['balance']:,.2f}</td>"
                f"<td><input name=p__{html.escape(ino)} class=pay-split type=number step=0.01 min=0 "
                f"max='{r['balance']:.2f}' placeholder='0.00'>{lines_btn}</td></tr>")
            if not states:
                return main
            return main + (
                f"<tr class='pay-lines' data-cust='{html.escape(r['customer_id'])}' "
                f"data-ino=\"{q}\" style='display:none'><td colspan=6>"
                + self._alloc_table_html(states, "pl", ino, "remaining")
                + f"<span class=hint id=\"plstat-{q}\"></span></td></tr>")

        apply_rows = "".join(_apply_row(r) for r in open_inv)
        # Split payment across an invoice and its Change Order
        # (build 'v', Jason 2026-10-25, the amended-PO exception):
        # an open Change Order of the same customer rides the same
        # splits table as its own Apply row — one payment event, one
        # batch, per-document allocations recorded separately (the
        # documents never merge). The CO row posts pco__<co_no>.
        _co_rows = []
        try:
            for r in con.execute(
                    """SELECT co.co_no, co.co_date, c.customer_id AS cust_code,
                              c.account_name
                       FROM change_orders co
                       JOIN customers c ON c.id = co.customer_id
                       WHERE co.status = 'Issued'
                       ORDER BY co.co_date, co.co_no"""):
                _bal = float(engine.doc_balance(con, "change", r["co_no"]))
                if _bal <= 0.009:
                    continue
                _co_rows.append(
                    f"<tr data-cust='{html.escape(r['cust_code'])}' style='display:none'>"
                    f"<td><input type=checkbox class=pay-full data-bal='{_bal:.2f}' title='Pay this change order in full'></td>"
                    f"<td>Change Order {html.escape(r['co_no'])}</td>"
                    f"<td>{html.escape(r['account_name'])}</td>"
                    f"<td>{html.escape(fmt_date(r['co_date']))}</td>"
                    f"<td>${_bal:,.2f}</td>"
                    f"<td><input name=pco__{html.escape(r['co_no'], quote=True)} class=pay-split type=number step=0.01 min=0 "
                    f"max='{_bal:.2f}' placeholder='0.00'></td></tr>")
        except Exception:
            _co_rows = []
        apply_rows += "".join(_co_rows)
        # Header zone (build 'r', Jason 2026-10-25, facelift item 4):
        # Company block, the Customer picker in the middle block (it
        # is this form's customer reference — a filter for the splits
        # below, unchanged), RP # + Date, bar, then the form's work.
        # The payment form has no line-item grid; its fields and the
        # splits table are the document's work, not above-the-lines
        # fields.
        _pay_doc = f'Payment # <input value="{rp_no}" disabled class=w-xs>'
        _pay_date = f'<label>Date</label> <input type=date name=pay_date value="{today}" required class=w-sm>'
        return f"""
        <form method=post action="/pay" enctype="multipart/form-data">
          <input type=hidden name=rp_no value="{rp_no}">
          {self._form_head(con, _pay_doc, _pay_date, pay_cust_combo)}
          {self._top_commit("Apply payment")}
          <div class="row">
            <div>{pay_inv_combo}</div>
            <div><label>Total payment</label><b id="pay-total-display">$0.00</b><input type=hidden name=amount id="pay-total" value="0"></div>
          </div>
          <p class="hint">One payment, multiple invoices.</p>
          <table id="pay-splits"><tr><th></th><th>Invoice</th><th>Customer</th><th>Date</th><th>Balance</th><th>Apply $</th></tr>
          <tr id="pay-hint"><td colspan=6 class="hint">No customer selected.</td></tr>
          {apply_rows}</table>
          <p><button type=button id="pay-all-full">Pay all shown in full</button></p>
          <div class="row4">
            <div><label>Payment Reference</label><input name=ref class=w-sm></div>
            <div>{pay_method_combo}</div>
            <div><label>Upload(s)</label><input type=file name=pay_upload></div>
          </div>
          <div><label>Notes</label><input name=notes style="width:100%"></div>
          {self._btn_row(None, "payjobpop", add_item=False)}
          {self._job_info_popup('payjobpop')}
        </form>
        <script>
        (function(){{
          var form = document.querySelector('form[action="/pay"]');
          if (!form) return;
          var CUST = {cust_map};
          var CUST_NAME = {cust_name_map};
          var invText = document.getElementById('f_pay_inv');
          var invHid = document.getElementById('f_pay_inv_id');
          var custText = document.getElementById('f_pay_cust');
          var custHid = document.getElementById('f_pay_cust_id');
          var invDl = document.getElementById('f_pay_inv_list');
          var ALL_INV = [];
          if (invDl) {{ Array.prototype.forEach.call(invDl.options, function(o){{
            ALL_INV.push({{id: o.getAttribute('data-id') || '', label: o.value}});
          }}); }}
          var hint = document.getElementById('pay-hint');
          var totalEl = document.getElementById('pay-total');
          var totalDisp = document.getElementById('pay-total-display');
          function pickedInv(){{
            var t = invText && invText.value.trim();
            if (t) {{
              var dl = document.getElementById('f_pay_inv_list');
              if (dl) {{
                var opts = dl.querySelectorAll('option');
                for (var i = 0; i < opts.length; i++) {{
                  if (opts[i].value === t) return opts[i].dataset.id || '';
                }}
              }}
            }}
            return (invHid && invHid.value) || '';
          }}
          function pickedCust(){{
            // Mirror COMBO_JS (exact match, else unique prefix): the
            // hidden id may be stale while the user is still typing,
            // because COMBO_JS syncs after this script's listeners.
            var t = custText && custText.value.trim();
            if (t) {{
              var dl = document.getElementById('f_pay_cust_list');
              if (dl) {{
                var prefix = [];
                for (var i = 0; i < dl.options.length; i++) {{
                  if (dl.options[i].value.trim() === t) return dl.options[i].getAttribute('data-id') || '';
                  if (dl.options[i].value.trim().toLowerCase().indexOf(t.toLowerCase()) === 0) prefix.push(dl.options[i]);
                }}
                if (prefix.length === 1) return prefix[0].getAttribute('data-id') || '';
              }}
            }}
            return (custHid && custHid.value.trim()) || '';
          }}
          function rebuildInv(cust){{
            if (!invDl) return;
            while (invDl.firstChild) invDl.removeChild(invDl.firstChild);
            ALL_INV.forEach(function(it){{
              if (cust && CUST[it.id] !== cust) return;
              var o = document.createElement('option');
              o.value = it.label;
              if (it.id) o.setAttribute('data-id', it.id);
              invDl.appendChild(o);
            }});
          }}
          function syncCustFromInv(){{
            // Picking an invoice sets the customer; a later pick for a
            // different customer re-points the picker — never stale.
            var cust = CUST[pickedInv()] || '';
            if (cust && cust !== pickedCust()) {{
              if (custText) custText.value = CUST_NAME[cust] || cust;
              if (custHid) custHid.value = cust;
            }}
          }}
          function filter(){{
            var cust = pickedCust() || CUST[pickedInv()] || '';
            form.querySelectorAll('#pay-splits tr[data-cust]').forEach(function(tr){{
              var show = cust && tr.dataset.cust === cust;
              if (tr.classList.contains('pay-lines')) show = show && tr.classList.contains('open');
              tr.style.display = show ? '' : 'none';
            }});
            if (hint) hint.style.display = cust ? 'none' : '';
          }}
          function lineStatus(block){{
            var ino = block.dataset.ino;
            var span = document.getElementById('plstat-' + ino);
            var split = form.querySelector('input[name="p__' + ino + '"]');
            var x = 0;
            block.querySelectorAll('.alloc-amt').forEach(function(el){{ x += parseFloat(el.value) || 0; }});
            var y = split ? (parseFloat(split.value) || 0) : 0;
            if (span) span.textContent = 'Lines $' + x.toFixed(2) + ' of $' + y.toFixed(2) + (x > y + 0.004 ? ' — over the Apply amount' : '');
          }}
          form.querySelectorAll('.pay-lines-btn').forEach(function(btn){{
            btn.addEventListener('click', function(){{
              var block = form.querySelector('tr.pay-lines[data-ino="' + btn.dataset.ino + '"]');
              if (block) {{ block.classList.toggle('open'); filter(); }}
            }});
          }});
          form.querySelectorAll('.alloc-full').forEach(function(cb){{
            cb.addEventListener('change', function(){{
              var inp = form.querySelector('input[name="' + cb.dataset.name + '"]');
              if (inp) inp.value = cb.checked ? cb.dataset.rem : '';
              var block = cb.closest('tr.pay-lines');
              if (block) lineStatus(block);
            }});
          }});
          form.querySelectorAll('.alloc-amt').forEach(function(el){{
            el.addEventListener('input', function(){{
              var block = el.closest('tr.pay-lines');
              if (block) lineStatus(block);
            }});
          }});
          function sum(){{
            var t = 0;
            form.querySelectorAll('.pay-split').forEach(function(el){{
              var tr = el.closest('tr');
              if (tr && tr.style.display === 'none') return;
              t += parseFloat(el.value) || 0;
            }});
            totalEl.value = t.toFixed(2);
            totalDisp.textContent = '$' + t.toFixed(2);
          }}
          form.querySelectorAll('.pay-full').forEach(function(cb){{
            cb.addEventListener('change', function(){{
              var amt = cb.closest('tr').querySelector('.pay-split');
              if (amt) amt.value = cb.checked ? cb.dataset.bal : '';
              sum();
            }});
          }});
          var allBtn = document.getElementById('pay-all-full');
          if (allBtn) allBtn.addEventListener('click', function(){{
            form.querySelectorAll('#pay-splits tr[data-cust]').forEach(function(tr){{
              if (tr.style.display === 'none') return;
              var cb = tr.querySelector('.pay-full');
              var amt = tr.querySelector('.pay-split');
              if (cb) cb.checked = true;
              if (amt && cb) amt.value = cb.dataset.bal;
            }});
            sum();
          }});
          form.querySelectorAll('.pay-split').forEach(function(el){{
            el.addEventListener('input', function(){{
              sum();
              var tr = el.closest('tr');
              var nx = tr && tr.nextElementSibling;
              if (nx && nx.classList.contains('pay-lines')) lineStatus(nx);
            }});
          }});
          function onCust(){{
            rebuildInv(pickedCust());
            if (invText) invText.value = '';
            if (invHid) invHid.value = '';
            filter();
          }}
          function onInv(){{
            filter();
            syncCustFromInv();
          }}
          if (custText) {{ custText.addEventListener('input', onCust); custText.addEventListener('change', onCust); }}
          if (custHid) custHid.addEventListener('change', function(){{ rebuildInv(pickedCust()); filter(); }});
          if (invText) {{ invText.addEventListener('input', onInv); invText.addEventListener('change', onInv); }}
          if (invHid) invHid.addEventListener('change', onInv);
          filter(); sum();
        }})();
        </script>
        """

    def _frag_credit_form(self, con, q):
        q = q or {}
        cid = q.get("customer_id") or ""
        custs = con.execute("SELECT customer_id, account_name FROM customers ORDER BY account_name").fetchall()
        if not custs:
            return ("<p>No customers yet.</p>"
                    "<p><a class=\"btn\" href=\"/customer/new\">→ Add Customer</a></p>")
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
        # Global line-item row (2026-10-15): Type (inv_cat) + Unit (inv_uom).
        cm_type_opts = lookup_select(con, "inv_cat", "type", blank=True)
        cm_uom_opts = lookup_select(con, "inv_uom", "uom", blank=True,
                                    vals=enabled_values(con, "inv_uom"),
                                    add_option=False)  # editors: enabled set only (Spec 7)
        open_inv = engine.list_open_invoices(con, cid) if cid else []

        def _capply_row(r):
            ino = r["invoice_no"]
            q = html.escape(ino, quote=True)
            states = engine.invoice_line_states(con, ino)
            lines_btn = (" <button type=button class=ca-lines-btn>Lines</button>"
                         if states else "")
            # A settled invoice takes no positive credit, but a
            # NEGATIVE credit re-opens settled amount (Jason
            # 2026-10-23) — it stays listed, capped at what it has
            # settled, its line table capped at each line's settled.
            _settled = r['balance'] <= 0.005
            _cap = r['paid'] if _settled else r['balance']
            _ckey = "allocated" if _settled else "remaining"
            main = (
                f"<tr><td>{html.escape(ino)}"
                f"{' · settled' if _settled else ''}</td>"
                f"<td>{html.escape(fmt_date(r['invoice_date']))}</td>"
                f"<td>${r['total']:,.2f}</td><td>${r['cash']:,.2f}</td>"
                f"<td>${r['credit']:,.2f}</td><td>${r['balance']:,.2f}</td>"
                f"<td><input name=a__{html.escape(ino)} type=number step=0.01 min=0 "
                f"max='{_cap:.2f}' placeholder='0.00'>{lines_btn}</td></tr>")
            if not states:
                return main
            return main + (
                f"<tr class='ca-lines' style='display:none'><td colspan=7>"
                + self._alloc_table_html(states, "ca", ino, _ckey)
                + "</td></tr>")

        apply_rows = "".join(_capply_row(r) for r in open_inv)
        if cid:
            _all_tot = engine.invoice_totals_batch(con)
            _settled_inv = []
            for r in con.execute(
                    "SELECT invoice_no, invoice_date FROM invoices "
                    "WHERE customer_id=? ORDER BY invoice_no DESC",
                    (engine.cust_key(con, cid),)):
                _t = _all_tot.get(r["invoice_no"])
                if (_t and _t["paid"] > 0.009
                        and _t["balance"] <= 0.009
                        and engine.invoice_has_lines(con, r["invoice_no"])):
                    _settled_inv.append({
                        "invoice_no": r["invoice_no"],
                        "invoice_date": str(r["invoice_date"])[:10],
                        "total": _t["total"], "cash": _t["cash"],
                        "credit": _t["credit"], "balance": _t["balance"],
                        "paid": _t["paid"]})
            apply_rows += "".join(_capply_row(r) for r in _settled_inv)
        # Documents (Jason 2026-10-23, universality): a credit stays
        # a credit — it may also be applied against the customer's
        # open work orders, rental tickets, sales, and quotes, blanket
        # or by line (cd__ / cdl__ fields, parsed beside a__).
        # Build 't' fix (2026-10-25): the ticket query named a column
        # that does not exist (out_date) — picking any customer on
        # this form raised and the whole Apply surface was
        # unreachable. The ticket's date is its on_rent.
        doc_rows = []
        if cid:
            _ckey = engine.cust_key(con, cid)
            _docs = []
            for r in con.execute(
                    "SELECT wo_id, wo_date FROM work_orders "
                    "WHERE customer_id=? AND charge_to='customer' "
                    "AND invoice_id IS NULL ORDER BY wo_id DESC",
                    (_ckey,)):
                _docs.append(("wo", r["wo_id"], r["wo_date"]))
            for r in con.execute(
                    "SELECT ticket_id, on_rent FROM tickets "
                    "WHERE customer_id=? AND invoice_id IS NULL "
                    "ORDER BY ticket_id DESC", (_ckey,)):
                _docs.append(("ticket", r["ticket_id"], r["on_rent"]))
            for r in con.execute(
                    "SELECT sale_id, MIN(sale_date) AS d FROM sales "
                    "WHERE customer_id=? "
                    "GROUP BY sale_id ORDER BY sale_id DESC",
                    (_ckey,)):
                _docs.append(("sale", r["sale_id"], r["d"]))
            for r in con.execute(
                    "SELECT quote_no, quote_date FROM quotes "
                    "WHERE customer_id=? ORDER BY quote_no DESC",
                    (_ckey,)):
                if engine.quote_money_block(con, r["quote_no"]):
                    continue  # closed or carried — its money moved
                _docs.append(("quote", r["quote_no"], r["quote_date"]))
            for r in con.execute(
                    "SELECT co_no, co_date FROM change_orders "
                    "WHERE customer_id=? AND status='Issued' "
                    "ORDER BY co_no DESC",
                    (_ckey,)):
                _docs.append(("change", r["co_no"], r["co_date"]))
            for _kind, _ref, _dt in _docs:
                _tot = float(engine.doc_total(con, _kind, _ref))
                _bal = float(engine.doc_balance(con, _kind, _ref))
                if _tot <= 0.005:
                    continue
                _set = _tot - _bal
                # Open documents take a credit up to their balance; a
                # settled document takes a NEGATIVE credit up to what
                # it has settled (re-opening) — same listing, the cap
                # and the line table follow the direction that fits.
                if _bal > 0.005:
                    _cap, _ckey = _bal, "remaining"
                elif _set > 0.005:
                    _cap, _ckey = _set, "allocated"
                else:
                    continue
                _q = html.escape(_ref, quote=True)
                _states = engine.doc_line_states(con, _kind, _ref)
                _lbtn = (" <button type=button class=ca-lines-btn>"
                         "Lines</button>" if _states else "")
                _main = (
                    f"<tr><td>{engine.DOC_LABELS[_kind]} {_q}"
                    f"{' · settled' if _ckey == 'allocated' else ''}</td>"
                    f"<td>{html.escape(fmt_date(_dt or ''))}</td>"
                    f"<td>${_tot:,.2f}</td><td>${_set:,.2f}</td>"
                    f"<td>${_bal:,.2f}</td>"
                    f"<td><input name=cd__{_kind}__{_q} type=number "
                    f"step=0.01 min=0 max='{_cap:.2f}' "
                    f"placeholder='0.00'>{_lbtn}</td></tr>")
                if _states:
                    _main += (
                        f"<tr class='ca-lines' style='display:none'>"
                        f"<td colspan=6>"
                        + self._alloc_table_html(
                            _states, f"cdl__{_kind}", _ref, _ckey)
                        + "</td></tr>")
                doc_rows.append(_main)
        doc_block = (
            f"""<h2 style="font-size:16px;color:var(--frame)">Documents</h2>
            <table><tr><th>Document</th><th>Date</th><th>Total</th><th>Settled</th><th>Balance</th><th>Apply</th></tr>
            {''.join(doc_rows)}</table>"""
            if doc_rows else "")
        leftovers = engine.list_open_credits(con, cid or None)
        cm_opts = []
        for r in leftovers:
            v = str(r["cm_no"])
            d = (f"{v} · {r['customer_id']} · unapplied "
                 f"${float(r['unapplied']):,.2f}"
                 f"{' (negative)' if float(r['unapplied']) < 0 else ''}")
            cm_opts.append((v, d, v))
        cm_combo = (
            combo_field("f_cm_no", "cm_no_text", cm_opts,
                        label="Open credit memo", required=True,
                        placeholder="Type to search credit memos…")
            + '<input type=hidden id="f_cm_no_id" name=cm_no value="">'
        )
        leftovers_capped = leftovers[:5]
        left_table = "".join(
            f"<tr><td><a href='/summary/credit/{html.escape(r['cm_no'])}'>{html.escape(r['cm_no'])}</a></td>"
            f"<td>{html.escape(fmt_date(r['cm_date']))}</td><td>{html.escape(r['customer_id'])}</td>"
            f"<td>{'Negative credit — ' if r['face'] < 0 else ''}{html.escape(r['reason'])}</td>"
            f"<td>${r['face']:,.2f}</td><td>${r['applied']:,.2f}</td><td>${r['unapplied']:,.2f}</td></tr>"
            for r in leftovers_capped
        )
        if len(leftovers) > 5:
            left_table += f"<tr><td colspan=7><button type='button' class='vbtn' data-audit='/money/credits/audit' data-title='Credit memos audit'>View More ({len(leftovers)-5} More)</button></td></tr>"
        apply_block = (
            f"""<h2 style="font-size:16px;color:var(--frame)">Apply Now (Optional)</h2>
            <table><tr><th>Invoice</th><th>Date</th><th>Total</th><th>Cash</th><th>Credit</th><th>Balance</th><th>Apply</th></tr>
            {apply_rows or '<tr><td colspan=7>No open invoices.</td></tr>'}</table>
            {doc_block}"""
            if cid else
            ""
        )
        leftover_popup = (
            f"""<div class="viewrow"><button type="button" class="vbtn" onclick="document.getElementById('cmleftpop').style.display='block'">Apply Leftover</button></div>
            <div id="cmleftpop" style="display:none;position:fixed;top:8%;left:8%;right:8%;background:white;border:2px solid #333;padding:18px;z-index:1000;max-height:84%;overflow:auto">
            <h3 style="margin-top:0">Apply Leftover <span style="float:right"><button type="button" onclick="document.getElementById('cmleftpop').style.display='none'">Close</button></span></h3>
            <p class="hint">Same customer only. A credit cannot exceed each balance; a negative credit cannot exceed what each document has settled.</p>
            <form method=post action="/credit/apply">
              {cm_combo}
              <label>Date</label><input type=date name=pay_date class=w-sm value="{today}">
              <table><tr><th>Invoice</th><th>Date</th><th>Total</th><th>Cash</th><th>Credit</th><th>Balance</th><th>Apply</th></tr>
              {apply_rows or '<tr><td colspan=7>No open invoices.</td></tr>'}</table>
              {doc_block}
              <p><button>Apply Leftover</button></p>
            </form>
            </div>"""
            if leftovers and cid else
            # Build 'r' (Jason 2026-10-25, facelift item 3): the
            # no-customer "Open Credit Memos" TABLE no longer renders
            # below the form — it is a display list, and lists live
            # behind the page's View button (/money/credits/audit).
            # Build 't' (same day, universal form law): the Apply
            # Leftover FORM no longer stands below the form either —
            # it lives in its own popup (#cmleftpop, the universal
            # off-form pattern), behind the Apply Leftover door above
            # it. Same form, same fields, same /credit/apply post.
            ""
        )
        cm_no = engine.peek_next_doc(con, "next_cm", "CM", "credit_memos", "cm_no")
        # Invoice dropdown for reference
        invs = con.execute("SELECT invoice_no, invoice_date FROM invoices ORDER BY invoice_date DESC LIMIT 20").fetchall()
        picked_inv = (q.get("invoice_no") or "").strip()
        if picked_inv and picked_inv not in {r[0] for r in invs}:
            _picked_row = con.execute(
                "SELECT invoice_no, invoice_date FROM invoices WHERE invoice_no=?",
                (picked_inv,)).fetchone()
            if _picked_row:
                invs = [_picked_row] + list(invs)
        inv_opts = "".join(
            f"<option value='{html.escape(str(r[0]), quote=True)}' data-date='{html.escape(str(r[1])[:10], quote=True)}'"
            f"{' selected' if str(r[0]) == picked_inv else ''}>{html.escape(str(r[0]))} · {fmt_date(r[1])}</option>"
            for r in invs)
        # Invoice line pulls (credit memo multi-line build): when the
        # picked Invoice Ref names an existing invoice, offer its lines
        # as one-click pulls into the grid. (Build 't': the standalone
        # "Invoice Ref pulls lines." hint paragraph that stood here is
        # removed — the universal form law leaves no stray copy in the
        # form flow; the Invoice Ref field lives in the Job Info popup
        # and the pulls speak for themselves when a ref is picked.)
        pull_block = ''
        if picked_inv:
            _inv_exists = con.execute(
                "SELECT invoice_no FROM invoices WHERE invoice_no=?",
                (picked_inv,)).fetchone()
            if _inv_exists:
                _pull_rows = []
                for r in con.execute(
                        """SELECT line_id, category, item, description, qty, uom, rate, amount, tax_amount, tax_exempt
                           FROM invoice_lines WHERE invoice_no=? ORDER BY line_id""",
                        (picked_inv,)):
                    _qty = float(r["qty"] or 0)
                    _rate = float(r["rate"] or 0)
                    _amt = float(r["amount"] or 0)
                    _taxed = "1" if (not r["tax_exempt"] and float(r["tax_amount"] or 0) > 0) else "0"
                    _visible = (
                        f"{html.escape(str(r['item'] or ''))} — "
                        f"{html.escape(str(r['description'] or ''))} · "
                        f"{_qty:g} {html.escape(str(r['uom'] or ''))} "
                        f"× ${_rate:,.2f} = ${_amt:,.2f}")
                    _pull_rows.append(
                        f"<div class=\"cm-pull-row\"><span>{_visible}</span> "
                        f"<button type=button class=\"cm-pull\""
                        f" data-type=\"{html.escape(str(r['category'] or ''), quote=True)}\""
                        f" data-item=\"{html.escape(str(r['item'] or ''), quote=True)}\""
                        f" data-desc=\"{html.escape(str(r['description'] or ''), quote=True)}\""
                        f" data-qty=\"{html.escape(f'{_qty:g}', quote=True)}\""
                        f" data-uom=\"{html.escape(str(r['uom'] or ''), quote=True)}\""
                        f" data-rate=\"{html.escape(str(r['rate'] or 0), quote=True)}\""
                        f" data-taxed=\"{_taxed}\""
                        f" data-lineid=\"{html.escape(str(r['line_id']), quote=True)}\""
                        f" data-inv=\"{html.escape(picked_inv, quote=True)}\">Add to memo</button></div>")
                pull_block = (
                    f"<div class=\"cm-pulls\">"
                    f"<h2 style=\"font-size:16px;color:var(--frame)\">Lines on {html.escape(picked_inv)} — add the ones this memo credits:</h2>"
                    f"{''.join(_pull_rows)}</div>")
        # Header zone (build 'r', Jason 2026-10-25, facelift item 4;
        # two-row form build 't', same day, universal form law):
        # Company block, CM # + Date, bar, Issue Customer left, Job
        # Info box right (the picked Invoice Ref), then the memo's
        # work. Invoice Ref lives in the Job Info popup (same name,
        # same onchange — it reloads the page with the pick, from the
        # popup as from the page) and shows in the header box.
        # Build 't': Inv Date, Reason, and Upload move into the Job
        # Info popup too (route (b) — required fields live in Job
        # Info; the engine enforces Reason itself, so the
        # requirement stands server-side, per the build 'r' F5
        # pattern). Below the lines only the Credit Total (the
        # memo's totals) and Notes remain. Apply Now and the line
        # pulls stay above the grid: they are the memo's application
        # mechanism, not fields (flagged in PHASER-REPORT, carried
        # in PHASET-REPORT).
        _cm_extra = (f'<div class="row"><div><label>Invoice Ref</label>'
                     f'<select name=invoice_no id=cm_inv onchange="var d=this.options[this.selectedIndex].getAttribute(\'data-date\');if(d){{document.getElementById(\'cm_inv_date\').value=d}}if(this.value){{var hc=document.getElementById(\'f_cred_cust_id\');location=\'/money?tab=credit&invoice_no=\'+encodeURIComponent(this.value)+(hc&&hc.value?\'&customer_id=\'+encodeURIComponent(hc.value):\'\')}}">'
                     f'<option value="">— Pick or Type —</option>{inv_opts}</select></div></div>'
                     f'<div class="row"><div><label>Inv Date</label><input type=date name=inv_date id=cm_inv_date class=w-sm></div>'
                     f'<div><label>Reason</label><input name=reason maxlength=2000 placeholder="Billed twice / wrong dates / courtesy"></div></div>'
                     f'<div><label>Upload</label><input type=file name=cm_upload></div>')
        _cm_doc = f'CM # <input name=cm_no value="{cm_no}" class=w-xs>'
        _cm_date = f'<label>Date</label> <input type=date name=cm_date value="{today}" required class=w-sm>'
        return f"""
        <form method=post action="/credit" enctype="multipart/form-data">
          {self._form_head(con, _cm_doc, _cm_date, issue_cust_combo, [("Invoice Ref", picked_inv)])}
          {apply_block}
          {pull_block}
          <input type=hidden name=tax_ui value="1">
          <div id="cm-lines">
            {self._line_head()}
            <div class="iline">
              <div><label>Type</label>{cm_type_opts}</div>
              <div><label>Item</label><input name=item list="fs_item_list"></div>
              <div><label>Description</label><textarea name=item_desc class=ldesc rows=1></textarea></div>
              <div><label>Qty</label><input name=qty class="iqty w-xs" type=number step=0.01 value=1></div>
              <div><label>Unit</label>{cm_uom_opts}</div>
              <div><label>Rate $</label><span class="rate-x"><input name=rate class="irate w-sm" type=number step=0.01 value=0><button type=button class=line-del title="Delete line item">✕</button></span><label style="display:block;margin-top:4px"><input type=checkbox name=taxable value=1 checked class=itaxable> Tax</label></div>
            </div>
          </div>
          <div style="display:flex;flex-wrap:wrap;gap:24px;align-items:flex-start;margin-top:8px">
            <div style="text-align:right;margin-left:auto">
              <div>Credit Total <b id="cm-total">$0.00</b></div>
            </div>
          </div>
          <div><label>Notes</label><input name=notes style="width:100%"></div>
          {self._btn_row("Save", "cmjobpop", add_item=True)}
          {self._job_info_popup('cmjobpop', None, _cm_extra)}
        </form>
        <script>
        (function(){{var box=document.getElementById('cm-lines'); if(!box)return; var form=box.closest('form');
        function num(v){{v=parseFloat(v); return isNaN(v)?0:v;}}
        function calc(){{var total=0; box.querySelectorAll('.iline').forEach(function(r){{var q=r.querySelector('.iqty'),rt=r.querySelector('.irate'); total+=num(q&&q.value)*num(rt&&rt.value);}}); var el=document.getElementById('cm-total'); if(el)el.textContent='$'+total.toFixed(2);}}
        form.addEventListener('input',calc); form.addEventListener('change',calc); calc();
        form.addEventListener('change',function(e){{var t=e.target; if(t&&t.matches&&t.matches('select[data-kind="inv_cat"]')){{var r=t.closest('.iline'); if(r){{var cb=r.querySelector('.itaxable'); if(cb){{cb.checked=(t.value||'').trim().toLowerCase().indexOf('freight')!==0;}}}}}}}});
        function cloneRow(){{var rows=box.querySelectorAll('.iline'); var n=rows.length; var c=rows[0].cloneNode(true);
        c.querySelectorAll('[name]').forEach(function(el){{var base=el.name.replace(/\\d+$/,''); el.name=base+n;}});
        c.querySelectorAll('input,textarea').forEach(function(el){{if(el.classList.contains('itaxable')){{el.checked=true; el.value='1';}} else if(el.classList.contains('iqty'))el.value='1'; else if(el.classList.contains('irate'))el.value='0'; else el.value='';}});
        c.querySelectorAll('select').forEach(function(el){{el.selectedIndex=0;}});
        return {{row:c, n:n}};}}
        function setField(row,name,val){{var el=row.querySelector('[name="'+name+'"]'); if(el)el.value=val;}}
        function setSelect(row,kind,val){{var s=row.querySelector('select[data-kind="'+kind+'"]'); if(!s)return; var has=false; Array.prototype.forEach.call(s.options,function(o){{if(o.value===val||o.text===val)has=true;}}); if(has){{try{{s.value=val;}}catch(e){{}} if(s.value!==val){{Array.prototype.forEach.call(s.options,function(o){{if(o.text===val)s.value=o.value;}});}}}}}}
        var btn=null; form.querySelectorAll('button[type=button]').forEach(function(b){{if(b.textContent.trim().toLowerCase()==='add item')btn=b;}});
        if(btn){{btn.addEventListener('click',function(){{var made=cloneRow(); box.appendChild(made.row); calc();}});}}
        document.querySelectorAll('.cm-pull').forEach(function(b){{b.addEventListener('click',function(){{var made=cloneRow(); var c=made.row, n=made.n;
        setSelect(c,'inv_cat',b.getAttribute('data-type')||'');
        setField(c,'item'+n,b.getAttribute('data-item')||'');
        setField(c,'item_desc'+n,b.getAttribute('data-desc')||'');
        setField(c,'qty'+n,b.getAttribute('data-qty')||'1');
        setSelect(c,'inv_uom',b.getAttribute('data-uom')||'');
        setField(c,'rate'+n,b.getAttribute('data-rate')||'0');
        var cb=c.querySelector('.itaxable'); if(cb){{cb.checked=(b.getAttribute('data-taxed')==='1'); cb.value='1';}}
        var h1=document.createElement('input'); h1.type='hidden'; h1.name='srcinv'+n; h1.value=b.getAttribute('data-inv')||''; c.appendChild(h1);
        var h2=document.createElement('input'); h2.type='hidden'; h2.name='srcline'+n; h2.value=b.getAttribute('data-lineid')||''; c.appendChild(h2);
        box.appendChild(c); calc();}});}});
        }})();
        </script>
        <script>
        (function(){{
          document.querySelectorAll('.ca-lines-btn').forEach(function(btn){{
            btn.addEventListener('click', function(){{
              var tr = btn.closest('tr');
              var nx = tr && tr.nextElementSibling;
              if (nx && nx.classList.contains('ca-lines')) nx.style.display = (nx.style.display === 'none') ? '' : 'none';
            }});
          }});
          document.querySelectorAll('.ca-lines .alloc-full').forEach(function(cb){{
            cb.addEventListener('change', function(){{
              var scope = cb.closest('form') || document;
              var inp = scope.querySelector('input[name="' + cb.dataset.name + '"]');
              if (inp) inp.value = cb.checked ? cb.dataset.rem : '';
            }});
          }});
        }})();
        </script>
        {leftover_popup}
        """ + _item_extras(con)

    def _frag_petty_form(self, con, frag=False):
        book = engine.petty_book(con)
        today = date.today().isoformat()
        desk = html.escape(self.desk(con), quote=True)
        # Fragment mode (Admin popup iframe): forms stay in the frame
        # and saves redirect back into it; the row Print menu becomes
        # a plain link to the drawer print route (the page=True menu
        # needs bundle JS the fragment shell does not carry).
        _ftarget = ' target="_self"' if frag else ''
        _fhidden = '<input type=hidden name=frag value="1">' if frag else ''
        _pmenu = None
        if frag:
            # Popup print (Jason 2026-10-24): the popup keeps the
            # header (bar) Print only — the formal drawer print stays
            # on the full page, not duplicated inside the popup.
            _pmenu = ""
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
            <form method=post action="/petty"{_ftarget} style="margin:0">
              {_fhidden}
              <input type=hidden name=direction value="out">
              {self._top_commit("Cash Out")}
              <div class="row"><div><label>Date</label><input type=date name=txn_date value="{today}" required class=w-sm></div>
              <div><label>Amount</label><input name=amount type=number step=0.01 min=0.01 required class=w-sm></div></div>
              <div class="row"><div>{out_cat_combo}</div><div><label>Payee</label><input name=payee class=w-sm></div></div>
              <div class="row"><div><label>Ref</label><input name=ref_no class=w-xs></div></div>
              <div><label>Notes</label><input name=notes></div>
              {self._btn_row(None, "pettyoutjobpop", print_menu=_pmenu)}
              {self._job_info_popup('pettyoutjobpop')}
            </form>
          </div>
          <div class="card" style="padding:10px">
            <h2 style="font-size:14px;margin:0 0 6px">Cash In</h2>
            <form method=post action="/petty"{_ftarget} style="margin:0">
              {_fhidden}
              <input type=hidden name=direction value="in">
              {self._top_commit("Cash In")}
              <div class="row"><div><label>Date</label><input type=date name=txn_date value="{today}" required class=w-sm></div>
              <div><label>Amount</label><input name=amount type=number step=0.01 min=0.01 required class=w-sm></div></div>
              <div class="row"><div><label>Category</label><select name=category class=w-sm>{in_opts}</select></div><div><label>From</label><input name=payee placeholder="Bank / owner" class=w-sm></div></div>
              <div class="row"><div><label>Ref</label><input name=ref_no class=w-xs></div></div>
              <div><label>Notes</label><input name=notes></div>
              {self._btn_row(None, "pettyinjobpop", print_menu=_pmenu)}
              {self._job_info_popup('pettyinjobpop')}
            </form>
          </div>
        </div>
        """

    def view_customers(self, con):
        # No inline index list (Jason 2026-10-21, look-see batch 2 —
        # the universal form rule): Done Today below is the recent
        # list, and the full filterable/sortable list lives behind
        # the box's View button (/customers/all, rows open the
        # customer). The inline table that used to sit here was
        # neither filterable nor sortable.
        return chain_banner_rerun(con, "customer") + tabs_admin("/customers") + """<p style="margin:0 0 8px"><a class="btn" href="/customer/new">+ New Customer</a></p>
        """ + self._view_door("/customers/all", "All customers — audit")

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
        <p class="hint"><input id="auditq" placeholder="Filter" size="30"
        oninput="document.querySelectorAll('table.audit').forEach(t=>auditFilter(t,this.value))">
        </p>
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
        # Batch 3 #6 (terms as a class): the customer form offers the
        # FULL enabled terms list on open — a lookup_select, not the
        # type-to-search combo (whose list only appeared after clearing
        # the text). Other type-over and -Add- ride the global rule;
        # the stored value rides along in vals when off-set, so an
        # existing record's terms are never hidden by the filter.
        terms_list = list(enabled_values(con, "terms"))
        terms_cur = row["terms"] if row else "Net 30"
        if terms_cur and terms_cur not in terms_list:
            terms_list.append(terms_cur)
        terms_combo = (
            "<label>Payment terms</label>"
            + lookup_select(con, "terms", "terms", current=terms_cur,
                            vals=terms_list, add_option=True,
                            extra="required", css="w-sm")
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
          <h2>Contacts</h2>
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
          <h2>Locations</h2>
          <table><tr><th>Location</th><th>Address</th><th>City / State / ZIP</th><th></th><th></th></tr>{loc_html}</table>
          <form method=post action="/customer/location/save" style="margin-top:8px">
            <input type=hidden name=customer_id value="{html.escape(cid)}">
            <div class=row><div><label>Location Name</label><input name=location_name placeholder="Main office, Lafayette yard, Houston branch" required></div><div></div></div>
            <label>Address</label><input name=street>
            <input name=street2 placeholder="Suite, building, c/o…">
            <div class=row><div><label>City</label><input name=city></div><div><label>State</label>{state_field("state", "", 'maxlength=20')}</div></div>
            <div class=row><div><label>Zip</label><input name=zip maxlength=12></div><div></div></div>
            <label><input type=checkbox name=is_primary value=1> Make primary location</label>
            <p><button class=secondary>Add Location</button></p>
          </form>
        </section>
        """
        # PO register (Batch 3 #15): this customer's PO numbers with
        # their stored status. A PO carrying a scan links through to
        # the invoice that holds it.
        po_block = ""
        if cid:
            try:
                _po_rows = con.execute(
                    """SELECT po_no, status, expire FROM purchase_orders
                       WHERE customer_id=? ORDER BY po_no""", (cid,)).fetchall()
            except Exception:
                _po_rows = []
            if _po_rows:
                def _po_link(_po_no):
                    _inv = con.execute(
                        """SELECT i.invoice_no FROM invoices i
                           JOIN invoice_docs d ON d.invoice_no = i.invoice_no
                           WHERE i.customer_id=? AND TRIM(i.po)=? AND d.kind='po'
                           ORDER BY i.invoice_date DESC LIMIT 1""",
                        (cid, _po_no)).fetchone()
                    if not _inv:
                        _inv = con.execute(
                            """SELECT invoice_no FROM invoices
                               WHERE customer_id=? AND TRIM(po)=?
                               ORDER BY invoice_date DESC LIMIT 1""",
                            (cid, _po_no)).fetchone()
                    if _inv:
                        return (f"<a href='/invoice/{html.escape(_inv['invoice_no'], quote=True)}'>"
                                f"{html.escape(_inv['invoice_no'])}</a>")
                    return ""
                _po_html = "".join(
                    f"<tr><td>{html.escape(r['po_no'])}</td>"
                    f"<td>{html.escape(r['status'] or 'Open')}</td>"
                    f"<td>{html.escape(fmt_date(r['expire']))}</td>"
                    f"<td>{_po_link(r['po_no'])}</td></tr>"
                    for r in _po_rows)
                po_block = f"""
        <section class=card>
          <h2>Purchase Orders</h2>
          <table><tr><th>PO #</th><th>Status</th><th>Expires</th><th>Invoice</th></tr>{_po_html}</table>
        </section>
        """
        return chain_banner(con, "customer") + f"""
        <p class=hint>{'Customer ID: <b>'+html.escape(nxt)+'</b>' if row else 'Customer ID: auto.'}</p>
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
            <div class=row><div><label>City</label><input name=bill_city value="{html.escape(v('bill_city'))}"></div><div><label>State</label>{state_field("bill_state", v('bill_state'), 'maxlength=20')}</div></div>
            <div class=row><div><label>Zip</label><input name=bill_zip maxlength=12 value="{html.escape(v('bill_zip'))}"></div><div></div></div>
          </section>
          <section>
            <h2>Commercial terms</h2>
            <div class=row><div>{terms_combo}</div><div><label>Credit Limit $</label><input name=credit_limit type=number class=w-sm step=0.01 value="{money_val(v('credit_limit'))}"></div></div>
            <label><input type=checkbox name=waiver_default value=1 {"checked" if (not row) or row["waiver_default"] else ""}> Damage waiver on by default</label>
          </section>
          <section><label>Internal Notes</label><input name=notes value="{html.escape(v('notes'))}"></section>
          <p><button>Save Customer</button> <a class="btn secondary" href="/customers">Cancel</a></p>
        </form>
        {contact_block}
        {po_block}
        {self._view_row("/customers/all", "Customers")}
        """

    def view_reports(self, con, days=14, period="mtd", stay_from="", stay_to="", board="avail", show_all=False):
        """Reports: prebuilts + mixed builder."""
        return self._reports_prebuilts(con)

    def _reports_prebuilts(self, con=None):
        """The three weekly-meeting reports, plus the mixed-report builder
        card. Nothing else. Billing OFF drops the AR Aging card (a money
        report door); the mixed card stays — its builder gates money
        kinds itself."""
        billing_card = ("" if (con is not None
                               and not engine.module_on(con, "billing")) else """
          <div class="card"><span>Billing</span><b style="font-size:16px">
            <a href="/reports/weekly/money">AR Aging</a></b>
            <span class="hint">Who owes what, by age.</span></div>""")
        return f"""
        <div class="cards">{billing_card}
          <div class="card"><span>Fleet</span><b style="font-size:16px">
            <a href="/reports/weekly/fleet">Utilization</a></b>
            <span class="hint">Time on rent vs idle vs down, per unit.</span></div>
          <div class="card"><span>Pipeline</span><b style="font-size:16px">
            <a href="/reports/weekly/flow">This week's Flow</a></b>
            <span class="hint">What's moving through the shop.</span></div>
          <div class="card"><span>Mixed</span><b style="font-size:16px">
            <a href="/reports/mixed">Mixed report</a></b>
            <span class="hint">Sales + rentals, once or every month, saved.</span></div>
        </div>
        """

    def view_report_mixed(self, con, q):
        """Mixed report (Jason 2026-10-24): one time-based report carrying
        mixed data types — pick kinds, timeframe, customer, run, sort,
        filter, export, print, save it as a preset. Monthly presets ROLL:
        loading one runs the current month (a fixed month is a once
        report with that month's from/to). Print is browser print with
        the page's print-head; no formal printpack page for a builder
        report whose rows change with the builder."""
        billing_on = engine.module_on(con, "billing")
        offered = [k for k in engine.MIXED_KINDS
                   if billing_on or not k[2]]
        # Resolve params: a preset load overrides the builder values.
        preset = None
        try:
            pid = int(q.get("preset") or 0)
        except ValueError:
            pid = 0
        if pid:
            preset = engine.get_mixed_preset(con, pid)
        if preset:
            kinds = [k for k in preset["kinds"].split(",") if k]
            time_mode = preset["time_mode"]
            date_from, date_to = preset["date_from"], preset["date_to"]
            month = "" if time_mode == "monthly" else preset["month"]
            customer = preset["customer_id"]
            filt, sort_col, sort_dir = (preset["filter_text"],
                                        preset["sort_col"], preset["sort_dir"])
            preset_name = preset["name"]
        else:
            kinds = [k for k, _, _ in offered if q.get("kind_" + k)]
            time_mode = q.get("time_mode") or "once"
            if time_mode not in ("once", "monthly"):
                time_mode = "once"
            date_from, date_to = q.get("from") or "", q.get("to") or ""
            month = q.get("month") or ""
            customer = q.get("customer") or ""
            filt, sort_col, sort_dir = "", 0, "desc"
            preset_name = ""
        kinds = [k for k in kinds if k in [o[0] for o in offered]]
        # Builder form (GET: the URL carries the report, so exports and
        # presets share the same params).
        kind_boxes = "".join(
            f'<label style="margin-right:10px"><input type="checkbox" '
            f'name="kind_{k}" value="1"'
            f'{" checked" if k in kinds else ""}> {lab}</label>'
            for k, lab, _ in offered)
        customers = con.execute(
            "SELECT customer_id, account_name FROM customers "
            "ORDER BY account_name").fetchall()
        cust_opts = '<option value="">All customers</option>' + "".join(
            f'<option value="{html.escape(c["customer_id"])}"'
            f'{" selected" if c["customer_id"] == customer else ""}>'
            f'{html.escape(c["account_name"])}</option>' for c in customers)
        once_style = "" if time_mode == "once" else ' style="display:none"'
        mon_style = "" if time_mode == "monthly" else ' style="display:none"'
        builder = f"""
        <form method="get" action="/reports/mixed" class="fgrid">
          <p>{kind_boxes}</p>
          <p><label><input type="radio" name="time_mode" value="once"
             {"checked" if time_mode == "once" else ""}> Once</label>
             <label><input type="radio" name="time_mode" value="monthly"
             {"checked" if time_mode == "monthly" else ""}> Every month</label></p>
          <p id="mixed-once"{once_style}>From
             <input type="date" name="from" value="{html.escape(date_from)}">
             To <input type="date" name="to" value="{html.escape(date_to)}"></p>
          <p id="mixed-monthly"{mon_style}>Month
             <input type="month" name="month" value="{html.escape(month)}"></p>
          <p><select name="customer">{cust_opts}</select>
             <button class="btn" type="submit">Run report</button></p>
        </form>
        <script>(function(){{
          var rs = document.querySelectorAll('input[name="time_mode"]');
          function tog(){{
            var m = document.querySelector('input[name="time_mode"]:checked').value === "monthly";
            document.getElementById('mixed-once').style.display = m ? "none" : "";
            document.getElementById('mixed-monthly').style.display = m ? "" : "none";
          }}
          rs.forEach(function(r){{ r.addEventListener('change', tog); }});
        }})();</script>
        """
        nav = tabs_reports("/reports", con)
        presets = engine.list_mixed_presets(con)
        plist = ""
        if presets:
            items = []
            for p in presets:
                kl = ", ".join(engine.MIXED_KIND_LABELS.get(k, k)
                               for k in p["kinds"].split(",") if k)
                tl = ("Monthly — rolls to the current month"
                      if p["time_mode"] == "monthly" else
                      f"Once {p['date_from']} to {p['date_to']}".strip())
                items.append(
                    f'<li><a href="/reports/mixed?preset={p["preset_id"]}">'
                    f'{html.escape(p["name"])}</a> ({html.escape(kl)}; '
                    f'{html.escape(tl)}) '
                    f'<form method="post" action="/reports/mixed/delete" '
                    f'style="display:inline" '
                    f'onsubmit="return confirm(\'Delete preset '
                    f'{html.escape(p["name"], quote=True)}?\')">'
                    f'<input type="hidden" name="preset_id" value="{p["preset_id"]}">'
                    f'<button class="btn secondary" type="submit">Delete</button>'
                    f'</form></li>')
            plist = "<p><b>Saved presets</b></p><ul>" + "".join(items) + "</ul>"
        if not kinds:
            return (nav + builder + plist +
                    "<p>No kinds picked yet. Pick kinds and run.</p>")
        rng_from, rng_to = engine.mixed_range(time_mode, date_from, date_to,
                                              month)
        rows, totals = engine.mixed_rows(con, kinds, rng_from, rng_to,
                                         customer)
        extra = ("&".join(f"kind_{k}=1" for k in kinds)
                 + f"&time_mode={time_mode}&from={rng_from}&to={rng_to}"
                 + (f"&month={month}" if time_mode == "monthly" else "")
                 + (f"&customer={customer}" if customer else ""))
        sub = " · ".join(
            f"{engine.MIXED_KIND_LABELS[k]}: ${totals[k]:,.2f}"
            for k, _, _ in offered if k in kinds)
        trs = "".join(
            f"<tr><td>{html.escape(r['date'])}</td>"
            f"<td>{html.escape(r['type'])}</td>"
            f"<td>{html.escape(r['ref'])}</td>"
            f"<td>{html.escape(r['customer'])}</td>"
            f"<td>{html.escape(r['unit'])}</td>"
            f"<td class=n>${r['amount']:,.2f}</td>"
            f"<td>{html.escape(r['status'])}</td></tr>" for r in rows)
        heads = "".join(f"<th>{c}</th>" for c in engine.MIXED_COLUMNS)
        save = f"""
        <form method="post" action="/reports/mixed/save" id="mixed-save"
              style="margin:12px 0">
          <input name="name" size="30" placeholder="Preset name"
                 value="{html.escape(preset_name, quote=True)}">
          <input type="hidden" name="kinds" value="{','.join(kinds)}">
          <input type="hidden" name="time_mode" value="{time_mode}">
          <input type="hidden" name="from" value="{html.escape(rng_from)}">
          <input type="hidden" name="to" value="{html.escape(rng_to)}">
          <input type="hidden" name="month" value="{html.escape(month)}">
          <input type="hidden" name="customer" value="{html.escape(customer)}">
          <input type="hidden" name="f_q" value="">
          <input type="hidden" name="f_sort_col" value="0">
          <input type="hidden" name="f_sort_dir" value="desc">
          <button class="btn" type="submit">Save preset</button>
          <span class="hint">Re-saving a name updates that preset.</span>
        </form>
        """
        dest = ('<div class="actions">'
                # One Print, three choices (Jason 2026-10-24): the
                # mixed report's old standalone window.print button is
                # now the standard page menu (Screen / PRINT / Location
                # on the current page, live values included).
                + self._print_menu(page=True)
                + f'<a class="btn" href="/export/report/mixed.csv?{extra}">Csv</a>'
                + f'<a class="btn" href="/export/report/mixed.xlsx?{extra}">Excel</a>'
                + f'<a class="btn secondary" href="/export/report/mixed.json?{extra}">Json</a>'
                + f'<a class="btn secondary" href="/export/report/mixed.zip?{extra}">Zip</a>'
                + '</div>')
        body = (f"<p>{sub}</p>" if rows else
                "<p>No rows in this range.</p>")
        if rows:
            body += (f'<p class="hint"><input id="auditq" placeholder="Filter" '
                     f'size="30" value="{html.escape(filt, quote=True)}" '
                     f'oninput="document.querySelectorAll(\'table.audit\').forEach(t=>auditFilter(t,this.value))"></p>'
                     f'<table class="audit"><tr>{heads}</tr>{trs}</table>'
                     + AUDIT_TABLE_JS)
        reapply = ""
        if preset and (filt or sort_col != 0 or sort_dir != "desc"):
            reapply = (f"<script>(function(){{"
                       f"var t = document.querySelector('table.audit');"
                       f"var q = document.getElementById('auditq');"
                       f"if (q && {json.dumps(filt)})"
                       f"{{ q.value = {json.dumps(filt)}; "
                       f"if (t) auditFilter(t, {json.dumps(filt)}); }}"
                       f"if (t && {sort_col} !== null) {{"
                       f"var th = t.rows[0].cells[{sort_col}];"
                       f"if (th) {{ th.click();"
                       f"if ({json.dumps(sort_dir)} === 'desc') th.click(); }}}}"
                       f"}})();</script>")
        track = (f"<script>(function(){{"
                 f"var t = document.querySelector('table.audit');"
                 f"if (!t) return;"
                 f"window.__mixedSort = {{col: 0, dir: 'desc'}};"
                 f"Array.from(t.rows[0].cells).forEach(function(th, c){{"
                 f"var orig = th.onclick;"
                 f"th.onclick = function(){{ if (orig) orig();"
                 f"window.__mixedSort = {{col: c, dir: "
                 f"(t.getAttribute('data-sorted') == String(c) ? 'asc' : 'desc')}}; }};"
                 f"}});"
                 f"var sf = document.getElementById('mixed-save');"
                 f"if (sf) sf.addEventListener('submit', function(){{"
                 f"var q = document.getElementById('auditq');"
                 f"if (q) sf.querySelector('[name=f_q]').value = q.value;"
                 f"sf.querySelector('[name=f_sort_col]').value = window.__mixedSort.col;"
                 f"sf.querySelector('[name=f_sort_dir]').value = window.__mixedSort.dir;"
                 f"}});"
                 f"}})();</script>")
        return (nav + builder + dest + body + save + track + reapply + plist)

    # ------------------------------------------------- Weekly push-button reports

    def _report_destinations(self, base, extra=""):
        """Print / PDF / CSV / Excel buttons for a prebuilt report."""
        return (
            '<div class="actions">'
            + self._print_menu(screen=f"/print/report/{base}{extra}",
                               pdf=f"/print/report/{base}.pdf{extra}")
            + f'<a class="btn" href="/export/report/{base}.csv{extra}">Csv</a>'
            + f'<a class="btn" href="/export/report/{base}.xlsx{extra}">Excel</a>'
            + f'<a class="btn secondary" href="/export/report/{base}.json{extra}">Json</a>'
            + f'<a class="btn secondary" href="/export/report/{base}.zip{extra}">Zip</a>'
            + "</div>"
        )

    def view_report_weekly_money(self, con):
        """Weekly money = the canonical AR aging table. Nothing else."""
        rep = engine.ar_aging(con)
        nav = tabs_reports("/reports", con) + weekly_tabs("/reports/weekly/money", con)
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
                f"<p class=\"hint\">As of {html.escape(fmt_date(rep['today']))}. Open balances only — no collected/invoiced summary.</p>"
                + self._report_destinations("aging")
                + f"<table class=\"audit\"><tr><th>Customer</th>{heads}<th class=n>Total</th></tr>"
                f"{rows or '<tr><td colspan=7>Nothing owed.</td></tr>'}"
                f"<tr><td><b>Total</b></td>{total}<td class=n><b>${rep['grand']:,.2f}</b></td></tr>"
                f"<tr><td>% of Total</td>{pct}<td></td></tr></table>"
                + AUDIT_TABLE_JS)

    def view_report_weekly_fleet(self, con, q):
        try:
            days = max(1, min(365, int(q.get("days") or 30)))
        except (TypeError, ValueError):
            days = 30
        rep = engine.fleet_utilization(con, days)
        nav = tabs_reports("/reports", con) + weekly_tabs("/reports/weekly/fleet", con)
        rows = "".join(
            f"<tr><td><b>{html.escape(r['unit_no'])}</b><br><span class=\"hint\">{html.escape(r['category'])}</span></td>"
            f"<td class=n>{r['rent_days']}</td><td class=n>{r['idle_days']}</td>"
            f"<td class=n>{r['down_days']}</td><td class=n>{r['util_pct']:.1f}%</td>"
            f"<td class=n>${r['revenue']:,.2f}</td></tr>"
            for r in rep["rows"])
        return (nav
                + "<h2 style=\"font-size:19px;color:var(--frame)\">Fleet Utilization</h2>"
                f"<p class=\"hint\">Last {rep['days']} days ({html.escape(fmt_date(rep['start']))} to {html.escape(fmt_date(rep['end']))}). "
                "Days only."
                + " ".join(f"<a href=\"/reports/weekly/fleet?days={d}\">{d}d</a>" for d in (7, 30, 90))
                + "</p>"
                + self._report_destinations("fleet", f"?days={rep['days']}")
                + "<table class=\"audit\"><tr><th>Unit</th><th class=n>Days on rent</th>"
                "<th class=n>Idle days</th><th class=n>Down (shop)</th><th class=n>Util %</th>"
                f"<th class=n>Revenue</th></tr>{rows}</table>"
                + AUDIT_TABLE_JS)

    def view_report_weekly_flow(self, con, q):
        span = "month" if (q.get("span") or "") == "month" else "week"
        rep = engine.weeks_flow(con, span)
        nav = tabs_reports("/reports", con) + weekly_tabs("/reports/weekly/flow", con)
        label = {k: lab for k, lab, _ in engine.FLOW_SECTIONS}
        sub = {k: s for k, _, s in engine.FLOW_SECTIONS}
        title = ("This week's flow" if span == "week"
                 else "Flow — exceptions, next 30 days")
        head = (nav
                + f"<h2 style=\"font-size:19px;color:var(--frame)\">{title}</h2>"
                + f"<p class=\"hint\">{html.escape(fmt_date(rep['start']))} to {html.escape(fmt_date(rep['end']))}. "
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
                f"<td>{html.escape(i['who'])}</td><td>{html.escape(fmt_date(i['when']))}</td>"
                + (f"<td>{html.escape(i.get('why') or '')}</td>" if span == "month" else "")
                + "</tr>" for i in items)
            parts.append(
                f"<h2 style=\"font-size:16px;color:var(--frame)\">{html.escape(label.get(key, key))} "
                f"<span class=\"hint\">— {html.escape(sub.get(key, ''))}</span></h2>"
                f"<table class=\"audit\"><tr><th>What</th><th>Who</th><th>When</th>{why}</tr>"
                f"{rows or '<tr><td colspan=4>Nothing.</td></tr>'}</table>")
        return "".join(parts)

    def view_money_audit(self, con):
        """Every money record, as it sits — filterable, sortable."""
        big = engine.big_fish_invoices(con)["invoice_nos"]
        inv_rows = "".join(
            f"<tr><td><a href='/invoice/{html.escape(r['invoice_no'])}'>{html.escape(r['invoice_no'])}</a></td>"
            f"<td>{html.escape(r['account_name'])}</td>"
            f"<td>{html.escape(fmt_date(r['invoice_date']))}</td>"
            f"<td>{html.escape(r['status'])}</td>"
            f"<td>${engine.invoice_totals(con, r['invoice_no'])['balance']:,.2f}</td>"
            f"<td>{'<b>Key Account</b>' if r['invoice_no'] in big else ''}</td>"
            "<td>" + _task_from_row(r['invoice_no'] + " — " + r['account_name'], "/invoice/" + r['invoice_no'], '/money/audit') + "</td></tr>"
            for r in con.execute(
                """SELECT i.invoice_no, i.invoice_date, i.status, c.account_name
                   FROM invoices i JOIN customers c ON c.id = i.customer_id""")
        )
        pay_rows = "".join(
            f"<tr><td>{html.escape(fmt_date(r['pay_date']))}</td>"
            f"<td><a href='/invoice/{html.escape(r['invoice_no'])}'>{html.escape(r['invoice_no'])}</a></td>"
            f"<td>{html.escape(r['method'])}</td><td>${r['amount']:,.2f}</td>"
            f"<td>{html.escape(r['kind'])}</td>"
            "<td>" + _task_from_row(r['kind'] + " $" + ("%.2f" % r['amount']) + " on " + r['invoice_no'], "/invoice/" + r['invoice_no'], '/money/audit') + "</td></tr>"
            for r in con.execute(
                """SELECT c.pay_date, COALESCE(i.invoice_no, '') AS invoice_no,
                   c.method, c.amount, c.kind
                   FROM collections c
                   LEFT JOIN invoices i ON i.id = c.invoice_id""")
        )
        return tabs_invoice("/money/all", con) + f"""
        <p class="hint"><input id="auditq" placeholder="Filter" size="30"
        oninput="document.querySelectorAll('table.audit').forEach(t=>auditFilter(t,this.value))">
        </p>
        <h2>Invoices</h2>
        <table class="audit"><tr><th>No</th><th>Customer</th><th>Date</th><th>Status</th><th>Balance</th><th>Flag</th><th></th></tr>
        {inv_rows or '<tr><td colspan=7>No invoices.</td></tr>'}</table>
        <h2>Payments &amp; Credits</h2>
        <table class="audit"><tr><th>Date</th><th>Invoice</th><th>Method</th><th>Amount</th><th>Kind</th><th></th></tr>
        {pay_rows or '<tr><td colspan=6>No payments.</td></tr>'}</table>
        """ + AUDIT_TABLE_JS

    def view_quotes_all(self, con):
        """Quotes list fragment — the universal View popup's content
        for the Quote pages (build 'r', Jason 2026-10-25)."""
        rows = con.execute(
            """SELECT q.quote_no, q.quote_date, q.status, c.account_name
               FROM quotes q
               LEFT JOIN customers c ON c.id = q.customer_id
               ORDER BY q.quote_date DESC, q.quote_no DESC""").fetchall()
        def _qtot(qno):
            try:
                return float(engine.quote_totals(con, qno)["face"])
            except Exception:
                return 0.0
        body = "".join(
            f"<tr><td><a href='/summary/quote/{html.escape(r['quote_no'], quote=True)}'>"
            f"{html.escape(r['quote_no'])}</a></td>"
            f"<td>{html.escape(fmt_date(r['quote_date']))}</td>"
            f"<td>{html.escape(r['account_name'] or '')}</td>"
            f"<td>{html.escape(r['status'] or '')}</td>"
            f"<td>${_qtot(r['quote_no']):,.2f}</td></tr>"
            for r in rows)
        return (f"<input id=auditq placeholder='Filter…' oninput='auditFilter(this)'>"
                f"<h2>Quotes</h2>"
                f"<table class=audit><tr><th>Quote #</th><th>Date</th>"
                f"<th>Customer</th><th>Status</th><th>Total</th></tr>"
                f"{body or '<tr><td colspan=5>No quotes.</td></tr>'}</table>"
                + AUDIT_TABLE_JS)

    def view_invoices(self, con):
        rows = con.execute(
            """SELECT i.invoice_no, i.invoice_date, i.status, i.customer_id, c.account_name
               FROM invoices i JOIN customers c ON c.id=i.customer_id
               ORDER BY i.invoice_date DESC"""
        ).fetchall()
        body = "".join(
            f"<tr><td>{html.escape(r['invoice_no'])}</td>"
            f"<td>{html.escape(r['account_name'])}</td>"
            f"<td>{html.escape(fmt_date(r['invoice_date']))}</td>"
            f"<td>{html.escape(r['status'])}</td>"
            f"<td>${engine.invoice_totals(con, r['invoice_no'])['balance']:,.2f}</td>"
            f"<td><a href='/invoice/{html.escape(r['invoice_no'])}'>Open</a> "
            + self._print_menu(screen=f"/print/invoice/{r['invoice_no']}",
                               pdf=f"/print/invoice/{r['invoice_no']}.pdf",
                               compact=True)
            + "</td></tr>"
            for r in rows
        )
        # The tab is the title (tab-echo rule) — no H1. The money
        # picture leads (it lived on the /money tab page until the
        # 2026-10-24 landing change; since build 't' the Invoices
        # place opens to the blank editor and this register is
        # reached from the tabs and the View lists).
        return (tabs_invoice("/invoices", con) + self._money_picture(con)
                + f"""<table><tr><th>No</th><th>Customer</th><th>Date</th><th>Status</th><th>Balance</th><th></th></tr>
        {body or '<tr><td colspan=6>No invoices.</td></tr>'}</table>""")

    def view_invoice_lines(self, con, ino):
        inv = con.execute(
            """SELECT i.*, c.account_name FROM invoices i
               JOIN customers c ON c.id=i.customer_id WHERE i.invoice_no=?""",
            (ino,),
        ).fetchone()
        if not inv:
            return tabs_invoice("/invoices", con) + "<p>Unknown invoice.</p>"
        tot = engine.invoice_totals(con, ino)
        locked = engine.invoice_locked(con, ino)
        lines = con.execute(
            "SELECT * FROM invoice_lines WHERE invoice_id=? ORDER BY line_id", (inv["id"],)
        ).fetchall()
        # Display table in the printed invoice's columns (Invoice
        # Round Part B): ITEM | DESCRIPTION | QTY | UNIT | UNIT PRICE
        # | LINE TOTAL. The description cell is the description text
        # only — category / PO line / clerk are NOT folded into it;
        # PO line data stays on the line itself.
        # ITEM type defaults (tweak round 4, mirroring print): a
        # line with no stored Item text falls back to its category's
        # default — Labor / Part / Freight (asset lines carry their
        # equipment number as the stored item or show blank here and
        # resolve it in printpack's pack builder).
        def _detail_item(r):
            _it = (r["item"] if "item" in r.keys() and r["item"] else "")
            _it = str(_it).strip()
            if not _it:
                try:
                    _cat = r["category"] if "category" in r.keys() else ""
                except Exception:
                    _cat = ""
                _c = str(_cat or "").strip().lower()
                if _c == "labor" or "labor" in _c:
                    _it = "Labor"
                elif _c in ("part", "parts") or "part" in _c:
                    _it = "Part"
                elif _c == "freight" or "freight" in _c:
                    _it = "Freight"
            return _it
        # Per-line paid state (Jason 2026-10-23): the Paid / Open
        # columns appear only when payments have been broken down by
        # line against this invoice. They read allocations only — a
        # blanket-paid line still reads open here; the balance governs.
        _states = {s["line_id"]: s
                   for s in engine.invoice_line_states(con, ino)}
        _has_alloc = engine.invoice_has_line_allocations(con, ino)
        # The Note column (the short-pay marker) rides with the paid
        # columns, or stands alone once any line carries a note, so a
        # note can always be edited or cleared where it is read.
        _show_note = _has_alloc or any(
            s["note"] for s in _states.values())

        def _line_row(r):
            _paid_cells = ""
            if _has_alloc:
                _st = _states.get(int(r["line_id"]))
                _cred_seg = ""
                if _st and _st["credited"] > 0:
                    _refs = ", ".join(html.escape(x)
                                       for x in _st["credit_refs"])
                    _cred_seg = (f" <span class=hint>(credit {_refs} "
                                 f"${_st['credited']:,.2f})</span>")
                if _st and _st.get("cash_paid", 0) > 0:
                    _cred_seg += (f" <span class=hint>(cash "
                                  f"${_st['cash_paid']:,.2f})</span>")
                if _st and _st.get("carried", 0) > 0:
                    _cred_seg += (f" <span class=hint>(carried "
                                  f"${_st['carried']:,.2f})</span>")
                _paid_cells = (
                    f"<td>${(_st['allocated'] if _st else 0):,.2f}{_cred_seg}</td>"
                    f"<td>${(_st['remaining'] if _st else 0):,.2f}</td>")
            _note_cell = ""
            if _show_note:
                _st = _states.get(int(r["line_id"]))
                _note_cell = (
                    f"<td>{note_pop_html(_st['note']) if _st else ''}</td>")
            return (
                f"<tr><td>{html.escape(_detail_item(r))}</td>"
                f"<td>{html.escape(r['description'])}</td>"
                f"<td>{float(r['qty']):g}</td>"
                f"<td>{html.escape(r['uom'] or '')}</td>"
                f"<td>${float(r['rate']):,.2f}</td>"
                f"<td>${float(r['amount']):,.2f}</td>"
                f"{_paid_cells}{_note_cell}</tr>")

        body = "".join(_line_row(r) for r in lines)
        _paid_head = "<th>Paid</th><th>Open</th>" if _has_alloc else ""
        if _show_note:
            _paid_head += "<th>Note</th>"
        _lines_colspan = 6 + (2 if _has_alloc else 0) + (1 if _show_note else 0)
        # Line work (build 'u', Jason 2026-10-25, universal summary
        # pattern): the summary's lines state as facts — the per-line
        # note forms and the per-line delete that stood in the table
        # ride in the Edit Lines popup with the Add a Line form. Same
        # posts (/linenote, /linedel, /line), same lock rules: note
        # forms render whenever the Note column does (a short-pay note
        # is written after payment, on a locked invoice too); delete
        # and Add a Line only while the invoice is unlocked.
        def _work_row(r):
            _st = _states.get(int(r["line_id"]))
            _nv = html.escape(_st["note"] if _st else "", quote=True)
            _note_form = (
                f"<form method=post "
                f"action=\"/invoice/{html.escape(ino, quote=True)}/linenote\">"
                f"<input type=hidden name=line_id value=\"{int(r['line_id'])}\">"
                f"<input name=note value=\"{_nv}\" class=w-sm> "
                f"<button class=secondary>Save</button></form>"
                if _show_note else "")
            _del = ("" if locked else
                    '<form method=post action=/invoice/' + html.escape(ino)
                    + '/linedel>'
                    + '<input type=hidden name=invoice_no value=' + html.escape(ino)
                    + '><input type=hidden name=line_id value=' + str(r['line_id'])
                    + '><button class=line-del-submit title="Delete line item">✕</button></form>')
            return (
                f"<tr><td>{html.escape(_detail_item(r))}</td>"
                f"<td>{html.escape(r['description'])}</td>"
                f"<td>{_note_form}</td><td>{_del}</td></tr>")
        line_work_rows = "".join(_work_row(r) for r in lines)
        if locked and not _show_note:
            # Nothing in the popup would be workable: no Add a Line,
            # no delete, no note forms. The door drops with it.
            line_work_rows = ""
        # Add-a-Line Tax toggle default (Invoice Round Part C):
        # UNCHECKED when the invoice's customer is exempt
        # (customers.tax_exempt), a tax-exempt certificate is on file
        # for THIS invoice (invoice_docs kind='tax_exempt'), or the
        # invoice already carries an operator exemption
        # (invoices.tax_exempt_op — guarded, the column may not exist
        # yet); CHECKED otherwise.
        _line_tax_checked = " checked"
        try:
            _cr = con.execute(
                "SELECT tax_exempt FROM customers WHERE id=?",
                (inv["customer_id"],)).fetchone()
            _cust_exempt_line = bool(_cr and _cr[0])
        except Exception:
            _cust_exempt_line = False
        try:
            _cert_exempt_line = con.execute(
                "SELECT 1 FROM invoice_docs WHERE invoice_id=? "
                "AND kind='tax_exempt' LIMIT 1", (inv["id"],)).fetchone() is not None
        except Exception:
            _cert_exempt_line = False
        _op_exempt_line = False
        try:
            if "tax_exempt_op" in inv.keys():
                _op_exempt_line = bool(inv["tax_exempt_op"])
        except Exception:
            _op_exempt_line = False
        if _cust_exempt_line or _cert_exempt_line or _op_exempt_line:
            _line_tax_checked = ""
        # One universal line-item row (Jason 2026-10-24, 'm' look-see
        # item 10): the same .iline row the invoice editor and every
        # other form use — not a stacked mini-form of its own.
        add = "" if locked else f"""
        <form method=post action="/invoice/{html.escape(ino)}/line">
          <input type=hidden name=tax_ui value="1">
          {self._line_head()}
          <div class="iline">
            <div><label>Type</label>{lookup_select(con, "inv_cat", "category", blank=True)}<label>PO Line #</label><input name=po_line placeholder="10" class=w-xs></div>
            <div><label>Item</label><input class="iitem" name=item list="fs_item_list"></div>
            <div><label>Description</label><textarea class="ldesc" name=description required rows=2></textarea></div>
            <div><label>Qty</label><input class="iqty" name=qty type=number step=0.01 min=0.01 value=1 required></div>
            <div><label>Unit</label>{lookup_select(con, "inv_uom", "uom", blank=True, vals=enabled_values(con, "inv_uom"), add_option=False)}</div>
            <div><label>$ Rate</label><input class="irate" name=rate type=number step=0.01 value=0 required>
            <label class="hint" style="display:block;font-weight:400"><input type=checkbox class="itaxable" name=taxable value=1{_line_tax_checked}> Tax</label></div>
          </div>
          <p><button>Add Line</button></p>
        </form>
        <script>
        (function(){{var cat=document.querySelector('select[name=category]'); if(!cat)return; var form=cat.closest('form'); var tax=form?form.querySelector('input[name=taxable]'):null; if(!tax)return; var dflt=tax.checked; function sync(){{var v=cat.value.trim().toLowerCase(); tax.checked=(v.indexOf('freight')===0)?false:dflt;}} cat.addEventListener('change',sync);}})();
        </script>
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
        po_total_val = f"{_pc0['total']:.2f}" if _pc0.get("total") else ""
        # PO status (Batch 3 #15): the register's stored value — a
        # select on the PO form when the invoice is editable, plain
        # text once it is locked. Never derived.
        po_status_val = _pc0.get("status") or "Open"
        if locked:
            po_status_sel = (
                f"<div><label>PO Status</label>"
                f"<input value=\"{html.escape(po_status_val)}\" disabled class=w-sm></div>")
        else:
            _po_opts = "".join(
                f"<option{' selected' if po_status_val == _st else ''}>{html.escape(_st)}</option>"
                for _st in engine.PO_STATUSES)
            po_status_sel = (
                f"<div><label>PO Status</label>"
                f"<select name=po_status>{_po_opts}</select></div>")
        # Document layout (restyle, tweak round 2): this page adopts
        # the printed invoice's arrangement. The Job Info box sits
        # bottom-left beside the totals column and honors the SAME
        # expanded Setup -> Billing toggle set as the print/PDF boxes
        # — it is built from printpack's own field list via
        # invoice_pack, so the three renderings cannot drift. The
        # on-screen box keeps its "Job Info" heading (prior ruling);
        # only the printed box has no caption. PO expiry is record
        # data and never appears here or as a line.
        _jb = engine.invoice_job_box(con, ino)
        from printpack import (_company_blocks, _inv_totals_rows_html,
                               _jobinfo_lines as _pp_jil, invoice_pack as _pp_pack)
        _pack = None
        try:
            _pack = _pp_pack(con, ino)
        except Exception:
            _pack = None
        _jb_rows = ""
        _totals_col = ""
        doc_header = ""
        if _pack is not None:
            _jb_rows = "".join(
                f"<div>{html.escape(label)} <b>{html.escape(str(value))}</b></div>"
                for label, value in _pp_jil(_pack))
            _totals_col = _inv_totals_rows_html(_pack)
            # Sales Tax always renders on the detail page (tweak
            # round 4, mirroring the print rule): printpack's totals
            # helper currently omits the row at $0.00, so when it did
            # the views layer inserts the $0.00 row before Grand
            # Total. Guarded by the "Sales Tax" presence check — if
            # printpack renders the row itself, nothing is added and
            # the row never duplicates.
            if _totals_col and "Sales Tax" not in _totals_col:
                _tax_row = ("<tr><td class='n'>Sales Tax</td>"
                            f"<td class='n'>${float(tot['tax']):,.2f}</td></tr>")
                _gt = "<tr><td class='n'>Grand Total</td>"
                if _gt in _totals_col:
                    _totals_col = _totals_col.replace(
                        _gt, _tax_row + _gt, 1)
                elif "</table>" in _totals_col:
                    _totals_col = _totals_col.replace(
                        "</table>", _tax_row + "</table>", 1)
            _pco, _pinv = _pack["co"], _pack["inv"]
            _remit, _dist = _company_blocks(_pco)
            _remit_html = "<br>".join(html.escape(x) for x in _remit if x)
            _dist_html = ""
            # Jason 2026-10-24 (screenshot read): when the billing and
            # physical addresses are the same lines, the Remit To block
            # already says it — printing the Distribution block too
            # shows the company address twice. Suppress the duplicate
            # only when identical; a shop with two different addresses
            # still gets both blocks.
            if _dist and [x.strip() for x in _dist if x] != [x.strip() for x in _remit if x]:
                _dist_html = f"""
              <div style="flex:1 1 240px;min-width:220px">
                <div style="font-weight:700;color:var(--frame)">{html.escape(_pco['name'])}</div>
                <div style="font-size:10px;color:#5C6B7A;text-transform:uppercase">Distribution Address</div>
                <div style="font-size:12px">{'<br>'.join(html.escape(x) for x in _dist if x)}<br>{html.escape(_pco['phone'] or '')}<br>{html.escape(_pco['billing_email'] or '')}</div>
              </div>"""
            _bill_bits = []
            if _pinv["bill_to"] and _pinv["bill_to"] != _pinv["account_name"]:
                _bill_bits.append(_pinv["bill_to"])
            _bill_bits += [_pinv["bill_street"], _pinv["bill_street2"],
                           _pinv["city_st"]]
            _bill_html = "<br>".join(html.escape(x) for x in _bill_bits if x)
            _ship_html = ""
            if _pack.get("ship_to"):
                _sblocks = []
                for s in _pack["ship_to"]:
                    _cityline = ", ".join(x for x in (
                        s.get("city"),
                        " ".join(y for y in (s.get("state"), s.get("zip")) if y)) if x)
                    _sbits = [s.get("operator"), s.get("rig_name"),
                              s.get("street"), s.get("street2"), _cityline]
                    _sblocks.append(
                        f"<b>{html.escape(s.get('site_name') or '')}</b>"
                        + ("<br>" + "<br>".join(html.escape(x) for x in _sbits if x)
                           if any(_sbits) else ""))
                _ship_html = f"""
              <div style="flex:1 1 240px;min-width:220px;border:1px solid #c5cdd6;padding:10px"><div style="font-size:10px;color:#5C6B7A;text-transform:uppercase">Ship To</div>
                {'<br>'.join(_sblocks)}
              </div>"""
            _terms_line = ""
            if _pinv["terms"]:
                _terms_line = f"<div style=\"font-size:12px\">Terms: {html.escape(_pinv['terms'])}</div>"
            job_box = f"""
        <div style="border:1px solid #1B2A4A;padding:10px 14px;min-width:230px;font-size:14px">
          <div style="font-weight:700;color:#1B2A4A;margin-bottom:6px">Job Info</div>
          {_jb_rows}
        </div>""" if _jb_rows else ""
            _job_col = f"""
              <div style="flex:1 1 240px;min-width:220px">{job_box}</div>""" if job_box else ""
            doc_header = f"""
        <div style="display:flex;flex-wrap:wrap;gap:24px;border-bottom:3px solid var(--frame);padding-bottom:10px">
          <div style="flex:1 1 240px;min-width:220px">
            <div style="font-size:10px;color:#5C6B7A;text-transform:uppercase">Remit To:</div>
            <div style="font-weight:700;color:var(--frame)">{html.escape(_pco['name'])}</div>
            <div style="font-size:12px">{_remit_html}<br>{html.escape(_pco['phone'] or '')}<br>{html.escape(_pco['billing_email'] or '')}</div>
          </div>{_dist_html}
          <div style="margin-left:auto;text-align:right">
            <div style="font-size:20px;font-weight:700">Invoice # {html.escape(ino)}</div>
            <div>Date: {html.escape(fmt_date(_pinv['invoice_date']))}</div>
            {_terms_line}
          </div>
        </div>
        <div style="display:flex;flex-wrap:wrap;gap:16px;margin-top:8px">
          <div style="flex:1 1 240px;min-width:220px;border:1px solid #c5cdd6;padding:10px"><div style="font-size:10px;color:#5C6B7A;text-transform:uppercase">Billing Address:</div>
            <b>{html.escape(_pinv['account_name'])}</b><br>{_bill_html}
          </div>{_ship_html}{_job_col}
        </div>"""
        job_totals_row = f"""
        <div style="display:flex;flex-wrap:wrap;gap:24px;align-items:flex-start;margin:10px 0">
          <div style="margin-left:auto">{_totals_col}</div>
        </div>""" if _totals_col else ""
        # No extra write-in row here (Invoice Round Part C): printpack's
        # totals column (job_totals_row above) now carries the write-in
        # row itself, so the Part B block that mirrored it under the
        # totals zone would duplicate it.
        # Paperwork scan-in slots (Part D: four typed slots): the PO scan,
        # the tax-exempt certificate, shipping paperwork, and one custom
        # slot the operator names (doc_title on its upload form). All
        # attach to the invoice and travel with it (print + PDF pack);
        # an occupied slot also carries its Print-with-invoice toggle —
        # an empty slot shows no toggle, there is nothing to print.
        _slot_docs = {"po": _jb.get("po_doc"), "tax_exempt": _jb.get("tax_doc"),
                      "shipping": _jb.get("shipping_doc"),
                      "custom": _jb.get("custom_doc")}
        def _slot(kind, label):
            d = _slot_docs.get(kind)
            heading = label
            if kind == "custom" and d and (d.get("title") or "").strip():
                heading = d["title"]
            cur = ""
            if d:
                _pw_on = d.get("print_with", 1)
                _pw_checked = " checked" if _pw_on is None or _pw_on else ""
                cur = (f"<div><a href='/invoicedoc/{html.escape(ino, quote=True)}/{kind}'>"
                       f"{html.escape(d['filename'])}</a> "
                       f"<span class='hint'>{d['bytes']/1024:.0f} KB · {html.escape(fmt_date(d['uploaded_at']))}</span> "
                       f"<form method=post action='/invoice/{html.escape(ino, quote=True)}/docdel' style='display:inline'>"
                       f"<input type=hidden name=kind value='{kind}'>"
                       f"<button class=secondary>Remove</button></form></div>"
                       f"<form method=post action='/invoice/{html.escape(ino, quote=True)}/docprint' class='actions'>"
                       f"<input type=hidden name=kind value='{kind}'>"
                       f"<label><input type=checkbox name=print_with value=1{_pw_checked}> Print with invoice</label> "
                       f"<button class=secondary>Save</button></form>")
            else:
                cur = "<div class='hint'>None attached.</div>"
            title_in = (f"<div><label>Document name</label>"
                        f"<input name=doc_title placeholder=\"Name this document\""
                        f" value=\"{html.escape(d['title'], quote=True) if d and (d.get('title') or '').strip() else ''}\"></div>"
                        if kind == "custom" else "")
            return f"""
          <div><b>{html.escape(heading)}</b>{cur}
            <form method=post action="/invoice/{html.escape(ino, quote=True)}/doc"
                  enctype="multipart/form-data" class="actions">
              {title_in}
              <input type=file name=doc_file accept=".pdf,.png,.jpg,.jpeg,.webp,.txt,.csv">
              <input type=hidden name=kind value="{kind}">
              <button class=secondary>Attach{' New' if d else ''}</button>
            </form>
          </div>"""
        paperwork = f"""
        <div class="row">{_slot("po", "PO scan")}{_slot("tax_exempt", "Tax-exempt certificate")}{_slot("shipping", "Shipping paperwork")}{_slot("custom", "Custom document")}</div>"""
        pays = con.execute(
            "SELECT c.*, cm.cm_no AS cm_number FROM collections c "
            "LEFT JOIN credit_memos cm ON cm.id = c.cm_id "
            "WHERE c.invoice_id=? ORDER BY c.pay_date, c.pay_id",
            (inv["id"],)
        ).fetchall()
        def _pay_row(p):
            _cf = (p["carried_from"] if "carried_from" in p.keys()
                   else "") or ""
            _cf_txt = ""
            if _cf:
                _ck, _, _cref = _cf.partition(":")
                _cnum = (engine.doc_num(con, _ck, _cref)
                         if _ck in engine.DOC_LABELS else None)
                _cf_txt = (f" <span class=hint>(carried from "
                           f"{engine.DOC_LABELS.get(_ck, _ck)} "
                           f"{html.escape(_cnum or _cref)})</span>")
            # A negative credit (Jason 2026-10-23) reads plainly as
            # one, with the note that is its record.
            _neg_txt = ""
            if p['kind'] == 'credit' and float(p['amount']) < 0:
                _cmr = con.execute(
                    "SELECT notes FROM credit_memos WHERE cm_no=?",
                    (p["cm_number"],)).fetchone() if p["cm_number"] else None
                _neg_txt = (" <span class=hint>(negative credit"
                            + (f" — {html.escape(_cmr[0])}"
                               if _cmr and _cmr[0] else "")
                            + ")</span>")
            row = (
                f"<tr><td>{html.escape(fmt_date(p['pay_date']))}</td>"
                f"<td>{'Credit memo' if p['kind']=='credit' else html.escape(p['method'] or '')}{_cf_txt}{_neg_txt}</td>"
                f"<td>{html.escape(p['cm_number']) if p['kind']=='credit' and p['cm_number'] else html.escape(p['ref_no'] or '')}</td>"
                f"<td>${float(p['amount']):,.2f}</td>"
                f"<td>${float(p['applied_amount'] if p['applied_amount'] is not None else p['amount']):,.2f}</td>"
                f"<td>{html.escape(p['clerk'] or '')}</td></tr>")
            # Line breakdown (Jason 2026-10-23): a payment or credit
            # broken down by line shows its split under its own row,
            # notes included.
            _al = engine.list_payment_allocations(
                con, pay_id=p["pay_id"], invoice_no=ino)
            if _al:
                _segs = []
                for a in _al:
                    _seg = (f"{html.escape(a['line_label'])} "
                            f"${float(a['amount']):,.2f}")
                    if a["source"] == "cash":
                        _seg += " (cash in)"
                    if a["line_note"]:
                        _seg += f" — {note_pop_html(a['line_note'])}"
                    _segs.append(_seg)
                row += (f"<tr><td></td><td colspan=5 class=hint>"
                        + " · ".join(_segs) + "</td></tr>")
            return row

        pay_rows = "".join(_pay_row(p) for p in pays)
        payments_html = f"""
        <h2 style="font-size:16px;color:var(--frame)">Payments &amp; Credits</h2>
        <table><tr><th>Date</th><th>Method</th><th>Ref / CM #</th><th>Amount</th><th>Applied</th><th>Input by:</th></tr>
        {pay_rows or '<tr><td colspan=6>No payments or credits applied yet.</td></tr>'}</table>
        """
        invpay_method_combo = (
            combo_field("f_invpay_method", "method_text",
                        [(m, m, m) for m in engine.CASH_METHODS],
                        label="Method", placeholder="Type to search methods…")
            + '<input type=hidden id="f_invpay_method_id" name=method value="">'
        )
        engine.stamp_module_seen(con, "billing")
        # Billing OFF (shop flow, Jason 2026-10-21): the Payment
        # section steps aside — the invoice itself, its payments
        # history and its print stay exactly as they are (records,
        # not doors). The heading is the noun "Payment" (Jason
        # 2026-10-24, build 'o' — the noun grammar of Invoice /
        # Payment / Credit Memo / Work Order); the #record-payment
        # anchor id stands, as the ticker and task links target it.
        pay_section = ("" if not engine.module_on(con, "billing") else f"""
        <h2 id="record-payment" style="font-size:16px;color:var(--frame)">Payment</h2>
        <form method=post action="/pay">
          <input type=hidden name=invoice_no value="{html.escape(ino, quote=True)}">
          <div class="row">
            <div><label>Amount</label><input name=amount type=number step=0.01 min=0.01 required class=w-sm></div>
            <div><label>Date</label><input type=date name=pay_date class=w-sm value="{date.today().isoformat()}" required></div>
          </div>
          <div class="row">
            <div><label>Ref / Check #</label><input name=ref></div>
            <div>{invpay_method_combo}</div>
          </div>
          <p><button>Apply Payment</button></p>
        </form>""")
        # Summary of Invoice# (build 'u', Jason 2026-10-25,
        # universal summary pattern): the existing view page becomes
        # the pattern — the printed-template header states the facts
        # (company, billing, ship-to, the Job Info box), the lines
        # and totals state as facts, the payments history states as
        # facts, and every act rides behind a popup door: Payment
        # (the payment form), Edit Lines (Add a Line + the per-line
        # note and delete forms), Job Info (the PO form — the
        # invoice's Job Info values), Paperwork (the four slots).
        # Edit and Print keep their places in the door row.
        po_form = f"""
        <form method=post action="/invoice/{html.escape(ino)}/po" id="po-form">
          <label>Customer PO</label>
          <input name=po value="{html.escape(po)}" {"readonly" if locked else ""}>
          <div class="frow">
            <div><label>PO Expires (Optional)</label><input type=date name=po_expire value="{html.escape(po_expire)}" {"readonly" if locked else ""}></div>
            <div><label>Cost Code (Optional)</label><input name=po_cost_code value="{html.escape(po_cost_code)}" placeholder="their cost code" {"readonly" if locked else ""}></div>
            <div><label>PO Total (Optional)</label><input name=po_total type=number step=0.01 value="{html.escape(po_total_val)}" placeholder="PO total" {"readonly" if locked else ""} class=w-sm></div>
            {po_status_sel}
          </div>
          <label>Other PO Requirements (Optional)</label>
          <input name=po_notes value="{html.escape(po_notes)}" placeholder="anything else their PO demands" {"readonly" if locked else ""}>
          {"" if locked else "<p><button>Save PO</button></p>"}
        </form>"""
        # The standard wrap, not a hand-built box: the wrap leads
        # with its <h3>, so the shell's section wrapper makes the
        # popup its own box and the collapse restore leaves its
        # display alone. A leading <span> instead gets the popup
        # absorbed into the Payments & Credits box, whose expanded
        # restore clears display:none — the popup stood open on
        # load (found in the build 'u' screenshot pass). The
        # #record-payment anchor rides at the top of the body.
        pay_popup = (self._pop_wrap(
            "invpay", "Payment",
            pay_section.replace(
                '<h2 id="record-payment" style="font-size:16px;'
                'color:var(--frame)">Payment</h2>',
                '<span id="record-payment"></span>'))
            if pay_section else "")
        lines_popup = (self._pop_wrap(
            "invlines", "Edit Lines",
            add + (f"<table><tr><th>Item</th><th>Description</th>"
                   f"<th>Note</th><th></th></tr>{line_work_rows}</table>"
                   if line_work_rows else ""))
            if (add or line_work_rows) else "")
        doors = (
            (self._pop_door("invpay", "Payment") if pay_section else "")
            + ((self._pop_door("invlines", "Edit Lines"))
               if (add or line_work_rows) else "")
            + self._pop_door("invjob", "Job Info")
            + self._pop_door("invpaper", "Paperwork")
            + ("" if locked else
               f"<a class=\"btn\" href=\"/invoice/new?edit={html.escape(ino, quote=True)}\">Edit</a> ")
            + self._print_menu(screen=f"/print/invoice/{ino}",
                               pdf=f"/print/invoice/{ino}.pdf"))
        popups = (
            pay_popup + lines_popup
            + self._pop_wrap("invjob", "Job Info", po_form)
            + self._pop_wrap("invpaper", "Paperwork", paperwork))
        _assoc_co = self._assoc_co_fact(con, "invoice", ino)
        _assoc_line = (f"<p>Associated: {_assoc_co}</p>"
                       if _assoc_co else "")
        return tabs_invoice("/invoices", con) + f"""
        <h1>Summary of Invoice# {html.escape(ino)}</h1>
        {doc_header}
        {task_nudge(con, f"/invoice/{ino}")}
        <p>Status: {html.escape(inv['status'])}</p>
        {_assoc_line}
        <div style="clear:both"></div>
        <table><tr><th>ITEM</th><th>DESCRIPTION</th><th>QTY</th><th>UNIT</th><th>UNIT PRICE</th><th>LINE TOTAL</th>{_paid_head}</tr>
        {body or f'<tr><td colspan={_lines_colspan}>No extra lines.</td></tr>'}</table>
        {job_totals_row}
        {po_panel}
        {quote_panel}
        {payments_html}
        <div class="viewrow" style="align-items:center">{doors}</div>
        {popups}
        {self._view_row("/money/invoices/audit", "Invoices")}
        """ + _item_extras(con)
