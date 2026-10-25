/** Pick a stored job to check against: type to narrow (server-side search, debounced), then
 *  choose from the matches. The chosen job stays listed even when a new search drops it, so the
 *  select never silently shows a different job than the one that will be sent. */
import { useEffect, useState } from 'react';

import { useJobs } from '@/hooks/useJobs';
import type { Job } from '@/types/job';

const DEBOUNCE_MS = 250;

export default function JobPicker({ jobId, onChange }: { jobId: string; onChange: (id: string) => void }) {
  const [query, setQuery] = useState('');
  const [debounced, setDebounced] = useState('');
  const [chosen, setChosen] = useState<Job | null>(null);

  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(query), DEBOUNCE_MS);
    return () => window.clearTimeout(t);
  }, [query]);

  const { data, isLoading, isError } = useJobs(1, 25, undefined, { query: debounced });
  const items = data?.items ?? [];
  const pinned = jobId && !items.some((j) => j.id === jobId) ? chosen : null;

  const pick = (id: string) => {
    setChosen(items.find((j) => j.id === id) ?? null);
    onChange(id);
  };

  return (
    <div className="rc-field">
      <label className="rc-label" htmlFor="rc-job-search">Find a job</label>
      <input
        id="rc-job-search" type="search" className="rc-control" value={query}
        onChange={(e) => setQuery(e.target.value)} placeholder="Title or company…" autoComplete="off"
      />
      <label className="rc-label" htmlFor="rc-job" style={{ marginTop: 6 }}>Job to check against</label>
      <select id="rc-job" className="rc-control" value={jobId} onChange={(e) => pick(e.target.value)} disabled={isLoading && !data}>
        <option value="">
          {isLoading && !data ? 'Loading jobs…' : items.length ? `Choose a job (${items.length} shown)…` : 'No jobs match'}
        </option>
        {pinned && <option value={pinned.id}>{pinned.title} · {pinned.company}</option>}
        {jobId && !pinned && !items.some((j) => j.id === jobId) && <option value={jobId}>Selected job</option>}
        {items.map((j) => <option key={j.id} value={j.id}>{j.title} · {j.company}</option>)}
      </select>
      {isError && <p className="rc-hint" role="alert">Couldn&apos;t load your jobs. Try again, or check against Skill Radar roles.</p>}
    </div>
  );
}
