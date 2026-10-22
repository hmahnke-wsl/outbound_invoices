// Mirrors the response shapes in code/api.py; keep the two in step.

export interface Invoice {
  id: number;
  customer: string;
  invoice_number: string | null;
  invoice_date: string | null;
  terms: string | null;
  due_date: string | null;
  amount: number;
  currency: string;
  memo: string | null;
  po_number: string | null;
  status: 'open' | 'paid';
  /** The date the payment landed (YYYY-MM-DD); null while open. */
  paid_at: string | null;
  overdue: boolean;
  /** Days from the invoice date to payment, or to today while open. */
  days_open: number | null;
  source_link: string | null;
  has_pdf: boolean;
  /** When the invoice was first seen (ISO UTC). */
  sent_at: string | null;
}

export interface HistoryEntry {
  status: Invoice['status'];
  changed_at: string;
  source: 'import' | 'manual';
}

export interface AttentionItem {
  id: number;
  customer: string;
  invoice_number: string | null;
  invoice_date: string | null;
  due_date: string | null;
  amount: number | null;
  currency: string;
  reason: string | null;
  source_link: string | null;
  has_pdf: boolean;
}

export interface Money {
  currency: string;
  amount: number;
}

/** A count plus one amount per currency: money is never added across currencies. */
export interface Total {
  count: number;
  amounts: Money[];
}

export interface AverageDays {
  days: number | null;
  based_on: number;
}

export interface Health {
  status: 'good' | 'watch' | 'action' | null;
  reason: string | null;
}

/** Topline figures over all open invoices (not affected by search or tab). */
export interface Summary {
  outstanding: Total;
  overdue: Total;
  days_overdue: AverageDays;
  days_open: AverageDays;
  aging: (Total & { label: string })[];
  health: { overdue: Health; days_open: Health };
}

/** What one Refresh (an import) found. Mirrors IngestResult in api.py. */
export interface IngestResult {
  saved: number;
  flagged: number;
  new_invoice_ids: number[];
}
