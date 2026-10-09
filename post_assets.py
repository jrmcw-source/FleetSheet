"""FleetSheet POST actions — assets flow: tickets, units, sites, work orders."""
import html
import json
from datetime import date

import engine
from urllib.parse import quote_plus
from views_core import next_setup_step


def handle_post(handler, con, data, u):
    """Handle one POST. Returns True when the path was handled."""
    if u.path == "/ticket/new":
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
            # Haul / deliver typeaheads: exact label/code match wins, otherwise
            # the free text rides along as a note on a sensible default.
            haul_text = (data.get("haul_text") or "").strip()
            haul_by, haul_note = "we", ""
            for h in engine.HAUL_BY:
                if haul_text.lower() in (h, engine.HAUL_LABELS[h].lower()):
                    haul_by = h
                    break
            else:
                if haul_text:
                    haul_by, haul_note = "third_party", haul_text
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
            if not (data.get("asset_id") or "").strip():
                raise ValueError("Pick a unit from the list")
            new_ticket_data = {
                "customer_id": data["customer_id"],
                "site_id": site_id,
                "asset_id": (data.get("asset_id") or "").strip(),
                "job_name": data.get("job_name"),
                "well_or_pad": data.get("well_or_pad"),
                "afe": data.get("afe"),
                "po": data.get("po"),
                "rate_type": data["rate_type"],
                "rate_value": data.get("rate_value") or None,
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
            try:
                # Ensure ref_ticket column exists (Jason 2026-10-07 F5)
                tcols = [r[1] for r in con.execute("PRAGMA table_info(tickets)")]
                if "ref_ticket" not in tcols:
                    con.execute("ALTER TABLE tickets ADD COLUMN ref_ticket TEXT")
                tid = engine.create_ticket(con, new_ticket_data)
                # Save ref_ticket
                if data.get("ref_ticket"):
                    con.execute("UPDATE tickets SET ref_ticket=? WHERE ticket_id=?",
                                ((data.get("ref_ticket") or "").strip(), tid))
                    con.commit()
                # Job info attachment (Jason 2026-10-07)
                up = (handler._files or {}).get("job_attach")
                if up and up[2]:
                    engine.save_job_attachment(con, "ticket", tid, up[0], up[2], data.get("clerk", ""))
                # Ticket upload (Jason 2026-10-07 F5)
                up2 = (handler._files or {}).get("ticket_upload")
                if up2 and up2[2]:
                    engine.save_job_attachment(con, "ticket", tid, up2[0], up2[2], data.get("clerk", ""))
            except engine.SoftReserveConflict as sc:
                # PO soft-reserve: never auto-block. Stash the booking and let
                # the operator pick which reservation wins.
                cur = con.execute(
                    "INSERT INTO pending_bookings (soft_ticket_id, data_json) VALUES (?,?)",
                    (sc.ticket["ticket_id"], json.dumps(new_ticket_data)))
                con.commit()
                handler._redirect(f"/ticket/new?soft_conflict={cur.lastrowid}")
                return True
            handler._redirect(f"/ticket/new?msg=Ticket+saved&new={tid}")
    elif u.path == "/ticket/new/override":
        # Operator picked the new booking over the soft reservation.
        pid = (data.get("pending_id") or "").strip()
        prow = con.execute("SELECT * FROM pending_bookings WHERE pending_id=?", (pid,)).fetchone()
        if not prow:
            handler._redirect("/ticket/new?err=Booking+expired")
            return True
        booking = json.loads(prow["data_json"])
        soft = con.execute(
            "SELECT ticket_id, COALESCE(soft_reserve,0) AS soft_reserve FROM tickets WHERE ticket_id=?",
            (prow["soft_ticket_id"],)).fetchone()
        if soft and soft["soft_reserve"]:
            con.execute("UPDATE tickets SET status='Void' WHERE ticket_id=?", (soft["ticket_id"],))
            unit = con.execute(
                "SELECT unit_no FROM assets WHERE asset_id=?", (booking.get("asset_id"),)).fetchone()
            engine.add_done_manual(
                con, f"Soft reserve {soft['ticket_id']} bumped for new booking"
                     f"{' — ' + unit['unit_no'] if unit else ''}",
                f"/ticket/{soft['ticket_id']}", (data.get("clerk") or "").strip()[:40])
        tid = engine.create_ticket(con, booking)
        con.execute("DELETE FROM pending_bookings WHERE pending_id=?", (pid,))
        con.commit()
        handler._redirect(f"/ticket/new?msg=Ticket+saved&new={tid}")
    elif u.path == "/ticket/new/cancel":
        # Operator kept the existing soft reservation.
        pid = (data.get("pending_id") or "").strip()
        con.execute("DELETE FROM pending_bookings WHERE pending_id=?", (pid,))
        con.commit()
        handler._redirect("/ticket/new")
    elif u.path.startswith("/ticket/") and u.path.endswith("/transport"):
            tid = u.path.split("/")[2]
            engine.update_ticket_transport(con, tid, {
                "haul_by": data.get("haul_by"),
                "deliver_to": data.get("deliver_to"),
                "tax_loc_id": data.get("tax_loc_id"),
                "transport_fee": data.get("transport_fee") or 0,
                "mob": data.get("mob") or 0,
                "demob": data.get("demob") or 0,
            })
            handler._redirect(f"/ticket/{tid}?msg=Transport+saved")
    elif u.path.startswith("/ticket/") and u.path.endswith("/status"):
            tid = u.path.split("/")[2]
            engine.set_status(con, tid, data["status"], data.get("off_rent") or None, data.get("clerk"))
            handler._redirect(f"/ticket/{tid}?msg=Status+updated")
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
                "clerk": data.get("clerk"),
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
                "notes": data.get("notes"),
            }, aid_in)
            if not aid_in:
                # New unit: the operator explicitly did something — log it so
                # it shows in the Done box. Edits are not logged.
                unit_no = (data.get("unit_no") or "").strip()
                desc = (data.get("description") or "").strip()
                engine.add_done_manual(
                    con, f"Added unit {unit_no} — {desc}"[:200],
                    f"/unit/{aid}", data.get("clerk") or "")
            handler._redirect(f"/units?msg=Unit+saved")
    elif u.path == "/site/save":
            sid = data.get("site_id") or None
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
            # Setup flow (Jason 2026-10-08): during initial setup, saving
            # advances to the next step; after setup, stay on the page.
            nxt = next_setup_step(con, "/sites")
            if nxt:
                handler._redirect(nxt + "?from=setup&msg=Site+saved")
            else:
                handler._redirect(f"/site/{sid}?msg=Site+saved")
    elif u.path == "/wo/save":
            wid = data.get("wo_id") or None
            wid = engine.save_wo(con, {
                "asset_id": data.get("asset_id"),
                "ticket_id": data.get("ticket_id"),
                "customer_id": data.get("customer_id"),
                "charge_to": data.get("charge_to") or "internal",
                "work_type": data.get("work_type"),
                "description": data.get("description"),
                "vendor": data.get("vendor"),
                "open_date": data.get("open_date"),
                "close_date": data.get("close_date"),
                "labor": data.get("labor"),
                "parts": data.get("parts"),
                "other_cost": data.get("other_cost"),
                "bill_amount": data.get("bill_amount"),
                "status": data.get("status"),
                "warranty": data.get("warranty") == "1",
                "yard_or_site": data.get("yard_or_site"),
                "notes": data.get("notes"),
                "quote_no": data.get("quote_no") or "",
                "ref_ticket": data.get("ref_ticket") or "",
                "wo_date": data.get("wo_date") or "",
                "item": data.get("item") or "",
                "qty": data.get("qty") or 1,
                "cost": data.get("cost") or 0,
            }, wid)
            up = (handler._files or {}).get("wo_upload")
            if up and up[2]:
                engine.save_job_attachment(con, "wo", wid, up[0], up[2], data.get("clerk", ""))
            handler._redirect(f"/ticket/new?kind=workorder&msg=Work+order+saved&new={wid}")
    elif u.path == "/po/ack":
        po_no = data.get("po_no") or ""
        engine.ack_po_record(con, data.get("customer_id") or "", po_no,
                             data.get("clerk") or "")
        # Walkthrough #3 (A5): acknowledging a PO is a real completion —
        # it must land in Done-today, not vanish.
        unit = ""
        prow = con.execute("SELECT asset_id FROM purchase_orders WHERE po_no=?",
                           (po_no,)).fetchone()
        if prow and prow["asset_id"]:
            u = con.execute("SELECT unit_no FROM assets WHERE asset_id=?",
                            (prow["asset_id"],)).fetchone()
            unit = f" — {u['unit_no']}" if u else ""
        engine.add_done_manual(con, f"PO acknowledged{unit} — unit reserved",
                               "", (data.get("clerk") or "").strip()[:40])
        handler._redirect("/assets?msg=PO+acknowledged")
    else:
        return False
    return True
