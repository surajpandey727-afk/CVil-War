/** The job-source catalogue, grouped into the tiers the operator actually reasons about.
 *
 *  `key` is the value the backend expects in `JobSearchRequest.platforms` and the value stored
 *  on `Job.platform`. Keys that exist in `app.core.job_discovery.sources.boards` and
 *  `app.core.automation.platforms` are marked `implemented: true`; everything else is a
 *  catalogue entry the UI shows (and lets the operator enable) but that the backend will
 *  currently ignore. Showing them is deliberate — hiding unimplemented sources is what made
 *  the old UI report "No matching roles" for what was really an unbuilt integration.
 *
 *  `domain` drives the logo lookup in `components/ui/CompanyLogo`.
 */

// Re-exported from types/source (the wire-format source of truth) rather than redeclared here —
// two independent copies of this union is exactly how it drifted out of sync with the backend's
// real values before and broke SourcesPage; see that file for the incident.
export type { SourceHealth } from '@/types/source';
import type { SourceHealth } from '@/types/source';

export interface JobSource {
  key: string;
  label: string;
  domain: string;
  tier: SourceTierId;
  /** True when a backend adapter exists for this key. */
  implemented: boolean;
  /** Default health when the registry endpoint has not reported yet. */
  health: SourceHealth;
  note?: string;
}

export type SourceTierId = 'tier1' | 'tier2' | 'tier4' | 'tier5' | 'careers';

export interface SourceTier {
  id: SourceTierId;
  name: string;
  note: string;
}

// No tier3: removed 2026-08-30 along with every source that was in it, matching the backend
// registry (app.core.job_discovery.source_registry) exactly — see that file's SourceTier
// docstring for why. Keeping the two catalogues in sync by hand is exactly the failure mode
// that let this file drift as far as it had (missing sources the backend had shipped weeks
// earlier); the real fix is `useSources()` reading the live endpoint, this file is only its
// offline fallback.
export const SOURCE_TIERS: SourceTier[] = [
  { id: 'tier1', name: 'Tier 1 — Must use', note: 'Highest volume for London AI/ML and product roles' },
  { id: 'tier2', name: 'Tier 2 — UK job boards', note: 'Consultancies, traditional business, contract' },
  { id: 'tier4', name: 'Tier 4 — Tech & startup', note: 'AI-first companies and scale-ups' },
  { id: 'tier5', name: 'Tier 5 — Specialist recruiters', note: 'Registered agencies' },
  { id: 'careers', name: 'Company career pages', note: 'Monitored directly, checked hourly' },
];

const s = (
  key: string,
  label: string,
  domain: string,
  tier: SourceTierId,
  implemented: boolean,
  health: SourceHealth,
  note?: string,
): JobSource => ({ key, label, domain, tier, implemented, health, note });

export const SOURCES: JobSource[] = [
  // Tier 1 — the browser-automation platforms. Registered in the backend platform registry,
  // but the browser-use API they target no longer exists (B14 in docs/PHASE0_AUDIT.md).
  s('linkedin', 'LinkedIn Jobs', 'linkedin.com', 'tier1', true, 'degraded', 'Browser scraper offline — B14'),
  s('indeed', 'Indeed UK', 'indeed.co.uk', 'tier1', true, 'degraded', 'Browser scraper offline — B14'),
  s('glassdoor', 'Glassdoor', 'glassdoor.co.uk', 'tier1', true, 'degraded', 'Browser scraper offline — B14'),
  s('wellfound', 'Wellfound', 'wellfound.com', 'tier1', false, 'not_implemented'),

  // The keyless API sources that do work today.
  s('remotive', 'Remotive', 'remotive.com', 'tier4', true, 'live'),
  s('jobicy', 'Jobicy', 'jobicy.com', 'tier4', true, 'live'),
  s('arbeitnow', 'Arbeitnow', 'arbeitnow.com', 'tier4', true, 'live'),
  s('remoteok', 'RemoteOK', 'remoteok.com', 'tier4', true, 'live'),
  s('exa', 'Exa semantic search', 'exa.ai', 'tier4', true, 'auth_required', 'Set EXA_API_KEY'),

  s('reed', 'Reed', 'reed.co.uk', 'tier2', true, 'live', 'Live — API key configured'),
  s('adzuna', 'Adzuna', 'adzuna.co.uk', 'tier2', true, 'live', 'Live — app id configured'),
  s('movejobs', 'MoveJobs', 'movejobs.uk', 'tier2', true, 'live', 'Visa-sponsorship-framed UK board'),
  s('tarve', 'Tarve', 'tarve.co.uk', 'tier2', true, 'live', 'Cross-checks the Home Office sponsor register'),
  s(
    'workinstartups', 'WorkInStartups', 'workinstartups.com', 'tier2', false, 'not_implemented',
    'Cloudflare-protected — covered via the Adzuna source instead (same network)',
  ),
  s(
    'findajob', 'Work Hub — GOV.UK', 'jobs.service.gov.uk', 'tier2', false, 'not_implemented',
    "DWP's new jobseeker platform — reconnaissance pending",
  ),
  s(
    'civilservice', 'Civil Service Jobs', 'civilservicejobs.service.gov.uk', 'tier2', false, 'auth_required',
    'Bot-verification gate — connect in Settings, then discovery can be built',
  ),
  s(
    'ukvisajobs', 'UK Visa Jobs', 'ukvisajobs.com', 'tier2', false, 'auth_required',
    'Real catalogue is behind login — connect in Settings, then discovery can be built',
  ),
  // tier4/5 placeholder entries (Otta, Hired, Built In, Technojobs, DevsData, Proactive,
  // Ashdown, DataLogic) were removed 2026-08-30 along with their backend registry
  // counterparts — none had an adapter, a note, or any research behind them; they were
  // exactly the kind of "unknown, never actually checked" entry this cleanup targeted.
];

/** Employers whose career pages are polled directly. One `careers:<slug>` source each.
 *
 *  Mirrors `app.core.job_discovery.source_registry.CAREER_PAGES` exactly, including which
 *  ones actually have a working adapter (`sources.ats.COMPANY_BOARDS`) versus which were
 *  probed and genuinely have no public board (`sources.ats.NO_PUBLIC_BOARD`) — see that
 *  file's 2026-08-30 comment for how each token was live-verified, not guessed.
 */
export const CAREER_PAGES: { slug: string; label: string; domain: string }[] = [
  { slug: 'deepmind', label: 'DeepMind', domain: 'deepmind.google' },
  { slug: 'anthropic', label: 'Anthropic', domain: 'anthropic.com' },
  { slug: 'openai', label: 'OpenAI', domain: 'openai.com' },
  { slug: 'palantir', label: 'Palantir', domain: 'palantir.com' },
  { slug: 'wayve', label: 'Wayve', domain: 'wayve.ai' },
  { slug: 'isomorphic', label: 'Isomorphic Labs', domain: 'isomorphiclabs.com' },
  { slug: 'nvidia', label: 'NVIDIA', domain: 'nvidia.com' },
  { slug: 'c3ai', label: 'C3 AI', domain: 'c3.ai' },
  { slug: 'revolut', label: 'Revolut', domain: 'revolut.com' },
  { slug: 'wise', label: 'Wise', domain: 'wise.com' },
  { slug: 'monzo', label: 'Monzo', domain: 'monzo.com' },
  { slug: 'starling', label: 'Starling Bank', domain: 'starlingbank.com' },
  { slug: 'lseg', label: 'LSEG', domain: 'lseg.com' },
  { slug: 'bloomberg', label: 'Bloomberg', domain: 'bloomberg.com' },
  { slug: 'lendable', label: 'Lendable', domain: 'lendable.co.uk' },
  { slug: 'capitalone', label: 'Capital One', domain: 'capitalone.co.uk' },
  { slug: 'deliveroo', label: 'Deliveroo', domain: 'deliveroo.co.uk' },
  { slug: 'justeat', label: 'Just Eat', domain: 'just-eat.co.uk' },
  { slug: 'ocado', label: 'Ocado', domain: 'ocadogroup.com' },
  { slug: 'asos', label: 'ASOS', domain: 'asos.com' },
  { slug: 'booking', label: 'Booking.com', domain: 'booking.com' },
  { slug: 'spotify', label: 'Spotify', domain: 'spotify.com' },
  { slug: 'expedia', label: 'Expedia', domain: 'expedia.com' },
  { slug: 'trainline', label: 'Trainline', domain: 'thetrainline.com' },
  { slug: 'king', label: 'King', domain: 'king.com' },

  { slug: 'quantexa', label: 'Quantexa', domain: 'quantexa.com' },
  { slug: 'synthesia', label: 'Synthesia', domain: 'synthesia.io' },
  { slug: 'speechmatics', label: 'Speechmatics', domain: 'speechmatics.com' },
  { slug: 'faculty', label: 'Faculty AI', domain: 'faculty.ai' },
  { slug: 'tractable', label: 'Tractable', domain: 'tractable.ai' },
  { slug: 'graphcore', label: 'Graphcore', domain: 'graphcore.ai' },
  { slug: 'improbable', label: 'Improbable', domain: 'improbable.io' },
  { slug: 'gocardless', label: 'GoCardless', domain: 'gocardless.com' },
  { slug: 'zopa', label: 'Zopa', domain: 'zopa.com' },
  { slug: 'truelayer', label: 'TrueLayer', domain: 'truelayer.com' },
  { slug: 'clearbank', label: 'ClearBank', domain: 'clearbank.co.uk' },
  { slug: 'marshmallow', label: 'Marshmallow', domain: 'marshmallow.com' },
  { slug: 'cleo', label: 'Cleo', domain: 'cleo.com' },
  { slug: 'snowflake', label: 'Snowflake', domain: 'snowflake.com' },
  { slug: 'databricks', label: 'Databricks', domain: 'databricks.com' },
  { slug: 'datadog', label: 'Datadog', domain: 'datadoghq.com' },
  { slug: 'fivetran', label: 'Fivetran', domain: 'fivetran.com' },
  { slug: 'similarweb', label: 'Similarweb', domain: 'similarweb.com' },
  { slug: 'contentsquare', label: 'Contentsquare', domain: 'contentsquare.com' },
  { slug: 'alphasense', label: 'AlphaSense', domain: 'alpha-sense.com' },
  { slug: 'stripe', label: 'Stripe', domain: 'stripe.com' },
  { slug: 'notion', label: 'Notion', domain: 'notion.so' },
  { slug: 'figma', label: 'Figma', domain: 'figma.com' },
  { slug: 'canva', label: 'Canva', domain: 'canva.com' },
  { slug: 'airtable', label: 'Airtable', domain: 'airtable.com' },
  { slug: 'asana', label: 'Asana', domain: 'asana.com' },
  { slug: 'miro', label: 'Miro', domain: 'miro.com' },
  { slug: 'linear', label: 'Linear', domain: 'linear.app' },
  { slug: 'vercel', label: 'Vercel', domain: 'vercel.com' },
  { slug: 'gitlab', label: 'GitLab', domain: 'gitlab.com' },
  { slug: 'thoughtworks', label: 'Thoughtworks', domain: 'thoughtworks.com' },
  { slug: 'cohere', label: 'Cohere', domain: 'cohere.com' },
  { slug: 'stabilityai', label: 'Stability AI', domain: 'stability.ai' },
  { slug: 'elevenlabs', label: 'ElevenLabs', domain: 'elevenlabs.io' },
  { slug: 'runwayml', label: 'Runway', domain: 'runwayml.com' },
  { slug: 'perplexity', label: 'Perplexity', domain: 'perplexity.ai' },
  { slug: 'scale', label: 'Scale AI', domain: 'scale.com' },
  { slug: 'together', label: 'Together AI', domain: 'together.ai' },
  { slug: 'harvey', label: 'Harvey', domain: 'harvey.ai' },
  { slug: 'glean', label: 'Glean', domain: 'glean.com' },
  { slug: 'ramp', label: 'Ramp', domain: 'ramp.com' },
  { slug: 'brex', label: 'Brex', domain: 'brex.com' },
  { slug: 'remote', label: 'Remote', domain: 'remote.com' },
];

/** Slugs with NO working adapter — probed against all four ATS providers and genuinely
 *  found nothing (large enterprises typically run Workday or a custom career site). Mirrors
 *  `sources.ats.NO_PUBLIC_BOARD` exactly. Everything else in `CAREER_PAGES` is implemented. */
const CAREER_NO_BOARD = new Set([
  'starling', 'revolut', 'deliveroo',
  'nvidia', 'c3ai', 'lseg', 'bloomberg', 'capitalone', 'justeat', 'booking', 'expedia', 'king',
]);

for (const c of CAREER_PAGES) {
  const implemented = !CAREER_NO_BOARD.has(c.slug);
  SOURCES.push(
    s(`careers:${c.slug}`, c.label, c.domain, 'careers', implemented, implemented ? 'live' : 'not_implemented'),
  );
}

export const SOURCE_BY_KEY: Record<string, JobSource> = Object.fromEntries(
  SOURCES.map((src) => [src.key, src]),
);

/** Keys with a working backend adapter — the sensible default selection. */
export const WORKING_SOURCE_KEYS = SOURCES.filter(
  (src) => src.implemented && src.health === 'live',
).map((src) => src.key);

export function sourceLabel(key: string): string {
  return SOURCE_BY_KEY[key]?.label ?? key;
}

export function sourcesInTier(tier: SourceTierId): JobSource[] {
  return SOURCES.filter((src) => src.tier === tier);
}

export const HEALTH_META: Record<SourceHealth, { label: string; color: string }> = {
  live: { label: 'Live', color: 'var(--applied)' },
  degraded: { label: 'Degraded', color: 'var(--review)' },
  auth_required: { label: 'Sign-in required', color: 'var(--rejected)' },
  rate_limited: { label: 'Rate limited', color: 'var(--review)' },
  // The portal refuses server-side automation but is reachable through the same one-time
  // browser sign-in Settings already offers (e.g. Civil Service Jobs, UK Visa Jobs) — a real,
  // usable rung, not a failure state, so it gets its own label rather than reading as broken.
  interactive_available: { label: 'Connect to use', color: 'var(--review)' },
  unavailable: { label: 'Unavailable', color: 'var(--rejected)' },
  not_implemented: { label: 'Not yet wired', color: 'var(--text-4)' },
};
