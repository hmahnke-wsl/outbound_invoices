import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import AuthGate, { useAuth } from './AuthGate';
import Header from './Header';
import { fetchInvoices, markOpen, runIngest } from './api';

type Reply = { status: number; body?: unknown };

// Routes fetch(url, init) -> canned reply; records every call.
function mockServer(routes: Record<string, Reply | ((init?: RequestInit) => Reply)>) {
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    const key = `${init?.method ?? 'GET'} ${url}`;
    const route = routes[key];
    if (!route) return Promise.reject(new Error(`unexpected fetch: ${key}`));
    let reply: Reply;
    try {
      reply = typeof route === 'function' ? route(init) : route;
    } catch (exc) {
      return Promise.reject(exc); // like a real network failure: async, not a sync throw
    }
    return Promise.resolve({
      ok: reply.status >= 200 && reply.status < 300,
      status: reply.status,
      json: () => Promise.resolve(reply.body ?? {}),
    });
  });
  global.fetch = fetchMock as unknown as typeof fetch;
  return fetchMock;
}

const Dashboard = () => <div>dashboard content</div>;

async function signIn(username: string, password: string) {
  fireEvent.change(await screen.findByLabelText(/username/i), { target: { value: username } });
  fireEvent.change(screen.getByLabelText(/password/i), { target: { value: password } });
  fireEvent.click(screen.getByRole('button', { name: /sign in/i }));
}

describe('AuthGate', () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    vi.restoreAllMocks();
  });
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('shows the login form, not the dashboard, when there is no session', async () => {
    mockServer({ 'GET /api/auth/me': { status: 401 } });

    render(<AuthGate><Dashboard /></AuthGate>);

    expect(await screen.findByLabelText(/username/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument();
    expect(screen.queryByText('dashboard content')).not.toBeInTheDocument();
  });

  it('shows the dashboard when already signed in', async () => {
    mockServer({ 'GET /api/auth/me': { status: 200, body: { user: 'jsmith' } } });

    render(<AuthGate><Dashboard /></AuthGate>);

    expect(await screen.findByText('dashboard content')).toBeInTheDocument();
    expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument();
  });

  it('shows the dashboard when the backend has no login gate (local dev)', async () => {
    mockServer({ 'GET /api/auth/me': { status: 404 } });

    render(<AuthGate><Dashboard /></AuthGate>);

    expect(await screen.findByText('dashboard content')).toBeInTheDocument();
  });

  it('falls through to the dashboard when the backend is unreachable', async () => {
    global.fetch = vi.fn(() => Promise.reject(new TypeError('Failed to fetch'))) as unknown as typeof fetch;

    render(<AuthGate><Dashboard /></AuthGate>);

    expect(await screen.findByText('dashboard content')).toBeInTheDocument();
  });

  it('signs in with the entered credentials and then shows the dashboard', async () => {
    const fetchMock = mockServer({
      'GET /api/auth/me': { status: 401 },
      'POST /api/auth/login': { status: 200, body: { user: 'jsmith' } },
    });
    render(<AuthGate><Dashboard /></AuthGate>);

    await signIn('jsmith', 's3cret');

    expect(await screen.findByText('dashboard content')).toBeInTheDocument();
    const [, init] = fetchMock.mock.calls.find(([url]) => url === '/api/auth/login')!;
    expect(JSON.parse(init!.body as string)).toEqual({ username: 'jsmith', password: 's3cret' });
  });

  it.each([
    [401, 'Incorrect username or password'],
    [429, 'Too many attempts -- try again in 15 minutes'],
    [503, "Can't reach the login server -- try again shortly"],
  ])('a refused sign-in (%i) shows the reason, keeps the username, clears the password', async (status, detail) => {
    mockServer({
      'GET /api/auth/me': { status: 401 },
      'POST /api/auth/login': { status, body: { detail } },
    });
    render(<AuthGate><Dashboard /></AuthGate>);

    await signIn('jsmith', 'wrong');

    expect(await screen.findByRole('alert')).toHaveTextContent(detail);
    expect(screen.getByLabelText(/username/i)).toHaveValue('jsmith');
    expect(screen.getByLabelText(/password/i)).toHaveValue('');
    expect(screen.queryByText('dashboard content')).not.toBeInTheDocument();
  });

  it('shows a plain message when the sign-in request itself fails', async () => {
    mockServer({
      'GET /api/auth/me': { status: 401 },
      'POST /api/auth/login': () => {
        throw new TypeError('Failed to fetch');
      },
    });
    render(<AuthGate><Dashboard /></AuthGate>);

    await signIn('jsmith', 's3cret');

    expect(await screen.findByRole('alert')).toHaveTextContent("Can't reach the dashboard server");
  });

  it.each([
    ['a load', 'GET /api/invoices', () => fetchInvoices()],
    ['a Refresh', 'POST /api/ingest', () => runIngest()],
    ['an edit', 'PATCH /api/invoices/1', () => markOpen(1)],
  ])('returns to the login page when the session expires mid-use (%s)', async (_, route, call) => {
    mockServer({
      'GET /api/auth/me': { status: 200, body: { user: 'jsmith' } },
      [route]: { status: 401 },
    });
    const Refreshing = () => (
      <button onClick={() => call().catch(() => {})}>refresh</button>
    );
    render(<AuthGate><Refreshing /></AuthGate>);

    fireEvent.click(await screen.findByRole('button', { name: 'refresh' }));

    expect(await screen.findByLabelText(/username/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'refresh' })).not.toBeInTheDocument();
  });

  it('shows who is signed in, and Sign out returns to the login page', async () => {
    const fetchMock = mockServer({
      'GET /api/auth/me': { status: 200, body: { user: 'jsmith' } },
      'POST /api/auth/logout': { status: 200, body: { user: null } },
    });
    const SignedInHeader = () => {
      const { user, signOut } = useAuth();
      return <Header user={user} onSignOut={signOut} />;
    };
    render(<AuthGate><SignedInHeader /></AuthGate>);

    expect(await screen.findByText('jsmith')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /sign out/i }));

    expect(await screen.findByLabelText(/username/i)).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url, init]) => url === '/api/auth/logout' && init?.method === 'POST')).toBe(true);
  });

  it('has no sign-out control when the backend has no login gate', async () => {
    mockServer({ 'GET /api/auth/me': { status: 404 } });
    const SignedInHeader = () => {
      const { user, signOut } = useAuth();
      return <Header user={user} onSignOut={signOut} />;
    };
    render(<AuthGate><SignedInHeader /></AuthGate>);

    expect(await screen.findByAltText('WSL')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /sign out/i })).not.toBeInTheDocument();
  });
});
