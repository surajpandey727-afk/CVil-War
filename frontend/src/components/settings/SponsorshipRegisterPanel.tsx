import Icon from '@/components/ui/Icon';
import { useRefreshSponsorshipRegister, useSponsorshipRegisterStatus } from '@/hooks/useSettings';
import { useAppStore } from '@/store/useAppStore';

const card: React.CSSProperties = {
  background: 'var(--surface)', border: '1px solid var(--border)',
  borderRadius: 'var(--r-lg)', boxShadow: 'var(--shadow-1)', padding: 18,
};

/**
 * The UK Home Office's public register of licensed Skilled Worker sponsors, cached locally
 * (see `core.sponsorship.register`) so a lookup never blocks on a ~140k-row network fetch.
 * This panel is the only way to see how stale that cache is, or to force a fresh download —
 * without it, "Sponsor confirmed" on the dashboard silently depends on a file nothing shows
 * the operator, or lets them refresh.
 */
export default function SponsorshipRegisterPanel() {
  const notify = useAppStore((s) => s.showNotification);
  const { data, isLoading, isError, refetch } = useSponsorshipRegisterStatus();
  const refresh = useRefreshSponsorshipRegister();

  const runRefresh = (force: boolean) => {
    refresh.mutate(force, {
      onSuccess: (result) => {
        if (result.error) {
          notify(`Register refresh failed: ${result.error}`, 'error');
        } else if (result.refreshed) {
          notify(`Register refreshed: ${result.row_count.toLocaleString()} sponsors loaded`, 'success');
        } else {
          notify('The cached register is still fresh — nothing to download', 'info');
        }
        void refetch();
      },
      onError: () => notify('Could not reach the register refresh endpoint', 'error'),
    });
  };

  if (isLoading) {
    return <div style={{ ...card, color: 'var(--text-3)', font: '500 12.5px/1.4 var(--font)' }}>
      Loading sponsor register status…
    </div>;
  }

  if (isError || !data) {
    return (
      <div style={{ ...card, borderColor: 'var(--rejected)' }}>
        <div style={{ font: '700 13px/1.3 var(--font)', marginBottom: 6 }}>
          Could not load the sponsor register status
        </div>
        <button onClick={() => void refetch()} style={ghost}>Try again</button>
      </div>
    );
  }

  const freshness = data.row_count === 0
    ? { label: 'Never loaded', tone: 'var(--rejected)' }
    : data.stale
      ? { label: 'Stale', tone: 'var(--pending)' }
      : { label: 'Fresh', tone: 'var(--applied)' };

  return (
    <section style={{ ...card, marginBottom: 14 }} id="sponsorship-register">
      <div style={{ display: 'flex', alignItems: 'center', gap: 11, flexWrap: 'wrap' }}>
        <span style={{ display: 'grid', placeItems: 'center', width: 32, height: 32, borderRadius: 9, background: 'var(--accent-soft)', color: 'var(--accent)' }}>
          <Icon name="shield" size={16} />
        </span>
        <span style={{ flex: '1 1 220px' }}>
          <span style={{ display: 'block', font: '700 14px/1.2 var(--font)', letterSpacing: '-.01em' }}>
            Sponsor register
          </span>
          <span style={{ display: 'block', font: '500 11.5px/1.3 var(--font)', color: 'var(--text-3)', marginTop: 2 }}>
            {data.row_count > 0
              ? `${data.row_count.toLocaleString()} licensed sponsors cached`
              : 'No register downloaded yet'}
            {data.fetched_at && ` · fetched ${new Date(data.fetched_at).toLocaleString()}`}
          </span>
        </span>
        <span style={{ font: '700 10.5px/1 var(--mono)', color: freshness.tone, textTransform: 'uppercase', letterSpacing: '.05em' }}>
          {freshness.label}
        </span>
        <button
          onClick={() => runRefresh(false)}
          disabled={refresh.isPending}
          style={{
            height: 28, padding: '0 12px', borderRadius: 999,
            cursor: refresh.isPending ? 'wait' : 'pointer', font: '600 11px/1 var(--font)',
            border: '1px solid var(--accent-line)', background: 'var(--accent-soft)',
            color: 'var(--accent)',
          }}
        >
          {refresh.isPending ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>
      <p style={{ margin: '12px 0 0', font: '500 11.5px/1.5 var(--font)', color: 'var(--text-3)' }}>
        Jobs are checked against this register at discovery time — refreshing it does not
        retroactively re-check jobs already in your list. The register updates on gov.uk
        regularly, so a weekly refresh keeps sponsor confirmations current.
      </p>
    </section>
  );
}

const ghost: React.CSSProperties = {
  height: 30, padding: '0 13px', borderRadius: 'var(--r-md)', background: 'var(--surface-2)',
  border: '1px solid var(--border)', color: 'var(--text-2)', font: '600 12px/1 var(--font)',
  cursor: 'pointer',
};
