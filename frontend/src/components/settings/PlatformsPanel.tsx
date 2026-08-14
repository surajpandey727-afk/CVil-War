import { useMemo, useState } from 'react';

import Icon from '@/components/ui/Icon';
import { useDisconnectPlatform, usePlatforms, useSettings, useUpdateSettings } from '@/hooks/useSettings';
import { useAppStore } from '@/store/useAppStore';
import type { PlatformStatus } from '@/types/platforms';

const card: React.CSSProperties = {
  background: 'var(--surface)', border: '1px solid var(--border)',
  borderRadius: 'var(--r-lg)', boxShadow: 'var(--shadow-1)', padding: 18,
};

/** How each registry health value reads, and how much attention it deserves. */
const HEALTH: Record<string, { label: string; tone: string }> = {
  live: { label: 'Live', tone: 'var(--applied)' },
  auth_required: { label: 'Needs connection', tone: 'var(--pending)' },
  degraded: { label: 'Degraded', tone: 'var(--pending)' },
  rate_limited: { label: 'Rate limited', tone: 'var(--pending)' },
  interactive_available: { label: 'Browser only', tone: 'var(--pending)' },
  not_implemented: { label: 'No adapter', tone: 'var(--text-4)' },
  unavailable: { label: 'Unavailable', tone: 'var(--rejected)' },
  blocked: { label: 'Blocked', tone: 'var(--rejected)' },
};

type Filter = 'usable' | 'connected' | 'all';

/**
 * Platform management.
 *
 * Driven entirely by `/settings/platforms`, which assembles the source registry with this
 * user's sessions. That is the point: Settings used to keep its own list of four platforms
 * while the registry served fifty-five, so the two screens disagreed about what the product
 * supports. One endpoint now answers for both.
 *
 * Actions come from the server with their availability and a reason, so a control that
 * cannot do anything says why instead of failing silently when clicked.
 */
export default function PlatformsPanel() {
  const notify = useAppStore((s) => s.showNotification);
  const { data, isLoading, isError, refetch } = usePlatforms();
  const { data: settings } = useSettings();
  const update = useUpdateSettings();
  const disconnect = useDisconnectPlatform();
  const [filter, setFilter] = useState<Filter>('usable');

  const platforms = useMemo(() => {
    const all = data?.platforms ?? [];
    if (filter === 'connected') return all.filter((p) => p.connected);
    if (filter === 'usable') return all.filter((p) => p.implemented);
    return all;
  }, [data, filter]);

  const toggle = (platform: PlatformStatus) => {
    const current = settings?.platforms_enabled ?? [];
    const next = current.includes(platform.key)
      ? current.filter((k) => k !== platform.key)
      : [...current, platform.key];
    update.mutate(
      { platforms_enabled: next },
      {
        onSuccess: () => {
          void refetch();
          notify(
            `${platform.label} ${next.includes(platform.key) ? 'enabled' : 'disabled'} for discovery`,
            'success',
          );
        },
        onError: () => notify('Could not save that change', 'error'),
      },
    );
  };

  const onDisconnect = (platform: PlatformStatus) => {
    disconnect.mutate(platform.key, {
      onSuccess: () => {
        void refetch();
        notify(`Disconnected ${platform.label}. The stored session was deleted.`, 'success');
      },
      onError: () => notify(`Could not disconnect ${platform.label}`, 'error'),
    });
  };

  if (isLoading) {
    return <div style={{ ...card, color: 'var(--text-3)', font: '500 12.5px/1.4 var(--font)' }}>
      Loading the source registry…
    </div>;
  }

  if (isError || !data) {
    return (
      <div style={{ ...card, borderColor: 'var(--rejected)' }}>
        <div style={{ font: '700 13px/1.3 var(--font)', marginBottom: 6 }}>
          Could not load platforms
        </div>
        <p style={{ margin: '0 0 12px', font: '500 12px/1.5 var(--font)', color: 'var(--text-3)' }}>
          The registry could not be reached. Your connections are unaffected — this screen
          simply cannot read them right now.
        </p>
        <button onClick={() => void refetch()} style={ghost}>Try again</button>
      </div>
    );
  }

  return (
    <section style={card} id="platforms">
      <div style={{ display: 'flex', alignItems: 'center', gap: 11, marginBottom: 4, flexWrap: 'wrap' }}>
        <span style={{ display: 'grid', placeItems: 'center', width: 32, height: 32, borderRadius: 9, background: 'var(--accent-soft)', color: 'var(--accent)' }}>
          <Icon name="plug" size={16} />
        </span>
        <span>
          <span style={{ display: 'block', font: '700 14px/1.2 var(--font)', letterSpacing: '-.01em' }}>
            Platforms
          </span>
          <span style={{ display: 'block', font: '500 11.5px/1.3 var(--font)', color: 'var(--text-3)', marginTop: 2 }}>
            {data.usable} of {data.total} sources have a working adapter · {data.connected} connected
          </span>
        </span>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 5 }}>
          {([['usable', 'Usable'], ['connected', 'Connected'], ['all', `All ${data.total}`]] as const).map(
            ([key, label]) => (
              <button
                key={key}
                onClick={() => setFilter(key)}
                aria-pressed={filter === key}
                style={{
                  height: 26, padding: '0 10px', borderRadius: 999, cursor: 'pointer',
                  font: '600 11px/1 var(--font)',
                  border: `1px solid ${filter === key ? 'var(--accent-line)' : 'var(--border)'}`,
                  background: filter === key ? 'var(--accent-soft)' : 'var(--surface-2)',
                  color: filter === key ? 'var(--accent)' : 'var(--text-3)',
                }}
              >
                {label}
              </button>
            ),
          )}
        </div>
      </div>

      {platforms.length === 0 ? (
        <p style={{ margin: '14px 0 0', font: '500 12.5px/1.5 var(--font)', color: 'var(--text-3)' }}>
          {filter === 'connected'
            ? 'No platforms are connected. Sources that need a login show a Connect action above.'
            : 'No sources match this filter.'}
        </p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 7, marginTop: 14 }}>
          {platforms.map((platform) => (
            <PlatformRow
              key={platform.key}
              platform={platform}
              busy={update.isPending || disconnect.isPending}
              onToggle={() => toggle(platform)}
              onDisconnect={() => onDisconnect(platform)}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function PlatformRow({
  platform, busy, onToggle, onDisconnect,
}: {
  platform: PlatformStatus;
  busy: boolean;
  onToggle: () => void;
  onDisconnect: () => void;
}) {
  const health = HEALTH[platform.health] ?? { label: platform.health, tone: 'var(--text-4)' };
  const toggleAction = platform.actions.find((a) => a.key === 'toggle');
  const disconnectAction = platform.actions.find((a) => a.key === 'disconnect');

  return (
    <div style={{ padding: '11px 13px', borderRadius: 'var(--r-md)', background: 'var(--surface-2)', border: '1px solid var(--border)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <span style={{ flex: '1 1 160px', minWidth: 0 }}>
          <span style={{ display: 'block', font: '700 12.5px/1.25 var(--font)' }}>{platform.label}</span>
          <span style={{ display: 'block', font: '500 10.5px/1.3 var(--mono)', color: 'var(--text-4)', marginTop: 2 }}>
            {platform.key}
          </span>
        </span>

        <span style={{ flex: '0 0 auto', font: '600 10.5px/1 var(--mono)', color: health.tone, textTransform: 'uppercase', letterSpacing: '.05em' }}>
          {health.label}
        </span>

        {platform.needs_credential && (
          <span style={{ flex: '0 0 auto', font: '600 10.5px/1 var(--mono)', color: platform.connected ? 'var(--applied)' : 'var(--text-4)' }}>
            {platform.connected ? 'CONNECTED' : platform.connection_state.replace(/_/g, ' ').toUpperCase()}
          </span>
        )}

        <span style={{ flex: '0 0 auto', display: 'flex', gap: 6 }}>
          {toggleAction && (
            <button
              onClick={onToggle}
              disabled={!toggleAction.available || busy}
              title={toggleAction.reason || undefined}
              style={{
                height: 27, padding: '0 11px', borderRadius: 'var(--r-md)',
                cursor: toggleAction.available && !busy ? 'pointer' : 'not-allowed',
                font: '600 11px/1 var(--font)',
                border: `1px solid ${platform.enabled ? 'var(--accent-line)' : 'var(--border)'}`,
                background: platform.enabled ? 'var(--accent-soft)' : 'var(--surface-3)',
                color: toggleAction.available
                  ? (platform.enabled ? 'var(--accent)' : 'var(--text-3)')
                  : 'var(--text-4)',
              }}
            >
              {platform.enabled ? 'Enabled' : 'Enable'}
            </button>
          )}
          {disconnectAction?.available && (
            <button
              onClick={onDisconnect}
              disabled={busy}
              style={{ height: 27, padding: '0 11px', borderRadius: 'var(--r-md)', cursor: 'pointer', font: '600 11px/1 var(--font)', border: '1px solid var(--border)', background: 'var(--surface-3)', color: 'var(--rejected)' }}
            >
              Disconnect
            </button>
          )}
        </span>
      </div>

      {platform.account && (
        <div style={{ font: '500 11px/1.4 var(--mono)', color: 'var(--text-3)', marginTop: 6 }}>
          {/* Masked server-side. Never a full address, never a credential. */}
          {platform.account}
        </div>
      )}

      {platform.capabilities.length > 0 && (
        <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', marginTop: 7 }}>
          {platform.capabilities.map((capability) => (
            <span key={capability} style={{ padding: '2px 6px', borderRadius: 4, background: 'var(--surface-3)', font: '600 9.5px/1.4 var(--mono)', color: 'var(--text-4)', textTransform: 'uppercase', letterSpacing: '.05em' }}>
              {capability.replace(/_/g, ' ')}
            </span>
          ))}
        </div>
      )}

      {(platform.detail || platform.last_error) && (
        // The actual reason, verbatim. "Something went wrong" is not debuggable.
        <div style={{ font: '500 11px/1.45 var(--font)', color: 'var(--text-3)', marginTop: 6 }}>
          {platform.detail || platform.last_error}
        </div>
      )}
    </div>
  );
}

const ghost: React.CSSProperties = {
  height: 30, padding: '0 13px', borderRadius: 'var(--r-md)', background: 'var(--surface-2)',
  border: '1px solid var(--border)', color: 'var(--text-2)', font: '600 12px/1 var(--font)',
  cursor: 'pointer',
};
