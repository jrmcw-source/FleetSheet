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
import socket
import subprocess
import threading
import time
import hmac
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, quote_plus, unquote, urlparse

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
main{max-width:1180px;margin:14px auto;padding:0 14px 40px}
.actions{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:12px 0}
.mark{position:fixed;bottom:8px;right:12px;font-size:11px;letter-spacing:.08em;color:#1B2A4A;opacity:.28;pointer-events:none;z-index:1}
.tabs{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 12px;padding-bottom:8px;border-bottom:1px solid #d0d5dd}
.tabs a{display:inline-block;padding:5px 9px;border-radius:4px;background:#fff;border:1px solid #d0d5dd;color:var(--frame);text-decoration:none;font-size:13px;position:relative}
.tabs a.on{background:var(--frame);color:#fff;border-color:var(--frame)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:9px}
.card{background:#fff;border:1px solid #d0d5dd;border-radius:6px;padding:11px}
.card b{display:block;font-size:22px;color:var(--frame)}
.card span{color:var(--mute);font-size:12px;text-transform:uppercase}
form,table{background:#fff;border:1px solid #d0d5dd;border-radius:6px;padding:11px;width:100%}
label{display:block;font-size:12px;color:var(--mute);margin:7px 0 3px}
label:has(input[type=checkbox]){display:flex;align-items:center;gap:6px;font-size:14px;color:var(--ink,#222)}
input,select{width:100%;padding:7px;border:1px solid #c5cdd6;border-radius:4px;font:inherit}
input[type=checkbox]{width:auto;flex:0 0 auto}
.row{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}
button,.btn{background:var(--frame);color:#fff;border:0;padding:8px 13px;border-radius:4px;cursor:pointer;font:inherit;display:inline-block;text-decoration:none}
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
fieldset{border:1px solid #d0d5dd;border-radius:6px;background:#fff;padding:8px 11px 11px;margin:10px 0}fieldset legend{padding:0 6px;font-weight:700;color:var(--frame)}details{border:1px solid #d0d5dd;border-radius:8px;background:#fff;padding:10px 14px;margin:12px 0}details summary{cursor:pointer;color:var(--frame);padding:2px 0}h1{font-size:19px;color:var(--frame);margin:6px 0 10px}
.hint{color:var(--mute);font-size:13px}
.eyebrow{display:block;font-size:11px;letter-spacing:.08em;font-weight:700;color:var(--mute);margin-bottom:3px}
.onboarding{border-left:4px solid var(--gold);margin-bottom:16px;display:grid;grid-template-columns:minmax(260px,1fr) minmax(260px,1fr);gap:18px;align-items:start}
.onboarding h2{margin:0;color:var(--frame);font-size:20px}
.setupsteps{display:grid;gap:7px}
.setupstep{display:flex;gap:9px;align-items:center;padding:8px 10px;background:#f7f9fb;border-radius:6px}
.setupstep a{color:var(--frame);font-weight:600;text-decoration:none}
.setupstep.done{color:var(--ok)}
.setupstep.done span:last-child{color:var(--mute);text-decoration:line-through}
@media (max-width:700px){.onboarding{grid-template-columns:1fr}}
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

import views_core
import views_accounting
import views_assets
import views_compliance
import views_health
import post_core
import post_assets
import post_accounting
import post_compliance
from views_core import lan_urls, page

GET_ROUTES = {
    "/": ("Today", lambda self, con, q: self.view_dash(con, q)),
    "/today/all": ("Everything", lambda self, con, q: self.view_today_all(con)),
    "/money": ("Billing", lambda self, con, q: self.view_money(con, q)),
    "/money/audit": ("All money — audit", lambda self, con, q: self.view_money_audit(con)),
    "/money/invoices/audit": ("Invoices audit", lambda self, con, q: self.view_money_invoices_audit(con)),
    "/money/payments/audit": ("Payments audit", lambda self, con, q: self.view_money_payments_audit(con)),
    "/money/credits/audit": ("Credit memos audit", lambda self, con, q: self.view_money_credits_audit(con)),
    "/money/petty/audit": ("Petty cash audit", lambda self, con, q: self.view_money_petty_audit(con)),
    "/tickets": ("Tickets", lambda self, con, q: self.view_tickets(con, q.get("flag"))),
    "/ticket/new": ("Rentals", lambda self, con, q: self.view_new_ticket(con, q)),
    "/quotes": ("Quotes", lambda self, con, q: self._redirect("/ticket/new?kind=quote")),
    "/quote/new": ("New quote", lambda self, con, q: self._redirect("/ticket/new?kind=quote")),
    "/changes": ("Change orders", lambda self, con, q: self._redirect("/ticket/new?kind=change")),
    "/invoice/new": ("New invoice", lambda self, con, q: self.view_money(con, {"tab": "invoice"})),
    "/pay": ("Record payment", lambda self, con, q: self.view_money(con, {"tab": "pay"})),
    "/credit": ("Credit memo", lambda self, con, q: self.view_money(con, dict(q or {}, tab="credit"))),
    "/petty": ("Petty cash", lambda self, con, q: self.view_money(con, {"tab": "petty"})),
    "/setup": ("Setup", lambda self, con, q: self.view_setup(con, q)),
    "/setup/vendors": ("Vendors", lambda self, con, q: self.view_setup_vendors(con, q)),
    "/setup/vendors/all": ("All vendors", lambda self, con, q: self.view_vendors_all(con)),
    "/setup/admin": ("Administration", lambda self, con, q: self.view_setup_admin(con, q)),
    "/setup/billing": ("Billing setup", lambda self, con, q: self.view_setup_billing(con, q)),
    "/setup/health": ("Data Health", lambda self, con, q: self.view_health(con)),
    "/setup/devices": ("Devices", lambda self, con, q: self.view_devices(con, q)),
    "/setup/complete": ("Setup Complete", lambda self, con, q: self.view_setup_complete(con)),
    "/setup/devices/show": ("Device QR", lambda self, con, q: self.view_device_show(
        con, q.get("token", ""), engine.get_option(con, "device_base_url", ""))),
    "/customers": ("Customers", lambda self, con, q: self.view_customers(con)),
    "/customers/all": ("All customers", lambda self, con, q: self.view_customers_all(con)),
    "/customer/new": ("New customer", lambda self, con, q: self.view_customer_form(con, None)),
    "/units": ("Units", lambda self, con, q: self._redirect("/assets/all")),
    "/assets": ("Assets", lambda self, con, q: self.view_assets(con)),
    "/assets/all": ("All assets", lambda self, con, q: self.view_assets_all(con)),
    "/unit/new": ("New unit", lambda self, con, q: self.view_unit_form(con, None)),
    "/sites": ("Sites", lambda self, con, q: self.view_sites(con)),
    "/sites/all": ("Job sites — all", lambda self, con, q: self.view_sites_all(con)),
    "/site/new": ("New site", lambda self, con, q: self.view_site_form(con, None, q)),
    "/wos": ("Work orders", lambda self, con, q: self._redirect("/ticket/new?kind=workorder")),
    "/wo/new": ("New work order", lambda self, con, q: self._redirect("/ticket/new?kind=workorder")),
    "/invoices": ("Invoices", lambda self, con, q: self.view_invoices(con)),
    "/export": ("Data", lambda self, con, q: self.view_export(con, q)),
    "/reports/weekly/money": ("Weekly money", lambda self, con, q: self.view_report_weekly_money(con)),
    "/reports/weekly/fleet": ("Fleet utilization", lambda self, con, q: self.view_report_weekly_fleet(con, q)),
    "/reports/weekly/flow": ("This week's flow", lambda self, con, q: self.view_report_weekly_flow(con, q)),
    "/backup": ("Backups", lambda self, con, q: self.view_backups(con)),
    "/health": ("System Health", lambda self, con, q: self.view_health(con)),
    "/billing": ("Billing", lambda self, con, q: self._redirect("/money")),
    "/rentals": ("Rentals", lambda self, con, q: self._redirect("/ticket/new")),
    "/sale": ("Sale", lambda self, con, q: self.view_sale(con, q)),
    "/reports": (
        "Reports",
        lambda self, con, q: self.view_reports(
            con, int(q.get("days") or 14), q.get("p") or "mtd", q.get("from") or "", q.get("to") or "",
            q.get("b") or "avail", q.get("all") == "1"
        ),
    ),
    "/pin": ("Desk PIN", lambda self, con, q: self.view_pin(con, q)),
    "/done": ("Done log", lambda self, con, q: self.view_done(con, q)),
    "/today/done/other": ("Other done", lambda self, con, q: self.view_done_other(con, q)),
    "/setup/security": ("Security", lambda self, con, q: self.view_security(con, q)),
    "/compliance": ("Compliance", lambda self, con, q: self.view_compliance(con)),
    "/compliance/all": ("All compliance", lambda self, con, q: self.view_compliance_all(con)),
}

# Prefix routes for /kind/<id>: prefix -> handler(self, con, item_id) -> (title, body_html)
GET_PREFIX_ROUTES = [
    ("/ticket/", lambda self, con, tid: (tid, self.view_ticket(con, tid))),
    ("/quote/", lambda self, con, qn: (qn, self.view_quote_form(con, qn))),
    ("/invoice/", lambda self, con, ino: (ino, self.view_invoice_lines(con, ino))),
    ("/customer/", lambda self, con, cid: (cid, self.view_customer_form(con, cid))),
    ("/unit/", lambda self, con, aid: (aid, self.view_unit_form(con, aid))),
    ("/site/", lambda self, con, sid: self.view_site_route(con, sid)),
    ("/wo/", lambda self, con, wid: (wid, self.view_wo_form(con, wid))),
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

# --- idle lifecycle -------------------------------------------------------
# Any open FleetSheet page (desk, yard, PIN-lock, EULA) POSTs /heartbeat once
# a minute. When every browser tab is closed the heartbeats stop, and the
# watchdog below checkpoints the WAL and shuts the server down instead of
# leaving it parked on the port. Closing the browser IS closing FleetSheet.
LAST_SEEN = time.time()
try:
    IDLE_TIMEOUT = int(os.environ.get("FLEETSHEET_IDLE_SECS", "300"))
except (TypeError, ValueError):
    IDLE_TIMEOUT = 300


def _stop_server(server, reason):
    """Checkpoint the WAL, drop the pidfile, and shut the HTTP server down.
    Shared by the idle watchdog and the app-window watcher."""
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


def _idle_watchdog(server):
    """Background: shut down after IDLE_TIMEOUT seconds with zero traffic."""
    while True:
        time.sleep(30)
        if time.time() - LAST_SEEN > IDLE_TIMEOUT:
            _stop_server(server, "idle — no open pages")
            return


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
# would be an instant false shutdown. The heartbeat backstop covers those.
_WINDOW_GRACE_SECS = 3


def _watch_browser_proc(server, proc):
    """Background: the app-mode window IS the session. When its browser
    process exits, stop the server at once instead of waiting out the idle
    timeout. Daemon thread; never blocks interpreter exit."""
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
        return  # never found it; the heartbeat backstop covers this
    while True:
        time.sleep(5)
        try:
            if target not in appmode.find_profile_pids(profile):
                break
        except Exception:
            return
    _begin_close_grace(server)
# --- end idle lifecycle ---------------------------------------------------


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
            "<p class='mute'>Please read and accept to use FleetSheet.</p>"
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
            self._redirect(dest + "?msg=" + quote_plus("License accepted — welcome to FleetSheet"))
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
        return "FleetSheet could not complete that action. Nothing was intentionally changed. Please try again; if it continues, check the server log."

    def do_GET(self):
        # Any traffic means somebody's there — heartbeat or not.
        global LAST_SEEN
        LAST_SEEN = time.time()
        u = urlparse(self.path)
        path, q = u.path, {k: v[0] for k, v in parse_qs(u.query).items()}
        if path == "/favicon.ico":
            # Brand the app-mode window's taskbar/dock icon with the
            # FleetSheet mark instead of the browser's globe. Exempt from
            # every gate: it's just the logo, no DB needed.
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
            # 404 when unset; the header img hides itself via onerror.
            try:
                import base64
                c2 = engine.connect()
                try:
                    raw_b64 = engine.get_option(c2, "company_logo", "")
                    mime = engine.get_option(c2, "company_logo_mime", "image/png")
                finally:
                    c2.close()
                if not raw_b64:
                    raise ValueError("no logo set")
                self._send_bytes(base64.b64decode(raw_b64), mime or "image/png")
            except Exception:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
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
            if path == "/eula":
                self._send(page("License agreement", self._render_eula(), name, path))
            elif path == "/welcome":
                # First-run onboarding: PIN setup right after the EULA.
                # Yard routes and the PIN setup POST are exempt from the gate below.
                if not engine.pin_is_set(con):
                    self._send(page("Welcome", self.view_welcome(con, q), name, path))
                else:
                    self._redirect("/")
                return
            elif path == "/pin/forgot":
                self._send(page("Reset PIN", flash + self.view_pin_forgot(con, q), name, path))
            elif path == "/setup/options":
                # Options merged into Devices — old links land there.
                self._redirect("/setup/devices")
                return
            elif path == "/money/all":
                # Old money hub folds into the new four-tab Money page.
                self._redirect("/money")
                return
            elif path in GET_ROUTES:
                title, view_fn = GET_ROUTES[path]
                # Per-tab news strip on the tab landing pages.
                strip_paths = {"/": "dash", "/money": "acct", "/reports": "reports"}
                alerts = None
                alert_total = None
                if path in strip_paths:
                    try:
                        alerts, alert_total = engine.alerts_for(con, strip_paths[path])
                    except Exception:
                        # Never break the page over the news strip — but say so
                        # in the server log instead of swallowing it silently.
                        logging.getLogger("fleetsheet.alerts").exception(
                            "alert engine failed for %s", strip_paths[path])
                        alerts = None
                top_items = None
                if path == "/":
                    try:
                        top_items = engine.top_of_day(con, 3)
                    except Exception:
                        logging.getLogger("fleetsheet.alerts").exception(
                            "top-of-day failed for dashboard strip")
                        top_items = None
                try:
                    ticker_cats = engine.get_ticker_cats(con)
                except Exception:
                    ticker_cats = None
                body = view_fn(self, con, q)
                if body is None:
                    # Redirect-alias routes (/quotes, /changes, /units, ...)
                    # answer the request themselves via _redirect and return
                    # None — there is no page to build. Without this guard the
                    # concatenation below raised a TypeError that the error
                    # handler logged as a page failure on every alias hit,
                    # crying wolf in the logs. (2026-10-08)
                    return
                self._send(page(title, flash + body, name, path,
                                alerts=alerts, top_items=top_items,
                                alert_total=alert_total, cats=ticker_cats))
            elif path == "/d":
                # Yard device home — needs the device cookie from a QR scan.
                dev, reason = self._device(con)
                if dev:
                    self._send(self.view_device_home(con, dev))
                else:
                    self._send(self._device_denied(reason), 403)
            elif path.startswith("/d/ticket/"):
                dev, reason = self._device(con)
                if dev:
                    tid = path[len("/d/ticket/"):]
                    self._send(self.view_device_ticket(con, dev, tid, flash))
                else:
                    self._send(self._device_denied(reason), 403)
            elif path == "/d/forget":
                # Drop the device cookie (e.g. desk user who opened a QR link).
                self._redirect("/?msg=" + quote_plus("Yard device signed out"),
                               cookie=f"{self.DEVICE_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0")
            elif path.startswith("/d/"):
                # Claim a device code: /d/<token> from the QR, then a cookie.
                token = path[len("/d/"):].strip()
                ok, reason, dev = engine.device_check(con, token)
                if ok:
                    engine.touch_device(con, token)
                    self._redirect("/d", cookie=f"{self.DEVICE_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=31536000")
                else:
                    self._send(self._device_denied(reason), 403)
            elif path.startswith("/photo/"):
                # Serve a ticket condition photo: /photo/<ticket_id>/out|in
                parts = path.split("/")
                got = None
                if len(parts) == 4:
                    got = engine.read_ticket_photo(con, unquote(parts[2]), parts[3])
                if got:
                    blob, ctype = got
                    self._send_bytes(blob, ctype)
                else:
                    self._redirect("/?err=" + quote_plus("Photo not found"))
            elif path.startswith("/doc/"):
                # Serve a data-book document: /doc/<doc_id>
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
            elif path.startswith("/invoicedoc/"):
                # Serve attached invoice paperwork: /invoicedoc/<invoice_no>/<kind>
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
            elif any(path.startswith(prefix) for prefix, _ in GET_PREFIX_ROUTES):
                prefix, handler = next(pair for pair in GET_PREFIX_ROUTES if path.startswith(pair[0]))
                item_id = path[len(prefix):]
                try:
                    title, body = handler(self, con, item_id, q)
                except TypeError:
                    title, body = handler(self, con, item_id)
                self._send(page(title, flash + body, name, path))
            elif path == "/phone.html":
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
                    "<p>Same Wi-Fi as the desk PC. After it opens: browser menu → Add to Home Screen.</p>"
                    "</body></html>"
                )
                # An open launcher page counts as "FleetSheet is open" too.
                doc = doc.replace("</body></html>",
                                  views_core.HEARTBEAT_JS + "</body></html>", 1)
                self._send_bytes(doc.encode("utf-8"), "text/html; charset=utf-8", "FleetSheet-phone.html")
            elif path == "/phone.url":
                urls = lan_urls()
                target = urls[0] if urls else "http://127.0.0.1:8765"
                body = f"[InternetShortcut]\r\nURL={target}\r\n"
                self._send_bytes(body.encode("ascii"), "application/internet-shortcut", "FleetSheet.url")
            elif path == "/logo.jpg":
                self._send_bytes(printpack.LOGO_BYTES, "image/jpeg")
            elif path.startswith("/print/"):
                self._handle_print(con, path, q)
            elif path == "/done/dump":
                self._handle_done_dump(con, q)
            elif path == "/export/run":
                self._handle_export_run(con, q)
            elif path == "/backup/download":
                blob = engine.read_backup_file(con, q.get("f") or "")
                ctype = ("application/zip" if str(q.get("f") or "").lower().endswith(".zip")
                         else "application/x-sqlite3")
                self._send_bytes(blob, ctype, q.get("f"))
            elif path == "/export/custom/run":
                # Ad-hoc custom build: field/filter params straight from the builder form.
                self._handle_custom_run(con, None, q)
            elif path.startswith("/export/custom/"):
                # Saved custom build re-run (Run uses the saved format; ?how= overrides).
                self._handle_custom_run(con, path.rsplit("/", 1)[-1], q)
            elif path.startswith("/export/report/"):
                # CSV/XLSX of a prebuilt weekly report (e.g. /export/report/aging.csv).
                self._handle_report_file(con, path.rsplit("/", 1)[-1], q)
            elif path.startswith("/export/saved/"):
                self._handle_export_saved_run(con, path.rsplit("/", 1)[-1])
            elif path.startswith("/export/"):
                self._handle_export(con, path)
            else:
                self._send(page("Missing", "<p>No such page.</p>", name, path), 404)
        except Exception:
            msg = quote_plus(self._safe_failure("page", path))
            self._redirect(self._action_parent(path) + "?err=" + msg)
        finally:
            con.close()

    def do_POST(self):
        # Any traffic means somebody's there — heartbeat or not.
        global LAST_SEEN
        LAST_SEEN = time.time()
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
            if u.path == "/update-check":
                # WinSparkle shows its own dialog on this machine. Where
                # the updater isn't live (no DLL / no key yet / not
                # Windows) the button reports that instead of pretending.
                _live = False
                try:
                    import updater_winsparkle
                    _live = updater_winsparkle.check_now()
                except Exception:
                    pass
                if _live:
                    self._redirect("/setup/admin?msg=" + quote_plus(
                        "Update check started — watch for the update window"))
                else:
                    self._redirect("/setup/admin?msg=" + quote_plus(
                        "Updates are not active in this build yet"))
                return
            # Desk PIN gate for money POSTs (yard routes and PIN pages exempt).
            if u.path not in ("/pin", "/pin/logout", "/pin/forgot", "/pin/nagoff", "/setup/security/pin"):
                if not self._pin_gate(con, u.path, is_post=True):
                    return
            handled = (post_core.handle_post(self, con, data, u)
                       or post_assets.handle_post(self, con, data, u)
                       or post_accounting.handle_post(self, con, data, u)
                       or post_compliance.handle_post(self, con, data, u))
            if not handled:
                self._redirect("/?err=Unknown+action")
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
    _idle_msg = (f"{IDLE_TIMEOUT // 60} idle minutes" if IDLE_TIMEOUT >= 60
                 else f"{IDLE_TIMEOUT} idle seconds")
    print("Stop: Close FleetSheet — close this window, Ctrl+C, or just close the FleetSheet window;")
    print(f"      the server stops with it (idle backstop: {_idle_msg}).")

    def _open():
        # FleetSheet opens in its own app-mode window (Chrome/Edge --app with
        # a dedicated profile): no tabs, no address bar — it feels like a
        # desktop app, not a website. Falls back to the default browser.
        # The window IS the session: when its browser process exits, the
        # watcher stops the server (at once, or after the close-grace
        # window when yard devices are still connected). (Default-browser
        # fallback and pre-existing-profile launches have no process to
        # watch — the idle backstop covers those.)
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
    # Idle watchdog: no open pages for IDLE_TIMEOUT seconds → checkpoint the
    # WAL and shut down. Daemon thread, so it never blocks interpreter exit.
    threading.Thread(target=_idle_watchdog, args=(_HTTPD,), daemon=True).start()
    # WinSparkle self-update (packaging/WINSPARKLE.md): live only on
    # Windows installs carrying WinSparkle.dll and a baked-in public key;
    # a no-op everywhere else. Never allowed to block or break startup.
    # Accepting an update calls _HTTPD.shutdown() from the updater's
    # thread so the new installer can replace files cleanly.
    try:
        import updater_winsparkle
        if updater_winsparkle.init(APP_VERSION, _HTTPD.shutdown):
            print("Update checks: on (WinSparkle)")
    except Exception:
        pass
    _HTTPD.serve_forever()


if __name__ == "__main__":
    main()
