import { useVersionDiff } from '@/hooks/useResumeIntelligence';
import type { VersionDiffEntry } from '@/types/resumeIntelligence';

const card: React.CSSProperties = {
  background: 'var(--surface)', border: '1px solid var(--border)',
  borderRadius: 'var(--r-lg)', boxShadow: 'var(--shadow-1)',
};

/** A clean, GitHub-like diff between two versions — a document review tool, not an IDE. */
export default function DiffView({ fromId, toId }: { fromId: string; toId: string }) {
  const { data, isLoading } = useVersionDiff(fromId, toId);

  if (isLoading || !data) {
    return <div style={{ ...card, height: 140, background: 'linear-gradient(90deg,var(--surface-2),var(--hover),var(--surface-2))', backgroundSize: '200% 100%', animation: 'aaShimmer 1.3s linear infinite' }} />;
  }

  const nothing = data.added.length === 0 && data.removed.length === 0 && data.modified.length === 0;

  return (
    <div style={{ ...card, padding: 16, display: 'flex', flexDirection: 'column', gap: 14 }}>
      {nothing && <p style={{ margin: 0, font: '500 12.5px/1.5 var(--font)', color: 'var(--text-3)' }}>No differences between these versions.</p>}
      {data.modified.length > 0 && (
        <DiffGroup title="Modified" entries={data.modified} render={(e) => (
          <>
            <div style={{ font: '500 12.5px/1.5 var(--font)', color: 'var(--rejected)', textDecoration: 'line-through', background: 'var(--rejected-soft)', padding: '4px 8px', borderRadius: 4, marginBottom: 4 }}>{e.before}</div>
            <div style={{ font: '500 12.5px/1.5 var(--font)', color: 'var(--applied)', background: 'var(--applied-soft)', padding: '4px 8px', borderRadius: 4 }}>{e.after}</div>
          </>
        )} />
      )}
      {data.added.length > 0 && (
        <DiffGroup title="Added" entries={data.added} render={(e) => (
          <div style={{ font: '500 12.5px/1.5 var(--font)', color: 'var(--applied)', background: 'var(--applied-soft)', padding: '4px 8px', borderRadius: 4 }}>{e.after}</div>
        )} />
      )}
      {data.removed.length > 0 && (
        <DiffGroup title="Removed" entries={data.removed} render={(e) => (
          <div style={{ font: '500 12.5px/1.5 var(--font)', color: 'var(--rejected)', textDecoration: 'line-through', background: 'var(--rejected-soft)', padding: '4px 8px', borderRadius: 4 }}>{e.before}</div>
        )} />
      )}
    </div>
  );
}

function DiffGroup({ title, entries, render }: {
  title: string; entries: VersionDiffEntry[]; render: (e: VersionDiffEntry) => React.ReactNode;
}) {
  return (
    <div>
      <div style={{ font: '700 10.5px/1 var(--font)', color: 'var(--text-4)', textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 8 }}>
        {title} <span style={{ color: 'var(--text-4)' }}>({entries.length})</span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {entries.map((e, i) => (
          <div key={i}>
            <div style={{ font: '600 10.5px/1 var(--mono)', color: 'var(--text-4)', textTransform: 'uppercase', marginBottom: 3 }}>{e.section}</div>
            {render(e)}
          </div>
        ))}
      </div>
    </div>
  );
}
