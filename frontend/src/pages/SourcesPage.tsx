import CompanyLogo from '@/components/ui/CompanyLogo';
import { useSources } from '@/hooks/useSources';
import { useDiscoveryStore } from '@/store/useDiscoveryStore';
import { HEALTH_META } from '@/lib/sources';
import type { SourceRecord } from '@/types/source';

const card: React.CSSProperties = {
  background: 'var(--surface)', border: '1px solid var(--border)',
  borderRadius: 'var(--r-lg)', boxShadow: 'var(--shadow-1)',
};

/**
 * Every source the product knows about, grouped by tier, with the health the backend derives.
 *
 * Sources with no adapter are listed and labelled rather than hidden. That is the point of the
 * screen: the operator needs to know the difference between "no London matches" and "this
 * integration does not exist yet", and only an honest catalogue can tell them apart.
 */
export default function SourcesPage() {
  const { catalogue, isFallback, isFetching } = useSources();
  const { enabledSources, toggleSource, setSources } = useDiscoveryStore();

  const all = catalogue.tiers.flatMap((t) => t.sources);
  const enabledCount = all.filter((s) => enabledSources.includes(s.key)).length;
  const liveCount = all.filter((s) => s.health === 'live').length;

  return (
    <div style={{ animation: 'aaUp .4s var(--ease) both', maxWidth: 1320 }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 14, marginBottom: 18, flexWrap: 'wrap' }}>
        <div style={{ flex: '1 1 auto', minWidth: 240 }}>
          <h1 style={{ margin: 0, font: '800 24px/1.1 var(--font)', letterSpacing: '-.03em' }}>Sources</h1>
          <p style={{ margin: '6px 0 0', font: '500 13px/1.4 var(--font)', color: 'var(--text-3)' }}>
            {enabledCount} of {all.length} enabled · {liveCount} can return results right now.
            {isFallback && ' Showing the built-in catalogue — live health is unavailable.'}
          </p>
        </div>
        <button
          onClick={() => setSources(catalogue.live_keys)}
          style={{ height: 36, padding: '0 15px', borderRadius: 'var(--r-md)', background: 'var(--surface-2)', border: '1px solid var(--border)', color: 'var(--text-2)', font: '700 12.5px/1 var(--font)', cursor: 'pointer' }}
        >
          Enable only working sources
        </button>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 16, opacity: isFetching ? 0.7 : 1 }}>
        {catalogue.tiers.map((tier) => {
          const on = tier.sources.filter((s) => enabledSources.includes(s.key)).length;
          return (
            <section key={tier.id}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 10, flexWrap: 'wrap' }}>
                <span style={{ font: '700 13.5px/1 var(--font)', color: 'var(--text)' }}>{tier.name}</span>
                <span style={{ font: '500 12px/1 var(--font)', color: 'var(--text-3)' }}>{tier.note}</span>
                <div style={{ flex: '1 1 auto' }} />
                <span style={{ font: '600 11px/1 var(--mono)', color: 'var(--text-4)' }}>
                  {on}/{tier.sources.length} ON
                </span>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(258px,1fr))', gap: 10 }}>
                {tier.sources.map((src) => (
                  <SourceCard
                    key={src.key} source={src}
                    on={enabledSources.includes(src.key)}
                    onToggle={() => toggleSource(src.key)}
                  />
                ))}
              </div>
            </section>
          );
        })}
      </div>
    </div>
  );
}

function SourceCard({ source, on, onToggle }: { source: SourceRecord; on: boolean; onToggle: () => void }) {
  const meta = HEALTH_META[source.health];
  const detail = source.note || meta.label;
  return (
    <div
      style={{
        ...card, display: 'flex', alignItems: 'center', gap: 11, padding: 12,
        borderRadius: 'var(--r-md)', opacity: on ? 1 : 0.62,
      }}
    >
      <CompanyLogo name={source.label} domain={source.domain} size={32} radius={8} />
      <div style={{ flex: '1 1 auto', minWidth: 0 }}>
        <div style={{ font: '700 12.5px/1.25 var(--font)', color: 'var(--text)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {source.label}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 4 }}>
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: on ? meta.color : 'var(--text-4)', flex: '0 0 auto' }} />
          <span
            title={detail}
            style={{ font: '500 11px/1 var(--font)', color: 'var(--text-3)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
          >
            {on ? detail : 'Disabled'}
          </span>
        </div>
      </div>
      <button
        onClick={onToggle} role="switch" aria-checked={on} aria-label={`Toggle ${source.label}`}
        style={{
          flex: '0 0 auto', width: 38, height: 22, borderRadius: 999, padding: 2, cursor: 'pointer',
          border: `1px solid ${on ? 'var(--accent-line)' : 'var(--border)'}`,
          background: on ? 'var(--accent)' : 'var(--surface-3)',
          display: 'flex', alignItems: 'center', justifyContent: on ? 'flex-end' : 'flex-start',
        }}
      >
        <span style={{ display: 'block', width: 16, height: 16, borderRadius: '50%', background: on ? '#fff' : 'var(--text-4)' }} />
      </button>
    </div>
  );
}
