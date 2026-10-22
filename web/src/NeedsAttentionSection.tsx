import { useState } from 'react';
import { DataTable, type Column } from '@wsl/ui';
import { setIgnored } from './api';
import FixInvoiceForm from './FixInvoiceForm';
import { money } from './format';
import { RefreshBadge } from './RefreshBadge';
import { sourceLinks } from './SourceLinks';
import type { AttentionItem } from './types';

const buildColumns = (
  fix: (item: AttentionItem) => void,
  ignore: (item: AttentionItem) => void,
): Column<AttentionItem>[] => [
  {
    header: 'Customer',
    className: 'min-w-[11rem]',
    accessor: (i) => (
      <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <RefreshBadge id={i.id} />
        {i.customer}
      </span>
    ),
  },
  { header: 'Invoice #', accessor: (i) => i.invoice_number ?? '', className: 'whitespace-nowrap' },
  { header: 'Amount', accessor: (i) => (i.amount === null ? 'Unknown' : money(i.amount, i.currency)), align: 'right' },
  { header: 'Invoice date', accessor: (i) => i.invoice_date ?? '', className: 'whitespace-nowrap' },
  { header: 'Due', accessor: (i) => i.due_date ?? '', className: 'whitespace-nowrap' },
  { header: 'Why flagged', accessor: (i) => i.reason ?? '', className: 'min-w-[14rem]' },
  { header: 'Source', accessor: sourceLinks },
  {
    header: 'Actions',
    className: 'whitespace-nowrap',
    accessor: (i) => (
      <span className="flex gap-3">
        <button type="button" className="text-navy underline" onClick={() => fix(i)}>
          Fix
        </button>
        <button type="button" className="text-navy underline" onClick={() => ignore(i)}>
          Ignore
        </button>
      </span>
    ),
  },
];

const buildIgnoredColumns = (restore: (item: AttentionItem) => void): Column<AttentionItem>[] => [
  { header: 'Customer', accessor: (i) => i.customer, className: 'min-w-[11rem]' },
  { header: 'Invoice #', accessor: (i) => i.invoice_number ?? '', className: 'whitespace-nowrap' },
  { header: 'Amount', accessor: (i) => (i.amount === null ? 'Unknown' : money(i.amount, i.currency)), align: 'right' },
  { header: 'Why flagged', accessor: (i) => i.reason ?? '', className: 'min-w-[14rem]' },
  { header: 'Source', accessor: sourceLinks },
  {
    header: 'Restore',
    className: 'whitespace-nowrap',
    accessor: (i) => (
      <button type="button" className="text-navy underline" onClick={() => restore(i)}>
        Restore
      </button>
    ),
  },
];

interface Props {
  items: AttentionItem[] | null;
  /** Flagged invoices the user chose to hide; they can be restored. */
  ignored: AttentionItem[] | null;
  error: string | null;
  /** Called after a fix, ignore or restore, so the lists can be reloaded. */
  onChanged: () => void;
}

export default function NeedsAttentionSection({ items, ignored, error, onChanged }: Props) {
  const [fixing, setFixing] = useState<AttentionItem | null>(null);
  const [showIgnored, setShowIgnored] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  async function change(item: AttentionItem, hide: boolean) {
    setActionError(null);
    try {
      await setIgnored(item.id, hide);
      if (hide && fixing?.id === item.id) setFixing(null);
      onChanged();
    } catch (e) {
      setActionError((e as Error).message);
    }
  }

  const columns = buildColumns(setFixing, (item) => change(item, true));
  const ignoredColumns = buildIgnoredColumns((item) => change(item, false));
  return (
    <section aria-label="Needs attention" className="mt-8">
      <h2 className="mb-2 flex items-center gap-2 text-[13px] font-semibold uppercase tracking-[0.06em] text-muted">
        Needs attention
        {items && items.length > 0 && (
          <span className="rounded-chip bg-[#fdf1d4] px-2 text-[12px] text-[#7a4f00]">{items.length}</span>
        )}
      </h2>
      {error && <p className="text-[14px] text-[#a61f14]">{error}</p>}
      {actionError && (
        <p role="alert" className="mb-2 text-[14px] text-[#a61f14]">
          {actionError}
        </p>
      )}
      {fixing && (
        <FixInvoiceForm
          key={fixing.id}
          item={fixing}
          onCancel={() => setFixing(null)}
          onSaved={() => {
            setFixing(null);
            onChanged();
          }}
        />
      )}
      {items && items.length === 0 && <p className="text-[15px] text-muted">Nothing needs attention</p>}
      {items && items.length > 0 && (
        <DataTable columns={columns} data={items} keyExtractor={(i) => i.id} />
      )}
      {ignored && ignored.length > 0 && (
        <div className="mt-4">
          <button
            type="button"
            aria-expanded={showIgnored}
            onClick={() => setShowIgnored(!showIgnored)}
            className="text-[13px] text-navy underline"
          >
            Ignored ({ignored.length})
          </button>
          {showIgnored && (
            <div className="mt-2" role="group" aria-label="Ignored invoices">
              <DataTable columns={ignoredColumns} data={ignored} keyExtractor={(i) => i.id} />
            </div>
          )}
        </div>
      )}
    </section>
  );
}
