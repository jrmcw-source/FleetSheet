"""FleetSheet POST actions — core desk/session actions: PIN, devices, setup, backup/restore, yard-device posts."""
import html
import os
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

import engine
import re as _re
import urllib.request as _urlreq
from urllib.parse import quote_plus

from views_core import (
    PIN_MAX_FAILS,
    _pin_fail_state,
    _pin_note_fail,
    _pin_reset,
    next_setup_step,
    chain_advance,
    setup_chain,
    enabled_values,
    ENABLED_CORES,
    page,
)


def _desk_name(handler, con):
    """The desk-session identity (Batch 3 #13): stamped silently at
    write time, never asked on a form. Same source Wave 1B used in
    post_accounting (handler.desk)."""
    try:
        return (handler.desk(con) or "").strip()[:40]
    except Exception:
        return ""


def _rerender(handler, con, title, path, body, err=""):
    """Re-render a page in place after a failed POST (Batch 3 #1):
    the operator stays on the page they were on, the error is stated
    on that page, and the view is built from the posted values so
    what they typed survives. `err` renders as the page's error
    banner; pass err="" when the view renders its own error box
    (Welcome, Forgot PIN). PIN fields themselves are never
    re-populated — they stay blank for hygiene; every other entry
    (security answers included) is retained."""
    co = handler.company(con)
    name = (co["dba"] or co["name"]) if co else "FleetSheet"
    flash = f'<div class="err">{html.escape(err)}</div>' if err else ""
    handler._send(page(title, flash + body, name, path))


def _chain_redirect(handler, adv):
    """Redirect to a chain advance target, carrying its step message."""
    sep = "&" if "?" in adv[0] else "?"
    handler._redirect(adv[0] + sep + "from=setup&msg=" + quote_plus(adv[1]))


def _post_sale_save(handler, con, data, u):
    try:
        # Line rows (2026-10-16): row 0 uses bare names, Add Item clones
        # use suffixed names (asset_id1, ...). Each non-blank row becomes
        # its own sale record sharing the header — selling two units =
        # two sales, same customer/date. A row is blank when it names no
        # asset and carries no description or price.
        def _row_sale(i):
            suf = "" if i == 0 else str(i)
            aid = (data.get(f"asset_id{suf}") or "").strip()
            desc = (data.get(f"item_desc{suf}") or "").strip()
            amt = (data.get(f"amount{suf}") or "").strip()
            if not aid and not desc and not amt:
                return None
            if not aid:
                raise ValueError("Pick a unit from the list")
            return {
                "asset_id": aid,
                "qty": int(data.get(f"qty{suf}") or 1),
                "amount": float(amt or 0),
                "item_desc": desc,
            }
        rows = []
        for _i in range(8):
            _r = _row_sale(_i)
            if _r is not None:
                rows.append(_r)
        if not rows:
            raise ValueError("Pick a unit from the list")
        # One line per unit; pre-check before creating anything so a
        # mid-loop failure never leaves a partial multi-unit sale.
        _seen = set()
        _plant_units = []
        _fleet_units = []
        for _r in rows:
            if _r["asset_id"] in _seen:
                _uno = con.execute("SELECT unit_no FROM assets WHERE asset_id=?",
                                   (_r["asset_id"],)).fetchone()
                raise ValueError(
                    f"Unit {_uno['unit_no'] if _uno else _r['asset_id']} is listed twice — one line per unit")
            _seen.add(_r["asset_id"])
            _a = con.execute("SELECT unit_no, sold_date, COALESCE(designation,'Fleet') AS designation FROM assets WHERE asset_id=?",
                             (_r["asset_id"],)).fetchone()
            if not _a:
                raise ValueError(f"Unknown unit {_r['asset_id']}")
            if _a["sold_date"]:
                raise ValueError(f"Unit {_a['unit_no']} is already sold")
            if _a["designation"] == "Plant":
                _plant_units.append(_a["unit_no"])
            elif _a["designation"] == "Fleet":
                _fleet_units.append(_a["unit_no"])
        # Plant-sale double check (Jason 2026-10-24): a Plant (fixed)
        # asset may be sold, but only deliberately — the form's
        # "Confirm Plant sale" check must be set. Plain explicit
        # confirm; the sale flow carries no override mechanism of its
        # own to ride. A confirmed Plant sale is stamped on the sale
        # record's notes.
        if _plant_units and data.get("plant_confirm") != "1":
            raise ValueError(
                f"Plant asset {', '.join(_plant_units)} is a fixed asset — "
                "check Confirm Plant sale on the form to proceed")
        # Fleet-sale double check (Jason 2026-10-24, same day, the
        # amendment): the same deliberate passage for a Fleet (rental)
        # unit — long-rent customers do buy the unit mid-rental. Its
        # own flag, its own stamp, mirroring Plant exactly. Stock and
        # the operator's own designations sell with no confirm.
        if _fleet_units and data.get("fleet_confirm") != "1":
            raise ValueError(
                f"Fleet asset {', '.join(_fleet_units)} is a rental unit — "
                "check Confirm Fleet sale on the form to proceed")
        _customer = (data.get("customer_id") or "").strip()
        _date = (data.get("sale_date") or "").strip()
        _notes = (data.get("notes") or "").strip()
        if _plant_units:
            _notes = ((_notes + " ") if _notes else "") + "Plant sale confirmed."
        if _fleet_units:
            _notes = ((_notes + " ") if _notes else "") + "Fleet sale confirmed."
        # Attribution (Batch 3 #13): the Sale form carries no clerk
        # field — the desk-session identity is stamped here.
        _clerk = handler.desk(con)
        _cond = (data.get("condition") or "").strip()
        _ref = (data.get("ref_no") or "").strip()
        _form_sid = (data.get("sale_id") or "").strip() or None
        ids = []
        for _k, _r in enumerate(rows):
            # Money universality (Jason 2026-10-23): the rows of one
            # submission share a sale group — the first row's sale
            # number — so the sale page can take money against the
            # whole sale or line by line.
            ids.append(engine.create_sale(
                con, _r["asset_id"], _customer, _date, _r["amount"],
                _notes, _clerk, _r["qty"], _cond,
                _form_sid if _k == 0 else None, _ref, _r["item_desc"],
                sale_group=(ids[0] if ids else None),
                plant_confirm=(data.get("plant_confirm") == "1"),
                fleet_confirm=(data.get("fleet_confirm") == "1")))
        up = (handler._files or {}).get("job_attach")
        if up and up[2]:
            engine.save_job_attachment(con, "sale", ids[0], up[0], up[2], handler.desk(con))
        if len(ids) == 1:
            handler._redirect(f"/sale?msg=Sale+{ids[0]}+recorded")
        else:
            handler._redirect(f"/sale?msg={len(ids)}+sales+recorded")
    except Exception as e:
        handler._redirect("/sale?err=" + __import__("urllib.parse").parse.quote_plus(str(e)[:120]))
    return True


def _post_rentals_checkinout(handler, con, data, u):
    tid = (data.get("ticket_id") or "").strip()
    direction = (data.get("direction") or "").strip()
    # Attribution (Batch 3 #13): the check in/out form carries no clerk
    # field — stamp the desk-session identity into the posted data.
    data = dict(data, clerk=handler.desk(con))
    try:
        if direction == "out":
            engine.save_ticket_condition(con, tid, "out", data)
            # FIT refuses dispatch in both condition-switch modes; the
            # form's "Proceed anyway" is the audited override (Jason
            # 2026-10-21: no un-overridable blocks anywhere).
            engine.set_status(con, tid, "Dispatched", None, data.get("clerk"),
                              override_fit=data.get("proceed") == "1")
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


def _post_rentals_complete(handler, con, data, u):
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


def _post_pin(handler, con, data, u):
    ip = handler.client_address[0]
    fails, wait = _pin_fail_state(ip)
    nxt = data.get("next") or "/invoices"
    if not nxt.startswith("/") or nxt.startswith("//"):
        nxt = "/invoices"
    if fails >= PIN_MAX_FAILS:
        # Batch 3 #1: failure stays on the unlock page, error stated.
        _rerender(handler, con, "Desk PIN", "/pin",
                  handler.view_pin(con, {"next": nxt}),
                  f"Too many wrong tries — wait {wait // 60 + 1} min.")
    elif engine.verify_pin(con, data.get("pin") or ""):
        _pin_reset(ip)
        handler._redirect(nxt, cookie=handler._pin_issue(con))
    else:
        _pin_note_fail(ip)
        _rerender(handler, con, "Desk PIN", "/pin",
                  handler.view_pin(con, {"next": nxt}), "Wrong PIN")


def _post_alert_ack(handler, con, data, u):
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
            if action == "dismiss" and data.get("perm") == "1":
                # Permanent dismissal (shop-flow discovery nudge, Jason
                # 2026-10-21): the nudge's Dismiss means never again.
                # A plain dismiss clamps at 90 days, so permanence goes
                # through the explicit-expiry path.
                engine.ack_alert(con, key, action, until_ts=4102444800)
            else:
                engine.ack_alert(con, key, action, hours=hours, days=days,
                                 minutes=minutes or None)
        except ValueError:
            pass
        # The stepper's durable standard (2026-10-17, Jason):
        # the value the operator actually used becomes the
        # standard the steppers open at next time. Only stepper
        # posts teach it (src=stepper) — the hero's Snooze posts
        # the standard itself and must not teach it back.
        if data.get("src") == "stepper":
            if action == "snooze" and minutes:
                engine.set_option(con, "ack_snooze_minutes", str(minutes))
    elif action == "unsnooze" and key:
        # Snoozed-alerts view: bring one alert back now.
        engine.unack_alert(con, key)
    handler._redirect(nxt)


def _post_ticker_cats(handler, con, data, u):
    nxt = data.get("next") or "/"
    if not nxt.startswith("/") or nxt.startswith("//"):
        nxt = "/"
    cats = {c for c in engine.TICKER_CATS if data.get(f"cat_{c}")}
    engine.set_ticker_cats(con, cats)
    handler._redirect(nxt + ("&" if "?" in nxt else "?") +
                      "msg=" + quote_plus("Ticker filter saved"))


def _post_today_task_add(handler, con, data, u):
    text = (data.get("text") or "").strip()
    tier = data.get("tier") or "can"
    try:
        engine.add_task(con, text, tier)
    except ValueError:
        pass
    handler._redirect("/")
    return


def _post_today_task_from(handler, con, data, u):
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


def _post_today_task_done(handler, con, data, u):
    try:
        _tid = int(data.get("task_id") or 0)
    except (ValueError, TypeError):
        _tid = 0
    # Working-style learning, underneath (2026-10-17, Jason): no
    # toggle in the user's face \u2014 the desk watches what he
    # actually completes. Finishing a must-do is a big-first
    # vote; finishing a can-do/later WHILE a must-do task waits
    # is a quick-wins vote (finishing one when nothing big waits
    # says nothing). SLOW on purpose: a side needs a 12-vote
    # lead \u2014 weeks of consistent habit \u2014 and the order can
    # move at most once in 30 days. The desk the user expects
    # is the desk he gets; learning arrives as a tiny change,
    # rarely, until one day it just works like he does.
    try:
        if _tid:
            # Slow fade (2026-10-17, Jason): the same user may
            # change his approach over time \u2014 banked votes
            # must not let a former self outvote the man he is
            # now. One vote per side fades per week of elapsed
            # time, applied lazily here, where learning happens.
            try:
                from datetime import datetime as _dtd, timedelta as _tdd
                _dat = engine.get_option(con, "learn_style_decay_at", "") or ""
                if _dat:
                    _weeks = (_dtd.now() - _dtd.fromisoformat(_dat)).days // 7
                    if _weeks > 0:
                        for _k in ("learn_style_big", "learn_style_quick"):
                            engine.set_option(con, _k, str(max(0,
                                int(engine.get_option(con, _k, "0") or 0) - _weeks)))
                        engine.set_option(con, "learn_style_decay_at",
                                          (_dtd.fromisoformat(_dat)
                                           + _tdd(weeks=_weeks)).isoformat(timespec="seconds"))
                else:
                    engine.set_option(con, "learn_style_decay_at",
                                      _dtd.now().isoformat(timespec="seconds"))
            except Exception:
                pass
            _row = con.execute(
                "SELECT tier FROM today_tasks WHERE task_id = ?",
                (_tid,)).fetchone()
            if _row:
                if _row["tier"] == "must":
                    engine.set_option(con, "learn_style_big", str(
                        int(engine.get_option(con, "learn_style_big", "0") or 0) + 1))
                else:
                    _waiting = con.execute(
                        "SELECT 1 FROM today_tasks WHERE tier = 'must' "
                        "AND done = 0 AND task_id != ? LIMIT 1",
                        (_tid,)).fetchone()
                    if _waiting:
                        engine.set_option(con, "learn_style_quick", str(
                            int(engine.get_option(con, "learn_style_quick", "0") or 0) + 1))
                _big = int(engine.get_option(con, "learn_style_big", "0") or 0)
                _quick = int(engine.get_option(con, "learn_style_quick", "0") or 0)
                _want = None
                if _quick - _big >= 12:
                    _want = "quick"
                elif _big - _quick >= 12:
                    _want = "big"
                if _want and _want != (engine.get_option(
                        con, "today_order", "big") or "big"):
                    _cool = True
                    _last = engine.get_option(con, "learn_style_flip_at", "") or ""
                    if _last:
                        try:
                            from datetime import datetime as _dt
                            _cool = (_dt.now() - _dt.fromisoformat(_last)).days >= 30
                        except ValueError:
                            _cool = True
                    if _cool:
                        from datetime import datetime as _dt2
                        engine.set_option(con, "today_order", _want)
                        engine.set_option(con, "learn_style_flip_at",
                                          _dt2.now().isoformat(timespec="seconds"))
                        engine.set_option(con, "learn_style_big", "0")
                        engine.set_option(con, "learn_style_quick", "0")
    except Exception:
        pass
    try:
        engine.complete_task(con, _tid,
                             (data.get("clerk") or "").strip()[:40])
    except (ValueError, TypeError):
        pass
    back = (data.get("back") or "/").strip()
    if not back.startswith("/"):
        back = "/"
    handler._redirect(back)
    return


def _post_today_task_undone(handler, con, data, u):
    try:
        engine.uncomplete_task(con, int(data.get("task_id") or 0))
    except (ValueError, TypeError):
        pass
    back = (data.get("back") or "/").strip()
    if not back.startswith("/"):
        back = "/"
    handler._redirect(back)
    return


def _post_today_sticky_add(handler, con, data, u):
    try:
        engine.add_sticky(con, data.get("text") or "")
    except ValueError:
        pass
    handler._redirect("/")
    return True


def _post_today_sticky_edit(handler, con, data, u):
    try:
        engine.edit_sticky(con, int(data.get("sticky_id") or 0),
                           data.get("text") or "")
    except (ValueError, TypeError):
        pass
    handler._redirect("/")
    return True


def _post_today_sticky_remove(handler, con, data, u):
    try:
        engine.remove_sticky(con, int(data.get("sticky_id") or 0))
    except (ValueError, TypeError):
        pass
    handler._redirect("/")
    return True


def _post_today_sticky_update(handler, con, data, u):
    try:
        sid = int(data.get("sticky_id") or 0)
        if data.get("snooze") in ("minutes", "pick"):
            try:
                _mins = int(data.get("minutes") or 0)
            except (TypeError, ValueError):
                _mins = 0
            engine.snooze_sticky(con, sid, data["snooze"],
                                 data.get("snooze_until") or "",
                                 minutes=_mins)
            # The sticky stepper teaches the same standard as every
            # other stepper (one standard everywhere).
            if data["snooze"] == "minutes" and _mins:
                engine.set_option(con, "ack_snooze_minutes", str(_mins))
            handler._redirect("/")
            return True
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


def _post_today_sticky_done(handler, con, data, u):
    try:
        engine.done_sticky(con, int(data.get("sticky_id") or 0),
                           data.get("clerk") or "")
    except (ValueError, TypeError):
        pass
    handler._redirect("/?msg=Note+done")
    return True


def _post_today_done_other(handler, con, data, u):
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


def _post_today_done_other_remove(handler, con, data, u):
    try:
        engine.remove_done_manual(con, int(data.get("entry_id") or 0))
    except (ValueError, TypeError):
        pass
    back = (data.get("back") or "/").strip()
    if not back.startswith("/"):
        back = "/"
    handler._redirect(back)
    return


def _post_today_money_done(handler, con, data, u):
    key = (data.get("key") or "").strip()[:120]
    if key:
        engine.advance_money_slot(con, key)
    handler._redirect("/")
    return


def _post_pin_logout(handler, con, data, u):
    handler._redirect("/pin?msg=" + quote_plus("Money pages locked on this browser"),
                   cookie=f"{handler.PIN_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0")


def _post_pin_forgot_questions(handler, con, data, u):
    ip = handler.client_address[0]
    fails, wait = _pin_fail_state(ip)
    # Batch 3 #1: this handler already stayed on its page with the
    # error stated; it now also retains the typed answers (the view
    # renders its own error box, so no banner is added here).
    if fails >= PIN_MAX_FAILS:
        _rerender(handler, con, "Reset PIN", "/pin/forgot",
                  handler.view_pin_forgot(con, {
                      "err": f"Too many wrong tries — wait {wait // 60 + 1} min.",
                      "sa1": data.get("sa1") or "",
                      "sa2": data.get("sa2") or ""}))
    elif engine.verify_pin_security(con, data.get("sa1") or "",
                                    data.get("sa2") or ""):
        _pin_reset(ip)
        engine.clear_pin(con)
        handler._redirect("/setup/security?msg=" + quote_plus(
            "PIN cleared — set a new one below"))
    else:
        _pin_note_fail(ip)
        _rerender(handler, con, "Reset PIN", "/pin/forgot",
                  handler.view_pin_forgot(con, {
                      "err": "The answers do not match the security questions on file. Check the answers and try again.",
                      "sa1": data.get("sa1") or "",
                      "sa2": data.get("sa2") or ""}))


def _post_setup_security_pin(handler, con, data, u):
    mode = data.get("mode")
    pin1 = (data.get("pin1") or "").strip()
    pin2 = (data.get("pin2") or "").strip()
    # Batch 3 #1: every failure re-renders the page the operator was
    # on — the Welcome page during onboarding (its form posts next=/),
    # Security otherwise — with the error stated and the entries kept.
    # PIN fields stay blank for hygiene; security answers survive.
    _welcome = bool((data.get("next") or "").strip())

    def _fail(err):
        _q = {"sq1": data.get("sq1"), "sq2": data.get("sq2"),
              "sa1": data.get("sa1") or "", "sa2": data.get("sa2") or ""}
        if _welcome:
            _q["err"] = err
            _rerender(handler, con, "Welcome", "/welcome",
                      handler.view_welcome(con, _q))
        else:
            _rerender(handler, con, "Security", "/setup/security",
                      handler.view_security(con, _q), err)

    if engine.pin_is_set(con):
        if mode != "change" or not engine.verify_pin(con, data.get("cur") or ""):
            _fail("The current PIN is incorrect. Enter the current desk PIN and try again.")
            return
    elif mode != "set":
        _fail("No desk PIN is set yet. Set a PIN before trying to change it.")
        return
    if pin1 != pin2:
        _fail("The two PIN entries do not match. Enter the same PIN in both fields.")
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
            _fail(str(e))
            return
    try:
        rec = engine.set_pin(con, pin1)
    except ValueError as e:
        _fail(str(e))
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
        dest_qs = ("&" if "?" in dest else "?") + ("from=setup&" if flow_next else "")
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


def _post_setup_security_lock(handler, con, data, u):
    # Desk idle lock (Jason 2026-10-15): 0 = Off, else minutes 5–1440.
    # A bare preference — inert until a PIN exists, so no PIN check here;
    # the Security page itself is reachable before a PIN is set by design.
    try:
        v = int(data.get("desk_lock_mins") or 60)
    except (TypeError, ValueError):
        v = 60
    if v <= 0:
        v = 0
    elif v < 5:
        v = 5
    elif v > 1440:
        v = 1440
    engine.set_option(con, "desk_lock_mins", str(v))
    con.commit()
    handler._redirect("/setup/security?msg=" + quote_plus("Idle lock saved"))


def _post_setup_security_questions(handler, con, data, u):
    # Batch 3 #1: failures re-render the Security page with the error
    # stated (this route's only surface is Security — no standalone
    # questions form exists in the current views, so there are no
    # answer fields on the page to re-populate).
    if not engine.pin_is_set(con):
        _rerender(handler, con, "Security", "/setup/security",
                  handler.view_security(con, {}), "No desk PIN is set yet. Set a PIN before saving security questions.")
        return
    if not engine.verify_pin(con, data.get("cur") or ""):
        _rerender(handler, con, "Security", "/setup/security",
                  handler.view_security(con, {}), "The current PIN is incorrect. Enter the current desk PIN and try again.")
        return
    try:
        q1 = int(data.get("sq1") or "0")
        q2 = int(data.get("sq2") or "1")
        engine.set_pin_security(con, q1, data.get("sa1") or "",
                                q2, data.get("sa2") or "")
    except (ValueError, TypeError) as e:
        _rerender(handler, con, "Security", "/setup/security",
                  handler.view_security(con, {}), str(e))
        return
    handler._redirect("/setup/security?msg=" + quote_plus(
        "Security questions saved"))


def _post_setup_lookups_add(handler, con, data, u):
    # Global dropdown rule (Issue 4): -Add- inserts one option into a
    # covered lookups list. PIN-gated by _pin_gate ("/setup/lookups" is a
    # gated prefix); the desk JS calls this via fetch and expects JSON.
    try:
        engine.add_lookup(con, data.get("kind") or "", data.get("value") or "")
    except ValueError as e:
        handler._send_json({"ok": False, "error": str(e)})
        return
    handler._send_json({"ok": True})


def _post_setup_devices_issue(handler, con, data, u):
    base = (data.get("base_url") or "").strip().rstrip("/")
    if base:
        engine.set_option(con, "device_base_url", base)
    # Batch 3 #13: no "Issued by" field — the desk identity is stamped.
    dev = engine.issue_device(con, data.get("label"), data.get("days") or 90,
                              _desk_name(handler, con))
    handler._redirect(f"/setup/devices/show?token={dev['token']}&msg=Device+code+issued")


def _post_setup_devices_revoke(handler, con, data, u):
    engine.revoke_device(con, data.get("token") or "")
    handler._redirect("/setup/devices?msg=Device+revoked")


def _post_setup_devices_rotate(handler, con, data, u):
    new = engine.rotate_device(con, data.get("token") or "", 90,
                               _desk_name(handler, con))
    handler._redirect(f"/setup/devices/show?token={new['token']}&msg=Code+rotated")


def _post_yard_ticket_condition(handler, con, data, u):
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


def _post_yard_ticket_status(handler, con, data, u):
    dev, reason = handler._device(con)
    if not dev:
        handler._send(handler._device_denied(reason), 403)
        return
    tid = u.path.split("/")[3]
    want = data.get("status") or ""
    if want not in handler.DEVICE_STATUSES:
        raise ValueError("That move is desk-only")
    # Yard moves follow the same gates (shop-flow, Jason 2026-10-21):
    # no un-overridable blocks anywhere. The condition switch OFF skips
    # the presence gates here too; the yard status form's "Proceed
    # anyway" checkbox is the audited escape for the presence gates
    # and for a non-PASS FIT, in both switch modes.
    _cond_on = engine.module_on(con, "condition")
    _proceed = data.get("proceed") == "1"
    engine.set_status(con, tid, want, data.get("off_rent") or None, data.get("clerk"),
                      skip_condition=(not _cond_on) or _proceed,
                      audit_bypass=_proceed and _cond_on,
                      override_fit=_proceed)
    handler._redirect(f"/d/ticket/{tid}?msg=Status+updated")


def _post_setup(handler, con, data, u):
    con.execute(
        """UPDATE company SET name=?, dba=?, addr_street=?, addr_street2=?, addr_city=?,
           addr_state=?, addr_zip=?, phys_street=?, phys_street2=?, phys_city=?,
           phys_county=?, phys_state=?, phys_zip=? WHERE id=1""",
        (
            data["name"], (data.get("dba") or "").strip() or None,
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
    # Setup chain (Batch 3 #3): during a setup run, saving carries the
    # operator to the next step with its step statement. After
    # Finished, save stays on the page (Jason 2026-10-21): the Company
    # page is the one setup page with a summary/form split — a bare
    # /setup lands on the read-only summary, not the form he was just
    # editing (look-see batch 2, 2026-10-21) — so the redirect keeps
    # edit=1 and he stays on the form, like every other setup save.
    adv = chain_advance(con, "company", "Company setup saved")
    if adv:
        _chain_redirect(handler, adv)
    else:
        handler._redirect("/setup?edit=1&saved=1&msg=" + quote_plus("Company setup saved"))


def _post_setup_billing(handler, con, data, u):
    # Book default terms (Item 6 edge, 2026-10-20): if the posted
    # default is no longer in the master terms list (deleted from the
    # master, or posted from a stale page), fall back to the first
    # remaining enabled term, else the first remaining master term —
    # never save a default the pickers cannot show. An empty master
    # keeps the posted string (it is a setting, not a picker entry).
    _dterms = (data.get("default_terms") or "").strip() or "Net 30"
    _master_terms = engine.lookups(con, "terms")
    if _master_terms and _dterms not in _master_terms:
        _en_terms = enabled_values(con, "terms")
        _dterms = _en_terms[0] if _en_terms else _master_terms[0]
    con.execute("UPDATE company SET invoice_prefix=?, billing_email=?, default_terms=?, min_days=?, bill_both_dates=? WHERE id=1",
                (data.get("invoice_prefix") or "INV", data.get("billing_email") or "", _dterms, int(data.get("min_days") or 1), 1 if data.get("bill_both_dates") == "1" else 0))
    try:
        engine.set_option(con, "quote_valid_days", str(max(1, int(data.get("quote_valid_days") or 30))))
    except (TypeError, ValueError):
        engine.set_option(con, "quote_valid_days", "30")
    con.commit()
    # Full Job Info print set (tweak round 2, 2026-10-20): every Job
    # Info card field, plus taxexempt. Attach File is excluded — an
    # upload, not a printable line. Maximum 7 is enforced here
    # (polish round, 2026-10-20): at most the first seven checked
    # fields, in the fixed print order, are stored, even if a post
    # arrives with eight or more jb_* values. The list is
    # in the fixed print order (follow-up, 2026-10-20) so the stored
    # inv_jobinfo_fields string reads in print order too; print
    # order itself is governed by printpack.JOBINFO_FIELDS.
    _jb = [k for k in ("po", "well", "afe", "cost_code",
                       "job", "contact_name", "contact_phone",
                       "contact_email", "ticket_ref", "job_notes",
                       "location", "taxexempt")
           if data.get("jb_" + k) == "1"]
    _jb = _jb[:7]
    engine.set_option(con, "inv_jobinfo_fields", ",".join(_jb))
    # Spec 7 curation: the three enabled sets save with the same
    # button. Posted checkboxes are en_<kind>_<index> with the value as
    # the value attribute; collect them in index order. A non-empty
    # "Add your own" (new_<kind>) joins the master list via add_lookup
    # (duplicates ignored) and the enabled set, checked by default.
    import json as _json
    for _kind, _opt_key, _new_key in (
            ("terms", "enabled_terms", "new_terms"),
            ("inv_uom", "enabled_inv_uom", "new_inv_uom"),
            ("inv_item", "enabled_inv_item", "new_inv_item"),
            ("comp_doc", "enabled_comp_doc", "new_comp_doc")):
        # Curation guard (look-see batch 2, 2026-10-21): a kind's
        # enabled set is rebuilt ONLY when that kind's panel was in
        # the post (each rendered panel carries a panel_<kind>
        # marker). A post that never rendered the panel — the terms
        # panel while the billing module is off, or any partial post
        # — must not rebuild the set from zero checkboxes and wipe
        # the book's curation to empty.
        if data.get(f"panel_{_kind}") != "1":
            continue
        _prefix = f"en_{_kind}_"
        _picked = []
        for _k, _v in data.items():
            if _k.startswith(_prefix) and _v:
                try:
                    _n = int(_k[len(_prefix):])
                except ValueError:
                    continue
                _picked.append((_n, _v))
        _chosen = [_v for _n, _v in sorted(_picked)]
        # Item 6 tolerance: a value deleted from the master (e.g. by
        # a stale page posting an old checkbox set) is pruned from the
        # enabled set being saved — the enabled set never dangles.
        _master_now = set(engine.lookups(con, _kind))
        _chosen = [_v for _v in _chosen if _v in _master_now]
        _new_val = (data.get(_new_key) or "").strip()
        if _new_val:
            try:
                engine.add_lookup(con, _kind, _new_val)
            except ValueError:
                pass
            if _new_val not in _chosen:
                _chosen.append(_new_val)
        engine.set_option(con, _opt_key, _json.dumps(_chosen))
    engine.set_option(con, "setup_billing_done", "1")
    # Setup chain (Batch 3 #3): advance during a run; after Finished,
    # save stays on the page (Jason 2026-10-21; see _post_setup).
    adv = chain_advance(con, "billing", "Billing settings saved")
    if adv:
        _chain_redirect(handler, adv)
    else:
        handler._redirect("/setup/billing?msg=" + quote_plus("Billing settings saved"))


_CURATED_OPT_KEYS = (("terms", "enabled_terms"),
                     ("inv_uom", "enabled_inv_uom"),
                     ("inv_item", "enabled_inv_item"),
                     ("comp_doc", "enabled_comp_doc"))


def _post_setup_billing_lookup_del(handler, con, data, u):
    # Item 6 (2026-10-20): delete ONE entry from a curated master list.
    # The panel ✕ buttons post here via formaction (name=del_<kind>,
    # value=the entry). Only the lookups row goes away (plus its
    # tombstone, inside engine.delete_lookup); stored documents,
    # invoices and customers keep their strings verbatim. The deleted
    # value is also pruned from the kind's enabled set — the pruned
    # set is written back explicitly so nothing dangles on disk even
    # when the book was still on the implicit factory-core set.
    import json as _json
    for _kind, _opt_key in _CURATED_OPT_KEYS:
        _val = (data.get("del_" + _kind) or "").strip()
        if not _val:
            continue
        try:
            engine.delete_lookup(con, _kind, _val)
        except ValueError as e:
            handler._redirect("/setup/billing?err=" + quote_plus(str(e)))
            return
        _en = [v for v in enabled_values(con, _kind) if v != _val]
        engine.set_option(con, _opt_key, _json.dumps(_en))
        if _kind == "terms":
            # Book default terms edge: if the deleted term was the
            # company default, fall back to the first remaining
            # enabled term (else first remaining master term, else
            # blank) so no screen offers a default that is gone.
            # Customer records are NOT rewritten — a customer's own
            # terms string stays verbatim, and lookup_select already
            # displays an off-list current value on its edit screen.
            _row = con.execute(
                "SELECT default_terms FROM company WHERE id=1").fetchone()
            if _row and (_row["default_terms"] or "") == _val:
                _master = engine.lookups(con, "terms")
                _fb = _en[0] if _en else (_master[0] if _master else "")
                con.execute("UPDATE company SET default_terms=? WHERE id=1",
                            (_fb,))
                con.commit()
        handler._redirect("/setup/billing?msg=" + quote_plus(
            f"Deleted {_val} from the list"))
        return
    handler._redirect("/setup/billing?err=" + quote_plus("Nothing to delete"))


def _post_setup_billing_lookup_restore(handler, con, data, u):
    # Item 6 companion safeguard: restore ONE curated list — the
    # shipped master entries come back (tombstones cleared + reseed,
    # in engine.restore_factory_lookups) and the enabled set is reset
    # to the factory-on core for that kind. Custom-added entries stay
    # in the master (unchecked); no record/document row is touched.
    import json as _json
    _kind = (data.get("restore_kind") or "").strip()
    _opt_key = dict(_CURATED_OPT_KEYS).get(_kind)
    if not _opt_key:
        handler._redirect("/setup/billing?err=" + quote_plus("Unknown list"))
        return
    try:
        engine.restore_factory_lookups(con, _kind)
    except ValueError as e:
        handler._redirect("/setup/billing?err=" + quote_plus(str(e)))
        return
    _master = set(engine.lookups(con, _kind))
    _core = [v for v in ENABLED_CORES.get(_kind, []) if v in _master]
    engine.set_option(con, _opt_key, _json.dumps(_core))
    handler._redirect("/setup/billing?msg=" + quote_plus(
        "Factory list restored"))


def _post_setup_admin(handler, con, data, u):
    con.execute("UPDATE company SET backup_dir=? WHERE id=1", (data.get("backup_dir") or "",))
    if data.get("print_folder") is not None:
        engine.set_option(con, "print_folder", (data.get("print_folder") or "").strip())
    if data.get("text_size") is not None:
        # The one general zoom (tweak round 2026-10-20): Setup ->
        # Administration's Zoom card posts here; same ui_text_size option
        # the Devices Display Preferences form writes.
        _ts = (data.get("text_size") or "standard").strip().lower()
        engine.set_option(con, "ui_text_size",
                          _ts if _ts in ("standard", "large", "xlarge") else "standard")
    if data.get("modules") is not None:
        # "What your shop does" (shop-flow, Jason 2026-10-21): a posted
        # checkbox = the shop does it, absent = it doesn't. Only this
        # card posts the modules marker, so the other cards sharing
        # this endpoint never touch the switches.
        for _name in engine.MODULE_NAMES:
            engine.set_module(con, _name, data.get(f"mod_{_name}") == "1")
    con.commit()
    engine.set_option(con, "setup_admin_done", "1")
    # Setup chain (Batch 3 #3): the Admin page hosts two chain stops
    # (step 2 operational, step 7 layout). Each form carries its stop
    # in chain_step; an unmarked post is attributed to the stop the
    # chain is waiting on, operational first. After Finished, save
    # stays on the page (Jason 2026-10-21; see _post_setup).
    _step = (data.get("chain_step") or "").strip()
    if _step not in ("admin", "layout"):
        _step = ""
        try:
            _by = {s["key"]: s for s in setup_chain(con)}
            if not _by.get("admin", {}).get("done"):
                _step = "admin"
            elif not _by.get("layout", {}).get("done"):
                _step = "layout"
        except Exception:
            _step = ""
    adv = None
    if _step == "layout":
        engine.set_option(con, "setup_layout_done", "1")
        adv = chain_advance(con, "layout", "Layout options saved")
    elif _step == "admin":
        adv = chain_advance(con, "admin", "Admin settings saved")
    if adv:
        _chain_redirect(handler, adv)
    else:
        handler._redirect("/setup/admin?msg=" + quote_plus("Backup settings saved"))


def _post_backup(handler, con, data, u):
    # Batch 3 #13: no Name field on the form — stamp the desk identity.
    dest = engine.run_backup(con, _desk_name(handler, con))
    # Stay on the Backups page (Jason 2026-10-21; see _post_setup).
    handler._redirect("/backup?msg=" + quote_plus(
        f"Backup {dest.name} (book + photos)"))


def _post_backup_schedule(handler, con, data, u):
    engine.set_backup_schedule(con, data.get("schedule"),
                               data.get("every_days"))
    con.commit()
    handler._redirect("/backup?msg=" + quote_plus("Backup schedule saved"))


def _post_backup_restore(handler, con, data, u):
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
                con, tmp, _desk_name(handler, con))
        else:
            snap = engine.restore_backup(
                con, tmp, _desk_name(handler, con))
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
    handler._redirect("/backup?msg=" + quote_plus(
        f"Backup restored. Safety snapshot kept as {snap.name}"))


def _post_setup_phones_add(handler, con, data, u):
    lbl = (data.get("label") or "").strip()
    try:
        # Batch 3 #5: no label inference — adding never makes a number
        # main. Main is the explicit Make main pick only.
        engine.add_company_phone(con, lbl, data.get("number") or "")
        handler._redirect("/setup?edit=1&msg=" + quote_plus("Phone saved"))
    except ValueError as e:
        handler._redirect("/setup?edit=1&err=" + quote_plus(str(e)))


def _post_setup_phones_main(handler, con, data, u):
    # Batch 3 #5: the explicit main pick, wired to the existing engine
    # function (exactly one main at a time — the engine clears the
    # others). Same gate posture as the other setup phone posts.
    try:
        engine.set_main_company_phone(con, int(data.get("phone_id") or 0))
        handler._redirect("/setup?edit=1&msg=" + quote_plus("Main phone set"))
    except (ValueError, TypeError) as e:
        handler._redirect("/setup?edit=1&err=" + quote_plus(str(e)))


def _post_setup_phones_del(handler, con, data, u):
    try:
        engine.del_company_phone(con, int(data.get("phone_id") or 0))
    except (ValueError, TypeError):
        pass
    handler._redirect("/setup?edit=1&msg=" + quote_plus("Phone removed"))


def _post_setup_crew(handler, con, data, u):
    parts = [(data.get("crew_first") or "").strip(),
             (data.get("crew_mi") or "").strip(),
             (data.get("crew_last") or "").strip(),
             (data.get("crew_suffix") or "").strip()]
    engine.add_crew(con, " ".join(p for p in parts if p),
                    data.get("crew_position") or "")
    handler._redirect("/setup?edit=1#crew-entry&msg=" + quote_plus("Crew member saved"))


def _post_setup_crew_del(handler, con, data, u):
    engine.drop_crew(con, data.get("crew_name") or "")
    handler._redirect("/setup?edit=1&msg=" + quote_plus("Crew removed"))


def _post_setup_vendors(handler, con, data, u):
    try:
        # Batch 3 #9: no Kind on this form (crew is not added here) —
        # an edit keeps the record's stored kind; a create is a vendor.
        # Contact and Notes ride the same save; the engine formats the
        # phone through the one formatter (#9c).
        _vid_raw = (data.get("vendor_id") or "").strip()
        _vid_in = int(_vid_raw) if _vid_raw else None
        _kind = "vendor"
        if _vid_in:
            _ex = next((v for v in engine.list_vendors(con)
                        if v["vendor_id"] == _vid_in), None)
            if _ex:
                _kind = _ex["kind"]
        _vid = engine.save_vendor(con, data.get("name") or "",
                           kind=_kind,
                           phone=data.get("phone") or "",
                           email=data.get("email") or "",
                           specialties=data.get("specialties") or "",
                           contact=data.get("contact") or "",
                           notes=data.get("notes") or "",
                           vendor_id=_vid_in)
        if not _vid_in:
            # A create is an explicit operator action — Done Today gets
            # it (look-see batch 2, 2026-10-21; the unit-create
            # precedent). Vendors have no page of their own; the link
            # lands on the list where the record lives.
            engine.add_done_manual(
                con, f"Added vendor {(data.get('name') or '').strip()}"[:200],
                "/setup/vendors/all", (data.get("clerk") or "").strip()[:40])
        # Save stays on the Vendor page (Jason 2026-10-21): the
        # operator may add another vendor or navigate away himself.
        handler._redirect("/setup/vendors?msg=" + quote_plus("Vendor saved"))
    except ValueError as e:
        handler._redirect("/setup/vendors?err=" + quote_plus(str(e)))


def _post_setup_vendors_del(handler, con, data, u):
    try:
        engine.delete_vendor(con, int(data.get("vendor_id") or 0))
    except (ValueError, TypeError):
        pass
    handler._redirect("/setup/vendors?msg=" + quote_plus("Vendor removed"))


def _post_setup_options(handler, con, data, u):
    con.execute(
        "UPDATE company SET tooltips=? WHERE id=1",
        (1 if data.get("tooltips") == "1" else 0,),
    )
    con.commit()
    _ts = (data.get("text_size") or "standard").strip().lower()
    engine.set_option(con, "ui_text_size",
                      _ts if _ts in ("standard", "large", "xlarge") else "standard")
    # Display Preferences is a functional-options save: during a setup
    # run it completes (or advances) the chain's layout stop.
    engine.set_option(con, "setup_layout_done", "1")
    adv = chain_advance(con, "layout", "Options saved")
    if adv:
        _chain_redirect(handler, adv)
    else:
        handler._redirect("/setup/devices?msg=" + quote_plus("Options saved"))


def _post_setup_rerun_start(handler, con, data, u):
    # "Run setup again" (from Admin): opens a review/change pass over
    # the existing settings. Sets a flag only — no record is touched,
    # no database is created or deleted.
    engine.set_option(con, "setup_rerun", "1")
    handler._redirect("/setup?from=setup&msg=" + quote_plus(
        "Setup review \u2014 your current settings are in place. "
        "Save a step to move to the next."))


def _post_setup_rerun_cancel(handler, con, data, u):
    engine.set_option(con, "setup_rerun", "")
    handler._redirect("/setup/admin?msg=" + quote_plus("Setup review ended. Settings are unchanged except for any steps saved during the review."))


def _folder_return(target):
    return "/backup" if target == "backup" else "/setup/admin"


def _post_folder_pick(handler, con, data, u):
    # Folder browser pick (Batch 3 #10e): store the browsed folder for
    # the backup setting (company.backup_dir) or the print setting
    # (print_folder option). An empty path clears to the default.
    target = data.get("target") if data.get("target") in ("backup", "print") else "backup"
    path = (data.get("path") or "").strip()
    if path and not Path(path).is_dir():
        handler._redirect("/setup/folders?for=" + target + "&path=" +
                          quote_plus(path) + "&err=" + quote_plus("That folder was not found. Browse to a folder that exists, then pick it."))
        return
    if target == "print":
        engine.set_option(con, "print_folder", path)
    else:
        con.execute("UPDATE company SET backup_dir=? WHERE id=1", (path,))
        con.commit()
    handler._redirect(_folder_return(target) + "?msg=" + quote_plus("Folder saved"))


def _post_folder_new(handler, con, data, u):
    # Folder browser New Folder (Batch 3 #10e): one new folder inside
    # the browsed folder — a single name, no path separators.
    target = data.get("target") if data.get("target") in ("backup", "print") else "backup"
    base = Path((data.get("path") or "").strip() or ".")
    name = (data.get("name") or "").strip()
    if (not name or name in (".", "..") or "/" in name or "\\" in name
            or len(name) > 80):
        handler._redirect("/setup/folders?for=" + target + "&path=" +
                          quote_plus(str(base)) + "&err=" +
                          quote_plus("That folder name is not allowed. Use a single folder name, up to 80 characters, with no slashes."))
        return
    newp = base / name
    try:
        newp.mkdir()
    except FileExistsError:
        pass
    except OSError:
        handler._redirect("/setup/folders?for=" + target + "&path=" +
                          quote_plus(str(base)) + "&err=" + quote_plus("That folder could not be created. Check that the location is available and writable, then try again."))
        return
    handler._redirect("/setup/folders?for=" + target + "&path=" +
                      quote_plus(str(newp)) + "&msg=" + quote_plus("Folder created"))


def _print_folder(con):
    """Where Print to Location files documents: the operator's chosen
    folder (Setup -> Administration), else a 'printouts' folder next
    to the database."""
    pf = (engine.get_option(con, "print_folder", "") or "").strip()
    if pf:
        return Path(pf)
    return Path(engine.DB_PATH).parent / "printouts"


def _post_print_save(handler, con, data, u):
    """Print to Location for documents: fetch the document (PDF where
    the path names one, else the print HTML) from this same server and
    file it into the print folder. The path is validated to stay
    inside /print/; the desk PIN gate covers this route."""
    doc = (data.get("doc") or "").strip()
    if not doc.startswith("/print/") or ".." in doc or "://" in doc:
        handler._send_json({"ok": False, "error": "bad document path"}, 400)
        return True
    port = handler.server.server_address[1]
    req = _urlreq.Request(
        f"http://127.0.0.1:{port}{doc}",
        headers={"Cookie": handler.headers.get("Cookie") or ""})
    try:
        with _urlreq.urlopen(req, timeout=30) as r:
            blob = r.read()
            ctype = r.headers.get_content_type()
    except Exception as e:
        handler._send_json({"ok": False, "error": f"could not render: {e}"}, 502)
        return True
    base = doc.split("?")[0].rstrip("/").rsplit("/", 1)[-1] or "document"
    base = _re.sub(r"[^A-Za-z0-9_.-]+", "-", base)
    if "." not in base:
        base += ".pdf" if ctype == "application/pdf" else ".html"
    folder = _print_folder(con)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / base
        dest.write_bytes(blob)
    except OSError as e:
        handler._send_json({"ok": False, "error": f"could not write: {e}"}, 500)
        return True
    handler._send_json({"ok": True, "path": str(dest)})
    return True


def _post_print_save_page(handler, con, data, u):
    """Print to Location for form pages: the browser sends the page's
    print view (live values included); it is filed as an .html
    document in the print folder."""
    raw = data.get("html") or ""
    if not raw or len(raw) > 3_000_000:
        handler._send_json({"ok": False, "error": "nothing to save"}, 400)
        return True
    name = _re.sub(r"[^A-Za-z0-9_.-]+", "-",
                   (data.get("name") or "FleetSheet document").strip()).strip("-.")
    if not name:
        name = "FleetSheet-document"
    if not name.lower().endswith(".html"):
        name += ".html"
    folder = _print_folder(con)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / name
        dest.write_text(raw, encoding="utf-8")
    except OSError as e:
        handler._send_json({"ok": False, "error": f"could not write: {e}"}, 500)
        return True
    handler._send_json({"ok": True, "path": str(dest)})
    return True


_POST_ROUTES = {
    "/print/save": _post_print_save,
    "/print/save-page": _post_print_save_page,
    "/sale/save": _post_sale_save,
    "/rentals/checkinout": _post_rentals_checkinout,
    "/rentals/complete": _post_rentals_complete,
    "/pin": _post_pin,
    "/alert/ack": _post_alert_ack,
    "/ticker/cats": _post_ticker_cats,
    "/today/task/add": _post_today_task_add,
    "/today/task/from": _post_today_task_from,
    "/today/task/done": _post_today_task_done,
    "/today/task/undone": _post_today_task_undone,
    "/today/sticky/add": _post_today_sticky_add,
    "/today/sticky/edit": _post_today_sticky_edit,
    "/today/sticky/remove": _post_today_sticky_remove,
    "/today/sticky/update": _post_today_sticky_update,
    "/today/sticky/done": _post_today_sticky_done,
    "/today/done/other": _post_today_done_other,
    "/today/done/other/remove": _post_today_done_other_remove,
    "/today/money/done": _post_today_money_done,
    "/pin/logout": _post_pin_logout,
    "/pin/forgot/questions": _post_pin_forgot_questions,
    "/setup/security/pin": _post_setup_security_pin,
    "/setup/security/questions": _post_setup_security_questions,
    "/setup/security/lock": _post_setup_security_lock,
    "/setup/lookups/add": _post_setup_lookups_add,
    "/setup/devices/issue": _post_setup_devices_issue,
    "/setup/devices/revoke": _post_setup_devices_revoke,
    "/setup/devices/rotate": _post_setup_devices_rotate,
    "/setup": _post_setup,
    "/setup/billing": _post_setup_billing,
    "/setup/billing/lookup/del": _post_setup_billing_lookup_del,
    "/setup/billing/lookup/restore": _post_setup_billing_lookup_restore,
    "/setup/admin": _post_setup_admin,
    "/backup": _post_backup,
    "/backup/schedule": _post_backup_schedule,
    "/backup/restore": _post_backup_restore,
    "/setup/phones/add": _post_setup_phones_add,
    "/setup/phones/main": _post_setup_phones_main,
    "/setup/phones/del": _post_setup_phones_del,
    "/setup/crew": _post_setup_crew,
    "/setup/crew/del": _post_setup_crew_del,
    "/setup/vendors": _post_setup_vendors,
    "/setup/vendors/del": _post_setup_vendors_del,
    "/setup/options": _post_setup_options,
    "/setup/rerun": _post_setup_rerun_start,
    "/setup/rerun/cancel": _post_setup_rerun_cancel,
    "/setup/folders/pick": _post_folder_pick,
    "/setup/folders/new": _post_folder_new,
}


_POST_PATTERN_ROUTES = [
    ("/d/ticket/", "/condition", _post_yard_ticket_condition),
    ("/d/ticket/", "/status", _post_yard_ticket_status),
]


def handle_post(handler, con, data, u):
    """Handle one POST. Returns True when the path was handled."""
    fn = _POST_ROUTES.get(u.path)
    if fn is not None:
        fn(handler, con, data, u)
        return True
    for prefix, suffix, fn in _POST_PATTERN_ROUTES:
        if u.path.startswith(prefix) and u.path.endswith(suffix):
            fn(handler, con, data, u)
            return True
    return False
