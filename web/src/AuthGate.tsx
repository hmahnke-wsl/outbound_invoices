import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import { AUTH_EXPIRED_EVENT, fetchMe, logout } from './api';
import LoginPage from './LoginPage';

type Session = { status: 'checking' } | { status: 'signedOut' } | { status: 'signedIn'; user: string | null };

export interface AuthContextValue {
  /** The signed-in username; `null` when the API has no login gate. */
  user: string | null;
  /** Ends the session; `undefined` when there's no login gate to sign out of. */
  signOut?: () => void;
}

const AuthContext = createContext<AuthContextValue>({ user: null });

export const useAuth = () => useContext(AuthContext);

/**
 * Renders the login page until there's a session, then `children`. An API with no login gate
 * (AUTH_DISABLED, so /api/auth/me 404s) goes straight to `children`. Any 401 from the API
 * afterwards (session expired) returns to the login page.
 */
export default function AuthGate({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session>({ status: 'checking' });

  useEffect(() => {
    let live = true;
    fetchMe()
      // API unreachable: not an auth answer -- let the dashboard show its own load errors.
      .catch(() => undefined)
      .then((user) => {
        if (!live) return;
        setSession(user === null ? { status: 'signedOut' } : { status: 'signedIn', user: user ?? null });
      });
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => {
    const expired = () => setSession({ status: 'signedOut' });
    window.addEventListener(AUTH_EXPIRED_EVENT, expired);
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, expired);
  }, []);

  const signOut = useCallback(async () => {
    await logout();
    setSession({ status: 'signedOut' });
  }, []);

  if (session.status === 'checking') return null;
  if (session.status === 'signedOut') {
    return <LoginPage onSignedIn={(user) => setSession({ status: 'signedIn', user })} />;
  }
  const value: AuthContextValue = session.user ? { user: session.user, signOut } : { user: null };
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
