import { useState, type FormEvent } from 'react';
import { patchInvoice, type InvoiceFix } from './api';
import type { AttentionItem } from './types';

interface Props {
  item: AttentionItem;
  onSaved: () => void;
  onCancel: () => void;
}

const INPUT = 'mt-1 block w-full rounded-card border border-line bg-white px-2 py-1 text-[15px]';

/**
 * Fill in what the parser could not read. Saving confirms every value shown, so a value the
 * parser guessed is settled just by saving it.
 */
export default function FixInvoiceForm({ item, onSaved, onCancel }: Props) {
  const initial = {
    customer: item.customer === 'Unknown customer' ? '' : item.customer,
    invoice_number: item.invoice_number ?? '',
    invoice_date: item.invoice_date ?? '',
    due_date: item.due_date ?? '',
    amount: item.amount === null ? '' : String(item.amount),
  };
  const [values, setValues] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const anythingToSave = Object.values(values).some((v) => v.trim() !== '');
  const set = (key: keyof typeof initial) => (e: { target: { value: string } }) =>
    setValues({ ...values, [key]: e.target.value });

  async function submit(e: FormEvent) {
    e.preventDefault();
    const fix: InvoiceFix = {};
    for (const key of Object.keys(values) as (keyof typeof values)[]) {
      const value = values[key].trim();
      if (value === '') continue;
      if (key === 'amount') fix.amount = Number(value);
      else fix[key] = value;
    }
    if (fix.amount !== undefined && Number.isNaN(fix.amount)) {
      setError('Amount must be a number');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await patchInvoice(item.id, fix);
      onSaved();
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  }

  return (
    <form
      aria-label="Fix invoice"
      onSubmit={submit}
      className="mb-4 rounded-card border border-line bg-white p-4"
    >
      <h3 className="text-[13px] font-semibold uppercase tracking-[0.06em] text-muted">
        Fix invoice · {item.customer}
      </h3>
      <p className="mt-1 text-[14px] text-muted">
        Fill in what is missing. Saving confirms the values shown and keeps them when the PDF is imported again.
        {item.reason && <> Flagged: {item.reason}.</>}
      </p>
      <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <label className="text-[14px]">
          Customer
          <input className={INPUT} value={values.customer} onChange={set('customer')} />
        </label>
        <label className="text-[14px]">
          Invoice #
          <input className={INPUT} value={values.invoice_number} onChange={set('invoice_number')} />
        </label>
        <label className="text-[14px]">
          Amount
          <input
            className={INPUT}
            type="number"
            step="0.01"
            min="0"
            value={values.amount}
            onChange={set('amount')}
          />
        </label>
        <label className="text-[14px]">
          Invoice date
          <input className={INPUT} type="date" value={values.invoice_date} onChange={set('invoice_date')} />
        </label>
        <label className="text-[14px]">
          Due date (optional)
          <input className={INPUT} type="date" value={values.due_date} onChange={set('due_date')} />
        </label>
      </div>
      {error && (
        <p role="alert" className="mt-3 text-[14px] text-[#a61f14]">
          {error}
        </p>
      )}
      <div className="mt-4 flex gap-3">
        <button
          type="submit"
          disabled={!anythingToSave || saving}
          className="rounded-card bg-navy px-3 py-1 text-[14px] text-white disabled:opacity-40"
        >
          Save fix
        </button>
        <button type="button" onClick={onCancel} className="text-[14px] text-navy underline">
          Cancel
        </button>
      </div>
    </form>
  );
}
