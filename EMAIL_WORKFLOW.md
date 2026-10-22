# Outbound Invoices — Email Workflow Overview

**Status:** proposal, not yet set up. Open questions are listed at the end.

## Goal

Every invoice WSL sends to a customer should reach the tracker automatically, and so should every payment
against it, without anyone remembering to forward anything. Accounting then sees what's open, what's
paid, and how long each invoice has been open.

## How it works

```
NetSuite ──invoice email──▶ Customer
    │
    ├─BCC──────────────────▶ invoicing-outbound@worldsurfleague.com (Google Group)
    │                              │
    └─daily payments report─▶      │  delivers to members' inboxes
      (scheduled saved search)     ▼
                            Henry's Gmail
                              ├─ label "Outbound-Invoice"  (invoice PDFs)
                              └─ label "Outbound-Payments" (payments CSV)
                                     │
                                     ▼  Gmail API (read-only)
                              Outbound Invoices tracker
                              ├─ parses each invoice PDF → open invoice
                              └─ matches payments by invoice # → paid
```

This is the same pattern `invoicingpm@` uses for inbound invoices in `invoice_tracking`: a Google Group
delivers to members' own inboxes, a Gmail filter labels the mail, and the app reads the label.

## The pieces

### 1. Google Group: `invoicing-outbound@worldsurfleague.com`

- **Members:** Henry, plus anyone in accounting who wants copies.
- **Who can post:** must allow NetSuite's sending address (or anyone, with spam moderation off for it).
  Otherwise NetSuite's mail is held for moderation or bounced.
- **Delivery:** each member gets every message in their own inbox (not a collaborative inbox only).
- **Owner:** likely IT (see open questions).

### 2. NetSuite BCCs the group on every invoice email

- A NetSuite admin adds `invoicing-outbound@` as a BCC on the invoice email template or the default
  transaction email settings. It's set once and covers every invoice from then on.
- **Why not Gmail forwarding rules:** Gmail filters only act on mail a person *receives*, not mail they
  *send*. A forwarding rule can't copy invoices an accountant sends out, and relying on people to BCC
  by hand means missed invoices nobody notices.
- **Fallback:** if some invoices are sent from Gmail instead of NetSuite, the sender BCCs the group by hand.

### 3. NetSuite emails a daily payments report

- A scheduled NetSuite report (a "saved search") of customer payments applied to invoices, emailed daily
  as a CSV to `invoicing-outbound@`.
- Needed columns: invoice number, payment date, amount applied, currency.
- The tracker marks the matching invoice paid on that date. Partial payments stay open (to be designed
  once there's a real sample).
- The dashboard's manual **Mark paid** stays as a fallback for anything the report misses.

### 4. Gmail labels (Henry's inbox)

| Filter | Label |
|---|---|
| `to:invoicing-outbound@worldsurfleague.com has:attachment filename:pdf` | `Outbound-Invoice` |
| `to:invoicing-outbound@worldsurfleague.com` from NetSuite's report sender, subject matching the saved search | `Outbound-Payments` |

### 5. The tracker reads the labels

- Gmail sign-in as Henry, **read-only** access. This is the same setup `invoice_tracking` already uses, so
  its ingest code carries over almost unchanged.
- Each invoice PDF goes through the existing parser (`code/invoice_parser.py`). The invoice number dedupes
  repeats, and anything it can't read lands in **Needs attention**.
- The dashboard's **Refresh** button runs the pull. Today it re-imports `sample_docs/` instead.

## What changes for whom

| Who | One-time setup | Day to day |
|---|---|---|
| IT | Create the group; allow NetSuite to post | Nothing |
| NetSuite admin | Add the BCC; schedule the payments saved search | Nothing |
| Henry | Join the group; add two Gmail filters; sign the tracker in to Gmail once | Nothing |
| Accounting | Nothing | Use the dashboard; Mark paid only when the report misses one |

## Later: hosted version

Reading Henry's personal inbox ties the tracker to one person's account. Once accounting relies on it
day to day, move ingest to a dedicated mailbox (e.g. `ar-tracker@`) with its own Gmail sign-in. That's a
small IT request; nothing else in the workflow changes.

## Open questions

- [ ] Do invoices go out from NetSuite directly, or does someone download the PDF and email it from Gmail?
- [ ] Who is the NetSuite admin, and can they add the BCC and schedule the saved search?
- [ ] Does Henry create Google Groups, or does IT?
- [ ] What address does NetSuite send from (for the group's posting permission and the Gmail filter)?
- [ ] How are partial payments and credits recorded, and should the tracker show them?
- [ ] Does accounting want a weekly digest email in addition to the dashboard?

## Next build steps (once the above is set up)

1. Get one real BCC'd invoice email and one payments CSV into the labels.
2. Port Gmail ingest from `invoice_tracking/code/ingest.py` for the `Outbound-Invoice` label.
3. Write the payments CSV parser and invoice-number matching, with unmatched rows listed on the dashboard.
4. Point **Refresh** at Gmail instead of `sample_docs/`.
