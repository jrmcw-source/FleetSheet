"""FleetSheet engine — void-and-revise (build 'ab', Jason's ruling
2026-10-26, standing): editing a posted/issued document never
updates it in place. The Edit act — a reason and the operator's
name, confirmed — voids the original (reason, name, and timestamp
signed into its record) and creates the revision as a NEW document
carrying the original's full content, its number prefilled
"<original> Rev. N". The chain links by engine key
(revises_id / revised_by_id on every document table); numbers are
never keys. The newest revision is the chain head — the live
document; voided ancestors are read-only paper. Money recorded
against any link of the chain resolves to the head (the accounting
engine's settled/total reads walk the chain through here).

The void + revision-creation happen when the operator CONFIRMS the
reason/name prompt (JC-AB0): the Edit act itself is the deliberate,
recorded act, on the pattern of his audited overrides. A revision
created and never finished stands as an exact copy of the original
at the head of the chain — the record stays coherent either way.
The revision's own form opens unlocked under a session marker
(options table, no schema of its own); its first Save completes
the revision, and the POST layer refuses any in-place save of an
existing document that carries no marker.
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
    """The revision-session marker: set when a revision is created
    (the confirm act), cleared by the revision form's first Save.
    It is the POST layer's license to complete a revision in place;
    without it, an existing document does not save in place."""
    if not key:
        return False
    return get_option(con, f"revpend:{kind}:{key}") == "1"


def set_revision_pending(con, kind: str, key: int) -> None:
    set_option(con, f"revpend:{kind}:{key}", "1")


def clear_revision_pending(con, kind: str, key: int) -> None:
    set_option(con, f"revpend:{kind}:{key}", "")


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


def _require_reason_name(reason: str, name: str) -> tuple:
    reason = (reason or "").strip()
    name = (name or "").strip()
    if not reason:
        raise ValueError("A revision needs its reason")
    if not name:
        raise ValueError("A revision needs the operator's name")
    return reason, name


def create_revision(con, kind: str, ref: str, reason: str,
                    name: str) -> str:
    """Void document ref and create its revision — ONE operation
    (JC-AB0, the confirm act). Returns the revision's number.
    Raises ValueError with the operator-facing reason when the
    document may not be revised."""
    ensure_revision_cols(con)
    reason, name = _require_reason_name(reason, name)
    at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fn = {"ticket": _revise_ticket, "sale": _revise_sale,
          "wo": _revise_wo, "quote": _revise_quote,
          "change": _revise_change, "invoice": _revise_invoice,
          "credit": _revise_credit, "cash": _revise_cash,
          "petty": _revise_petty}[kind]
    return fn(con, ref, reason, name, at)


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


def _revise_ticket(con, ref, reason, name, at):
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
        "clerk": name, "created_at": at})
    for ln in con.execute("SELECT * FROM ticket_lines "
                          "WHERE ticket_id=?", (row["id"],)).fetchall():
        _copy_row(con, "ticket_lines", ln, {"ticket_id": new_key}, pk="line_id")
    _mark_void(con, "ticket", row["id"], new_key, reason, name, at)
    set_revision_pending(con, "ticket", new_key)
    con.commit()
    return new_no


def _revise_sale(con, ref, reason, name, at):
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
            "clerk": name, "created_at": at})
        new_keys[r["id"]] = nk
        if i == 0:
            con.execute("UPDATE sales SET group_id=? WHERE id=?",
                        (nk, nk))
    for i, r in enumerate(rows):
        if i:
            con.execute("UPDATE sales SET group_id=? WHERE id=?",
                        (new_keys[head["id"]], new_keys[r["id"]]))
    for r in rows:
        _mark_void(con, "sale", r["id"], new_keys[r["id"]],
                   reason, name, at)
    set_revision_pending(con, "sale", new_keys[head["id"]])
    con.commit()
    return new_no


def _revise_wo(con, ref, reason, name, at):
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
        "void_at": None, "clerk": name, "created_at": at})
    try:
        lines = con.execute("SELECT * FROM wo_lines WHERE wo_id=?",
                            (row["id"],)).fetchall()
    except Exception:
        lines = []
    for ln in lines:
        _copy_row(con, "wo_lines", ln, {"wo_id": new_key}, pk="line_id")
    _mark_void(con, "wo", row["id"], new_key, reason, name, at)
    set_revision_pending(con, "wo", new_key)
    con.commit()
    return new_no


def _revise_quote(con, ref, reason, name, at):
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
        "void_at": None, "clerk": name, "created_at": at,
        "status": ("Draft" if (row["status"] or "") in
                   ("Accepted", "Converted") else row["status"])})
    for ln in con.execute("SELECT * FROM quote_lines WHERE quote_id=?",
                          (row["id"],)).fetchall():
        _copy_row(con, "quote_lines", ln, {"quote_id": new_key}, pk="line_id")
    _mark_void(con, "quote", row["id"], new_key, reason, name, at)
    set_revision_pending(con, "quote", new_key)
    con.commit()
    return new_no


def _revise_change(con, ref, reason, name, at):
    row = _head_row(con, "change", ref)
    ancestors = len(chain_ancestor_keys(con, "change", row["id"])) - 1
    new_no = _unique_rev_no(con, "change", ref, ancestors)
    new_key = _copy_row(con, "change_orders", row, {
        "co_no": new_no, "revises_id": row["id"],
        "revised_by_id": None, "void_reason": None, "void_by": None,
        "void_at": None, "clerk": name, "created_at": at})
    for ln in con.execute(
            "SELECT * FROM change_order_lines WHERE co_id=?",
            (row["id"],)).fetchall():
        _copy_row(con, "change_order_lines", ln, {"co_id": new_key}, pk="line_id")
    _mark_void(con, "change", row["id"], new_key, reason, name, at)
    set_revision_pending(con, "change", new_key)
    con.commit()
    return new_no


def _revise_invoice(con, ref, reason, name, at):
    row = _head_row(con, "invoice", ref)
    ancestors = len(chain_ancestor_keys(con, "invoice", row["id"])) - 1
    new_no = _unique_rev_no(con, "invoice", ref, ancestors)
    new_key = _copy_row(con, "invoices", row, {
        "invoice_no": new_no, "revises_id": row["id"],
        "revised_by_id": None, "void_reason": None, "void_by": None,
        "void_at": None, "clerk": name, "created_at": at})
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
    _mark_void(con, "invoice", row["id"], new_key, reason, name, at)
    set_revision_pending(con, "invoice", new_key)
    con.commit()
    return new_no


def _revise_credit(con, ref, reason, name, at):
    row = _head_row(con, "credit", ref)
    ancestors = len(chain_ancestor_keys(con, "credit", row["id"])) - 1
    new_no = _unique_rev_no(con, "credit", ref, ancestors)
    new_key = _copy_row(con, "credit_memos", row, {
        "cm_no": new_no, "revises_id": row["id"],
        "revised_by_id": None, "void_reason": None, "void_by": None,
        "void_at": None, "clerk": name, "created_at": at})
    for ln in con.execute("SELECT * FROM credit_memo_lines "
                          "WHERE cm_id=?", (row["id"],)).fetchall():
        _copy_row(con, "credit_memo_lines", ln, {"cm_id": new_key}, pk="line_id")
    _mark_void(con, "credit", row["id"], new_key, reason, name, at)
    # A credit memo stands complete at the confirm act — that act
    # IS its posting, so the revision wears a FRESH company
    # snapshot (redirect #3), not the voided memo's.
    stamp_company_snapshot(con, "credit_memos", new_key)
    con.commit()
    return new_no


def _revise_cash(con, ref, reason, name, at):
    """Cash entry (redirect #2): the entry AND its settlement are
    one money event, so the void takes both — the entry's chain
    fields sign the entry, and its settlement rows in the payment
    ledgers void alongside (their own void fields sign them). The
    clone stands as a shell carrying the original's content; the
    revision form's Save completes it through record_cash_entry's
    own path (complete_cash_revision), which posts the settlement
    fresh against the clone. A settling entry whose overage became
    an open credit memo cannot be revised — the memo cannot be
    un-issued (the app has no credit-memo void)."""
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
        "void_at": None, "clerk": name, "created_at": at},
        pk="entry_id")
    inv_nos = {num_of(con, "invoices", r[1]) for r in settled if r[1]}
    for tbl in ("collections", "doc_collections"):
        con.execute(
            f"UPDATE {tbl} SET voided=1, void_reason=?, void_by=?, "
            f"void_at=? WHERE cash_entry_id=? "
            f"AND COALESCE(voided,0)=0",
            (reason, name, at, key))
    pacols = [r[1] for r in con.execute(
        "PRAGMA table_info(payment_allocations)")]
    if "voided" in pacols and "cash_entry_id" in pacols:
        con.execute(
            "UPDATE payment_allocations SET voided=1 "
            "WHERE cash_entry_id=? AND COALESCE(voided,0)=0", (key,))
    _mark_void(con, "cash", key, new_key, reason, name, at)
    if inv_nos:
        from engine_accounting import _refresh_invoice_status
        for ino in inv_nos:
            _refresh_invoice_status(con, ino)
    set_revision_pending(con, "cash", new_key)
    con.commit()
    return new_no


def _revise_petty(con, ref, reason, name, at):
    """Petty cash entry (redirect #2): the template inside the
    petty log only — the clone is a shell in the same log; the
    revision form's Save completes it in place (complete_petty_
    revision). Balances read chain heads only, so the voided
    original drops out of the box the moment the revision stands."""
    row = _head_row(con, "petty", ref)
    key = row["id"]
    ancestors = len(chain_ancestor_keys(con, "petty", key)) - 1
    new_no = _unique_rev_no(con, "petty", ref, ancestors)
    new_key = _copy_row(con, "petty_cash", row, {
        "pc_id": new_no, "revises_id": key,
        "revised_by_id": None, "void_reason": None, "void_by": None,
        "void_at": None, "clerk": name, "created_at": at})
    _mark_void(con, "petty", key, new_key, reason, name, at)
    set_revision_pending(con, "petty", new_key)
    con.commit()
    return new_no
