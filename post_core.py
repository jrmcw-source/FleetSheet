"""FleetSheet POST actions — core desk/session actions: PIN, devices, setup, backup/restore, yard-device posts."""
import html
import os
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

import engine
from urllib.parse import quote_plus

from views_core import (
    PIN_MAX_FAILS,
    _pin_fail_state,
    _pin_note_fail,
    _pin_reset,
    next_setup_step,
)


def handle_post(handler, con, data, u):
    """Handle one POST. Returns True when the path was handled."""
    if u.path == "/sale/save":
        # Equipment sale (Jason 2026-10-07).
        try:
            sale_id = engine.create_sale(
                con,
                (data.get("asset_id") or "").strip(),
                (data.get("customer_id") or "").strip(),
                (data.get("sale_date") or "").strip(),
                float(data.get("amount") or 0),
                (data.get("notes") or "").strip(),
                (data.get("clerk") or "").strip(),
                int(data.get("qty") or 1),
                (data.get("condition") or "").strip(),
                (data.get("sale_id") or "").strip() or None,
                (data.get("ref_no") or "").strip(),
                (data.get("item_desc") or "").strip(),
            )
            up = (handler._files or {}).get("job_attach")
            if up and up[2]:
                engine.save_job_attachment(con, "sale", sale_id, up[0], up[2], data.get("clerk", ""))
            handler._redirect(f"/sale?msg=Sale+{sale_id}+recorded")
        except Exception as e:
            handler._redirect("/sale?err=" + __import__("urllib.parse").parse.quote_plus(str(e)[:120]))
        return True
    if u.path == "/rentals/checkinout":
        # Rentals sub-tab check in/out: save condition + move status.
        tid = (data.get("ticket_id") or "").strip()
        direction = (data.get("direction") or "").strip()
        try:
            if direction == "out":
                engine.save_ticket_condition(con, tid, "out", data)
                engine.set_status(con, tid, "Dispatched", None, data.get("clerk"))
                engine.add_done_manual(con, f"Checked out {tid}", f"/ticket/{tid}",
                                       (data.get("clerk") or "").strip()[:40])
            elif direction == "in":
                engine.save_ticket_condition(con, tid, "in", data)
                engine.set_status(con, tid, "Off Rent", None, data.get("clerk"))
                engine.add_done_manual(con, f"Checked in {tid}", f"/ticket/{tid}",
                                       (data.get("clerk") or "").strip()[:40])
            else:
                raise ValueError("Pick in or out")
            handler._redirect("/ticket/new?kind=checkinout&msg=" + quote_plus("Saved"))
        except (ValueError, TypeError) as e:
            handler._redirect("/ticket/new?kind=checkinout&err=" + quote_plus(str(e)))
        return True
    if u.path == "/rentals/complete":
        # Rentals sub-tab "Completed" toggle: explicit hand-logged done entry.
        kind = (data.get("kind") or "").strip()[:40]
        label = (data.get("label") or kind).strip()[:60]
        nxt = data.get("next") or "/ticket/new"
        if not nxt.startswith("/") or nxt.startswith("//"):
            nxt = "/ticket/new"
        completed = data.get("completed") == "1"
        engine.set_option(con, f"rentals_complete_{kind}", "1" if completed else "")
        if completed:
            engine.add_done_manual(con, f"{label} completed",
                                   f"/ticket/new?kind={kind}",
                                   (data.get("clerk") or "").strip()[:40])
        handler._redirect(nxt)
        return True
    if u.path == "/pin":
            ip = handler.client_address[0]
            fails, wait = _pin_fail_state(ip)
            nxt = data.get("next") or "/invoices"
            if not nxt.startswith("/") or nxt.startswith("//"):
                nxt = "/invoices"
            if fails >= PIN_MAX_FAILS:
                handler._redirect("/pin?next=" + quote_plus(nxt) +
                               "&err=" + quote_plus(
                                   f"Too many wrong tries — wait {wait // 60 + 1} min."))
            elif engine.verify_pin(con, data.get("pin") or ""):
                _pin_reset(ip)
                handler._redirect(nxt, cookie=handler._pin_issue(con))
            else:
                _pin_note_fail(ip)
                handler._redirect("/pin?next=" + quote_plus(nxt) + "&err=Wrong+PIN")
    elif u.path == "/alert/ack":
            # News-strip shoulder-tap: snooze (default 3h) or dismiss
            # (default 7d), durations adjustable per tap before pushing.
            # Dismiss kills the instance, not the condition — the tap returns
            # if the underlying problem is still true when the ack expires.
            key = (data.get("key") or "").strip()[:120]
            action = data.get("action") or ""
            nxt = data.get("next") or "/"
            if not nxt.startswith("/") or nxt.startswith("//"):
                nxt = "/"
            try:
                hours = int(data.get("hours") or 3)
            except (TypeError, ValueError):
                hours = 3
            try:
                minutes = int(data.get("minutes") or 0)
            except (TypeError, ValueError):
                minutes = 0
            try:
                days = int(data.get("days") or 7)
            except (TypeError, ValueError):
                days = 7
            if key and action in ("snooze", "dismiss"):
                try:
                    engine.ack_alert(con, key, action, hours=hours, days=days,
                                     minutes=minutes or None)
                except ValueError:
                    pass
            elif action == "clear":
                # Ticker Clear: dismiss every listed key for the rest of the day.
                for k in (data.get("keys") or "").split(","):
                    k = k.strip()[:120]
                    if k:
                        try:
                            engine.ack_alert(con, k, "dismiss", days=1)
                        except ValueError:
                            pass
            handler._redirect(nxt)
    elif u.path == "/ticker/cats":
        # Ticker category filter: which kinds of shoulder-taps earn a slot.
        # Checkboxes post only when checked; absent = off. (2026-10-06)
        nxt = data.get("next") or "/"
        if not nxt.startswith("/") or nxt.startswith("//"):
            nxt = "/"
        cats = {c for c in engine.TICKER_CATS if data.get(f"cat_{c}")}
        engine.set_ticker_cats(con, cats)
        handler._redirect(nxt + ("&" if "?" in nxt else "?") +
                          "msg=" + quote_plus("Ticker filter saved"))
    elif u.path == "/today/task/add":
            text = (data.get("text") or "").strip()
            tier = data.get("tier") or "can"
            try:
                engine.add_task(con, text, tier)
            except ValueError:
                pass
            handler._redirect("/")
            return
    elif u.path == "/today/task/from":
            # From an audit row: make a linked task, user picks the tier.
            text = (data.get("text") or "").strip()[:200]
            tier = data.get("tier") or "can"
            link = (data.get("link") or "").strip()[:200]
            back = (data.get("back") or "/").strip()
            if not back.startswith("/"):
                back = "/"
            try:
                engine.add_task(con, text, tier, link)
            except ValueError:
                pass
            handler._redirect(back)
            return
    elif u.path == "/today/task/done":
            try:
                engine.complete_task(con, int(data.get("task_id") or 0),
                                     (data.get("clerk") or "").strip()[:40])
            except (ValueError, TypeError):
                pass
            back = (data.get("back") or "/").strip()
            if not back.startswith("/"):
                back = "/"
            handler._redirect(back)
            return
    elif u.path == "/today/task/undone":
            try:
                engine.uncomplete_task(con, int(data.get("task_id") or 0))
            except (ValueError, TypeError):
                pass
            back = (data.get("back") or "/").strip()
            if not back.startswith("/"):
                back = "/"
            handler._redirect(back)
            return
    elif u.path == "/today/sticky/add":
            # Quiet desk reminder — free text, no date, no tier. Never taps.
            try:
                engine.add_sticky(con, data.get("text") or "")
            except ValueError:
                pass
            handler._redirect("/")
            return True
    elif u.path == "/today/sticky/edit":
            try:
                engine.edit_sticky(con, int(data.get("sticky_id") or 0),
                                   data.get("text") or "")
            except (ValueError, TypeError):
                pass
            handler._redirect("/")
            return True
    elif u.path == "/today/sticky/remove":
            try:
                engine.remove_sticky(con, int(data.get("sticky_id") or 0))
            except (ValueError, TypeError):
                pass
            handler._redirect("/")
            return True
    elif u.path == "/today/sticky/update":
            try:
                sid = int(data.get("sticky_id") or 0)
                fields = {}
                if data.get("priority") in ("0", "1", "2"):
                    fields["priority"] = int(data["priority"])
                if data.get("color") in ("yellow", "pink", "green", "blue"):
                    fields["color"] = data["color"]
                if data.get("snooze_hours"):
                    try:
                        hrs = max(1, min(72, int(data["snooze_hours"])))
                        fields["snoozed_until"] = (
                            datetime.now() + timedelta(hours=hrs)).isoformat(sep=" ", timespec="seconds")
                    except (ValueError, TypeError):
                        pass
                if data.get("hide_until"):
                    fields["hide_until"] = data["hide_until"].replace("T", " ")[:16]
                if data.get("pinned") in ("0", "1"):
                    fields["pinned"] = int(data["pinned"])
                if data.get("dismissed") == "1":
                    fields["dismissed"] = 1
                engine.update_sticky(con, sid, **fields)
            except (ValueError, TypeError):
                pass
            handler._redirect("/")
            return True
    elif u.path == "/today/sticky/done":
            try:
                engine.done_sticky(con, int(data.get("sticky_id") or 0),
                                   data.get("clerk") or "")
            except (ValueError, TypeError):
                pass
            handler._redirect("/?msg=Note+done")
            return True
    elif u.path == "/today/done/other":
            # Hand-logged "Other done" entry — explicit completion, nothing inferred.
            # Lands back on the page that opened the pop-up.
            try:
                engine.add_done_manual(con, data.get("text") or "",
                                       data.get("link") or "", data.get("clerk") or "")
            except ValueError:
                pass
            back = (data.get("back") or "/").strip()
            if not back.startswith("/"):
                back = "/"
            handler._redirect(back)
            return
    elif u.path == "/today/done/other/remove":
            try:
                engine.remove_done_manual(con, int(data.get("entry_id") or 0))
            except (ValueError, TypeError):
                pass
            back = (data.get("back") or "/").strip()
            if not back.startswith("/"):
                back = "/"
            handler._redirect(back)
            return
    elif u.path == "/today/money/done":
            key = (data.get("key") or "").strip()[:120]
            if key:
                engine.advance_money_slot(con, key)
            handler._redirect("/")
            return
    elif u.path == "/pin/logout":
            handler._redirect("/pin?msg=" + quote_plus("Money pages locked on this browser"),
                           cookie=f"{handler.PIN_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0")
    elif u.path == "/pin/forgot/questions":
            # Security answers are low-entropy: same throttling as PIN tries.
            ip = handler.client_address[0]
            fails, wait = _pin_fail_state(ip)
            if fails >= PIN_MAX_FAILS:
                handler._redirect("/pin/forgot?err=" + quote_plus(
                    f"Too many wrong tries — wait {wait // 60 + 1} min."))
            elif engine.verify_pin_security(con, data.get("sa1") or "",
                                            data.get("sa2") or ""):
                _pin_reset(ip)
                engine.clear_pin(con)
                handler._redirect("/setup/security?msg=" + quote_plus(
                    "PIN cleared — set a new one below"))
            else:
                _pin_note_fail(ip)
                handler._redirect("/pin/forgot?err=Wrong+answers")
    elif u.path == "/setup/security/pin":
            mode = data.get("mode")
            pin1 = (data.get("pin1") or "").strip()
            pin2 = (data.get("pin2") or "").strip()
            if engine.pin_is_set(con):
                if mode != "change" or not engine.verify_pin(con, data.get("cur") or ""):
                    handler._redirect("/setup/security?err=Current+PIN+wrong")
                    return
            elif mode != "set":
                handler._redirect("/setup/security?err=No+PIN+set+yet")
                return
            if pin1 != pin2:
                handler._redirect("/setup/security?err=PINs+do+not+match")
                return
            if mode == "set":
                # Fresh PIN: security questions are required so a lost
                # recovery code never means a lockout. Validate BEFORE
                # set_pin — a failed validation must not leave a PIN
                # with no recovery questions stored.
                try:
                    q1 = int(data.get("sq1") or "0")
                    q2 = int(data.get("sq2") or "1")
                    sa1 = data.get("sa1") or ""
                    sa2 = data.get("sa2") or ""
                    engine.validate_pin_security(q1, sa1, q2, sa2)
                except (ValueError, TypeError) as e:
                    handler._redirect("/setup/security?err=" + quote_plus(str(e)))
                    return
            try:
                rec = engine.set_pin(con, pin1)
            except ValueError as e:
                handler._redirect("/setup/security?err=" + quote_plus(str(e)))
                return
            if mode == "set":
                engine.set_pin_security(con, q1, sa1, q2, sa2)
            # Whoever just set/changed the PIN proved they know it — unlock this browser.
            # Fresh setups land on the dashboard. The recovery code is NOT shown
            # after a fresh PIN set: security questions are required at setup,
            # so the code is redundant (Jason 2026-10-06). The welcome flow
            # passes next=/ so onboarding lands back on the dashboard.
            nxt = (data.get("next") or "").strip()
            if nxt.startswith("/") and not nxt.startswith("//"):
                dest = nxt
                dest_qs = "?"
            elif mode == "set":
                # Setup flow (Jason 2026-10-08): a fresh PIN set during initial
                # setup advances to the next step; otherwise go to the dashboard.
                flow_next = next_setup_step(con, "/setup/security")
                dest = flow_next if flow_next else "/"
                dest_qs = "?from=setup&" if flow_next else "?"
            else:
                dest = "/setup/security"
                dest_qs = "?"
            if mode == "set":
                handler._redirect(dest + dest_qs + "msg=" + quote_plus("Desk PIN set"),
                                  cookie=handler._pin_issue(con))
            else:
                handler._redirect(dest + "?recovery=" + quote_plus(rec) +
                                  "&msg=" + quote_plus("Desk PIN set"),
                                  cookie=handler._pin_issue(con))
    elif u.path == "/setup/security/questions":
            if not engine.pin_is_set(con):
                handler._redirect("/setup/security?err=No+PIN+set+yet")
                return
            if not engine.verify_pin(con, data.get("cur") or ""):
                handler._redirect("/setup/security?err=Current+PIN+wrong")
                return
            try:
                q1 = int(data.get("sq1") or "0")
                q2 = int(data.get("sq2") or "1")
                engine.set_pin_security(con, q1, data.get("sa1") or "",
                                        q2, data.get("sa2") or "")
            except (ValueError, TypeError) as e:
                handler._redirect("/setup/security?err=" + quote_plus(str(e)))
                return
            handler._redirect("/setup/security?msg=" + quote_plus(
                "Security questions saved"))
    elif u.path == "/setup/devices/issue":
            base = (data.get("base_url") or "").strip().rstrip("/")
            if base:
                engine.set_option(con, "device_base_url", base)
            dev = engine.issue_device(con, data.get("label"), data.get("days") or 90,
                                      data.get("clerk"))
            handler._redirect(f"/setup/devices/show?token={dev['token']}&msg=Device+code+issued")
    elif u.path == "/setup/devices/revoke":
            engine.revoke_device(con, data.get("token") or "")
            handler._redirect("/setup/devices?msg=Device+revoked")
    elif u.path == "/setup/devices/rotate":
            new = engine.rotate_device(con, data.get("token") or "", 90, data.get("clerk"))
            handler._redirect(f"/setup/devices/show?token={new['token']}&msg=Code+rotated")
    elif u.path == "/setup/devices/done":
            # First-time setup complete (Jason 2026-10-08): mark devices done,
            # show acknowledgement, then Today.
            engine.set_option(con, "setup_devices_done", "1")
            con.commit()
            handler._redirect("/setup/complete")
    elif u.path.startswith("/d/ticket/") and u.path.endswith("/condition"):
            dev, reason = handler._device(con)
            if not dev:
                handler._send(handler._device_denied(reason), 403)
                return
            tid = u.path.split("/")[3]
            side = data.get("side") or ""
            engine.save_ticket_condition(con, tid, side, {
                "condition": data.get("condition"),
                "note": data.get("note"),
                "meter": data.get("meter"),
                "clerk": data.get("clerk"),
                "source": "yard",
            })
            up = (handler._files or {}).get("photo")
            if up and up[2]:
                engine.save_ticket_photo(con, tid, side, up[2], up[0])
            handler._redirect(f"/d/ticket/{tid}?msg=Condition+saved")
    elif u.path.startswith("/d/ticket/") and u.path.endswith("/status"):
            dev, reason = handler._device(con)
            if not dev:
                handler._send(handler._device_denied(reason), 403)
                return
            tid = u.path.split("/")[3]
            want = data.get("status") or ""
            if want not in handler.DEVICE_STATUSES:
                raise ValueError("That move is desk-only")
            engine.set_status(con, tid, want, data.get("off_rent") or None, data.get("clerk"))
            handler._redirect(f"/d/ticket/{tid}?msg=Status+updated")
    elif u.path == "/setup":
            # Money is always .00 — waiver_pct/env_pct have no UI and are
            # ignored here. Legacy `address`/`phone` columns stay untouched.
            con.execute(
                """UPDATE company SET name=?, dba=?, addr_street=?, addr_street2=?, addr_city=?,
                   addr_state=?, addr_zip=?, phys_street=?, phys_street2=?, phys_city=?,
                   phys_county=?, phys_state=?, phys_zip=? WHERE id=1""",
                (
                    data["name"], data.get("dba"),
                    data.get("addr_street") or "", data.get("addr_street2") or "",
                    data.get("addr_city") or "",
                    data.get("addr_state") or "", data.get("addr_zip") or "",
                    data.get("phys_street") or "", data.get("phys_street2") or "",
                    data.get("phys_city") or "", data.get("phys_county") or "",
                    data.get("phys_state") or "", data.get("phys_zip") or "",
                ),
            )
            # Company logo for the header brand (optional image upload).
            up = (handler._files or {}).get("company_logo")
            if up and up[2]:
                _fname, _ctype, _blob = up
                if not (_ctype or "").startswith("image/"):
                    raise ValueError("Logo must be an image file")
                if len(_blob) > 512 * 1024:
                    raise ValueError("Logo too large — 512 KB max")
                import base64
                engine.set_option(con, "company_logo",
                                  base64.b64encode(_blob).decode("ascii"))
                engine.set_option(con, "company_logo_mime", _ctype)
            elif data.get("remove_logo") == "1":
                engine.set_option(con, "company_logo", "")
                engine.set_option(con, "company_logo_mime", "")
            con.commit()
            # Setup flow (Jason 2026-10-08): during initial setup, saving
            # advances to the next step; after setup, stay on the page.
            nxt = next_setup_step(con, "/setup")
            if nxt:
                handler._redirect(nxt + "?from=setup&msg=" + quote_plus("Company setup saved"))
            else:
                handler._redirect("/setup?saved=1&msg=" + quote_plus("Company setup saved"))
    elif u.path == "/setup/billing":
            con.execute("UPDATE company SET invoice_prefix=?, billing_email=?, default_terms=?, min_days=?, bill_both_dates=? WHERE id=1",
                        (data.get("invoice_prefix") or "INV", data.get("billing_email") or "", data.get("default_terms") or "Net 30", int(data.get("min_days") or 1), 1 if data.get("bill_both_dates") == "1" else 0))
            try:
                engine.set_option(con, "quote_valid_days", str(max(1, int(data.get("quote_valid_days") or 30))))
            except (TypeError, ValueError):
                engine.set_option(con, "quote_valid_days", "30")
            con.commit()
            engine.set_option(con, "setup_billing_done", "1")
            nxt = next_setup_step(con, "/setup/billing")
            if nxt:
                handler._redirect(nxt + "?from=setup&msg=" + quote_plus("Billing settings saved"))
            else:
                handler._redirect("/setup/billing?msg=" + quote_plus("Billing settings saved"))
    elif u.path == "/setup/admin":
            con.execute("UPDATE company SET backup_dir=? WHERE id=1", (data.get("backup_dir") or "",))
            con.commit()
            engine.set_option(con, "setup_admin_done", "1")
            nxt = next_setup_step(con, "/setup/admin")
            if nxt:
                handler._redirect(nxt + "?from=setup&msg=" + quote_plus("Backup settings saved"))
            else:
                handler._redirect("/setup/admin?msg=" + quote_plus("Backup settings saved"))
    elif u.path == "/backup":
            dest = engine.run_backup(con, data.get("clerk") or "")
            handler._redirect("/?msg=" + quote_plus(
                f"Backup {dest.name} (book + photos)"))
    elif u.path == "/backup/schedule":
            engine.set_backup_schedule(con, data.get("schedule"),
                                       data.get("every_days"))
            con.commit()
            handler._redirect("/backup?msg=" + quote_plus("Backup schedule saved"))
    elif u.path == "/backup/restore":
            if data.get("confirm") != "yes":
                raise ValueError("Restore needs the confirmation checkbox")
            up = (handler._files or {}).get("backup_file")
            if not up or not up[2]:
                raise ValueError("Choose a backup file to restore")
            fname, _ctype, blob = up
            is_archive = str(fname or "").lower().endswith(".zip")
            suffix = ".zip" if is_archive else ".db"
            tmp = Path(tempfile.gettempdir()) / (
                f"fleetsheet-restore-{os.getpid()}{suffix}")
            tmp.write_bytes(blob)
            try:
                if is_archive:
                    snap = engine.restore_backup_archive(
                        con, tmp, data.get("clerk") or "")
                else:
                    snap = engine.restore_backup(
                        con, tmp, data.get("clerk") or "")
            finally:
                try:
                    tmp.unlink()
                except OSError:
                    pass
            handler._redirect("/backup?msg=" + quote_plus(
                f"Backup restored. Safety snapshot kept as {snap.name}"))
    elif u.path == "/setup/phones/add":
            # No "main" toggle (Jason 2026-10-06): label it "Main" and it IS
            # the main; the first number added is also auto-main in the engine.
            lbl = (data.get("label") or "").strip()
            try:
                engine.add_company_phone(con, lbl, data.get("number") or "",
                                         make_main=lbl.lower() == "main")
                handler._redirect("/setup?edit=1&msg=" + quote_plus("Phone saved"))
            except ValueError as e:
                handler._redirect("/setup?edit=1&err=" + quote_plus(str(e)))
    elif u.path == "/setup/phones/del":
            try:
                engine.del_company_phone(con, int(data.get("phone_id") or 0))
            except (ValueError, TypeError):
                pass
            handler._redirect("/setup?edit=1&msg=" + quote_plus("Phone removed"))
    elif u.path == "/setup/crew":
            # Crew name is entered as parts (Jason 2026-10-06) and stored as
            # one display string: "First M. Last Suffix".
            parts = [(data.get("crew_first") or "").strip(),
                     (data.get("crew_mi") or "").strip(),
                     (data.get("crew_last") or "").strip(),
                     (data.get("crew_suffix") or "").strip()]
            engine.add_crew(con, " ".join(p for p in parts if p),
                            data.get("crew_position") or "")
            handler._redirect("/setup?edit=1#crew-entry&msg=" + quote_plus("Crew member saved"))
    elif u.path == "/setup/crew/del":
            engine.drop_crew(con, data.get("crew_name") or "")
            handler._redirect("/setup?edit=1&msg=" + quote_plus("Crew removed"))
    elif u.path == "/setup/vendors":
            try:
                engine.save_vendor(con, data.get("name") or "",
                                   kind=data.get("kind") or "vendor",
                                   phone=data.get("phone") or "",
                                   email=data.get("email") or "",
                                   specialties=data.get("specialties") or "")
                nxt = next_setup_step(con, "/setup/vendors")
                if nxt:
                    handler._redirect(nxt + "?from=setup&msg=" + quote_plus("Vendor saved"))
                else:
                    handler._redirect("/setup/vendors?msg=" + quote_plus("Vendor saved"))
            except ValueError as e:
                handler._redirect("/setup?edit=1&err=" + quote_plus(str(e)))
    elif u.path == "/setup/vendors/del":
            try:
                engine.delete_vendor(con, int(data.get("vendor_id") or 0))
            except (ValueError, TypeError):
                pass
            handler._redirect("/setup/vendors?msg=" + quote_plus("Vendor removed"))
    elif u.path == "/setup/options":
            # Options now lives on the Devices tab; old form posts land there.
            con.execute(
                "UPDATE company SET tooltips=? WHERE id=1",
                (1 if data.get("tooltips") == "1" else 0,),
            )
            con.commit()
            _ts = (data.get("text_size") or "standard").strip().lower()
            engine.set_option(con, "ui_text_size",
                              _ts if _ts in ("standard", "large", "xlarge") else "standard")
            handler._redirect("/setup/devices?msg=" + quote_plus("Options saved"))
    else:
        return False
    return True
