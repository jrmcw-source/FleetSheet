"""FleetSheet POST actions — assets flow: tickets, units, sites, work orders."""
import json
from datetime import date

import engine
from urllib.parse import quote_plus

from views_core import chain_advance


def _haul_names(con, cust_key=None, cust_code=None):
    """Names for engine.resolve_haul_text (build 'am', Jason
    2026-10-28): the company's dba/name and the customer's account
    name — the two name-form Transport presets resolve to their
    keys when the caller supplies them. '' when unknown."""
    try:
        co = con.execute(
            "SELECT dba, name FROM company WHERE id=1").fetchone()
        company = ((co["dba"] or co["name"]) if co else "") or ""
    except Exception:
        company = ""
    customer = ""
    try:
        key = cust_key
        if key is None and cust_code:
            key = engine.cust_key(con, cust_code)
        if key is not None:
            r = con.execute(
                "SELECT account_name FROM customers WHERE id=?",
                (key,)).fetchone()
            customer = (r["account_name"] or "") if r else ""
    except Exception:
        customer = ""
    return company, customer


def _chain_redirect(handler, adv):
    sep = "&" if "?" in adv[0] else "?"
    handler._redirect(adv[0] + sep + "from=setup&msg=" + quote_plus(adv[1]))



def _post_ticket_edit(handler, con, data):
    """Save the rental editor (build 'ab', void-and-revise): the
    booking form loaded with an existing ticket posts editing=1.
    Under the model this save is a REVISION completing — the form
    was loaded with a fresh revision under its session marker
    (edit_target names the revision as loaded; the posted
    ticket_id is the operator's number for it, renames included,
    validated against the whole history). Without the marker the
    save is refused: a posted rental never updates in place.
    engine.update_ticket writes the revision's own row; the gates
    it carries (customer lock, unit-after-check-out, JC-AB1/AB2)
    apply unchanged. The Job Info popup's Well # and the form's
    Off-Rent Est map onto the ticket's columns here (JC-AB15: at
    creation both are dropped by the booking handler —
    pre-existing, untouched). The ticket's tax jurisdiction is
    not a field on this form and is preserved from the record."""
    target = (data.get("edit_target") or "").strip()
    tid = (data.get("ticket_id") or "").strip()
    if not target:
        handler._redirect("/tickets?err=" + quote_plus(
            "Rental Ticket " + (tid or "?") + " is posted — revise "
            "it (Edit on its form) to change it"))
        return True
    back = f"/ticket/new?kind=rental&edit={target}"
    trow = con.execute(
        "SELECT id, customer_id, tax_loc_id FROM tickets "
        "WHERE ticket_id=?", (target,)).fetchone()
    if not trow:
        handler._redirect("/tickets?err=" + quote_plus(
            "No such rental ticket"))
        return True
    if not engine.revision_pending(con, "ticket", trow["id"]):
        handler._redirect(f"/ticket/{target}?err=" + quote_plus(
            f"Rental Ticket {target} is posted — revise it (Edit "
            f"on its form) to change it"))
        return True
    # Site from the Job Info popup's Job Location text — the same
    # resolution creation applies to a typed site name.
    site_id = None
    site_text = (data.get("job_location") or "").strip()
    if site_text:
        hit = con.execute(
            "SELECT site_id FROM sites WHERE site_name=?",
            (site_text,)).fetchone()
        if hit:
            site_id = hit["site_id"]
        else:
            site_id = engine.next_site_id(con)
            con.execute(
                "INSERT INTO sites (site_id, site_name, customer_id, loc_id) VALUES (?,?,?,NULL)",
                (site_id, site_text,
                 engine.cust_key(con, data.get("customer_id") or "")))
            con.commit()
    haul_text = (data.get("haul_text") or "").strip()
    haul_by, haul_note = engine.resolve_haul_text(
        haul_text, *_haul_names(con, cust_code=data.get("customer_id")))
    deliver_text = (data.get("deliver_text") or "").strip()
    deliver_to, deliver_note = "job_site", ""
    for d in ("job_site", "our_yard", "customer_yard", "dock"):
        if deliver_text.lower() in (d, engine.DELIVER_LABELS[d].lower()):
            deliver_to = d
            break
    else:
        if deliver_text:
            deliver_note = deliver_text
    upd = {
        "customer_id": data.get("customer_id") or "",
        "site_id": site_id,
        "asset_id": (data.get("asset_id") or "").strip(),
        "job_name": data.get("job_name"),
        "well_or_pad": data.get("well_no") or data.get("well_or_pad"),
        "afe": data.get("afe"),
        "po": data.get("po"),
        "rate_type": engine.uom_to_rate_type(data.get("uom"))
                     or (data.get("rate_type") or "Day"),
        "rate_value": data.get("rate_value") or None,
        "on_rent": data.get("on_rent"),
        "off_rent": (data.get("off_rent_est") or "").strip() or None,
        "haul_by": haul_by,
        "haul_note": haul_note,
        "deliver_to": deliver_to,
        "deliver_note": deliver_note,
        "tax_loc_id": engine.loc_code(con, trow["tax_loc_id"])
                      if trow["tax_loc_id"] else None,
        "location_note": data.get("location_note") or "",
        "clerk": handler.desk(con),
    }
    try:
        engine.update_ticket(con, target, upd)
    except engine.SoftReserveConflict as sc:
        con.rollback()
        handler._redirect(back + "&err=" + quote_plus(
            f"Unit is soft-reserved on Rental Ticket "
            f"{sc.ticket['ticket_id']} for another job — the edit "
            f"was not saved"))
        return True
    except ValueError as e:
        con.rollback()
        handler._redirect(back + "&err=" + quote_plus(str(e)[:160]))
        return True
    final = target
    if tid and tid != target:
        try:
            engine.validate_new_doc_no(con, "tickets", "ticket_id",
                                       tid, "rental ticket")
        except ValueError as e:
            handler._redirect(back + "&err=" + quote_plus(str(e)[:160]))
            return True
        con.execute("UPDATE tickets SET ticket_id=? WHERE ticket_id=?",
                    (tid, target))
        final = tid
    con.execute(
        "UPDATE tickets SET ref_ticket=? WHERE ticket_id=?",
        ((data.get("ref_ticket") or "").strip() or None, final))
    con.commit()
    engine.clear_revision_pending(
        con, "ticket", engine.doc_key(con, "ticket", final))
    up = (handler._files or {}).get("job_attach")
    if up and up[2]:
        engine.save_job_attachment(con, "ticket", final, up[0], up[2],
                                   handler.desk(con))
    up2 = (handler._files or {}).get("ticket_upload")
    if up2 and up2[2]:
        engine.save_job_attachment(con, "ticket", final, up2[0], up2[2],
                                   handler.desk(con))
    engine.add_done_manual(
        con, f"Edited Rental Ticket {final}", f"/ticket/{final}",
        handler.desk(con))
    handler._redirect(f"/ticket/{final}?msg=" + quote_plus(
        "Rental Ticket saved"))
    return True


def handle_post(handler, con, data, u):
    """Handle one POST. Returns True when the path was handled."""
    if u.path == "/ticket/new":
            if (data.get("editing") or "") == "1":
                return _post_ticket_edit(handler, con, data)
            # Site is optional on the rental form (Jason 2026-10-07) — no
            # site field is rendered. A site may still arrive from older
            # flows; match it, else leave the ticket site-less (NULL).
            site_id = (data.get("site_id") or "").strip() or None
            site_text = (data.get("site_text") or "").strip()
            if not site_id and site_text:
                hit = con.execute(
                    "SELECT site_id FROM sites WHERE site_name=?",
                    (site_text,)).fetchone()
                if hit:
                    site_id = hit["site_id"]
            if not site_id and site_text:
                # Legacy free-text flow only: the typed name becomes a real
                # site on this customer so it can be picked next time.
                # No tax jurisdiction is autofilled: that is the operator's
                # call, made on the site page.
                site_id = engine.next_site_id(con)
                con.execute(
                    "INSERT INTO sites (site_id, site_name, customer_id, loc_id) VALUES (?,?,?,NULL)",
                    (site_id, site_text, data.get("customer_id") or None))
                con.commit()
            # Transport typeahead: a preset or a storage key resolves to
            # its key; any other text is a third-party carrier name, kept
            # verbatim as the note (engine.resolve_haul_text).
            haul_text = (data.get("haul_text") or "").strip()
            haul_by, haul_note = engine.resolve_haul_text(
                haul_text,
                *_haul_names(con, cust_code=data.get("customer_id")))
            deliver_text = (data.get("deliver_text") or "").strip()
            deliver_to, deliver_note = "job_site", ""
            for d in ("job_site", "our_yard", "customer_yard", "dock"):
                if deliver_text.lower() in (d, engine.DELIVER_LABELS[d].lower()):
                    deliver_to = d
                    break
            else:
                if deliver_text:
                    deliver_note = deliver_text
            tax_text = (data.get("tax_text") or "").strip()
            tax_loc_id = ""
            if tax_text:
                hit = con.execute(
                    "SELECT loc_id FROM jurisdictions WHERE loc_id=? OR display_name=?",
                    (tax_text, tax_text)).fetchone()
                # also try matching the "name · 8.50%" label form
                if not hit:
                    hit = con.execute(
                        "SELECT loc_id, COALESCE(display_name, loc_id) || ' · ' || "
                        "printf('%.2f%%', tax_rate*100) AS label FROM jurisdictions"
                    ).fetchall()
                    hit = next((r for r in hit if r["label"] == tax_text), None)
                tax_loc_id = hit["loc_id"] if hit else ""
            # Line rows (2026-10-16): row 0 uses bare names, Add Item clones
            # use suffixed names (asset_id1, uom1, ...). Each non-blank row
            # becomes its own ticket sharing the header — renting two units
            # = two tickets, same customer/dates/haul. A row is blank when
            # it names no unit and carries no text, description, or rate.
            def _row_ticket(i):
                suf = "" if i == 0 else str(i)
                aid = (data.get(f"asset_id{suf}") or "").strip()
                itext = (data.get(f"unit_text{suf}") or "").strip()
                desc = (data.get(f"item_desc{suf}") or "").strip()
                rate = (data.get(f"rate_value{suf}") or "").strip()
                if not aid and not itext and not desc and not rate:
                    return None
                if not aid:
                    raise ValueError("Pick a unit from the list")
                return {
                    "customer_id": data["customer_id"],
                    "site_id": site_id,
                    "asset_id": aid,
                    "job_name": data.get("job_name"),
                    "well_or_pad": data.get("well_or_pad"),
                    "afe": data.get("afe"),
                    "po": data.get("po"),
                    # The row's Unit select (inv_uom) drives the ticket's rate
                    # type when it maps (Days→Day, …); Each/blank falls back to
                    # the JS-synced hidden rate_type, which preserves a unit's
                    # Special/Standby/Yard rate instead of silently re-rating
                    # it to Day.
                    "rate_type": engine.uom_to_rate_type(data.get(f"uom{suf}")) or (data.get(f"rate_type{suf}") or "Day"),
                    "rate_value": data.get(f"rate_value{suf}") or None,
                    "on_rent": data["on_rent"],
                    "waiver_yn": data.get("waiver_yn") == "1",
                    "status": data.get("status") or "Reserved",
                    "mob": data.get("mob") or 0,
                    "demob": data.get("demob") or 0,
                    "transport_fee": data.get("transport_fee") or 0,
                    "haul_by": haul_by,
                    "haul_note": haul_note,
                    "deliver_to": deliver_to,
                    "deliver_note": deliver_note,
                    "tax_loc_id": tax_loc_id or None,
                    "location_note": data.get("location_note") or "",
                    "quote_no": data.get("quote_no") or "",
                }

            row_tickets = []
            for _i in range(8):
                _rt = _row_ticket(_i)
                if _rt is not None:
                    if not row_tickets:
                        _want_tid = (data.get("ticket_id") or "").strip()
                        if _want_tid:
                            _rt["ticket_id"] = _want_tid
                    row_tickets.append(_rt)
            if not row_tickets:
                raise ValueError("Pick a unit from the list")
            # Charge lines no longer ride the booking (build 's',
            # Jason 2026-10-25): charges on tickets ended as a
            # capability — freight and extras are line items on the
            # invoice. A crafted post's c-fields are ignored here.
            # One line per unit: the same asset twice is a form error, not
            # two tickets — the frontend flags it, but never trust the client.
            _seen_aids = set()
            for _rt in row_tickets:
                if _rt["asset_id"] in _seen_aids:
                    _uno = con.execute("SELECT unit_no FROM assets WHERE asset_id=?",
                                       (_rt["asset_id"],)).fetchone()
                    raise ValueError(
                        f"Unit {_uno['unit_no'] if _uno else _rt['asset_id']} is listed twice — one line per unit")
                _seen_aids.add(_rt["asset_id"])
            # Pre-check conflicts BEFORE creating anything: create_ticket
            # commits per ticket, so a mid-loop conflict would leave earlier
            # rows booked. Same query create_ticket uses.
            conflict_idx = None
            conflict_ticket = None
            for _i, _rt in enumerate(row_tickets):
                _busy = con.execute(
                    """SELECT ticket_id, COALESCE(soft_reserve,0) AS soft_reserve
                       FROM tickets
                       WHERE asset_id=? AND status IN ('Reserved','Dispatched','On Rent','Standby')""",
                    (engine.asset_key(con, _rt["asset_id"]),)).fetchone()
                if _busy:
                    if _busy["soft_reserve"]:
                        if conflict_idx is None:
                            conflict_idx = _i
                            conflict_ticket = _busy["ticket_id"]
                    else:
                        raise ValueError(f"Unit already on Rental Ticket {_busy['ticket_id']} (open)")
            if conflict_idx is not None:
                # PO soft-reserve: never auto-block. Stash ALL rows —
                # override books them all, cancel books none.
                cur = con.execute(
                    "INSERT INTO pending_bookings (soft_ticket_id, data_json) VALUES (?,?)",
                    (engine.doc_key(con, "ticket", conflict_ticket),
                     json.dumps({"tickets": row_tickets, "conflict": conflict_idx})))
                con.commit()
                handler._redirect(f"/ticket/new?soft_conflict={cur.lastrowid}")
                return True
            # Ensure ref_ticket column exists (Jason 2026-10-07 F5)
            tcols = [r[1] for r in con.execute("PRAGMA table_info(tickets)")]
            if "ref_ticket" not in tcols:
                con.execute("ALTER TABLE tickets ADD COLUMN ref_ticket TEXT")
            tids = []
            for _rt in row_tickets:
                tids.append(engine.create_ticket(con, _rt))
            # Creates are explicit operator actions — Done Today gets
            # one entry per ticket (look-see batch 2, 2026-10-21).
            for _tid in tids:
                engine.add_done_manual(
                    con, f"Created Rental Ticket {_tid}", f"/ticket/{_tid}",
                    handler.desk(con))
            # Save ref_ticket on every ticket in the booking.
            if data.get("ref_ticket"):
                for _tid in tids:
                    con.execute("UPDATE tickets SET ref_ticket=? WHERE ticket_id=?",
                                ((data.get("ref_ticket") or "").strip(), _tid))
                con.commit()
            # Job info attachment (Jason 2026-10-07) + ticket upload
            # (Jason 2026-10-07 F5): one file for the booking, attached
            # to the first ticket only.
            up = (handler._files or {}).get("job_attach")
            if up and up[2]:
                engine.save_job_attachment(con, "ticket", tids[0], up[0], up[2], handler.desk(con))
            up2 = (handler._files or {}).get("ticket_upload")
            if up2 and up2[2]:
                engine.save_job_attachment(con, "ticket", tids[0], up2[0], up2[2], handler.desk(con))
            if len(tids) == 1:
                handler._redirect(f"/ticket/new?msg=Rental+Ticket+saved&new={tids[0]}")
            else:
                handler._redirect(f"/ticket/new?msg={len(tids)}+Rental+Tickets+saved&new={tids[0]}")
    elif u.path == "/ticket/new/override":
        # Operator picked the new booking over the soft reservation.
        pid = (data.get("pending_id") or "").strip()
        prow = con.execute("SELECT * FROM pending_bookings WHERE pending_id=?", (pid,)).fetchone()
        if not prow:
            handler._redirect("/ticket/new?err=Booking+expired")
            return True
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
            "SELECT ticket_id, COALESCE(soft_reserve,0) AS soft_reserve FROM tickets WHERE id=?",
            (prow["soft_ticket_id"],)).fetchone()
        if soft and soft["soft_reserve"]:
            con.execute("UPDATE tickets SET status='Void' WHERE ticket_id=?", (soft["ticket_id"],))
            unit = con.execute(
                "SELECT unit_no FROM assets WHERE asset_id=?", (conflict_row.get("asset_id"),)).fetchone()
            engine.add_done_manual(
                con, f"Soft reserve {soft['ticket_id']} bumped for new booking"
                     f"{' — ' + unit['unit_no'] if unit else ''}",
                f"/ticket/{soft['ticket_id']}", handler.desk(con))
        try:
            tids = [engine.create_ticket(con, d) for d in ticket_dicts]
            for _tid in tids:
                engine.add_done_manual(
                    con, f"Created Rental Ticket {_tid}", f"/ticket/{_tid}",
                    handler.desk(con))
        except engine.SoftReserveConflict as sc:
            # A second soft reserve still holds the unit (two POs can
            # soft-reserve one asset). The void above already committed
            # via the done-log; the pending row stays, so the operator
            # can cancel. Name the blocker instead of the generic page.
            handler._redirect(
                f"/ticket/new?err=Unit+still+soft-reserved+on+Rental+Ticket+{sc.ticket['ticket_id']}")
            return True
        con.execute("DELETE FROM pending_bookings WHERE pending_id=?", (pid,))
        con.commit()
        if len(tids) == 1:
            handler._redirect(f"/ticket/new?msg=Rental+Ticket+saved&new={tids[0]}")
        else:
            handler._redirect(f"/ticket/new?msg={len(tids)}+Rental+Tickets+saved&new={tids[0]}")
    elif u.path == "/ticket/new/cancel":
        # Operator kept the existing soft reservation.
        pid = (data.get("pending_id") or "").strip()
        con.execute("DELETE FROM pending_bookings WHERE pending_id=?", (pid,))
        con.commit()
        handler._redirect("/ticket/new")
    elif u.path.startswith("/ticket/") and u.path.endswith("/transport"):
            # Build 's' (Jason 2026-10-25): this route now serves the
            # ticket page's Job Info popup — Transport, Deliver to, Tax
            # Jurisdiction, and ticket uploads (the ticket attachment
            # store, same as the booking form's uploads). The charges
            # grid that rode this Save through build 'p' is gone:
            # charges on tickets ended as a capability, and a crafted
            # post's c-fields save nothing. update_ticket_transport
            # keeps the lock (Billed/Closed/Void or invoiced refuses),
            # so a locked ticket's popup post is refused whole —
            # fields and upload alike.
            tid = u.path.split("/")[2]
            _trow = con.execute(
                "SELECT customer_id FROM tickets WHERE ticket_id=?",
                (tid,)).fetchone()
            _haul_by, _haul_note = engine.resolve_haul_text(
                data.get("haul_by"),
                *_haul_names(con, cust_key=(
                    _trow["customer_id"] if _trow else None)))
            engine.update_ticket_transport(con, tid, {
                "haul_by": _haul_by,
                "haul_note": _haul_note,
                "deliver_to": data.get("deliver_to"),
                "tax_loc_id": data.get("tax_loc_id"),
            })
            up = (handler._files or {}).get("ticket_upload")
            if up and up[2]:
                engine.save_job_attachment(con, "ticket", tid, up[0], up[2], handler.desk(con))
            handler._redirect(f"/ticket/{tid}?msg=Rental+Ticket+saved")
    elif u.path.startswith("/ticket/") and u.path.endswith("/status"):
            tid = u.path.split("/")[2]
            # Condition gates (shop-flow ruling, Jason 2026-10-21): no
            # un-overridable blocks anywhere. The condition switch OFF
            # skips the presence gates entirely; ON keeps them, with the
            # status form's "Proceed anyway" checkbox as the audited
            # escape. The FIT block refuses in BOTH modes — the switch
            # governs condition records only — and opens through the
            # same Proceed anyway (override_fit), stamped on the ticket.
            _cond_on = engine.module_on(con, "condition")
            _proceed = data.get("proceed") == "1"
            # Batch 3 #13: the bypass stamp is the desk-session
            # identity, never a posted clerk field.
            engine.set_status(con, tid, data["status"], data.get("off_rent") or None,
                              handler.desk(con),
                              skip_condition=(not _cond_on) or _proceed,
                              audit_bypass=_proceed and _cond_on,
                              override_fit=_proceed)
            handler._redirect(f"/ticket/{tid}?msg=Status+updated")
    elif u.path.startswith("/ticket/") and u.path.endswith("/jump"):
            # Noted passage (Jason, 2026-10-21): any status, with a note.
            # set_status composes the gates around the note itself.
            tid = u.path.split("/")[2]
            engine.set_status(con, tid, data.get("status", ""),
                              data.get("off_rent") or None,
                              handler.desk(con),
                              jump_note=data.get("note", ""))
            handler._redirect(f"/ticket/{tid}?msg=" + quote_plus(
                f"{tid} moved to {data.get('status', '')} with note"))
    elif u.path.startswith("/ticket/") and u.path.endswith("/offrent"):
            # Quick off-rent date entry from the no-end-date list: sets the
            # date only, status untouched.
            tid = u.path.split("/")[2]
            back = "/tickets?flag=nooff"
            try:
                off = engine.parse_date(data.get("off_rent") or "", "Off-rent date", required=True)
            except ValueError as e:
                handler._redirect(back + "&err=" + quote_plus(str(e)))
                return
            con.execute("UPDATE tickets SET off_rent=? WHERE ticket_id=?", (off, tid))
            con.commit()
            handler._redirect(back + "&msg=" + quote_plus(f"{tid} off-rent {off}"))
    elif u.path.startswith("/ticket/") and u.path.endswith("/condition"):
            tid = u.path.split("/")[2]
            side = data.get("side") or ""
            up = (handler._files or {}).get("photo")
            if up and up[2]:
                # Validate the photo BEFORE the condition commits, so a bad
                # upload rejects the whole save instead of leaving a
                # condition with no photo.
                engine.validate_photo_blob(up[2])
            engine.save_ticket_condition(con, tid, side, {
                "condition": data.get("condition"),
                "note": data.get("note"),
                "meter": data.get("meter"),
                "hours": data.get("hours"),
                "clerk": handler.desk(con),
                "source": "desk",
            })
            if up and up[2]:
                engine.save_ticket_photo(con, tid, side, up[2], up[0])
            handler._redirect(f"/ticket/{tid}?msg=Condition+saved")
    elif u.path == "/unit/save":
            aid_in = data.get("asset_id") or None
            aid = engine.save_asset(con, {
                "unit_no": data.get("unit_no"),
                "description": data.get("description"),
                "category": data.get("category"),
                "yard": data.get("yard"),
                "serial_no": data.get("serial_no"),
                "uscg_ok": data.get("uscg_ok") == "1",
                "dnv_ok": data.get("dnv_ok") == "1",
                "abs_ok": data.get("abs_ok") == "1",
                "cert_operator": data.get("cert_operator") == "1",
                "rate_unit": data.get("rate_unit"),
                "rate_value": data.get("rate_value"),
                "meter_hours": data.get("meter_hours"),
                "replacement_cost": data.get("replacement_cost"),
                # cert_expire is legacy and no longer edited here; cert records carry expiries.
                "ownership": data.get("ownership"),
                "active": "1" if data.get("active") == "1" else "0",
                "condition": data.get("condition"),
                "designation": data.get("designation"),
                # Lifecycle switch (Phase 5, Oct 24) + audit attribution:
                # the desk-session identity rides the save so a class or
                # status change is recorded under its name (Batch 3 #13
                # pattern — stamped here, never a posted field).
                "status": data.get("status"),
                "clerk": handler.desk(con),
                "notes": data.get("notes"),
                # While-out switch note (build 'o'): the editor shows
                # the field when the unit is out on a live ticket; the
                # engine requires it for a class/status switch then.
                "switch_note": data.get("switch_note"),
            }, aid_in)
            if not aid_in:
                # New unit: the operator explicitly did something — log it so
                # it shows in the Done box. Edits are not logged.
                unit_no = (data.get("unit_no") or "").strip()
                desc = (data.get("description") or "").strip()
                engine.add_done_manual(
                    con, f"Added unit {unit_no} — {desc}"[:200],
                    f"/unit/{aid}", handler.desk(con))
            # Setup chain (Batch 3 #3): advance during a run; after
            # Finished, the normal landing below.
            adv = chain_advance(con, "equipment", "Unit saved")
            if adv:
                _chain_redirect(handler, adv)
            else:
                handler._redirect(f"/units?msg=Unit+saved")
    elif u.path == "/site/save":
            sid = data.get("site_id") or None
            _site_existed = bool(sid and con.execute(
                "SELECT 1 FROM sites WHERE site_id=?", (sid,)).fetchone())
            sid = engine.save_site(con, {
                "site_name": data.get("site_name"),
                "street": data.get("street"),
                "street2": data.get("street2"),
                "city": data.get("city"),
                "state": data.get("state"),
                "zip": data.get("zip"),
                "operator": data.get("operator"),
                "rig_name": data.get("rig_name"),
                "flag_state": data.get("flag_state"),
                "waters": data.get("waters"),
                "primary_regime": data.get("primary_regime"),
                "customer_id": data.get("customer_id"),
                "loc_id": data.get("loc_id"),
                "tax_exempt": data.get("tax_exempt") == "1",
                "notes": data.get("notes"),
            }, sid)
            if not _site_existed:
                engine.add_done_manual(
                    con, f"Added site {(data.get('site_name') or '').strip()} ({sid})"[:200],
                    f"/site/{sid}/edit", handler.desk(con))
            # Setup chain (Batch 3 #3): advance during a run. After
            # Finished (Batch 3 #8): an edit-save STAYS on the site edit
            # form with the saved statement — the company-save pattern,
            # never the bespoke /site/{id} read page; a create lands on
            # the sites surface (the batch-2 create pattern: Done Today
            # entry above + the list surface).
            adv = chain_advance(con, "site", "Site saved")
            if adv:
                _chain_redirect(handler, adv)
            elif _site_existed:
                handler._redirect(f"/site/{sid}/edit?msg=Site+saved")
            else:
                handler._redirect("/sites?msg=Site+saved")
    elif u.path == "/wo/save":
            wid = data.get("wo_id") or None
            # Void-and-revise (build 'ab', Jason 2026-10-26): an
            # existing Work Order never saves in place — except a
            # fresh revision completing under its session marker.
            _wo_session = False
            if wid and con.execute(
                    "SELECT 1 FROM work_orders WHERE wo_id=?",
                    (wid,)).fetchone():
                if not engine.revision_pending(
                        con, "wo", engine.doc_key(con, "wo", wid)):
                    raise ValueError(
                        f"Work Order {wid} is posted — revise it "
                        f"(Edit on its form) to change it")
                _wo_session = True
                _wo_new = (data.get("wo_rename") or "").strip()
                if _wo_new and _wo_new != wid:
                    engine.validate_new_doc_no(
                        con, "work_orders", "wo_id", _wo_new,
                        "work order")
                    con.execute("UPDATE work_orders SET wo_id=? "
                                "WHERE wo_id=?", (_wo_new, wid))
                    con.commit()
                    wid = _wo_new
            # Line rows: indexed item0..item7 (Add Item clones), with a
            # fallback to the legacy unindexed names. One WO with many
            # lines (2026-10-15): every non-blank row becomes a line
            # item on the single WO; the bill is the sum of the lines.
            # A row is blank when item + description are empty and
            # qty/cost are untouched defaults.
            rows = []
            if any(f"item{i}" in data for i in range(8)):
                for i in range(8):
                    rows.append({
                        "item": data.get(f"item{i}") or "",
                        "description": data.get(f"description{i}") or "",
                        "category": data.get(f"type{i}") or "",
                        "qty": data.get(f"qty{i}") or 1,
                        "cost": data.get(f"cost{i}") or 0,
                        "uom": data.get(f"uom{i}") or "",
                    })
            else:
                rows.append({
                    "item": data.get("item") or "",
                    "description": data.get("description") or "",
                    "category": data.get("type") or "",
                    "qty": data.get("qty") or 1,
                    "cost": data.get("cost") or 0,
                    "uom": data.get("uom") or "",
                })

            def _blank(r):
                try:
                    q = float(r["qty"])
                except (TypeError, ValueError):
                    q = 0
                try:
                    c = float(r["cost"])
                except (TypeError, ValueError):
                    c = 0
                return (not (r["item"] or "").strip()
                        and not (r["description"] or "").strip()
                        and q in (0, 1) and c == 0)

            header = {
                "asset_id": data.get("asset_id"),
                "ticket_id": data.get("ticket_id"),
                "customer_id": data.get("customer_id"),
                "charge_to": data.get("charge_to") or "internal",
                "work_type": data.get("work_type"),
                "vendor": data.get("vendor"),
                "open_date": data.get("open_date"),
                "close_date": data.get("close_date"),
                "labor": data.get("labor"),
                "parts": data.get("parts"),
                "other_cost": data.get("other_cost"),
                "status": data.get("status"),
                "warranty": data.get("warranty") == "1",
                "yard_or_site": data.get("yard_or_site"),
                "notes": data.get("notes"),
                "quote_no": data.get("quote_no") or "",
                "ref_ticket": data.get("ref_ticket") or "",
                "wo_date": data.get("wo_date") or "",
                # PO from the Job Info popup (2026-10-15): previously
                # read by nothing, so a PO typed on a WO was lost.
                "po": data.get("po") or "",
            }
            lines = [r for r in rows if not _blank(r)]
            # The WO's own description is the first line's description
            # (the form has no separate header Description field — the
            # old code smuggled it in via the row dict).
            desc = next((r["description"] for r in lines
                         if (r["description"] or "").strip()), "")
            _wo_existed = bool(wid and con.execute(
                "SELECT 1 FROM work_orders WHERE wo_id=?", (wid,)).fetchone())
            wid = engine.save_wo(con, dict(header, description=desc,
                                           lines=lines), wid)
            if _wo_session:
                engine.clear_revision_pending(
                    con, "wo", engine.doc_key(con, "wo", wid))
            if not _wo_existed:
                engine.add_done_manual(
                    con, f"Created work order {wid}", f"/summary/wo/{wid}",
                    handler.desk(con))
            up = (handler._files or {}).get("wo_upload")
            if up and up[2]:
                engine.save_job_attachment(con, "wo", wid, up[0], up[2], handler.desk(con))
            handler._redirect(f"/ticket/new?kind=workorder&msg=Work+order+saved&new={wid}")
    else:
        return False
    return True
