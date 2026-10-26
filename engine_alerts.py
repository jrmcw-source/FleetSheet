"""The one news strip (Today): the guy tapping you on the shoulder.

Alerts are computed fresh from current conditions on every page load.
Each alert has a stable key. A customer can snooze an alert (default 3
hours, adjustable per tap) or dismiss it (default 7 days, adjustable per
tap) — dismiss kills that instance, not the condition: if the underlying
problem is still true when the ack expires, the shoulder-tap comes back.
"""
from __future__ import annotations
import sqlite3
import time
from datetime import date, timedelta

import engine_core as _core

__all__ = ["alerts_for", "ack_alert", "is_acked", "ladder_level", "TAP", "SLAP", "PUNCH",
           "get_ticker_cats", "set_ticker_cats", "TICKER_CATS", "CAT_LABELS",
           "list_snoozed", "unack_alert"]

SNOOZE_HOURS = 3
DISMISS_DAYS = 7
# A shoulder-tap, not a firehose: never more than this many shown.
# The Today strip shows up to five rows; anything past five is a
# quiet "+ N more".
STRIP_SHOW = 5

# Ticker categories: the operator chooses which kinds of shoulder-taps earn
# a slot on the strip. Money = invoices/POs, Rentals = open-ended rental
# contention, Compliance = shipping-paper problems. (2026-10-06)
TICKER_CATS = ("money", "rentals", "compliance")
CAT_LABELS = {"money": "Money", "rentals": "Rentals", "compliance": "Compliance"}
_TICKER_CATS_OPT = "ticker_cats"


def get_ticker_cats(con: sqlite3.Connection) -> set:
    """Enabled ticker categories. Defaults to all three when never set;
    an explicitly saved empty set means the strip is off."""
    _core._ensure_device_tables(con)
    row = con.execute("SELECT value FROM options WHERE key=?",
                      (_TICKER_CATS_OPT,)).fetchone()
    if row is None:
        return set(TICKER_CATS)
    raw = (row["value"] or "").strip()
    return {c.strip() for c in raw.split(",") if c.strip() in TICKER_CATS}


def set_ticker_cats(con: sqlite3.Connection, cats) -> None:
    """Persist the enabled ticker categories. Empty set = strip off."""
    clean = sorted({c for c in (cats or []) if c in TICKER_CATS})
    _core.set_option(con, _TICKER_CATS_OPT, ",".join(clean))
    con.commit()


# Escalation ladder for date-driven taps (a month, a week, tomorrow):
# within a month a tap, inside a week a slap, tomorrow a punch. Generic —
# any date-driven tap can map its days-out through ladder_level(). The
# only ladder customer today is open-ended rental contention.
TAP, SLAP, PUNCH = 0, 1, 2
LADDER_TAP_DAYS = 30
LADDER_SLAP_DAYS = 7
LADDER_PUNCH_DAYS = 1


def ladder_level(days_out) -> int | None:
    """Map days-until-consequence to an escalation level.

    Returns TAP (within a month), SLAP (within a week), PUNCH (tomorrow
    or overdue), or None when the consequence is too far out to earn a
    tap at all. Unknown timing (None) is a gentle TAP: the condition is
    real, it just can't say when.
    """
    if days_out is None:
        return TAP
    if days_out <= LADDER_PUNCH_DAYS:
        return PUNCH
    if days_out <= LADDER_SLAP_DAYS:
        return SLAP
    if days_out <= LADDER_TAP_DAYS:
        return TAP
    return None


def _ensure_alert_tables(con: sqlite3.Connection) -> None:
    try:
        con.execute("PRAGMA busy_timeout = 5000")
    except sqlite3.Error:
        pass
    # Current schema owns table creation. Keep this helper as a cheap
    # compatibility assertion for callers that use alerts on old books.
    if not con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='alert_ack'").fetchone():
        raise RuntimeError("Database schema is incomplete: alert_ack is missing")


def _acked_keys(con: sqlite3.Connection) -> set:
    _ensure_alert_tables(con)
    now = int(time.time())
    # No DELETE sweep here: the SELECT already ignores expired rows, and
    # sweeping on every dashboard GET took a write lock on a read path —
    # under concurrent load that raised "database is locked" (2026-09-29
    # soak). Expired rows are swept on the write path in ack_alert().
    try:
        return {
            r[0] for r in con.execute("SELECT alert_key FROM alert_ack WHERE until_ts > ?", (now,))
        }
    except sqlite3.OperationalError:
        # Degrade gracefully: show the taps rather than 500 the page.
        return set()


def is_acked(con: sqlite3.Connection, key: str) -> bool:
    """True if this alert/ticker key is currently snoozed or dismissed."""
    return key in _acked_keys(con)


def list_snoozed(con: sqlite3.Connection) -> list:
    """Currently snoozed/dismissed alert keys with their return times,
    soonest first. Only live rows (until_ts in the future) — expired
    rows are swept on the write path."""
    _ensure_alert_tables(con)
    return [(r[0], r[1]) for r in con.execute(
        "SELECT alert_key, until_ts FROM alert_ack WHERE until_ts > ? ORDER BY until_ts",
        (int(time.time()),))]


def unack_alert(con: sqlite3.Connection, key: str) -> None:
    """Bring a snoozed alert back now: drop its alert_ack row."""
    _ensure_alert_tables(con)
    con.execute("DELETE FROM alert_ack WHERE alert_key = ?", (key,))
    con.commit()


def ack_alert(con: sqlite3.Connection, key: str, action: str,
              hours: int = SNOOZE_HOURS, days: int = DISMISS_DAYS,
              minutes: int | None = None,
              until_ts: int | None = None) -> None:
    """Record a snooze or dismiss for an alert key.

    Durations are adjustable per tap: snooze in minutes (2026-10-04;
    previously hours) or hours as fallback, dismiss in days.
    Clamped to sane bounds. `until_ts` overrides the duration math
    with an explicit expiry — the permanent-dismiss path uses it.
    """
    _ensure_alert_tables(con)
    if action not in ("snooze", "dismiss"):
        raise ValueError("action must be snooze or dismiss")
    if until_ts is not None:
        until = max(int(until_ts), int(time.time()) + 60)
    elif action == "snooze":
        if minutes is not None:
            m = max(1, min(4320, int(minutes)))
            until = int(time.time()) + m * 60
        else:
            h = max(1, min(72, int(hours or SNOOZE_HOURS)))
            until = int(time.time()) + h * 3600
    else:  # dismiss
        d = max(1, min(90, int(days or DISMISS_DAYS)))
        until = int(time.time()) + d * 24 * 3600
    # Opportunistic sweep of expired acks on the write path — best effort,
    # never fatal to the ack itself.
    try:
        con.execute("DELETE FROM alert_ack WHERE until_ts <= ?", (int(time.time()),))
    except sqlite3.OperationalError:
        pass
    con.execute(
        "INSERT OR REPLACE INTO alert_ack(alert_key, until_ts) VALUES (?, ?)",
        (key, until),
    )
    con.commit()


def _alert(key: str, text: str, href: str, level: int = TAP, verb: str | None = None,
           cat: str | None = None, weight: int = 1) -> dict:
    """A shoulder-tap. `verb` is the one action button the strip shows for
    this item ("Record payment", "Set date", ...) — the button names the
    decision, the href lands where the decision gets made. `cat` is the
    ticker category ("money", "rentals", "compliance") for user filtering.
    `weight` is how much of the workload this one row stands for in the
    "+ N more" count: 1 for ordinary taps; a grouped compliance line
    weighs its item count, so the overflow counts items, not units
    (Batch 3 #18/#2)."""
    return {"key": key, "text": text, "href": href, "level": level, "verb": verb,
            "cat": cat, "weight": weight}


def _fmt_mdy(s) -> str:
    """'MM/DD/YYYY' — the views_core.fmt_date shape, for engine-side
    ticker text; '—' when missing or unparseable."""
    d = _core._parse(s) if s else None
    return d.strftime("%m/%d/%Y") if d else "—"


def _fmt_day(s) -> str:
    """'Thu 10/01/2026' style for a date string (MM/DD/YYYY, zero-padded);
    '' when missing or unparseable."""
    d = _core._parse(s) if s else None
    return d.strftime("%a %m/%d/%Y") if d else ""


def _shipping_bad_paper(con: sqlite3.Connection) -> list:
    """Reserved/Dispatched tickets whose unit fails the job's fit — the only
    moment paper earns a shoulder-tap (receiving checks it once, at the
    gate). Soonest ship first. Each item names its stakes."""
    from engine import ticket_money, fit_reason, operative_cert_expiry  # lazy: engine imports us

    out = []
    for r in con.execute(
            """SELECT t.ticket_id, t.status, t.on_rent, a.asset_id, a.unit_no,
                      c.account_name
               FROM tickets t
               JOIN assets a ON a.id = t.asset_id
               JOIN customers c ON c.id = t.customer_id
               WHERE t.status IN ('Reserved','Dispatched')"""):
        m = ticket_money(con, r["ticket_id"])
        fit = m.get("fit", "PASS")
        if fit == "PASS":
            continue
        day = _fmt_day(r["on_rent"])
        if r["status"] == "Dispatched":
            head = f"{r['unit_no']} en route to {r['account_name']}"
        else:
            head = f"{r['unit_no']} → {r['account_name']}" + (f" (ships {day})" if day else "")
        # Cert identity (Q5): the alert names the operative cert-record expiry.
        cexp = m.get("cert_expiry") or operative_cert_expiry(con, r["asset_id"])
        out.append({
            "ticket_id": r["ticket_id"],
            "sort": (_core._parse(r["on_rent"]) or date.max).isoformat(),
            "text": f"{head}: {fit_reason(fit, cexp)} — may be rejected at receiving",
        })
    out.sort(key=lambda t: t["sort"])
    return out


def _nooff_contention(con: sqlite3.Connection) -> list:
    """On-rent/standby tickets with no end date that actually matter: another
    Reserved ticket wants the same category AND no idle unit of that category
    exists. Otherwise it's revenue \u2014 stay calm, no tap.

    One tap per WANT, not per unit (2026-10-17, Jason's read of the demo
    dash): when two open-ended units block the same reservation, that's one
    story \u2014 "GEN-103 and GEN-104 are both out; Vermilion wants a Generator
    Thursday" \u2014 not the same tap told twice."""
    rows = []
    for r in con.execute(
            """SELECT t.ticket_id, a.unit_no, a.category, c.account_name
               FROM tickets t
               JOIN assets a ON a.id = t.asset_id
               JOIN customers c ON c.id = t.customer_id
               WHERE t.status IN ('On Rent','Standby')
                 AND (t.off_rent IS NULL OR t.off_rent = '')
                 AND a.category IS NOT NULL AND a.category != ''"""):
        want = con.execute(
            """SELECT t2.ticket_id, t2.on_rent, c2.account_name
               FROM tickets t2
               JOIN assets a2 ON a2.id = t2.asset_id
               JOIN customers c2 ON c2.id = t2.customer_id
               WHERE t2.status = 'Reserved' AND t2.ticket_id != ?
                 AND a2.category = ?
               ORDER BY t2.on_rent LIMIT 1""",
            (r["ticket_id"], r["category"])).fetchone()
        if not want:
            continue
        idle = con.execute(
            """SELECT 1 FROM assets a WHERE a.active = 1 AND a.category = ?
               AND NOT EXISTS
                 (SELECT 1 FROM tickets t WHERE t.asset_id = a.id
                  AND t.status NOT IN ('Billed','Closed','Void'))
               LIMIT 1""",
            (r["category"],)).fetchone()
        if idle:
            continue  # another unit can cover it \u2014 not important
        # The escalation ladder: the tap grows as the consequence approaches \u2014
        # within a month a tap, inside a week a slap, tomorrow a punch.
        # A reservation more than a month out earns nothing yet.
        d = _core._parse(want["on_rent"]) if want["on_rent"] else None
        days_out = (d - date.today()).days if d else None
        level = ladder_level(days_out)
        if level is None:
            continue
        rows.append({
            "ticket_id": r["ticket_id"], "unit_no": r["unit_no"],
            "holder": r["account_name"], "category": r["category"],
            "want_id": want["ticket_id"], "want_name": want["account_name"],
            "want_on": want["on_rent"], "level": level, "days_out": days_out,
        })
    # Group by the want: units blocking the same reservation merge into
    # a single tap naming them all.
    groups = {}
    for row in rows:
        groups.setdefault(row["want_id"], []).append(row)
    out = []
    for want_id, grows in groups.items():
        g = grows[0]
        units = ", ".join(x["unit_no"] for x in grows)
        holders = list(dict.fromkeys(x["holder"] for x in grows))
        if len(holders) == 1:
            with_whom = holders[0]
        elif len(holders) == 2:
            with_whom = f"{holders[0]} and {holders[1]}"
        else:
            with_whom = ", ".join(holders[:-1]) + f" and {holders[-1]}"
        day = _fmt_day(g["want_on"])
        when = f" {day}" if day else ""
        text = (f"{units} open-ended with {with_whom} \u2014 "
                f"{g['want_name']} wants a {g['category']}{when}, nothing else free")
        if g["level"] == SLAP:
            text = "This week: " + text
        elif g["level"] == PUNCH:
            text = ("Tomorrow: " if g["days_out"] == 1 else "Now: ") + text
        out.append({
            "ticket_id": g["ticket_id"],
            "text": text,
            "level": g["level"],
        })
    return out


def _po_expiry_taps(con: sqlite3.Connection, tapped: set) -> list:
    """POs expired or expiring within 14 days, tied to open invoices with
    money still out. Q6: surfaced when problematic — one tap per PO naming
    the PO, the customer, and the biggest open invoice. Invoices already
    earning a money tap are excluded (one invoice, one tap). Nonblocking
    nudge; saving, printing, and dispatch are never gated."""
    from engine import invoice_balances_batch  # lazy: engine imports us
    balances = invoice_balances_batch(con)

    out = []
    today = date.today()
    try:
        pos = con.execute(
            """SELECT p.po_no, p.customer_id, p.expire, c.account_name
               FROM purchase_orders p
               JOIN customers c ON c.id = p.customer_id
               WHERE p.expire IS NOT NULL AND TRIM(p.expire) != ''""").fetchall()
    except Exception:
        return out  # pre-migration DB: no PO record yet
    for p in pos:
        d = _core._parse((p["expire"] or "").strip())
        if not d:
            continue
        delta = (d - today).days
        if delta > 14:
            continue
        level = ladder_level(delta)
        if level is None:
            continue
        cands = []
        for inv in con.execute(
                """SELECT invoice_no FROM invoices
                   WHERE customer_id = ? AND TRIM(po) = ?
                   AND status NOT IN ('Paid','Write-off','Draft')""",
                (p["customer_id"], (p["po_no"] or "").strip())):
            ino = inv["invoice_no"]
            if ino in tapped:
                continue
            bal = balances.get(ino, 0.0)
            if bal > 0.009:
                cands.append((ino, bal))
        if not cands:
            continue
        cands.sort(key=lambda t: -t[1])
        ino, bal = cands[0]
        day = _fmt_day(p["expire"])
        if delta < 0:
            head = f"PO {p['po_no']} expired {day}"
        elif delta == 0:
            head = f"PO {p['po_no']} expires today"
        else:
            head = f"PO {p['po_no']} expires {day} ({delta}d)"
        extra = f" +{len(cands) - 1} more" if len(cands) > 1 else ""
        out.append({
            "key": f"acct:poexp:{p['customer_id']}:{(p['po_no'] or '').strip()}",
            "text": (f"{head} — {p['account_name']}, invoice {ino} "
                     f"${bal:,.2f} unpaid{extra}. They may bounce it."),
            "href": f"/invoice/{ino}",
            "rank": 3,
            "tie": (-bal, 0),
            "level": level,
            "verb": "Fix PO",
        })
    return out


# ---------------------------------------------------------------------------
# The Assets families (build 'x'): the five producers that fed the
# Assets page's own ticker until build 'w', ported to the engine so
# the one Today ticker can carry them — plus a sixth, new in 'x':
# idle-unit paper, which the Assets ticker never carried at all
# (nothing off the rank). Texts are PLAIN — the strip escapes item
# text — and carry the Assets ticker's wording with its mute spans
# dropped (the words are the same; the parentheses stay). Each
# returns (key, text, href) rows in the Assets ticker's order.

def _asset_conflict_items(con: sqlite3.Connection) -> list:
    """Expired cert/paper on a unit with a job starting within 14 days."""
    from engine import operative_cert_expiry  # lazy: engine imports us
    out = []
    today = date.today()
    soon = (today + timedelta(days=14)).isoformat()
    for r in con.execute(
            """SELECT DISTINCT a.asset_id, a.unit_no, t.ticket_id, t.on_rent, c.account_name
               FROM assets a
               JOIN tickets t ON t.asset_id = a.id
               JOIN customers c ON c.id = t.customer_id
               WHERE a.active = 1
               AND t.status IN ('Reserved','Dispatched')
               AND t.on_rent <= ?""", (soon,)):
        exp = operative_cert_expiry(con, r["asset_id"])
        if exp and exp < today.isoformat():
            out.append((f"aconf:{r['ticket_id']}",
                        f"EXPIRED CERT — {r['unit_no']} ships "
                        f"{_fmt_mdy(r['on_rent'])} to {r['account_name']} "
                        f"(expired {_fmt_mdy(exp)})",
                        f"/ticket/{r['ticket_id']}"))
    return out


def _asset_live_po_items(con: sqlite3.Connection) -> list:
    """Live POs missing an expiry — the one PO field where "unknown"
    is money risk (an invoice against an expired PO may bounce).
    Live = a Reserved ticket holds a unit for it, or an editable
    open invoice carries it (Sent invoices are locked — their PO
    can no longer be marked). Every live PO lists: the producer
    carries no LIMIT (build 'x' — an exclusionary cap in a
    producer silently drops actionable items off the rank, which
    the one-ticker law bans; the strip's five-item cut governs
    what shows and the overflow counts the rest). The row's link
    is the unit when the PO names one, else where the PO gets
    marked: its editable open invoice, else its Reserved rental.
    (The Assets row's separate
    "Mark PO details" button does not ride into the strip — strip
    rows are text plus Snooze only.) A PO that names neither earns
    no tap: a condition that can't name its stakes doesn't earn one."""
    out = []
    for p in con.execute(
            """SELECT p.po_no, p.customer_id, p.asset_id, p.expire, p.cost_code,
                      COALESCE(c.account_name, p.customer_id) AS account_name
               FROM purchase_orders p
               LEFT JOIN customers c ON c.id = p.customer_id
               WHERE (p.expire IS NULL OR TRIM(p.expire) = '')
                 AND (EXISTS (SELECT 1 FROM tickets t
                              WHERE t.customer_id = p.customer_id AND t.po = p.po_no
                                AND t.status = 'Reserved')
                      OR EXISTS (SELECT 1 FROM invoices i
                                 WHERE i.customer_id = p.customer_id
                                   AND TRIM(i.po) = p.po_no
                                   AND i.status NOT IN ('Paid','Write-off','Draft','Sent')))
               ORDER BY p.rowid DESC"""):
        unit = ""
        href = None
        if p["asset_id"]:
            u = con.execute("SELECT unit_no, asset_id FROM assets WHERE id=?",
                            (p["asset_id"],)).fetchone()
            if u:
                unit = f" — {u['unit_no']}"
                href = f"/unit/{u['asset_id']}"
        # Is the unit in-yard (reserved) or on a job (paperwork only)?
        state = ""
        if p["asset_id"]:
            busy = con.execute(
                """SELECT ticket_id FROM tickets WHERE asset_id=?
                   AND status IN ('Dispatched','On Rent','Standby')""",
                (p["asset_id"],)).fetchone()
            state = (" (on job — paperwork change)" if busy
                     else " (reserved)")
        if href is None:
            inv = con.execute(
                """SELECT invoice_no FROM invoices
                   WHERE customer_id = ? AND TRIM(po) = ?
                     AND status NOT IN ('Paid','Write-off','Draft','Sent')
                   ORDER BY invoice_date DESC LIMIT 1""",
                (p["customer_id"], (p["po_no"] or "").strip())).fetchone()
            if inv:
                href = f"/invoice/{inv['invoice_no']}"
            else:
                tk = con.execute(
                    """SELECT ticket_id FROM tickets
                       WHERE customer_id = ? AND po = ? AND status = 'Reserved'
                       ORDER BY rowid DESC LIMIT 1""",
                    (p["customer_id"], p["po_no"])).fetchone()
                if tk:
                    href = f"/ticket/{tk['ticket_id']}"
        if href is None:
            continue
        missing = "no expiry"
        if not (p["cost_code"] or "").strip():
            missing += ", no cost code"
        out.append((f"poack:{p['customer_id']}:{p['po_no']}",
                    f"{p['po_no']}{unit} — {p['account_name']}: "
                    f"{missing}{state}",
                    href))
    return out


def _asset_accepted_quote_items(con: sqlite3.Connection) -> list:
    """Accepted quote: recognition tap, with urgency as the date nears."""
    out = []
    today = date.today()
    for q in con.execute(
            """SELECT q.quote_no, q.customer_id, q.valid_until, c.account_name
               FROM quotes q JOIN customers c ON c.id = q.customer_id
               WHERE q.status='Accepted' ORDER BY q.valid_until"""):
        vu = (q["valid_until"] or "").strip()[:10]
        try:
            delta = (date.fromisoformat(vu) - today).days if vu else None
        except ValueError:
            delta = None
        if delta is None:
            when = ""
        elif delta < 0:
            when = f" (validity lapsed {_fmt_mdy(vu)})"
        elif delta <= 7:
            when = f" ({delta}d left)"
        else:
            when = f" (valid to {_fmt_mdy(vu)})"
        out.append((f"aq:{q['quote_no']}",
                    f"Quote {q['quote_no']} accepted — "
                    f"{q['account_name']}{when}",
                    f"/summary/quote/{q['quote_no']}"))
    return out


def _asset_offrent_items(con: sqlite3.Connection) -> list:
    """Expected off-rent returns within 7 days."""
    out = []
    soon = (date.today() + timedelta(days=7)).isoformat()
    for r in con.execute(
            """SELECT t.ticket_id, t.off_rent, a.unit_no, c.account_name
               FROM tickets t
               JOIN assets a ON a.id = t.asset_id
               JOIN customers c ON c.id = t.customer_id
               WHERE t.status='On Rent' AND t.off_rent IS NOT NULL
               AND t.off_rent <= ? ORDER BY t.off_rent""", (soon,)):
        out.append((f"aoff:{r['ticket_id']}",
                    f"{r['unit_no']} due back {_fmt_mdy(r['off_rent'])} "
                    f"({r['account_name']})",
                    f"/ticket/{r['ticket_id']}"))
    return out


def _asset_sole_unit_items(con: sqlite3.Connection) -> list:
    """Sole available unit of its kind with an issue gets a nudge."""
    from engine import operative_cert_expiry  # lazy: engine imports us
    out = []
    today = date.today().isoformat()
    for cat in con.execute(
            """SELECT category, COUNT(*) AS n FROM assets
               WHERE active=1 AND COALESCE(designation,'Fleet') NOT IN ('Plant','Stock')
               AND COALESCE(status,'Active')='Active'
               AND category IS NOT NULL AND TRIM(category)!=''
               GROUP BY category HAVING n=1"""):
        u = con.execute(
            """SELECT a.asset_id, a.unit_no FROM assets a
               WHERE a.active=1 AND COALESCE(a.designation,'Fleet') NOT IN ('Plant','Stock') AND COALESCE(a.status,'Active')='Active' AND a.category=?
               AND NOT EXISTS (SELECT 1 FROM tickets t WHERE t.asset_id = a.id
                   AND t.status NOT IN ('Billed','Closed','Void'))""",
            (cat["category"],)).fetchone()
        if not u:
            continue
        exp = operative_cert_expiry(con, u["asset_id"])
        if exp and exp < today:
            out.append((f"asole:{u['asset_id']}",
                        f"{u['unit_no']} unfit & only available "
                        f"(expired {_fmt_mdy(exp)})",
                        f"/unit/{u['asset_id']}"))
    return out


def _asset_idle_paper_items(con: sqlite3.Connection) -> list:
    """Expired or due-soon certification paper on units with no job
    in front of them — the bottom of the rank (build 'x', Jason
    2026-10-26: NOTHING OFF THE RANK). The Assets ticker tapped
    expired paper only when a job was coming soon; idle iron got
    no tap at all. In the one ticker the item lists — very low,
    under money, shipping, contention, and the job-linked paper —
    counted in the workload, and reached by punching through
    everything above it. A unit counts as idle when no open
    rental names it (Reserved, Dispatched, On Rent, and Standby
    are job-linked states; their paper earns its own taps above).
    Units earning the sole-unit line are skipped — that line
    already names the same paper, higher. Expired paper first,
    then due-soon, each in expiry order."""
    from engine import operative_cert_expiry  # lazy: engine imports us
    sole = {k.split(":", 1)[1] for k, _t, _h in _asset_sole_unit_items(con)}
    today = date.today()
    horizon = (today + timedelta(days=_core.DUE_SOON_DAYS)).isoformat()
    rows = []
    for r in con.execute(
            """SELECT a.asset_id, a.unit_no FROM assets a
               WHERE a.active = 1
                 AND NOT EXISTS (SELECT 1 FROM tickets t
                                 WHERE t.asset_id = a.id
                                   AND t.status IN ('Reserved','Dispatched',
                                                    'On Rent','Standby'))
               ORDER BY a.unit_no"""):
        if r["asset_id"] in sole:
            continue
        exp = operative_cert_expiry(con, r["asset_id"])
        if not exp:
            continue
        if exp < today.isoformat():
            rows.append((0, exp, f"comp:idle:{r['asset_id']}",
                         f"{r['unit_no']} — certification expired "
                         f"{_fmt_mdy(exp)}",
                         f"/unit/{r['asset_id']}"))
        elif exp <= horizon:
            rows.append((1, exp, f"comp:idle:{r['asset_id']}",
                         f"{r['unit_no']} — certification due "
                         f"{_fmt_mdy(exp)}",
                         f"/unit/{r['asset_id']}"))
    rows.sort(key=lambda x: (x[0], x[1]))
    return [(k, t, h) for _s, _e, k, t, h in rows]


def alerts_for(con: sqlite3.Connection, section: str = "dash") -> list:
    """The one shoulder-tap pool (build 'x', Jason 2026-10-26).

    There is exactly one ticker in the build — on Today — and it
    captures all. Returns (shown, total): up to five ranked taps plus
    the full workload count so the strip can render a quiet
    "+ N more". Every tap names its stakes: the unit, the customer,
    the date, the reason. A condition that can't name its stakes
    doesn't earn a tap.

    The merged ladder (each pool keeps its internal order; the
    ladder interleaves the pools by stakes): shipping bad paper
    (rank 0); disputed invoices (rank 1); expired certification on
    upcoming work (rank 2); past-due invoices and PO expiry on open
    invoices (rank 3, balances first); open-ended-rental contention
    (rank 4); live POs missing an expiry date (rank 5); expired
    compliance grouped by unit (rank 6); accepted quotes (rank 7);
    expected off-rent returns (rank 8); a sole unit unfit for work
    (rank 9); and certification paper on idle units (rank 10).
    Ranks 2 and 5–10 are the families that fed the Assets page's
    own ticker until build 'w' — plus rank 10, which no ticker
    carried before: nothing is off the rank (Jason 2026-10-26).
    Every actionable condition in the build lists somewhere in
    this ladder; low priority is a rank, absence is not. The
    operator's own acts — the category Filter, the module
    switches, Snooze — narrow the pool by his choice and are not
    exclusions. The `section` argument is retained for caller
    compatibility and no longer selects a pool: every caller
    gets the one pool.

    One invoice, one tap: whichever money condition fires first for
    an invoice (dispute, then past-due, then PO expiry) is the only
    tap that invoice gets.
    """

    acked = _acked_keys(con)
    ranked: list = []  # (rank, tiebreak, key, text, href, level, verb, cat, weight)

    def add(rank: int, tie, key: str, text: str, href: str,
             level: int = TAP, verb: str | None = None,
             cat: str | None = None, weight: int = 1) -> None:
        if key not in acked:
            ranked.append((rank, tie, key, text, href, level, verb, cat, weight))

    # Shipping paper first: a unit about to hit receiving with bad paper
    # is the one compliance tap that matters.
    for i, t in enumerate(_shipping_bad_paper(con)):
        add(0, i, f"dash:fitship:{t['ticket_id']}", t["text"],
            f"/ticket/{t['ticket_id']}", verb="Review", cat="compliance")
    # Real contention for open-ended rentals.
    for t in _nooff_contention(con):
        add(4, 0, f"dash:nooff:{t['ticket_id']}", t["text"],
            "/tickets?flag=nooff", t["level"], verb="Set date",
            cat="rentals")
    # Batch 3 #18: checklist attention lives ONLY here, in the
    # ticker, and ONLY grouped by unit — one line per unit, worst
    # first, carrying the due/overdue split, the most urgent item
    # and its due date, and "→ call X" when that item has a
    # performer. Snooze keys are per unit (comp:unit:<asset_id>),
    # so one Snooze quiets the whole unit. The line's overflow
    # weight is its item count: "+ N more" counts items (the
    # workload), never units. Per-shift rows are not in the watch
    # at all — they never reach this list.
    try:
        from engine import compliance_groups  # lazy: engine imports us
        for g in compliance_groups(con):
            first = g["first"]
            text = (f"{g['status'].upper()} — {g['unit_no']}: "
                    f"{g['n_due']} due, {g['n_overdue']} overdue — "
                    f"first: {first['item']} due {_fmt_mdy(first['next_due'])}"
                    + (f" → call {first['performer_name']}"
                       if first.get("performer_name") else ""))
            add(6, (0 if g["status"] == "overdue" else 1,
                    first["next_due"] or "9999"),
                f"comp:unit:{g['asset_id']}", text,
                f"/ucompliance/{g['asset_id']}?focus={first['eqc_id']}",
                verb="Fix It", cat="compliance", weight=g["total"])
    except Exception:
        pass  # the strip never breaks a page over compliance
    # Money taps: disputed first, then past-due, then PO expiry.
    from engine import invoice_balances_batch  # lazy: engine imports us
    _balances = invoice_balances_batch(con)
    today = date.today()
    tapped_invoices = set()
    for inv in con.execute(
        """SELECT i.invoice_no, i.invoice_date, i.terms, i.status, c.account_name
           FROM invoices i JOIN customers c ON c.id = i.customer_id
           WHERE i.status NOT IN ('Paid','Write-off','Draft')"""
    ):
        bal = _balances.get(inv["invoice_no"], 0.0)
        if bal <= 0.009:
            continue
        d0 = _core._parse(inv["invoice_date"]) or today
        due = d0 + timedelta(days=_core.terms_days(inv["terms"]))
        if inv["status"] == "Disputed":
            # Disputed ranks first; no second past-due tap for the same invoice.
            tapped_invoices.add(inv["invoice_no"])
            add(
                1, (-bal, 0),
                f"acct:disputed:{inv['invoice_no']}",
                f"Invoice {inv['invoice_no']} disputed — {inv['account_name']}",
                f"/invoice/{inv['invoice_no']}",
                verb="Clear dispute",
                cat="money",
            )
        elif today > due:
            late = (today - due).days
            # Biggest money first, then most days late.
            tapped_invoices.add(inv["invoice_no"])
            add(
                3, (-bal, -late),
                f"acct:pastdue:{inv['invoice_no']}",
                f"Invoice {inv['invoice_no']} {late}d past due — "
                f"{inv['account_name']} ${bal:,.2f}",
                f"/invoice/{inv['invoice_no']}#record-payment",
                verb="Record payment",
                cat="money",
            )
    # Q6: PO expiry is a money risk too — expired/expiring POs on open
    # invoices earn a tap, money-first alongside past-due. Invoices
    # already tapped above are excluded: one invoice, one tap.
    for t in _po_expiry_taps(con, tapped_invoices):
        add(t["rank"], t["tie"], t["key"], t["text"], t["href"], t["level"],
            verb=t.get("verb"), cat="money")
    # The Assets families (build 'x'): the five kinds that fed the
    # Assets page's own ticker, interleaved by stakes — conflicts
    # (expired-certification facts) ride beside the money at rank 2;
    # live POs missing an expiry at rank 5; accepted quotes, expected
    # off-rent returns, and the sole-unit line follow the grouped
    # compliance lines at ranks 7–9, in the order the Assets ticker
    # presented them. Categories by nature: conflicts are rental
    # work blocked on paper (rentals); live POs are money; quotes
    # and off-rent returns are rentals; the sole-unit line is an
    # expired-certification fact (compliance). The module-switch
    # discard below governs them exactly as it governs the rest.
    try:
        for i, (key, text, href) in enumerate(_asset_conflict_items(con)):
            add(2, i, key, text, href, verb="Review", cat="rentals")
    except Exception:
        pass  # the strip never breaks a page over an Assets family
    try:
        for i, (key, text, href) in enumerate(_asset_live_po_items(con)):
            add(5, i, key, text, href, verb="Fix PO", cat="money")
    except Exception:
        pass  # the strip never breaks a page over an Assets family
    try:
        for i, (key, text, href) in enumerate(_asset_accepted_quote_items(con)):
            add(7, i, key, text, href, verb="View", cat="rentals")
    except Exception:
        pass  # the strip never breaks a page over an Assets family
    try:
        for i, (key, text, href) in enumerate(_asset_offrent_items(con)):
            add(8, i, key, text, href, verb="Review", cat="rentals")
    except Exception:
        pass  # the strip never breaks a page over an Assets family
    try:
        for i, (key, text, href) in enumerate(_asset_sole_unit_items(con)):
            add(9, i, key, text, href, verb="Review", cat="compliance")
    except Exception:
        pass  # the strip never breaks a page over an Assets family
    # The bottom of the rank: idle units' certification paper
    # (build 'x', nothing off the rank — see _asset_idle_paper_items).
    try:
        for i, (key, text, href) in enumerate(_asset_idle_paper_items(con)):
            add(10, i, key, text, href, verb="Review", cat="compliance")
    except Exception:
        pass  # the strip never breaks a page over an Assets family
    ranked.sort(key=lambda r: (r[0], r[1]))
    # Category filter: the operator chooses which kinds of taps earn a slot.
    # Filter BEFORE the five-item cut so disabled categories don't consume
    # slots. All off = empty strip. (2026-10-06)
    enabled = get_ticker_cats(con)
    # Shop flow (Jason, 2026-10-21): a module switched OFF wins over the
    # ticker-category settings — its categories leave the strip before
    # the cut, exactly like a category the operator unchecked.
    from engine_core import module_on as _module_on
    if not _module_on(con, "rentals"):
        enabled.discard("rentals")
    if not _module_on(con, "compliance"):
        enabled.discard("compliance")
    if not _module_on(con, "billing"):
        enabled.discard("money")
    if not enabled:
        return ([], 0)
    ranked = [r for r in ranked if (r[7] in enabled)]
    # All five shown items carry their action verbs. Anything past five is a
    # quiet "+ N more" — a glimpse, not a firehose. Handling, snoozing, or
    # dismissing an item lets the next one roll up. Calm line when there is
    # nothing to tap about (dashboard only).
    # Total counts WORKLOAD, not rows (Batch 3 #2/#18): a grouped
    # compliance line weighs its item count, every other tap weighs 1.
    total = sum(r[8] for r in ranked)
    shown = ranked[:STRIP_SHOW]
    return ([_alert(k, t, h, level=lv, verb=v, cat=c, weight=w)
             for _, _, k, t, h, lv, v, c, w in shown], total)
