import { useEffect, useState } from 'react';
import { DataTable, type Column } from '@wsl/ui';
import ActionsMenu from './ActionsMenu';
import { fetchPaid, markOpen } from './api';
import { money } from './format';
import InvoiceDetail from './InvoiceDetail';
import { matchesSearch } from './search';
import { sourceLinks } from './SourceLinks';
import type { Invoice } from './types';

const buildColumns = (open: (invoice: Invoice) => void, reopen: (invoice: Invoice) => void): Column<Invoice>[] => [
  {
    header: 'Customer',
    className: 'min-w-[10rem]',
    accessor: (i) => (
      <button type="button" className="text-left text-navy underline-offset-2 hover:underline" onClick={() => open(i)}>
        {i.customer}
      </button>
    ),
  },
  { header: 'Invoice #', accessor: (i) => i.invoice_number ?? '', className: 'whitespace-nowrap' },
  { header: 'Memo', accessor: (i) => i.memo ?? '', className: 'min-w-[12rem]' },
  { header: 'Amount', accessor: (i) => money(i.amount, i.currency), align: 'right' },
  { header: 'Invoice date', accessor: (i) => i.invoice_date ?? '', className: 'whitespace-nowrap' },
  { header: 'Due', accessor: (i) => i.due_date ?? '', className: 'whitespace-nowrap' },
  { header: 'Paid', accessor: (i) => i.paid_at ?? '', className: 'whitespace-nowrap' },
  { header: 'Days to pay', accessor: (i) => i.days_open ?? '', align: 'right' },
  { header: 'Source', accessor: sourceLinks },
  {
    header: '',
    accessor: (i) => (
      <ActionsMenu
        label={`Actions for ${i.customer} ${i.invoice_number ?? ''}`.trim()}
        items={[{ label: 'Mark unpaid', onSelect: () => reopen(i) }]}
      />
    ),
  },
];

/** Paid invoices, most recently paid first. */
export default function PaidPage({ query = '', onChanged }: { query?: string; onChanged: () => void }) {
  const [invoices, setInvoices] = useState<Invoice[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Invoice | null>(null);

  const load = () =>
    fetchPaid()
      .then(setInvoices)
      .catch((e: Error) => setError(e.message));
  useEffect(() => {
    load();
  }, []);

  const reopen = async (invoice: Invoice) => {
    try {
      await markOpen(invoice.id);
      if (selected?.id === invoice.id) setSelected(null);
      load();
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const shown = invoices?.filter((i) => matchesSearch(i, query)) ?? null;

  return (
    <section aria-label="Paid invoices">
      {error && (
        <div role="alert" className="mb-4 rounded-card border border-[#c8372b] bg-[#fbe6e3] p-4 text-[#a61f14]">
          {error}
        </div>
      )}
      {selected && <InvoiceDetail key={selected.id} invoice={selected} onClose={() => setSelected(null)} />}
      {invoices && invoices.length === 0 && <p className="text-muted py-10 text-center">No paid invoices yet</p>}
      {invoices && invoices.length > 0 && shown?.length === 0 && (
        <p className="text-muted py-10 text-center">{`No paid invoices match "${query.trim()}"`}</p>
      )}
      {shown && shown.length > 0 && (
        <DataTable columns={buildColumns(setSelected, reopen)} data={shown} keyExtractor={(i) => i.id} />
      )}
    </section>
  );
}
