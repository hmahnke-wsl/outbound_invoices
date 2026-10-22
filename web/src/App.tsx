import { useEffect, useState } from 'react';
import { DataTable, StatusChip, type Column } from '@wsl/ui';
import ActionsMenu from './ActionsMenu';
import { useAuth } from './AuthGate';
import { fetchIgnored, fetchInvoices, fetchNeedsAttention, fetchSummary } from './api';
import { money } from './format';
import Header from './Header';
import InvoiceDetail from './InvoiceDetail';
import MarkPaidForm from './MarkPaidForm';
import NeedsAttentionSection from './NeedsAttentionSection';
import PaidPage from './PaidPage';
import { LastRefresh, RefreshBadge } from './RefreshBadge';
import RefreshButton from './RefreshButton';
import RefreshPanel from './RefreshPanel';
import { matchesSearch } from './search';
import { sourceLinks } from './SourceLinks';
import SummaryStrip from './SummaryStrip';
import { parsePage, writePage, type Page } from './view';
import type { AttentionItem, IngestResult, Invoice, Summary } from './types';

const statusChip = (invoice: Invoice) =>
  invoice.overdue ? <StatusChip status="behind" text="Overdue" /> : <StatusChip status="none" text="Not due" />;

const buildColumns = (open: (invoice: Invoice) => void, pay: (invoice: Invoice) => void): Column<Invoice>[] => [
  { header: '', accessor: (i) => <RefreshBadge id={i.id} /> },
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
  { header: 'Days open', accessor: (i) => i.days_open ?? '', align: 'right' },
  { header: 'Status', accessor: statusChip },
  { header: 'Source', accessor: sourceLinks },
  {
    // No header: the row's ⋯ button names itself ("Actions for <customer> <invoice #>").
    header: '',
    className: 'whitespace-nowrap',
    accessor: (i) => (
      <ActionsMenu
        label={`Actions for ${i.customer} ${i.invoice_number ?? ''}`.trim()}
        items={[{ label: 'Mark paid…', onSelect: () => pay(i) }]}
      />
    ),
  },
];

const INVOICE_TABS: { page: Page; label: string; includes: (invoice: Invoice) => boolean }[] = [
  { page: 'outstanding', label: 'Outstanding', includes: () => true },
  { page: 'overdue', label: 'Overdue', includes: (i) => i.overdue },
];

export default function App() {
  const { user, signOut } = useAuth();
  const [page, setPage] = useState<Page>(() => parsePage(window.location.hash));
  const [invoices, setInvoices] = useState<Invoice[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attention, setAttention] = useState<AttentionItem[] | null>(null);
  const [attentionError, setAttentionError] = useState<string | null>(null);
  const [ignored, setIgnoredItems] = useState<AttentionItem[] | null>(null);
  const [selected, setSelected] = useState<Invoice | null>(null);
  const [paying, setPaying] = useState<Invoice | null>(null);
  const [query, setQuery] = useState('');
  const [summary, setSummary] = useState<Summary | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [refreshes, setRefreshes] = useState(0); // bumped after a refresh so the Paid page reloads too
  // What the last Refresh in this tab found; kept in memory only, so a reload clears it.
  const [lastRefresh, setLastRefresh] = useState<IngestResult | null>(null);
  const [panelOpen, setPanelOpen] = useState(false);

  const loadInvoices = () => {
    fetchInvoices()
      .then(setInvoices)
      .catch((e: Error) => setError(e.message));
    fetchNeedsAttention()
      .then(setAttention)
      .catch((e: Error) => setAttentionError(e.message));
    fetchIgnored()
      .then(setIgnoredItems)
      .catch((e: Error) => setAttentionError(e.message));
  };

  useEffect(loadInvoices, []);

  // Reloaded whenever the invoices change (a refresh, a fix, a payment).
  useEffect(() => {
    let current = true;
    fetchSummary()
      .then((s) => current && setSummary(s))
      .catch((e: Error) => current && setSummaryError(e.message));
    return () => {
      current = false;
    };
  }, [invoices]);

  const reloadAll = () => {
    setError(null);
    setAttentionError(null);
    setSummaryError(null);
    loadInvoices();
    setRefreshes((n) => n + 1);
  };

  const refreshed = (result: IngestResult) => {
    setLastRefresh(result);
    setPanelOpen(true);
    reloadAll();
  };

  // The address bar keeps the page, so a reload or the back button lands on the same view.
  useEffect(() => {
    const sync = () => setPage(parsePage(window.location.hash));
    window.addEventListener('hashchange', sync);
    return () => window.removeEventListener('hashchange', sync);
  }, []);

  const go = (next: Page) => {
    window.location.hash = writePage(next);
    setPage(next);
  };

  const searched = invoices?.filter((i) => matchesSearch(i, query)) ?? null;
  const invoiceTab = INVOICE_TABS.find((t) => t.page === page);
  const shown = invoiceTab && searched ? searched.filter(invoiceTab.includes) : null;
  const tabs = [
    ...INVOICE_TABS.map(({ page, label, includes }) => ({ page, label, count: searched?.filter(includes).length })),
    { page: 'paid' as Page, label: 'Paid', count: undefined },
  ];

  return (
    <LastRefresh.Provider value={lastRefresh}>
      <Header user={user} onSignOut={signOut} />
      <main className="mx-auto max-w-[100rem] p-6">
        <h1 className="mb-4 text-[22px] font-bold text-navy">Outbound invoices</h1>
        <div className="mb-4 flex items-end justify-between gap-6 border-b border-line">
          <nav aria-label="Pages" className="flex gap-6">
            {tabs.map(({ page: tab, label, count }) => (
              <button
                key={tab}
                type="button"
                aria-current={page === tab ? 'page' : undefined}
                onClick={() => go(tab)}
                className={`-mb-px flex items-center gap-1.5 border-b-2 pb-2 text-[14px] font-semibold ${
                  page === tab ? 'border-navy text-navy' : 'border-transparent text-muted hover:text-navy'
                }`}
              >
                {label}
                {count !== undefined && (
                  <span aria-hidden="true" className="rounded-chip bg-[#eef1f5] px-1.5 text-[12px] font-normal">
                    {count}
                  </span>
                )}
              </button>
            ))}
          </nav>
          <div className="pb-2">
            <RefreshButton onRefreshed={refreshed} />
          </div>
        </div>
        {lastRefresh && panelOpen && <RefreshPanel result={lastRefresh} onDismiss={() => setPanelOpen(false)} />}
        <SummaryStrip summary={summary} error={summaryError} />
        <div className="mb-6 flex items-center gap-4">
          <input
            type="search"
            aria-label="Search by customer, invoice # or memo"
            placeholder="Search by customer, invoice # or memo"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="w-full max-w-sm rounded-card border border-line px-3 py-2 text-[14px]"
          />
        </div>
        {page === 'paid' && <PaidPage key={refreshes} query={query} onChanged={reloadAll} />}
        {invoiceTab && (
          <>
            {error && (
              <div role="alert" className="mb-4 rounded-card border border-[#c8372b] bg-[#fbe6e3] p-4 text-[#a61f14]">
                {error}
              </div>
            )}
            {paying && (
              <MarkPaidForm
                key={paying.id}
                invoice={paying}
                onCancel={() => setPaying(null)}
                onSaved={() => {
                  if (selected?.id === paying.id) setSelected(null);
                  setPaying(null);
                  reloadAll();
                }}
              />
            )}
            {selected && <InvoiceDetail key={selected.id} invoice={selected} onClose={() => setSelected(null)} />}
            {shown && shown.length === 0 && (
              <p className="text-muted py-10 text-center">
                {`No ${invoiceTab.label.toLowerCase()} invoices${query.trim() ? ` match "${query.trim()}"` : ''}`}
              </p>
            )}
            {shown && shown.length > 0 && (
              <DataTable columns={buildColumns(setSelected, setPaying)} data={shown} keyExtractor={(i) => i.id} />
            )}
            {page === 'outstanding' && (
              <NeedsAttentionSection items={attention} ignored={ignored} error={attentionError} onChanged={loadInvoices} />
            )}
          </>
        )}
      </main>
    </LastRefresh.Provider>
  );
}
