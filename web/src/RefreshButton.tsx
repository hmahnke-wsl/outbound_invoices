import { useEffect, useState } from 'react';
import { ActionButton } from '@wsl/ui';
import { fetchLastRefresh, runIngest } from './api';
import type { IngestResult } from './types';

/** "Oct 13, 2:05 PM" in the viewer's time zone; the year only when it isn't this one. */
function formatStamp(iso: string): string {
  const at = new Date(iso);
  const sameYear = at.getFullYear() === new Date().getFullYear();
  return at.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    ...(sameYear ? {} : { year: 'numeric' }),
    hour: 'numeric',
    minute: '2-digit',
  });
}

/** Imports new invoice PDFs, then hands the result to the dashboard (which reloads and shows what changed). */
export default function RefreshButton({ onRefreshed }: { onRefreshed: (result: IngestResult) => void }) {
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastAt, setLastAt] = useState<string | null>(null);

  // A missing stamp is cosmetic: never let it surface as an error next to the button.
  const loadStamp = () => fetchLastRefresh().then(setLastAt, () => {});
  useEffect(() => {
    loadStamp();
  }, []);

  const refresh = async () => {
    setRunning(true);
    setError(null);
    try {
      onRefreshed(await runIngest());
      loadStamp();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="flex items-center gap-3">
      {error && (
        <span role="alert" className="text-[13px] text-[#a61f14]">
          {error}
        </span>
      )}
      {lastAt && (
        <span className="text-[13px] text-muted" title={new Date(lastAt).toLocaleString()}>
          Last refreshed {formatStamp(lastAt)}
        </span>
      )}
      <ActionButton variant="secondary" loading={running} loadingLabel="Refreshing" onClick={refresh}>
        Refresh
      </ActionButton>
    </div>
  );
}
