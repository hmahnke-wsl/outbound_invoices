import { MetricCard } from '@wsl/ui';
import { wholeMoney } from './format';
import type { Health, Money, Summary, Total } from './types';

const count = (t: Total) => `${t.count} invoice${t.count === 1 ? '' : 's'}`;
const pct = (part: number, whole: number) => (whole ? Math.round((part / whole) * 100) : 0);
const days = (d: number | null) => (d === null ? '—' : `${Math.round(d)} days`);

// Card border, chip tint and chip text per health status, from the dashboard's chip palette.
const HEALTH = {
  good: { label: 'Healthy', border: 'border-t-[#2f8a45]', dot: 'bg-[#2f8a45]', chip: 'bg-[#e3f1e6] text-[#1f5c2e]' },
  watch: { label: 'Watch', border: 'border-t-[#d99a00]', dot: 'bg-[#d99a00]', chip: 'bg-[#fdf1d4] text-[#7a4f00]' },
  action: { label: 'Action', border: 'border-t-[#c8372b]', dot: 'bg-[#c8372b]', chip: 'bg-[#fbe6e3] text-[#a61f14]' },
};

/** Props that color a metric card's top border and add a status chip for its health; none without a status. */
function rated({ status, reason }: Health) {
  if (!status) return {};
  const style = HEALTH[status];
  return {
    topBorder: 'none' as const,
    className: `border-t-4 ${style.border}`,
    badge: (
      <span title={reason ?? undefined} className={`inline-flex items-center gap-1 rounded-chip px-2 text-[12px] ${style.chip}`}>
        <span aria-hidden className={`h-2 w-2 rounded-full ${style.dot}`} />
        {style.label}
      </span>
    ),
  };
}

/** The first currency large, any others on a smaller line below (they are never added together). */
function Amounts({ list }: { list: Money[] }) {
  if (!list.length) return <>None</>;
  const [first, ...rest] = list;
  return (
    <>
      {wholeMoney(first)}
      {rest.length > 0 && <div className="mt-1 text-[18px] font-semibold">{rest.map((m) => `+ ${wholeMoney(m)}`).join('  ')}</div>}
    </>
  );
}

/** Topline figures and an aging breakdown over every open invoice. */
export default function SummaryStrip({ summary, error }: { summary: Summary | null; error: string | null }) {
  if (error) return <p className="mb-6 text-[14px] text-[#a61f14]">{error}</p>;
  if (!summary) return null;
  const { outstanding, overdue, days_overdue: late, days_open: open } = summary;
  const most = Math.max(...summary.aging.map((b) => b.count), 0);

  return (
    <section aria-label="Summary" className="mb-6">
      <div className="flex flex-wrap gap-4">
        <MetricCard title="Outstanding" value={<Amounts list={outstanding.amounts} />} subtitle={count(outstanding)} />
        <MetricCard
          title="Overdue"
          value={<Amounts list={overdue.amounts} />}
          {...rated(summary.health.overdue)}
          subtitle={[
            `${overdue.count} of ${count(outstanding)} (${pct(overdue.count, outstanding.count)}%)`,
            ...(late.days === null ? [] : [`avg ${days(late.days)} past due`]),
          ].join(' · ')}
        />
        <MetricCard
          title="Avg days open"
          value={days(open.days)}
          {...rated(summary.health.days_open)}
          subtitle={`since invoice date (${open.based_on} of ${outstanding.count})`}
        />
      </div>
      <table className="mt-4 w-full max-w-2xl text-[14px]">
        <caption className="mb-2 text-left text-[13px] font-semibold uppercase tracking-[0.06em] text-muted">
          Aging (days past due)
        </caption>
        <tbody>
          {summary.aging.map((b) => (
            <tr key={b.label}>
              <th scope="row" className="w-28 py-1 text-left font-normal text-muted">{b.label}</th>
              <td className="py-1 pr-3">
                <div className="h-2.5 rounded-r bg-[#e6e9ec]">
                  <div className="h-full rounded-r bg-navy" style={{ width: most ? `${(b.count / most) * 100}%` : 0 }} />
                </div>
              </td>
              <td className="w-48 py-1 text-right tabular-nums">{b.amounts.map(wholeMoney).join(' · ') || '—'}</td>
              <td className="w-24 py-1 text-right text-muted tabular-nums">{count(b)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
