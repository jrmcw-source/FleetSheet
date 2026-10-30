#!/usr/bin/env python3
"""FleetSheet local app. Open http://127.0.0.1:8765 — SQLite is the book."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import html
import json
import logging
import os
import subprocess
import threading
import time
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, quote_plus, unquote, unquote_plus, urlparse

import engine
import printpack

import views_core
import views_accounting
import views_assets
import views_compliance
import views_health
import post_core
import post_assets
import post_accounting
import post_compliance
try:
    import updater_winsparkle
except Exception:
    # Older/partial installs without the updater module: the app runs
    # exactly as before, update checks just aren't available.
    updater_winsparkle = None
from views_core import lan_urls, page

GET_ROUTES = {
    "/": ("Today", lambda self, con, q: self.view_dash(con, q)),
    "/today/all": ("Everything", lambda self, con, q: self.view_today_all(con)),
    "/money": ("Billing", lambda self, con, q: self.view_money(con, q)),
    "/money/audit": ("All money — audit", lambda self, con, q: self.view_money_audit(con)),
    "/money/invoices/audit": ("Invoices audit", lambda self, con, q: self.view_money_invoices_audit(con)),
    "/money/payments/audit": ("Payments audit", lambda self, con, q: self.view_money_payments_audit(con, q or {})),
    "/money/credits/audit": ("Credit memos audit", lambda self, con, q: self.view_money_credits_audit(con)),
    "/petty/audit": ("Petty cash audit", lambda self, con, q: self.view_money_petty_audit(con)),
    "/money/petty/audit": ("Petty cash audit", lambda self, con, q: self._redirect("/petty/audit")),
    "/money/cash/audit": ("Cash audit", lambda self, con, q: self.view_money_cash_audit(con)),
    "/tickets": ("Rental Tickets", lambda self, con, q: self.view_tickets(con, q.get("flag"))),
    "/ticket/new": ("Rentals", lambda self, con, q: self.view_new_ticket(con, q)),
    "/quotes": ("Quotes", lambda self, con, q: self._redirect("/ticket/new?kind=quote")),
    "/quote/new": ("New quote", lambda self, con, q: self._redirect("/ticket/new?kind=quote")),
    "/changes": ("Change orders", lambda self, con, q: self._redirect("/ticket/new?kind=change")),
    "/changes/all": ("Change orders — audit", lambda self, con, q: self.view_changes_all(con)),
    "/wos/all": ("Work orders — audit", lambda self, con, q: self.view_wos_all(con)),
    "/quotes/all": ("Quotes — audit", lambda self, con, q: self.view_quotes_all(con)),
    "/sales/all": ("Sales — audit", lambda self, con, q: self.view_sales_all(con)),
    "/invoice/new": ("New invoice", lambda self, con, q: self.view_invoice_new(con, q)),
    "/pay": ("Record payment", lambda self, con, q: self.view_money(con, {"tab": "pay"})),
    "/credit": ("Credit memo", lambda self, con, q: self.view_money(con, dict(q or {}, tab="credit"))),
    "/petty": ("Petty cash", lambda self, con, q: self.view_petty(con, q)),
    "/cash": ("Cash", lambda self, con, q: self.view_money(con, {"tab": "cash"})),
    "/setup": ("Company", lambda self, con, q: self.view_setup(con, q)),
    "/setup/vendors": ("Vendors", lambda self, con, q: self.view_setup_vendors(con, q)),
    "/setup/vendors/all": ("All vendors", lambda self, con, q: self.view_vendors_all(con)),
    "/setup/admin": ("Administration", lambda self, con, q: self.view_setup_admin(con, q)),
    "/setup/folders": ("Choose folder", lambda self, con, q: self.view_folder_picker(con, q)),
    "/setup/billing": ("Billing setup", lambda self, con, q: self.view_setup_billing(con, q)),
    "/setup/health": ("Data Health", lambda self, con, q: self.view_health(con)),
    "/setup/devices": ("Devices", lambda self, con, q: self.view_devices(con, q)),
    "/setup/devices/show": ("Device QR", lambda self, con, q: self.view_device_show(
        con, q.get("token", ""), engine.get_option(con, "device_base_url", ""))),
    "/customers": ("Customers", lambda self, con, q: self.view_customers(con)),
    "/customers/all": ("All customers", lambda self, con, q: self.view_customers_all(con)),
    "/customer/new": ("New customer", lambda self, con, q: self.view_customer_form(con, None)),
    "/units": ("Units", lambda self, con, q: self._redirect("/assets/all")),
    "/assets": ("Assets", lambda self, con, q: self.view_assets(con)),
    "/assets/all": ("All assets", lambda self, con, q: self.view_assets_all(con)),
    "/unit/new": ("New unit", lambda self, con, q: self.view_unit_form(con, None)),
    "/unit/paperwork": ("Paperwork", lambda self, con, q: self.view_unit_paperwork(con, q)),
    "/sites": ("Sites", lambda self, con, q: self.view_sites(con)),
    "/sites/all": ("Job sites — all", lambda self, con, q: self.view_sites_all(con)),
    "/site/new": ("New site", lambda self, con, q: self.view_site_form(con, None, q)),
    "/wos": ("Work orders", lambda self, con, q: self._redirect("/ticket/new?kind=workorder")),
    "/wo/new": ("New work order", lambda self, con, q: self._redirect("/ticket/new?kind=workorder")),
    "/invoices": ("Invoices", lambda self, con, q: self.view_invoices(con)),
    "/export": ("Data", lambda self, con, q: self.view_export(con, q)),
    "/reports/mixed": ("Mixed report", lambda self, con, q: self.view_report_mixed(con, q)),
    "/reports/weekly/money": ("Weekly money", lambda self, con, q: self.view_report_weekly_money(con)),
    "/reports/weekly/fleet": ("Fleet utilization", lambda self, con, q: self.view_report_weekly_fleet(con, q)),
    "/reports/weekly/flow": ("This week's flow", lambda self, con, q: self.view_report_weekly_flow(con, q)),
    "/backup": ("Backups", lambda self, con, q: self.view_backups(con)),
    "/health": ("System Health", lambda self, con, q: self.view_system_health(con)),
    "/billing": ("Billing", lambda self, con, q: self._redirect("/money")),
    "/rentals": ("Rentals", lambda self, con, q: self._redirect("/ticket/new")),
    "/sale": ("Sales Ticket", lambda self, con, q: self.view_sale(con, q)),
    "/reports": (
        "Reports",
        lambda self, con, q: self.view_reports(
            con, int(q.get("days") or 14), q.get("p") or "mtd", q.get("from") or "", q.get("to") or "",
            q.get("b") or "avail", q.get("all") == "1"
        ),
    ),
    "/pin": ("Desk PIN", lambda self, con, q: self.view_pin(con, q)),
    "/done": ("Done log", lambda self, con, q: self.view_done(con, q)),
    "/today/done/other": ("Add Done", lambda self, con, q: self.view_done_other(con, q)),
    "/ticker/panel": ("Filter", lambda self, con, q: self.view_ticker_panel(con, q)),
    "/setup/security": ("Security", lambda self, con, q: self.view_security(con, q)),
    "/compliance": ("Compliance", lambda self, con, q: self.view_compliance(con, q)),
    "/compliance/all": ("All compliance", lambda self, con, q: self.view_compliance_all(con)),
}

# Prefix routes for /kind/<id>: prefix -> handler(self, con, item_id) -> (title, body_html)
GET_PREFIX_ROUTES = [
    ("/summary/", lambda self, con, rest: self.view_summary_route(con, rest)),
    ("/ticket/", lambda self, con, tid: (tid, self.view_ticket(con, tid))),
    ("/quote/", lambda self, con, qn: (qn, self.view_quote_form(con, qn))),
    ("/invoice/", lambda self, con, ino: (ino, self.view_invoice_lines(con, ino))),
    ("/customer/", lambda self, con, cid: (cid, self.view_customer_form(con, cid))),
    ("/unit/", lambda self, con, aid: (aid, self.view_unit_form(con, aid))),
    ("/site/", lambda self, con, sid: self.view_site_route(con, sid)),
    ("/wo/", lambda self, con, wid: (wid, self.view_wo_form(con, wid))),
    ("/sale/", lambda self, con, grp: (grp, self.view_sale_detail(con, grp))),
    ("/compack/", lambda self, con, pid: (pid, self.view_pack(con, pid))),
    ("/ucompliance/", lambda self, con, aid, q=None: (aid, self.view_unit_compliance(con, aid, (q or {}).get("focus")))),
]
# --- end GET routing table ---------------------------------------------------

# --- consumer license (EULA) gate ---------------------------------------------
# Consumer builds ship an empty `.eula_required` file next to app.py. When it
# is present, every desk page redirects to /eula until the user clicks "I
# accept" (recorded in `.eula_accepted`). Dev trees and test harnesses never
# carry `.eula_required`, so this gate is inert there. Yard (/d) routes are
# always exempt.
_HTTPD = None

# --- window-close lifecycle -----------------------------------------------
# Any open FleetSheet page (desk, yard, PIN-lock, EULA) POSTs /heartbeat once
# a minute. The server stops when the app window closes (see the app-window
# watcher and close-grace paths below), when this console window is closed,
# or on Ctrl+C. There is no server idle timeout: Jason removed it
# 2026-10-20 as redundant with the desk idle lock, which stays.
def _stop_server(server, reason):
    """Checkpoint the WAL, drop the pidfile, and shut the HTTP server down.
    Shared by the app-window watcher and the close-grace paths."""
    try:
        _c = engine.connect()
        try:
            _c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            _c.close()
    except Exception as e:
        print(f"WAL checkpoint before shutdown failed ({e})")
    print(f"FleetSheet shutting down ({reason}).")
    try:
        (engine.DB_PATH.parent / "fleetsheet.pid").unlink(missing_ok=True)
    except OSError:
        pass
    try:
        server.shutdown()
    except Exception:
        pass


# --- close-grace lifecycle ------------------------------------------------
# When the desk app-mode window closes while yard devices are still
# heartbeating, the server does not stop silently. It enters a grace window
# (FLEETSHEET_CLOSE_GRACE_SECS, default 30s): heartbeat replies carry a
# shutdown countdown so /d pages can warn and auto-save, then the server
# checkpoints and stops exactly like the other shutdown paths. With no
# yard clients active, the window close still stops the server at once.
try:
    CLOSE_GRACE_SECS = int(os.environ.get("FLEETSHEET_CLOSE_GRACE_SECS", "30"))
except (TypeError, ValueError):
    CLOSE_GRACE_SECS = 30

SHUTDOWN_AT = None          # epoch when the close-grace window ends; None = no grace
_YARD_SEEN = {}             # device token -> last heartbeat epoch
_YARD_LOCK = threading.Lock()
_YARD_ACTIVE_WINDOW = 120   # a yard client counts as active this long after its last beat


def _yard_active_count():
    """Distinct yard devices heartbeating recently. Prunes stale entries."""
    now = time.time()
    with _YARD_LOCK:
        stale = [t for t, ts in _YARD_SEEN.items() if now - ts > _YARD_ACTIVE_WINDOW]
        for t in stale:
            del _YARD_SEEN[t]
        return len(_YARD_SEEN)


def _note_yard_heartbeat(token):
    if token:
        with _YARD_LOCK:
            _YARD_SEEN[token] = time.time()


def _begin_close_grace(server):
    """The desk window closed. Yard clients active: warn them through the
    grace window, then stop. None active: stop at once, as before."""
    global SHUTDOWN_AT
    n = _yard_active_count()
    if n == 0:
        _stop_server(server, "app window closed")
        return
    if SHUTDOWN_AT is not None:
        return  # already in grace
    SHUTDOWN_AT = time.time() + CLOSE_GRACE_SECS
    print(f"FleetSheet: desk window closed with {n} yard device(s) active — "
          f"{CLOSE_GRACE_SECS}s grace before shutdown.")
    threading.Thread(target=_grace_waiter, args=(server,), daemon=True).start()


def _grace_waiter(server):
    """Background: at the end of the close-grace window, checkpoint and stop."""
    while time.time() < SHUTDOWN_AT:
        time.sleep(1)
    n = _yard_active_count()
    _stop_server(server, f"close grace elapsed — {n} yard client(s) warned")


# Desk pages read the live yard count through this hook (set once here, so
# views_core needs no import back into app).
views_core.yard_status_hook = _yard_active_count
# --- end close-grace lifecycle ----------------------------------------------


# How long the freshly launched browser process must stay alive before its
# exit counts as "the window was closed". A client that dies inside this
# window never owned a window at all — it handed off to a pre-existing
# browser on our profile, or the launch itself failed — so waiting on it
# would be an instant false shutdown.
_WINDOW_GRACE_SECS = 3


def _watch_browser_proc(server, proc):
    """Background: the app-mode window IS the session. When its browser
    process exits, stop the server at once. Daemon thread; never blocks
    interpreter exit."""
    try:
        proc.wait(timeout=_WINDOW_GRACE_SECS)
        return  # died too fast to have owned a window — not a real close
    except subprocess.TimeoutExpired:
        pass
    except Exception:
        return
    try:
        proc.wait()
    except Exception:
        return
    _begin_close_grace(server)


def _watch_macos_profile(server):
    """Background: macOS `open -n` gives no process handle, so poll for the
    FleetSheet profile's browser process instead. When it's gone, the window
    is closed — stop the server at once. Daemon thread."""
    import appmode
    profile = appmode.profile_dir()
    target = None
    deadline = time.time() + 20
    while time.time() < deadline and target is None:
        pids = appmode.find_profile_pids(profile)
        if pids:
            target = max(pids)  # PIDs rise monotonically: newest wins
        else:
            time.sleep(1)
    if target is None:
        return  # never found it; nothing to watch
    while True:
        time.sleep(5)
        try:
            if target not in appmode.find_profile_pids(profile):
                break
        except Exception:
            return
    _begin_close_grace(server)
# --- end window-close lifecycle -------------------------------------------


def _eula_required():
    return (Path(__file__).resolve().parent / ".eula_required").exists()


def _eula_accepted():
    return (Path(__file__).resolve().parent / ".eula_accepted").exists()


def _eula_text():
    p = Path(__file__).resolve().parent.parent / "EULA.txt"
    try:
        t = p.read_text(encoding="utf-8")
        if t.strip():
            return t
    except OSError:
        pass
    return ("FLEET SHEET - LICENSE AGREEMENT\n\n"
            "Use of this software requires accepting the license agreement\n"
            "shipped as EULA.txt with this package.")


# --- end consumer license ---------------------------------------------------


# --- build version -----------------------------------------------------------
# The launcher compares this stamp against the running server's /version.
# If they differ, the launcher restarts the server instead of opening a
# window onto stale code ("new window, old guts"). Packaging writes the
# build tag into VERSION; dev trees keep "dev".
def _app_version():
    try:
        v = (Path(__file__).resolve().parent / "VERSION").read_text(
            encoding="ascii").strip()
        return v or "dev"
    except OSError:
        return "dev"


APP_VERSION = _app_version()
# --- end build version --------------------------------------------------------


class Handler(views_accounting.AccountingViews,
              views_assets.AssetViews, views_compliance.ComplianceViews,
              views_health.HealthViews, BaseHTTPRequestHandler):
    """FleetSheet request handler. Views/actions live in views_* and post_* modules."""
    # HTTP/1.1 keep-alive (master plan Phase 0): kills per-request TCP handshake.
    protocol_version = "HTTP/1.1"
    def log_message(self, fmt, *args):
        print("[http]", args[0] if args else fmt)

    # --- consumer license + stop -------------------------------------------
    def _render_eula(self):
        t = html.escape(_eula_text())
        return (
            "<div class='card' style='max-width:720px;margin:24px auto'>"
            "<h2 style='margin-top:0'>License agreement</h2>"
            "<p class='mute'>Read the agreement below. Accepting it is required to use FleetSheet.</p>"
            f"<pre style='white-space:pre-wrap;max-height:50vh;overflow:auto;"
            f"background:#f4f6f9;padding:12px;border:1px solid #d5dbe3'>{t}</pre>"
            "<form method='post' action='/eula'>"
            "<button type='submit' name='accept' value='1'>I accept</button> "
            "<button type='submit' name='accept' value='0'>I do not accept</button>"
            "</form></div>")

    def _accept_eula(self, data):
        if (data.get("accept") or "") == "1":
            try:
                (Path(__file__).resolve().parent / ".eula_accepted").write_text(
                    "accepted\n", encoding="ascii")
            except OSError:
                pass
            # After the EULA, first-run onboarding collects the desk PIN
            # before anything else — money pages are PIN-gated, so this
            # avoids a surprise wall mid-workflow. (2026-10-06)
            con = engine.connect()
            try:
                needs_pin = not engine.pin_is_set(con)
            finally:
                con.close()
            dest = "/welcome" if needs_pin else "/"
            self._redirect(dest + "?msg=" + quote_plus("License accepted."))
        else:
            self._send(page(
                "License agreement",
                "<div class='card' style='max-width:720px;margin:24px auto'>"
                "<h2 style='margin-top:0'>Not accepted</h2>"
                "<p>FleetSheet can't be used without accepting the license agreement.</p>"
                "<p><a href='/eula'>Read it again</a></p></div>",
                "FleetSheet", "/eula"))

    # --- end consumer license ----------------------------------------------------

    def _safe_failure(self, action, path):
        """Log the technical failure while giving the customer a stable recovery message."""
        logging.exception("FleetSheet %s failure at %s", action, path)
        return "FleetSheet could not complete that action. Nothing was changed."

    # Main GET route table: first match wins, in original chain order.
    _GET_DISPATCH = [
        ("exact", '/eula', "_get_eula"),
        ("exact", '/welcome', "_get_welcome"),
        ("exact", '/pin/forgot', "_get_pin_forgot"),
        ("exact", '/pin/lock', "_get_pin_lock"),
        ("exact", '/setup/options', "_get_setup_options"),
        ("exact", '/money/all', "_get_money_all"),
        ("get_routes", None, "_get_tab_route"),
        ("exact", '/d', "_get_yard_home"),
        ("prefix", '/d/ticket/', "_get_yard_ticket"),
        ("exact", '/d/forget', "_get_yard_forget"),
        ("prefix", '/d/', "_get_yard_device"),
        ("prefix", '/photo/', "_get_photo"),
        ("prefix", '/doc/', "_get_doc"),
        ("prefix", '/invoicedoc/', "_get_invoicedoc"),
        ("prefix", '/jobdoc/', "_get_jobdoc"),
        ("any_prefix", None, "_get_prefix_route"),
        ("exact", '/phone.html', "_get_phone_html"),
        ("exact", '/phone.url', "_get_phone_url"),
        ("exact", '/logo.jpg', "_get_logo_jpg"),
        ("prefix", '/print/', "_get_print"),
        ("exact", '/done/dump', "_get_done_dump"),
        ("exact", '/export/run', "_get_export_run"),
        ("exact", '/backup/download', "_get_backup_download"),
        ("exact", '/export/custom/run', "_get_export_custom_run"),
        ("prefix", '/export/custom/', "_get_export_custom"),
        ("prefix", '/export/report/', "_get_export_report"),
        ("prefix", '/export/saved/', "_get_export_saved"),
        ("prefix", '/export/', "_get_export"),
        ("fallback", None, "_get_missing"),
    ]


    def _dispatch_get(self, con, q, flash, name, path):
        for kind, pattern, meth in self._GET_DISPATCH:
            if kind == "exact" and path != pattern:
                continue
            if kind == "prefix" and not path.startswith(pattern):
                continue
            if kind == "get_routes" and path not in GET_ROUTES:
                continue
            if kind == "any_prefix" and not any(
                    path.startswith(p) for p, _ in GET_PREFIX_ROUTES):
                continue
            getattr(self, meth)(con, q, flash, name, path)
            return

    def _get_eula(self, con, q, flash, name, path):
        self._send(page("License agreement", self._render_eula(), name, path))

    def _get_welcome(self, con, q, flash, name, path):
        if not engine.pin_is_set(con):
            self._send(page("Welcome", self.view_welcome(con, q), name, path))
        else:
            self._redirect("/")
        return

    def _get_pin_forgot(self, con, q, flash, name, path):
        self._send(page("Reset PIN", flash + self.view_pin_forgot(con, q), name, path))

    def _get_pin_lock(self, con, q, flash, name, path):
        # Idle lock (Jason 2026-10-15): clear the PIN session and send
        # the browser to /pin. Reuses the PIN gate — no second auth.
        # The desk JS only navigates here after inactivity, and never
        # from auth/onboarding pages.
        nxt = q.get("next") or "/invoices"
        if not nxt.startswith("/") or nxt.startswith("//"):
            nxt = "/invoices"
        self._redirect("/pin?next=" + quote_plus(nxt),
                       cookie=f"{self.PIN_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0")

    def _get_setup_options(self, con, q, flash, name, path):
        self._redirect("/setup/devices")
        return

    def _get_money_all(self, con, q, flash, name, path):
        self._redirect("/money")
        return

    def _get_tab_route(self, con, q, flash, name, path):
        title, view_fn = GET_ROUTES[path]
        # The one ticker stands on Today only (Jason 2026-10-26,
        # build 'x'): no other page is fed a strip. Today is the
        # special page — the one to work from — and its pool
        # captures every alert family in the build. (Build 'w' had
        # already taken the strip off the Invoices tab; 'x' retires
        # the Billing and Reports feeds and the Assets page's own
        # ticker outright: some pages having a ticker and some not
        # broke the universality rules.)
        alerts = None
        alert_total = None
        if path == "/":
            try:
                alerts, alert_total = engine.alerts_for(con, "dash")
            except Exception:
                # Never break the page over the news strip — but say so
                # in the server log instead of swallowing it silently.
                logging.getLogger("fleetsheet.alerts").exception(
                    "alert engine failed for %s", path)
                alerts = None
        top_items = None
        if path == "/":
            try:
                top_items = engine.top_of_day(con, 1)
                # The strip's Snooze steppers use the standard snooze
                # (2026-10-17, Jason): one default everywhere —
                # the same ack_snooze_minutes the steppers open
                # at and teach. No bespoke defaults. Laptop-pass fix
                # round (2026-10-20): every shown alert carries a
                # stepper now, so the standard is stamped onto the
                # alert pool too, not just the hero.
                try:
                    std_minutes = int(engine.get_option(
                        con, "ack_snooze_minutes", "30") or 30)
                except (TypeError, ValueError):
                    std_minutes = 30
                for it in (top_items or []):
                    it["snooze_minutes"] = std_minutes
            except Exception:
                logging.getLogger("fleetsheet.alerts").exception(
                    "top-of-day failed for dashboard strip")
                top_items = None
        if alerts:
            # Same standard for the alert pool on the Today strip
            # (laptop-pass fix round): every row carries a stepper.
            try:
                _std = int(engine.get_option(
                    con, "ack_snooze_minutes", "30") or 30)
            except (TypeError, ValueError):
                _std = 30
            for it in alerts:
                if isinstance(it, dict):
                    it.setdefault("snooze_minutes", _std)
        try:
            ticker_cats = engine.get_ticker_cats(con)
        except Exception:
            ticker_cats = None
        try:
            mods = {n: engine.module_on(con, n) for n in engine.MODULE_NAMES}
        except Exception:
            mods = None
        body = view_fn(self, con, q)
        if body is None:
            # The view already sent its response (e.g. a redirect-only
            # route like /quotes -> /ticket/new?kind=quote). Sending
            # anything more would put a second response on the same
            # keep-alive connection and poison it — and the old code
            # crashed here with TypeError: str + NoneType, which the
            # do_GET handler then answered with a second redirect.
            return
        if (q or {}).get("frag") == "1":
            # Batch 3 #7: the in-page View box fetches the list WITHOUT
            # the page shell — no app header/nav, no news strip, no
            # footer, no nested audit popup. base target=_top makes
            # rows/forms inside the fragment navigate the main window,
            # never spawn a window or drill down inside the box.
            doc = ("<!doctype html><html><head><meta charset=utf-8>"
                   f"<title>{html.escape(title)}</title>"
                   f"<style>{views_core.CSS}</style>"
                   f"{views_core._text_size_style()}"
                   # Popup print (Jason 2026-10-24): inside a fragment,
                   # only the filter box is chrome — drawer form fields
                   # print, filled or blank, so the page is writable.
                   "<style>@media print{#auditq{display:none!important}}</style>"
                   "<base target=\"_top\"></head>"
                   f"<body class=\"{views_core._body_classes()}\">"
                   f"<main style=\"padding:12px\">{views_core.print_head(name, title)}{body}</main>"
                   "</body></html>")
            self._send(doc)
            return
        self._send(page(title, flash + body, name, path,
                        alerts=alerts, top_items=top_items,
                        alert_total=alert_total, cats=ticker_cats, mods=mods))

    def _get_yard_home(self, con, q, flash, name, path):
        dev, reason = self._device(con)
        if dev:
            self._send(self.view_device_home(con, dev))
        else:
            self._send(self._device_denied(reason), 403)

    def _get_yard_ticket(self, con, q, flash, name, path):
        dev, reason = self._device(con)
        if dev:
            tid = path[len("/d/ticket/"):]
            self._send(self.view_device_ticket(con, dev, tid, flash))
        else:
            self._send(self._device_denied(reason), 403)

    def _get_yard_forget(self, con, q, flash, name, path):
        self._redirect("/?msg=" + quote_plus("Yard device signed out"),
                       cookie=f"{self.DEVICE_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0")

    def _get_yard_device(self, con, q, flash, name, path):
        token = path[len("/d/"):].strip()
        ok, reason, dev = engine.device_check(con, token)
        if ok:
            engine.touch_device(con, token)
            self._redirect("/d", cookie=f"{self.DEVICE_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=31536000")
        else:
            self._send(self._device_denied(reason), 403)

    def _get_photo(self, con, q, flash, name, path):
        parts = path.split("/")
        got = None
        if len(parts) == 4:
            got = engine.read_ticket_photo(con, unquote(parts[2]), parts[3])
        if got:
            blob, ctype = got
            self._send_bytes(blob, ctype)
        else:
            self._redirect("/?err=" + quote_plus("Photo not found"))

    def _get_doc(self, con, q, flash, name, path):
        parts = path.split("/")
        got = None
        if len(parts) == 3:
            try:
                got = engine.read_unit_doc(con, int(parts[2]))
            except (TypeError, ValueError):
                got = None
        if got:
            row, blob = got
            self._send_bytes(blob, row["mime"] or "application/octet-stream")
        else:
            self._redirect("/?err=" + quote_plus("Document not found"))

    def _get_invoicedoc(self, con, q, flash, name, path):
        parts = path.split("/")
        got = None
        if len(parts) == 4:
            try:
                got = engine.read_invoice_doc(con, unquote(parts[2]), parts[3])
            except (TypeError, ValueError):
                got = None
        if got:
            row, blob = got
            self._send_bytes(blob, row["mime"] or "application/octet-stream")
        else:
            self._redirect("/?err=" + quote_plus("Paperwork not found"))

    def _get_jobdoc(self, con, q, flash, name, path):
        # A summary Paperwork link (build 'af'): serve one job
        # attachment by its stored name from the shared document
        # folder. The name is a bare filename from the folder scan —
        # any path separator or traversal is refused outright.
        import mimetypes
        from pathlib import Path
        stored = unquote(path[len("/jobdoc/"):])
        p = None
        if stored and Path(stored).name == stored:
            cand = Path(engine.doc_dir()) / stored
            if cand.is_file():
                p = cand
        if p is not None:
            self._send_bytes(
                p.read_bytes(),
                mimetypes.guess_type(p.name)[0]
                or "application/octet-stream")
        else:
            self._redirect("/?err=" + quote_plus("Paperwork not found"))

    def _get_prefix_route(self, con, q, flash, name, path):
        prefix, handler = next(pair for pair in GET_PREFIX_ROUTES if path.startswith(pair[0]))
        # Build 'ab': decode the id the way the app's own links encode
        # it (quote_plus). Revision numbers ("WO-1001 Rev. 1") always
        # carry spaces; without the decode they landed on blank forms.
        item_id = unquote_plus(path[len(prefix):])
        try:
            title, body = handler(self, con, item_id, q)
        except TypeError:
            title, body = handler(self, con, item_id)
        self._send(page(title, flash + body, name, path))

    def _get_phone_html(self, con, q, flash, name, path):
        urls = lan_urls()
        target = urls[0] if urls else "http://127.0.0.1:8765"
        doc = (
            "<!doctype html><html><head><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>Open FleetSheet</title>"
            "<style>body{font:18px/1.4 Calibri,Segoe UI,sans-serif;margin:0;padding:32px 20px;"
            "background:#f4f6f9;color:#1a1a1a;text-align:center}"
            "a.big{display:block;background:#1B2A4A;color:#fff;text-decoration:none;"
            "padding:18px 16px;border-radius:8px;font-size:20px;margin:24px 0}"
            "p{color:#5C6B7A;font-size:14px}</style></head><body>"
            "<p>Yard book on the shop Wi-Fi</p>"
            f"<a class=big href='{html.escape(target)}'>Open FleetSheet</a>"
            "<p>Same Wi-Fi as the desk PC.</p>"
            "</body></html>"
        )
        # An open launcher page counts as "FleetSheet is open" too.
        doc = doc.replace("</body></html>",
                          f"<script>window.FS_IDLE_MINS={views_core.IDLE_MINS};window.FS_LOCK_MINS={views_core.LOCK_MINS};</script>"
                          + views_core.HEARTBEAT_JS + "</body></html>", 1)
        self._send_bytes(doc.encode("utf-8"), "text/html; charset=utf-8", "FleetSheet-phone.html")

    def _get_phone_url(self, con, q, flash, name, path):
        urls = lan_urls()
        target = urls[0] if urls else "http://127.0.0.1:8765"
        body = f"[InternetShortcut]\r\nURL={target}\r\n"
        self._send_bytes(body.encode("ascii"), "application/internet-shortcut", "FleetSheet.url")

    def _get_logo_jpg(self, con, q, flash, name, path):
        self._send_bytes(printpack.LOGO_BYTES, "image/jpeg")

    def _get_print(self, con, q, flash, name, path):
        self._handle_print(con, path, q)

    def _get_done_dump(self, con, q, flash, name, path):
        self._handle_done_dump(con, q)

    def _get_export_run(self, con, q, flash, name, path):
        self._handle_export_run(con, q)

    def _get_backup_download(self, con, q, flash, name, path):
        blob = engine.read_backup_file(con, q.get("f") or "")
        ctype = ("application/zip" if str(q.get("f") or "").lower().endswith(".zip")
                 else "application/x-sqlite3")
        self._send_bytes(blob, ctype, q.get("f"))

    def _get_export_custom_run(self, con, q, flash, name, path):
        self._handle_custom_run(con, None, q)

    def _get_export_custom(self, con, q, flash, name, path):
        self._handle_custom_run(con, path.rsplit("/", 1)[-1], q)

    def _get_export_report(self, con, q, flash, name, path):
        self._handle_report_file(con, path.rsplit("/", 1)[-1], q)

    def _get_export_saved(self, con, q, flash, name, path):
        self._handle_export_saved_run(con, path.rsplit("/", 1)[-1])

    def _get_export(self, con, q, flash, name, path):
        self._handle_export(con, path)

    def _get_missing(self, con, q, flash, name, path):
        self._send(page("Missing", "<p>No such page.</p>", name, path), 404)

    def do_GET(self):
        u = urlparse(self.path)
        path, q = u.path, {k: v[0] for k, v in parse_qs(u.query).items()}
        if path == "/favicon.ico":
            # Brand the app-mode window's taskbar/dock icon with the
            # FleetSheet mark instead of the browser's globe. Exempt from
            # every gate: it's just the logo, no DB needed.
            # Termination rule (spinner fix 2026-10-13): every response
            # sends Content-Length and returns exactly once. This block
            # once fell through and sent a second Missing-page response
            # on the same keep-alive connection, poisoning it.
            try:
                import base64
                import logo_data
                raw = base64.b64decode("".join(logo_data.LOGO_JPEG))
                self._send_bytes(raw, "image/jpeg")
            except Exception:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
            return
        if path == "/manual":
            # Operation Manual PDF (Jason 2026-10-07)
            try:
                with open("manual.pdf", "rb") as mf:
                    self._send_bytes(mf.read(), "application/pdf")
            except Exception:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
            return
        if path.startswith("/fonts/inter-") and path.endswith(".ttf"):
            # Bundled Inter typeface (offline-safe). Exempt from every gate:
            # it's just a font file, no DB needed. (2026-10-06)
            try:
                import os as _os
                _fp = _os.path.join(_os.path.dirname(__file__), "fonts",
                                    _os.path.basename(path))
                if not _os.path.isfile(_fp):
                    raise FileNotFoundError(_fp)
                with open(_fp, "rb") as _f:
                    self._send_bytes(_f.read(), "font/ttf")
            except Exception:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
            return
        if path == "/version":
            # Build stamp for the launcher's version check. Exempt from every
            # gate: no DB, no identity, just the stamp. Old builds (no such
            # endpoint) 404, which the launcher treats as a version mismatch.
            body = ('{"version":%s}' % json.dumps(APP_VERSION)).encode("ascii")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/company-logo":
            # Company logo for the header brand — uploaded on Setup.
            # No user logo set: serve the FleetSheet logo (logo_data)
            # so the header img always resolves and the mark gets seen
            # when the user hasn't uploaded their own. The old
            # 404-without-Content-Length hung the img request forever
            # and kept the tab spinner going on every page.
            # Setup's "Current logo" display is gated on a user-set
            # logo, so the FleetSheet default never shows there.
            # A terminated 404 is returned only if even the logo
            # module fails to load.
            try:
                import base64
                c2 = engine.connect()
                try:
                    raw_b64 = engine.get_option(c2, "company_logo", "")
                    mime = engine.get_option(c2, "company_logo_mime", "image/png")
                finally:
                    c2.close()
                if raw_b64:
                    self._send_bytes(base64.b64decode(raw_b64), mime or "image/png")
                else:
                    import logo_data
                    self._send_bytes(
                        base64.b64decode("".join(logo_data.LOGO_JPEG)),
                        "image/jpeg")
            except Exception:
                try:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                except Exception:
                    pass
            return
        con = engine.connect()
        try:
            engine.init_db(con)
            co = self.company(con)
            name = co["dba"] or co["name"]
            try:
                views_core.TIPS_ON = int(co["tooltips"]) != 0
            except Exception:
                views_core.TIPS_ON = True
            _ts = engine.get_option(con, "ui_text_size", "standard")
            views_core.TEXT_SIZE = _ts if _ts in ("standard", "large", "xlarge") else "standard"
            # Desk idle lock: 0 when no PIN is set (nothing to lock).
            views_core.LOCK_MINS = (0 if not engine.pin_is_set(con)
                                    else views_core.desk_lock_mins(con))
            msg = q.get("msg", "")
            err = q.get("err", "")
            flash = (f'<div class="ok">{html.escape(msg)}</div>' if msg else "") + (
                f'<div class="err">{html.escape(err)}</div>' if err else ""
            )
            # A browser holding a valid yard-device cookie IS a yard device:
            # keep it inside the yard UI, never on desk pages.
            if path != "/d" and not path.startswith("/d/"):
                dev, _ = self._device(con)
                if dev:
                    self._redirect("/d?msg=" + quote_plus(
                        "Yard device mode — desk pages are disabled on this device"))
                    return
            # Consumer license gate: desk pages need a click-to-accept first.
            if (path != "/eula" and not path.startswith("/d")
                    and _eula_required() and not _eula_accepted()):
                self._redirect("/eula")
                return
            # First-run onboarding: after the EULA, collect the desk PIN before
            # anything else. Upgrading users without a PIN get the same prompt
            # once. Exempt the welcome page itself, the PIN setup POST target,
            # and yard routes. Test harnesses bypass via FLEETSHEET_TEST_MODE.
            # (2026-10-06)
            if (_eula_required() and _eula_accepted()
                    and not os.environ.get("FLEETSHEET_TEST_MODE") == "1"
                    and not engine.pin_is_set(con)
                    and path not in ("/welcome", "/eula", "/setup/security/pin",
                                     "/pin", "/pin/forgot")
                    and not path.startswith("/d")):
                self._redirect("/welcome")
                return
            # Desk PIN gate for the money pages (yard routes are never gated).
            if not self._pin_gate(con, path):
                return
            self._dispatch_get(con, q, flash, name, path)
        except Exception:
            msg = quote_plus(self._safe_failure("page", path))
            self._redirect(self._action_parent(path) + "?err=" + msg)
        finally:
            con.close()

    def do_POST(self):
        u = urlparse(self.path)
        if u.path == "/heartbeat":
            # "I'm still here" from every open FleetSheet page. Exempt from
            # every gate: PIN, EULA, yard-device. A yard heartbeat (fsdev
            # cookie present) is noted so the desk can see connected devices
            # and the close-grace knows who to warn — but only when the
            # token passes device_check; a fake/stale/revoked cookie gets a
            # 400 and creates no phantom yard client. The reply is always
            # JSON carrying the live yard-client count (the desk uses it to
            # show/hide its yard note and arm the close warning); during the
            # close-grace window it also carries the shutdown countdown.
            _tok = self._cookies().get(self.DEVICE_COOKIE, "")
            if _tok:
                _hc = engine.connect()
                try:
                    _ok, _, _ = engine.device_check(_hc, _tok)
                finally:
                    _hc.close()
                if _ok:
                    _note_yard_heartbeat(_tok)
                else:
                    self.send_response(400)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
            _yn = _yard_active_count()
            if SHUTDOWN_AT is not None:
                remain = max(0, int(SHUTDOWN_AT - time.time()))
                body = ('{"shutdown_in":%d,"yard_clients":%d}' % (remain, _yn)).encode("ascii")
            else:
                body = ('{"yard_clients":%d}' % _yn).encode("ascii")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        ctype = self.headers.get("Content-Type") or ""
        if ctype.startswith("multipart/form-data"):
            data, self._files = self._multipart()
        else:
            data, self._files = self._form(), {}
        con = engine.connect()
        try:
            engine.init_db(con)
            # Yard devices may only POST inside /d/*.
            if not u.path.startswith("/d/"):
                dev, _ = self._device(con)
                if dev:
                    self._redirect("/d?msg=" + quote_plus(
                        "Yard device mode — desk pages are disabled on this device"))
                    return
            # Consumer license gate (yard routes exempt).
            if (u.path != "/eula" and not u.path.startswith("/d/")
                    and _eula_required() and not _eula_accepted()):
                self._redirect("/eula")
                return
            if u.path == "/eula":
                self._accept_eula(data)
                return
            if u.path == "/pin/nagoff":
                self._redirect("/", "pin_nag=off; Path=/")
                return
            # Desk PIN gate for money POSTs (yard routes and PIN pages exempt).
            if u.path not in ("/pin", "/pin/logout", "/pin/forgot", "/pin/nagoff", "/setup/security/pin"):
                if not self._pin_gate(con, u.path, is_post=True):
                    return
            if u.path == "/updater/check":
                # Admin → "Check for Updates…" — menu-only (decision B).
                # Availability is checked synchronously (no DLL load);
                # the check itself runs on a worker thread so the page
                # returns at once while WinSparkle shows its dialog.
                if updater_winsparkle is not None and updater_winsparkle.available():
                    threading.Thread(target=updater_winsparkle.check_now,
                                     daemon=True).start()
                    self._redirect("/setup/admin?msg=" + quote_plus(
                        "Checking for updates…"))
                else:
                    self._redirect("/setup/admin?msg=" + quote_plus(
                        "Update checks are not available in this install."))
                return
            handled = (post_core.handle_post(self, con, data, u)
                       or post_assets.handle_post(self, con, data, u)
                       or post_accounting.handle_post(self, con, data, u)
                       or post_compliance.handle_post(self, con, data, u))
            if not handled:
                self._redirect("/?err=Unknown+action")
        except ValueError as e:
            # Validation failures (Issue 1, 2026-10-15): show the real
            # reason — the message the validator raised — instead of the
            # generic banner. Validators only raise user-facing text.
            target = self._action_parent(u.path.split("?")[0])
            msg = quote_plus(str(e) or "That didn't save — check the fields and try again.")
            self._redirect(target + "?err=" + msg)
        except Exception:
            # B6: a failed nested action (e.g. POST /credit/apply) must land
            # back on a real page, not on the action URL itself (which has no
            # GET view and renders "unknown"). Technical details belong in
            # the server log, not in the customer's URL or screen.
            target = self._action_parent(u.path.split("?")[0])
            msg = quote_plus(self._safe_failure("action", u.path))
            self._redirect(target + "?err=" + msg)
        finally:
            con.close()

def main():
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleTitleW("FleetSheet")
        except Exception:
            pass
    try:
        (engine.DB_PATH.parent / "fleetsheet.pid").write_text(str(os.getpid()), encoding="ascii")
    except OSError:
        pass
    engine.init_db()
    if engine.connect().execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 0:
        print("Database empty. Fill Setup, then Customers, Units, Sites.")
    # Automatic safety net: back the book up on startup when the last backup
    # is older than 7 days (or never happened). Never blocks serving.
    # Also sweeps photo/doc files nothing references anymore.
    try:
        _bcon = engine.connect()
        try:
            if engine.backup_status(_bcon)["stale"]:
                _dest = engine.run_backup(_bcon, "auto")
                print(f"Auto book backup: {_dest}")
            else:
                engine.prune_backups(_bcon)
            _orphans = engine.sweep_orphan_photos(_bcon)
            if _orphans:
                print(f"Removed {_orphans} orphan photo file(s)")
            _dorphans = engine.sweep_orphan_docs(_bcon)
            if _dorphans:
                print(f"Removed {_dorphans} orphan document file(s)")
        finally:
            _bcon.close()
    except Exception as e:
        print(f"Auto backup skipped ({e})")
    # Bind policy: localhost is the safe default for a single-PC install.
    # Set FLEETSHEET_BIND=lan (or an explicit IP) when phones/tablets need
    # access over the yard LAN. This makes network exposure an intentional
    # deployment choice instead of an implicit side effect of startup.
    bind_mode = os.environ.get("FLEETSHEET_BIND", "localhost").strip().lower()
    if bind_mode in ("lan", "0.0.0.0", "all"):
        host = "0.0.0.0"
    elif bind_mode in ("localhost", "127.0.0.1", "local", ""):
        host = "127.0.0.1"
    else:
        host = os.environ.get("FLEETSHEET_BIND", "127.0.0.1").strip()
    port = int(os.environ.get("FLEETSHEET_PORT", "8765"))
    print(f"FleetSheet bind -> {host}:{port}")
    print(f"FleetSheet desk  -> http://127.0.0.1:{port}")
    for u in lan_urls(port):
        print(f"Phone / tablet  -> {u}")
    print("Stop: Close FleetSheet — close this window, Ctrl+C, or just close the FleetSheet window;")
    print("      the server stops with it.")

    def _open():
        # FleetSheet opens in its own app-mode window (Chrome/Edge --app with
        # a dedicated profile): no tabs, no address bar — it feels like a
        # desktop app, not a website. Falls back to the default browser.
        # The window IS the session: when its browser process exits, the
        # watcher stops the server (at once, or after the close-grace
        # window when yard devices are still connected). (Default-browser
        # fallback and pre-existing-profile launches have no process to
        # watch.)
        try:
            import appmode
            mode, handle = appmode.open_app_window_proc(
                f"http://127.0.0.1:{port}")
        except Exception:
            return
        if handle == "poll":
            # macOS: `open -n` gives no handle — poll for the profile's
            # browser process instead.
            threading.Thread(target=_watch_macos_profile, args=(_HTTPD,),
                             daemon=True).start()
        elif handle is not None:
            threading.Thread(target=_watch_browser_proc, args=(_HTTPD, handle),
                             daemon=True).start()

    if not os.environ.get("FLEETSHEET_NO_AUTO_OPEN"):
        threading.Timer(0.8, _open).start()
    global _HTTPD
    _HTTPD = ThreadingHTTPServer((host, port), Handler)
    # Updater (WinSparkle, Windows-only, menu-only): configure after the
    # server binds. Never breaks startup — every failure is a silent
    # no-op inside the wrapper (DLL absent, not Windows, placeholder key).
    if updater_winsparkle is not None:
        try:
            def _updater_shutdown():
                # WinSparkle calls this when the operator accepts an
                # update: stop the HTTP server so the new installer can
                # replace the app. Worker thread + small delay lets
                # WinSparkle proceed; shutdown() must not run on the
                # serve_forever thread.
                def _stop():
                    time.sleep(0.5)
                    try:
                        _HTTPD.shutdown()
                    except Exception:
                        pass
                threading.Thread(target=_stop, daemon=True).start()
            updater_winsparkle.init(APP_VERSION,
                                    on_shutdown_request=_updater_shutdown)
        except Exception:
            pass
    _HTTPD.serve_forever()


if __name__ == "__main__":
    main()
