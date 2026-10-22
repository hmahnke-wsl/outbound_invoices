import type { AttentionItem, HistoryEntry, IngestResult, Invoice, Summary } from './types';

/** GET /api/auth/me -> the signed-in user, `null` when not signed in (401),
 * or `undefined` when the API has no login gate (404 -- AUTH_DISABLED). */
export async function fetchMe(): Promise<string | null | undefined> {
  const response = await fetch('/api/auth/me');
  if (response.status === 401) return null;
  if (response.status === 404) return undefined;
  if (!response.ok) throw new Error(`Could not check sign-in (${response.status})`);
  return (await response.json()).user;
}

/** POST /api/auth/login -> the signed-in user; throws with the server's message on a refused login. */
export async function login(username: string, password: string): Promise<string> {
  let response: Response;
  try {
    response = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
  } catch {
    throw new Error("Can't reach the dashboard server -- check your connection and try again");
  }
  if (!response.ok) throw new Error(await errorText(response, `Sign-in failed (${response.status})`));
  return (await response.json()).user;
}

/** POST /api/auth/logout. Best-effort: the caller signs out locally either way. */
export async function logout(): Promise<void> {
  await fetch('/api/auth/logout', { method: 'POST' }).catch(() => undefined);
}

/** Fired on `window` whenever the API answers 401 -- the session expired or was never there.
 * `AuthGate` listens and returns to the login page. */
export const AUTH_EXPIRED_EVENT = 'auth:expired';

/** A 401 from the API: not an outage, so callers mustn't treat it as one. */
export class UnauthorizedError extends Error {
  constructor() {
    super('Signed out -- sign in again');
    this.name = 'UnauthorizedError';
  }
}

function checkAuth(response: Response): void {
  if (response.status === 401) {
    window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
    throw new UnauthorizedError();
  }
}

async function getJson<T>(url: string, failure: string): Promise<T> {
  const response = await fetch(url);
  checkAuth(response);
  if (!response.ok) throw new Error(`${failure} (${response.status})`);
  return response.json();
}

export const fetchInvoices = () => getJson<Invoice[]>('/api/invoices', 'Could not load invoices');

export const fetchSummary = () => getJson<Summary>('/api/summary', 'Could not load the summary');

export const fetchPaid = () => getJson<Invoice[]>('/api/paid-invoices', 'Could not load paid invoices');

export const fetchIgnored = () => getJson<AttentionItem[]>('/api/ignored', 'Could not load ignored invoices');

export const fetchHistory = (invoiceId: number) =>
  getJson<HistoryEntry[]>(`/api/invoices/${invoiceId}/history`, 'Could not load history');

export const fetchNeedsAttention = () =>
  getJson<AttentionItem[]>('/api/needs-attention', 'Could not load needs-attention invoices');

export interface InvoiceFix {
  customer?: string;
  invoice_number?: string;
  invoice_date?: string;
  due_date?: string;
  amount?: number;
  currency?: string;
  status?: Invoice['status'];
  paid_at?: string;
  ignored?: boolean;
}

export async function patchInvoice(invoiceId: number, fix: InvoiceFix): Promise<void> {
  const response = await fetch(`/api/invoices/${invoiceId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(fix),
  });
  checkAuth(response);
  if (!response.ok) throw new Error(await errorText(response, `Could not save (${response.status})`));
}

interface ValidationError {
  loc?: (string | number)[];
  msg?: string;
}

/**
 * Readable text for a failed request. The API answers `{"detail": "..."}` for business-rule and
 * not-found errors, and `{"detail": [{loc, msg}, ...]}` when the request fails validation (422).
 */
async function errorText(response: Response, fallback: string): Promise<string> {
  const detail: unknown = (await response.json().catch(() => null))?.detail;
  if (typeof detail === 'string' && detail) return detail;
  if (Array.isArray(detail) && detail.length) {
    return detail
      .map(({ loc = [], msg = '' }: ValidationError) => {
        const field = loc.filter((part) => part !== 'body').join('.');
        const text = msg.replace(/^Value error, /, '');
        return field ? `${field}: ${text}` : text;
      })
      .join('; ');
  }
  return fallback;
}

/** Hide a flagged invoice from Needs attention (or bring it back). Nothing is deleted. */
export const setIgnored = (invoiceId: number, ignored: boolean) => patchInvoice(invoiceId, { ignored });

/** Record the date a payment landed. */
export const markPaid = (invoiceId: number, paid_at: string) => patchInvoice(invoiceId, { status: 'paid', paid_at });

/** Undo a payment recorded by mistake. */
export const markOpen = (invoiceId: number) => patchInvoice(invoiceId, { status: 'open' });

/** When the last successful Refresh (or import_pdfs.py run) finished, as an ISO datetime; null if never. */
export const fetchLastRefresh = () =>
  getJson<{ finished_at: string | null }>('/api/last-refresh', 'Could not load last refresh').then((r) => r.finished_at);

/** Import new invoice PDFs (runs import_pdfs.py's work on the server). */
export async function runIngest(): Promise<IngestResult> {
  const response = await fetch('/api/ingest', { method: 'POST' });
  checkAuth(response);
  if (!response.ok) throw new Error(await errorText(response, `Refresh failed (${response.status})`));
  return response.json();
}
