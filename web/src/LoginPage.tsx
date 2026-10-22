import { useState, type FormEvent } from 'react';
import { ActionButton } from '@wsl/ui';
import { login } from './api';
import Header from './Header';

const labelClass = 'text-[13px] font-semibold uppercase tracking-[0.04em] text-muted';
const inputClass =
  'box-border h-[44px] w-full rounded-btn border border-grey bg-white px-3 text-[15px] text-black disabled:opacity-60';

export default function LoginPage({ onSignedIn }: { onSignedIn: (user: string) => void }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      onSignedIn(await login(username.trim(), password));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
      setPassword('');
      setSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen flex-col bg-page-bg">
      <Header />
      <main className="flex flex-grow items-start justify-center px-4 pt-[12vh]">
        <form
          onSubmit={submit}
          className="flex w-full max-w-[380px] flex-col gap-5 rounded-card border border-t-4 border-line border-t-navy bg-white p-7"
        >
          <div>
            <h1 className="text-[22px] font-bold text-navy">Sign in</h1>
            <p className="mt-1 text-[14px] text-muted">Use your WSL network login.</p>
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="login-username" className={labelClass}>
              Username
            </label>
            <input
              id="login-username"
              name="username"
              autoComplete="username"
              disabled={submitting}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className={inputClass}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="login-password" className={labelClass}>
              Password
            </label>
            <input
              id="login-password"
              name="password"
              type="password"
              autoComplete="current-password"
              disabled={submitting}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className={inputClass}
            />
          </div>
          {error && (
            <div role="alert" className="rounded-btn bg-[#fbe6e3] px-3 py-2.5 text-[14px] font-medium text-[#a61f14]">
              {error}
            </div>
          )}
          <ActionButton type="submit" variant="primary" loading={submitting} loadingLabel="Signing in…" className="justify-center">
            Sign in
          </ActionButton>
        </form>
      </main>
    </div>
  );
}
