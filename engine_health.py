"""FleetSheet database health / business-integrity checks.

This module is intentionally read-only.  It reports inconsistent states without
repairing them, so an operator can review the findings before any corrective data
change is made.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import date
from pathlib import Path

from engine_core import doc_dir, photo_dir

SEVERITIES = ("critical", "warning", "info")
_NUM = re.compile(r"(\d+)$")


def _issue(severity, code, message, count=1, examples=None):
    return {
        "severity": severity,
        "code": code,
        "message": message,
        "count": int(count),
        "examples": list(examples or [])[:8],
    }


def _rows(con, sql, args=()):
    return con.execute(sql, args).fetchall()


def _valid_date(v):
    try:
        date.fromisoformat(str(v)[:10])
        return True
    except (TypeError, ValueError):
        return False


def _counter_issue(con, table, column, company_column, label, prefix):
    row = con.execute(f"SELECT {company_column} FROM company WHERE id=1").fetchone()
    if not row:
        return None
    nxt = int(row[0] or 0)
    nums = []
    for r in con.execute(f"SELECT {column} FROM {table}"):
        m = _NUM.search(str(r[0] or ""))
        if m:
            nums.append(int(m.group(1)))
    if nums and nxt <= max(nums):
        return _issue("warning", "SEQUENCE_BEHIND", f"{label} next-number counter is {nxt}, but an existing {label.lower()} reaches {max(nums)}.", examples=[f"next={nxt}", f"max={max(nums)}"])
    return None


def data_health(con: sqlite3.Connection) -> dict:
    """Return a structured, read-only health report for the current book."""
    issues = []
    checks = 0

    # SQLite-level integrity.
    checks += 1
    try:
        r = con.execute("PRAGMA integrity_check").fetchone()
        if not r or r[0] != "ok":
            issues.append(_issue("critical", "SQLITE_INTEGRITY", "SQLite integrity_check did not return ok.", examples=[str(r[0] if r else "no result")]))
    except sqlite3.DatabaseError as e:
        issues.append(_issue("critical", "SQLITE_INTEGRITY", f"SQLite integrity check failed: {e}"))

    checks += 1
    fk = _rows(con, "PRAGMA foreign_key_check")
    if fk:
        issues.append(_issue("critical", "FOREIGN_KEYS", "Foreign-key violations exist in the book.", len(fk), [str(tuple(r)) for r in fk]))

    # Live asset conflicts — the same physical unit cannot be on two blocking tickets.
    checks += 1
    rows = _rows(con, """SELECT asset_id, COUNT(*) n, GROUP_CONCAT(ticket_id, ', ') ids
                          FROM tickets
                          WHERE status IN ('Reserved','Dispatched','On Rent','Standby')
                          GROUP BY asset_id HAVING COUNT(*) > 1""")
    if rows:
        issues.append(_issue("critical", "LIVE_ASSET_CONFLICT", "A unit has more than one blocking live ticket.", len(rows), [f"{r['asset_id']}: {r['ids']}" for r in rows]))

    # Ticket state/invoice coherence.
    checks += 1
    rows = _rows(con, """SELECT ticket_id FROM tickets
                          WHERE status='Billed' AND (invoice_no IS NULL OR invoice_no='')""")
    if rows:
        issues.append(_issue("critical", "BILLED_WITHOUT_INVOICE", "Billed tickets have no invoice number.", len(rows), [r['ticket_id'] for r in rows]))

    checks += 1
    rows = _rows(con, """SELECT ticket_id FROM tickets
                          WHERE status='Closed' AND (invoice_no IS NULL OR invoice_no='')""")
    if rows:
        issues.append(_issue("critical", "CLOSED_WITHOUT_INVOICE", "Closed tickets have no invoice number.", len(rows), [r['ticket_id'] for r in rows]))

    checks += 1
    rows = _rows(con, """SELECT t.ticket_id FROM tickets t
                          LEFT JOIN invoices i ON i.invoice_no=t.invoice_no
                          WHERE t.invoice_no IS NOT NULL AND t.invoice_no!='' AND i.invoice_no IS NULL""")
    if rows:
        issues.append(_issue("critical", "TICKET_INVOICE_MISSING", "Tickets reference invoices that do not exist.", len(rows), [r['ticket_id'] for r in rows]))

    checks += 1
    rows = _rows(con, """SELECT t.ticket_id FROM tickets t
                          WHERE t.status IN ('Off Rent','Ready to Bill','Billed','Closed')
                            AND (t.off_rent IS NULL OR t.off_rent='')""")
    if rows:
        issues.append(_issue("warning", "MISSING_OFF_RENT", "Completed/ready/billed tickets have no off-rent date.", len(rows), [r['ticket_id'] for r in rows]))

    checks += 1
    rows = []
    for r in con.execute("SELECT ticket_id,on_rent,off_rent FROM tickets WHERE on_rent IS NOT NULL AND off_rent IS NOT NULL"):
        if not _valid_date(r['on_rent']) or not _valid_date(r['off_rent']) or str(r['off_rent'])[:10] < str(r['on_rent'])[:10]:
            rows.append(r)
    if rows:
        issues.append(_issue("warning", "BAD_RENTAL_DATES", "Tickets contain invalid or backwards rental dates.", len(rows), [r['ticket_id'] for r in rows]))

    # Invoice line/source coherence.
    checks += 1
    rows = _rows(con, """SELECT il.line_id FROM invoice_lines il
                          LEFT JOIN invoices i ON i.invoice_no=il.invoice_no
                          WHERE i.invoice_no IS NULL""")
    if rows:
        issues.append(_issue("critical", "ORPHAN_INVOICE_LINES", "Invoice lines exist without a parent invoice.", len(rows), [str(r['line_id']) for r in rows]))

    checks += 1
    rows = _rows(con, """SELECT il.line_id FROM invoice_lines il
                          JOIN tickets t ON il.source_type='ticket' AND il.source_id=t.ticket_id
                          JOIN invoices i ON i.invoice_no=il.invoice_no
                          WHERE t.invoice_no IS NULL OR t.invoice_no != il.invoice_no OR t.customer_id != i.customer_id""")
    if rows:
        issues.append(_issue("critical", "INVOICE_TICKET_MISMATCH", "Ticket-sourced invoice lines do not agree with the ticket's invoice/customer.", len(rows), [str(r['line_id']) for r in rows]))

    checks += 1
    rows = _rows(con, """SELECT il.line_id FROM invoice_lines il
                          LEFT JOIN work_orders w ON il.source_type='work_order' AND il.source_id=w.wo_id
                          WHERE il.source_type='work_order' AND (w.wo_id IS NULL OR w.invoice_no != il.invoice_no)""")
    if rows:
        issues.append(_issue("critical", "INVOICE_WO_MISMATCH", "Work-order invoice lines do not agree with their work order invoice.", len(rows), [str(r['line_id']) for r in rows]))

    # Work order invoice coherence.
    checks += 1
    rows = _rows(con, """SELECT w.wo_id FROM work_orders w
                          LEFT JOIN invoices i ON i.invoice_no=w.invoice_no
                          WHERE w.invoice_no IS NOT NULL AND w.invoice_no!='' AND i.invoice_no IS NULL""")
    if rows:
        issues.append(_issue("critical", "WO_INVOICE_MISSING", "Work orders reference invoices that do not exist.", len(rows), [r['wo_id'] for r in rows]))

    # Ticket customer vs site owner (site customer may be blank, which is valid).
    checks += 1
    rows = _rows(con, """SELECT t.ticket_id FROM tickets t JOIN sites s ON s.site_id=t.site_id
                          WHERE s.customer_id IS NOT NULL AND s.customer_id != t.customer_id""")
    if rows:
        issues.append(_issue("warning", "SITE_CUSTOMER_MISMATCH", "Tickets use a site assigned to a different customer.", len(rows), [r['ticket_id'] for r in rows]))

    # Tax jurisdiction completeness.  Older pre-migration books may not yet
    # have tax_loc_id; the application migration adds it before normal use.
    ticket_cols = {r[1] for r in con.execute("PRAGMA table_info(tickets)")}
    if "tax_loc_id" in ticket_cols:
        checks += 1
        rows = _rows(con, """SELECT ticket_id FROM tickets
                              WHERE haul_by IN ('we','third_party')
                                AND deliver_to IN ('customer_yard','dock')
                                AND (tax_loc_id IS NULL OR tax_loc_id='')""")
        if rows:
            issues.append(_issue("critical", "TAX_JURISDICTION_MISSING", "Customer-yard/dock delivery tickets lack an explicit tax jurisdiction.", len(rows), [r['ticket_id'] for r in rows]))

        checks += 1
        rows = _rows(con, """SELECT t.ticket_id FROM tickets t
                              LEFT JOIN jurisdictions j ON j.loc_id=t.tax_loc_id
                              WHERE t.tax_loc_id IS NOT NULL AND t.tax_loc_id!='' AND j.loc_id IS NULL""")
        if rows:
            issues.append(_issue("critical", "TAX_JURISDICTION_UNKNOWN", "Tickets reference a tax jurisdiction that does not exist.", len(rows), [r['ticket_id'] for r in rows]))

    # Duplicate operational unit numbers are confusing even if asset IDs differ.
    checks += 1
    rows = _rows(con, """SELECT unit_no, COUNT(*) n FROM assets
                          WHERE active=1 AND unit_no IS NOT NULL AND unit_no!=''
                          GROUP BY unit_no HAVING COUNT(*) > 1""")
    if rows:
        issues.append(_issue("warning", "DUPLICATE_UNIT_NO", "Active assets share the same displayed unit number.", len(rows), [f"{r['unit_no']} ({r['n']})" for r in rows]))

    # Negative charge components generally indicate data corruption; credits should use credit memos.
    checks += 1
    rows = _rows(con, """SELECT ticket_id FROM tickets
                          WHERE transport_fee < 0 OR mob < 0 OR demob < 0 OR fuel < 0 OR parts < 0 OR other_amt < 0""")
    if rows:
        issues.append(_issue("warning", "NEGATIVE_TICKET_CHARGE", "Tickets contain negative charge components.", len(rows), [r['ticket_id'] for r in rows]))

    # Sequence counters.
    for args in (
        ("tickets", "ticket_id", "next_ticket", "ticket", "T-"),
        ("invoices", "invoice_no", "next_invoice", "invoice", ""),
        ("collections", "payment_id", "next_payment", "payment", "P-"),
    ):
        checks += 1
        try:
            issue = _counter_issue(con, *args)
            if issue:
                issues.append(issue)
        except sqlite3.OperationalError:
            # Older books can legitimately lack a table during migration.
            pass

    # Attached media: records pointing to absent files are actionable.
    checks += 1
    photo_rows = _rows(con, "SELECT ticket_id, out_photo, in_photo FROM tickets WHERE (out_photo IS NOT NULL AND out_photo!='') OR (in_photo IS NOT NULL AND in_photo!='')")
    missing_photos = []
    pdir = photo_dir()
    for r in photo_rows:
        for col in ("out_photo", "in_photo"):
            name = r[col]
            if name and not (pdir / str(name)).is_file():
                missing_photos.append(f"{r['ticket_id']}:{col}:{name}")
    if missing_photos:
        issues.append(_issue("warning", "MISSING_PHOTO_FILE", "Ticket records reference photo files that are missing from the photo directory.", len(missing_photos), missing_photos))

    # Attached unit documents.
    checks += 1
    try:
        doc_rows = _rows(con, "SELECT doc_id, rel_path FROM unit_docs WHERE rel_path IS NOT NULL AND rel_path!=''")
        missing_docs = [f"{r['doc_id']}:{r['rel_path']}" for r in doc_rows if not (doc_dir() / str(r['rel_path'])).is_file()]
        if missing_docs:
            issues.append(_issue("warning", "MISSING_DOCUMENT_FILE", "Unit-document records reference missing files.", len(missing_docs), missing_docs))
    except sqlite3.OperationalError:
        pass

    critical = sum(i['count'] for i in issues if i['severity'] == 'critical')
    warning = sum(i['count'] for i in issues if i['severity'] == 'warning')
    return {
        "ok": critical == 0,
        "checks": checks,
        "critical": critical,
        "warning": warning,
        "issues": issues,
    }


__all__ = ["SEVERITIES", "data_health"]
