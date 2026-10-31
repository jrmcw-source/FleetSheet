"""FleetSheet engine — void-and-revise (build 'av', Jason's ruling
2026-10-30, replacing the build 'ab' confirm-time model): editing a
posted/issued document never updates it in place, and Edit no
longer voids anything. The Edit act creates a PENDING revision —
an editable clone (rev_pending=1) carrying the original's full
content, its number prefilled "<original> Rev. N" — while the
original stays live as the chain head, unvoided, and keeps
answering every money and list read; the pending clone is
invisible to those reads. The revision's own form opens unlocked
under a session marker (options table, no schema of its own); the
POST layer refuses any in-place save of an existing document that
carries no marker. Save — or Print, which commits first — is the
single commit act (finalize_revision): only then does the
original void, signed automatically with the desk user and the
server timestamp (no typed name, no required reason; an OPTIONAL
internal revision note replaces the old reason and rides the
void record when the operator offers one), and the revision
becomes the chain head with rev_pending cleared. The chain links
by engine key (revises_id / revised_by_id on every document
table); numbers are never keys. Voided ancestors are read-only
paper. Money recorded against any link of the chain resolves to
the head (the accounting engine's settled/total reads walk the
chain through here). A pending revision that is never finished
never disturbs the record: the original stands, the clone waits.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime

from engine_core import (
    get_option,
    set_option,
    key_of,
    stamp_company_snapshot,
    company_snapshot_json,
    num_of,
    doc_key,
)

# kind -> (table, number column). Payments ride the same model on
# their ledgers (engine_accounting's void machinery); they are not
# cloned — the correction re-post is their revision — so no table
# entry stands here for them.
TABLES = {
    "ticket": ("tickets", "ticket_id"),
    "sale": ("sales", "sale_id"),
    "wo": ("work_orders", "wo_id"),
    "quote": ("quotes", "quote_no"),
    "change": ("change_orders", "co_no"),
    "invoice": ("invoices", "invoice_no"),
    "credit": ("credit_memos", "cm_no"),
    # Redirect #2 (Jason 2026-10-26): cash entries and petty cash
    # entries are inside the model too — same chain, own registers.
    "cash": ("cash_entries", "entry_no"),
    "petty": ("petty_cash", "pc_id"),
}

# Engine-key column per kind where it is not plain "id".
_PKS = {"cash": "entry_id"}


def _pk(kind: str) -> str:
    return _PKS.get(kind, "id")


def _num(con, kind: str, key: int):
    tbl, idcol = TABLES[kind]
    r = con.execute(f"SELECT {idcol} FROM {tbl} WHERE {_pk(kind)}=?",
                    (key,)).fetchone()
    return r[0] if r else None

# Kinds whose status vocabulary carries a Void of their own; the
# others (invoice, sale, credit memo) carry the void in the chain
# fields alone — revised_by_id set IS their void.
_VOID_STATUS = {"ticket", "wo", "quote", "change"}

_CHAIN_COLS = ("revises_id", "revised_by_id", "void_reason",
               "void_by", "void_at")


def ensure_revision_cols(con: sqlite3.Connection) -> None:
    """The chain/void columns on every document table. schema.sql
    owns them for new books and engine_migrations adds them to old
    ones; this lazy guard follows the app's lazy-column idiom so a
    revision read or write is safe on any book."""
    for tbl, _idc in TABLES.values():
        if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                       "AND name=?", (tbl,)).fetchone():
            cols = [r[1] for r in con.execute(f"PRAGMA table_info({tbl})")]
            if cols and "revises_id" not in cols:
                con.execute(f"ALTER TABLE {tbl} ADD COLUMN revises_id INTEGER")
                con.execute(f"ALTER TABLE {tbl} ADD COLUMN revised_by_id INTEGER")
                con.execute(f"ALTER TABLE {tbl} ADD COLUMN void_reason TEXT")
                con.execute(f"ALTER TABLE {tbl} ADD COLUMN void_by TEXT")
                con.execute(f"ALTER TABLE {tbl} ADD COLUMN void_at TEXT")
            if cols and "rev_pending" not in cols:
                con.execute(
                    f"ALTER TABLE {tbl} ADD COLUMN rev_pending "
                    f"INTEGER NOT NULL DEFAULT 0")
            if tbl == "cash_entries" and cols and "entry_no" not in cols:
                con.execute("ALTER TABLE cash_entries ADD COLUMN entry_no TEXT")


def rev_base(number: str) -> str:
    """A document number with any trailing ' Rev. N' stripped —
    the chain's root name."""
    return re.sub(r"\s+Rev\.\s*\d+\s*$", "", (number or "").strip())


def rev_name(number: str, n: int) -> str:
    return f"{rev_base(number)} Rev. {n}"


def chain_ancestor_keys(con, kind: str, key: int) -> list:
    """[key, its revises parent, grandparent, ...] — the chain
    from a document up to its root, by engine key."""
    tbl, _idc = TABLES[kind]
    ensure_revision_cols(con)
    out = []
    seen = set()
    cur = key
    while cur and cur not in seen:
        seen.add(cur)
        out.append(cur)
        r = con.execute(f"SELECT revises_id FROM {tbl} "
                        f"WHERE {_pk(kind)}=?", (cur,)).fetchone()
        cur = r[0] if r else None
    return out



def chain_head_ref(con, kind: str, ref: str):
    """The live document at the head of ref's chain — ref itself
    when it was never revised. Money recorded against a document
    resolves to its head (the void-and-revise ruling): a form
    prefilled from history may name a voided ancestor, and the
    posting belongs on the head."""
    tbl, idcol = TABLES[kind]
    ensure_revision_cols(con)
    row = con.execute(
        f"SELECT {_pk(kind)} AS k, revised_by_id FROM {tbl} "
        f"WHERE {idcol}=?", (ref,)).fetchone()
    if not row:
        return None
    key, nxt = row[0], row[1]
    seen = set()
    while nxt and nxt not in seen:
        seen.add(nxt)
        key = nxt
        r = con.execute(
            f"SELECT revised_by_id FROM {tbl} WHERE {_pk(kind)}=?",
            (key,)).fetchone()
        nxt = r[0] if r else None
    return _num(con, kind, key)


def revision_cols_ready(con, table: str) -> bool:
    """True when the chain columns stand on the named table (they
    ride schema.sql / migrate_legacy_schema / the lazy guard; a
    book read before any of those ran simply has no chains yet)."""
    if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                       "AND name=?", (table,)).fetchone():
        return False
    cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
    return "revised_by_id" in cols


def revision_pending(con, kind: str, key: int) -> bool:
    """The revision-session marker: set when a pending revision is
    created (the Edit act), cleared at finalize (the revision
    form's Save or Print commit).
    It is the POST layer's license to complete a revision in place;
    without it, an existing document does not save in place."""
    if not key:
        return False
    return get_option(con, f"revpend:{kind}:{key}") == "1"


def set_revision_pending(con, kind: str, key: int) -> None:
    set_option(con, f"revpend:{kind}:{key}", "1")


def clear_revision_pending(con, kind: str, key: int) -> None:
    set_option(con, f"revpend:{kind}:{key}", "")


def pending_filter(con, table: str) -> str:
    """SQL fragment excluding pending revisions from a scan of
    `table`: " AND COALESCE(rev_pending,0)=0" when the column
    stands on that table, else "". Append it to a WHERE clause (a
    scan with no WHERE yet adds "WHERE 1=1" first). A pending
    revision is invisible to money and list reads until its Save
    or Print finalizes it."""
    if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                       "AND name=?", (table,)).fetchone():
        return ""
    cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
    return " AND COALESCE(rev_pending,0)=0" if "rev_pending" in cols else ""


def pending_revision_ref(con, kind: str, ref: str):
    """The number of ref's pending revision — the clone whose
    revises_id resolves from ref's engine key and whose
    rev_pending flag stands — else None. At most one pending
    revision stands per document: reopening Edit resumes it."""
    tbl, idcol = TABLES[kind]
    ensure_revision_cols(con)
    row = con.execute(f"SELECT {_pk(kind)} FROM {tbl} WHERE {idcol}=?",
                      (ref,)).fetchone()
    if not row:
        return None
    r = con.execute(
        f"SELECT {idcol} FROM {tbl} WHERE revises_id=? "
        f"AND COALESCE(rev_pending,0)=1", (row[0],)).fetchone()
    return r[0] if r else None


def revision_is_pending(con, kind: str, key: int) -> bool:
    """True when the row at engine key `key` is a pending revision
    (rev_pending=1). The lazy guard (ensure_revision_cols) runs
    first, so the column's existence is settled before the read."""
    if not key:
        return False
    tbl, _idc = TABLES[kind]
    ensure_revision_cols(con)
    cols = [r[1] for r in con.execute(f"PRAGMA table_info({tbl})")]
    if "rev_pending" not in cols:
        return False
    r = con.execute(f"SELECT rev_pending FROM {tbl} "
                    f"WHERE {_pk(kind)}=?", (key,)).fetchone()
    return bool(r and r[0])


def revision_info(con, kind: str, row) -> dict:
    """Chain state of one document row, for summaries and doors:
    revised_by / revision_of as document numbers, and the signed
    void (reason, name, timestamp) — a revision reads the void it
    was created with from its ancestor's record."""
    tbl, _idc = TABLES[kind]
    d = dict(row)
    out = {"revised_by": None, "revision_of": None,
           "reason": None, "by": None, "at": None}
    if d.get("revised_by_id"):
        out["revised_by"] = _num(con, kind, d["revised_by_id"])
        out["reason"] = d.get("void_reason")
        out["by"] = d.get("void_by")
        out["at"] = d.get("void_at")
    if d.get("revises_id"):
        out["revision_of"] = _num(con, kind, d["revises_id"])
        anc = con.execute(
            f"SELECT void_reason, void_by, void_at FROM {tbl} "
            f"WHERE {_pk(kind)}=?", (d["revises_id"],)).fetchone()
        if anc:
            out["reason"] = anc[0]
            out["by"] = anc[1]
            out["at"] = anc[2]
    return out


def _unique_rev_no(con, kind: str, number: str, ancestors: int) -> str:
    """The prefilled revision number: '<base> Rev. N' with
    N = chain length + 1, bumped past any collision — uniqueness
    runs over the kind's whole history, voided documents included
    (their rows stand in the table, so the check sees them)."""
    tbl, idcol = TABLES[kind]
    n = ancestors + 1
    while True:
        cand = rev_name(number, n)
        if not con.execute(f"SELECT 1 FROM {tbl} WHERE {idcol}=?",
                           (cand,)).fetchone():
            return cand
        n += 1


def _copy_row(con, table: str, row, overrides: dict,
              pk: str = "id") -> int:
    d = dict(row)
    d.pop(pk, None)
    for k, v in overrides.items():
        if k in d:
            d[k] = v
    cols = list(d.keys())
    cur = con.execute(
        f"INSERT INTO {table} ({','.join(cols)}) "
        f"VALUES ({','.join('?' * len(cols))})",
        tuple(d[c] for c in cols))
    return cur.lastrowid


def _mark_void(con, kind: str, key: int, new_key: int, reason: str,
               name: str, at: str) -> None:
    tbl, _idc = TABLES[kind]
    sets = ("revised_by_id=?, void_reason=?, void_by=?, void_at=?")
    args = [new_key, reason, name, at]
    if kind in _VOID_STATUS:
        sets += ", status='Void'"
    con.execute(f"UPDATE {tbl} SET {sets} WHERE {_pk(kind)}=?",
                (*args, key))


def create_pending_revision(con, kind: str, ref: str, by: str) -> str:
    """Create document ref's PENDING revision (build 'av'): an
    editable clone carrying the original's full content, marked
    rev_pending=1, number prefilled "<original> Rev. N". The
    original is NOT voided — it stays the live chain head until
    the revision's Save or Print finalizes it (finalize_revision).
    No reason, no typed name: the void signature at finalize is
    the desk user and the server timestamp, taken automatically.
    Returns the pending revision's number. Raises ValueError with
    the operator-facing reason when the document may not be
    revised."""
    ensure_revision_cols(con)
    existing = pending_revision_ref(con, kind, ref)
    if existing is not None:
        return existing
    at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fn = {"ticket": _clone_ticket, "sale": _clone_sale,
          "wo": _clone_wo, "quote": _clone_quote,
          "change": _clone_change, "invoice": _clone_invoice,
          "credit": _clone_credit, "cash": _clone_cash,
          "petty": _clone_petty}[kind]
    return fn(con, ref, by, at)


def void_cash_settlements(con, entry_key, note, by, at) -> set:
    """Void one cash entry's settlement rows (collections +
    doc_collections + payment_allocations, same column guards as
    today) and refresh the touched invoices' statuses; returns
    the set of invoice numbers touched."""
    settled = con.execute(
        "SELECT pay_id, invoice_id FROM collections "
        "WHERE cash_entry_id=? AND COALESCE(voided,0)=0",
        (entry_key,)).fetchall()
    inv_nos = {num_of(con, "invoices", r[1]) for r in settled if r[1]}
    for ltbl in ("collections", "doc_collections"):
        con.execute(
            f"UPDATE {ltbl} SET voided=1, void_reason=?, "
            f"void_by=?, void_at=? WHERE cash_entry_id=? "
            f"AND COALESCE(voided,0)=0",
            (note, by, at, entry_key))
    pacols = [r[1] for r in con.execute(
        "PRAGMA table_info(payment_allocations)")]
    if "voided" in pacols and "cash_entry_id" in pacols:
        con.execute(
            "UPDATE payment_allocations SET voided=1 "
            "WHERE cash_entry_id=? AND COALESCE(voided,0)=0",
            (entry_key,))
    if inv_nos:
        from engine_accounting import _refresh_invoice_status
        for ino in inv_nos:
            _refresh_invoice_status(con, ino)
    return inv_nos


def finalize_revision(con, kind: str, ref: str, note: str,
                      by: str) -> str:
    """Commit a pending revision (build 'av') — the revision
    form's Save, or its Print (which commits first). ref is the
    PENDING revision's number. All steps land before one final
    commit: the original voids now, signed with the desk user
    (`by`) and the server timestamp, automatically; its void
    reason carries the revision's OPTIONAL note (empty when none
    was offered); the clone's rev_pending flag clears and its
    session marker clears, so the clone stands as chain head.
    Per kind: a credit memo wears a FRESH company snapshot at
    this, its posting, moment; a cash entry's ORIGINAL settlement
    rows void alongside its entry (complete_cash_revision
    releases the original's settlement first, inside the same
    act, so the fresh settlement posts against the reopened
    balance, and the clone's fresh settlement was posted by
    complete_cash_revision before this call, so the
    invoice-status refresh here reads the final money). Returns
    the ORIGINAL's number."""
    ensure_revision_cols(con)
    tbl, idcol = TABLES[kind]
    pk = _pk(kind)
    row = con.execute(f"SELECT * FROM {tbl} WHERE {idcol}=?",
                      (ref,)).fetchone()
    if not row:
        raise ValueError(f"Unknown document {ref}")
    clone = dict(row)
    if not clone.get("rev_pending"):
        raise ValueError(f"{ref} is not a pending revision")
    clone_key = clone[pk]
    orig_key = clone.get("revises_id")
    if not orig_key:
        raise ValueError(f"{ref} is not a pending revision")
    orow = con.execute(f"SELECT * FROM {tbl} WHERE {pk}=?",
                       (orig_key,)).fetchone()
    if not orow:
        raise ValueError(f"{ref} is not a pending revision")
    orig = dict(orow)
    if orig.get("revised_by_id"):
        head = chain_head_ref(con, kind, _num(con, kind, orig_key))
        raise ValueError(
            f"{_num(con, kind, orig_key)} was already revised — "
            f"{head}, the live document at the head of its chain, "
            f"stands instead")
    at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    note = (note or "").strip()
    by = (by or "").strip()
    if kind == "sale":
        # A sale document is its group: every original row voids
        # to its own clone row, and every clone row's pending flag
        # clears. The chain is marked from the head row's pair.
        ogroup = orig.get("group_id") or orig_key
        orows = con.execute(
            "SELECT * FROM sales WHERE group_id=? ORDER BY seq, id",
            (ogroup,)).fetchall()
        cgroup = clone.get("group_id") or clone_key
        for orow2 in orows:
            crow = con.execute(
                "SELECT id FROM sales WHERE revises_id=?",
                (orow2["id"],)).fetchone()
            if crow:
                _mark_void(con, "sale", orow2["id"], crow[0],
                           note, by, at)
        con.execute(
            "UPDATE sales SET rev_pending=0 WHERE group_id=?",
            (cgroup,))
    else:
        _mark_void(con, kind, orig_key, clone_key, note, by, at)
        con.execute(f"UPDATE {tbl} SET rev_pending=0 WHERE {pk}=?",
                    (clone_key,))
    clear_revision_pending(con, kind, clone_key)
    if kind == "credit":
        stamp_company_snapshot(con, "credit_memos", clone_key)
    elif kind == "cash":
        void_cash_settlements(con, orig_key, note, by, at)
    con.commit()
    return _num(con, kind, orig_key)


def _head_row(con, kind: str, ref: str):
    tbl, idcol = TABLES[kind]
    row = con.execute(f"SELECT * FROM {tbl} WHERE {idcol}=?",
                      (ref,)).fetchone()
    if not row:
        raise ValueError(f"Unknown document {ref}")
    if dict(row).get("revised_by_id"):
        new = _num(con, kind, row["revised_by_id"])
        raise ValueError(
            f"{ref} was already revised — revise {new}, the live "
            f"document at the head of its chain")
    # A document voided outright (a status Void with no revision
    # behind it) stands as the record — it is not revised back to
    # life; a new document is written instead.
    if "status" in dict(row) and (row["status"] or "") == "Void":
        raise ValueError(f"{ref} is void — it stands as the record")
    return row


def _clone_ticket(con, ref, by, at):
    row = _head_row(con, "ticket", ref)
    if row["invoice_id"]:
        raise ValueError(
            f"Rental Ticket {ref} is on "
            f"{num_of(con, 'invoices', row['invoice_id'])} — its "
            f"paper is the invoice's now and it cannot be revised")
    ancestors = len(chain_ancestor_keys(con, "ticket", row["id"])) - 1
    new_no = _unique_rev_no(con, "ticket", ref, ancestors)
    new_key = _copy_row(con, "tickets", row, {
        "ticket_id": new_no, "invoice_id": None,
        "revises_id": row["id"], "revised_by_id": None,
        "void_reason": None, "void_by": None, "void_at": None,
        "rev_pending": 1, "clerk": by, "created_at": at})
    for ln in con.execute("SELECT * FROM ticket_lines "
                          "WHERE ticket_id=?", (row["id"],)).fetchall():
        _copy_row(con, "ticket_lines", ln, {"ticket_id": new_key}, pk="line_id")
    set_revision_pending(con, "ticket", new_key)
    con.commit()
    return new_no


def _clone_sale(con, ref, by, at):
    from engine_assets import next_sale_id  # lazy: import order
    gkey = doc_key(con, "sale", ref)
    rows = con.execute(
        "SELECT * FROM sales WHERE group_id=? ORDER BY seq, id",
        (gkey,)).fetchall()
    if not rows:
        raise ValueError(f"Unknown sale {ref}")
    head = rows[0]
    if dict(head).get("revised_by_id"):
        new = num_of(con, "sales", head["revised_by_id"])
        raise ValueError(
            f"{ref} was already revised — revise {new}, the live "
            f"document at the head of its chain")
    if any(r["invoice_id"] for r in rows):
        ino = next(num_of(con, "invoices", r["invoice_id"])
                   for r in rows if r["invoice_id"])
        raise ValueError(
            f"Sale {ref} is on {ino} — its money lives on the "
            f"invoice now and it cannot be revised")
    ancestors = len(chain_ancestor_keys(con, "sale", head["id"])) - 1
    new_no = _unique_rev_no(con, "sale", ref, ancestors)
    new_keys = {}
    for i, r in enumerate(rows):
        no = new_no if i == 0 else next_sale_id(con)
        nk = _copy_row(con, "sales", r, {
            "sale_id": no, "group_id": None,
            "revises_id": r["id"], "revised_by_id": None,
            "void_reason": None, "void_by": None, "void_at": None,
            "rev_pending": 1, "clerk": by, "created_at": at})
        new_keys[r["id"]] = nk
        if i == 0:
            con.execute("UPDATE sales SET group_id=? WHERE id=?",
                        (nk, nk))
    for i, r in enumerate(rows):
        if i:
            con.execute("UPDATE sales SET group_id=? WHERE id=?",
                        (new_keys[head["id"]], new_keys[r["id"]]))
    set_revision_pending(con, "sale", new_keys[head["id"]])
    con.commit()
    return new_no


def _clone_wo(con, ref, by, at):
    row = _head_row(con, "wo", ref)
    if row["invoice_id"]:
        raise ValueError(
            f"Work Order {ref} is on "
            f"{num_of(con, 'invoices', row['invoice_id'])} — its "
            f"paper is the invoice's now and it cannot be revised")
    ancestors = len(chain_ancestor_keys(con, "wo", row["id"])) - 1
    new_no = _unique_rev_no(con, "wo", ref, ancestors)
    new_key = _copy_row(con, "work_orders", row, {
        "wo_id": new_no, "revises_id": row["id"],
        "revised_by_id": None, "void_reason": None, "void_by": None,
        "void_at": None, "rev_pending": 1, "clerk": by, "created_at": at})
    try:
        lines = con.execute("SELECT * FROM wo_lines WHERE wo_id=?",
                            (row["id"],)).fetchall()
    except Exception:
        lines = []
    for ln in lines:
        _copy_row(con, "wo_lines", ln, {"wo_id": new_key}, pk="line_id")
    set_revision_pending(con, "wo", new_key)
    con.commit()
    return new_no


def _clone_quote(con, ref, by, at):
    row = _head_row(con, "quote", ref)
    ancestors = len(chain_ancestor_keys(con, "quote", row["id"])) - 1
    new_no = _unique_rev_no(con, "quote", ref, ancestors)
    # JC-AB18: a revision of an Accepted or Converted quote is new
    # paper — its terms are unaccepted terms until the operator
    # works it through the status door again — so the clone stands
    # as a Draft. (save_quote also refuses edits to Accepted /
    # Converted quotes; the clone must be saveable.) Other
    # statuses copy verbatim.
    new_key = _copy_row(con, "quotes", row, {
        "quote_no": new_no, "revises_id": row["id"],
        "revised_by_id": None, "void_reason": None, "void_by": None,
        "void_at": None, "rev_pending": 1, "clerk": by, "created_at": at,
        "status": ("Draft" if (row["status"] or "") in
                   ("Accepted", "Converted") else row["status"])})
    for ln in con.execute("SELECT * FROM quote_lines WHERE quote_id=?",
                          (row["id"],)).fetchall():
        _copy_row(con, "quote_lines", ln, {"quote_id": new_key}, pk="line_id")
    set_revision_pending(con, "quote", new_key)
    con.commit()
    return new_no


def _clone_change(con, ref, by, at):
    row = _head_row(con, "change", ref)
    ancestors = len(chain_ancestor_keys(con, "change", row["id"])) - 1
    new_no = _unique_rev_no(con, "change", ref, ancestors)
    new_key = _copy_row(con, "change_orders", row, {
        "co_no": new_no, "revises_id": row["id"],
        "revised_by_id": None, "void_reason": None, "void_by": None,
        "void_at": None, "rev_pending": 1, "clerk": by, "created_at": at})
    for ln in con.execute(
            "SELECT * FROM change_order_lines WHERE co_id=?",
            (row["id"],)).fetchall():
        _copy_row(con, "change_order_lines", ln, {"co_id": new_key}, pk="line_id")
    set_revision_pending(con, "change", new_key)
    con.commit()
    return new_no


def _clone_invoice(con, ref, by, at):
    row = _head_row(con, "invoice", ref)
    ancestors = len(chain_ancestor_keys(con, "invoice", row["id"])) - 1
    new_no = _unique_rev_no(con, "invoice", ref, ancestors)
    new_key = _copy_row(con, "invoices", row, {
        "invoice_no": new_no, "revises_id": row["id"],
        "revised_by_id": None, "void_reason": None, "void_by": None,
        "void_at": None, "rev_pending": 1, "clerk": by, "created_at": at})
    for ln in con.execute("SELECT * FROM invoice_lines "
                          "WHERE invoice_id=?", (row["id"],)).fetchall():
        _copy_row(con, "invoice_lines", ln, {"invoice_id": new_key}, pk="line_id")
    try:
        docs = con.execute("SELECT * FROM invoice_docs "
                           "WHERE invoice_id=?", (row["id"],)).fetchall()
    except Exception:
        docs = []
    for dc in docs:
        _copy_row(con, "invoice_docs", dc, {"invoice_id": new_key}, pk="doc_id")
    set_revision_pending(con, "invoice", new_key)
    con.commit()
    return new_no


def _clone_credit(con, ref, by, at):
    row = _head_row(con, "credit", ref)
    ancestors = len(chain_ancestor_keys(con, "credit", row["id"])) - 1
    new_no = _unique_rev_no(con, "credit", ref, ancestors)
    new_key = _copy_row(con, "credit_memos", row, {
        "cm_no": new_no, "revises_id": row["id"],
        "revised_by_id": None, "void_reason": None, "void_by": None,
        "void_at": None, "rev_pending": 1, "clerk": by, "created_at": at})
    for ln in con.execute("SELECT * FROM credit_memo_lines "
                          "WHERE cm_id=?", (row["id"],)).fetchall():
        _copy_row(con, "credit_memo_lines", ln, {"cm_id": new_key}, pk="line_id")
    # No company snapshot here (build 'av'): the clone is only
    # pending — finalize_revision stamps the fresh snapshot at
    # the commit, which is the memo's posting moment.
    set_revision_pending(con, "credit", new_key)
    con.commit()
    return new_no


def _clone_cash(con, ref, by, at):
    """Cash entry (redirect #2): the entry AND its settlement are
    one money event. Under the pending model (build 'av') the
    clone stands as a shell carrying the original's content and
    NOTHING voids here — the original entry and its settlement
    rows stay live until the revision form's Save completes the
    clone through record_cash_entry's own path
    (complete_cash_revision, which posts the settlement fresh
    against the clone and then finalizes: original entry and its
    settlement rows void at that commit). A settling entry whose
    overage became an open credit memo cannot be revised — the
    memo cannot be un-issued (the app has no credit-memo void)."""
    row = _head_row(con, "cash", ref)
    key = row["entry_id"]
    settled = con.execute(
        "SELECT pay_id, invoice_id FROM collections "
        "WHERE cash_entry_id=? AND COALESCE(voided,0)=0",
        (key,)).fetchall()
    doc_settled = con.execute(
        "SELECT pay_id FROM doc_collections "
        "WHERE cash_entry_id=? AND COALESCE(voided,0)=0",
        (key,)).fetchall()
    pay_ids = {r[0] for r in settled} | {r[0] for r in doc_settled}
    for pid in pay_ids:
        cm = con.execute(
            "SELECT cm_no FROM credit_memos WHERE notes LIKE ?",
            (f"%Auto-created%(payment {pid})%",)).fetchone()
        if cm:
            raise ValueError(
                f"Cash entry {ref} issued open credit {cm[0]} — a "
                f"credit memo cannot be un-issued, so the entry "
                f"stands as the record")
    ancestors = len(chain_ancestor_keys(con, "cash", key)) - 1
    new_no = _unique_rev_no(con, "cash", ref, ancestors)
    new_key = _copy_row(con, "cash_entries", row, {
        "entry_no": new_no, "revises_id": key,
        "revised_by_id": None, "void_reason": None, "void_by": None,
        "void_at": None, "rev_pending": 1, "clerk": by, "created_at": at},
        pk="entry_id")
    set_revision_pending(con, "cash", new_key)
    con.commit()
    return new_no


def _clone_petty(con, ref, by, at):
    """Petty cash entry (redirect #2): the template inside the
    petty log only — the clone is a pending shell in the same log;
    the revision form's Save completes it in place
    (complete_petty_revision) and finalizes the chain at that
    commit. Balances exclude pending rows, so the original alone
    stands in the box until then."""
    row = _head_row(con, "petty", ref)
    key = row["id"]
    ancestors = len(chain_ancestor_keys(con, "petty", key)) - 1
    new_no = _unique_rev_no(con, "petty", ref, ancestors)
    new_key = _copy_row(con, "petty_cash", row, {
        "pc_id": new_no, "revises_id": key,
        "revised_by_id": None, "void_reason": None, "void_by": None,
        "void_at": None, "rev_pending": 1, "clerk": by, "created_at": at})
    set_revision_pending(con, "petty", new_key)
    con.commit()
    return new_no
