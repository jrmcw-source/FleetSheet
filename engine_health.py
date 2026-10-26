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

from engine_core import doc_dir, module_on, photo_dir

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


def _table_exists(con, name):
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,)).fetchone() is not None


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
    if table == "collections":
        # Pay ids also live in doc_collections (WO / ticket / sale money).
        try:
            for r in con.execute("SELECT pay_id FROM doc_collections"):
                m = _NUM.search(str(r[0] or ""))
                if m:
                    nums.append(int(m.group(1)))
        except Exception:
            pass
    if nums and nxt <= max(nums):
        return _issue("warning", "SEQUENCE_BEHIND", f"{label} next-number counter is {nxt}, but an existing {label.lower()} reaches {max(nums)}.", examples=[f"next={nxt}", f"max={max(nums)}"])
    return None


def data_health(con: sqlite3.Connection) -> dict:
    """Return a structured, read-only health report for the current book."""
    issues = []
    checks = 0

    # Billing module state (shop-flow doctrine — build-playbook
    # functions.md, "Billing OFF hides money kinds" / the module-switch
    # doctrine): with the Billing switch OFF, a returned rental ticket
    # closing with no invoice is BY DESIGN — a shop that does not bill
    # (the charity case) closes every delivery as its normal work, not
    # as an exception. The two invoice-presence checks below therefore
    # run only when billing is ON, and are not counted when suppressed
    # (the tax checks below set the precedent: a not-applicable check
    # is not a performed check). An unreadable switch defaults to ON,
    # which is the pre-doctrine behavior.
    try:
        billing_on = module_on(con, "billing")
    except Exception:
        billing_on = True

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
    rows = _rows(con, """SELECT a.asset_id, COUNT(*) n, GROUP_CONCAT(t.ticket_id, ', ') ids
                          FROM tickets t JOIN assets a ON a.id = t.asset_id
                          WHERE t.status IN ('Reserved','Dispatched','On Rent','Standby')
                          GROUP BY t.asset_id HAVING COUNT(*) > 1""")
    if rows:
        issues.append(_issue("critical", "LIVE_ASSET_CONFLICT", "A unit has more than one blocking live Rental Ticket.", len(rows), [f"{r['asset_id']}: {r['ids']}" for r in rows]))

    # Ticket state/invoice coherence. The two invoice-presence checks
    # are billing-doctrine-aware (see the billing_on note above): they
    # fire only when the Billing module is ON.
    if billing_on:
        checks += 1
        rows = _rows(con, """SELECT ticket_id FROM tickets
                              WHERE status='Billed' AND invoice_id IS NULL""")
        if rows:
            issues.append(_issue("critical", "BILLED_WITHOUT_INVOICE", "Billed Rental Tickets have no invoice number.", len(rows), [r['ticket_id'] for r in rows]))

        checks += 1
        rows = _rows(con, """SELECT ticket_id FROM tickets
                              WHERE status='Closed' AND invoice_id IS NULL""")
        if rows:
            issues.append(_issue("critical", "CLOSED_WITHOUT_INVOICE", "Closed Rental Tickets have no invoice number.", len(rows), [r['ticket_id'] for r in rows]))

    checks += 1
    rows = _rows(con, """SELECT t.ticket_id FROM tickets t
                          LEFT JOIN invoices i ON i.id=t.invoice_id
                          WHERE t.invoice_id IS NOT NULL AND i.id IS NULL""")
    if rows:
        issues.append(_issue("critical", "TICKET_INVOICE_MISSING", "Rental Tickets reference invoices that do not exist.", len(rows), [r['ticket_id'] for r in rows]))

    checks += 1
    rows = _rows(con, """SELECT t.ticket_id FROM tickets t
                          WHERE t.status IN ('Off Rent','Ready to Bill','Billed','Closed')
                            AND (t.off_rent IS NULL OR t.off_rent='')""")
    if rows:
        issues.append(_issue("warning", "MISSING_OFF_RENT", "Completed/ready/billed Rental Tickets have no off-rent date.", len(rows), [r['ticket_id'] for r in rows]))

    checks += 1
    rows = []
    for r in con.execute("SELECT ticket_id,on_rent,off_rent FROM tickets WHERE on_rent IS NOT NULL AND off_rent IS NOT NULL"):
        if not _valid_date(r['on_rent']) or not _valid_date(r['off_rent']) or str(r['off_rent'])[:10] < str(r['on_rent'])[:10]:
            rows.append(r)
    if rows:
        issues.append(_issue("warning", "BAD_RENTAL_DATES", "Rental Tickets contain invalid or backwards rental dates.", len(rows), [r['ticket_id'] for r in rows]))

    # Invoice line/source coherence.
    checks += 1
    rows = _rows(con, """SELECT il.line_id FROM invoice_lines il
                          LEFT JOIN invoices i ON i.id=il.invoice_id
                          WHERE i.id IS NULL""")
    if rows:
        issues.append(_issue("critical", "ORPHAN_INVOICE_LINES", "Invoice lines exist without a parent invoice.", len(rows), [str(r['line_id']) for r in rows]))

    checks += 1
    rows = _rows(con, """SELECT il.line_id FROM invoice_lines il
                          JOIN tickets t ON il.source_type='ticket' AND il.source_id=t.ticket_id
                          JOIN invoices i ON i.id=il.invoice_id
                          WHERE t.invoice_id IS NULL OR t.invoice_id != il.invoice_id OR t.customer_id != i.customer_id""")
    if rows:
        issues.append(_issue("critical", "INVOICE_TICKET_MISMATCH", "Rental-Ticket-sourced invoice lines do not agree with the Rental Ticket's invoice/customer.", len(rows), [str(r['line_id']) for r in rows]))

    checks += 1
    rows = _rows(con, """SELECT il.line_id FROM invoice_lines il
                          LEFT JOIN work_orders w ON il.source_type='work_order' AND il.source_id=w.wo_id
                          WHERE il.source_type='work_order' AND (w.wo_id IS NULL OR w.invoice_id != il.invoice_id)""")
    if rows:
        issues.append(_issue("critical", "INVOICE_WO_MISMATCH", "Work-order invoice lines do not agree with their work order invoice.", len(rows), [str(r['line_id']) for r in rows]))

    # Work order invoice coherence.
    checks += 1
    rows = _rows(con, """SELECT w.wo_id FROM work_orders w
                          LEFT JOIN invoices i ON i.id=w.invoice_id
                          WHERE w.invoice_id IS NOT NULL AND i.id IS NULL""")
    if rows:
        issues.append(_issue("critical", "WO_INVOICE_MISSING", "Work orders reference invoices that do not exist.", len(rows), [r['wo_id'] for r in rows]))

    # Ticket customer vs site owner (site customer may be blank, which is valid).
    checks += 1
    rows = _rows(con, """SELECT t.ticket_id FROM tickets t JOIN sites s ON s.id=t.site_id
                          WHERE s.customer_id IS NOT NULL AND s.customer_id != t.customer_id""")
    if rows:
        issues.append(_issue("warning", "SITE_CUSTOMER_MISMATCH", "Rental Tickets use a site assigned to a different customer.", len(rows), [r['ticket_id'] for r in rows]))

    # Tax jurisdiction completeness.  Older pre-migration books may not yet
    # have tax_loc_id; the application migration adds it before normal use.
    ticket_cols = {r[1] for r in con.execute("PRAGMA table_info(tickets)")}
    if "tax_loc_id" in ticket_cols:
        checks += 1
        rows = _rows(con, """SELECT ticket_id FROM tickets
                              WHERE haul_by IN ('we','third_party')
                                AND deliver_to IN ('customer_yard','dock')
                                AND tax_loc_id IS NULL""")
        if rows:
            issues.append(_issue("critical", "TAX_JURISDICTION_MISSING", "Customer-yard/dock delivery tickets lack an explicit tax jurisdiction.", len(rows), [r['ticket_id'] for r in rows]))

        checks += 1
        rows = _rows(con, """SELECT t.ticket_id FROM tickets t
                              LEFT JOIN jurisdictions j ON j.id=t.tax_loc_id
                              WHERE t.tax_loc_id IS NOT NULL AND j.id IS NULL""")
        if rows:
            issues.append(_issue("critical", "TAX_JURISDICTION_UNKNOWN", "Rental Tickets reference a tax jurisdiction that does not exist.", len(rows), [r['ticket_id'] for r in rows]))

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
        issues.append(_issue("warning", "NEGATIVE_TICKET_CHARGE", "Rental Tickets contain negative charge components.", len(rows), [r['ticket_id'] for r in rows]))

    # Sequence counters. Build 'v' landmine (e): the collections leg
    # named a "payment_id" column that does not exist — the audit
    # threw OperationalError into the swallow below and NEVER ran.
    # The column is pay_id; the audit runs now.
    for args in (
        ("tickets", "ticket_id", "next_ticket", "ticket", "T-"),
        ("invoices", "invoice_no", "next_invoice", "invoice", ""),
        ("collections", "pay_id", "next_payment", "payment", "P-"),
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
        issues.append(_issue("warning", "MISSING_PHOTO_FILE", "Rental Ticket records reference photo files that are missing from the photo directory.", len(missing_photos), missing_photos))

    # Attached unit documents. The column is unit_docs.stored (the
    # pre-rename name rel_path exists in no current schema; querying
    # it raised OperationalError and this check silently no-oped on
    # every current book — revived 2026-10-24, Phase 3/4).
    checks += 1
    try:
        doc_rows = _rows(con, "SELECT doc_id, stored FROM unit_docs WHERE stored IS NOT NULL AND stored!=''")
        missing_docs = [f"{r['doc_id']}:{r['stored']}" for r in doc_rows if not (doc_dir() / str(r['stored'])).is_file()]
        if missing_docs:
            issues.append(_issue("warning", "MISSING_DOCUMENT_FILE", "Unit-document records reference missing files.", len(missing_docs), missing_docs))
    except sqlite3.OperationalError:
        pass

    # Attached invoice paperwork (PO scans, tax-exempt certificates):
    # the invoice-side mirror of MISSING_DOCUMENT_FILE. The stored
    # filename lives in doc_dir(), like unit documents.
    checks += 1
    try:
        inv_doc_rows = _rows(con, "SELECT d.doc_id, i.invoice_no, d.stored FROM invoice_docs d LEFT JOIN invoices i ON i.id = d.invoice_id WHERE d.stored IS NOT NULL AND d.stored!=''")
        ddir = doc_dir()
        missing_inv_docs = [f"{r['doc_id']}:{r['invoice_no']}:{r['stored']}" for r in inv_doc_rows if not (ddir / str(r['stored'])).is_file()]
        if missing_inv_docs:
            issues.append(_issue("warning", "MISSING_INVOICE_DOCUMENT_FILE", "Invoice-document records (PO scans and paperwork) reference missing files.", len(missing_inv_docs), missing_inv_docs))
    except sqlite3.OperationalError:
        pass

    # --- Payment-allocation coherence ----------------------------------
    # Allocations are OPTIONAL by doctrine (functions.md: payments are
    # CAPABLE of line-by-line allocation; blanket cover is legitimate
    # and writes no rows, or only a blanket remainder row with
    # line_id NULL). Absence is never flagged; rows that exist must
    # cohere. doc_kind values below are the ones engine_accounting's
    # writers actually write — verified in _doc_line_rows /
    # record_payment / record_doc_payment / record_cash_entry:
    # 'invoice', 'wo', 'ticket', 'sale', 'quote'. Any other kind is
    # not asserted against and never flagged here.
    # Build 'v': allocations carry the document's ENGINE KEY
    # (doc_id), and the payment link is the shared ledger key.
    # _ALLOC_DOC maps a kind to (parent table, number column) for
    # existence + display; _ALLOC_LINE maps a kind to its line
    # table + the parent-key column a line carries.
    _ALLOC_DOC = {
        "invoice": ("invoices", "invoice_no"),
        "wo": ("work_orders", "wo_id"),
        "ticket": ("tickets", "ticket_id"),
        "sale": ("sales", "sale_id"),
        "quote": ("quotes", "quote_no"),
        "change": ("change_orders", "co_no"),
    }
    _ALLOC_LINE = {
        "invoice": ("invoice_lines", "invoice_id"),
        "wo": ("wo_lines", "wo_id"),
        "ticket": ("ticket_lines", "ticket_id"),
        "quote": ("quote_lines", "quote_id"),
        "change": ("change_order_lines", "co_id"),
    }
    try:
        con.execute("SELECT 1 FROM doc_collections LIMIT 1")
        _has_doc_ledger = True
    except sqlite3.OperationalError:
        _has_doc_ledger = False

    # Allocations pointing at a document that does not exist.
    checks += 1
    try:
        bad = []
        seen_doc = {}
        for r in _rows(con, "SELECT alloc_id, doc_kind, doc_id FROM payment_allocations WHERE doc_id IS NOT NULL"):
            kind = r['doc_kind']
            if kind not in _ALLOC_DOC:
                continue
            key = (kind, r['doc_id'])
            if key not in seen_doc:
                tbl, numcol = _ALLOC_DOC[kind]
                nrow = con.execute(
                    f"SELECT {numcol} FROM {tbl} WHERE id=? LIMIT 1",
                    (r['doc_id'],)).fetchone()
                seen_doc[key] = nrow[0] if nrow else None
            if not seen_doc[key]:
                bad.append(f"{r['alloc_id']}:{kind}:{r['doc_id']}")
        if bad:
            issues.append(_issue("critical", "ALLOC_DOC_MISSING", "Payment allocations reference documents that do not exist.", len(bad), bad))
    except sqlite3.OperationalError:
        pass

    # Allocations pointing at a line that is not a line of their document.
    checks += 1
    try:
        bad = []
        for r in _rows(con, "SELECT alloc_id, doc_kind, doc_id, line_id FROM payment_allocations WHERE line_id IS NOT NULL"):
            kind = r['doc_kind']
            lid = r['line_id']
            if kind == "sale":
                try:
                    lr = con.execute("SELECT group_id FROM sales WHERE id=?", (lid,)).fetchone()
                except sqlite3.OperationalError:
                    continue
                ok = lr is not None and lr[0] == r['doc_id']
            elif kind in _ALLOC_LINE:
                tbl, col = _ALLOC_LINE[kind]
                try:
                    lr = con.execute(f"SELECT {col} FROM {tbl} WHERE line_id=?", (lid,)).fetchone()
                except sqlite3.OperationalError:
                    continue
                ok = lr is not None and lr[0] == r['doc_id']
            else:
                continue
            if not ok:
                bad.append(f"{r['alloc_id']}:{kind}:{r['doc_id']}:line {lid}")
        if bad:
            issues.append(_issue("critical", "ALLOC_LINE_MISSING", "Payment allocations reference lines that are not lines of their document.", len(bad), bad))
    except sqlite3.OperationalError:
        pass

    # Payment-sourced allocations whose payment is in neither ledger.
    checks += 1
    try:
        if _has_doc_ledger:
            rows = _rows(con, """SELECT pa.alloc_id, pa.pay_id,
                                    COALESCE(c.pay_id, d.pay_id) AS pay_no
                                  FROM payment_allocations pa
                                  LEFT JOIN collections c ON c.id = pa.pay_id
                                  LEFT JOIN doc_collections d ON d.id = pa.pay_id
                                  WHERE pa.source='payment' AND pa.pay_id IS NOT NULL
                                    AND c.id IS NULL AND d.id IS NULL""")
        else:
            rows = _rows(con, """SELECT pa.alloc_id, pa.pay_id, c.pay_id AS pay_no
                                  FROM payment_allocations pa
                                  LEFT JOIN collections c ON c.id = pa.pay_id
                                  WHERE pa.source='payment' AND pa.pay_id IS NOT NULL
                                    AND c.id IS NULL""")
        if rows:
            issues.append(_issue("critical", "ALLOC_PAYMENT_MISSING", "Payment allocations reference payments that exist in neither payment ledger.", len(rows), [f"{r['alloc_id']}:{r['pay_no'] or r['pay_id']}" for r in rows]))
    except sqlite3.OperationalError:
        pass

    # Per-payment over-allocation. Semantics verified in
    # record_payment / record_doc_payment: each collections /
    # doc_collections row is ONE payment leg whose amount (and
    # applied_amount, set equal at posting) is the amount applied to
    # its document — a split batch is one row per leg under its own
    # pay_id. _write_line_allocs guarantees a leg's allocation rows
    # (line rows plus the blanket remainder) sum back to that applied
    # amount. Carried mirrors reuse the source row's engine key on the
    # invoice side, so the comparison groups by (pay key, doc_kind,
    # doc_id): a doc leg reads doc_collections, its invoice mirror
    # reads the carried collections row, and neither inflates the
    # other.
    checks += 1
    try:
        bad = []
        groups = _rows(con, """SELECT pay_id, doc_kind, doc_id, SUM(amount) AS s
                                FROM payment_allocations
                                WHERE source='payment' AND pay_id IS NOT NULL
                                GROUP BY pay_id, doc_kind, doc_id""")
        for g in groups:
            if g['doc_kind'] == "invoice":
                led = con.execute("SELECT pay_id, amount, applied_amount FROM collections WHERE id=?", (g['pay_id'],)).fetchone()
            elif _has_doc_ledger:
                led = con.execute("SELECT pay_id, amount, applied_amount FROM doc_collections WHERE id=?", (g['pay_id'],)).fetchone()
            else:
                continue
            if led is None:
                continue  # ALLOC_PAYMENT_MISSING owns this payment.
            expected = led['applied_amount'] if led['applied_amount'] is not None else led['amount']
            if abs(float(g['s'] or 0)) - abs(float(expected or 0)) > 0.01:
                _tbl, _numcol = _ALLOC_DOC.get(g['doc_kind'], (None, None))
                _dno = None
                if _tbl:
                    _dr = con.execute(f"SELECT {_numcol} FROM {_tbl} WHERE id=?", (g['doc_id'],)).fetchone()
                    _dno = _dr[0] if _dr else None
                bad.append(f"{led['pay_id']}:{g['doc_kind']}:{_dno or g['doc_id']} allocated {abs(float(g['s'] or 0)):.2f} vs paid {abs(float(expected or 0)):.2f}")
        if bad:
            issues.append(_issue("warning", "ALLOC_OVER_ALLOCATED", "Payment allocations exceed the amount their payment applied.", len(bad), bad))
    except sqlite3.OperationalError:
        pass

    # --- Credit-memo-line coherence ------------------------------------
    # issue_credit_memo's contract: when a memo has lines, its
    # face_amount is the sum of the line amounts. Legacy memos may
    # carry NO lines (memo-level category only) — those are not
    # incoherent and are never flagged by the totals check.
    checks += 1
    try:
        rows = _rows(con, """SELECT cml.line_id, cml.cm_id FROM credit_memo_lines cml
                              LEFT JOIN credit_memos cm ON cm.id=cml.cm_id
                              WHERE cm.id IS NULL""")
        if rows:
            issues.append(_issue("critical", "ORPHAN_CREDIT_MEMO_LINES", "Credit memo lines exist without a parent credit memo.", len(rows), [f"{r['line_id']}:{r['cm_id']}" for r in rows]))
    except sqlite3.OperationalError:
        pass

    checks += 1
    try:
        rows = _rows(con, """SELECT cm.cm_no, cm.face_amount, SUM(cml.amount) AS s
                              FROM credit_memos cm
                              JOIN credit_memo_lines cml ON cml.cm_id=cm.id
                              GROUP BY cm.cm_no, cm.face_amount""")
        bad = [f"{r['cm_no']}: lines {float(r['s'] or 0):.2f} vs face {float(r['face_amount'] or 0):.2f}"
               for r in rows if abs(float(r['s'] or 0) - float(r['face_amount'] or 0)) > 0.01]
        if bad:
            issues.append(_issue("warning", "CREDIT_MEMO_LINE_TOTAL", "Credit memo line amounts do not add up to the memo face amount.", len(bad), bad))
    except sqlite3.OperationalError:
        pass

    # --- Mixed-report preset validity ----------------------------------
    # save_mixed_preset sanitizes on write, so an invalid row can only
    # arrive via an older book or a direct edit — which is what a
    # health check exists to catch. The kinds vocabulary is
    # engine_reports.MIXED_KINDS; it is imported lazily because
    # engine_reports -> exportpack -> engine (facade) -> this module
    # would cycle at import time. The fallback mirrors the current
    # MIXED_KINDS if that import ever fails.
    try:
        from engine_reports import MIXED_KIND_LABELS, MIXED_KINDS
        _kind_labels = MIXED_KIND_LABELS
        _money_kinds = {k for k, _lab, _money in MIXED_KINDS if _money}
    except Exception:
        _kind_labels = {"rentals": "Rentals", "sales": "Sales",
                        "work_orders": "Work orders", "invoices": "Invoices",
                        "payments": "Payments", "credits": "Credits"}
        _money_kinds = {"invoices", "payments", "credits"}
    try:
        presets = _rows(con, "SELECT preset_id, name, kinds, time_mode, customer_id FROM mixed_presets")
    except sqlite3.OperationalError:
        presets = None
    if presets is not None:
        checks += 4
        bad_kind, bad_cust, bad_mode, money_off = [], [], [], []
        seen_cust = {}
        for p in presets:
            tokens = [t.strip() for t in str(p['kinds'] or "").split(",") if t.strip()]
            unknown = [t for t in tokens if t not in _kind_labels]
            if unknown:
                bad_kind.append(f"{p['name']}: {', '.join(unknown)}")
            cid = p['customer_id']
            if cid:
                if cid not in seen_cust:
                    try:
                        seen_cust[cid] = con.execute(
                            "SELECT 1 FROM customers WHERE id=? LIMIT 1",
                            (cid,)).fetchone() is not None
                    except sqlite3.OperationalError:
                        seen_cust[cid] = True
                if not seen_cust[cid]:
                    bad_cust.append(f"{p['name']}: {cid}")
            if str(p['time_mode'] or "") not in ("once", "monthly"):
                bad_mode.append(f"{p['name']}: {p['time_mode']}")
            if not billing_on:
                money = [t for t in tokens if t in _money_kinds]
                if money:
                    money_off.append(f"{p['name']}: {', '.join(money)}")
        if bad_kind:
            issues.append(_issue("warning", "MIXED_PRESET_KIND_UNKNOWN", "Mixed-report presets name report kinds that do not exist.", len(bad_kind), bad_kind))
        if bad_cust:
            issues.append(_issue("warning", "MIXED_PRESET_CUSTOMER_MISSING", "Mixed-report presets name customers that do not exist.", len(bad_cust), bad_cust))
        if bad_mode:
            issues.append(_issue("warning", "MIXED_PRESET_TIME_MODE", "Mixed-report presets carry a time mode outside 'once'/'monthly'.", len(bad_mode), bad_mode))
        if money_off:
            issues.append(_issue("info", "MIXED_PRESET_MONEY_BILLING_OFF", "Mixed-report presets include money kinds while the Billing module is off; those kinds render empty by design.", len(money_off), money_off))

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
