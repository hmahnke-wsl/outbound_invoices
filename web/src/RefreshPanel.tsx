import type { IngestResult } from './types';

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** "Since last refresh": new invoices found, and how many PDFs need attention. */
export default function RefreshPanel({ result, onDismiss }: { result: IngestResult; onDismiss: () => void }) {
  const found = result.new_invoice_ids.length;
  const flagged = result.flagged;
  return (
    <section
      aria-label="Since last refresh"
      className="mb-4 flex items-start justify-between gap-4 rounded-card border border-line bg-[#f6f8fb] px-4 py-3 text-[14px] text-navy"
    >
      <div>
        <h2 className="mb-1 text-[13px] font-semibold uppercase tracking-[0.06em] text-muted">Since last refresh</h2>
        {found || flagged ? (
          <ul className="flex flex-wrap gap-x-6 gap-y-1">
            <li>{plural(found, 'new invoice')}</li>
            <li>{`${flagged} need${flagged === 1 ? 's' : ''} attention`}</li>
          </ul>
        ) : (
          <p>Nothing new</p>
        )}
      </div>
      <button type="button" aria-label="Dismiss" title="Dismiss" onClick={onDismiss} className="text-[15px] text-muted hover:text-navy">
        ✕
      </button>
    </section>
  );
}
