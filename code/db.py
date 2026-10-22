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
    source     TEXT NOT NULL CHECK (source IN ('import', 'manual', 'netsuite'))
);

-- One row per NetSuite payment-history line: a payment, credit memo, currency revaluation or journal
-- applied to an invoice. Keyed by invoice number, not id, so a payment can arrive before its invoice.
CREATE TABLE IF NOT EXISTS applications (
    id              INTEGER PRIMARY KEY,
    invoice_number  TEXT NOT NULL,
    document_number TEXT NOT NULL,
    kind            TEXT NOT NULL CHECK (kind IN ('payment', 'credit_memo', 'revaluation', 'journal')),
    applied_on      TEXT NOT NULL,
    amount_usd      REAL NOT NULL,  -- positive reduces the invoice's balance
    currency        TEXT,           -- currency of the applying document
    source          TEXT NOT NULL,  -- the export file it came from
    UNIQUE (invoice_number, document_number, kind, applied_on, amount_usd)
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

# Columns the NetSuite import adds to invoices, created on databases made before it existed.
NETSUITE_COLUMNS = {
    "subsidiary": "TEXT",        # '210' (WSL, LLC) or '315' (WSL Merchandise)
    "customer_raw": "TEXT",      # NetSuite's name before normalising, e.g. "OMD Digital_AU"
    "amount_usd": "REAL",        # the invoice in USD at its own exchange rate
    "exchange_rate": "REAL",
    "netsuite_status": "TEXT",   # 'Open' or 'Paid In Full', as last exported
    "netsuite_seen_at": "TEXT",  # when the last export carrying it was imported
    "reconcile_issue": "TEXT",   # why NetSuite's status and the payments disagree; NULL when they agree
}

# A balance within half a cent is settled. Payments and revaluations net to the invoice's USD
# amount exactly in NetSuite's export, so this only absorbs float noise.
SETTLED_TOLERANCE = 0.005


def _migrate(conn):
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(invoices)")}
    for name, kind in NETSUITE_COLUMNS.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE invoices ADD COLUMN {name} {kind}")
    # status_history's CHECK predates the 'netsuite' source; SQLite can only change it by rebuilding.
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'status_history'").fetchone()["sql"]
    if "'netsuite'" not in sql:
        conn.executescript("""
            ALTER TABLE status_history RENAME TO status_history_old;
            CREATE TABLE status_history (
                id         INTEGER PRIMARY KEY,
                invoice_id INTEGER NOT NULL REFERENCES invoices(id),
                status     TEXT NOT NULL,
                changed_at TEXT NOT NULL,
                source     TEXT NOT NULL CHECK (source IN ('import', 'manual', 'netsuite'))
            );
            INSERT INTO status_history SELECT * FROM status_history_old;
            DROP TABLE status_history_old;
        """)
    conn.commit()


def init_db(path=DEFAULT_DB):
    """Open (creating if needed) the database and return a connection."""
    # One connection per API request, but FastAPI may open it and use it on different worker threads.
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _rows(cursor):
    rows = [dict(r) for r in cursor]
    for row in rows:
        if "has_pdf" in row:
            row["has_pdf"] = bool(row["has_pdf"])
    return rows


def _missing(invoice):
    return [label for field, label in REQUIRED.items() if invoice.get(field) in (None, "")]


def _recheck_missing(invoice):
    """Flag (or clear) the invoice by what required fields it still lacks."""
    missing = _missing(invoice)
    invoice["needs_review"] = int(bool(missing))
    invoice["review_reason"] = "; ".join(f"no {label} found" for label in missing) or None


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


_CLEAN = "needs_review = 0 AND reconcile_issue IS NULL AND ignored = 0"
_FLAGGED = "(needs_review = 1 OR reconcile_issue IS NOT NULL)"


def list_open(conn):
    """Outstanding (unpaid) invoices read in full and agreeing with NetSuite, oldest due first."""
    return _rows(conn.execute(
        f"SELECT {_LIST_COLUMNS} FROM invoices WHERE status = 'open' AND {_CLEAN} "
        "ORDER BY due_date IS NULL, due_date, invoice_date, id"))


def list_paid(conn):
    """Paid invoices, most recently paid first."""
    return _rows(conn.execute(
        f"SELECT {_LIST_COLUMNS} FROM invoices WHERE status = 'paid' AND {_CLEAN} "
        "ORDER BY paid_at DESC, id DESC"))


def _attention(conn, ignored):
    rows = _rows(conn.execute(
        "SELECT id, customer, invoice_number, invoice_date, due_date, amount, currency, review_reason, reconcile_issue, "
        f"source_link, pdf_file IS NOT NULL AS has_pdf FROM invoices WHERE {_FLAGGED} AND ignored = ? "
        "ORDER BY id DESC", (int(ignored),)))
    for row in rows:
        reasons = [row.pop("review_reason"), row.pop("reconcile_issue")]
        row["reason"] = "; ".join(r for r in reasons if r) or None
    return rows


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
    - `ignored` hides or restores a flagged invoice (missing fields or a NetSuite mismatch); only
      flagged ones can be ignored.
    """
    row = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
    if row is None:
        return False
    invoice = dict(row)
    edits = {f: changes[f] for f in EDITABLE if f in changes}
    if edits:
        invoice.update(edits)
        _recheck_missing(invoice)
        invoice["manually_edited"] = 1
    if "ignored" in changes:
        if changes["ignored"] and not (invoice["needs_review"] or invoice["reconcile_issue"]):
            raise ValueError("only invoices that need attention can be ignored")
        invoice["ignored"] = int(changes["ignored"])
    if "status" in changes:
        if invoice["needs_review"] or invoice["reconcile_issue"]:
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


# What NetSuite's invoice export says about an invoice. Terms and PO # come only from the PDF.
NETSUITE_FIELDS = ("customer", "invoice_date", "due_date", "amount", "currency", "memo")
NETSUITE_ONLY = ("subsidiary", "customer_raw", "amount_usd", "exchange_rate", "netsuite_status")


def save_netsuite_invoice(conn, invoice, *, now):
    """Store one invoice from NetSuite's invoice export; returns (id, status_changed). Does not commit.

    Matched by invoice number, so an invoice first seen as a PDF gains NetSuite's figures. A row
    someone fixed by hand keeps its fixed fields; otherwise NetSuite's values win wherever it has one.
    `status_changed` is True the first time NetSuite reports the invoice and whenever its status
    differs from the last export: only then does `reconcile_invoice` set the tracker's status, so a
    manual Mark paid sticks until NetSuite itself changes its mind.
    """
    netsuite = {f: invoice.get(f) for f in NETSUITE_ONLY} | {"netsuite_seen_at": now}
    existing = conn.execute("SELECT * FROM invoices WHERE invoice_number = ?", (invoice["invoice_number"],)).fetchone()
    if existing is None:
        row = {f: invoice.get(f) for f in NETSUITE_FIELDS} | {"invoice_number": invoice["invoice_number"]}
        row["currency"] = row["currency"] or "USD"
        _recheck_missing(row)
        row |= netsuite
        cursor = conn.execute(f"INSERT INTO invoices ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
                              tuple(row.values()))
        conn.execute("INSERT INTO status_history (invoice_id, status, changed_at, source) VALUES (?, 'open', ?, 'netsuite')",
                     (cursor.lastrowid, now))
        return cursor.lastrowid, True
    row = dict(existing)
    if not row["manually_edited"]:
        row |= {f: invoice[f] for f in NETSUITE_FIELDS if invoice.get(f) not in (None, "")}
        _recheck_missing(row)
    status_changed = row["netsuite_status"] != invoice.get("netsuite_status")
    row |= netsuite
    columns = [*NETSUITE_FIELDS, "needs_review", "review_reason", *netsuite]
    conn.execute(f"UPDATE invoices SET {', '.join(f'{c} = ?' for c in columns)} WHERE id = ?",
                 (*(row[c] for c in columns), row["id"]))
    return row["id"], status_changed


def save_application(conn, application):
    """Store one payment-history line; returns False when it was already stored. Does not commit."""
    cursor = conn.execute(
        "INSERT OR IGNORE INTO applications (invoice_number, document_number, kind, applied_on, amount_usd, currency, "
        "source) VALUES (:invoice_number, :document_number, :kind, :applied_on, :amount_usd, :currency, :source)",
        application)
    return cursor.rowcount == 1


def settlement(conn, invoice_number, amount_usd):
    """What has been applied to an invoice, in USD.

    `settled_on` is the date the balance last reached zero (None while any is left), so a
    revaluation booked before the payment doesn't count as the paid date.
    """
    rows = conn.execute("SELECT applied_on, amount_usd FROM applications WHERE invoice_number = ? "
                        "ORDER BY applied_on, id", (invoice_number,)).fetchall()
    applied, settled_on = 0.0, None
    for r in rows:
        applied += r["amount_usd"]
        settled = amount_usd is not None and abs(amount_usd - applied) <= SETTLED_TOLERANCE
        settled_on = r["applied_on"] if settled else None
    balance = round(amount_usd - applied, 2) if amount_usd is not None else None
    return {"count": len(rows), "applied_usd": round(applied, 2), "balance_usd": balance, "settled_on": settled_on,
            "last_applied_on": rows[-1]["applied_on"] if rows else None}


def _reconcile_issue(paid_in_netsuite, settled):
    balance = settled["balance_usd"]
    if balance is None:
        return None  # no amount: already flagged as a missing field
    if paid_in_netsuite and balance > SETTLED_TOLERANCE:
        if not settled["count"]:
            return "paid in full in NetSuite, but the payments export has nothing applied to it"
        return f"paid in full in NetSuite, but ${balance:,.2f} of it has no payment recorded"
    if not paid_in_netsuite and settled["count"] and abs(balance) <= SETTLED_TOLERANCE:
        return "the payments export covers it in full, but NetSuite still shows it open"
    if balance < -SETTLED_TOLERANCE:
        return f"payments exceed the invoice by ${-balance:,.2f}"
    return None


def reconcile_invoice(conn, invoice_id, *, apply_status, now):
    """Check an invoice's NetSuite status against its applications and record any mismatch.

    With `apply_status` the tracker's status follows NetSuite's, and a paid invoice is dated by when
    its payments settled it. Does not commit.
    """
    invoice = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
    if invoice["netsuite_status"] is None:
        return
    settled = settlement(conn, invoice["invoice_number"], invoice["amount_usd"])
    paid_in_netsuite = invoice["netsuite_status"] == "Paid In Full"
    status, paid_at = invoice["status"], invoice["paid_at"]
    if apply_status:
        status = "paid" if paid_in_netsuite else "open"
        paid_at = (settled["settled_on"] or settled["last_applied_on"]) if paid_in_netsuite else None
    elif status == "paid" and paid_at is None:
        paid_at = settled["settled_on"]
    if status != invoice["status"]:
        conn.execute("INSERT INTO status_history (invoice_id, status, changed_at, source) VALUES (?, ?, ?, 'netsuite')",
                     (invoice_id, status, now))
    conn.execute("UPDATE invoices SET status = ?, paid_at = ?, reconcile_issue = ? WHERE id = ?",
                 (status, paid_at, _reconcile_issue(paid_in_netsuite, settled), invoice_id))


def record_refresh(conn, finished_at):
    conn.execute("INSERT INTO refreshes (finished_at) VALUES (?)", (finished_at,))
    conn.commit()


def last_refresh(conn):
    row = conn.execute("SELECT MAX(finished_at) AS at FROM refreshes").fetchone()
    return row["at"]
