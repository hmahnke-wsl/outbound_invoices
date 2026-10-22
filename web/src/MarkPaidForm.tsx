import { useState, type FormEvent } from 'react';
import { markPaid } from './api';
import { money, todayIso } from './format';
import type { Invoice } from './types';

/** Record the date a customer's payment landed. Defaults to today. */
export default function MarkPaidForm({ invoice, onSaved, onCancel }: { invoice: Invoice; onSaved: () => void; onCancel: () => void }) {
  const [paidAt, setPaidAt] = useState(todayIso());
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await markPaid(invoice.id, paidAt);
      onSaved();
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  }

  return (
    <form aria-label="Mark paid" onSubmit={submit} className="mb-4 rounded-card border border-line bg-white p-4">
      <h3 className="text-[13px] font-semibold uppercase tracking-[0.06em] text-muted">
        Mark paid · {invoice.customer} {invoice.invoice_number}
      </h3>
      <p className="mt-1 text-[14px] text-muted">{money(invoice.amount, invoice.currency)} — the date the payment landed.</p>
      <label className="mt-3 block max-w-xs text-[14px]">
        Paid on
        <input
          type="date"
          required
          max={todayIso()}
          value={paidAt}
          onChange={(e) => setPaidAt(e.target.value)}
          className="mt-1 block w-full rounded-card border border-line bg-white px-2 py-1 text-[15px]"
        />
      </label>
      {error && (
        <p role="alert" className="mt-3 text-[14px] text-[#a61f14]">
          {error}
        </p>
      )}
      <div className="mt-4 flex gap-3">
        <button type="submit" disabled={!paidAt || saving} className="rounded-card bg-navy px-3 py-1 text-[14px] text-white disabled:opacity-40">
          Mark paid
        </button>
        <button type="button" onClick={onCancel} className="text-[14px] text-navy underline">
          Cancel
        </button>
      </div>
    </form>
  );
}
