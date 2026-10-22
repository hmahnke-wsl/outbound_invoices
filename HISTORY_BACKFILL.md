# Outbound Invoices — History Backfill Scope

**Status:** steps 1–3 built (`code/import_netsuite.py`); the dashboard changes (step 4) are not. Based on the two NetSuite exports in `sample_docs/` (pulled 2026-10-22).

## Goal

Rebuild the tracker's database from NetSuite's own records instead of only the PDFs we've happened to see:
every invoice live since 1 Jan 2026, what was applied against it, when, and what's still open.

## Start date: 1 Jan 2026

The payment export only has data from 2026-01-01, so that's where history starts. What gets imported:

| Set | Count | Why |
|---|---|---|
| Invoices dated 2026-01-01 on | 204 (156 paid, 48 open) | the period we have payments for |
| 2025 invoices still open on 1 Jan 2026 | 53 (31 since paid, 22 still open) | open now, or have a 2026 payment row; they belong in 2026 aging |
| Other 2025 invoices | 274 | paid during 2025; skipped |

A 2025 invoice with no 2026 payment row and `Paid In Full` status was paid in 2025, so the rule is exact
for subsidiary 210. The exception is the 9 paid 2025 merchandise (315) invoices: with no 315 payments in
the export, it can't be told whether they were paid in 2025 or 2026. They're skipped until gap 2 is fixed. The same two
exports, scheduled daily, then become the ongoing feed (step 3 of `EMAIL_WORKFLOW.md`).

## What's in the files

### Invoice History (`JEDetailROReceivablesCFCLEANHQ`)

531 rows, one per invoice, INV4750–INV7074, invoice dates 2025-01-01 → 2026-10-19. Clean header row.

| Column | Use |
|---|---|
| Document Number | invoice # (unique, all `INV…`); the join key |
| Date / Due Date/Receive By | invoice date / due date (10 blank, 50 due same day) |
| Status | `Open` (70) or `Paid In Full` (461): NetSuite's current status, as of the export |
| Name | customer, with NetSuite suffixes (`_AU`, `_EUR`, `_210`, `- 210`): 121 names |
| Subsidiary | `210 - WSL, LLC` (504) or `315 - WSL Merchandise` (27) |
| Amount (Debit) (Foreign Currency) + Currency | invoice amount in its own currency (USD 473, AUD 29, EUR 23, GBP 4, ZAR 1, BRL 1) |
| Amount (Debit), Exchange Rate | USD equivalent at the invoice-date rate |
| Memo | description (20 blank) |
| Type, Account Type, Period, Credit columns | constant / empty; drop |

### Payment History (`Custom A/R Payment History`)

188 rows, one per **application** of a document to an invoice. 6 title rows above the header, plus an
"Amount Open" total row at the bottom to skip.

| Column | Use |
|---|---|
| Transaction Number | the invoice it was applied to (all match the invoice file) |
| Document Number | the applying document: `PYMT…`, `CM…`, `CR…`, `JE…` |
| Payment Type | `Payment` 163, `Credit Memo` 16, `Currency Revaluation` 7, `Journal` 2 |
| Date | application date |
| Amount | **USD**, negative = reduces the balance (reval can be ±) |
| Amount (Foreign Currency) | **the invoice's total, not the amount applied** (matches the invoice amount on every row) |
| Currency: Currency Symbol | currency of the applying document |
| Entity, Transaction | customer / display text; redundant |
| Payment Method, Check Number | always blank |

## How the two fit together

Summing `Amount` (USD) per invoice and adding the invoice's USD amount nets to zero for 174 of the 177
invoices that have payment rows. The 3 that don't are genuinely part-paid and still `Open` in NetSuite
(INV4983 $50k left, INV5685 $41.2k left, INV5872 $65 short). So the model is sound: **invoice balance =
invoice amount − Σ applications**, reconciled in USD.

## Gaps to settle before trusting it

1. **Payments only start 2026-01-01**, though the report header says 1 Jan 2025. Settled by starting the
   history at 1 Jan 2026 (above).
2. **No WSL Merchandise (315) payments at all.** All payment rows are subsidiary 210. 11 merch invoices from
   2026 (Jack's Surfboards, Huntington Surf & Sport) are `Paid In Full` with nothing applied. Likely a
   subsidiary filter on the saved search.
3. **Applied amounts in foreign currency aren't exported.** Fine for full payments; a part payment on a
   EUR/AUD invoice can only be shown in USD unless the search adds the applied foreign amount.
4. **Credit memos aren't cash.** 16 invoices were settled (fully or partly) by a credit memo, e.g. Team One
   INV5881/5882 at $1.95M each, Surf Abu Dhabi INV5680–82. These are cancellations/discounts, not
   collections, and should show as "credited", not "paid".
5. **Small write-offs** come through as `Journal` lines ($10, $25 short-pays on INV6552, INV6656).
6. **3 invoices have no amount** (INV6693, INV6694, INV7054, OMD Digital): $0 invoices or a bad export.
7. One payment document can cover several invoices (11 cases, e.g. PYMT7168 → INV6780 + INV6800), and one
   invoice can have several payments (INV6183 paid in two halves). Applications need their own table.
8. Customer names need normalising (`OMD Digital_AU`, `Vissla_210`, `Montres TUDOR SA_EUR`); the PDF
   parser already strips the currency suffix, the subsidiary suffixes are new.

## Schema

Built in `code/db.py`; existing databases are upgraded on open. The current `invoices` columns and API
stay as they are.

- `invoices` gains `subsidiary` ('210' / '315'), `customer_raw` (NetSuite's name before normalising),
  `amount_usd`, `exchange_rate`, `netsuite_status` ('Open' / 'Paid In Full', as last exported),
  `netsuite_seen_at`, and `reconcile_issue` (why NetSuite and the payments disagree; NULL when they agree).
- `applications`: one row per Payment History line, with `invoice_number`, `document_number`
  (PYMT6397, CM515, CR2216, JE45846), `kind` (payment / credit_memo / revaluation / journal), `applied_on`,
  `amount_usd` (positive reduces the balance), `currency` and `source` (the export file). Keyed by invoice
  number rather than id, so a payment can arrive before its invoice. Re-importing a line is a no-op.
- `status_history.source` gains `'netsuite'`, shown as "NetSuite" in the invoice's history.

How status is set on each import:

- Balance = `amount_usd` − Σ applications. `paid_at` is the date it last reached zero.
- The tracker's open/paid follows NetSuite's status only when NetSuite's status changes (or the first time
  it sees the invoice), so a manual **Mark paid** sticks until NetSuite changes its mind.
- Credit-memo settlements count as paid for now; the `kind` is kept for a "credited" view later.
- NetSuite's figures fill in an invoice first imported as a PDF; terms and PO # stay from the PDF, and a
  field someone fixed by hand is never overwritten.

## Build steps

Steps 1–3 are done: `uv run python code/import_netsuite.py` (defaults to the newest exports in
`sample_docs/`). On the 22 Oct exports: 257 invoices imported, 274 skipped, 188 payment lines, 13 flagged.

1. ✅ `code/import_netsuite.py`: read both xlsx (or CSV), skip the title/footer rows, map columns,
   upsert invoices by invoice #, insert applications idempotently, recompute status.
2. ✅ Customer normaliser: strip `_AU/_EUR/_USD/_AUD/_210/_315/ - 210` suffixes; keep the raw name.
3. ✅ Reconciliation check run on every import: flag any invoice where NetSuite says `Paid In Full` but the
   balance isn't 0 (or the reverse) into **Needs attention** with the reason. Today that would flag 13
   invoices from 2026 (10 merchandise invoices with no payments, plus the 3 with no amount).
4. Dashboard: part-paid amount and balance on the row, a Credited tab or badge, applications in the
   invoice detail history.
5. ✅ Tests: `tests/test_import_netsuite.py` builds small workbooks shaped like NetSuite's exports from
   lines modelled on the real ones.

Still to do: step 4, and pointing the dashboard's **Refresh** at the exports (today it's the CLI only).

## Questions for accounting

- [ ] Can the payment saved search include subsidiary 315?
- [ ] Can it add the applied amount in the invoice's currency?
- [ ] Should credit-memo settlements count as "paid" in the summary figures or sit apart?
- [ ] Are INV6693 / INV6694 / INV7054 really $0?
- [ ] Should write-offs under some threshold (e.g. $50) count as paid in full?
