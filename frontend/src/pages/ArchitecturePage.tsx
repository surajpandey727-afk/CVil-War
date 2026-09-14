const card: React.CSSProperties = {
  background: 'var(--surface)', border: '1px solid var(--border)',
  borderRadius: 'var(--r-lg)', boxShadow: 'var(--shadow-1)',
};

interface Node {
  x: number; y: number; w: number; h: number;
  label: string; sub?: string; color: string; soft: string;
}

const NODES: Record<string, Node> = {
  web: { x: 20, y: 20, w: 200, h: 56, label: 'Frontend', sub: 'React + Vite · this app', color: 'var(--accent)', soft: 'var(--accent-soft)' },
  api: { x: 20, y: 116, w: 200, h: 56, label: 'Backend API', sub: 'FastAPI (uvicorn)', color: 'var(--accent)', soft: 'var(--accent-soft)' },
  worker: { x: 260, y: 116, w: 200, h: 56, label: 'Worker', sub: 'arq — apply, discovery, review', color: 'var(--offer)', soft: 'var(--offer-soft)' },
  redis: { x: 260, y: 212, w: 200, h: 56, label: 'Redis', sub: 'queue + pub/sub + cache', color: 'var(--secondary)', soft: 'var(--secondary-soft)' },
  db: { x: 20, y: 212, w: 200, h: 56, label: 'Postgres', sub: 'Supabase', color: 'var(--secondary)', soft: 'var(--secondary-soft)' },
  gateway: { x: 500, y: 116, w: 200, h: 56, label: 'OmniRoute', sub: 'LLM gateway · "Full-Send"', color: 'var(--review)', soft: 'var(--review-soft)' },
  llms: { x: 500, y: 212, w: 200, h: 56, label: 'LLM providers', sub: 'codex · groq · gemini · deepseek', color: 'var(--text-3)', soft: 'var(--surface-2)' },
  browser: { x: 260, y: 20, w: 200, h: 56, label: 'Browser automation', sub: 'Playwright, assisted login', color: 'var(--offer)', soft: 'var(--offer-soft)' },
  portals: { x: 500, y: 20, w: 200, h: 56, label: 'Job portals', sub: 'LinkedIn, Greenhouse, Lever…', color: 'var(--text-3)', soft: 'var(--surface-2)' },
  external: { x: 740, y: 116, w: 200, h: 56, label: 'External APIs', sub: 'Reed · Adzuna · Exa · Gmail · Apollo', color: 'var(--text-3)', soft: 'var(--surface-2)' },
};

const EDGES: [string, string, string?][] = [
  ['web', 'api', 'HTTPS + WS'],
  ['api', 'db'],
  ['api', 'redis', 'enqueue'],
  ['worker', 'redis'],
  ['worker', 'db'],
  ['worker', 'browser'],
  ['browser', 'portals'],
  ['worker', 'gateway', 'chat completions'],
  ['gateway', 'llms'],
  ['api', 'gateway', 'fit / résumé'],
  ['api', 'external'],
  ['worker', 'external'],
];

const AGENTS = [
  { key: 'discovery', label: 'Discovery', note: 'sources every enabled portal' },
  { key: 'eligibility', label: 'Eligibility', note: 'sponsorship classification' },
  { key: 'scoring', label: 'Scoring', note: 'which résumé fits, and why' },
  { key: 'application', label: 'Application', note: 'submits through the policy gate' },
  { key: 'tracking', label: 'Tracking', note: 'recruiter reply detection' },
];

function centerOf(n: Node): [number, number] {
  return [n.x + n.w / 2, n.y + n.h / 2];
}

function edgePath(from: Node, to: Node): string {
  const [fx, fy] = centerOf(from);
  const [tx, ty] = centerOf(to);
  // Route from the nearer edge, not the center, so the line doesn't run through the box.
  const dx = tx - fx;
  const dy = ty - fy;
  const startX = fx + (Math.abs(dx) > Math.abs(dy) ? Math.sign(dx) * from.w / 2 : 0);
  const startY = fy + (Math.abs(dx) > Math.abs(dy) ? 0 : Math.sign(dy) * from.h / 2);
  const endX = tx - (Math.abs(dx) > Math.abs(dy) ? Math.sign(dx) * to.w / 2 : 0);
  const endY = ty - (Math.abs(dx) > Math.abs(dy) ? 0 : Math.sign(dy) * to.h / 2);
  return `M${startX},${startY} L${endX},${endY}`;
}

/**
 * A static map of what is actually built, not an aspiration — every node and edge here
 * corresponds to a real, running piece of the system verified this session (worker started
 * and consumed a real queued job, OmniRoute answered a real completion, Supabase holds the
 * real schema, Playwright drives the real assisted-login sessions). Distinct from Automation →
 * Agent ops, which is the LIVE view of the same system while it runs; this is the fixed
 * picture of how the pieces fit together.
 */
export default function ArchitecturePage() {
  return (
    <div style={{ animation: 'aaUp .4s var(--ease) both', maxWidth: 1000 }}>
      <div style={{ marginBottom: 18 }}>
        <h1 style={{ margin: 0, font: '800 24px/1.1 var(--font)', letterSpacing: '-.03em' }}>Architecture</h1>
        <p style={{ margin: '6px 0 0', font: '500 13px/1.4 var(--font)', color: 'var(--text-3)' }}>
          What is actually built and how it fits together. For what it is doing right now, see{' '}
          <span style={{ color: 'var(--text-2)', fontWeight: 700 }}>Automation → Agent ops</span>.
        </p>
      </div>

      <div style={{ ...card, padding: 16, marginBottom: 16, overflowX: 'auto' }}>
        <svg viewBox="0 0 960 300" width="100%" style={{ minWidth: 820, display: 'block' }}>
          <defs>
            <marker id="arch-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M0,0 L10,5 L0,10 z" fill="var(--text-4)" />
            </marker>
          </defs>
          {EDGES.map(([fromKey, toKey, label], i) => {
            const from = NODES[fromKey]!;
            const to = NODES[toKey]!;
            const [mx, my] = [(centerOf(from)[0] + centerOf(to)[0]) / 2, (centerOf(from)[1] + centerOf(to)[1]) / 2];
            return (
              <g key={i}>
                <path d={edgePath(from, to)} fill="none" stroke="var(--border)" strokeWidth={1.5} markerEnd="url(#arch-arrow)" />
                {label && (
                  <text x={mx} y={my - 6} textAnchor="middle" fontSize="9.5" fontWeight={600} fill="var(--text-4)" style={{ fontFamily: 'var(--mono)' }}>
                    {label}
                  </text>
                )}
              </g>
            );
          })}
          {Object.values(NODES).map((n) => (
            <g key={n.label}>
              <rect x={n.x} y={n.y} width={n.w} height={n.h} rx={10} fill={n.soft} stroke={n.color} strokeWidth={1.2} />
              <text x={n.x + 14} y={n.y + 24} fontSize="13" fontWeight={700} fill="var(--text)" style={{ fontFamily: 'var(--font)' }}>
                {n.label}
              </text>
              <text x={n.x + 14} y={n.y + 41} fontSize="10.5" fontWeight={500} fill="var(--text-3)" style={{ fontFamily: 'var(--font)' }}>
                {n.sub}
              </text>
            </g>
          ))}
        </svg>
      </div>

      <div style={{ ...card, padding: 18 }}>
        <div style={{ font: '700 13px/1 var(--font)', marginBottom: 4 }}>The agent pipeline</div>
        <p style={{ margin: '0 0 14px', font: '500 12px/1.5 var(--font)', color: 'var(--text-3)' }}>
          Five single-responsibility agents, each its own row on Automation → Agent ops when it runs.
        </p>
        <div style={{ display: 'flex', alignItems: 'stretch', gap: 0, overflowX: 'auto' }}>
          {AGENTS.map((a, i) => (
            <div key={a.key} style={{ display: 'flex', alignItems: 'center', flex: '0 0 auto' }}>
              <div style={{
                width: 168, minHeight: 78, padding: '12px 14px', borderRadius: 'var(--r-lg)',
                border: '1px solid var(--border)', background: 'var(--surface-2)',
              }}>
                <div style={{ font: '700 12.5px/1.2 var(--font)' }}>{a.label}</div>
                <div style={{ font: '500 10.5px/1.4 var(--font)', color: 'var(--text-3)', marginTop: 4 }}>{a.note}</div>
              </div>
              {i < AGENTS.length - 1 && (
                <div style={{ width: 20, flex: '0 0 auto', textAlign: 'center', color: 'var(--text-4)', font: '700 14px/1 var(--font)' }}>→</div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
