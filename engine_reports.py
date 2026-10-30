"""Push-button report engines + custom-build storage.

Three weekly push-button reports live here:
  1. ar_aging        — canonical AR aging table (no headers, no extra summaries)
  2. fleet_utilization — days-based per-unit utilization over a trailing window
  3. weeks_flow      — Jason's lean "This week's flow" (reservations, quotes
                       pending, job ends/returns, shop work); a monthly view
                       is exception-only, not a full ledger.

Custom builds: unlimited saved reports with real field + filter selection over
the eight named datasets in exportpack. Filters are genuine (date window,
contains, sort) — not just dataset + date range.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta

from engine_core import terms_days, cust_key, cust_code
from engine_accounting import invoice_totals
import exportpack

__all__ = ['ar_aging', 'fleet_utilization', 'weeks_flow', 'custom_datasets', 'custom_dataset_fields', 'run_custom', 'list_custom_reports', 'get_custom_report', 'save_custom_report', 'delete_custom_report']

# ---------------------------------------------------------------- AR aging

BUCKETS = ("current", "b1_30", "b31_60", "b61_90", "b90")
BUCKET_LABELS = {
    "current": "Current",
    "b1_30": "1–30",
    "b31_60": "31–60",
    "b61_90": "61–90",
    "b90": "90+",
}


def ar_aging(con: sqlite3.Connection, today: date | None = None) -> dict:
    """Canonical AR aging. Returns per-customer bucket rows plus TOTAL and
    % of Total footer rows. Only open balances — no collected/invoiced header."""
    today = today or date.today()
    cust: dict[str, dict] = {}
    for inv in con.execute(
        """SELECT i.invoice_no, i.invoice_date, i.terms,
                  c.customer_id AS cust_code, c.account_name
           FROM invoices i JOIN customers c ON c.id = i.customer_id
           WHERE i.status NOT IN ('Paid','Write-off','Draft')"""
    ):
        tot = invoice_totals(con, inv["invoice_no"])
        bal = tot["balance"]
        if bal <= 0.009:
            continue
        inv_date = _safe_date(inv["invoice_date"])
        due = inv_date + timedelta(days=terms_days(inv["terms"])) if inv_date else today
        late = (today - due).days
        if late <= 0:
            bucket = "current"
        elif late <= 30:
            bucket = "b1_30"
        elif late <= 60:
            bucket = "b31_60"
        elif late <= 90:
            bucket = "b61_90"
        else:
            bucket = "b90"
        cid = inv["cust_code"]
        row = cust.get(cid)
        if row is None:
            row = cust[cid] = {"customer": inv["account_name"], "customer_id": cid,
                               "total": 0.0, **{b: 0.0 for b in BUCKETS}}
        row[bucket] += bal
        row["total"] += bal
    rows = sorted(cust.values(), key=lambda r: -r["total"])
    total = {b: sum(r[b] for r in rows) for b in BUCKETS}
    grand = sum(total.values())
    pct = {b: (total[b] / grand * 100.0 if grand > 0.009 else 0.0) for b in BUCKETS}
    return {"today": today.isoformat(), "rows": rows, "total": total,
            "grand": grand, "pct": pct}


def _safe_date(val) -> date | None:
    s = str(val or "")[:10]
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


# ------------------------------------------------------- Fleet utilization

def fleet_utilization(con: sqlite3.Connection, days: int = 30,
                      today: date | None = None) -> dict:
    """Days-based utilization per unit over a trailing window.

    Days on rent = overlap of ticket on_rent..off_rent with the window.
    Down = overlap of open work-order open_date..close_date with the window.
    Idle = window days minus both. Util% = rent days / window days.
    Revenue = ticket-line billing in the window (not prorated).
    """
    today = today or date.today()
    days = max(1, min(365, int(days or 30)))
    start = today - timedelta(days=days - 1)
    window_days = days

    def overlap(a_start, a_end):
        a = _safe_date(a_start)
        b = _safe_date(a_end) or today
        if not a:
            return 0
        lo, hi = max(a, start), min(b, today)
        return max(0, (hi - lo).days + 1)

    # Rent days per asset from tickets (open-ended count through today).
    rent: dict[str, int] = {}
    for t in con.execute(
        """SELECT t.asset_id, t.on_rent, t.off_rent, t.status
           FROM tickets t WHERE t.on_rent IS NOT NULL AND t.on_rent != ''
             AND t.status NOT IN ('Billed','Closed','Void','Quoted')"""
    ):
        rent[t["asset_id"]] = rent.get(t["asset_id"], 0) + overlap(t["on_rent"], t["off_rent"])

    # Down (shop) days per asset from work orders.
    down: dict[str, int] = {}
    for w in con.execute(
        """SELECT asset_id, open_date, close_date FROM work_orders
           WHERE status != 'Void'"""
    ):
        d = overlap(w["open_date"], w["close_date"])
        if d:
            down[w["asset_id"]] = down.get(w["asset_id"], 0) + d

    # Revenue per asset: ticket-linked invoice lines on invoices dated in window.
    rev: dict[str, float] = {}
    for r in con.execute(
        """SELECT t.asset_id AS aid, l.amount + l.tax_amount AS amt
           FROM invoice_lines l
           JOIN invoices i ON i.id = l.invoice_id
           JOIN tickets t ON t.ticket_id = l.source_id
           WHERE l.source_type = 'ticket'
             AND i.invoice_date >= ? AND i.invoice_date <= ?""",
        (start.isoformat(), today.isoformat()),
    ):
        rev[r["aid"]] = rev.get(r["aid"], 0.0) + float(r["amt"] or 0)

    rows = []
    for a in con.execute(
        """SELECT id, asset_id, unit_no, category, description FROM assets
           WHERE active = 1 ORDER BY unit_no"""
    ):
        aid = a["id"]
        rent_days = min(rent.get(aid, 0), window_days)
        down_days = min(down.get(aid, 0), window_days)
        idle_days = max(0, window_days - rent_days - down_days)
        util = rent_days / window_days * 100.0
        rows.append({
            "unit_no": a["unit_no"], "category": a["category"] or "",
            "description": a["description"] or "",
            "rent_days": rent_days, "idle_days": idle_days, "down_days": down_days,
            "util_pct": round(util, 1), "revenue": round(rev.get(aid, 0.0), 2),
        })
    rows.sort(key=lambda r: -r["util_pct"])
    return {"days": days, "start": start.isoformat(), "end": today.isoformat(),
            "rows": rows}


# ------------------------------------------------------------ Week's flow

FLOW_SECTIONS = (
    ("reservations", "Reservations", "Ships out"),
    ("quotes", "Quotes pending", "Waiting on the customer"),
    ("job_ends", "Job ends / returns", "Coming home"),
    ("shop", "Shop work", "Down / in the shop"),
)


def weeks_flow(con: sqlite3.Connection, span: str = "week",
               today: date | None = None) -> dict:
    """Lean flow report. Weekly default: everything inside [today, today+7].
    Monthly: exception-only — only the items that smell off, with a 'why'."""
    today = today or date.today()
    span = "month" if span == "month" else "week"
    if span == "week":
        return _flow_week(con, today)
    return _flow_month_exceptions(con, today)


def _flow_week(con: sqlite3.Connection, today: date) -> dict:
    end = today + timedelta(days=7)
    s, e = today.isoformat(), end.isoformat()
    reservations = []
    for t in con.execute(
        """SELECT t.ticket_id, t.on_rent, a.unit_no, a.description, c.account_name
           FROM tickets t JOIN assets a ON a.id = t.asset_id
           JOIN customers c ON c.id = t.customer_id
           WHERE t.status = 'Reserved' AND t.on_rent >= ? AND t.on_rent <= ?
           ORDER BY t.on_rent""", (s, e)):
        reservations.append({"what": f"{t['ticket_id']} — {t['unit_no']} {t['description'] or ''}".strip(),
                             "who": t["account_name"], "when": t["on_rent"],
                             "href": f"/ticket/{t['ticket_id']}"})
    quotes = []
    for q in con.execute(
        """SELECT q.quote_no, q.quote_date, q.valid_until, q.job_name, c.account_name
           FROM quotes q JOIN customers c ON c.id = q.customer_id
           WHERE q.status IN ('Draft','Sent')
           ORDER BY q.valid_until"""):
        quotes.append({"what": f"Quote {q['quote_no']} {q['job_name'] or ''}".strip(),
                       "who": q["account_name"],
                       "when": q["valid_until"] or q["quote_date"],
                       "href": f"/summary/quote/{q['quote_no']}"})
    job_ends = []
    for t in con.execute(
        """SELECT t.ticket_id, t.off_rent, a.unit_no, c.account_name
           FROM tickets t JOIN assets a ON a.id = t.asset_id
           JOIN customers c ON c.id = t.customer_id
           WHERE t.status IN ('On Rent','Standby')
             AND t.off_rent >= ? AND t.off_rent <= ?
           ORDER BY t.off_rent""", (s, e)):
        job_ends.append({"what": f"{t['ticket_id']} — {t['unit_no']} back",
                         "who": t["account_name"], "when": t["off_rent"],
                         "href": f"/ticket/{t['ticket_id']}"})
    shop = []
    for w in con.execute(
        """SELECT w.wo_id, w.work_type, w.open_date, w.vendor, a.unit_no,
                  cu.account_name
           FROM work_orders w JOIN assets a ON a.id = w.asset_id
           LEFT JOIN customers cu ON cu.id = w.customer_id
           WHERE w.status IN ('Open','In progress')
           ORDER BY w.open_date"""):
        shop.append({"what": f"WO {w['wo_id']} — {w['unit_no']} {w['work_type'] or ''}".strip(),
                     "who": w["vendor"] or w["account_name"] or "Yard",
                     "when": w["open_date"], "href": f"/summary/wo/{w['wo_id']}"})
    return {"span": "week", "start": s, "end": e,
            "sections": [("reservations", reservations), ("quotes", quotes),
                         ("job_ends", job_ends), ("shop", shop)]}


def _flow_month_exceptions(con: sqlite3.Connection, today: date) -> dict:
    """Monthly is exception-only: reservations that should have shipped,
    stale quotes, past-due returns, shop jobs open too long."""
    s = today.isoformat()
    month_ago = (today - timedelta(days=30)).isoformat()
    two_months = (today - timedelta(days=60)).isoformat()
    reservations = []
    for t in con.execute(
        """SELECT t.ticket_id, t.on_rent, a.unit_no, c.account_name
           FROM tickets t JOIN assets a ON a.id = t.asset_id
           JOIN customers c ON c.id = t.customer_id
           WHERE t.status = 'Reserved' AND t.on_rent < ?
           ORDER BY t.on_rent""", (s,)):
        why = "should have shipped by now" if t["on_rent"] < month_ago else "ship date passed"
        reservations.append({"what": f"{t['ticket_id']} — {t['unit_no']}",
                             "who": t["account_name"], "when": t["on_rent"],
                             "why": why, "href": f"/ticket/{t['ticket_id']}"})
    quotes = []
    for q in con.execute(
        """SELECT q.quote_no, q.quote_date, q.valid_until, q.job_name, c.account_name
           FROM quotes q JOIN customers c ON c.id = q.customer_id
           WHERE q.status IN ('Draft','Sent')
             AND (q.quote_date < ? OR (q.valid_until IS NOT NULL AND q.valid_until != '' AND q.valid_until < ?))
           ORDER BY q.quote_date""", (two_months, s)):
        why = ("sitting 60+ days" if str(q["quote_date"] or "") < two_months
               else "validity expired")
        quotes.append({"what": f"Quote {q['quote_no']} {q['job_name'] or ''}".strip(),
                       "who": q["account_name"],
                       "when": q["valid_until"] or q["quote_date"], "why": why,
                       "href": f"/summary/quote/{q['quote_no']}"})
    job_ends = []
    for t in con.execute(
        """SELECT t.ticket_id, t.off_rent, t.on_rent, a.unit_no, c.account_name
           FROM tickets t JOIN assets a ON a.id = t.asset_id
           JOIN customers c ON c.id = t.customer_id
           WHERE t.status IN ('On Rent','Standby')
             AND (t.off_rent < ? OR (t.off_rent IS NULL OR t.off_rent = '') AND t.on_rent < ?)
           ORDER BY t.off_rent""", (s, two_months)):
        why = "return date passed" if (t["off_rent"] or "") else "open-ended 60+ days"
        job_ends.append({"what": f"{t['ticket_id']} — {t['unit_no']}",
                         "who": t["account_name"],
                         "when": t["off_rent"] or t["on_rent"], "why": why,
                         "href": f"/ticket/{t['ticket_id']}"})
    shop = []
    for w in con.execute(
        """SELECT w.wo_id, w.work_type, w.open_date, a.unit_no
           FROM work_orders w JOIN assets a ON a.id = w.asset_id
           WHERE w.status IN ('Open','In progress') AND w.open_date < ?
           ORDER BY w.open_date""", (month_ago,)):
        shop.append({"what": f"WO {w['wo_id']} — {w['unit_no']} {w['work_type'] or ''}".strip(),
                     "who": "Shop", "when": w["open_date"],
                     "why": "open over a month", "href": f"/summary/wo/{w['wo_id']}"})
    end = (today + timedelta(days=30)).isoformat()
    return {"span": "month", "start": s, "end": end,
            "sections": [("reservations", reservations), ("quotes", quotes),
                         ("job_ends", job_ends), ("shop", shop)]}


# -------------------------------------------------------- Custom builds


def _ensure_custom_tables(con: sqlite3.Connection) -> None:
    """Repair-only compatibility hook; schema.sql owns current table DDL."""
    if not con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='custom_reports'").fetchone():
        raise RuntimeError("Database schema is incomplete: custom_reports is missing")


def custom_datasets() -> list:
    return list(exportpack.PACK_LABELS)


def custom_dataset_fields(dataset: str) -> list:
    """Selectable field names for a dataset (exportpack PACKS keys + 'all')."""
    if dataset == "all":
        return []
    if dataset not in exportpack.PACKS:
        raise ValueError("Unknown dataset")
    return list(exportpack.cols_named(dataset))


def run_custom(con: sqlite3.Connection, dataset: str, fields: list | None = None,
               from_date: str = "", to_date: str = "",
               contains_field: str = "", contains_text: str = "",
               sort_field: str = "", sort_dir: str = "asc") -> tuple:
    """Returns (headers, rows) after applying field selection and filters."""
    if dataset == "all":
        raise ValueError("'Everything' cannot be used in a custom build")
    if dataset not in exportpack.PACKS:
        raise ValueError("Unknown dataset")
    cols = exportpack.cols_named(dataset)
    rows = [dict(r) for r in exportpack.rows_named(con, dataset, from_date or "", to_date or "")]
    if contains_field and contains_text:
        needle = contains_text.strip().lower()
        rows = [r for r in rows if needle in str(r.get(contains_field, "") or "").lower()]
    if sort_field and sort_field in cols:
        rows.sort(key=lambda r: str(r.get(sort_field) or ""),
                  reverse=(sort_dir == "desc"))
    headers = [f for f in (fields or cols) if f in cols] or cols
    out = [[r.get(h, "") for h in headers] for r in rows]
    return headers, out


def list_custom_reports(con: sqlite3.Connection) -> list:
    _ensure_custom_tables(con)
    rows = con.execute("SELECT * FROM custom_reports ORDER BY label").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["field_count"] = len(json.loads(d.get("fields") or "[]"))
        out.append(d)
    return out


def get_custom_report(con: sqlite3.Connection, report_id: int) -> dict | None:
    _ensure_custom_tables(con)
    r = con.execute("SELECT * FROM custom_reports WHERE report_id=?",
                    (report_id,)).fetchone()
    return dict(r) if r else None


def save_custom_report(con: sqlite3.Connection, label: str, dataset: str,
                       fields: list, from_date: str = "", to_date: str = "",
                       contains_field: str = "", contains_text: str = "",
                       sort_field: str = "", sort_dir: str = "asc",
                       how: str = "csv") -> int:
    _ensure_custom_tables(con)
    label = (label or "").strip()[:60]
    if not label:
        raise ValueError("Build name is required")
    if dataset not in exportpack.PACKS:
        raise ValueError("Unknown dataset")
    cur = con.execute(
        """INSERT INTO custom_reports(label, dataset, fields, from_date, to_date,
                                      contains_field, contains_text, sort_field, sort_dir, how)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (label, dataset, json.dumps(list(fields or [])), from_date or "",
         to_date or "", contains_field or "", contains_text or "",
         sort_field or "", "desc" if sort_dir == "desc" else "asc",
         how if how in ("csv", "xlsx", "json") else "csv"))
    con.commit()
    return cur.lastrowid


def delete_custom_report(con: sqlite3.Connection, report_id: int) -> None:
    _ensure_custom_tables(con)
    con.execute("DELETE FROM custom_reports WHERE report_id=?", (report_id,))
    con.commit()


# ---------------------------------------------------------------- Mixed reports
# Mixed report (Jason 2026-10-24, built in-app): ONE time-based report
# carrying mixed data types — sales + rentals, once or every month —
# sortable, filterable, exportable, printable, savable. The Data tab's
# custom builder already does single datasets; mixing is what was
# missing. Grain per kind (counted exactly once, no double count):
# rentals = rental tickets, sales = sale docs, work orders = WOs,
# invoices = invoice docs, payments = the one money-in ledger
# (collections + doc_collections, carried mirrors excluded — they are
# the same money as the ticket/WO row), credits = credit memos.
# Petty cash is NOT a kind (sealed drawer, no relationships).
# Quotes are NOT kinds (unposted). Change orders are NOT kinds
# either (build 'v': a Change Order is its own receivable, settled
# on its own summary — it is not folded into any invoice, so it
# never counts here; adding it as a kind is Jason's call, not
# assumed). Units/customers are NOT
# kinds (snapshots, no event date) — units ride the Unit column,
# customers ride the builder's customer filter.

# (key, label, money?) — money kinds hide when the billing module is off.
MIXED_KINDS = [
    ("rentals", "Rentals", False),
    ("sales", "Sales", False),
    ("work_orders", "Work orders", False),
    ("invoices", "Invoices", True),
    ("payments", "Payments", True),
    ("credits", "Credits", True),
]

MIXED_KIND_LABELS = {k: lab for k, lab, _ in MIXED_KINDS}

MIXED_COLUMNS = ["Date", "Type", "Ref", "Customer", "Unit / Doc", "Amount", "Status"]


def _mixed_in(d: str, start: str, end: str) -> bool:
    """ISO date inside [start, end]; empty bounds mean no bound, and a
    dateless row is kept — filtering must never silently drop data."""
    if not d:
        return True
    if start and d < start:
        return False
    if end and d > end:
        return False
    return True


def mixed_range(time_mode: str, date_from: str = "", date_to: str = "",
                month: str = "") -> tuple:
    """Resolve a builder timeframe to a (from, to) ISO pair. Monthly
    presets carry only the month; each run resolves it to that calendar
    month (a bad month falls back to the current month, never to
    all-time). Once presets carry fixed from/to."""
    if time_mode == "monthly":
        try:
            y, m = (month or "").split("-")
            y, m = int(y), int(m)
            if not 1 <= m <= 12:
                raise ValueError
        except (ValueError, AttributeError):
            today = date.today()
            y, m = today.year, today.month
        first = date(y, m, 1)
        nxt = date(y + (m == 12), (m % 12) + 1, 1)
        last = nxt - timedelta(days=1)
        return first.isoformat(), last.isoformat()
    return date_from or "", date_to or ""


def mixed_rows(con: sqlite3.Connection, kinds: list, date_from: str = "",
               date_to: str = "", customer_id: str = "") -> tuple:
    """Returns (rows, totals): rows are common-column dicts (date, type,
    ref, customer, unit, amount, status), newest first; totals maps each
    selected kind key to its Amount sum. Rows come from the exportpack
    dataset queries (the computed amounts) plus a direct sales query —
    no second set of money math."""
    kinds = [k for k in (kinds or []) if k in MIXED_KIND_LABELS]
    rows = []
    if "rentals" in kinds:
        for t in exportpack.tickets_rows(con):
            d = (t.get("on_rent") or "")[:10]
            if not _mixed_in(d, date_from, date_to):
                continue
            if customer_id and t.get("customer_id") != customer_id:
                continue
            rows.append({"date": d, "type": "Rental", "ref": t["ticket_id"],
                         "customer": t.get("account_name") or "",
                         "unit": t.get("unit_no") or "",
                         "amount": round(float(t.get("total") or 0), 2),
                         "status": t.get("status") or ""})
    if "sales" in kinds:
        for s in con.execute(
                """SELECT s.sale_id, s.sale_date, s.amount,
                          c.customer_id AS customer_id,
                          COALESCE(c.account_name, '') AS account_name,
                          COALESCE(a.unit_no, '') AS unit_no
                   FROM sales s
                   LEFT JOIN customers c ON c.id = s.customer_id
                   LEFT JOIN assets a ON a.id = s.asset_id
                   ORDER BY s.sale_date"""):
            d = str(s["sale_date"] or "")[:10]
            if not _mixed_in(d, date_from, date_to):
                continue
            if customer_id and s["customer_id"] != customer_id:
                continue
            rows.append({"date": d, "type": "Sales Ticket", "ref": s["sale_id"],
                         "customer": s["account_name"],
                         "unit": s["unit_no"],
                         "amount": round(float(s["amount"] or 0), 2),
                         "status": "Sold"})
    if "work_orders" in kinds:
        for w in exportpack.wo_rows(con):
            d = (w.get("open_date") or "")[:10]
            if not _mixed_in(d, date_from, date_to):
                continue
            if customer_id and w.get("customer_id") != customer_id:
                continue
            rows.append({"date": d, "type": "Work order", "ref": w["wo_id"],
                         "customer": w.get("account_name") or "",
                         "unit": w.get("unit_no") or "",
                         "amount": round(float(w.get("bill_amount") or 0), 2),
                         "status": w.get("status") or ""})
    if "invoices" in kinds:
        for i in exportpack.invoices_rows(con):
            d = (i.get("invoice_date") or "")[:10]
            if not _mixed_in(d, date_from, date_to):
                continue
            if customer_id and i.get("customer_id") != customer_id:
                continue
            rows.append({"date": d, "type": "Invoice", "ref": i["invoice_no"],
                         "customer": i.get("account_name") or "",
                         "unit": "",
                         "amount": round(float(i.get("total") or 0), 2),
                         "status": i.get("status") or ""})
    if "payments" in kinds:
        for p in exportpack.collections_rows(con):
            if p.get("carried_from"):
                continue
            d = (p.get("pay_date") or "")[:10]
            if not _mixed_in(d, date_from, date_to):
                continue
            if customer_id and p.get("customer_id") != customer_id:
                continue
            rows.append({"date": d, "type": "Payment", "ref": p["pay_id"],
                         "customer": p.get("account_name") or "",
                         "unit": p.get("invoice_no") or "",
                         "amount": round(float(p.get("signed_amount") or 0), 2),
                         "status": p.get("method") or ""})
        for p in exportpack.doccollections_rows(con):
            d = (p.get("pay_date") or "")[:10]
            if not _mixed_in(d, date_from, date_to):
                continue
            if customer_id and p.get("customer_id") != customer_id:
                continue
            rows.append({"date": d, "type": "Payment", "ref": p["pay_id"],
                         "customer": p.get("account_name") or "",
                         "unit": p.get("doc_ref") or "",
                         "amount": round(float(p.get("signed_amount") or 0), 2),
                         "status": p.get("method") or ""})
    if "credits" in kinds:
        cust = {r["customer_id"]: r["account_name"] for r in con.execute(
            "SELECT customer_id, account_name FROM customers")}
        for cm in exportpack.credits_rows(con):
            d = (cm.get("cm_date") or "")[:10]
            if not _mixed_in(d, date_from, date_to):
                continue
            if customer_id and cm.get("customer_id") != customer_id:
                continue
            rows.append({"date": d, "type": "Credit", "ref": cm["cm_no"],
                         "customer": cust.get(cm.get("customer_id"), ""),
                         "unit": "",
                         "amount": round(float(cm.get("face") or 0), 2),
                         "status": "Open" if float(cm.get("unapplied") or 0) else "Applied"})
    # Newest first; same-date rows keep type/ref order (stable sort).
    rows.sort(key=lambda r: (r["type"], r["ref"]))
    rows.sort(key=lambda r: r["date"], reverse=True)
    type_of = {"Rental": "rentals", "Sales Ticket": "sales", "Work order": "work_orders",
               "Invoice": "invoices", "Payment": "payments", "Credit": "credits"}
    totals = {}
    for k in kinds:
        totals[k] = round(sum(r["amount"] for r in rows
                              if type_of.get(r["type"]) == k), 2)
    return rows, totals


def _ensure_mixed_tables(con: sqlite3.Connection) -> None:
    """Repair-only compatibility hook; schema.sql owns current table DDL."""
    if not con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='mixed_presets'").fetchone():
        raise RuntimeError("Database schema is incomplete: mixed_presets is missing")


def list_mixed_presets(con: sqlite3.Connection) -> list:
    _ensure_mixed_tables(con)
    out = []
    for r in con.execute("SELECT * FROM mixed_presets ORDER BY name"):
        d = dict(r)
        d["customer_id"] = cust_code(con, d.get("customer_id")) or ""
        out.append(d)
    return out


def get_mixed_preset(con: sqlite3.Connection, preset_id: int) -> dict | None:
    _ensure_mixed_tables(con)
    r = con.execute("SELECT * FROM mixed_presets WHERE preset_id=?",
                    (preset_id,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["customer_id"] = cust_code(con, d.get("customer_id")) or ""
    return d


def save_mixed_preset(con: sqlite3.Connection, name: str, kinds: list,
                      time_mode: str = "once", date_from: str = "",
                      date_to: str = "", month: str = "",
                      customer_id: str = "", filter_text: str = "",
                      sort_col: int = 0, sort_dir: str = "desc") -> int:
    """Save by name — re-saving a name updates that preset (no duplicate
    names, same as a document number never renumbering: the name IS the
    preset's identity)."""
    _ensure_mixed_tables(con)
    name = (name or "").strip()[:60]
    if not name:
        raise ValueError("Preset name is required")
    kinds = [k for k in (kinds or []) if k in MIXED_KIND_LABELS]
    if not kinds:
        raise ValueError("Pick at least one kind")
    if time_mode not in ("once", "monthly"):
        time_mode = "once"
    try:
        sort_col = int(sort_col)
    except (TypeError, ValueError):
        sort_col = 0
    sort_col = max(0, min(len(MIXED_COLUMNS) - 1, sort_col))
    sort_dir = "asc" if sort_dir == "asc" else "desc"
    existing = con.execute("SELECT preset_id FROM mixed_presets WHERE name=?",
                           (name,)).fetchone()
    vals = (",".join(kinds), time_mode, date_from or "", date_to or "",
            month or "", cust_key(con, customer_id), (filter_text or "")[:200],
            sort_col, sort_dir)
    if existing:
        con.execute(
            """UPDATE mixed_presets SET kinds=?, time_mode=?, date_from=?,
               date_to=?, month=?, customer_id=?, filter_text=?, sort_col=?,
               sort_dir=? WHERE preset_id=?""",
            vals + (existing["preset_id"],))
        pid = existing["preset_id"]
    else:
        cur = con.execute(
            """INSERT INTO mixed_presets(name, kinds, time_mode, date_from,
               date_to, month, customer_id, filter_text, sort_col, sort_dir)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (name,) + vals)
        pid = cur.lastrowid
    con.commit()
    return pid


def delete_mixed_preset(con: sqlite3.Connection, preset_id: int) -> None:
    _ensure_mixed_tables(con)
    con.execute("DELETE FROM mixed_presets WHERE preset_id=?", (preset_id,))
    con.commit()


# ---------------------------------------------------------------- Mixed reports
# Mixed report (Jason 2026-10-24, built in-app): ONE time-based report
# carrying mixed data types — sales + rentals, once or every month —
# sortable, filterable, exportable, printable, savable. The Data tab's
# custom builder already does single datasets; mixing is what was
# missing. Grain per kind (counted exactly once, no double count):
# rentals = rental tickets, sales = sale docs, work orders = WOs,
# invoices = invoice docs, payments = the one money-in ledger
# (collections + doc_collections, carried mirrors excluded — they are
# the same money as the ticket/WO row), credits = credit memos.
# Petty cash is NOT a kind (sealed drawer, no relationships).
# Quotes are NOT kinds (unposted). Change orders are NOT kinds
# either (build 'v': a Change Order is its own receivable, settled
# on its own summary — it is not folded into any invoice, so it
# never counts here; adding it as a kind is Jason's call, not
# assumed). Units/customers are NOT
# kinds (snapshots, no event date) — units ride the Unit column,
# customers ride the builder's customer filter.

# (key, label, money?) — money kinds hide when the billing module is off.
MIXED_KINDS = [
    ("rentals", "Rentals", False),
    ("sales", "Sales", False),
    ("work_orders", "Work orders", False),
    ("invoices", "Invoices", True),
    ("payments", "Payments", True),
    ("credits", "Credits", True),
]

MIXED_KIND_LABELS = {k: lab for k, lab, _ in MIXED_KINDS}

MIXED_COLUMNS = ["Date", "Type", "Ref", "Customer", "Unit / Doc", "Amount", "Status"]


def _mixed_in(d: str, start: str, end: str) -> bool:
    """ISO date inside [start, end]; empty bounds mean no bound, and a
    dateless row is kept — filtering must never silently drop data."""
    if not d:
        return True
    if start and d < start:
        return False
    if end and d > end:
        return False
    return True


def mixed_range(time_mode: str, date_from: str = "", date_to: str = "",
                month: str = "") -> tuple:
    """Resolve a builder timeframe to a (from, to) ISO pair. Monthly
    presets carry only the month; each run resolves it to that calendar
    month (a bad month falls back to the current month, never to
    all-time). Once presets carry fixed from/to."""
    if time_mode == "monthly":
        try:
            y, m = (month or "").split("-")
            y, m = int(y), int(m)
            if not 1 <= m <= 12:
                raise ValueError
        except (ValueError, AttributeError):
            today = date.today()
            y, m = today.year, today.month
        first = date(y, m, 1)
        nxt = date(y + (m == 12), (m % 12) + 1, 1)
        last = nxt - timedelta(days=1)
        return first.isoformat(), last.isoformat()
    return date_from or "", date_to or ""


def mixed_rows(con: sqlite3.Connection, kinds: list, date_from: str = "",
               date_to: str = "", customer_id: str = "") -> tuple:
    """Returns (rows, totals): rows are common-column dicts (date, type,
    ref, customer, unit, amount, status), newest first; totals maps each
    selected kind key to its Amount sum. Rows come from the exportpack
    dataset queries (the computed amounts) plus a direct sales query —
    no second set of money math."""
    kinds = [k for k in (kinds or []) if k in MIXED_KIND_LABELS]
    rows = []
    if "rentals" in kinds:
        for t in exportpack.tickets_rows(con):
            d = (t.get("on_rent") or "")[:10]
            if not _mixed_in(d, date_from, date_to):
                continue
            if customer_id and t.get("customer_id") != customer_id:
                continue
            rows.append({"date": d, "type": "Rental", "ref": t["ticket_id"],
                         "customer": t.get("account_name") or "",
                         "unit": t.get("unit_no") or "",
                         "amount": round(float(t.get("total") or 0), 2),
                         "status": t.get("status") or ""})
    if "sales" in kinds:
        for s in con.execute(
                """SELECT s.sale_id, s.sale_date, s.amount,
                          c.customer_id AS customer_id,
                          COALESCE(c.account_name, '') AS account_name,
                          COALESCE(a.unit_no, '') AS unit_no
                   FROM sales s
                   LEFT JOIN customers c ON c.id = s.customer_id
                   LEFT JOIN assets a ON a.id = s.asset_id
                   ORDER BY s.sale_date"""):
            d = str(s["sale_date"] or "")[:10]
            if not _mixed_in(d, date_from, date_to):
                continue
            if customer_id and s["customer_id"] != customer_id:
                continue
            rows.append({"date": d, "type": "Sales Ticket", "ref": s["sale_id"],
                         "customer": s["account_name"],
                         "unit": s["unit_no"],
                         "amount": round(float(s["amount"] or 0), 2),
                         "status": "Sold"})
    if "work_orders" in kinds:
        for w in exportpack.wo_rows(con):
            d = (w.get("open_date") or "")[:10]
            if not _mixed_in(d, date_from, date_to):
                continue
            if customer_id and w.get("customer_id") != customer_id:
                continue
            rows.append({"date": d, "type": "Work order", "ref": w["wo_id"],
                         "customer": w.get("account_name") or "",
                         "unit": w.get("unit_no") or "",
                         "amount": round(float(w.get("bill_amount") or 0), 2),
                         "status": w.get("status") or ""})
    if "invoices" in kinds:
        for i in exportpack.invoices_rows(con):
            d = (i.get("invoice_date") or "")[:10]
            if not _mixed_in(d, date_from, date_to):
                continue
            if customer_id and i.get("customer_id") != customer_id:
                continue
            rows.append({"date": d, "type": "Invoice", "ref": i["invoice_no"],
                         "customer": i.get("account_name") or "",
                         "unit": "",
                         "amount": round(float(i.get("total") or 0), 2),
                         "status": i.get("status") or ""})
    if "payments" in kinds:
        for p in exportpack.collections_rows(con):
            if p.get("carried_from"):
                continue
            d = (p.get("pay_date") or "")[:10]
            if not _mixed_in(d, date_from, date_to):
                continue
            if customer_id and p.get("customer_id") != customer_id:
                continue
            rows.append({"date": d, "type": "Payment", "ref": p["pay_id"],
                         "customer": p.get("account_name") or "",
                         "unit": p.get("invoice_no") or "",
                         "amount": round(float(p.get("signed_amount") or 0), 2),
                         "status": p.get("method") or ""})
        for p in exportpack.doccollections_rows(con):
            d = (p.get("pay_date") or "")[:10]
            if not _mixed_in(d, date_from, date_to):
                continue
            if customer_id and p.get("customer_id") != customer_id:
                continue
            rows.append({"date": d, "type": "Payment", "ref": p["pay_id"],
                         "customer": p.get("account_name") or "",
                         "unit": p.get("doc_ref") or "",
                         "amount": round(float(p.get("signed_amount") or 0), 2),
                         "status": p.get("method") or ""})
    if "credits" in kinds:
        cust = {r["customer_id"]: r["account_name"] for r in con.execute(
            "SELECT customer_id, account_name FROM customers")}
        for cm in exportpack.credits_rows(con):
            d = (cm.get("cm_date") or "")[:10]
            if not _mixed_in(d, date_from, date_to):
                continue
            if customer_id and cm.get("customer_id") != customer_id:
                continue
            rows.append({"date": d, "type": "Credit", "ref": cm["cm_no"],
                         "customer": cust.get(cm.get("customer_id"), ""),
                         "unit": "",
                         "amount": round(float(cm.get("face") or 0), 2),
                         "status": "Open" if float(cm.get("unapplied") or 0) else "Applied"})
    # Newest first; same-date rows keep type/ref order (stable sort).
    rows.sort(key=lambda r: (r["type"], r["ref"]))
    rows.sort(key=lambda r: r["date"], reverse=True)
    type_of = {"Rental": "rentals", "Sales Ticket": "sales", "Work order": "work_orders",
               "Invoice": "invoices", "Payment": "payments", "Credit": "credits"}
    totals = {}
    for k in kinds:
        totals[k] = round(sum(r["amount"] for r in rows
                              if type_of.get(r["type"]) == k), 2)
    return rows, totals


def _ensure_mixed_tables(con: sqlite3.Connection) -> None:
    """Repair-only compatibility hook; schema.sql owns current table DDL."""
    if not con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='mixed_presets'").fetchone():
        raise RuntimeError("Database schema is incomplete: mixed_presets is missing")


def list_mixed_presets(con: sqlite3.Connection) -> list:
    _ensure_mixed_tables(con)
    out = []
    for r in con.execute("SELECT * FROM mixed_presets ORDER BY name"):
        d = dict(r)
        d["customer_id"] = cust_code(con, d.get("customer_id")) or ""
        out.append(d)
    return out


def get_mixed_preset(con: sqlite3.Connection, preset_id: int) -> dict | None:
    _ensure_mixed_tables(con)
    r = con.execute("SELECT * FROM mixed_presets WHERE preset_id=?",
                    (preset_id,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["customer_id"] = cust_code(con, d.get("customer_id")) or ""
    return d


def save_mixed_preset(con: sqlite3.Connection, name: str, kinds: list,
                      time_mode: str = "once", date_from: str = "",
                      date_to: str = "", month: str = "",
                      customer_id: str = "", filter_text: str = "",
                      sort_col: int = 0, sort_dir: str = "desc") -> int:
    """Save by name — re-saving a name updates that preset (no duplicate
    names, same as a document number never renumbering: the name IS the
    preset's identity)."""
    _ensure_mixed_tables(con)
    name = (name or "").strip()[:60]
    if not name:
        raise ValueError("Preset name is required")
    kinds = [k for k in (kinds or []) if k in MIXED_KIND_LABELS]
    if not kinds:
        raise ValueError("Pick at least one kind")
    if time_mode not in ("once", "monthly"):
        time_mode = "once"
    try:
        sort_col = int(sort_col)
    except (TypeError, ValueError):
        sort_col = 0
    sort_col = max(0, min(len(MIXED_COLUMNS) - 1, sort_col))
    sort_dir = "asc" if sort_dir == "asc" else "desc"
    existing = con.execute("SELECT preset_id FROM mixed_presets WHERE name=?",
                           (name,)).fetchone()
    vals = (",".join(kinds), time_mode, date_from or "", date_to or "",
            month or "", cust_key(con, customer_id), (filter_text or "")[:200],
            sort_col, sort_dir)
    if existing:
        con.execute(
            """UPDATE mixed_presets SET kinds=?, time_mode=?, date_from=?,
               date_to=?, month=?, customer_id=?, filter_text=?, sort_col=?,
               sort_dir=? WHERE preset_id=?""",
            vals + (existing["preset_id"],))
        pid = existing["preset_id"]
    else:
        cur = con.execute(
            """INSERT INTO mixed_presets(name, kinds, time_mode, date_from,
               date_to, month, customer_id, filter_text, sort_col, sort_dir)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (name,) + vals)
        pid = cur.lastrowid
    con.commit()
    return pid


def delete_mixed_preset(con: sqlite3.Connection, preset_id: int) -> None:
    _ensure_mixed_tables(con)
    con.execute("DELETE FROM mixed_presets WHERE preset_id=?", (preset_id,))
    con.commit()
