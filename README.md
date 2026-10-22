# Outbound Invoices

Tracks the invoices WSL sends to customers: open or paid, days open, overdue, and aging. Built on the same
stack and look as `../invoice_tracking` (FastAPI + SQLite, React dashboard on `@wsl/ui`, the same LDAP login gate).

## Layout

| Path | What it is |
|---|---|
| `code/invoice_parser.py` | Reads WSL's NetSuite invoice PDF: customer, invoice #, invoice date, terms, due date, amount + currency, memo, PO # |
| `code/import_pdfs.py` | Imports every PDF in a folder (default `sample_docs/`, or `INBOX_DIR`). Stand-in for Gmail ingest |
| `code/import_netsuite.py` | Imports NetSuite's Invoice History and Payment History exports from 1 Jan 2026 (see `HISTORY_BACKFILL.md`) |
| `code/db.py`, `code/api.py`, `code/summary.py`, `code/auth.py` | SQLite, the JSON API, summary figures, LDAP login |
| `web/` | React dashboard: Outstanding / Overdue / Paid tabs, summary strip, Needs attention, Mark paid |
| `tests/` | `pytest`; `tests/fixtures/` holds the sample's text with WSL's bank details redacted |
| `sample_docs/`, `attachments/` | Invoice PDFs. Git-ignored: they carry WSL's remit-to bank details |

## How it works

- **Open → Paid.** Every imported invoice starts open. Someone in accounting marks it paid from the row's ⋯ menu,
  with the date the payment landed ("Mark unpaid" on the Paid tab undoes it). Each change is kept in the history.
- **Days open** runs from the invoice date to today, or to the paid date once paid.
- **Overdue** is open and past its due date. An invoice with no due date is never overdue.
- **Currencies are never added together.** Totals show one figure per currency (e.g. `$42,000 + €287,500`).
- **Needs attention.** A PDF missing a customer, invoice #, invoice date or amount (or not on WSL's template) is
  listed there with Fix and Ignore actions instead of being guessed. A fix survives re-imports.
- **Re-imports don't duplicate.** The same invoice number updates the existing row.

## Run

Double-click `dashboard.command` (API on 5040, web on 3040; see `ports.env` and `../PORTS.md`).

Double-click `import-netsuite.command` to import the newest NetSuite exports in `sample_docs/` (it backs up
`invoices.db` first). The same from a terminal:

```bash
uv run python code/import_netsuite.py
```

```bash
uv run python code/import_pdfs.py
```

```bash
uv run pytest
```

```bash
cd web && npm test
```

First-time setup: `uv sync` here, then `cd web && npm install` (needs `../shared_ui` installed).

## Not built yet

- Email forwarding / Gmail ingest. The dashboard's Refresh currently re-imports `sample_docs/`.
- Refresh doesn't run the NetSuite import yet; run `import-netsuite.command` after dropping new exports in `sample_docs/`.
- Health thresholds in `code/summary.py` (overdue %, days open 30/60) are placeholders for accounting to set.
