"""Today tab: one screen, ranked. Money slot + Must do / Can do / Do it later.

The money slot holds ONE item at a time, date-driven: a money event earns
the slot when its date is today (due today, still overdue today, paid today).
Handle it or kill it and the next one slides in. Every stack refills from
its backlog as items are worked through — there is always a next job.

When today is clear, the tab stays calm: "get a head start on tomorrow"
showing tomorrow's must-dos instead of red flashing.
"""
from __future__ import annotations
import sqlite3
from datetime import date, datetime, timedelta

import engine_core as _core

def today_everything(con: sqlite3.Connection) -> list:
    """Everything the Today ranking looked at — no filter, no sort, just there.

    Money candidates live on /money (the Money tab), so they are
    not duplicated here. Every other ranking input is: tickets, compliance
    (expired certs, failing fit, due checklist items), live quotes, idle
    units, and user tasks.
    """
    from engine import fleet_compliance_watch, ticket_money
    _ensure_task_tables(con)

    sections = []

    tickets = [
        {"text": f"{r['ticket_id']} — {r['status']} — {r['asset_id']} ({r['customer_id']})",
         "href": f"/ticket/{r['ticket_id']}"}
        for r in con.execute(
            "SELECT ticket_id, status, asset_id, customer_id FROM tickets")
    ]
    if tickets:
        sections.append(("Tickets", tickets))

    compliance = []
    for r in con.execute(
            """SELECT asset_id, unit_no FROM assets WHERE active = 1
               AND cert_expire IS NOT NULL AND date(cert_expire) < date('now')
               ORDER BY unit_no"""):
        compliance.append({
            "text": f"EXPIRED CERT — {r['unit_no']} ({r['asset_id']})",
            "href": f"/unit/{r['asset_id']}"})
    for r in con.execute(
            """SELECT ticket_id FROM tickets
               WHERE status IN ('Quoted','Reserved','Dispatched','On Rent','Standby')
               ORDER BY ticket_id"""):
        if ticket_money(con, r["ticket_id"]).get("fit", "PASS") != "PASS":
            compliance.append({
                "text": f"FAILING FIT — {r['ticket_id']}",
                "href": f"/ticket/{r['ticket_id']}"})
    for w in fleet_compliance_watch(con):
        compliance.append({
            "text": f"{w['status'].upper()} — {w['unit_no']}: {w['item']}",
            "href": f"/unit/{w['asset_id']}"})
    if compliance:
        sections.append(("Compliance", compliance))

    quotes = [
        {"text": f"{r['quote_no']} — {r['status']} — {r['account_name']}",
         "href": f"/quote/{r['quote_no']}"}
        for r in con.execute(
            """SELECT q.quote_no, q.status, c.account_name FROM quotes q
               JOIN customers c ON c.customer_id = q.customer_id
               WHERE q.status NOT IN ('Void','Declined','Expired','Converted')
               ORDER BY q.quote_no""")
    ]
    if quotes:
        sections.append(("Quotes", quotes))

    idle = [
        {"text": f"{r['unit_no']} — {r['description'] or ''} ({r['asset_id']})",
         "href": f"/unit/{r['asset_id']}"}
        for r in con.execute(
            """SELECT a.asset_id, a.unit_no, a.description FROM assets a
               WHERE a.active = 1 AND NOT EXISTS
               (SELECT 1 FROM tickets t WHERE t.asset_id = a.asset_id
                AND t.status NOT IN ('Billed','Closed','Void'))
               ORDER BY a.unit_no""")
    ]
    if idle:
        sections.append(("Idle units", idle))

    tasks = []
    for t in con.execute("SELECT task_id, text, tier, done, link FROM today_tasks"):
        mark = "✓ " if t["done"] else ""
        tasks.append({"text": f"{mark}[{t['tier']}] {t['text']}", "href": t["link"] or ""})
    if tasks:
        sections.append(("Tasks", tasks))

    return sections


def tasks_for_link(con: sqlite3.Connection, link: str) -> list:
    """Open Today tasks pointing at one record — for the Done nudge."""
    _ensure_task_tables(con)
    return [
        {"task_id": r["task_id"], "text": r["text"], "tier": r["tier"]}
        for r in con.execute(
            "SELECT task_id, text, tier FROM today_tasks WHERE link = ? AND done = 0 ORDER BY task_id",
            (link or "",))
    ]


__all__ = [
    "today_money_slot",
    "advance_money_slot",
    "top_of_day",
    "today_must_do",
    "today_can_do",
    "today_later",
    "today_tomorrow",
    "today_everything",
    "add_task",
    "complete_task",
    "uncomplete_task",
    "add_sticky",
    "edit_sticky",
    "remove_sticky",
    "list_stickies",
    "update_sticky",
    "done_sticky",
    "add_done_manual",
    "remove_done_manual",
    "done_today",
    "done_tasks",
    "done_payments",
    "done_period",
    "list_tasks",
    "tasks_for_link",
]


def _ensure_task_tables(con: sqlite3.Connection) -> None:
    """Repair-only compatibility hook; schema.sql owns current table DDL."""
    required = ("today_tasks", "done_manual", "today_money_done", "today_stickies")
    for table in required:
        if not con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
            raise RuntimeError(f"Database schema is incomplete: {table} is missing")
    # Older books may lack columns introduced after the original table DDL.
    cols = [r[1] for r in con.execute("PRAGMA table_info(today_tasks)")]
    for col, typ, default in (("link", "TEXT", "''"), ("done_at", "TEXT", "NULL"),
                              ("done_by", "TEXT", "''")):
        if col not in cols:
            sql = f"ALTER TABLE today_tasks ADD COLUMN {col} {typ}"
            if default != "NULL":
                sql += f" NOT NULL DEFAULT {default}"
            con.execute(sql)
    cols = [r[1] for r in con.execute("PRAGMA table_info(today_stickies)")]
    for col, typ, default in (("priority", "INTEGER", "1"), ("color", "TEXT", "'yellow'"),
                              ("snoozed_until", "TEXT", "NULL"), ("hide_until", "TEXT", "NULL"),
                              ("pinned", "INTEGER", "0"), ("dismissed", "INTEGER", "0")):
        if col not in cols:
            sql = f"ALTER TABLE today_stickies ADD COLUMN {col} {typ}"
            if default != "NULL":
                sql += f" NOT NULL DEFAULT {default}"
            con.execute(sql)


def _money_candidates(con: sqlite3.Connection, today: date) -> list:
    """All money events that could take the Today slot, most urgent first.

    Date earns the slot (late > due today > paid today); within a date
    class the yard's own big fish swim first — an invoice far above the
    yard's median open balance stays on the desk's mind all day."""
    from engine import invoice_balances_batch, big_fish_invoices

    big = big_fish_invoices(con)["invoice_nos"]
    balances = invoice_balances_batch(con)

    cands = []
    for inv in con.execute(
        """SELECT i.invoice_no, i.invoice_date, i.terms, c.account_name
           FROM invoices i JOIN customers c ON c.customer_id = i.customer_id
           WHERE i.status NOT IN ('Paid','Write-off','Draft')"""
    ):
        bal = balances.get(inv["invoice_no"], 0.0)
        if bal <= 0.009:
            continue
        d0 = _core._parse(inv["invoice_date"]) or today
        due = d0 + timedelta(days=_core.terms_days(inv["terms"]))
        late = (today - due).days
        fish = 0 if inv["invoice_no"] in big else 1
        tag = " · key account" if not fish else ""
        if late > 0:
            cands.append(
                (0, fish, -late, -bal, f"money:late:{today.isoformat()}:{inv['invoice_no']}",
                 f"Invoice {inv['invoice_no']} {late}d late — {inv['account_name']} ${bal:,.2f}{tag}",
                 f"/invoice/{inv['invoice_no']}#record-payment"))
        elif late == 0:
            cands.append(
                (1, fish, 0, -bal, f"money:due:{today.isoformat()}:{inv['invoice_no']}",
                 f"Invoice {inv['invoice_no']} due today — {inv['account_name']} ${bal:,.2f}{tag}",
                 f"/invoice/{inv['invoice_no']}#record-payment"))
    for p in con.execute(
        """SELECT c.invoice_no, c.amount, cu.account_name
           FROM collections c JOIN invoices i ON i.invoice_no = c.invoice_no
           JOIN customers cu ON cu.customer_id = i.customer_id
           WHERE date(c.pay_date) = date('now') AND c.kind = 'payment'"""
    ):
        cands.append(
            (2, 1, 0, 0, f"money:paid:{today.isoformat()}:{p['invoice_no']}:{p['amount']}",
             f"Paid today: {p['invoice_no']} — {p['account_name']} ${p['amount']:,.2f}",
             f"/invoice/{p['invoice_no']}"))
    cands.sort(key=lambda c: (c[0], c[1], c[2], c[3]))
    return [{"key": k, "text": t, "href": h} for _, _, _, _, k, t, h in cands]


def today_money_slot(con: sqlite3.Connection) -> dict | None:
    """The single money item for Today, or None."""
    _ensure_task_tables(con)
    done = {r[0] for r in con.execute("SELECT slot_key FROM today_money_done")}
    for c in _money_candidates(con, date.today()):
        if c["key"] not in done:
            return c
    return None


def advance_money_slot(con: sqlite3.Connection, key: str) -> None:
    """Kill the current money-slot instance; the next one slides in."""
    _ensure_task_tables(con)
    con.execute("INSERT OR IGNORE INTO today_money_done(slot_key) VALUES (?)", (key,))
    con.commit()


def _top_asset_item(con: sqlite3.Connection) -> dict | None:
    """The single most urgent shipping-paper problem for the day ticker:
    Reserved/Dispatched tickets failing fit, soonest ship first. Paper only
    matters at the gate — no problem means no item, and the ticker stays
    calm."""
    from engine import ticket_money

    cands = []
    for r in con.execute(
            """SELECT t.ticket_id, t.status, t.on_rent, a.unit_no, c.account_name
               FROM tickets t
               JOIN assets a ON a.asset_id = t.asset_id
               JOIN customers c ON c.customer_id = t.customer_id
               WHERE t.status IN ('Reserved','Dispatched')"""):
        fit = ticket_money(con, r["ticket_id"]).get("fit", "PASS")
        if fit != "PASS":
            cands.append({"ticket_id": r["ticket_id"], "unit_no": r["unit_no"],
                          "account_name": r["account_name"],
                          "on_rent": r["on_rent"], "fit": fit})
    if not cands:
        return None
    cands.sort(key=lambda c: (_core._parse(c["on_rent"]) or date.max).isoformat())
    t = cands[0]
    day = _core._parse(t["on_rent"])
    when = f" {day.strftime('%a')}" if day else ""
    short = {"FAIL-CERT": "cert expired", "FAIL-USCG": "needs USCG stamp",
             "FAIL-DNV": "needs DNV stamp", "FAIL-ABS": "needs ABS stamp"}.get(t["fit"], "bad paper")
    return {"text": f"{t['unit_no']} → {t['account_name']}{when}: {short}",
            "href": f"/ticket/{t['ticket_id']}",
            "key": f"top:asset:{t['ticket_id']}"}


def top_of_day(con: sqlite3.Connection, limit: int = 3) -> list:
    """Top-of-the-day ticker items: up to `limit` prioritized dicts.

    Overdue invoices lead (days late, then amount) — on a rough day three of
    them fill the ticker. Then invoices due today, then the single most
    urgent asset item, then money in. Each item is {key, text, href}.
    Snoozed/dismissed keys are skipped. The ticker category filter applies
    here too (2026-10-08): money items need the Money category enabled;
    the asset item is shipping paper, which the strip counts as Compliance.
    Filtering happens before the limit cut, so a disabled category never
    consumes one of the slots."""
    from engine_alerts import is_acked, get_ticker_cats
    enabled = get_ticker_cats(con)
    if not enabled:
        return []
    owed, cash_in = [], []
    if "money" in enabled:
        for c in _money_candidates(con, date.today()):
            if is_acked(con, c["key"]):
                continue
            (cash_in if c["key"].startswith("money:paid:") else owed).append(c)
    out = owed[:limit]
    if len(out) < limit and "compliance" in enabled:
        asset = _top_asset_item(con)
        if asset and not is_acked(con, asset["key"]):
            out.append(asset)
    if len(out) < limit:
        out.extend(cash_in[:limit - len(out)])
    # The verb names the decision; the href lands where it's made.
    verbs = (("money:late:", "Record payment"), ("money:due:", "Record payment"),
             ("money:paid:", "View"), ("top:asset:", "Review"))
    for it in out:
        key = it.get("key") or ""
        it["verb"] = next((v for p, v in verbs if key.startswith(p)), "Open")
    return out[:limit]


def today_must_do(con: sqlite3.Connection) -> list:
    """What has to happen today."""
    from engine import dashboard

    out = []
    today = date.today().isoformat()
    for t in con.execute(
        """SELECT ticket_id, customer_id, asset_id FROM tickets
           WHERE status = 'Dispatched'
             AND (on_rent IS NULL OR date(on_rent) <= date('now'))
           ORDER BY ticket_id"""
    ):
        out.append({"text": f"Dispatch {t['ticket_id']} — {t['asset_id']} to {t['customer_id']}",
                    "href": f"/ticket/{t['ticket_id']}", "key": f"must:disp:{t['ticket_id']}"})
    for t in con.execute(
        """SELECT ticket_id, customer_id, asset_id FROM tickets
           WHERE status = 'On Rent' AND date(off_rent) = date('now')"""
    ):
        out.append({"text": f"Due back today {t['ticket_id']} — {t['asset_id']} ({t['customer_id']})",
                    "href": f"/ticket/{t['ticket_id']}", "key": f"must:back:{t['ticket_id']}"})
    d = dashboard(con)
    if d.get("fail"):
        n = d["fail"]
        out.append({"text": f"{n} unit{'s' if n != 1 else ''} shipping with bad paper",
                    "href": "/tickets?flag=fit", "key": "must:fit"})
    for task in list_tasks(con, "must"):
        out.append({"text": task["text"], "href": task["link"], "key": f"must:task:{task['task_id']}",
                    "task_id": task["task_id"]})
    return out


def today_can_do(con: sqlite3.Connection) -> list:
    """When there's air."""
    from engine import fleet_compliance_watch

    out = []
    n = con.execute(
        "SELECT COUNT(*) FROM tickets WHERE status = 'Ready to Bill'").fetchone()[0]
    if n:
        out.append({"text": f"{n} tickets ready to bill", "href": "/invoice/new",
                    "key": "can:bill"})
    watch = fleet_compliance_watch(con)
    due = [w for w in watch if w["status"] == "due"]
    if due:
        out.append({"text": f"{len(due)} checklist items due this week", "href": "/assets",
                    "key": "can:watch"})
    # Quiet paper chores: expired certs on idle iron (a unit already on the
    # job passed receiving once — mid-job paper is the field's business).
    paper = con.execute(
        """SELECT COUNT(*) FROM assets a WHERE a.active = 1
           AND a.cert_expire IS NOT NULL AND date(a.cert_expire) < date('now')
           AND NOT EXISTS
             (SELECT 1 FROM tickets t WHERE t.asset_id = a.asset_id
              AND t.status NOT IN ('Billed','Closed','Void'))""").fetchone()[0]
    if paper:
        out.append({"text": f"{paper} expired cert{'s' if paper != 1 else ''} on idle iron",
                    "href": "/assets", "key": "can:paper"})
    # Quiet money note: open-ended rentals only earn a shoulder-tap when
    # another job is contending for the iron (the alert strip decides that).
    nooff = con.execute(
        """SELECT COUNT(*) FROM tickets
           WHERE status IN ('On Rent','Standby') AND (off_rent IS NULL OR off_rent='')"""
    ).fetchone()[0]
    if nooff:
        out.append({"text": f"{nooff} on rent with no end date",
                    "href": "/tickets?flag=nooff", "key": "can:nooff"})
    nq = con.execute(
        "SELECT COUNT(*) FROM quotes WHERE status NOT IN ('Void','Declined','Expired','Converted')").fetchone()[0]
    if nq:
        out.append({"text": f"{nq} live quotes waiting on follow-up", "href": "/quotes",
                    "key": "can:quotes"})
    idle = con.execute(
        """SELECT COUNT(*) FROM assets a WHERE a.active = 1 AND NOT EXISTS
           (SELECT 1 FROM tickets t WHERE t.asset_id = a.asset_id
            AND t.status NOT IN ('Billed','Closed','Void'))""").fetchone()[0]
    if idle:
        out.append({"text": f"{idle} idle units worth a sales call", "href": "/reports",
                    "key": "can:idle"})
    for task in list_tasks(con, "can"):
        out.append({"text": task["text"], "href": task["link"], "key": f"can:task:{task['task_id']}",
                    "task_id": task["task_id"]})
    return out


def today_later(con: sqlite3.Connection) -> list:
    """Parked."""
    return [
        {"text": t["text"], "href": t["link"], "key": f"later:task:{t['task_id']}",
         "task_id": t["task_id"]}
        for t in list_tasks(con, "later")
    ]


def today_tomorrow(con: sqlite3.Connection) -> list:
    """Tomorrow's must-dos, for the calm head-start state.

    Only tickets actually going on rent tomorrow that still need action —
    not every Dispatched ticket in the yard.
    """
    out = []
    for t in con.execute(
        """SELECT ticket_id, asset_id FROM tickets
           WHERE date(on_rent) = date('now', '+1 day')
             AND status IN ('Reserved', 'Dispatched')
           ORDER BY ticket_id LIMIT 5"""
    ):
        out.append({"text": f"Tomorrow: {t['ticket_id']} — {t['asset_id']}",
                    "href": f"/ticket/{t['ticket_id']}"})
    return out


def list_tasks(con: sqlite3.Connection, tier: str) -> list:
    _ensure_task_tables(con)
    return [
        {"task_id": r["task_id"], "text": r["text"], "link": r["link"] or ""}
        for r in con.execute(
            "SELECT task_id, text, link FROM today_tasks WHERE tier = ? AND done = 0 ORDER BY task_id",
            (tier,))
    ]


def add_task(con: sqlite3.Connection, text: str, tier: str, link: str = "") -> None:
    _ensure_task_tables(con)
    if tier not in ("must", "can", "later"):
        raise ValueError("bad tier")
    text = (text or "").strip()
    if not text:
        raise ValueError("empty task")
    link = (link or "").strip()
    if link and not link.startswith("/"):
        raise ValueError("bad link")
    con.execute("INSERT INTO today_tasks(text, tier, link) VALUES (?, ?, ?)", (text, tier, link))
    con.commit()


def complete_task(con: sqlite3.Connection, task_id: int, clerk: str = "") -> None:
    _ensure_task_tables(con)
    con.execute(
        """UPDATE today_tasks
           SET done = 1, done_at = strftime('%Y-%m-%d %H:%M:%f', 'now'), done_by = ?
           WHERE task_id = ?""",
        ((clerk or "").strip()[:40], task_id))
    con.commit()


def uncomplete_task(con: sqlite3.Connection, task_id: int) -> None:
    """Put a task back on its tier list (fat-fingered Done)."""
    _ensure_task_tables(con)
    con.execute("UPDATE today_tasks SET done = 0, done_at = NULL, done_by = '' WHERE task_id = ?",
                (task_id,))
    con.commit()


def list_stickies(con: sqlite3.Connection) -> list:
    """Quiet desk reminders, oldest first — the note you wrote longest ago is
    the one you're most likely to have forgotten. Pinned notes float to the
    top. Snoozed, hidden-until, and dismissed notes stay out of sight."""
    _ensure_task_tables(con)
    now = datetime.now().isoformat(sep=" ", timespec="seconds")
    return [
        {"sticky_id": r["sticky_id"], "text": r["text"],
         "priority": r["priority"] or 1, "color": r["color"] or "yellow",
         "pinned": bool(r["pinned"])}
        for r in con.execute(
            """SELECT sticky_id, text, priority, color, pinned FROM today_stickies
               WHERE dismissed = 0
               AND (snoozed_until IS NULL OR snoozed_until <= ?)
               AND (hide_until IS NULL OR hide_until <= ?)
               ORDER BY pinned DESC, priority DESC, sticky_id""", (now, now))
    ]


def update_sticky(con: sqlite3.Connection, sticky_id: int, **fields) -> None:
    """Update sticky-note attributes: priority, color, snoozed_until,
    hide_until, pinned, dismissed."""
    _ensure_task_tables(con)
    allowed = {"priority", "color", "snoozed_until", "hide_until", "pinned", "dismissed"}
    sets = [f"{k}=?" for k in fields if k in allowed]
    if not sets:
        return
    con.execute(f"UPDATE today_stickies SET {', '.join(sets)} WHERE sticky_id=?",
                [fields[k] for k in fields if k in allowed] + [sticky_id])
    con.commit()


def done_sticky(con: sqlite3.Connection, sticky_id: int, clerk: str = "") -> None:
    """Mark a sticky note Done: it goes to the done list, then peels off."""
    _ensure_task_tables(con)
    r = con.execute("SELECT text FROM today_stickies WHERE sticky_id=?",
                    (sticky_id,)).fetchone()
    if r:
        add_done_manual(con, f"Note done: {(r['text'] or '')[:180]}", "", clerk)
        con.execute("DELETE FROM today_stickies WHERE sticky_id=?", (sticky_id,))
        con.commit()


def add_sticky(con: sqlite3.Connection, text: str) -> int:
    """Stick a reminder on the desk. Returns the new sticky_id."""
    _ensure_task_tables(con)
    text = (text or "").strip()[:500]
    if not text:
        raise ValueError("empty note")
    cur = con.execute("INSERT INTO today_stickies(text) VALUES (?)", (text,))
    con.commit()
    return cur.lastrowid


def edit_sticky(con: sqlite3.Connection, sticky_id: int, text: str) -> None:
    """Rewrite a sticky note in place."""
    _ensure_task_tables(con)
    text = (text or "").strip()[:500]
    if not text:
        raise ValueError("empty note")
    con.execute("UPDATE today_stickies SET text = ? WHERE sticky_id = ?",
                (text, sticky_id))
    con.commit()


def remove_sticky(con: sqlite3.Connection, sticky_id: int) -> None:
    """Peel a sticky note off the desk."""
    _ensure_task_tables(con)
    con.execute("DELETE FROM today_stickies WHERE sticky_id = ?", (sticky_id,))
    con.commit()


def add_done_manual(con: sqlite3.Connection, text: str, link: str = "", clerk: str = "") -> None:
    """Log an ad-hoc completion by hand — the 'Other done' pop-up."""
    _ensure_task_tables(con)
    text = (text or "").strip()[:200]
    if not text:
        raise ValueError("empty entry")
    link = (link or "").strip()[:200]
    if link and not link.startswith("/"):
        raise ValueError("bad link")
    con.execute(
        """INSERT INTO done_manual(text, link, done_at, done_by)
           VALUES (?, ?, strftime('%Y-%m-%d %H:%M:%f', 'now'), ?)""",
        (text, link, (clerk or "").strip()[:40]))
    con.commit()


def remove_done_manual(con: sqlite3.Connection, entry_id: int) -> None:
    """Pull a hand-logged entry back off (fat-fingered Other done)."""
    _ensure_task_tables(con)
    con.execute("DELETE FROM done_manual WHERE entry_id = ?", (entry_id,))
    con.commit()


def done_today(con: sqlite3.Connection, limit: int = 20) -> list:
    """What got done today, newest first — the Done box at the bottom of Today."""
    start = con.execute("SELECT date('now')").fetchone()[0]
    return done_tasks(con, start, start, limit)


def done_period(con: sqlite3.Connection, period: str) -> tuple:
    """(start, end, label) for the done-log audit: today, week, year."""
    q = {
        "today": "SELECT date('now'), date('now'), 'Today'",
        "week": "SELECT date('now','weekday 0','-6 days'), date('now'), 'This week'",
        "year": "SELECT date('now','start of year'), date('now'), 'This year'",
    }[period if period in ("today", "week", "year") else "week"]
    return con.execute(q).fetchone()


def done_tasks(con: sqlite3.Connection, start: str, end: str, limit: int = 500) -> list:
    """Explicit completions in [start, end], newest first: tasks clicked off
    the to-do list plus hand-logged 'Other done' entries. Nothing inferred —
    payments and everything else live in their own audits, not here."""
    _ensure_task_tables(con)
    rows = [
        {"kind": "task", "task_id": r["task_id"], "text": r["text"], "tier": r["tier"],
         "done_at": r["done_at"], "done_by": r["done_by"], "link": r["link"] or ""}
        for r in con.execute(
            """SELECT task_id, text, tier, done_at, done_by, link FROM today_tasks
               WHERE done = 1 AND date(done_at) BETWEEN ? AND ?
               ORDER BY done_at DESC, task_id DESC LIMIT ?""", (start, end, limit))
    ]
    rows += [
        {"kind": "manual", "entry_id": r["entry_id"], "text": r["text"], "tier": "other",
         "done_at": r["done_at"], "done_by": r["done_by"], "link": r["link"] or ""}
        for r in con.execute(
            """SELECT entry_id, text, link, done_at, done_by FROM done_manual
               WHERE date(done_at) BETWEEN ? AND ?
               ORDER BY done_at DESC, entry_id DESC LIMIT ?""", (start, end, limit))
    ]
    rows.sort(key=lambda r: (r["done_at"] or ""), reverse=True)
    return rows[:limit]


def done_payments(con: sqlite3.Connection, start: str, end: str, limit: int = 500) -> list:
    """Payments collected in [start, end], newest first — money in the door."""
    return [
        {"pay_date": r["pay_date"], "invoice_no": r["invoice_no"],
         "account_name": r["account_name"], "amount": r["amount"],
         "method": r["method"] or "", "clerk": r["clerk"] or ""}
        for r in con.execute(
            """SELECT c.pay_date, c.invoice_no, c.amount, c.method, c.clerk,
                      cu.account_name
               FROM collections c
               JOIN invoices i ON i.invoice_no = c.invoice_no
               JOIN customers cu ON cu.customer_id = i.customer_id
               WHERE c.kind = 'payment' AND date(c.pay_date) BETWEEN ? AND ?
               ORDER BY c.pay_date DESC, c.rowid DESC LIMIT ?""", (start, end, limit))
    ]
