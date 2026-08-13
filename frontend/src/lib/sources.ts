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

export type SourceHealth = 'live' | 'degraded' | 'auth_required' | 'not_implemented';

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

export type SourceTierId = 'tier1' | 'tier2' | 'tier3' | 'tier4' | 'tier5' | 'careers';

export interface SourceTier {
  id: SourceTierId;
  name: string;
  note: string;
}

export const SOURCE_TIERS: SourceTier[] = [
  { id: 'tier1', name: 'Tier 1 — Must use', note: 'Highest volume for London AI/ML and product roles' },
  { id: 'tier2', name: 'Tier 2 — UK job boards', note: 'Consultancies, traditional business, contract' },
  { id: 'tier3', name: 'Tier 3 — Government & public sector', note: 'Statistical Scientist, Operational Research, AI Specialist' },
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

  s('reed', 'Reed', 'reed.co.uk', 'tier2', false, 'not_implemented', 'Needs a Reed API key'),
  s('totaljobs', 'Totaljobs', 'totaljobs.com', 'tier2', false, 'not_implemented'),
  s('cvlibrary', 'CV-Library', 'cv-library.co.uk', 'tier2', false, 'not_implemented'),
  s('cwjobs', 'CWJobs', 'cwjobs.co.uk', 'tier2', false, 'not_implemented'),
  s('jobsite', 'Jobsite', 'jobsite.co.uk', 'tier2', false, 'not_implemented'),
  s('adzuna', 'Adzuna', 'adzuna.co.uk', 'tier2', false, 'not_implemented', 'Needs an Adzuna app id'),
  s('jobserve', 'JobServe', 'jobserve.com', 'tier2', false, 'not_implemented'),
  s('guardianjobs', 'The Guardian Jobs', 'jobs.theguardian.com', 'tier2', false, 'not_implemented'),

  s('civilservice', 'Civil Service Jobs', 'civilservicejobs.service.gov.uk', 'tier3', false, 'not_implemented'),
  s('findajob', 'Find a job — GOV.UK', 'gov.uk', 'tier3', false, 'not_implemented'),
  s('nhsjobs', 'NHS Jobs', 'jobs.nhs.uk', 'tier3', false, 'not_implemented'),
  s('ddat', 'Digital & Data Jobs', 'ddat.gov.uk', 'tier3', false, 'not_implemented'),

  s('otta', 'Otta / Welcome to the Jungle', 'otta.com', 'tier4', false, 'not_implemented'),
  s('hired', 'Hired', 'hired.com', 'tier4', false, 'not_implemented'),
  s('builtin', 'Built In', 'builtin.com', 'tier4', false, 'not_implemented'),
  s('technojobs', 'Technojobs', 'technojobs.co.uk', 'tier4', false, 'not_implemented'),

  s('devsdata', 'DevsData LLC', 'devsdata.com', 'tier5', false, 'not_implemented'),
  s('proactive', 'Proactive IT Appointments', 'proactive.uk.com', 'tier5', false, 'not_implemented'),
  s('ashdown', 'Ashdown Group', 'ashdowngroup.com', 'tier5', false, 'not_implemented'),
  s('datalogic', 'DataLogic', 'datalogic-recruitment.co.uk', 'tier5', false, 'not_implemented'),
];

/** Employers whose career pages are polled directly. One `careers:<slug>` source each. */
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
];

for (const c of CAREER_PAGES) {
  SOURCES.push(s(`careers:${c.slug}`, c.label, c.domain, 'careers', false, 'not_implemented'));
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
  not_implemented: { label: 'Not yet wired', color: 'var(--text-4)' },
};
