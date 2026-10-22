"""SQLite storage for outbound invoices and their paid/open history."""

import os
import sqlite3
from datetime import datetime

# The project folder (the parent of code/). Data files live here whatever directory a script is run from.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(PROJECT_ROOT, "invoices.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS invoices (
    id              INTEGER PRIMARY KEY,
    customer        TEXT NOT NULL,
    invoice_number  TEXT,
    invoice_date    TEXT,
    terms           TEXT,
    due_date        TEXT,
    amount          REAL,
    currency        TEXT NOT NULL DEFAULT 'USD',
    memo            TEXT,
    po_number       TEXT,
    status          TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'paid')),
    paid_at         TEXT,
    needs_review    INTEGER NOT NULL DEFAULT 0,
    review_reason   TEXT,
    source_file     TEXT,
    pdf_file        TEXT,
    source_link     TEXT,
    sent_at         TEXT,
    manually_edited INTEGER NOT NULL DEFAULT 0,
    ignored         INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_invoices_number ON invoices (invoice_number) WHERE invoice_number IS NOT NULL;

CREATE TABLE IF NOT EXISTS status_history (
    id         INTEGER PRIMARY KEY,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id),
    status     TEXT NOT NULL,
    changed_at TEXT NOT NULL,
    source     TEXT NOT NULL CHECK (source IN ('import', 'manual'))
);

-- One row per completed import (dashboard Refresh or import_pdfs.py), for the "Last refreshed" stamp.
CREATE TABLE IF NOT EXISTS refreshes (
    finished_at TEXT NOT NULL
);
"""

# Fields the Fix form and the API may edit. Editing any of them marks the row manually edited.
EDITABLE = ("customer", "invoice_number", "invoice_date", "terms", "due_date", "amount", "currency", "memo",
            "po_number")
REQUIRED = {"customer": "customer", "invoice_number": "invoice number", "invoice_date": "invoice date",
            "amount": "amount"}

_LIST_COLUMNS = """id, customer, invoice_number, invoice_date, terms, due_date, amount, currency, memo, po_number,
                   status, paid_at, source_link, sent_at, pdf_file IS NOT NULL AS has_pdf"""


def init_db(path=DEFAULT_DB):
    """Open (creating if needed) the database and return a connection."""
    # One connection per API request, but FastAPI may open it and use it on different worker threads.
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def _rows(cursor):
    rows = [dict(r) for r in cursor]
    for row in rows:
        if "has_pdf" in row:
            row["has_pdf"] = bool(row["has_pdf"])
    return rows


def _missing(invoice):
    return [label for field, label in REQUIRED.items() if invoice.get(field) in (None, "")]


def save_parsed_invoice(conn, parsed, *, pdf_file=None, source_link=None, sent_at=None, now):
    """Store one parsed invoice; returns (id, created).

    The same invoice seen again (same invoice number, or the same file when it had none) is not
    duplicated: its parsed fields are refreshed unless someone edited it by hand or ignored it.
    `sent_at` keeps the earliest time the invoice was seen. Paid status is never touched here.
    """
    key, value = ("invoice_number", parsed["invoice_number"]) if parsed.get("invoice_number") \
        else ("source_file", parsed.get("source_file"))
    existing = conn.execute(f"SELECT * FROM invoices WHERE {key} = ?", (value,)).fetchone() if value else None
    fields = {f: parsed.get(f) for f in EDITABLE}
    fields["customer"] = fields["customer"] or "Unknown customer"
    fields["currency"] = fields["currency"] or "USD"
    review = "; ".join(parsed.get("review_reasons") or []) or None
    if existing is None:
        cursor = conn.execute(
            f"INSERT INTO invoices ({', '.join(fields)}, needs_review, review_reason, source_file, pdf_file, "
            f"source_link, sent_at) VALUES ({', '.join('?' * (len(fields) + 6))})",
            (*fields.values(), int(bool(review)), review, parsed.get("source_file"), pdf_file, source_link, sent_at))
        invoice_id = cursor.lastrowid
        conn.execute("INSERT INTO status_history (invoice_id, status, changed_at, source) VALUES (?, 'open', ?, 'import')",
                     (invoice_id, now))
        conn.commit()
        return invoice_id, True
    invoice_id = existing["id"]
    if existing["sent_at"] is None or (sent_at and sent_at < existing["sent_at"]):
        conn.execute("UPDATE invoices SET sent_at = ? WHERE id = ?", (sent_at, invoice_id))
    if not existing["manually_edited"] and not existing["ignored"]:
        sets = ", ".join(f"{f} = ?" for f in fields)
        conn.execute(f"UPDATE invoices SET {sets}, needs_review = ?, review_reason = ?, "
                     "pdf_file = COALESCE(?, pdf_file), source_link = COALESCE(?, source_link) WHERE id = ?",
                     (*fields.values(), int(bool(review)), review, pdf_file, source_link, invoice_id))
    conn.commit()
    return invoice_id, False


def list_open(conn):
    """Outstanding (unpaid) invoices the parser read in full, oldest due first."""
    return _rows(conn.execute(
        f"SELECT {_LIST_COLUMNS} FROM invoices WHERE status = 'open' AND needs_review = 0 AND ignored = 0 "
        "ORDER BY due_date IS NULL, due_date, invoice_date, id"))


def list_paid(conn):
    """Paid invoices, most recently paid first."""
    return _rows(conn.execute(
        f"SELECT {_LIST_COLUMNS} FROM invoices WHERE status = 'paid' AND needs_review = 0 AND ignored = 0 "
        "ORDER BY paid_at DESC, id DESC"))


def _attention(conn, ignored):
    return _rows(conn.execute(
        "SELECT id, customer, invoice_number, invoice_date, due_date, amount, currency, review_reason AS reason, "
        "source_link, pdf_file IS NOT NULL AS has_pdf FROM invoices WHERE needs_review = 1 AND ignored = ? "
        "ORDER BY id DESC", (int(ignored),)))


def list_needs_attention(conn):
    return _attention(conn, False)


def list_ignored(conn):
    return _attention(conn, True)


def get_invoice_history(conn, invoice_id):
    """Oldest first. Sorted as datetimes, not text, so times stamped in different offsets order correctly."""
    rows = conn.execute("SELECT id, status, changed_at, source FROM status_history WHERE invoice_id = ?", (invoice_id,))
    rows = sorted(rows, key=lambda r: (datetime.fromisoformat(r["changed_at"]), r["id"]))
    return [{"status": r["status"], "changed_at": r["changed_at"], "source": r["source"]} for r in rows]


def get_pdf_file(conn, invoice_id):
    row = conn.execute("SELECT pdf_file FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
    return row["pdf_file"] if row else None


def update_invoice(conn, invoice_id, changes, now):
    """Apply an edit; returns False when there is no such invoice. Raises ValueError on a broken rule.

    - Editing a parsed field marks the row manually edited (import never overwrites it again) and
      re-checks what is still missing, so a full fix moves it out of Needs attention.
    - `status` "paid" needs `paid_at` (a date); "open" clears it. Each change is recorded in the history.
    - `ignored` hides or restores a flagged invoice; only flagged ones can be ignored.
    """
    row = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
    if row is None:
        return False
    invoice = dict(row)
    edits = {f: changes[f] for f in EDITABLE if f in changes}
    if edits:
        invoice.update(edits)
        missing = _missing(invoice)
        invoice["needs_review"] = int(bool(missing))
        invoice["review_reason"] = "; ".join(f"no {label} found" for label in missing) or None
        invoice["manually_edited"] = 1
    if "ignored" in changes:
        if changes["ignored"] and not invoice["needs_review"]:
            raise ValueError("only invoices that need attention can be ignored")
        invoice["ignored"] = int(changes["ignored"])
    if "status" in changes:
        if invoice["needs_review"]:
            raise ValueError("fix this invoice before marking it paid")
        if changes["status"] == "paid" and not changes.get("paid_at"):
            raise ValueError("paid_at is required when marking an invoice paid")
        if changes["status"] != invoice["status"]:
            conn.execute("INSERT INTO status_history (invoice_id, status, changed_at, source) VALUES (?, ?, ?, 'manual')",
                         (invoice_id, changes["status"], now))
        invoice["status"] = changes["status"]
        invoice["paid_at"] = changes.get("paid_at") if changes["status"] == "paid" else None
    columns = [*EDITABLE, "needs_review", "review_reason", "manually_edited", "ignored", "status", "paid_at"]
    conn.execute(f"UPDATE invoices SET {', '.join(f'{c} = ?' for c in columns)} WHERE id = ?",
                 (*(invoice[c] for c in columns), invoice_id))
    conn.commit()
    return True


def record_refresh(conn, finished_at):
    conn.execute("INSERT INTO refreshes (finished_at) VALUES (?)", (finished_at,))
    conn.commit()


def last_refresh(conn):
    row = conn.execute("SELECT MAX(finished_at) AS at FROM refreshes").fetchone()
    return row["at"]
