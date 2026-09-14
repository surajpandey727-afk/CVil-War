import { useMemo, useState } from 'react';

import Icon from '@/components/ui/Icon';
import {
  useAICatalogue, useAIUsage, useBYOLLMKeys, useDeleteBYOLLMKey, useSaveBYOLLMKey,
} from '@/hooks/useSettings';
import { useAppStore } from '@/store/useAppStore';
import { useQueryClient } from '@tanstack/react-query';
import type { AIUsagePeriod } from '@/types/aiSettings';

const KNOWN_PROVIDERS = [
  'openai', 'anthropic', 'gemini', 'groq', 'openrouter', 'azure', 'bedrock', 'vertex_ai',
];

const card: React.CSSProperties = {
  background: 'var(--surface)', border: '1px solid var(--border)',
  borderRadius: 'var(--r-lg)', boxShadow: 'var(--shadow-1)', padding: 18,
};

const PERIODS: { key: AIUsagePeriod; label: string }[] = [
  { key: 'today', label: 'Today' },
  { key: '7d', label: '7 days' },
  { key: '30d', label: '30 days' },
  { key: 'all', label: 'All time' },
];

const CAPABILITY_LABEL: Record<string, string> = {
  tool_calling: 'tools',
  vision: 'vision',
  reasoning: 'reasoning',
  temperature: 'temperature',
  effort_tiers: 'effort tiers',
};

const fmt = (n: number) =>
  n >= 1_000_000 ? `${(n / 1_000_000).toFixed(2)}M`
    : n >= 1_000 ? `${(n / 1_000).toFixed(1)}K`
      : String(n);

/**
 * AI providers, models and usage.
 *
 * Everything here is read from somewhere real. The provider list is the gateway's own
 * `/v1/models` response — it replaced five hard-coded providers with model names
 * (`gpt-4o`, `gemini-pro`) that this deployment's gateway does not offer, each marked
 * "configured" purely because an API key string was non-empty. The usage figures are sums
 * over `llm_usage` rows the application wrote when it made each call.
 *
 * Where a number was not reported, the panel says so rather than showing a default.
 */
export default function AISettingsPanel() {
  const queryClient = useQueryClient();
  const { data: catalogue, isLoading, isError } = useAICatalogue();
  const notify = useAppStore((s) => s.showNotification);
  const { data: byoKeys } = useBYOLLMKeys();
  const saveKey = useSaveBYOLLMKey();
  const deleteKey = useDeleteBYOLLMKey();
  const [newProvider, setNewProvider] = useState('openai');
  const [newKey, setNewKey] = useState('');
  const [newModel, setNewModel] = useState('');
  const [period, setPeriod] = useState<AIUsagePeriod>('7d');
  const [expanded, setExpanded] = useState<string | null>(null);
  const { data: usage } = useAIUsage(period);
  const [refreshing, setRefreshing] = useState(false);

  const refresh = async () => {
    setRefreshing(true);
    try {
      // Re-queries the gateway rather than serving the cached catalogue: an operator who has
      // just started or reconfigured it should not have to wait out a TTL.
      await queryClient.fetchQuery({
        queryKey: ['settings', 'ai-catalogue'],
        queryFn: () => import('@/services/settingsService').then((m) => m.getAICatalogue(true)),
      });
    } finally {
      setRefreshing(false);
    }
  };

  const sorted = useMemo(
    () => [...(catalogue?.providers ?? [])].sort((a, b) => b.model_count - a.model_count),
    [catalogue],
  );

  const submitKey = () => {
    if (!newKey.trim()) {
      notify('Enter an API key first', 'warning');
      return;
    }
    saveKey.mutate(
      { provider: newProvider, api_key: newKey.trim(), default_model: newModel.trim() || undefined },
      {
        onSuccess: () => {
          notify(`Saved your ${newProvider} key`, 'success');
          setNewKey('');
          setNewModel('');
        },
        onError: () => notify('Could not save the key — try again', 'error'),
      },
    );
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <section style={card}>
        <div style={{ font: '700 13.5px/1 var(--font)', marginBottom: 4 }}>Your own API key</div>
        <p style={{ margin: '0 0 12px', font: '500 12px/1.5 var(--font)', color: 'var(--text-3)' }}>
          Bring your own key: stored encrypted, used only for your calls, never shown again once
          saved. Without one, the account falls back to the shared gateway above (when it's
          reachable).
        </p>

        {byoKeys && byoKeys.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 12 }}>
            {byoKeys.map((k) => (
              <div
                key={k.provider}
                style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '9px 11px', borderRadius: 'var(--r-md)', background: 'var(--surface-2)', border: `1px solid ${k.is_active ? 'var(--accent-line)' : 'var(--border)'}` }}
              >
                <span style={{ font: '700 12.5px/1 var(--font)', color: 'var(--text)' }}>{k.provider}</span>
                {k.is_active && (
                  <span style={{ font: '700 10px/1 var(--font)', letterSpacing: '.06em', textTransform: 'uppercase', color: 'var(--accent)', background: 'var(--accent-soft)', padding: '3px 7px', borderRadius: 999 }}>
                    Active
                  </span>
                )}
                {k.default_model && (
                  <span style={{ font: '500 11px/1.4 var(--mono)', color: 'var(--text-4)' }}>{k.default_model}</span>
                )}
                <button
                  onClick={() => deleteKey.mutate(k.provider, {
                    onSuccess: () => notify(`Removed the ${k.provider} key`, 'info'),
                  })}
                  disabled={deleteKey.isPending}
                  style={{ marginLeft: 'auto', height: 26, padding: '0 9px', borderRadius: 'var(--r-md)', background: 'transparent', border: '1px solid var(--border)', color: 'var(--text-3)', font: '600 11px/1 var(--font)', cursor: 'pointer' }}
                >
                  Remove
                </button>
              </div>
            ))}
          </div>
        )}

        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <select
            value={newProvider}
            onChange={(e) => setNewProvider(e.target.value)}
            style={{ height: 32, padding: '0 8px', borderRadius: 'var(--r-md)', background: 'var(--surface-2)', border: '1px solid var(--border)', color: 'var(--text)', font: '600 12px/1 var(--font)' }}
          >
            {KNOWN_PROVIDERS.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
          <input
            type="password"
            autoComplete="off"
            placeholder="API key"
            value={newKey}
            onChange={(e) => setNewKey(e.target.value)}
            style={{ flex: '1 1 200px', minWidth: 160, height: 32, padding: '0 10px', borderRadius: 'var(--r-md)', background: 'var(--surface-2)', border: '1px solid var(--border)', color: 'var(--text)', font: '500 12px/1 var(--mono)' }}
          />
          <input
            type="text"
            placeholder="Default model (optional)"
            value={newModel}
            onChange={(e) => setNewModel(e.target.value)}
            style={{ flex: '1 1 160px', minWidth: 140, height: 32, padding: '0 10px', borderRadius: 'var(--r-md)', background: 'var(--surface-2)', border: '1px solid var(--border)', color: 'var(--text)', font: '500 12px/1 var(--mono)' }}
          />
          <button
            onClick={submitKey}
            disabled={saveKey.isPending}
            style={{ height: 32, padding: '0 13px', borderRadius: 'var(--r-md)', background: 'var(--accent)', border: '1px solid var(--accent)', color: 'var(--accent-ink)', font: '700 12px/1 var(--font)', cursor: saveKey.isPending ? 'default' : 'pointer' }}
          >
            {saveKey.isPending ? 'Saving…' : 'Save key'}
          </button>
        </div>
      </section>

      <section style={card}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4, flexWrap: 'wrap' }}>
          <div style={{ font: '700 13.5px/1 var(--font)' }}>AI providers &amp; models</div>
          <button
            onClick={() => void refresh()}
            disabled={refreshing}
            style={{
              marginLeft: 'auto', height: 28, padding: '0 11px', borderRadius: 'var(--r-md)',
              background: 'var(--surface-2)', border: '1px solid var(--border)',
              color: 'var(--text-2)', font: '600 11.5px/1 var(--font)',
              cursor: refreshing ? 'default' : 'pointer',
            }}
          >
            {refreshing ? 'Refreshing…' : 'Refresh models'}
          </button>
        </div>

        {isLoading ? (
          <div style={{ font: '500 12px/1.5 var(--font)', color: 'var(--text-3)' }}>
            Asking the gateway what it can route to…
          </div>
        ) : isError || !catalogue ? (
          <Notice tone="var(--rejected)">
            The settings screen could not query the gateway. This is a problem reaching the
            API, not a statement about which models exist.
          </Notice>
        ) : !catalogue.reachable ? (
          // "Cannot reach the gateway" and "the gateway has no models" are different
          // problems with different fixes, and an empty list conflates them.
          <Notice tone="var(--pending)">
            <strong style={{ color: 'var(--text)' }}>Gateway unreachable.</strong>{' '}
            {catalogue.error ?? 'No reason reported.'}
            {catalogue.base_url && (
              <>
                {' '}Configured endpoint:{' '}
                <code style={{ font: '600 11px var(--mono)' }}>{catalogue.base_url}</code>.
              </>
            )}{' '}
            No provider list is shown, because none could be established.
          </Notice>
        ) : (
          <>
            <p style={{ margin: '0 0 12px', font: '500 12px/1.5 var(--font)', color: 'var(--text-3)' }}>
              {catalogue.model_count} models across {catalogue.provider_count} providers,
              discovered from{' '}
              <code style={{ font: '600 11px var(--mono)' }}>{catalogue.base_url}</code>.
            </p>

            <div style={{
              display: 'flex', alignItems: 'baseline', gap: 8, padding: '9px 11px',
              borderRadius: 'var(--r-md)', background: 'var(--surface-2)',
              border: `1px solid ${catalogue.default_model_available ? 'var(--border)' : 'var(--rejected)'}`,
              marginBottom: 12,
            }}>
              <span style={{ font: '600 10px/1.5 var(--mono)', letterSpacing: '.08em', color: 'var(--text-4)', textTransform: 'uppercase' }}>
                Default
              </span>
              <span style={{ font: '600 12px/1.4 var(--mono)', color: 'var(--text)' }}>
                {catalogue.default_model || 'none configured'}
              </span>
              {!catalogue.default_model_available && (
                // A default naming a model the gateway does not list is a real
                // misconfiguration that otherwise only surfaces as a failed run much later.
                <span style={{ marginLeft: 'auto', font: '600 11px/1.4 var(--font)', color: 'var(--rejected)' }}>
                  Not offered by this gateway
                </span>
              )}
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {sorted.map((provider) => (
                <div key={provider.id} style={{ border: '1px solid var(--border)', borderRadius: 'var(--r-md)', background: 'var(--surface-2)' }}>
                  <button
                    onClick={() => setExpanded(expanded === provider.id ? null : provider.id)}
                    aria-expanded={expanded === provider.id}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 10, width: '100%',
                      padding: '10px 12px', background: 'none', border: 0, cursor: 'pointer',
                      color: 'inherit', textAlign: 'left',
                    }}
                  >
                    <span style={{ font: '700 12.5px/1 var(--font)', color: 'var(--text)' }}>
                      {provider.id}
                    </span>
                    <span style={{ font: '600 11px/1 var(--mono)', color: 'var(--text-4)' }}>
                      {provider.model_count} {provider.model_count === 1 ? 'model' : 'models'}
                    </span>
                    <span style={{ marginLeft: 'auto', color: 'var(--text-4)' }}>
                      <Icon name={expanded === provider.id ? 'chevD' : 'chevR'} size={14} />
                    </span>
                  </button>

                  {expanded === provider.id && (
                    <div style={{ padding: '0 12px 10px', display: 'flex', flexDirection: 'column', gap: 5 }}>
                      {provider.models.slice(0, 40).map((model) => (
                        <div key={model.id} style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
                          <span style={{
                            font: '500 11.5px/1.4 var(--mono)', minWidth: 0, wordBreak: 'break-all',
                            color: model.is_default ? 'var(--accent)' : 'var(--text-2)',
                          }}>
                            {model.id}
                          </span>
                          {model.capabilities.map((c) => (
                            <span key={c} style={{
                              font: '600 9.5px/1 var(--mono)', letterSpacing: '.05em',
                              padding: '2px 5px', borderRadius: 4, textTransform: 'uppercase',
                              background: 'var(--surface-3)', color: 'var(--text-4)',
                            }}>
                              {CAPABILITY_LABEL[c] ?? c}
                            </span>
                          ))}
                          <span style={{ marginLeft: 'auto', font: '500 10.5px/1.4 var(--mono)', color: 'var(--text-4)' }}>
                            {/* Absent means the gateway did not report it. Showing a
                                plausible default here would be inventing a limit. */}
                            {model.context_length
                              ? `${fmt(model.context_length)} ctx`
                              : 'ctx not reported'}
                          </span>
                        </div>
                      ))}
                      {provider.model_count > 40 && (
                        <div style={{ font: '500 11px/1.4 var(--font)', color: 'var(--text-4)' }}>
                          …and {provider.model_count - 40} more.
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </>
        )}
      </section>

      <section style={card}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
          <div style={{ font: '700 13.5px/1 var(--font)' }}>AI usage</div>
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 5 }}>
            {PERIODS.map((p) => (
              <button
                key={p.key}
                onClick={() => setPeriod(p.key)}
                aria-pressed={period === p.key}
                style={{
                  height: 26, padding: '0 10px', borderRadius: 999, cursor: 'pointer',
                  font: '600 11px/1 var(--font)',
                  border: `1px solid ${period === p.key ? 'var(--accent-line)' : 'var(--border)'}`,
                  background: period === p.key ? 'var(--accent-soft)' : 'var(--surface-2)',
                  color: period === p.key ? 'var(--accent)' : 'var(--text-3)',
                }}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>

        {!usage ? (
          <div style={{ font: '500 12px/1.5 var(--font)', color: 'var(--text-3)' }}>Loading usage…</div>
        ) : !usage.recorded ? (
          // Not the same as zeroes: a row of confident zeroes reads as "measured, and it
          // was nothing" rather than "nothing has been recorded in this window".
          <div style={{ font: '500 12.5px/1.5 var(--font)', color: 'var(--text-3)' }}>
            No LLM calls recorded in this period. Usage appears here once the agent runs.
          </div>
        ) : (
          <>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(110px,1fr))', gap: 10, marginBottom: 14 }}>
              <Stat label="Total tokens" value={fmt(usage.total_tokens)} />
              <Stat label="Input" value={fmt(usage.prompt_tokens)} />
              <Stat label="Output" value={fmt(usage.completion_tokens)} />
              <Stat label="Requests" value={fmt(usage.requests)} />
              <Stat label="Errors" value={fmt(usage.errors)} tone={usage.errors ? 'var(--rejected)' : undefined} />
              <Stat label="Cost" value={`$${usage.cost_usd.toFixed(4)}`} />
            </div>

            <Breakdown title="By model" rows={usage.by_model} />
            <Breakdown title="By task" rows={usage.by_purpose} />
            <Breakdown title="By provider" rows={usage.by_provider} />
          </>
        )}
      </section>
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div style={{ padding: '9px 11px', borderRadius: 'var(--r-md)', background: 'var(--surface-2)', border: '1px solid var(--border)' }}>
      <div style={{ font: '600 9.5px/1 var(--mono)', letterSpacing: '.1em', color: 'var(--text-4)', textTransform: 'uppercase' }}>
        {label}
      </div>
      <div style={{ font: '700 16px/1.2 var(--mono)', color: tone ?? 'var(--text)', marginTop: 4 }}>
        {value}
      </div>
    </div>
  );
}

function Breakdown({ title, rows }: { title: string; rows: { key: string; total_tokens: number; requests: number }[] }) {
  if (!rows.length) return null;
  const max = Math.max(...rows.map((r) => r.total_tokens), 1);
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ font: '600 10px/1 var(--mono)', letterSpacing: '.12em', color: 'var(--text-4)', textTransform: 'uppercase', marginBottom: 7 }}>
        {title}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
        {rows.slice(0, 6).map((row) => (
          <div key={row.key} style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
            <span style={{ flex: '0 0 34%', minWidth: 0, font: '500 11.5px/1.4 var(--font)', color: 'var(--text-2)', wordBreak: 'break-all' }}>
              {row.key}
            </span>
            <span style={{ flex: '1 1 auto', height: 6, borderRadius: 3, background: 'var(--surface-3)', overflow: 'hidden' }}>
              <span style={{ display: 'block', height: '100%', width: `${(row.total_tokens / max) * 100}%`, background: 'var(--accent)' }} />
            </span>
            <span style={{ flex: '0 0 auto', font: '600 11px/1.4 var(--mono)', color: 'var(--text-3)' }}>
              {fmt(row.total_tokens)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function Notice({ tone, children }: { tone: string; children: React.ReactNode }) {
  return (
    <div style={{
      display: 'flex', gap: 9, padding: '11px 12px', borderRadius: 'var(--r-md)',
      background: 'var(--surface-2)', border: `1px solid ${tone}`,
      font: '500 12px/1.5 var(--font)', color: 'var(--text-2)',
    }}>
      <span style={{ flex: '0 0 auto', color: tone }}><Icon name="alert" size={15} /></span>
      <span style={{ minWidth: 0 }}>{children}</span>
    </div>
  );
}
