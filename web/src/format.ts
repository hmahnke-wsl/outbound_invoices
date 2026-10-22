import type { Money } from './types';

export const money = (amount: number | null, currency: string | null = 'USD') =>
  amount === null
    ? ''
    : new Intl.NumberFormat('en-US', { style: 'currency', currency: currency || 'USD' }).format(amount);

/** Whole units, for headline figures. */
export const wholeMoney = ({ amount, currency }: Money) =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency, maximumFractionDigits: 0 }).format(amount);

/** An ISO datetime as "2026-10-22 08:34" in the viewer's time zone (stamps are stored in mixed offsets). */
export const when = (iso: string | null) => {
  if (!iso) return '';
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

/** Today as YYYY-MM-DD in the viewer's time zone. */
export const todayIso = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};
