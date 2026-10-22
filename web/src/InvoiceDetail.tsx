import { useEffect, useState } from 'react';
import { fetchHistory } from './api';
import { money, when } from './format';
import type { HistoryEntry, Invoice } from './types';

const STATUS_LABELS: Record<Invoice['status'], string> = { open: 'Open', paid: 'Paid' };

/** The invoice's details the table leaves out (memo, terms, PO), and its open/paid history. */
export default function InvoiceDetail({ invoice, onClose }: { invoice: Invoice; onClose: () => void }) {
  const [history, setHistory] = useState<HistoryEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchHistory(invoice.id)
      .then(setHistory)
      .catch((e: Error) => setError(e.message));
  }, [invoice.id]);

  const facts: [string, string | null][] = [
    ['Memo', invoice.memo],
    ['Amount', money(invoice.amount, invoice.currency)],
    ['Invoice date', invoice.invoice_date],
    ['Terms', invoice.terms],
    ['Due', invoice.due_date],
    ['PO #', invoice.po_number],
    ['Paid', invoice.paid_at],
  ];

  return (
    <section aria-label="Invoice detail" className="mb-6 rounded-card border border-line bg-white p-4">
      <div className="flex items-start justify-between">
        <h2 className="text-[13px] font-semibold uppercase tracking-[0.06em] text-muted">
          {invoice.customer} · {invoice.invoice_number}
        </h2>
        <button type="button" aria-label="Close" onClick={onClose} className="text-[15px] text-muted hover:text-navy">
          ✕
        </button>
      </div>
      <dl className="mt-2 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-[15px]">
        {facts
          .filter(([, value]) => value)
          .map(([label, value]) => (
            <div key={label} className="contents">
              <dt className="text-muted">{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
      </dl>
      <h3 className="mt-4 text-[13px] font-semibold uppercase tracking-[0.06em] text-muted">History</h3>
      {error && <p className="mt-2 text-[14px] text-[#a61f14]">{error}</p>}
      {history && (
        <ul className="mt-1">
          {history.map((entry, i) => (
            <li key={i} className="flex gap-3 border-b border-line py-2 text-[15px]">
              <span className="font-semibold">{STATUS_LABELS[entry.status]}</span>
              <span className="text-muted">{when(entry.changed_at)}</span>
              <span className="text-muted">{entry.source === 'import' ? 'Imported' : 'Manual'}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
