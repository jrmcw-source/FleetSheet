"""Per-tab news strip: the guy tapping you on the shoulder.

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
           "get_ticker_cats", "set_ticker_cats", "TICKER_CATS", "CAT_LABELS"]

SNOOZE_HOURS = 3
DISMISS_DAYS = 7
# A shoulder-tap, not a firehose: never more than this many per page.
# The strip shows the two head taps with action verbs and the next three
# with snooze/dismiss only; anything past five is a quiet "+ N more".
STRIP_SHOW = 5
STRIP_VERBS = 2

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


def ack_alert(con: sqlite3.Connection, key: str, action: str,
              hours: int = SNOOZE_HOURS, days: int = DISMISS_DAYS,
              minutes: int | None = None) -> None:
    """Record a snooze or dismiss for an alert key.

    Durations are adjustable per tap: snooze in minutes (2026-10-04;
    previously hours) or hours as fallback, dismiss in days.
    Clamped to sane bounds.
    """
    _ensure_alert_tables(con)
    if action == "snooze":
        if minutes is not None:
            m = max(1, min(4320, int(minutes)))
            until = int(time.time()) + m * 60
        else:
            h = max(1, min(72, int(hours or SNOOZE_HOURS)))
            until = int(time.time()) + h * 3600
    elif action == "dismiss":
        d = max(1, min(90, int(days or DISMISS_DAYS)))
        until = int(time.time()) + d * 24 * 3600
    else:
        raise ValueError("action must be snooze or dismiss")
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
           cat: str | None = None) -> dict:
    """A shoulder-tap. `verb` is the one action button the strip shows for
    this item ("Record payment", "Set date", ...) — the button names the
    decision, the href lands where the decision gets made. `cat` is the
    ticker category ("money", "rentals", "compliance") for user filtering."""
    return {"key": key, "text": text, "href": href, "level": level, "verb": verb,
            "cat": cat}


def _fmt_day(s) -> str:
    """'Thu 10/1' style for a date string; '' when missing or unparseable."""
    d = _core._parse(s) if s else None
    return d.strftime("%a %-m/%-d") if d else ""


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
               JOIN assets a ON a.asset_id = t.asset_id
               JOIN customers c ON c.customer_id = t.customer_id
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
    exists. Otherwise it's revenue — stay calm, no tap."""
    out = []
    for r in con.execute(
            """SELECT t.ticket_id, a.unit_no, a.category, c.account_name
               FROM tickets t
               JOIN assets a ON a.asset_id = t.asset_id
               JOIN customers c ON c.customer_id = t.customer_id
               WHERE t.status IN ('On Rent','Standby')
                 AND (t.off_rent IS NULL OR t.off_rent = '')
                 AND a.category IS NOT NULL AND a.category != ''"""):
        want = con.execute(
            """SELECT t2.ticket_id, t2.on_rent, c2.account_name
               FROM tickets t2
               JOIN assets a2 ON a2.asset_id = t2.asset_id
               JOIN customers c2 ON c2.customer_id = t2.customer_id
               WHERE t2.status = 'Reserved' AND t2.ticket_id != ?
                 AND a2.category = ?
               ORDER BY t2.on_rent LIMIT 1""",
            (r["ticket_id"], r["category"])).fetchone()
        if not want:
            continue
        idle = con.execute(
            """SELECT 1 FROM assets a WHERE a.active = 1 AND a.category = ?
               AND NOT EXISTS
                 (SELECT 1 FROM tickets t WHERE t.asset_id = a.asset_id
                  AND t.status NOT IN ('Billed','Closed','Void'))
               LIMIT 1""",
            (r["category"],)).fetchone()
        if idle:
            continue  # another unit can cover it — not important
        # The escalation ladder: the tap grows as the consequence approaches —
        # within a month a tap, inside a week a slap, tomorrow a punch.
        # A reservation more than a month out earns nothing yet.
        d = _core._parse(want["on_rent"]) if want["on_rent"] else None
        days_out = (d - date.today()).days if d else None
        level = ladder_level(days_out)
        if level is None:
            continue
        day = _fmt_day(want["on_rent"])
        when = f" {day}" if day else ""
        text = (f"{r['unit_no']} open-ended with {r['account_name']} — "
                f"{want['account_name']} wants a {r['category']}{when}, nothing else free")
        if level == SLAP:
            text = "This week: " + text
        elif level == PUNCH:
            text = ("Tomorrow: " if days_out == 1 else "Now: ") + text
        out.append({
            "ticket_id": r["ticket_id"],
            "text": text,
            "level": level,
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
               JOIN customers c ON c.customer_id = p.customer_id
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
                     f"${bal:,.2f} unpaid{extra}. They may bounce it — get the PO reissued."),
            "href": f"/invoice/{ino}",
            "rank": 1,
            "tie": (-bal, 0),
            "level": level,
            "verb": "Fix PO",
        })
    return out


def alerts_for(con: sqlite3.Connection, section: str) -> list:
    """Shoulder-taps for a nav section: dash, acct, reports.

    Returns (shown, total): up to five ranked taps plus the full count so the
    strip can render a quiet "+ N more". All five taps carry action verbs.
    Every tap names its stakes: the unit, the customer, the date, the reason. A
    condition that can't name its stakes doesn't earn a tap. Disputed
    invoices rank ahead of plain past-due ones, and a disputed invoice never
    also raises a past-due alert for the same invoice (one invoice, one tap).
    """

    acked = _acked_keys(con)
    ranked: list = []  # (rank, tiebreak, key, text, href, level)

    def add(rank: int, tie: float, key: str, text: str, href: str,
             level: int = TAP, verb: str | None = None,
             cat: str | None = None) -> None:
        if key not in acked:
            ranked.append((rank, tie, key, text, href, level, verb, cat))

    if section == "dash":
        # Shipping paper first: a unit about to hit receiving with bad paper
        # is the one compliance tap that matters. Then real contention for
        # open-ended rentals. Expired certs on idle iron and mid-job checklist
        # items are quiet chores — they live on Assets / Today, never here.
        for i, t in enumerate(_shipping_bad_paper(con)):
            add(0, i, f"dash:fitship:{t['ticket_id']}", t["text"],
                f"/ticket/{t['ticket_id']}", verb="Review", cat="compliance")
        for t in _nooff_contention(con):
            add(1, 0, f"dash:nooff:{t['ticket_id']}", t["text"],
                "/tickets?flag=nooff", t["level"], verb="Set date",
                cat="rentals")
    elif section == "acct":
        from engine import invoice_balances_batch  # lazy: engine imports us
        _balances = invoice_balances_batch(con)
        today = date.today()
        tapped_invoices = set()
        for inv in con.execute(
            """SELECT i.invoice_no, i.invoice_date, i.terms, i.status, c.account_name
               FROM invoices i JOIN customers c ON c.customer_id = i.customer_id
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
                    0, (-bal, 0),
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
                    1, (-bal, -late),
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
    elif section == "reports":
        # Quiet by doctrine: checklist items are sticky notes — they live on
        # Today's "due this week" item and the Assets paperwork list. The
        # strip is for shipping paper and money now.
        pass
    ranked.sort(key=lambda r: (r[0], r[1]))
    # Category filter: the operator chooses which kinds of taps earn a slot.
    # Filter BEFORE the five-item cut so disabled categories don't consume
    # slots. All off = empty strip. (2026-10-06)
    enabled = get_ticker_cats(con)
    if not enabled:
        return ([], 0)
    ranked = [r for r in ranked if (r[7] in enabled)]
    # All five shown items carry their action verbs. Anything past five is a
    # quiet "+ N more" — a glimpse, not a firehose. Handling, snoozing, or
    # dismissing an item lets the next one roll up. Calm line when there is
    # nothing to tap about (dashboard only).
    total = len(ranked)
    shown = ranked[:STRIP_SHOW]
    return ([_alert(k, t, h, level=lv, verb=v, cat=c)
             for _, _, k, t, h, lv, v, c in shown], total)
