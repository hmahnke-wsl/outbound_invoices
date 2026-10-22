// Lowercase and drop spaces and punctuation, so "inv 7025" finds "INV7025".
const normalize = (text: string) => text.toLowerCase().replace(/[^a-z0-9]/g, '');

/** True when the query appears in the invoice's customer, invoice number or memo. An empty query matches everything. */
export function matchesSearch(invoice: { customer: string; invoice_number: string | null; memo?: string | null }, query: string) {
  const q = normalize(query);
  if (!q) return true;
  return [invoice.customer, invoice.invoice_number, invoice.memo].some((field) => normalize(field ?? '').includes(q));
}
