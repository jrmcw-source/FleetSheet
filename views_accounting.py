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
                 submit_name="", submit_value="", print_menu=None,
                 edit_pop=None):
        from views_core import CoreViews
        return CoreViews._btn_row(self, save_label, jobpop, add_item, extra,
                                  submit_name, submit_value, print_menu,
                                  edit_pop)

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
            # Void-and-revise (build 'ab', Jason 2026-10-26): an
            # existing invoice's form opens LOCKED — the record,
            # viewable and printable, its Edit door starting the
            # revision flow — unless it IS a fresh revision under
            # its session marker, when it opens unlocked as the
            # revision's own editor. The old invoice_locked refusal
            # page is superseded by the locked render.
            inv_mode = ("session" if engine.revision_pending(
                con, "invoice", inv["id"]) else "locked")
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
            if inv_mode == "session":
                editing_hidden += (
                    f'<input type=hidden name=edit_target '
                    f'value="{html.escape(inv_no, quote=True)}">')
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
        # Build 'am' (Jason 2026-10-28): the Transport suggestions
        # carry the haulers' own names — the company's dba/name,
        # and the invoice's customer's name when one stands on the
        # form. Free typing stands for any other carrier.
        _ship_opts = ""
        _co_tr = self.desk(con)
        if _co_tr:
            _ship_opts += (f'<option value="'
                           f'{html.escape(_co_tr, quote=True)} Transport">'
                           f'</option>')
        if inv is not None:
            # inv["customer_id"] carries the customer's CODE on
            # this form (converted at load, build 'v').
            _cr = con.execute(
                "SELECT account_name FROM customers WHERE customer_id=?",
                (inv["customer_id"],)).fetchone()
            if _cr and _cr["account_name"]:
                _ship_opts += (
                    f'<option value="'
                    f'{html.escape(_cr["account_name"], quote=True)} '
                    f'Transport"></option>')
        _inv_extra = f"""
            <div class="row">
              <div><label>Reference Ticket</label><input name=ref_ticket class=w-sm placeholder="Optional"{ref_attr}></div>
              <div><label>Terms</label>{terms_sel}</div>
            </div>
            <div class="row">
              <div><label>Header bar note</label><input name=bar_text placeholder="Header note"{bar_attr}></div>
              <div><label>Transport</label><input name=shipped_by list="inv-shipped-by" placeholder="Customer, company, or carrier…"{ship_attr}><datalist id="inv-shipped-by">{_ship_opts}</datalist></div>
            </div>"""
        _inv_doc = (f'Invoice # <a href="/invoice/{inv_no}">{inv_no}</a>'
                    if inv is not None and inv_mode == "locked" else
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
          {self._btn_row(None, "invjobpop", add_item=False, edit_pop="revpop", print_menu=self._print_menu(screen=f"/print/invoice/{inv_no}", pdf=f"/print/invoice/{inv_no}.pdf")) if inv is not None and inv_mode == "locked" else self._btn_row("Save", "invjobpop", add_item=True, submit_name="action", submit_value="save", print_menu=(self._print_menu(screen=f"/print/invoice/{inv_no}", pdf=f"/print/invoice/{inv_no}.pdf") if inv is not None else None))}
          {self._job_info_popup('invjobpop', job_vals, _inv_extra)}
          {self._revise_popup(con, "invoice", inv_no) if inv is not None and inv_mode == "locked" else ""}
        </form>
        {self._LOCK_JS if inv is not None and inv_mode == "locked" else ""}
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
            body = self._money_pay(con, q)
            view_url, view_title = "/money/payments/audit", "Payments — audit"
        elif tab == "credit":
            body = self._money_credit(con, q)
            view_url, view_title = "/money/credits/audit", "Credit memos — audit"
        elif tab == "cash":
            body = self._money_cash(con, q)
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

    def _money_pay(self, con, q=None):
        ticker = ''
        # Build 'ai' (Jason 2026-10-28): a money summary's Payment
        # button lands here with doc=<kind>:<ref> — the form opens
        # with that record prefilled as the allocation target.
        # Kinds are the engine's payable kinds; anything else is
        # ignored and the blank form stands.
        _doc = ((q or {}).get("doc") or "").strip()
        _pk, _, _pr = _doc.partition(":")
        prefill = ((_pk, _pr.strip())
                   if _pk in engine.PAYABLE_KINDS and _pr.strip()
                   else None)
        return ticker + self._frag_pay_form(
            con, edit_batch=((q or {}).get("edit") or "").strip() or None,
            rev_batch=((q or {}).get("rev") or "").strip() or None,
            prefill=prefill)

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
        return tabs + self._money_petty(
            con, frag=frag, edit_no=(q or {}).get("edit"))

    def _money_petty(self, con, frag=False, edit_no=None):
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
            "<button type='button' class='mini' onclick='wpopPrint()'>Print</button>"
            "<button type='button' class='mini' onclick='closeFloatpop()'>Close</button>")
        # Slim strip, no company band — the popup bar already titles
        # the drawer, and the full page's title does the same.
        header = (
            "<div style=\"display:flex;flex-wrap:wrap;gap:24px\">"
            + "<div style=\"margin-left:auto;text-align:right\">"
            + (f"<p class='actions' style='margin:0 0 6px'>{self._print_menu(screen='/print/petty', pdf='/print/petty.pdf')}</p>" if not frag else "")
            + "<div style=\"font-size:10px;color:#5C6B7A;text-transform:uppercase\">Next entry</div>"
            + f"<div style=\"font-size:20px;font-weight:700\">{html.escape(engine.peek_pc_id(con))}</div>"
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
        def _petty_row(r):
            # Build 'ab' (redirect #2): the register shows the
            # entry's number; live rows carry the Edit door to the
            # entry's own form; a voided row shows the chain and no
            # running figure (its money stands in its revision).
            _run = (f"${r['running']:,.2f}"
                    if r["running"] is not None else "—")
            _door = ""
            _state = ""
            if r.get("revised_by_id"):
                _head = con.execute(
                    "SELECT pc_id FROM petty_cash WHERE id=?",
                    (r["revised_by_id"],)).fetchone()
                _state = (" — Void, revised by "
                          + (_head[0] if _head else "")
                          + (f": {r['void_reason']}" if r["void_reason"] else "")
                          + (f" ({r['void_by']})" if r["void_by"] else ""))
            else:
                _door = (f"<br><a href='/petty?edit="
                         f"{html.escape(r['pc_id'], quote=True)}'"
                         f"{' target=_top' if frag else ''}>Edit</a>")
            return (
                f"<tr><td>{html.escape(fmt_date(r['txn_date']))}</td>"
                f"<td>{html.escape(r['pc_id'])}{_door}</td>"
                f"<td>{html.escape(r['direction'])}</td>"
                f"<td>{html.escape(r['category'])}</td>"
                f"<td>{html.escape(r['payee'])}</td>"
                f"<td>${r['signed']:,.2f}</td><td>{_run}</td>"
                f"<td>{html.escape(r['ref_no'])}</td>"
                f"<td>{note_pop_html(r['notes'])}{html.escape(_state)}</td></tr>")
        _reg_rows = "".join(_petty_row(r) for r in book["rows"])
        register = (
            "<h2 style=\"font-size:16px;color:var(--frame)\">Petty cash register</h2>"
            "<p class=\"hint\"><input id=\"auditq\" placeholder=\"Filter\" size=\"30\" "
            "oninput=\"document.querySelectorAll('table.audit').forEach(t=>auditFilter(t,this.value))\"></p>"
            "<table class=\"audit\"><tr><th>Date</th><th>No.</th><th>Dir</th><th>Category</th><th>Payee</th>"
            "<th>Amount</th><th>Running</th><th>Ref</th><th>Notes</th></tr>"
            f"{_reg_rows or '<tr><td colspan=9>Empty box.</td></tr>'}</table>")
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
        return ticker + header + cards + self._frag_petty_form(con, frag=frag, edit_no=edit_no) + register + done + scripts

    def _money_cash(self, con, q=None):
        return (self._frag_cash_form(con, (q or {}).get("edit"))
                + self._cash_list_html(con))

    def _frag_cash_form(self, con, edit_no=None):
        # Build 'ab' (redirect #2): a loaded cash entry opens LOCKED
        # like every posted document; Edit starts its revision; the
        # session Save completes it through record_cash_entry's own
        # path (complete_cash_revision). A new entry's number field
        # carries the generated default, overwritable.
        today = date.today().isoformat()
        mode = "new"
        vals = {}
        erow = None
        if edit_no:
            erow = next(
                (r for r in engine.list_cash_entries(con)
                 if r.get("entry_no") == edit_no), None)
            if erow is None:
                return (f"<p class='card'>Cash entry {html.escape(edit_no)} "
                        f"is not on record.</p>")
            if erow.get("revised_by_id"):
                _head = con.execute(
                    "SELECT entry_no FROM cash_entries WHERE entry_id=?",
                    (erow["revised_by_id"],)).fetchone()
                _hn = _head[0] if _head else ""
                return (
                    f"<p class='card'>Cash entry {html.escape(edit_no)} was "
                    f"voided — revised as "
                    f"<a href='/money?tab=cash&edit={html.escape(_hn, quote=True)}'>"
                    f"{html.escape(_hn)}</a>, the live entry at the head "
                    f"of its chain.</p>")
            vals = erow
            mode = ("session" if engine.revision_pending(
                con, "cash", erow["entry_id"]) else "locked")

        def _mark(opts, value):
            if value:
                opts = opts.replace(
                    f"value='{html.escape(str(value), quote=True)}'",
                    f"value='{html.escape(str(value), quote=True)}' selected", 1)
            return opts
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
        if vals:
            cust_opts = _mark(cust_opts, vals.get("customer_id"))
            inv_opts = _mark(inv_opts, vals.get("invoice_no"))
            wo_opts = _mark(wo_opts, vals.get("wo_no"))
            tick_opts = _mark(tick_opts, vals.get("ticket_id"))
            sale_opts = _mark(sale_opts, vals.get("sale_group"))
            quote_opts = _mark(quote_opts, vals.get("quote_no"))
            co_opts = _mark(co_opts, vals.get("co_no"))
            asset_opts = _mark(asset_opts, vals.get("asset_id"))
            if vals.get("method"):
                method_opts = method_opts.replace(
                    f"<option>{html.escape(vals['method'])}</option>",
                    f"<option selected>{html.escape(vals['method'])}</option>", 1)
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
        _eno_val = (vals.get("entry_no") if vals
                    else engine.peek_cash_entry_no(con))
        _dir_in = " selected" if vals.get("direction") == "in" else ""
        _dir_out = " selected" if vals.get("direction") == "out" else ""
        _row = (self._btn_row(None, edit_pop="revpop")
                if mode == "locked" else self._btn_row("Save"))
        _revpop = (self._revise_popup(con, "cash", vals["entry_no"])
                   if mode == "locked" else "")
        _hidden = (f"<input type=hidden name=edit_target "
                   f"value=\"{html.escape(vals['entry_no'], quote=True)}\">"
                   if mode == "session" else "")
        _lock = self._LOCK_JS if mode == "locked" else ""
        return f"""
        <form method=post action="/cash/save">
          {_hidden}
          <!-- Compact (Jason 2026-10-24, screenshot read): the old
               2-col .row grid gave every field half the screen — a
               3-character Direction select sat in a half-screen track.
               .frow rows size each field to its content instead: the
               whole entry form is three short rows, not a tall stack.
               Field order and names unchanged. -->
          <div class="frow">
            <div><label>Entry #</label><input name=entry_no value="{html.escape(_eno_val or '', quote=True)}" class=w-sm></div>
            <div><label>Date</label><input type=date name=entry_date value="{vals.get('entry_date') or today}" required class=w-sm></div>
            <div><label>Direction</label><select name=direction class=w-xs><option value="in"{_dir_in}>In</option><option value="out"{_dir_out}>Out</option></select></div>
            <div><label>Method</label><select name=method class=w-sm>{method_opts}</select></div>
            <div><label>Amount</label><input name=amount type=number step=0.01 min=0.01 required class=w-sm value="{vals.get('amount') or ''}"></div>
          </div>
          <div class="frow">
            <div style="flex:1 1 240px"><label>Customer</label><select name=customer_id><option value="">— From attachment —</option>{cust_opts}</select></div>
            <div><label>Asset</label><select name=asset_id class=w-sm><option value="">—</option>{asset_opts}</select></div>
            <div style="flex:1 1 240px"><label>Notes</label><input name=notes value="{html.escape(vals.get('notes') or '', quote=True)}"></div>
          </div>
          <div class="frow">
            <div><label>Quote #</label><select name=quote_no class=w-sm><option value="">—</option>{quote_opts}</select></div>
            <div><label>Invoice #</label><select name=invoice_no class=w-sm><option value="">—</option>{inv_opts}</select></div>
            <div><label>Work Order #</label><select name=wo_no class=w-sm><option value="">—</option>{wo_opts}</select></div>
            <div><label>Rental Ticket #</label><select name=ticket_id class=w-sm><option value="">—</option>{tick_opts}</select></div>
            <div><label>Sales Ticket #</label><select name=sale_group class=w-sm><option value="">—</option>{sale_opts}</select></div>
            <div><label>Change Order #</label><select name=co_no class=w-sm><option value="">—</option>{co_opts}</select></div>
          </div>
          <p class="hint">Attach: one of Invoice / WO / Rental Ticket / Quote / Sales Ticket / Change Order</p>
          {cash_blocks_html}
          {_row}
          {_revpop}
        </form>
        {_lock}
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
        # Build 'ab' (redirect #2): totals read the chain heads — a
        # voided entry's money stands in its revision, not twice.
        total_in = sum(float(e["amount"]) for e in entries
                       if e["direction"] == "in"
                       and not e.get("revised_by_id"))
        total_out = sum(float(e["amount"]) for e in entries
                        if e["direction"] == "out"
                        and not e.get("revised_by_id"))
        def _cash_row(e):
            # The register's identifier is the entry's operator
            # number (entry_no, build 'ab'); pre-'ab' the raw
            # entry_id stood here. Live rows carry the Edit door to
            # the entry's own form; voided rows show the chain.
            _eno = e.get("entry_no") or str(e["entry_id"])
            _door = ""
            if not e.get("revised_by_id"):
                _door = (f"<br><a href='/money?tab=cash&edit="
                         f"{html.escape(_eno, quote=True)}'>Edit</a>")
            row = (
                f"<tr><td>{html.escape(_eno)}{_door}</td>"
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
            # Chain state (build 'ab', redirect #2): a voided entry
            # names its revision + the signed void; a revision names
            # the entry it revises.
            if e.get("revised_by_id") or e.get("revises_id"):
                _ci = engine.revision_info(con, "cash", e)
                if _ci["revised_by"]:
                    _seg = f"Void — revised by {_ci['revised_by']}"
                    if _ci["reason"]:
                        _seg += f": {_ci['reason']}"
                    if _ci["by"]:
                        _seg += f" ({_ci['by']})"
                    _segs.append(html.escape(_seg))
                elif _ci["revision_of"]:
                    _segs.append(html.escape(
                        f"Revision of {_ci['revision_of']}"))
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
        # Print (build 'aa', 2026-10-26, WS7 — Jason: "we need to
        # print everything that can be seen"): the register carries
        # the page print menu beside its heading, the universal
        # position for a list on a page. The Cash ENTRY form above
        # keeps its own button-row Print (the form grammar) — the
        # two print different things: the form prints the entry
        # being keyed, this menu prints the register page.
        _reg_print = self._print_menu(page=True)
        return f"""
        <h2 style="font-size:16px;color:var(--frame)">Cash entries <span style="float:right">{_reg_print}</span></h2>
        <table><tr><th>Entry #</th><th>Date</th><th>Method</th><th>Customer</th><th>Attached</th><th>Dir</th><th>Amount</th><th>Asset</th><th>Input by:</th></tr>
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
        def _arow(r):
            # Build 'ab' (redirect #2): the audit register carries
            # the entry number + the chain, same as the drawer.
            _run = (f"${r['running']:,.2f}"
                    if r["running"] is not None else "—")
            _state = ""
            if r.get("revised_by_id"):
                _head = con.execute(
                    "SELECT pc_id FROM petty_cash WHERE id=?",
                    (r["revised_by_id"],)).fetchone()
                _state = (" — Void, revised by "
                          + (_head[0] if _head else "")
                          + (f": {r['void_reason']}" if r["void_reason"] else "")
                          + (f" ({r['void_by']})" if r["void_by"] else ""))
            return (
                f"<tr><td>{html.escape(fmt_date(r['txn_date']))}</td>"
                f"<td>{html.escape(r['pc_id'])}</td>"
                f"<td>{html.escape(r['direction'])}</td>"
                f"<td>{html.escape(r['category'])}</td>"
                f"<td>{html.escape(r['payee'])}</td>"
                f"<td>${r['signed']:,.2f}</td><td>{_run}</td>"
                f"<td>{html.escape(r['ref_no'])}</td>"
                f"<td>{note_pop_html(r['notes'])}{html.escape(_state)}</td></tr>")
        rows = "".join(_arow(r) for r in book["rows"])
        return f"""
        <p class="hint"><input id="auditq" placeholder="Filter" size="30"
        oninput="document.querySelectorAll('table.audit').forEach(t=>auditFilter(t,this.value))">
        </p>
        <h2>Petty Cash Register</h2>
        <table class="audit"><tr><th>Date</th><th>No.</th><th>Dir</th><th>Category</th><th>Payee</th><th>Amount</th><th>Running</th><th>Ref</th><th>Notes</th></tr>
        {rows or '<tr><td colspan=9>Empty box.</td></tr>'}</table>
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
            qno = engine.peek_next_doc(con, "next_quote", engine.doc_prefix(con, "quote"), "quotes", "quote_no", floor=engine.doc_number_floor("quote"))
        q = pack["q"] if pack else {}
        # Void-and-revise (build 'ab'): an existing quote's form
        # opens LOCKED (the record) unless it is a fresh revision
        # under its session marker — then it is the revision's own
        # editor, its number an editable free-text field.
        q_mode = None
        if pack:
            q_mode = ("session" if engine.revision_pending(
                con, "quote", dict(q).get("id")) else "locked")
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
              <p><button>Save</button></p>
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
        # below this form. Build 'ag' (Jason 2026-10-28) took the
        # summary's Payment popup as well: a live quote's money is
        # worked on the Cash tab and the Credit Memoranda tab, and
        # its summary states the money block as a fact only. The
        # form keeps its own work only.
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
        # ride in the popup as read-only lines. (Build 'ac',
        # 2026-10-27: the status buttons and convert form that
        # builds 't'–'ab' carried in popups below this form are
        # removed — defect C-3; the work stands on the Quote
        # summary's doors.)
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
        # Build 'ac' (Jason 2026-10-27, defect C-3): the under-form
        # door row this block used to build (Status / Convert in a
        # .viewrow after </form>, with its own copies of the two
        # popups) is REMOVED — Status and Convert work stands on
        # the Quote summary's doors, where it already stands. The
        # status_form / convert forms above are no longer rendered
        # here; the summary builds its own.
        _q_doc = (f'Quote # <input name=quote_no value="{html.escape(qno)}" class=w-xs>'
                  if q_mode == "session" else
                  f'Quote # <input value="{html.escape(qno)}" disabled class=w-xs>'
                  if pack else
                  f'Quote # <input name=quote_no value="{html.escape(qno)}" class=w-xs>')
        _q_date = (f'<label>Date</label> <input type=date name=quote_date '
                   f'value="{html.escape(str(q.get("quote_date") or today)[:10])}" class=w-sm>')
        _q_cust = ('<div style="font-size:10px;color:#5C6B7A;'
                   'text-transform:uppercase">Billing Address</div>' + qcust_combo)
        return ("" if bare else tabs_quotes("/quotes")) + f"""
        <form method=post action="/quote/save" enctype="multipart/form-data">
          {f'<input type=hidden name=quote_no value="{html.escape(qno)}">' if pack and q_mode != "session" else ''}
          {f'<input type=hidden name=edit_target value="{html.escape(qno, quote=True)}">' if q_mode == "session" else ''}
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
          {self._btn_row(None, "qjobpop", add_item=False, edit_pop="revpop") if q_mode == "locked" else self._btn_row("Save", "qjobpop", add_item=True)}
          {self._job_info_popup('qjobpop', {"po": q.get("po") or "", "job_name": q.get("job_name") or "", "afe": q.get("afe") or "", "contact_name": q.get("contact_name") or ""}, _q_extra)}
          {self._revise_popup(con, "quote", qno) if q_mode == "locked" else ""}
        </form>
        {self._LOCK_JS if q_mode == "locked" else ""}
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
        doors: Edit (to the form), Status and Convert
        (the same popup forms the quote form carries), Print (the
        quote's three-choice print), View (the Quotes list).
        Build 'ag' (Jason 2026-10-28): no Payment door stands on
        this summary — money is worked on the Payment form.
        Build 'ai' (Jason 2026-10-28, reversing 'ag'/'ah' at his
        word): ONE small Payment button stands in the summary's
        bottom row — navigation to the payment form with this
        quote prefilled; no money is worked on the summary."""
        pack = engine.quote_pack(con, qno)
        if not pack:
            return tabs_quotes("/quotes") + "<p>Unknown quote.</p>"
        q = pack["q"]
        tot = pack["tot"]
        # Build 'ac' (Jason 2026-10-27): the shared summary lines
        # builder, the family vocabulary — the Note column stands
        # (quote_lines carries line_note); no lines renders the
        # shell, never a blank area.
        lines_html = self._sum_lines(
            [("Type", False), ("Item", False), ("Description", False),
             ("Qty", True), ("Unit", False), ("Rate", True),
             ("Amount", True), ("Note", False)],
            [[html.escape(ln.get('kind') or ''),
              html.escape(ln.get('item') or ''),
              html.escape(ln.get('description') or ''),
              f"{float(ln.get('qty') or 0):g}",
              html.escape(ln.get('uom') or ''),
              f"${float(ln.get('rate') or 0):,.2f}",
              f"${float(ln.get('amount') or 0):,.2f}",
              self._sum_note_cell("quote", qno, ln.get('line_id'),
                                  ln.get('line_note'))]
             for ln in pack["lines"]],
            empty_text="No lines.")
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
        # Build 'ac' (Jason 2026-10-27, state changes values, not
        # anatomy): Settled/Balance stand in the fact list at their
        # standing position on every quote — no state-conditional
        # insertion. (Build 'ag': the Payment door that once stood
        # beside these facts is off the summary; the Money fact
        # still states a closed or carried quote's block.)
        _set = engine.doc_settled(con, "quote", qno)
        # Build 'af': grouped fact blocks. Job Info markers follow
        # the quote's printed sheet (printpack.html_quote info
        # rows): Job and PO # print; AFE # and Contact Name do not.
        cust_pairs = [
            ("Customer", html.escape(q.get("account_name") or "")),
            ("Site", html.escape(site_name) if site_name else None),
        ]
        job_pairs = self._ji_pairs([
            ("Job Name", html.escape(q["job_name"]) if q.get("job_name") else None, True),
            ("PO #", html.escape(q["po"]) if q.get("po") else None, True),
            ("AFE #", html.escape(q["afe"]) if q.get("afe") else None, False),
            ("Contact Name", html.escape(q["contact_name"])
             if q.get("contact_name") else None, False),
        ])
        doc_pairs = [
            ("Date", html.escape(fmt_date(q.get("quote_date") or ""))),
            ("Status", html.escape(q.get("status") or "")),
            ("Valid Until", html.escape(fmt_date(q["valid_until"]))
             if q.get("valid_until") else None),
            ("Quoted", f"${tot['quoted']:,.2f}"),
            ("Face", f"${tot['face']:,.2f}"),
            ("Billed", f"${tot['billed']:,.2f}"),
            ("Variance", f"${tot['variance']:,.2f}"),
            ("Settled", f"${float(_set['total']):,.2f}"),
            ("Balance", f"${float(engine.doc_balance(con, 'quote', qno)):,.2f}"),
            ("Money", html.escape(_blk) + "." if _blk else None),
            ("Linked", " · ".join(linked) if linked else None),
            ("Notes", html.escape(q["notes"]) if q.get("notes") else None),
            ("Input by:", html.escape(q.get("clerk") or "")),
        ]
        doors = ""
        popups = ""
        # Build 'ag' (Jason 2026-10-28): the Payment door and its
        # money popup are OFF this summary — summaries state facts;
        # money work lives on the Payment form and the document's
        # own form. The Money fact above still states the block.
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
                f"<p><button>Save</button></p>"
                f"</form>")
            doors += self._pop_door("qconvpop", "Convert")
            popups += self._pop_wrap("qconvpop", "Convert", convert)
        doc_pairs += self._chain_facts(
            con, "quote", q,
            lambda n: f"/summary/quote/{html.escape(n, quote=True)}")
        doors = self._sum_doors(
            doors, None if (dict(q).get("revised_by_id")
                            or (q.get("status") or "") == "Void")
            else f"/quote/{qno}",
            self._print_menu(screen=f"/print/quote/{qno}",
                             pdf=f"/print/quote/{qno}.pdf"))
        # Build 'ac': no family tab strip on a summary — bare
        # under its title, like Rental/Sale.
        return self._sum_page(
            "Quote", qno, [], lines_html, doors, popups,
            "/quotes/all", "Quotes",
            extra_top=self._revto_line(con, "quote", q),
            fact_groups=[("Customer", cust_pairs),
                         ("Job Info", job_pairs),
                         ("Quote", doc_pairs)],
            paper_html=self._sum_paperwork("quote", qno),
            pay_doc=("quote", qno))

    def view_change_summary(self, con, co_no):
        """Summary of Change Order# (build 'u' pattern; build 'v',
        Jason 2026-10-25: the Change Order is a standalone money
        document — nothing requires anything). Its facts stated:
        customer, date, status, reason, PO, its optional associated
        document (a fact, linked — it changes no totals anywhere),
        its lines with directions, the add/subtract/net totals, its
        money (total / settled / balance), notes, record stamps.
        Doors: Edit (to the CO form — open only while nothing has settled
        against it), Print, View (the Change orders list).
        Build 'ag' (Jason 2026-10-28): no Payment door stands on
        this summary — money is worked on the Payment form.
        Build 'ai' (Jason 2026-10-28, reversing 'ag'/'ah' at his
        word): ONE small Payment button stands in the summary's
        bottom row — navigation to the payment form with this
        change order prefilled; no money is worked here."""
        co = con.execute("SELECT * FROM change_orders WHERE co_no=?",
                         (co_no,)).fetchone()
        if not co:
            return tabs_quotes("/changes") + "<p>Unknown change order.</p>"
        lines = con.execute(
            "SELECT * FROM change_order_lines WHERE co_id=? ORDER BY line_id",
            (co["id"],)).fetchall()
        # Build 'ac' (Jason 2026-10-27): the shared summary lines
        # builder — Direction keeps (kind-real data), the Note
        # column stands (change_order_lines carries line_note);
        # no lines renders the shell, never a blank area.
        lines_html = self._sum_lines(
            [("Type", False), ("Item", False), ("Description", False),
             ("Direction", False), ("Qty", True), ("Unit", False),
             ("Rate", True), ("Amount", True), ("Note", False)],
            [[html.escape(ln['kind'] or ''),
              html.escape(ln['item'] or ''),
              html.escape(ln['description'] or ''),
              html.escape(ln['direction'] or ''),
              f"{float(ln['qty'] or 0):g}",
              html.escape(ln['uom'] or ''),
              f"${float(ln['rate'] or 0):,.2f}",
              f"${float(ln['amount'] or 0):,.2f}",
              self._sum_note_cell("change", co_no, ln['line_id'],
                                  ln['line_note'])]
             for ln in lines],
            empty_text="No lines.")
        adds = sum(float(ln["amount"] or 0) for ln in lines
                   if ln["direction"] == "add")
        subs = sum(float(ln["amount"] or 0) for ln in lines
                   if ln["direction"] == "subtract")
        _cust = con.execute(
            "SELECT account_name, customer_id FROM customers WHERE id=?",
            (co["customer_id"],)).fetchone()
        _cust_name = _cust["account_name"] if _cust else ""
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
        cust_pairs = [
            ("Customer", html.escape(_cust_name) if _cust_name else None),
        ]
        # Job Info markers: the printed Change Order sheet
        # (printpack.html_change info rows) carries the PO #.
        job_pairs = self._ji_pairs([
            ("PO #", html.escape(self._g(co, "po")) if self._g(co, "po") else None, True),
        ])
        doc_pairs = [
            ("Date", html.escape(fmt_date(co["co_date"]))),
            ("Status", html.escape(co["status"] or "")),
            ("Reason", html.escape(co["reason"] or "")),
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
        doc_pairs += self._chain_facts(
            con, "change", co,
            lambda n: f"/summary/change/{html.escape(n, quote=True)}")
        doors = ""
        popups = ""
        _co_edit = None
        # Build 'ag' (Jason 2026-10-28): the Payment door and its
        # money popup are OFF this summary — summaries state facts;
        # money work lives on the Payment form and the document's
        # own form. Settled/Balance above still state the money.
        if not dict(co).get("revised_by_id") \
                and (co["status"] or "") != "Void":
            # Void-and-revise (build 'ab'): the Edit door stands for
            # every live Change Order — the form opens locked, and
            # settled money no longer bars the door: a revision's
            # chain carries the settlements to the head. (Build
            # 'aa' verified the route; the settled-refusal inside
            # the form is superseded by the locked render.)
            _co_edit = f"/ticket/new?kind=change&co_no={co_no}"
        doors = self._sum_doors(
            doors, _co_edit,
            self._print_menu(screen=f"/print/change/{co_no}",
                             pdf=f"/print/change/{co_no}.pdf"))
        # Build 'ac': no family tab strip on a summary — bare
        # under its title, like Rental/Sale.
        return self._sum_page(
            "Change Order", co_no, [], lines_html, doors, popups,
            "/changes/all", "Change orders — audit",
            extra_top=self._revto_line(con, "change", co),
            fact_groups=[("Customer", cust_pairs),
                         ("Job Info", job_pairs),
                         ("Change Order", doc_pairs)],
            paper_html=self._sum_paperwork("change", co_no),
            pay_doc=("change", co_no))

    def view_payment_summary(self, con, batch):
        """Summary of Payment# (build 'u', Jason 2026-10-25,
        universal summary pattern): one received payment — its
        batch (COALESCE(batch_id, pay_id), the identity the
        payments audit groups by) — stated as facts: date,
        customer, method, kind, ref, the amount, the documents it
        settled (links to their summaries), its line allocations,
        record stamps. Build 'ab' (JC-AA3 + the void-and-revise
        ruling, of which the payment correction model is the first
        instance): the Edit door opens the Payment form LOCKED;
        confirming its reason + name prompt voids this batch —
        signed into the record — and names its replacement
        '<batch> Rev. N'; the replacement's form posts the edited
        splits at Apply. The void, the reason, the name, and the
        link both ways stand as facts below. A blocked payment
        (payment_edit_block) carries no Edit door. Print is the
        page print menu."""
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
        _allocs = engine.list_payment_allocations(con, batch_id=batch)
        if not _allocs:
            _allocs = engine.list_payment_allocations(con, pay_id=batch)
        # Build 'af' (Jason 2026-10-28): the allocations area is a
        # real grid — one row per document the batch settled,
        # Document (linked to its summary), Kind, Applied — with
        # the allocation's line-detail segments and notes as a
        # sub-line under their document's row (the invoice
        # summary's payments-table shape, not a prose column). An
        # unapplied leftover states as its own row; the totals row
        # states the batch total.
        _segs_by_ref = {}
        for a in _allocs:
            _seg = (f"{html.escape(a['line_label'])} "
                    f"${float(a['amount']):,.2f}")
            if a["source"] == "credit" and a["cm_no"]:
                _seg += f" (credit {html.escape(a['cm_no'])})"
            if a["source"] == "cash":
                _seg += " (cash in)"
            if a["line_note"]:
                _seg += f" — {note_pop_html(a['line_note'])}"
            _segs_by_ref.setdefault(a["doc_ref"], []).append(_seg)
        _href_of = {"wo": "/summary/wo/", "ticket": "/ticket/",
                    "sale": "/sale/", "quote": "/summary/quote/",
                    "change": "/summary/change/"}
        _grid = []
        _applied_sum = 0.0
        _seen_docs = set()
        for r in inv_rows:
            if r["inv_no"] in _seen_docs:
                continue
            _seen_docs.add(r["inv_no"])
            _amt = sum(float(x["amount"] or 0) for x in inv_rows
                       if x["inv_no"] == r["inv_no"])
            _applied_sum += _amt
            _grid.append([
                f"Invoice <a href=\"/invoice/"
                f"{html.escape(r['inv_no'], quote=True)}\">"
                f"{html.escape(r['inv_no'])}</a>",
                "Invoice", f"${_amt:,.2f}"])
            for _seg in _segs_by_ref.get(r["inv_no"], []):
                _grid.append([_seg, "", ""])
            _segs_by_ref.pop(r["inv_no"], None)
        for r in doc_rows:
            _dref = engine.doc_num(con, r["doc_kind"], r["doc_id"]) or ""
            if (r["doc_kind"], _dref) in _seen_docs:
                continue
            _seen_docs.add((r["doc_kind"], _dref))
            _amt = sum(float(x["amount"] or 0) for x in doc_rows
                       if x["doc_kind"] == r["doc_kind"]
                       and (engine.doc_num(con, x["doc_kind"],
                                           x["doc_id"]) or "") == _dref)
            _applied_sum += _amt
            _lbl = engine.DOC_LABELS.get(r["doc_kind"], r["doc_kind"])
            _href = _href_of.get(r["doc_kind"], "/")
            _grid.append([
                f"{html.escape(_lbl)} <a href=\"{_href}"
                f"{html.escape(_dref, quote=True)}\">"
                f"{html.escape(_dref)}</a>",
                html.escape(_lbl), f"${_amt:,.2f}"])
            for _seg in _segs_by_ref.get(_dref, []):
                _grid.append([_seg, "", ""])
            _segs_by_ref.pop(_dref, None)
        for _ref_left, _segs_left in _segs_by_ref.items():
            for _seg in _segs_left:
                _grid.append(
                    [f"{html.escape(_ref_left)}: {_seg}", "", ""])
        _leftover = round(total - _applied_sum, 2)
        if _leftover > 0.005:
            _grid.append(["Unapplied", "", f"${_leftover:,.2f}"])
        if _grid:
            _grid.append(["Total", "", f"${total:,.2f}"])
        alloc_html = self._sum_lines(
            [("Document", False), ("Kind", False), ("Applied", True)],
            _grid, empty_text="No allocations.")
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
        # Correction facts (build 'ab'): a voided original names
        # its replacement; a correction names what it corrects —
        # inside the fact table, as facts.
        _voided = any(int(dict(r).get("voided") or 0) for r in rows)
        _replaced_by = next(
            (dict(r).get("void_replaced_by") for r in rows
             if dict(r).get("void_replaced_by")), None)
        _corrects = next(
            (dict(r).get("void_corrects") for r in rows
             if dict(r).get("void_corrects")), None)
        def _pay_link(b):
            return (f"<a href=\"/summary/payment/"
                    f"{html.escape(b, quote=True)}\">"
                    f"{html.escape(b)}</a>")
        _pinfo = engine.payment_batch_info(con, batch)
        cust_pairs = [
            ("Customer", html.escape(head["cust"] or "")),
        ]
        doc_pairs = [
            ("Date", html.escape(fmt_date(head["pay_date"]))),
            ("Method", html.escape(head["method"] or "")),
            ("Kind", html.escape(head["kind"] or "")),
            ("Ref", html.escape(", ".join(_refs)) if _refs else None),
            ("Amount", f"${total:,.2f}"),
            ("Status", "Void" if _voided else None),
            ("Replaced by", _pay_link(_replaced_by)
             if _replaced_by else None),
            ("Correction of", _pay_link(_corrects)
             if _corrects else None),
            ("Reason", html.escape(_pinfo["void_reason"])
             if _pinfo.get("void_reason") else None),
            ("By", html.escape(
                ((_pinfo.get("void_by") or "") + " · "
                 + (_pinfo.get("void_at") or "")).strip(" ·"))
             if _pinfo.get("void_by") else None),
            ("Notes", html.escape(" · ".join(_notes)) if _notes else None),
            ("Input by:", html.escape(
                ", ".join(sorted({r["clerk"] for r in rows if r["clerk"]})))) ,
        ]
        doors = self._sum_doors(
            "",
            None if engine.payment_edit_block(con, batch)
            else f"/money?tab=pay&edit={batch}",
            self._print_menu(page=True))
        # Build 'ac': no family tab strip on a summary — bare
        # under its title, like Rental/Sale.
        # Build 'af': the batch's Paperwork section files under the
        # batch's first pay row (the 'pay' attachment key the
        # payment form itself uses).
        _pay_ref = rows[0]["pay_id"] if rows else batch
        return self._sum_page(
            "Payment", batch, [], alloc_html, doors, "",
            "/money/payments/audit", "Payments — audit",
            fact_groups=[("Customer", cust_pairs),
                         ("Payment", doc_pairs)],
            paper_html=self._sum_paperwork(
                "pay", _pay_ref, ret=f"/summary/payment/{batch}"))

    def view_credit_summary(self, con, cm_no):
        """Summary of Credit Memo# (build 'u', Jason 2026-10-25,
        universal summary pattern): the memo's facts stated —
        customer, date, reason, face, applied / unapplied, the
        documents it settled (links to their summaries), notes,
        record stamps — with doors: Edit (to the Credit Memo form
        with THIS MEMO loaded — build 'aa', 2026-10-26, WS5: the
        form stands on the memo's customer with the memo selected
        in its Apply Leftover popup, open, where its application
        work lives; a posted memo's own fields never change), Print
        (the memo's three-choice print), View (the Credit memos
        list). Build 'aa' also gives the summary the memo's own
        lines table — it carried none."""
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
        cust_pairs = [
            ("Customer", html.escape(cm["account_name"])),
        ]
        doc_pairs = [
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
        doc_pairs += self._chain_facts(
            con, "credit", cm,
            lambda n: f"/summary/credit/{html.escape(n, quote=True)}")
        _cm_lines = con.execute(
            "SELECT * FROM credit_memo_lines WHERE cm_id = ? "
            "ORDER BY rowid", (cm["id"],)).fetchall()
        # Build 'ac' (Jason 2026-10-27): the shared summary lines
        # builder (its classes were this table's own). No Note
        # column — credit_memo_lines carries no line_note. No lines
        # renders the shell, never a blank area.
        lines_html = self._sum_lines(
            [("Type", False), ("Item", False), ("Description", False),
             ("Qty", True), ("Unit", False), ("Rate", True),
             ("Amount", True)],
            [[html.escape(ln['category'] or 'Line'),
              html.escape(ln['item'] or ''),
              html.escape(ln['description'] or ''),
              f"{float(ln['qty'] or 0):g}",
              html.escape(ln['uom'] or ''),
              f"${float(ln['rate'] or 0):,.2f}",
              f"${float(ln['amount'] or 0):,.2f}"]
             for ln in _cm_lines],
            empty_text="No lines.")
        doors = self._sum_doors(
            "", None if dict(cm).get("revised_by_id") else
            (f"/credit?customer_id={cm['cust_code']}"
             f"&cm_no={cm_no}"),
            self._print_menu(screen=f"/print/credit/{cm_no}",
                             pdf=f"/print/credit/{cm_no}.pdf"))
        # Build 'ac': no family tab strip on a summary — bare
        # under its title, like Rental/Sale.
        return self._sum_page(
            "Credit Memo", cm_no, [], lines_html, doors, "",
            "/money/credits/audit", "Credit memos audit",
            extra_top=self._revto_line(con, "credit", cm),
            fact_groups=[("Customer", cust_pairs),
                         ("Credit Memo", doc_pairs)],
            paper_html=self._sum_paperwork("credit", cm_no))


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
            # Void-and-revise (build 'ab', Jason 2026-10-26): the
            # settled-refusal page is superseded — an existing CO's
            # form opens LOCKED (its Edit door starts the revision
            # flow; settlements ride the chain to the head), or
            # unlocked as a fresh revision under its marker.
            co_mode = ("session" if engine.revision_pending(
                con, "change", co["id"]) else "locked")
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
            co_no = engine.peek_next_doc(con, "next_co", engine.doc_prefix(con, "change"),
                                         "change_orders", "co_no", floor=engine.doc_number_floor("change"))
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
        _co_doc = (f'CO # <a href="/summary/change/{html.escape(co_no, quote=True)}">{html.escape(co_no)}</a>'
                   if co is not None and co_mode == "locked" else
                   f'Change Order # <input name=co_no value="{html.escape(co_no, quote=True)}" class=w-xs>')
        _co_date = f'<label>Date</label> <input type=date name=co_date value="{_co_date_v}" class=w-sm>'
        _job_lines = [("Reason", _reason), ("PO #", _po),
                      ("Associated", _assoc_label)]
        return ("" if bare else tabs_quotes("/changes")) + f"""
        <form method=post action="/change/save" enctype="multipart/form-data">
          {f'<input type=hidden name=co_no value="{html.escape(co_no, quote=True)}">' if co is not None and co_mode == "locked" else ''}
          {f'<input type=hidden name=edit_target value="{html.escape(co_no, quote=True)}">' if co is not None and co_mode == "session" else ''}
          {self._form_head(con, _co_doc, _co_date, cust_combo, _job_lines)}
          {self._line_head()}
          {''.join(line_rows)}
          <div><label>Notes</label><input name=notes value="{html.escape((co['notes'] or '') if co else '', quote=True)}"></div>
          {self._btn_row(None, "cojobpop", add_item=False, edit_pop="revpop") if co is not None and co_mode == "locked" else self._btn_row("Save", "cojobpop", add_item=True)}
          {self._job_info_popup('cojobpop', _job_vals, _extra)}
          {self._revise_popup(con, "change", co_no) if co is not None and co_mode == "locked" else ""}
        </form>
        {self._LOCK_JS if co is not None and co_mode == "locked" else ""}
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
        _co_filter = ("WHERE co.revised_by_id IS NULL "
                      if engine.revision_cols_ready(con, "change_orders")
                      else "")
        for r in con.execute(
                f"""SELECT co.co_no, co.po, co.co_date, co.reason, co.status,
                          c.account_name
                   FROM change_orders co
                   LEFT JOIN customers c ON c.id = co.customer_id
                   {_co_filter}
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

    def _frag_pay_form(self, con, edit_batch=None, rev_batch=None,
                       prefill=None):
        # Build 'ab' (void-and-revise): edit_batch loads an existing
        # payment into this same form — its splits prefilled at
        # their pre-payment balances. The form opens LOCKED (the
        # record; Edit starts the revision). With rev_batch — the
        # replacement batch minted at the revise confirm, its
        # session marker standing — the form is the revision's own
        # editor: Apply posts the splits into the minted batch and
        # the original stands void, never rewritten. A blocked
        # payment refuses here with the reason and a pointer to its
        # summary (the revise gate states the same).
        edit_info = None
        pay_mode = None
        if edit_batch:
            # The session state is checked BEFORE the block gate:
            # a revision session loads the original batch — by then
            # voided and replaced, which is exactly the state the
            # gate reports — under the marker the confirm set.
            _session = bool(
                rev_batch and engine.get_option(
                    con, f"revtarget:payment:{rev_batch}") == edit_batch)
            if not _session:
                block = engine.payment_edit_block(con, edit_batch)
                if block:
                    return (f"<p class='hint'>{html.escape(block)} "
                            f"<a href='/summary/payment/"
                            f"{html.escape(edit_batch, quote=True)}'>"
                            f"Summary of Payment# "
                            f"{html.escape(edit_batch)}</a></p>")
            edit_info = engine.payment_batch_info(con, edit_batch)
            pay_mode = "session" if _session else "locked"
        # Prefill maps (edit mode only): what the original applied,
        # per document — the form renders the payment as it stood
        # when posted.
        e_inv_applied = {}
        e_co_applied = {}
        e_doc_applied = {}
        if edit_info is not None:
            for r in edit_info["crows"]:
                ino = engine.doc_num(con, "invoice", r["invoice_id"])
                if ino:
                    e_inv_applied[ino] = (e_inv_applied.get(ino, 0.0)
                                          + float(r["amount"] or 0))
            for r in edit_info["drows"]:
                ref = engine.doc_num(con, r["doc_kind"], r["doc_id"])
                if not ref:
                    continue
                if r["doc_kind"] == "change":
                    e_co_applied[ref] = (e_co_applied.get(ref, 0.0)
                                         + float(r["amount"] or 0))
                else:
                    key = (r["doc_kind"], ref)
                    e_doc_applied[key] = (e_doc_applied.get(key, 0.0)
                                          + float(r["amount"] or 0))
        # Build 'ai' prefill resolution (new payments only): the
        # summary button's target document — its customer, date,
        # and current balance, read once. An unknown reference
        # resolves to nothing and the blank form stands.
        _pf = None
        if prefill is not None and edit_info is None:
            _pk, _pr = prefill
            try:
                if _pk == "invoice":
                    _irow = con.execute(
                        "SELECT i.invoice_date, i.customer_id AS "
                        "cust_key, c.account_name FROM invoices i "
                        "JOIN customers c ON c.id = i.customer_id "
                        "WHERE i.invoice_no=?", (_pr,)).fetchone()
                    if _irow:
                        _pf = {
                            "kind": _pk, "ref": _pr,
                            "cust": engine.cust_code(
                                con, _irow["cust_key"]),
                            "name": _irow["account_name"],
                            "date": _irow["invoice_date"],
                            "bal": float(engine.invoice_totals(
                                con, _pr)["balance"])}
                elif _pk == "change":
                    _crow2 = con.execute(
                        "SELECT co.co_date, co.customer_id AS "
                        "cust_key, c.account_name FROM change_orders "
                        "co JOIN customers c ON c.id = co.customer_id "
                        "WHERE co.co_no=?", (_pr,)).fetchone()
                    if _crow2:
                        _pf = {
                            "kind": _pk, "ref": _pr,
                            "cust": engine.cust_code(
                                con, _crow2["cust_key"]),
                            "name": _crow2["account_name"],
                            "date": _crow2["co_date"],
                            "bal": float(engine.doc_balance(
                                con, "change", _pr))}
                else:
                    _pf_tables = {
                        "wo": ("work_orders", "wo_id", "open_date"),
                        "ticket": ("tickets", "ticket_id", "on_rent"),
                        "sale": ("sales", "sale_id", "sale_date"),
                        "quote": ("quotes", "quote_no", "quote_date")}
                    _tbl, _idc, _dc = _pf_tables[_pk]
                    _drow2 = con.execute(
                        f"SELECT {_dc} AS d, customer_id FROM {_tbl} "
                        f"WHERE {_idc}=?", (_pr,)).fetchone()
                    if _drow2:
                        _ccode = engine.cust_code(
                            con, _drow2["customer_id"])
                        _cname2 = con.execute(
                            "SELECT account_name FROM customers "
                            "WHERE customer_id=?", (_ccode,)).fetchone()
                        _pf = {
                            "kind": _pk, "ref": _pr,
                            "cust": _ccode,
                            "name": (_cname2["account_name"]
                                     if _cname2 else _ccode),
                            "date": _drow2["d"],
                            "bal": float(engine.doc_balance(
                                con, _pk, _pr))}
            except Exception:
                _pf = None
            if _pf is not None and not _pf["cust"]:
                # A document with no customer (an internal work
                # order) has no one to bill — its button still
                # lands here, on the blank form; the form governs.
                _pf = None
        open_inv = engine.list_open_invoices(con)
        if not open_inv and edit_info is None and _pf is None:
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
        _pf_inv_val = ""
        _pf_inv_hid = ""
        if _pf is not None and _pf["kind"] == "invoice":
            _pf_inv_val = (f"{_pf['ref']} · {_pf['name']} · bal "
                           f"${_pf['bal']:,.2f}")
            _pf_inv_hid = _pf["ref"]
        pay_inv_combo = (
            combo_field("f_pay_inv", "invoice_no_text", pay_inv_opts,
                        value=_pf_inv_val,
                        label="Invoice",
                        placeholder="Type to search invoices…")
            + f'<input type=hidden id="f_pay_inv_id" name=invoice_no '
              f'value="{html.escape(_pf_inv_hid, quote=True)}">'
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
        _cust_val = ""
        _cust_hid = ""
        _method_val = ""
        _method_hid = ""
        if edit_info is not None:
            _ec = edit_info["customer_id"]
            _erow = con.execute(
                "SELECT account_name FROM customers WHERE customer_id=?",
                (_ec,)).fetchone()
            _ename = _erow["account_name"] if _erow else _ec
            if _ec not in _seen_cust:
                cust_opts.append((_ec, f"{_ename} ({_ec})", _ec))
            _cust_val = f"{_ename} ({_ec})"
            _cust_hid = _ec
            _method_val = edit_info["method"] or ""
            _method_hid = _method_val
        elif _pf is not None:
            # Build 'ai': the prefill sets the form's customer, the
            # way an edit does — the splits filter then stands on
            # that customer and the target's row shows.
            _ec = _pf["cust"]
            if _ec not in _seen_cust:
                cust_opts.append((_ec, f"{_pf['name']} ({_ec})", _ec))
            _cust_val = f"{_pf['name']} ({_ec})"
            _cust_hid = _ec
        pay_cust_combo = (
            combo_field("f_pay_cust", "customer_id_text", cust_opts,
                        value=_cust_val,
                        label="Customer",
                        placeholder="Type to search customers…")
            + f'<input type=hidden id="f_pay_cust_id" name=customer_id '
              f'value="{html.escape(_cust_hid, quote=True)}">'
        )
        pay_method_opts = [(m, m, m) for m in engine.CASH_METHODS]
        pay_method_combo = (
            combo_field("f_pay_method", "method_text", pay_method_opts,
                        value=_method_val,
                        label="Method", placeholder="Type to search methods…")
            + f'<input type=hidden id="f_pay_method_id" name=method '
              f'value="{html.escape(_method_hid, quote=True)}">'
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
        # Edit mode: the batch's invoices stand in the row set at
        # their PRE-payment balances (today's balance plus what this
        # payment applied), even when the payment closed them and
        # they no longer count as open.
        inv_rows = []
        for r in open_inv:
            r = dict(r)
            if r["invoice_no"] in e_inv_applied:
                r["balance"] = (float(r["balance"])
                                + e_inv_applied[r["invoice_no"]])
            inv_rows.append(r)
        if edit_info is not None:
            _have = {r["invoice_no"] for r in inv_rows}
            for ino, amt in e_inv_applied.items():
                if ino in _have:
                    continue
                # Build 'aj' (Jason 2026-10-28, JC-AI3): the key
                # comes from the INVOICE's own customer_id — the
                # customers table's customer_id column is the
                # operator CODE, and feeding it to cust_code()
                # resolved None (non-numeric codes) or another
                # customer entirely (a code equal to some key).
                # Rule for this whole form: documents give keys;
                # codes come only from cust_code(key).
                r = con.execute(
                    "SELECT i.invoice_no, i.invoice_date, "
                    "i.customer_id AS cust_key, c.account_name "
                    "FROM invoices i JOIN customers c "
                    "ON c.id = i.customer_id WHERE i.invoice_no=?",
                    (ino,)).fetchone()
                if not r:
                    continue
                inv_rows.append({
                    "invoice_no": ino,
                    "invoice_date": r["invoice_date"],
                    "customer_id": engine.cust_code(con, r["cust_key"]),
                    "account_name": r["account_name"],
                    "balance": float(engine.invoice_totals(
                        con, ino)["balance"]) + amt})
        if _pf is not None and _pf["kind"] == "invoice" \
                and _pf["ref"] not in {r["invoice_no"] for r in inv_rows}:
            # Build 'ai': a prefilled invoice that is no longer
            # open (settled) stands in the row set at its balance,
            # the way an edited payment's closed invoices do.
            inv_rows.append({
                "invoice_no": _pf["ref"],
                "invoice_date": _pf["date"],
                "customer_id": _pf["cust"],
                "account_name": _pf["name"],
                "balance": _pf["bal"]})
        cust_map = json.dumps({r["invoice_no"]: r["customer_id"]
                               for r in inv_rows})
        cust_name_map = json.dumps({r["customer_id"]: r["account_name"]
                                    for r in inv_rows})
        # Build 'ak' (Jason 2026-10-28): the per-row "Lines" toggle
        # button and its line-breakdown block are removed package-
        # wide at his order — no buttons stand in line rows. The
        # form allocates per document (the Apply column); the engine
        # still honors line splits a post carries. Each split row
        # carries the template's red line-del ✕ (class co-line: the
        # global line-del machinery hides the first row's ✕, as on
        # every line grid).
        def _apply_row(r):
            ino = r["invoice_no"]
            _val = (f" value='{e_inv_applied[ino]:.2f}'"
                    if ino in e_inv_applied else "")
            return (
                f"<tr class=co-line data-cust='{html.escape(r['customer_id'])}' style='display:none'>"
                f"<td><input type=checkbox class=pay-full data-bal='{r['balance']:.2f}' title='Pay this invoice in full'></td>"
                f"<td>{html.escape(ino)}</td>"
                f"<td>{html.escape(r['account_name'])}</td>"
                f"<td>{html.escape(fmt_date(r['invoice_date']))}</td>"
                f"<td>${r['balance']:,.2f}</td>"
                f"<td><input name=p__{html.escape(ino)} class=pay-split type=number step=0.01 min=0 "
                f"max='{r['balance']:.2f}' placeholder='0.00'{_val}>"
                f"<button type=button class=line-del title=\"Delete line item\">✕</button></td></tr>")

        apply_rows = "".join(_apply_row(r) for r in inv_rows)
        # Split payment across an invoice and its Change Order
        # (build 'v', Jason 2026-10-25, the amended-PO exception):
        # an open Change Order of the same customer rides the same
        # splits table as its own Apply row — one payment event, one
        # batch, per-document allocations recorded separately (the
        # documents never merge). The CO row posts pco__<co_no>.
        _co_rows = []
        _co_data = []
        _co_seen = set()
        try:
            for r in con.execute(
                    """SELECT co.co_no, co.co_date, co.customer_id AS cust_key,
                              c.account_name
                       FROM change_orders co
                       JOIN customers c ON c.id = co.customer_id
                       WHERE co.status = 'Issued'
                       ORDER BY co.co_date, co.co_no"""):
                _bal = float(engine.doc_balance(con, "change", r["co_no"]))
                _ap = e_co_applied.get(r["co_no"])
                if _ap is not None:
                    _bal += _ap
                if _bal <= 0.009:
                    continue
                _co_seen.add(r["co_no"])
                # Build 'aj': the CO's own key, converted — the
                # same discipline as the invoice append above.
                _ccode = engine.cust_code(con, r["cust_key"])
                _co_data.append({"co_no": r["co_no"],
                                 "cust": _ccode,
                                 "name": r["account_name"],
                                 "bal": _bal})
                _val = f" value='{_ap:.2f}'" if _ap is not None else ""
                _co_rows.append(
                    f"<tr class=co-line data-cust='{html.escape(_ccode)}' style='display:none'>"
                    f"<td><input type=checkbox class=pay-full data-bal='{_bal:.2f}' title='Pay this change order in full'></td>"
                    f"<td>Change Order {html.escape(r['co_no'])}</td>"
                    f"<td>{html.escape(r['account_name'])}</td>"
                    f"<td>{html.escape(fmt_date(r['co_date']))}</td>"
                    f"<td>${_bal:,.2f}</td>"
                    f"<td><input name=pco__{html.escape(r['co_no'], quote=True)} class=pay-split type=number step=0.01 min=0 "
                    f"max='{_bal:.2f}' placeholder='0.00'{_val}>"
                    f"<button type=button class=line-del title=\"Delete line item\">✕</button></td></tr>")
            if edit_info is not None:
                # Change Orders this payment closed stand at their
                # pre-payment balance too.
                for _cno, _ap in e_co_applied.items():
                    if _cno in _co_seen:
                        continue
                    r = con.execute(
                        "SELECT co.co_date, co.customer_id AS cust_key, "
                        "c.account_name FROM change_orders co "
                        "JOIN customers c ON c.id = co.customer_id "
                        "WHERE co.co_no=?", (_cno,)).fetchone()
                    if not r:
                        continue
                    _bal = float(engine.doc_balance(
                        con, "change", _cno)) + _ap
                    # Build 'aj': the CO's own key, converted —
                    # the same discipline as the invoice append.
                    _ccode = engine.cust_code(con, r["cust_key"])
                    _co_data.append({"co_no": _cno,
                                     "cust": _ccode,
                                     "name": r["account_name"],
                                     "bal": _bal})
                    _co_rows.append(
                        f"<tr class=co-line data-cust='{html.escape(_ccode)}' style='display:none'>"
                        f"<td><input type=checkbox class=pay-full data-bal='{_bal:.2f}' title='Pay this change order in full'></td>"
                        f"<td>Change Order {html.escape(_cno)}</td>"
                        f"<td>{html.escape(r['account_name'])}</td>"
                        f"<td>{html.escape(fmt_date(r['co_date']))}</td>"
                        f"<td>${_bal:,.2f}</td>"
                        f"<td><input name=pco__{html.escape(_cno, quote=True)} class=pay-split type=number step=0.01 min=0 "
                        f"max='{_bal:.2f}' placeholder='0.00' value='{_ap:.2f}'>"
                        f"<button type=button class=line-del title=\"Delete line item\">✕</button></td></tr>")
        except Exception:
            _co_rows = []
        if _pf is not None and _pf["kind"] == "change" \
                and _pf["ref"] not in _co_seen:
            # Build 'ai': a prefilled change order that is no
            # longer open stands in the row set at its balance.
            _co_data.append({"co_no": _pf["ref"], "cust": _pf["cust"],
                             "name": _pf["name"], "bal": _pf["bal"]})
            _co_rows.append(
                f"<tr class=co-line data-cust='{html.escape(_pf['cust'])}' style='display:none'>"
                f"<td><input type=checkbox class=pay-full data-bal='{_pf['bal']:.2f}' title='Pay this change order in full'></td>"
                f"<td>Change Order {html.escape(_pf['ref'])}</td>"
                f"<td>{html.escape(_pf['name'])}</td>"
                f"<td>{html.escape(fmt_date(_pf['date']))}</td>"
                f"<td>${_pf['bal']:,.2f}</td>"
                f"<td><input name=pco__{html.escape(_pf['ref'], quote=True)} class=pay-split type=number step=0.01 min=0 "
                f"max='{_pf['bal']:.2f}' placeholder='0.00'>"
                f"<button type=button class=line-del title=\"Delete line item\">✕</button></td></tr>")
        apply_rows += "".join(_co_rows)
        # Edit mode only: the payment's document splits (work order,
        # rental, sale, quote) ride the same table in the Change
        # Order row's shape, posting pd__<kind>__<ref> — parsed by
        # the correction save through the credit side's own
        # doc-split reader. Balances are pre-payment, as above.
        if edit_info is not None:
            _doc_dates = {"wo": ("work_orders", "wo_id", "open_date"),
                          "ticket": ("tickets", "ticket_id", "on_rent"),
                          "sale": ("sales", "sale_id", "sale_date"),
                          "quote": ("quotes", "quote_no", "quote_date")}
            _doc_rows = []
            _cust = edit_info["customer_id"]
            _cname_row = con.execute(
                "SELECT account_name FROM customers WHERE customer_id=?",
                (_cust,)).fetchone()
            _cname = _cname_row["account_name"] if _cname_row else _cust
            for (kind, ref), amt in sorted(e_doc_applied.items()):
                _tbl, _idc, _dc = _doc_dates[kind]
                _drow = con.execute(
                    f"SELECT {_dc} AS d FROM {_tbl} WHERE {_idc}=?",
                    (ref,)).fetchone()
                _bal = float(engine.doc_balance(con, kind, ref)) + amt
                _lab = f"{engine.DOC_LABELS[kind]} {ref}"
                _qref = html.escape(ref, quote=True)
                _doc_rows.append(
                    f"<tr class=co-line data-cust='{html.escape(_cust)}' style='display:none'>"
                    f"<td><input type=checkbox class=pay-full data-bal='{_bal:.2f}' title='Pay in full'></td>"
                    f"<td>{html.escape(_lab)}</td>"
                    f"<td>{html.escape(_cname)}</td>"
                    f"<td>{html.escape(fmt_date(_drow['d'] if _drow else ''))}</td>"
                    f"<td>${_bal:,.2f}</td>"
                    f"<td><input name=pd__{kind}__{_qref} class=pay-split type=number step=0.01 min=0 "
                    f"max='{_bal:.2f}' placeholder='0.00' value='{amt:.2f}'>"
                    f"<button type=button class=line-del title=\"Delete line item\">✕</button></td></tr>")
            apply_rows += "".join(_doc_rows)
        if _pf is not None and _pf["kind"] in (
                "wo", "ticket", "sale", "quote"):
            # Build 'ai': the prefilled document's own split row —
            # the same row shape an edited payment's document
            # splits stand in (pd__<kind>__<ref>, Lines where the
            # document carries line states). The form's filter
            # stands on the document's customer (set above), so
            # the row shows with the customer's other rows.
            _kind = _pf["kind"]
            _ref = _pf["ref"]
            _qref = html.escape(_ref, quote=True)
            _prow = (
                f"<tr class=co-line data-cust='{html.escape(_pf['cust'])}' style='display:none'>"
                f"<td><input type=checkbox class=pay-full data-bal='{_pf['bal']:.2f}' title='Pay in full'></td>"
                f"<td>{html.escape(engine.DOC_LABELS[_kind])} {html.escape(_ref)}</td>"
                f"<td>{html.escape(_pf['name'])}</td>"
                f"<td>{html.escape(fmt_date(_pf['date']))}</td>"
                f"<td>${_pf['bal']:,.2f}</td>"
                f"<td><input name=pd__{_kind}__{_qref} class=pay-split type=number step=0.01 min=0 "
                f"max='{_pf['bal']:.2f}' placeholder='0.00'>"
                f"<button type=button class=line-del title=\"Delete line item\">✕</button></td></tr>")
            apply_rows += _prow
        # Header zone (build 'r', Jason 2026-10-25, facelift item 4):
        # Company block, the Customer picker (it is this form's
        # customer reference — a filter for the splits below,
        # unchanged), RP # + Date, bar, then the form's work.
        # The payment form has no line-item grid; its fields and the
        # splits table are the document's work, not above-the-lines
        # fields. Build 'ao' (Jason 2026-10-29): the head stacks
        # like every other money form's — the Customer picker stands
        # on its own row BELOW the Company block, not to its right
        # (stacked=True; the form carries no Job Info box).
        if edit_info is not None:
            if pay_mode == "session":
                _pay_doc = (f'Payment # <input name=pay_no '
                            f'value="{html.escape(rev_batch, quote=True)}" '
                            f'class=w-xs>')
                _pay_hiddens = (
                    f'<input type=hidden name=revising value=1>'
                    f'<input type=hidden name=target_batch '
                    f'value="{html.escape(rev_batch, quote=True)}">')
            else:
                _pay_doc = (f'Payment # <input '
                            f'value="{html.escape(edit_batch, quote=True)}" '
                            f'disabled class=w-xs>')
                _pay_hiddens = (
                    f'<input type=hidden name=editing value=1>'
                    f'<input type=hidden name=orig_batch '
                    f'value="{html.escape(edit_batch, quote=True)}">')
            _pay_date_val = edit_info["pay_date"] or today
            _pay_ref = edit_info["ref_no"] or ""
            _pay_notes = edit_info["notes"] or ""
        else:
            _pay_doc = f'Payment # <input value="{rp_no}" disabled class=w-xs>'
            _pay_hiddens = f'<input type=hidden name=rp_no value="{rp_no}">'
            _pay_date_val = today
            _pay_ref = ""
            _pay_notes = ""
        _pay_date = f'<label>Date</label> <input type=date name=pay_date value="{_pay_date_val}" required class=w-sm>'
        # Add Item (build 'af', Jason 2026-10-28): the picker's
        # documents — the same open documents the splits table
        # lists (open invoices + open Change Orders), as data for
        # the form's addItemRow script.
        _add_docs = []
        for r in inv_rows:
            _add_docs.append({
                "v": f"invoice:{r['invoice_no']}",
                "cust": r["customer_id"],
                "label": (f"Invoice {r['invoice_no']} · "
                          f"{r['account_name']} · bal "
                          f"${float(r['balance']):,.2f}")})
        for _cd in _co_data:
            _add_docs.append({
                "v": f"change:{_cd['co_no']}",
                "cust": _cd["cust"],
                "label": (f"Change Order {_cd['co_no']} · "
                          f"{_cd['name']} · bal ${_cd['bal']:,.2f}")})
        pay_add_docs = json.dumps(_add_docs)
        return f"""
        <form method=post action="/pay" enctype="multipart/form-data">
          {_pay_hiddens}
          {self._form_head(con, _pay_doc, _pay_date, pay_cust_combo, stacked=True)}
          <!-- One apply (build 'aa', Jason 2026-10-26, WS6 / JC-AA2):
               the form's single commit is Save (labeled "Apply
               payment" until build 'ad', Jason 2026-10-27 — the
               commit is named for the act only), and the
               scope toggle says what it applies: the amounts as
               entered (the default), or every shown split filled
               to its full balance in the same action. The
               standalone "Pay all shown in full" button is
               deleted — two controls doing one thing is drift; one
               button, toggle what you want to apply to. Build 'ab'
               (form-row ruling, same day): the commit rides the
               universal split row's RIGHT cluster with Print — the
               top-commit bar is retired. Build 'ac' (Jason
               2026-10-27): the toggle moves OUT of the button
               cluster into the form body directly above the row —
               the cluster is Print, then the one commit, last;
               the toggle is form content, one control set,
               unchanged names/values/behavior. -->
          <div class="row">
            <div>{pay_inv_combo}</div>
            <div><label>Total payment</label><b id="pay-total-display">$0.00</b><input type=hidden name=amount id="pay-total" value="0"></div>
          </div>
          <p class="hint">One payment, multiple invoices.</p>
          <table id="pay-splits"><tr><th></th><th>Invoice</th><th>Customer</th><th>Date</th><th>Balance</th><th>Apply $</th></tr>
          <tr id="pay-hint"><td colspan=6 class="hint">No customer selected.</td></tr>
          {apply_rows}</table>
          <div class="row4">
            <div><label>Payment Reference</label><input name=ref class=w-sm value="{html.escape(_pay_ref, quote=True)}"></div>
            <div>{pay_method_combo}</div>
            <div><label>Upload(s)</label><input type=file name=pay_upload></div>
          </div>
          <div><label>Notes</label><input name=notes style="width:100%" value="{html.escape(_pay_notes, quote=True)}"></div>
          {"" if pay_mode == "locked" else '<div style="display:flex;justify-content:flex-end;gap:16px;margin:0 0 4px"><label style="display:inline-flex;align-items:center;gap:6px;white-space:nowrap"><input type=radio name=pay_scope value="entered" checked> Amounts as entered</label><label style="display:inline-flex;align-items:center;gap:6px;white-space:nowrap"><input type=radio name=pay_scope value="full"> All shown in full</label></div>'}
          {self._btn_row(None, "payjobpop", add_item=False, edit_pop="revpop") if pay_mode == "locked" else self._btn_row("Save", "payjobpop", add_item=True)}
          {self._job_info_popup('payjobpop')}
          {self._revise_popup(con, "payment", edit_batch) if pay_mode == "locked" else ""}
        </form>
        {self._LOCK_JS if pay_mode == "locked" else ""}
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
              // Add Item rows (build 'af'): a row whose document
              // is not picked yet stands open so the pick can be
              // made; once picked it follows the customer filter.
              if (tr.classList.contains('pay-add-row')) show = !tr.dataset.cust || (cust && tr.dataset.cust === cust);
              tr.style.display = show ? '' : 'none';
            }});
            if (hint) hint.style.display = cust ? 'none' : '';
          }}
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
          // Scope toggle (build 'aa'): "All shown in full" fills
          // every shown split to its full balance as part of the
          // Apply itself — one action, one button.
          form.addEventListener('submit', function(){{
            var sc = form.querySelector('input[name=pay_scope]:checked');
            if (sc && sc.value === 'full') {{
              form.querySelectorAll('#pay-splits tr[data-cust]').forEach(function(tr){{
                if (tr.style.display === 'none') return;
                var cb = tr.querySelector('.pay-full');
                var amt = tr.querySelector('.pay-split');
                if (cb) cb.checked = true;
                if (amt && cb) amt.value = cb.dataset.bal;
              }});
              sum();
            }}
          }});
          form.querySelectorAll('.pay-split').forEach(function(el){{
            el.addEventListener('input', function(){{ sum(); }});
          }});
          // Build 'ak': the template's line-del ✕ removes a split
          // row through the global handler, which fires an input
          // event on the row's container — re-sum on it so the
          // form's total follows the rows that stand.
          var splitsTbl = document.getElementById('pay-splits');
          if (splitsTbl) splitsTbl.addEventListener('input', function(){{ sum(); }});
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
          // Add Item (build 'af', Jason 2026-10-28): adds an
          // allocation row — a document picker over the same open
          // documents the splits table lists, plus an amount. The
          // row commits nothing; the batch's Save posts it
          // (adddoc__N / addamt__N, merged by the post, which
          // refuses a document that already holds a row).
          var ADD_DOCS = {pay_add_docs};
          var addN = 0;
          function addItemRow(){{
            addN += 1;
            var n = addN;
            var tbl = document.getElementById('pay-splits');
            var tr = document.createElement('tr');
            tr.className = 'pay-add-row';
            tr.setAttribute('data-cust', '');
            var td0 = document.createElement('td');
            var del = document.createElement('button');
            del.type = 'button'; del.className = 'line-del';
            del.title = 'Remove row'; del.textContent = '✕';
            del.addEventListener('click', function(){{ tr.remove(); sum(); }});
            td0.appendChild(del);
            var td1 = document.createElement('td');
            td1.colSpan = 4;
            var sel = document.createElement('select');
            sel.name = 'adddoc__' + n;
            var o0 = document.createElement('option');
            o0.value = ''; o0.textContent = 'Pick a document';
            sel.appendChild(o0);
            ADD_DOCS.forEach(function(d){{
              var o = document.createElement('option');
              o.value = d.v; o.textContent = d.label;
              o.setAttribute('data-cust', d.cust);
              sel.appendChild(o);
            }});
            sel.addEventListener('change', function(){{
              var o = sel.options[sel.selectedIndex];
              tr.setAttribute('data-cust', o ? (o.getAttribute('data-cust') || '') : '');
              filter();
            }});
            td1.appendChild(sel);
            var td2 = document.createElement('td');
            var amt = document.createElement('input');
            amt.name = 'addamt__' + n;
            amt.className = 'pay-split';
            amt.type = 'number'; amt.step = '0.01'; amt.min = '0';
            amt.placeholder = '0.00';
            amt.addEventListener('input', sum);
            td2.appendChild(amt);
            tr.appendChild(td0); tr.appendChild(td1); tr.appendChild(td2);
            (tbl.querySelector('tbody') || tbl).appendChild(tr);
            filter();
          }}
          form.querySelectorAll('button[type=button]').forEach(function(b){{
            if (b.textContent.trim().toLowerCase() === 'add item') b.addEventListener('click', addItemRow);
          }});
          filter(); sum();
        }})();
        </script>
        """

    def _frag_credit_form(self, con, q):
        q = q or {}
        cid = q.get("customer_id") or ""
        # Build 'aa' (2026-10-26, WS5): cm_no loads a SPECIFIC memo —
        # the Credit Memo summary's Edit door lands here with the
        # memo's customer AND its number; the memo stands selected in
        # the Apply Leftover popup, which renders open. A memo with
        # no unapplied credit left is not in the open list; the form
        # then stands on the customer, as before.
        load_cm = (q.get("cm_no") or "").strip()
        # Void-and-revise (build 'ab', JC-AB17): the credit form is
        # a working form, not the memo's document form. Build 'ac'
        # (Jason 2026-10-27, defect C-1 — supersedes JC-AB17's
        # no-lock arrangement): with a live memo loaded, the form
        # takes the same locked/session split as the other seven
        # kinds — it opens LOCKED, the row carries Edit alone, and
        # no Save stands beside it; the working form (no memo
        # loaded) keeps Save + Add Item. Confirming the revision
        # voids the memo and clones it (credit's revision completes
        # at the confirm act in the engine), and the form then
        # stands on the clone — again locked, Edit alone. A
        # revised-away memo carries no Edit.
        _cm_live = None
        if load_cm:
            _cm_live = con.execute(
                "SELECT * FROM credit_memos WHERE cm_no=?",
                (load_cm,)).fetchone()
            if _cm_live is not None and dict(_cm_live).get(
                    "revised_by_id"):
                _cm_live = None
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
            # A settled invoice takes no positive credit, but a
            # NEGATIVE credit re-opens settled amount (Jason
            # 2026-10-23) — it stays listed, capped at what it has
            # settled.
            # Build 'ak' (Jason 2026-10-28): the row's "Lines" toggle
            # and its line-breakdown block are removed, as on the
            # payment form — the form applies per document.
            _settled = r['balance'] <= 0.005
            _cap = r['paid'] if _settled else r['balance']
            # Build 'al' (Jason 2026-10-28): the invoice rows take
            # the unified application grid's shape (Document / Date
            # / Total / Settled / Balance / Apply — Settled carries
            # cash + credit together, as the document rows state
            # it) and the template's red line-del X, classed
            # co-line like the payment form's split rows.
            return (
                f"<tr class=co-line><td>Invoice {html.escape(ino)}"
                f"{' · settled' if _settled else ''}</td>"
                f"<td>{html.escape(fmt_date(r['invoice_date']))}</td>"
                f"<td>${r['total']:,.2f}</td>"
                f"<td>${r['cash'] + r['credit']:,.2f}</td>"
                f"<td>${r['balance']:,.2f}</td>"
                f"<td><input name=a__{html.escape(ino)} type=number step=0.01 min=0 "
                f"max='{_cap:.2f}' placeholder='0.00'>"
                f"<button type=button class=line-del title=\"Delete line item\">✕</button></td></tr>")

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
                # follows the direction that fits.
                if _bal > 0.005:
                    _cap, _ckey = _bal, "remaining"
                elif _set > 0.005:
                    _cap, _ckey = _set, "allocated"
                else:
                    continue
                _q = html.escape(_ref, quote=True)
                _main = (
                    f"<tr class=co-line><td>{engine.DOC_LABELS[_kind]} {_q}"
                    f"{' · settled' if _ckey == 'allocated' else ''}</td>"
                    f"<td>{html.escape(fmt_date(_dt or ''))}</td>"
                    f"<td>${_tot:,.2f}</td><td>${_set:,.2f}</td>"
                    f"<td>${_bal:,.2f}</td>"
                    f"<td><input name=cd__{_kind}__{_q} type=number "
                    f"step=0.01 min=0 max='{_cap:.2f}' "
                    f"placeholder='0.00'>"
                    f"<button type=button class=line-del title=\"Delete line item\">✕</button></td></tr>")
                doc_rows.append(_main)
        # Build 'al' (Jason 2026-10-28): the two application
        # tables (invoices here, "Documents" below) are ONE grid —
        # the payment form's shape: one table of document rows,
        # each carrying the template's red X (class co-line, the
        # 'ak' payment-split pattern), the a__ / cd__ input names
        # unchanged so both posts read it as before. One builder
        # serves the form and the Apply Leftover popup (its own
        # form, its own grid id).
        def _apply_grid(gid):
            _rows = apply_rows + "".join(doc_rows)
            return (
                f"""<table id="{gid}"><tr><th>Document</th><th>Date</th><th>Total</th><th>Settled</th><th>Balance</th><th>Apply</th></tr>
                {_rows or '<tr><td colspan=6>No open documents.</td></tr>'}</table>"""
                if cid else "")
        leftovers = engine.list_open_credits(con, cid or None)
        cm_opts = []
        _cm_val = ""
        _cm_hid = ""
        for r in leftovers:
            v = str(r["cm_no"])
            d = (f"{v} · {r['customer_id']} · unapplied "
                 f"${float(r['unapplied']):,.2f}"
                 f"{' (negative)' if float(r['unapplied']) < 0 else ''}")
            cm_opts.append((v, d, v))
            if load_cm and v == load_cm:
                _cm_val, _cm_hid = d, v
        cm_combo = (
            combo_field("f_cm_no", "cm_no_text", cm_opts, value=_cm_val,
                        label="Open credit memo", required=True,
                        placeholder="Type to search credit memos…")
            + f'<input type=hidden id="f_cm_no_id" name=cm_no '
              f'value="{html.escape(_cm_hid, quote=True)}">'
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
        # Build 'al': the "Apply Now (Optional)" section and its
        # second table are gone; the one grid stands in the form
        # below the memo's lines (see the form assembly) and in
        # the leftover popup.
        apply_block = _apply_grid("cm-apply")
        apply_block_pop = _apply_grid("cm-apply-pop")
        leftover_popup = (
            f"""<div class="viewrow"><button type="button" class="vbtn" onclick="document.getElementById('cmleftpop').style.display='block'">Apply Leftover</button></div>
            <div id="cmleftpop" class="wpop" style="display:{'block' if _cm_hid else 'none'};position:fixed;top:8%;left:8%;right:8%;background:white;border:2px solid #333;padding:18px;z-index:1000;max-height:84%;overflow:auto">
            <h3 class="wpop-h" style="margin-top:0">Apply Leftover {self._pop_furniture("cmleftpop")}</h3>
            <p class="hint">Same customer only. A credit cannot exceed each balance; a negative credit cannot exceed what each document has settled.</p>
            <form method=post action="/credit/apply">
              {cm_combo}
              <label>Date</label><input type=date name=pay_date class=w-sm value="{today}">
              {apply_block_pop}
              <p><button>Save</button></p>
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
        cm_no = engine.peek_next_doc(con, "next_cm", engine.doc_prefix(con, "cm"), "credit_memos", "cm_no", floor=engine.doc_number_floor("cm"))
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
        # memo's totals) and Notes remain. Build 'al' (Jason
        # 2026-10-28) settles the carried flag: nothing stands
        # above the line rows but the header zone — the line pulls
        # stand directly below the grid they feed, and the one
        # application grid stands below Notes, above the row.
        _cm_extra = (f'<div class="row"><div><label>Invoice Ref</label>'
                     f'<select name=invoice_no id=cm_inv onchange="var d=this.options[this.selectedIndex].getAttribute(\'data-date\');if(d){{document.getElementById(\'cm_inv_date\').value=d}}if(this.value){{var hc=document.getElementById(\'f_cred_cust_id\');location=\'/money?tab=credit&invoice_no=\'+encodeURIComponent(this.value)+(hc&&hc.value?\'&customer_id=\'+encodeURIComponent(hc.value):\'\')}}">'
                     f'<option value="">— Pick or Type —</option>{inv_opts}</select></div></div>'
                     f'<div class="row"><div><label>Inv Date</label><input type=date name=inv_date id=cm_inv_date class=w-sm></div>'
                     f'<div><label>Reason</label><input name=reason maxlength=2000 placeholder="Billed twice / wrong dates / courtesy"></div></div>'
                     f'<div><label>Upload</label><input type=file name=cm_upload></div>')
        _cm_doc = f'Credit Memo # <input name=cm_no value="{cm_no}" class=w-xs>'
        _cm_date = f'<label>Date</label> <input type=date name=cm_date value="{today}" required class=w-sm>'
        return f"""
        <form method=post action="/credit" enctype="multipart/form-data">
          {self._form_head(con, _cm_doc, _cm_date, issue_cust_combo, [("Invoice Ref", picked_inv)])}
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
          {pull_block}
          <div style="display:flex;flex-wrap:wrap;gap:24px;align-items:flex-start;margin-top:8px">
            <div style="text-align:right;margin-left:auto">
              <div>Credit Total <b id="cm-total">$0.00</b></div>
            </div>
          </div>
          <div><label>Notes</label><input name=notes style="width:100%"></div>
          {apply_block}
          {self._btn_row(None, "cmjobpop", add_item=False, edit_pop="revpop") if _cm_live is not None else self._btn_row("Save", "cmjobpop", add_item=True)}
          {self._job_info_popup('cmjobpop', None, _cm_extra)}
          {self._revise_popup(con, "credit", load_cm) if _cm_live is not None else ""}
        </form>
        {self._LOCK_JS if _cm_live is not None else ""}
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
        {leftover_popup}
        """ + _item_extras(con)

    def _frag_petty_form(self, con, frag=False, edit_no=None):
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
        if edit_no:
            # Build 'ab' (redirect #2): a loaded petty entry renders
            # as one revision card — LOCKED like every posted record,
            # Edit starts its revision, the session Save completes
            # the shell in the same log (complete_petty_revision).
            erow = con.execute(
                "SELECT * FROM petty_cash WHERE pc_id=?",
                (edit_no,)).fetchone()
            if erow is None:
                return (f"<p class='card'>Petty cash entry "
                        f"{html.escape(edit_no)} is not on record.</p>")
            erow = dict(erow)
            if erow.get("revised_by_id"):
                _head = con.execute(
                    "SELECT pc_id FROM petty_cash WHERE id=?",
                    (erow["revised_by_id"],)).fetchone()
                _hn = _head[0] if _head else ""
                return (
                    f"<p class='card'>Petty cash entry "
                    f"{html.escape(edit_no)} was voided — revised as "
                    f"<a href='/petty?edit={html.escape(_hn, quote=True)}'>"
                    f"{html.escape(_hn)}</a>, the live entry at the "
                    f"head of its chain.</p>")
            emode = ("session" if engine.revision_pending(
                con, "petty", erow["id"]) else "locked")
            _cats = "".join(
                f"<optgroup label='{lbl}'>" + "".join(
                    f"<option{' selected' if c == erow['category'] else ''}>"
                    f"{html.escape(c)}</option>" for c in cats)
                + "</optgroup>"
                for lbl, cats in (("In", engine.PC_IN_CATS),
                                  ("Out", engine.PC_OUT_CATS)))
            _din = " selected" if erow["direction"] == "in" else ""
            _dout = " selected" if erow["direction"] == "out" else ""
            _erow_btn = (self._btn_row(None, edit_pop="revpop",
                                       print_menu=_pmenu)
                         if emode == "locked" else
                         self._btn_row("Save", print_menu=_pmenu))
            _erev = (self._revise_popup(con, "petty", edit_no)
                     if emode == "locked" else "")
            if frag and emode == "locked":
                # Inside the Admin popup's iframe the revise prompt
                # cannot post (its redirect is a full page) — the
                # door breaks out to the full drawer page instead,
                # where the same locked card carries the prompt.
                # Build 'ac' (Jason 2026-10-27, defect C-5): the
                # door is the standard Edit door — the standard btn
                # class at the standard size, in the LEFT cluster
                # the row pattern puts Edit in (the old 'btnlink'
                # anchor had no CSS rule and rode the right
                # cluster). The row is built by hand here because
                # _btn_row's Edit is a popup button; the fragment
                # forces the anchor form of the same door.
                _erow_btn = (
                    f'<div style="display:flex;justify-content:'
                    f'space-between;align-items:center;gap:8px">'
                    f'<span style="font-size:14px;text-transform:none">'
                    f"<a class='btn' target='_top' "
                    f"href='/petty?edit="
                    f"{html.escape(edit_no, quote=True)}'>"
                    f"Edit</a></span>"
                    f'<span style="text-align:right;font-size:14px;'
                    f'text-transform:none"></span></div>')
                _erev = ""
            _ehid = (
                f"<input type=hidden name=revising value=1>"
                f"<input type=hidden name=target "
                f"value=\"{html.escape(edit_no, quote=True)}\">"
                if emode == "session" else "")
            _elock = self._LOCK_JS if emode == "locked" else ""
            return f"""
        <div class="fgrid">
          <div class="card" style="padding:10px">
            <h2 style="font-size:14px;margin:0 0 6px">Petty Cash Entry {html.escape(edit_no)}</h2>
            <form method=post action="/petty"{_ftarget} style="margin:0">
              {_fhidden}
              {_ehid}
              <div class="row"><div><label>No.</label><input name=pc_id value="{html.escape(edit_no, quote=True)}" class=w-sm></div>
              <div><label>Date</label><input type=date name=txn_date value="{html.escape(str(erow['txn_date'])[:10])}" required class=w-sm></div>
              <div><label>Direction</label><select name=direction class=w-xs><option value="in"{_din}>In</option><option value="out"{_dout}>Out</option></select></div></div>
              <div class="row"><div><label>Amount</label><input name=amount type=number step=0.01 min=0.01 required class=w-sm value="{float(erow['amount'])}"></div>
              <div><label>Category</label><select name=category class=w-md>{_cats}</select></div></div>
              <div class="row"><div><label>Payee / From</label><input name=payee value="{html.escape(erow['payee'] or '', quote=True)}" class=w-sm></div>
              <div><label>Ref</label><input name=ref_no value="{html.escape(erow['ref_no'] or '', quote=True)}" class=w-xs></div></div>
              <div><label>Notes</label><input name=notes value="{html.escape(erow['notes'] or '', quote=True)}"></div>
              {_erow_btn}
              {_erev}
            </form>
            {_elock}
          </div>
        </div>
        """
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
              <div class="row"><div><label>No.</label><input name=pc_id value="{html.escape(engine.peek_pc_id(con), quote=True)}" class=w-sm></div>
              <div><label>Date</label><input type=date name=txn_date value="{today}" required class=w-sm></div></div>
              <div class="row"><div><label>Amount</label><input name=amount type=number step=0.01 min=0.01 required class=w-sm></div><div>{out_cat_combo}</div></div>
              <div class="row"><div><label>Payee</label><input name=payee class=w-sm></div><div><label>Ref</label><input name=ref_no class=w-xs></div></div>
              <div><label>Notes</label><input name=notes></div>
              {self._btn_row("Save", "pettyoutjobpop", print_menu=_pmenu)}
              {self._job_info_popup('pettyoutjobpop')}
            </form>
          </div>
          <div class="card" style="padding:10px">
            <h2 style="font-size:14px;margin:0 0 6px">Cash In</h2>
            <form method=post action="/petty"{_ftarget} style="margin:0">
              {_fhidden}
              <input type=hidden name=direction value="in">
              <div class="row"><div><label>No.</label><input name=pc_id value="{html.escape(engine.peek_pc_id(con), quote=True)}" class=w-sm></div>
              <div><label>Date</label><input type=date name=txn_date value="{today}" required class=w-sm></div></div>
              <div class="row"><div><label>Amount</label><input name=amount type=number step=0.01 min=0.01 required class=w-sm></div><div><label>Category</label><select name=category class=w-sm>{in_opts}</select></div></div>
              <div class="row"><div><label>From</label><input name=payee placeholder="Bank / owner" class=w-sm></div><div><label>Ref</label><input name=ref_no class=w-xs></div></div>
              <div><label>Notes</label><input name=notes></div>
              {self._btn_row("Save", "pettyinjobpop", print_menu=_pmenu)}
              {self._job_info_popup('pettyinjobpop')}
            </form>
          </div>
        </div>
        """

    def view_customers(self, con):
        # Build 'ai' (Jason 2026-10-28): the page opens on the
        # standing blank form, like Vendors — the universal master
        # pattern. The form carries its own chain banner, its Save
        # row, and its View row at the bottom left (/customers/all).
        # What stood here before — a "+ New Customer" door and a
        # separate View door, no form (look-see batch 2, 2026-10-21)
        # — is the form's own furniture now.
        return tabs_admin("/customers", con=con) \
            + self.view_customer_form(con, None)

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
        if row:
            # Children key by the customer's ENGINE id (schema FK:
            # customer_contacts.customer_id REFERENCES customers(id),
            # enforced on the app connection) — the same key
            # engine.save_customer's auto-location uses.
            contacts=con.execute("SELECT * FROM customer_contacts WHERE customer_id=? ORDER BY is_primary DESC, name",(row["id"],)).fetchall()
            locations=con.execute("SELECT * FROM customer_locations WHERE customer_id=? ORDER BY is_primary DESC, location_name",(row["id"],)).fetchall()
        # Build 'ae' rebuild (Phase 3, Jason 2026-10-27 — one step, one form):
        # Contacts and Locations are sections of THIS form, on create
        # and edit alike (one anatomy). Rows mirror the money forms'
        # line rows: existing entries render filled; an empty set
        # renders one blank row; Add Contact / Add Location are
        # ADD-ROW controls (Add family — they append a blank row and
        # commit nothing); the form's one Save posts customer +
        # contacts + locations together. The post-save cards and
        # their separate POSTs are retired with the cards;
        # the per-row remove control is the package's
        # line-del ✕.
        _ROLE_OPTS = ("Main", "Accounting / A/P", "Purchasing", "Service",
                      "Operations", "Commercial / Terms", "Other")
        def _ct_row(i, c=None):
            def cv(k, default=""):
                if c is None:
                    return default
                val = c[k]
                return "" if val is None else str(val)
            opts = "".join(
                f'<option{" selected" if cv("role") == r else ""}>{r}</option>'
                for r in _ROLE_OPTS)
            return f"""
            <div class="ctrow">
              <input type=hidden name=ct_id_{i} value="{cv('contact_id')}">
              <input type=hidden name=ct_del_{i} value="">
              <div class=row3><div><label>Contact Name</label><input name=ct_name_{i} value="{html.escape(cv('name'), quote=True)}"></div><div><label>Role</label><select name=ct_role_{i}>{opts}</select></div><div style="align-self:end"><button type=button class="line-del" title="Remove contact">✕</button></div></div>
              <div class=row><div><label>Phone</label><input name=ct_phone_{i} value="{html.escape(format_phone(cv('phone')), quote=True)}" placeholder="+1 (337) 555-0100"></div><div><label>Email</label><input name=ct_email_{i} type=email value="{html.escape(cv('email'), quote=True)}"></div></div>
              <label><input type=checkbox name=ct_primary_{i} value=1 {"checked" if (c is not None and c["is_primary"]) else ""}> Main contact</label>
            </div>"""
        def _lc_row(i, l=None):
            def lv(k, default=""):
                if l is None:
                    return default
                val = l[k]
                return "" if val is None else str(val)
            return f"""
            <div class="lcrow">
              <input type=hidden name=lc_id_{i} value="{lv('location_id')}">
              <input type=hidden name=lc_del_{i} value="">
              <div class=row><div><label>Location Name</label><input name=lc_name_{i} value="{html.escape(lv('location_name'), quote=True)}" placeholder="Main office, Lafayette yard, Houston branch"></div><div style="align-self:end"><button type=button class="line-del" title="Remove location">✕</button></div></div>
              <label>Address</label><input name=lc_street_{i} value="{html.escape(lv('street'), quote=True)}">
              <input name=lc_street2_{i} value="{html.escape(lv('street2'), quote=True)}" placeholder="Suite, building, c/o…">
              <div class=row><div><label>City</label><input name=lc_city_{i} value="{html.escape(lv('city'), quote=True)}"></div><div><label>State</label>{state_field(f"lc_state_{i}", lv('state'), 'maxlength=20')}</div></div>
              <div class=row><div><label>Zip</label><input name=lc_zip_{i} maxlength=12 value="{html.escape(lv('zip'), quote=True)}"></div><div></div></div>
              <label><input type=checkbox name=lc_primary_{i} value=1 {"checked" if (l is not None and l["is_primary"]) else ""}> Make main location</label>
            </div>"""
        _ct_rows = "".join(_ct_row(i, c) for i, c in enumerate(contacts)) \
            or _ct_row(0)
        _lc_rows = "".join(_lc_row(i, l) for i, l in enumerate(locations)) \
            or _lc_row(0)
        _ct_js = """
        <script>
        (function(){
          function wire(boxId, addId, cls){
            var box=document.getElementById(boxId), btn=document.getElementById(addId);
            if(!box||!btn) return;
            function bind(row){
              var rm=row.querySelector('.line-del');
              if(!rm) return;
              rm.addEventListener('click', function(){
                var hid=null, del=null;
                row.querySelectorAll('input[type=hidden]').forEach(function(el){
                  if(/_id_\\d+$/.test(el.name)) hid=el;
                  if(/_del_\\d+$/.test(el.name)) del=el;
                });
                if(hid && hid.value){
                  if(del) del.value='1';
                  row.style.display='none';
                } else if(box.querySelectorAll('.'+cls).length>1){
                  row.remove();
                } else {
                  row.querySelectorAll('input,select').forEach(function(el){
                    if(el.type==='checkbox') el.checked=false;
                    else if(el.tagName==='SELECT') el.selectedIndex=0;
                    else el.value='';
                  });
                }
              });
            }
            box.querySelectorAll('.'+cls).forEach(bind);
            btn.addEventListener('click', function(){
              var rows=box.querySelectorAll('.'+cls);
              var n=0;
              rows.forEach(function(r){
                r.querySelectorAll('[name]').forEach(function(el){
                  var m=el.name.match(/_(\\d+)$/);
                  if(m) n=Math.max(n, parseInt(m[1],10)+1);
                });
              });
              var c=rows[rows.length-1].cloneNode(true);
              c.querySelectorAll('[name]').forEach(function(el){
                el.name=el.name.replace(/_\\d+$/, '_'+n);
                if(el.type==='checkbox') el.checked=false;
                else if(el.tagName==='SELECT') el.selectedIndex=0;
                else el.value='';
              });
              c.style.display='';
              box.appendChild(c);
              bind(c);
            });
          }
          wire('ct-rows','ct-add','ctrow');
          wire('lc-rows','lc-add','lcrow');
        })();
        </script>
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
        _crow = self._btn_row(
            "Save",
            extra='<a class="btn secondary" href="/customers">Close</a>')
        return chain_banner(con, "customer") + f"""
        <p class=hint>{'Customer ID: <b>'+html.escape(nxt)+'</b>' if row else 'Customer ID: auto.'}</p>
        <form method=post action="/customer/save">
          <input type=hidden name=customer_id value="{html.escape(nxt) if row else ''}">
          <section>
            <h2>Customer Information</h2>
            <div class=row><div><label>Business Name</label><input name=account_name required value="{html.escape(v('account_name'))}"></div><div><label>DBA / trade name <span class=hint>(optional)</span></label><input name=short_name value="{html.escape(v('short_name'))}"></div></div>
            <div class=row><div><label>Main Phone</label><input name=phone value="{html.escape(format_phone(v('phone')))}" placeholder="+1 (337) 555-0100"></div><div><label>General Email</label><input name=email type=email value="{html.escape(v('email'))}"></div></div>
          </section>
          <section>
            <h2>Main / Billing Address</h2>
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
          <section>
            <h2>Contacts</h2>
            <div id="ct-rows">{_ct_rows}</div>
            <p><button type=button id="ct-add" class=secondary>Add Contact</button></p>
          </section>
          <section>
            <h2>Locations</h2>
            <div id="lc-rows">{_lc_rows}</div>
            <p><button type=button id="lc-add" class=secondary>Add Location</button></p>
          </section>
          {_crow}
        </form>
        {po_block}
        {self._view_row("/customers/all", "Customers")}
        {_ct_js}
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
        _q_filter = ("WHERE q.revised_by_id IS NULL "
                     if engine.revision_cols_ready(con, "quotes")
                     else "")
        rows = con.execute(
            f"""SELECT q.quote_no, q.quote_date, q.status, c.account_name
               FROM quotes q
               LEFT JOIN customers c ON c.id = q.customer_id
               {_q_filter}
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
        # Void-and-revise (build 'ab'): the register shows chain
        # heads — a revised-away invoice is paper, reached through
        # its chain from the head's summary.
        rows = con.execute(
            """SELECT i.invoice_no, i.invoice_date, i.status, i.customer_id, c.account_name
               FROM invoices i JOIN customers c ON c.id=i.customer_id
               WHERE i.revised_by_id IS NULL
               ORDER BY i.invoice_date DESC"""
        ).fetchall() if engine._chain_ready(con) else con.execute(
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
        _inv_row = inv
        _inv_revised_away = bool(dict(inv).get("revised_by_id"))
        lines = con.execute(
            "SELECT * FROM invoice_lines WHERE invoice_id=? ORDER BY line_id", (inv["id"],)
        ).fetchall()
        # Per-line paid state (Jason 2026-10-23): the Paid / Open
        # figures read allocations only — a blanket-paid line still
        # reads open here; the balance governs. Build 'ac' (Jason
        # 2026-10-27, state changes values, not anatomy): the Paid /
        # Open / Note columns stand on EVERY invoice — they used to
        # appear only once line allocations existed (Paid/Open) or a
        # note did (Note). A line with no allocation state reads
        # $0.00 paid and its full amount open.
        _states = {s["line_id"]: s
                   for s in engine.invoice_line_states(con, ino)}

        def _line_cells(r):
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
            # Build 'ah' (Jason 2026-10-28): the per-line note form
            # (and its Save button, and the Read button the note
            # script injected beside it) is off — the note stands
            # in the one summary note seat: plain text when it fits
            # its cell, the click-to-open temporary box when it
            # runs long, posting with the summary's Print door.
            _note_cell = self._sum_note_cell(
                "invoice", ino, int(r["line_id"]),
                (_st["note"] if _st else (r["line_note"] or "")))
            return [
                html.escape(r['category'] or ''),
                html.escape(r['item'] or ''),
                html.escape(r['description']),
                f"{float(r['qty']):g}",
                html.escape(r['uom'] or ''),
                f"${float(r['rate']):,.2f}",
                f"${float(r['amount']):,.2f}",
                (f"${(_st['allocated'] if _st else 0):,.2f}"
                 f"{_cred_seg}"),
                (f"${(_st['remaining'] if _st else 0):,.2f}"
                 if _st else f"${float(r['amount']):,.2f}"),
                _note_cell,
            ]

        _inv_line_cols = [("Type", False), ("Item", False),
                          ("Description", False), ("Qty", True),
                          ("Unit", False), ("Rate", True),
                          ("Amount", True), ("Paid", True),
                          ("Open", True), ("Note", False)]
        body = [_line_cells(r) for r in lines]
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
            # Build 'aa' (2026-10-26): the printed-template header
            # block (doc_header) that used to head this page is not
            # built anymore — the summary's fact table states its
            # facts now. The block's inputs above (the remit /
            # distribution lines, the billing lines) still feed the
            # fact table and the totals column.
        # Build 'af' (Jason 2026-10-28): the totals ride INSIDE
        # the lines block — compact rows directly under the lines
        # table. The old free-standing flex row (totals floated
        # right, a void at left) dies. No extra write-in row here
        # (Invoice Round Part C): printpack's totals column carries
        # the write-in row itself.
        totals_html = (
            f"<div style='display:flex;justify-content:flex-end'>"
            f"{_totals_col}</div>" if _totals_col else "")
        # Paperwork (build 'af'): the summary's Paperwork section
        # lists the invoice's four slot documents as plain links —
        # the slots themselves stay managed on the invoice form
        # side exactly as before; nothing on a summary alters an
        # existing upload.
        _slot_docs = {"po": _jb.get("po_doc"), "tax_exempt": _jb.get("tax_doc"),
                      "shipping": _jb.get("shipping_doc"),
                      "custom": _jb.get("custom_doc")}
        _slot_links = []
        for _sk in ("po", "tax_exempt", "shipping", "custom"):
            _sd = _slot_docs.get(_sk)
            if _sd:
                _slot_links.append(
                    f"<a href='/invoicedoc/"
                    f"{html.escape(ino, quote=True)}/{_sk}'>"
                    f"{html.escape(_sd['filename'])}</a>")
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
        # Build 'af': the section heading is a .sumsec div, not an
        # h2 — the shell's section wrapper starts a new card at an
        # h2, and Payments & Credits is a section INSIDE the one
        # summary card (Jason 2026-10-28).
        payments_html = f"""
        <div class="sumsec">Payments &amp; Credits</div>
        <table><tr><th>Date</th><th>Method</th><th>Ref / Credit Memo #</th><th>Amount</th><th>Applied</th><th>Input by:</th></tr>
        {pay_rows or '<tr><td colspan=6>No payments or credits applied yet.</td></tr>'}</table>
        """
        engine.stamp_module_seen(con, "billing")
        # Summary of Invoice# (build 'u', Jason 2026-10-25,
        # universal summary pattern; build 'aa' fold into the
        # shared template; build 'ac' sections composition — the
        # history stands in git). Build 'af' (Jason 2026-10-28):
        # the Edit Lines, Job Info and Paperwork doors AND their
        # popups are OFF this summary — Edit Lines was never asked
        # for (line add/delete is the invoice form's work), the
        # summary states the job info itself, and paperwork is
        # attached at creation or through Edit. The PO form's post
        # and the slot paperwork posts stay routed — the invoice
        # FORM side uses them.
        # Build 'ag' (Jason 2026-10-28): the Payment door and its
        # popup are OFF this summary too — the quick-pay form it
        # carried duplicated the Payment form, and money work
        # lives there and on the invoice form. Build 'ai' (Jason
        # 2026-10-28, reversing 'ag'/'ah' at his word): ONE small
        # Payment button stands in the summary's bottom row —
        # navigation to the payment form with this invoice
        # prefilled; no money is worked on the summary. The Payments &
        # Credits section above is a record and stands. The
        # #record-payment anchor died with the popup; the Today
        # and ticker links that targeted it now land on the
        # summary itself (engine_today / engine_alerts).
        # Build 'ah' (Jason 2026-10-28): the per-line note forms
        # 'af' stood in this lines table are off — the note stands
        # in the one summary note seat (_sum_note_cell): plain
        # text when it fits, the click-to-open temporary box when
        # it runs long, posting with this summary's Print door.
        doors = self._sum_doors(
            "",
            None if _inv_revised_away else f"/invoice/new?edit={ino}",
            self._print_menu(screen=f"/print/invoice/{ino}",
                             pdf=f"/print/invoice/{ino}.pdf"))
        popups = ""
        _assoc_co = self._assoc_co_fact(con, "invoice", ino)
        # Build 'af' (Jason 2026-10-28): grouped fact blocks —
        # Customer up-left, Job Info at right, the invoice's own
        # facts in their block; facts with no value are omitted.
        # The Job Info block states ALL provided job info fields
        # (not only the print-selected subset the old flat list
        # carried), each with its print-inclusion marker: printed
        # = the field is in the inv_jobinfo_fields selection AND
        # inside printpack's first-seven cap, exactly what
        # _jobinfo_lines puts on the printed invoice.
        cust_pairs = [("Customer", html.escape(inv["account_name"] or ""))]
        job_pairs = []
        doc_pairs = [("Date", html.escape(fmt_date(inv["invoice_date"]))),
                     ("Status", html.escape(inv["status"] or ""))]
        if _pack is not None:
            cust_pairs.append(("Billing Address", _bill_html or None))
            _ship_txt = ""
            if _pack.get("ship_to"):
                _sb = []
                for s in _pack["ship_to"]:
                    _cl = ", ".join(x for x in (
                        s.get("city"),
                        " ".join(y for y in (s.get("state"),
                                             s.get("zip")) if y)) if x)
                    _bits = [s.get("site_name"), s.get("operator"),
                             s.get("rig_name"), s.get("street"),
                             s.get("street2"), _cl]
                    _sb.append("<br>".join(
                        html.escape(x) for x in _bits if x))
                _ship_txt = "<br>".join(x for x in _sb if x)
            cust_pairs.append(("Ship To", _ship_txt or None))
            cust_pairs.append(("Terms", html.escape(_pinv["terms"])
                               if _pinv["terms"] else None))
            # Values and the printed set follow printpack's own
            # _jobinfo_lines exactly (the same pack["job"] map and
            # the same first-seven cap) — the marker states what
            # the printed invoice carries, never a second reading.
            from printpack import JOBINFO_FIELDS as _PP_JF
            _jb2 = _pack.get("job") or {}
            _fields = _pack.get("job_fields")
            if _fields is None:
                _fields = ["po", "job", "well", "location",
                           "taxexempt"]
            _sel = [k for k, _l in _PP_JF if k in set(_fields)][:7]
            if "tax_exempt_source" in _jb2:
                _src = (_jb2.get("tax_exempt_source") or "").strip()
                _taxv = {"cert": "Cert on file", "customer": "Yes",
                         "operator": "Yes"}.get(_src, "No")
            else:
                _taxv = ("Cert on file" if _jb2.get("tax_exempt")
                         else "No")
            _raw = {
                "po": _jb2.get("po") or "",
                "well": ", ".join(_jb2.get("wells") or []),
                "afe": (_jb2.get("afe")
                        or ", ".join(_jb2.get("afes") or [])),
                "cost_code": _jb2.get("cost_code") or "",
                "job": ", ".join(_jb2.get("jobs") or []),
                "contact_name": _jb2.get("contact_name") or "",
                "contact_phone": _jb2.get("contact_phone") or "",
                "contact_email": _jb2.get("contact_email") or "",
                "ticket_ref": (_jb2.get("ticket_ref") or ", ".join(
                    _jb2.get("ticket_refs") or [])),
                "job_notes": _jb2.get("job_notes") or "",
                "location": ", ".join(_jb2.get("locations") or []),
                "taxexempt": _taxv,
            }
            _triples = []
            for _k, _lab in _PP_JF:
                if _k == "taxexempt":
                    _triples.append((_lab, _taxv, _k in _sel))
                elif _raw.get(_k):
                    _triples.append((_lab,
                                     html.escape(str(_raw[_k])),
                                     _k in _sel))
            job_pairs = self._ji_pairs(_triples)
        doc_pairs.append(("Associated", _assoc_co))
        doc_pairs += self._chain_facts(
            con, "invoice", _inv_row,
            lambda n: f"/invoice/{html.escape(n, quote=True)}")
        # Build 'ac': the lines render through the shared builder.
        # Build 'af': the totals ride inside the lines block (see
        # totals_html above), and the PO panel, quote panel and
        # Payments & Credits ride as sections after the lines.
        lines_html = (self._sum_lines(
            _inv_line_cols, body, empty_text="No extra lines.")
            + totals_html)
        sections_html = f"{po_panel}{quote_panel}{payments_html}"
        return (self._sum_page(
                    "Invoice", ino, [], lines_html, doors, popups,
                    "/money/invoices/audit", "Invoices",
                    extra_top=(self._revto_line(con, "invoice", _inv_row)
                               + task_nudge(con, f"/invoice/{ino}")),
                    sections_html=sections_html,
                    fact_groups=[("Customer", cust_pairs),
                                 ("Job Info", job_pairs),
                                 ("Invoice", doc_pairs)],
                    paper_html=self._sum_paperwork(
                        "invoice", ino, extra_links=_slot_links),
                    pay_doc=("invoice", ino))
                + _item_extras(con))
