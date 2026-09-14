import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import Icon from '@/components/ui/Icon';
import { useApplications } from '@/hooks/useApplications';
import {
  useApolloStatus, useCommunications, useDisconnectGmail, useGmailStatus,
  useInboxSync, useLinkApplication,
} from '@/hooks/useCommunications';
import { useAppStore } from '@/store/useAppStore';
import { relativeTime } from '@/lib/status';
import type { CommunicationEventItem } from '@/types/communications';

const card: React.CSSProperties = {
  background: 'var(--surface)', border: '1px solid var(--border)',
  borderRadius: 'var(--r-lg)', boxShadow: 'var(--shadow-1)', padding: 18,
};

const CLASSIFICATION_STYLE: Record<string, { label: string; color: string; soft: string }> = {
  rejection: { label: 'Rejection', color: 'var(--rejected)', soft: 'var(--rejected-soft)' },
  interview_invite: { label: 'Interview invite', color: 'var(--interview)', soft: 'var(--interview-soft)' },
  reply: { label: 'Reply', color: 'var(--text-3)', soft: 'var(--surface-3)' },
  '': { label: 'Outbound', color: 'var(--text-4)', soft: 'var(--surface-3)' },
};

/**
 * Unified communications feed: Apollo outbound tracking and Gmail inbound reply detection in
 * one place — replacing "check Apollo, then check Gmail, then check the dashboard" with one
 * screen. Matched replies already live on their application's own timeline too; this is where
 * unmatched ones wait for a quick confirmation instead of being silently dropped.
 */
export default function CommunicationsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const notify = useAppStore((s) => s.showNotification);

  const unmatchedOnly = searchParams.get('filter') === 'unmatched';
  const setUnmatchedOnly = (v: boolean) => setSearchParams(v ? { filter: 'unmatched' } : {});

  const { data: gmail, isLoading: gmailLoading } = useGmailStatus();
  const { data: apollo } = useApolloStatus();
  const disconnectGmail = useDisconnectGmail();
  const inboxSync = useInboxSync();
  const { data, isLoading, isError, refetch } = useCommunications(unmatchedOnly);

  return (
    <div style={{ animation: 'aaUp .4s var(--ease) both', maxWidth: 1000 }}>
      <div style={{ marginBottom: 18 }}>
        <h1 style={{ margin: 0, font: '800 24px/1.1 var(--font)', letterSpacing: '-.03em' }}>
          Communications
        </h1>
        <p style={{ margin: '6px 0 0', font: '500 13px/1.4 var(--font)', color: 'var(--text-3)' }}>
          Every recruiter reply Gmail can see, and every outbound contact logged to Apollo, in
          one feed instead of two separate tools.
        </p>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <section style={{ ...card, display: 'flex', gap: 14, flexWrap: 'wrap' }}>
          <GmailCard
            status={gmail}
            loading={gmailLoading}
            onDisconnect={() => disconnectGmail.mutate(undefined, {
              onSuccess: () => notify('Gmail disconnected', 'success'),
              onError: () => notify('Could not disconnect Gmail', 'error'),
            })}
            onSync={() => inboxSync.mutate(undefined, {
              onSuccess: (r) => notify(
                `Synced: ${r.matched_to_application} matched, ${r.unmatched} need review`,
                'success',
              ),
              onError: (e: unknown) => {
                const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
                notify(detail || 'Inbox sync failed', 'error');
              },
            })}
            syncing={inboxSync.isPending}
            disconnecting={disconnectGmail.isPending}
          />
          <div style={{ width: 1, background: 'var(--border)', alignSelf: 'stretch' }} />
          <ApolloCard configured={apollo?.configured ?? false} />
        </section>

        <section style={card}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14, flexWrap: 'wrap' }}>
            <div style={{ font: '700 13.5px/1 var(--font)' }}>Feed</div>
            <div style={{ display: 'flex', gap: 6, marginLeft: 'auto' }}>
              <FilterButton active={!unmatchedOnly} onClick={() => setUnmatchedOnly(false)}>
                All
              </FilterButton>
              <FilterButton active={unmatchedOnly} onClick={() => setUnmatchedOnly(true)}>
                Needs review {data ? `(${data.unmatched})` : ''}
              </FilterButton>
            </div>
          </div>

          {isLoading && <Notice>Loading communications…</Notice>}
          {isError && (
            <Notice>
              Could not load the feed.{' '}
              <button onClick={() => void refetch()} style={linkBtn}>Try again</button>
            </Notice>
          )}
          {!isLoading && !isError && data?.items.length === 0 && (
            <Notice>
              {unmatchedOnly
                ? 'Nothing needs review — every captured reply matched an application.'
                : 'Nothing captured yet. Connect Gmail above and run a sync.'}
            </Notice>
          )}
          {!isLoading && !isError && data && data.items.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {data.items.map((item) => <FeedRow key={item.id} item={item} />)}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function GmailCard({ status, loading, onDisconnect, onSync, syncing, disconnecting }: {
  status: { configured: boolean; connected: boolean; authorize_url: string | null } | undefined;
  loading: boolean;
  onDisconnect: () => void;
  onSync: () => void;
  syncing: boolean;
  disconnecting: boolean;
}) {
  return (
    <div style={{ flex: '1 1 260px', minWidth: 220 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
        <Icon name="mail" size={16} />
        <span style={{ font: '700 13px/1 var(--font)' }}>Gmail</span>
        {!loading && status && (
          <Dot on={status.connected} title={status.connected ? 'Connected' : status.configured ? 'Not connected' : 'Not configured'} />
        )}
      </div>
      {loading ? (
        <p style={{ margin: 0, font: '500 12px/1.4 var(--font)', color: 'var(--text-3)' }}>Checking…</p>
      ) : !status?.configured ? (
        <p style={{ margin: 0, font: '500 12px/1.5 var(--font)', color: 'var(--text-3)' }}>
          Not set up. Add <code style={{ font: '600 11px var(--mono)' }}>GMAIL_CLIENT_ID</code> and{' '}
          <code style={{ font: '600 11px var(--mono)' }}>GMAIL_CLIENT_SECRET</code> to <code style={{ font: '600 11px var(--mono)' }}>.env</code> to enable reply detection.
        </p>
      ) : !status.connected ? (
        <div>
          <p style={{ margin: '0 0 8px', font: '500 12px/1.5 var(--font)', color: 'var(--text-3)' }}>
            Grant read-only access to detect replies. Your password is never seen — you sign in
            on Google&rsquo;s own page.
          </p>
          <a
            href={status.authorize_url ?? '#'}
            style={{ ...ghost, display: 'inline-flex', alignItems: 'center', textDecoration: 'none', padding: '0 14px' }}
          >
            Connect Gmail
          </a>
        </div>
      ) : (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button onClick={onSync} disabled={syncing} style={{ ...ghost, padding: '0 14px' }}>
            {syncing ? 'Syncing…' : 'Sync now'}
          </button>
          <button onClick={onDisconnect} disabled={disconnecting} style={{ ...ghost, padding: '0 14px', color: 'var(--rejected)' }}>
            Disconnect
          </button>
        </div>
      )}
    </div>
  );
}

function ApolloCard({ configured }: { configured: boolean }) {
  return (
    <div style={{ flex: '1 1 220px', minWidth: 200 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
        <Icon name="target" size={16} />
        <span style={{ font: '700 13px/1 var(--font)' }}>Apollo</span>
        <Dot on={configured} title={configured ? 'Configured' : 'Not configured'} />
      </div>
      <p style={{ margin: 0, font: '500 12px/1.5 var(--font)', color: 'var(--text-3)' }}>
        {configured
          ? 'Log a recruiter contact from any application’s own page — it lands here and on that application’s timeline.'
          : (
            <>Not set up. Add <code style={{ font: '600 11px var(--mono)' }}>APOLLO_API_KEY</code> to <code style={{ font: '600 11px var(--mono)' }}>.env</code> to enable contact logging.</>
          )}
      </p>
    </div>
  );
}

function FeedRow({ item }: { item: CommunicationEventItem }) {
  const style = CLASSIFICATION_STYLE[item.classified_as] ?? CLASSIFICATION_STYLE['']!;
  const [linking, setLinking] = useState(false);
  const [picked, setPicked] = useState('');
  const linkApplication = useLinkApplication();
  const notify = useAppStore((s) => s.showNotification);
  const { data: appData } = useApplications(1, 100);
  const apps = useMemo(() => appData?.items ?? [], [appData]);

  const doLink = () => {
    if (!picked) return;
    linkApplication.mutate({ eventId: item.id, applicationId: picked }, {
      onSuccess: () => { notify('Linked to application', 'success'); setLinking(false); },
      onError: () => notify('Could not link this communication', 'error'),
    });
  };

  return (
    <div style={{
      display: 'flex', alignItems: 'flex-start', gap: 12, padding: '10px 12px',
      borderRadius: 'var(--r-md)', background: 'var(--surface-2)', border: '1px solid var(--border)',
    }}>
      <div style={{ flex: '1 1 auto', minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ font: '700 12px/1.3 var(--font)' }}>{item.subject || '(no subject)'}</span>
          <span style={{
            display: 'inline-flex', height: 18, padding: '0 7px', borderRadius: 999,
            alignItems: 'center', font: '700 9.5px/1 var(--mono)', textTransform: 'uppercase',
            color: style.color, background: style.soft,
          }}>
            {style.label}
          </span>
          <span style={{ font: '600 11px/1 var(--mono)', color: 'var(--text-4)', marginLeft: 'auto' }}>
            {relativeTime(item.occurred_at)}
          </span>
        </div>
        <div style={{ font: '500 11.5px/1.4 var(--mono)', color: 'var(--text-4)', marginTop: 3 }}>
          {item.sender}
        </div>
        <div style={{ font: '500 11.5px/1.5 var(--font)', color: 'var(--text-3)', marginTop: 4 }}>
          {item.snippet}
        </div>

        {item.application_id === null && !linking && (
          <button onClick={() => setLinking(true)} style={{ ...linkBtn, marginTop: 8 }}>
            Link to an application
          </button>
        )}
        {item.application_id === null && linking && (
          <div style={{ display: 'flex', gap: 6, marginTop: 8, flexWrap: 'wrap' }}>
            <select
              value={picked}
              onChange={(e) => setPicked(e.target.value)}
              aria-label="Application to link"
              style={{
                height: 30, padding: '0 8px', borderRadius: 'var(--r-md)', background: 'var(--surface-3)',
                border: '1px solid var(--border)', color: 'var(--text)', font: '600 11.5px/1 var(--font)',
              }}
            >
              <option value="">— pick an application —</option>
              {apps.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.job_title ?? 'Untitled'} · {a.company ?? ''}
                </option>
              ))}
            </select>
            <button onClick={doLink} disabled={!picked || linkApplication.isPending} style={{ ...ghost, height: 30, padding: '0 12px' }}>
              Link
            </button>
            <button onClick={() => setLinking(false)} style={{ ...ghost, height: 30, padding: '0 12px' }}>
              Cancel
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function Dot({ on, title }: { on: boolean; title: string }) {
  return (
    <span
      title={title}
      style={{
        width: 8, height: 8, borderRadius: '50%',
        background: on ? 'var(--offer)' : 'var(--text-4)',
      }}
    />
  );
}

function FilterButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      role="tab" aria-selected={active} onClick={onClick}
      style={{
        height: 28, padding: '0 12px', borderRadius: 999,
        border: `1px solid ${active ? 'var(--accent-line)' : 'var(--border)'}`,
        background: active ? 'var(--accent-soft)' : 'var(--surface-2)',
        color: active ? 'var(--accent)' : 'var(--text-3)', font: '700 11.5px/1 var(--font)', cursor: 'pointer',
      }}
    >
      {children}
    </button>
  );
}

function Notice({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ padding: '20px 0', textAlign: 'center', font: '500 12.5px/1.5 var(--font)', color: 'var(--text-3)' }}>
      {children}
    </div>
  );
}

const ghost: React.CSSProperties = {
  height: 32, borderRadius: 'var(--r-md)', background: 'var(--surface-2)', border: '1px solid var(--border)',
  color: 'var(--text-2)', font: '600 12px/1 var(--font)', cursor: 'pointer',
};

const linkBtn: React.CSSProperties = {
  color: 'var(--accent)', background: 'none', border: 0, cursor: 'pointer', font: '600 11.5px/1 var(--font)',
  padding: 0, textDecoration: 'underline',
};
