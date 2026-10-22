import { createContext, useContext } from 'react';
import type { IngestResult } from './types';

/** The last Refresh's result in this tab, or null before one (or after a reload). */
export const LastRefresh = createContext<IngestResult | null>(null);

/** "New" on an invoice the last Refresh first stored. */
export function RefreshBadge({ id }: { id: number }) {
  const result = useContext(LastRefresh);
  if (!result?.new_invoice_ids.includes(id)) return null;
  return <span className="whitespace-nowrap rounded-chip bg-[#e3f1e6] px-1.5 text-[12px] font-medium text-[#1f5c2e]">New</span>;
}
