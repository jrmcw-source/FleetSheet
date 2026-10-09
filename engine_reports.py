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

from engine_core import terms_days
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

_OPEN_INVOICE_STATUSES = ("Paid", "Write-off", "Draft")


def ar_aging(con: sqlite3.Connection, today: date | None = None) -> dict:
    """Canonical AR aging. Returns per-customer bucket rows plus TOTAL and
    % of Total footer rows. Only open balances — no collected/invoiced header."""
    today = today or date.today()
    cust: dict[str, dict] = {}
    for inv in con.execute(
        """SELECT i.invoice_no, i.invoice_date, i.terms, i.customer_id, c.account_name
           FROM invoices i JOIN customers c ON c.customer_id = i.customer_id
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
        cid = inv["customer_id"]
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
           JOIN invoices i ON i.invoice_no = l.invoice_no
           JOIN tickets t ON t.ticket_id = l.source_id
           WHERE l.source_type = 'ticket'
             AND i.invoice_date >= ? AND i.invoice_date <= ?""",
        (start.isoformat(), today.isoformat()),
    ):
        rev[r["aid"]] = rev.get(r["aid"], 0.0) + float(r["amt"] or 0)

    rows = []
    for a in con.execute(
        """SELECT asset_id, unit_no, category, description FROM assets
           WHERE active = 1 ORDER BY unit_no"""
    ):
        aid = a["asset_id"]
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
           FROM tickets t JOIN assets a ON a.asset_id = t.asset_id
           JOIN customers c ON c.customer_id = t.customer_id
           WHERE t.status = 'Reserved' AND t.on_rent >= ? AND t.on_rent <= ?
           ORDER BY t.on_rent""", (s, e)):
        reservations.append({"what": f"{t['ticket_id']} — {t['unit_no']} {t['description'] or ''}".strip(),
                             "who": t["account_name"], "when": t["on_rent"],
                             "href": f"/ticket/{t['ticket_id']}"})
    quotes = []
    for q in con.execute(
        """SELECT q.quote_no, q.quote_date, q.valid_until, q.job_name, c.account_name
           FROM quotes q JOIN customers c ON c.customer_id = q.customer_id
           WHERE q.status IN ('Draft','Sent')
           ORDER BY q.valid_until"""):
        quotes.append({"what": f"Quote {q['quote_no']} {q['job_name'] or ''}".strip(),
                       "who": q["account_name"],
                       "when": q["valid_until"] or q["quote_date"],
                       "href": f"/quote/{q['quote_no']}"})
    job_ends = []
    for t in con.execute(
        """SELECT t.ticket_id, t.off_rent, a.unit_no, c.account_name
           FROM tickets t JOIN assets a ON a.asset_id = t.asset_id
           JOIN customers c ON c.customer_id = t.customer_id
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
           FROM work_orders w JOIN assets a ON a.asset_id = w.asset_id
           LEFT JOIN customers cu ON cu.customer_id = w.customer_id
           WHERE w.status IN ('Open','In progress')
           ORDER BY w.open_date"""):
        shop.append({"what": f"WO {w['wo_id']} — {w['unit_no']} {w['work_type'] or ''}".strip(),
                     "who": w["vendor"] or w["account_name"] or "Yard",
                     "when": w["open_date"], "href": f"/wo/{w['wo_id']}"})
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
           FROM tickets t JOIN assets a ON a.asset_id = t.asset_id
           JOIN customers c ON c.customer_id = t.customer_id
           WHERE t.status = 'Reserved' AND t.on_rent < ?
           ORDER BY t.on_rent""", (s,)):
        why = "should have shipped by now" if t["on_rent"] < month_ago else "ship date passed"
        reservations.append({"what": f"{t['ticket_id']} — {t['unit_no']}",
                             "who": t["account_name"], "when": t["on_rent"],
                             "why": why, "href": f"/ticket/{t['ticket_id']}"})
    quotes = []
    for q in con.execute(
        """SELECT q.quote_no, q.quote_date, q.valid_until, q.job_name, c.account_name
           FROM quotes q JOIN customers c ON c.customer_id = q.customer_id
           WHERE q.status IN ('Draft','Sent')
             AND (q.quote_date < ? OR (q.valid_until IS NOT NULL AND q.valid_until != '' AND q.valid_until < ?))
           ORDER BY q.quote_date""", (two_months, s)):
        why = ("sitting 60+ days" if str(q["quote_date"] or "") < two_months
               else "validity expired")
        quotes.append({"what": f"Quote {q['quote_no']} {q['job_name'] or ''}".strip(),
                       "who": q["account_name"],
                       "when": q["valid_until"] or q["quote_date"], "why": why,
                       "href": f"/quote/{q['quote_no']}"})
    job_ends = []
    for t in con.execute(
        """SELECT t.ticket_id, t.off_rent, t.on_rent, a.unit_no, c.account_name
           FROM tickets t JOIN assets a ON a.asset_id = t.asset_id
           JOIN customers c ON c.customer_id = t.customer_id
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
           FROM work_orders w JOIN assets a ON a.asset_id = w.asset_id
           WHERE w.status IN ('Open','In progress') AND w.open_date < ?
           ORDER BY w.open_date""", (month_ago,)):
        shop.append({"what": f"WO {w['wo_id']} — {w['unit_no']} {w['work_type'] or ''}".strip(),
                     "who": "Shop", "when": w["open_date"],
                     "why": "open over a month", "href": f"/wo/{w['wo_id']}"})
    end = (today + timedelta(days=30)).isoformat()
    return {"span": "month", "start": s, "end": end,
            "sections": [("reservations", reservations), ("quotes", quotes),
                         ("job_ends", job_ends), ("shop", shop)]}


# -------------------------------------------------------- Custom builds

CUSTOM_SORTABLE = ("", "asc", "desc")


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
        raise ValueError("'Everything' is a one-click preset — use the New export form above.")
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
        raise ValueError("Name the build so it can be found later.")
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
