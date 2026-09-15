import { useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate } from 'react-router-dom';

import CompanyLogo from '@/components/ui/CompanyLogo';
import Icon from '@/components/ui/Icon';
import JobDrawer from '@/components/jobs/JobDrawer';
import { useJobs, useSearchJobs, useUpdateJobStatus } from '@/hooks/useJobs';
import { useCreateApplicationBatch } from '@/hooks/useApplications';
import { useDashboardStats } from '@/hooks/useAnalytics';
import { useResumes } from '@/hooks/useResumes';
import { useSettings } from '@/hooks/useSettings';
import { useSources } from '@/hooks/useSources';
import { useAppStore } from '@/store/useAppStore';
import { useDiscoveryStore } from '@/store/useDiscoveryStore';
import { atsColor, atsPercent, relativeTime, jcSponsorMeta, jobStatusMeta } from '@/lib/status';
import { ROLE_FAMILIES, familyForTitle, queryForTitles, type RoleFamily } from '@/lib/roleTargets';
import {
  HEALTH_META, SOURCE_BY_KEY, SOURCE_TIERS, sourceLabel, sourcesInTier,
} from '@/lib/sources';
import '@/styles/jobs-command.css';
import type { Job } from '@/types/job';

const card: React.CSSProperties = {
  background: 'var(--jc-surface)', border: '1px solid var(--jc-border)',
  borderRadius: 'var(--jc-r-lg)', boxShadow: 'var(--jc-shadow-1)',
};

const SENIORITY = ['Junior', 'Mid', 'Senior', 'Lead', 'Principal'];
const POSTED: { key: '24h' | '7d' | '30d' | 'any'; label: string; days: number }[] = [
  { key: '24h', label: '24h', days: 1 },
  { key: '7d', label: '7d', days: 7 },
  { key: '30d', label: '30d', days: 30 },
  { key: 'any', label: 'Any', days: 3650 },
];

/** Lowest number in a salary string, in thousands. `null` when no band is published. */
function salaryK(range: string | null): number | null {
  if (!range) return null;
  const nums = range.match(/\d[\d,.]*/g);
  if (!nums) return null;
  const values = nums.map((n) => {
    const v = Number(n.replace(/[,]/g, ''));
    return v > 1000 ? v / 1000 : v;
  });
  return Math.min(...values);
}

function ageInDays(iso: string | null): number {
  if (!iso) return 9999;
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return 9999;
  return (Date.now() - t) / 86_400_000;
}

/**
 * Which filter is hiding the jobs, and the button that undoes it.
 *
 * Built because "23 stored roles were filtered out" sent the operator hunting through eight
 * controls to find which one was responsible — the honest answer was a remote-only toggle they
 * had set days earlier and forgotten. Naming the control and offering to clear it turns a dead
 * end into one click.
 */
function FilterCulprits({ rejected }: { rejected: Record<string, number> }) {
  const { patchFilters, activeFamilies, toggleFamily, setSources } = useDiscoveryStore();

  const LABELS: Record<string, { label: string; clear: () => void }> = {
    remoteOnly: { label: 'Remote or hybrid only', clear: () => patchFilters({ remoteOnly: false }) },
    minAtsScore: { label: 'Minimum ATS match', clear: () => patchFilters({ minAtsScore: 0 }) },
    hideApplied: { label: 'Hide already applied', clear: () => patchFilters({ hideApplied: false }) },
    postedWithin: { label: 'Posted within', clear: () => patchFilters({ postedWithin: 'any' }) },
    publishedSalaryOnly: {
      label: 'Published salary only', clear: () => patchFilters({ publishedSalaryOnly: false }),
    },
    minSalaryK: { label: 'Minimum salary', clear: () => patchFilters({ minSalaryK: 0 }) },
    seniority: { label: 'Seniority', clear: () => patchFilters({ seniority: [] }) },
    roleTargets: {
      label: 'Role target chips',
      clear: () => activeFamilies.forEach((f) => toggleFamily(f)),
    },
    sources: { label: 'Disabled sources', clear: () => setSources([]) },
  };

  // Worst offender first — that is almost always the one to clear.
  const entries = Object.entries(rejected)
    .filter(([key, count]) => count > 0 && LABELS[key])
    .sort((a, b) => b[1] - a[1]);

  if (!entries.length) return null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 12, width: '100%', maxWidth: 460 }}>
      {entries.map(([key, count]) => (
        <div
          key={key}
          style={{
            display: 'flex', alignItems: 'center', gap: 10, padding: '8px 11px',
            borderRadius: 'var(--jc-r-md)', background: 'var(--jc-surface-2)',
            border: '1px solid var(--jc-border)',
          }}
        >
          <span style={{ flex: 1, textAlign: 'left', font: '600 12px/1.3 var(--font)', color: 'var(--jc-text-2)' }}>
            {LABELS[key]!.label}
          </span>
          <span style={{ font: '600 11px/1 var(--mono)', color: 'var(--jc-status-rejected)' }}>
            {`−${count} hidden`}
          </span>
          <button
            onClick={LABELS[key]!.clear}
            className="jc-btn"
            style={{
              height: 24, padding: '0 9px', borderRadius: 'var(--jc-r-sm)',
              font: '600 11px/1 var(--font)', border: '1px solid var(--jc-accent-line)',
              background: 'var(--jc-accent-soft)', color: 'var(--jc-accent-2)',
            }}
          >
            Clear
          </button>
        </div>
      ))}
    </div>
  );
}

export default function JobSearchPage() {
  const navigate = useNavigate();
  const notify = useAppStore((s) => s.showNotification);

  const {
    query, location, appliedLocation, appliedQuery, activeTitles, activeFamilies,
    enabledSources, filters, selectedJobIds,
    setQuery, setLocation, commitSearch, toggleFamily, toggleSource, patchFilters, resetFilters,
    toggleJob, setSelected, clearSelection,
  } = useDiscoveryStore();

  // The location and title filters go to the server, which matches them against the stored
  // job location rather than the rendered text. Doing this in the browser is what made a
  // London search return a Cleveland accounts-payable role: the filter was never applied at
  // all, and `total` counted every job the account had ever cached.
  const { data, isLoading, isError } = useJobs(1, 100, undefined, {
    location: appliedLocation,
    query: appliedQuery,
  });
  const { data: resumeData } = useResumes();
  // The authoritative list of what exists, from the backend registry rather than the static
  // catalogue. Used only to decide whether a source is one the operator could have disabled.
  const { catalogue: liveCatalogue } = useSources();
  const { data: settings } = useSettings();
  const search = useSearchJobs();
  const createApps = useCreateApplicationBatch();
  const updateJobStatus = useUpdateJobStatus();
  // Real, backend-aggregated counts — the same source the Dashboard's own stat tiles use.
  // The command header intentionally does not invent pipeline stages (e.g. a generic
  // "shortlisted"/"ready" bucket) that have no field behind them; every number here maps
  // to something the API actually computes.
  const { data: stats } = useDashboardStats();

  const [drawerJob, setDrawerJob] = useState<Job | null>(null);
  const [runResumeId, setRunResumeId] = useState<string>('auto');

  const resumes = useMemo(() => resumeData?.items ?? [], [resumeData]);
  const allJobs = useMemo(() => data?.items ?? [], [data]);
  // An empty selection means "no restriction", not "exclude everything" — the operator has
  // simply never narrowed the list.
  const restrictSources = enabledSources.length > 0;
  const knownKeys = useMemo(
    () => new Set(liveCatalogue.tiers.flatMap((t) => t.sources.map((src) => src.key))),
    [liveCatalogue],
  );

  /** Client-side filtering. The backend returns the stored corpus; these are the operator's
   *  standing preferences, applied to whatever is in it.
   *
   *  Alongside the surviving jobs this counts *which* control rejected each one. An empty
   *  screen that says "23 roles were filtered out" and leaves you to guess which of eight
   *  controls did it is barely better than showing nothing: the operator's actual question is
   *  "what is hiding my jobs, and how do I undo it". Each job is charged to the first filter
   *  that rejects it, so the counts sum to the number hidden rather than double-counting. */
  const { jobs, rejected } = useMemo(() => {
    const maxAge = POSTED.find((p) => p.key === filters.postedWithin)?.days ?? 3650;
    const rejected: Record<string, number> = {};
    const reject = (key: string) => {
      rejected[key] = (rejected[key] ?? 0) + 1;
      return false;
    };
    const out = allJobs.filter((j) => {
      // Only exclude a source the operator has actually switched off. A job whose source
      // the frontend catalogue does not recognise must never be dropped silently: the static
      // catalogue in lib/sources marks every `careers:*` entry not_implemented, which was
      // false for nine of them and hid 28 of 55 London jobs. The live registry decides what
      // exists; this filter only applies the operator's own choices on top of it.
      if (restrictSources && knownKeys.has(j.platform) && !enabledSources.includes(j.platform)) {
        return reject('sources');
      }
      if (atsPercent(j.match_score) < filters.minAtsScore && j.match_score != null) {
        return reject('minAtsScore');
      }
      if (filters.remoteOnly && !j.remote) return reject('remoteOnly');
      // Was `status !== 'new' && status !== 'discovered'`, which also caught 'saved' —
      // added by this same redesign as a genuinely distinct, still-relevant status. That
      // meant saving a job for later immediately hid it from the default view (hideApplied
      // is on by default), the opposite of what "save for later" is for. Only an actual
      // 'applied' status is what this filter's own label promises to hide.
      if (filters.hideApplied && j.status === 'applied') {
        return reject('hideApplied');
      }
      // A missing posted_date is unknown, not old: excluding it would silently drop every
      // source that does not publish one (Arbeitnow, several career pages).
      if (j.posted_date && ageInDays(j.posted_date) > maxAge) return reject('postedWithin');
      const band = salaryK(j.salary_range);
      if (filters.publishedSalaryOnly && band == null) return reject('publishedSalaryOnly');
      if (filters.minSalaryK > 0 && band != null && band < filters.minSalaryK) {
        return reject('minSalaryK');
      }
      if (filters.seniority.length) {
        const level = (j.experience_level ?? '').toLowerCase();
        if (!filters.seniority.some((s) => level.includes(s.toLowerCase()))) {
          return reject('seniority');
        }
      }
      if (activeFamilies.length && !activeFamilies.includes(familyForTitle(j.title))) {
        return reject('roleTargets');
      }
      return true;
    });
    out.sort((a, b) => {
      if (filters.sort === 'match') return atsPercent(b.match_score) - atsPercent(a.match_score);
      if (filters.sort === 'newest') return ageInDays(a.posted_date) - ageInDays(b.posted_date);
      return (salaryK(b.salary_range) ?? 0) - (salaryK(a.salary_range) ?? 0);
    });
    return { jobs: out, rejected };
  }, [allJobs, enabledSources, restrictSources, knownKeys, filters, activeFamilies]);

  const selected = selectedJobIds.filter((id) => jobs.some((j) => j.id === id));
  const allSelected = jobs.length > 0 && selected.length === jobs.length;

  const openDrawer = (job: Job) => setDrawerJob(job);

  /** Queue this job for the agent with the CV chosen in the drawer. */
  const onApplyWithAgent = (job: Job, resumeId: string | null) => {
    createApps.mutate(
      { job_ids: [job.id], resume_id: resumeId, apply_mode: 'review' },
      {
        onSuccess: () => {
          notify(`Queued for review · ${job.title}`, 'success');
          setDrawerJob(null);
        },
        onError: () => notify('Could not queue this application', 'error'),
      },
    );
  };

  /**
   * The operator is applying on the external site themselves.
   *
   * The link opens the real page; this only records the intent. Nothing is marked applied —
   * CVil-War opened a tab, which is not evidence that anyone submitted anything, and
   * claiming otherwise is exactly the false "Applied" the product exists to avoid.
   */
  const onApplyManually = (url: string) => {
    notify(
      `Opening ${new URL(url).hostname} — record the outcome yourself once you have applied.`,
      'info',
    );
  };

  /** Save a job for later, or un-save it. Previously there was no way to do this at all —
   *  a job only ever moved status as a side effect of creating an application. */
  const toggleSaveJob = (job: Job) => {
    const next = job.status === 'saved' ? 'new' : 'saved';
    updateJobStatus.mutate(
      { jobId: job.id, status: next },
      {
        onSuccess: () => notify(next === 'saved' ? 'Saved for later' : 'Removed from saved', 'success'),
        onError: () => notify('Could not update this job', 'error'),
      },
    );
  };


  const runSearch = () => {
    const effective = query.trim() || queryForTitles(activeTitles);
    if (!effective) {
      notify('Add at least one role target, or type a search term', 'warning');
      return;
    }
    // Empty means "every live source", the same convention this file already applies to
    // filtering results (`restrictSources`, above) and that SourcesPage/platforms_enabled
    // use for the background scheduler. Without this, a first-time visitor who has never
    // touched the per-device source filter got a dead-end "none of the enabled sources
    // have a working adapter yet" the moment they tried to search — discovery blocked
    // entirely, not merely narrowed, on a screen whose only job is to search.
    //
    // The fallback also intersects with the operator's backend `platforms_enabled`
    // (Settings/Sources page) when it's been narrowed. Previously it only checked adapter
    // health, so disabling a source in Settings — the control that also gates the
    // background discovery worker — had no effect on a manual search here: a source the
    // operator explicitly turned off kept getting searched anyway the moment the per-device
    // filter was untouched, which is the opposite of what disabling it means.
    const settingsEnabled = settings?.platforms_enabled;
    const respectingSettings = settingsEnabled && settingsEnabled.length > 0
      ? liveCatalogue.live_keys.filter((k) => settingsEnabled.includes(k))
      : liveCatalogue.live_keys;
    const usable = enabledSources.length > 0
      ? enabledSources.filter((k) => SOURCE_BY_KEY[k]?.implemented)
      : respectingSettings;
    if (!usable.length) {
      notify('None of the enabled sources have a working adapter yet', 'warning');
      return;
    }
    // Promote the typed boxes to the filter the list is fetched with, so the results shown
    // after a search are the results of *that* search.
    commitSearch();
    search.mutate(
      { query: effective, location: location.trim() || undefined, platforms: usable, limit: 100 },
      {
        onSuccess: (r) => notify(`Found ${r.total} matching roles across ${usable.length} sources`, 'success'),
        onError: () => notify('Search failed — try again', 'error'),
      },
    );
  };

  /** Queue every ticked job in one request. `review` keeps the approval gate before submit;
   *  the worker then emits progress over the existing application WebSocket. */
  const startRun = () => {
    if (!selected.length) return;
    createApps.mutate(
      {
        job_ids: selected,
        apply_mode: 'review',
        resume_id: runResumeId === 'auto' ? null : runResumeId,
      },
      {
        onSuccess: (apps) => {
          notify(`Run started · ${apps.length} applications queued`, 'success');
          clearSelection();
          navigate('/applications');
        },
        onError: () => notify('Could not queue the run', 'error'),
      },
    );
  };

  const enabledInTier = (tier: (typeof SOURCE_TIERS)[number]['id']) =>
    sourcesInTier(tier).filter((s) => enabledSources.includes(s.key)).length;

  // Real, backend-computed pipeline stages — never a fabricated "shortlisted"/"ready"
  // bucket with no field behind it. Opportunities is the deduped corpus size; the rest
  // mirror the ApplicationStatus lifecycle exactly.
  const pipeline = [
    { key: 'opportunities', label: 'Opportunities', value: stats?.unique_jobs ?? allJobs.length },
    { key: 'queued', label: 'Queued', value: stats?.applications_queued ?? 0 },
    { key: 'review', label: 'Pending review', value: stats?.applications_pending ?? 0 },
    { key: 'applied', label: 'Applied', value: stats?.applications_applied ?? 0 },
    { key: 'interview', label: 'Interview', value: stats?.applications_interview ?? 0 },
    { key: 'offer', label: 'Offer', value: stats?.applications_offer ?? 0 },
  ] as const;

  return (
    <div data-jc-theme="" className="jc-leather" style={{ animation: 'aaUp .4s var(--ease) both', margin: -20, padding: 20 }}>
      {/* ---- Command header ------------------------------------------------------------ */}
      <div className="jc-header">
        <div>
          <div className="jc-display">Jobs</div>
          <div className="jc-body" style={{ marginTop: 4 }}>
            Discover, evaluate, and act on every opportunity in one command surface.
          </div>
        </div>
      </div>

      {/* ---- Pipeline: glanceable in under three seconds -------------------------------- */}
      <div className="jc-pipeline">
        {pipeline.map((stage) => (
          <div key={stage.key} className="jc-pipeline-stage">
            <span className="jc-pipeline-count" style={{ color: stage.key === 'opportunities' ? 'var(--jc-text)' : 'var(--jc-accent-2)' }}>
              {stage.value}
            </span>
            <span className="jc-pipeline-label">{stage.label}</span>
          </div>
        ))}
      </div>

      <div className="jc-layout" style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
      {/* ---- Left rail: targets, filters, sources ------------------------------------ */}
      <div className="jc-rail" style={{ flex: '0 0 268px', display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div style={{ ...card, padding: 14 }}>
          <RailHead label="Role targets" action="Edit" onAction={() => navigate('/targets')} />
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {(Object.keys(ROLE_FAMILIES) as RoleFamily[]).map((f) => (
              <Chip key={f} on={activeFamilies.includes(f)} onClick={() => toggleFamily(f)}>
                {ROLE_FAMILIES[f].short}
              </Chip>
            ))}
          </div>
          <div style={{ font: '500 11px/1.4 var(--font)', color: 'var(--text-4)', marginTop: 10 }}>
            {activeTitles.length} titles active · {activeFamilies.length ? 'filtered' : 'all families'}
          </div>
        </div>

        <div style={{ ...card, padding: 14 }}>
          <div style={{ font: '700 12.5px/1 var(--font)', marginBottom: 12 }}>Filters</div>

          <RangeRow
            label="MIN ATS MATCH" value={`${filters.minAtsScore}%`}
            min={0} max={95} step={5} current={filters.minAtsScore}
            onChange={(v) => patchFilters({ minAtsScore: v })}
          />
          <RangeRow
            label="MIN SALARY" value={filters.minSalaryK ? `£${filters.minSalaryK}k` : 'Any'}
            min={0} max={150} step={5} current={filters.minSalaryK}
            onChange={(v) => patchFilters({ minSalaryK: v })}
          />

          <FieldLabel>SENIORITY</FieldLabel>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 16 }}>
            {SENIORITY.map((s) => (
              <Chip
                key={s} small on={filters.seniority.includes(s)}
                onClick={() => patchFilters({
                  seniority: filters.seniority.includes(s)
                    ? filters.seniority.filter((x) => x !== s)
                    : [...filters.seniority, s],
                })}
              >
                {s}
              </Chip>
            ))}
          </div>

          <FieldLabel>POSTED WITHIN</FieldLabel>
          <div style={{ display: 'flex', gap: 6, marginBottom: 16 }}>
            {POSTED.map((p) => (
              <Chip key={p.key} small on={filters.postedWithin === p.key} onClick={() => patchFilters({ postedWithin: p.key })}>
                {p.label}
              </Chip>
            ))}
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
            <CheckRow label="Remote or hybrid only" on={filters.remoteOnly} onClick={() => patchFilters({ remoteOnly: !filters.remoteOnly })} />
            <CheckRow label="Hide already applied" on={filters.hideApplied} onClick={() => patchFilters({ hideApplied: !filters.hideApplied })} />
            <CheckRow label="Published salary only" on={filters.publishedSalaryOnly} onClick={() => patchFilters({ publishedSalaryOnly: !filters.publishedSalaryOnly })} />
          </div>

          <button onClick={resetFilters} style={ghostBtn}>Reset filters</button>
        </div>

        <div style={{ ...card, padding: 14 }}>
          {/* Deep link, not a bare /settings: "Manage" landing at the top of a long page with
              no indication of where to look is what made this flow a dead end. */}
          <RailHead label="Sources" action="Manage" onAction={() => navigate('/settings?section=platforms')} />
          {SOURCE_TIERS.map((tier) => (
            <div key={tier.id} style={{ marginBottom: 10 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', padding: '6px 2px' }}>
                <span style={{ font: '600 10px/1 var(--mono)', letterSpacing: '.12em', color: 'var(--text-4)' }}>
                  {tier.name.replace(/ —.*/, '').toUpperCase()}
                </span>
                <span style={{ font: '600 10px/1 var(--mono)', color: 'var(--text-4)' }}>
                  {enabledInTier(tier.id)}/{sourcesInTier(tier.id).length}
                </span>
              </div>
              {sourcesInTier(tier.id).slice(0, 6).map((src) => {
                const on = enabledSources.includes(src.key);
                const meta = HEALTH_META[src.health];
                return (
                  <button
                    key={src.key} onClick={() => toggleSource(src.key)} title={src.note ?? meta.label}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 9, width: '100%', height: 30,
                      padding: '0 8px', borderRadius: 'var(--r-sm)', border: 0, cursor: 'pointer',
                      background: 'transparent', font: '600 11.5px/1 var(--font)',
                      color: on ? 'var(--text-2)' : 'var(--text-4)',
                    }}
                  >
                    <span style={{ width: 6, height: 6, borderRadius: '50%', background: on ? meta.color : 'var(--text-4)', flex: '0 0 auto' }} />
                    <span style={{ flex: '1 1 auto', textAlign: 'left', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {src.label}
                    </span>
                    {!src.implemented && (
                      <span style={{ font: '600 9px/1 var(--mono)', color: 'var(--text-4)' }}>SOON</span>
                    )}
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      </div>

      {/* ---- Results ------------------------------------------------------------------ */}
      <div style={{ flex: '1 1 auto', minWidth: 0 }}>
        <form
          onSubmit={(e) => { e.preventDefault(); runSearch(); }}
          style={{ ...card, display: 'flex', gap: 10, padding: 12, marginBottom: 12, flexWrap: 'wrap' }}
        >
          <SearchField icon="search" label="Job title or keywords" placeholder={queryForTitles(activeTitles.slice(0, 2)) || 'Job title, skills, or company'} value={query} onChange={setQuery} grow={2} />
          <SearchField icon="mappin" label="Location" placeholder="London, UK" value={location} onChange={setLocation} grow={1} />
          <button
            type="submit" disabled={search.isPending}
            className="jc-btn jc-btn-primary"
            style={{ flex: '0 0 auto', height: 40, padding: '0 18px' }}
          >
            {search.isPending ? 'Searching…' : 'Search'}
          </button>
        </form>

        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12, flexWrap: 'wrap' }}>
          <button
            onClick={() => setSelected(allSelected ? [] : jobs.map((j) => j.id))}
            style={{ display: 'flex', alignItems: 'center', gap: 9, background: 'none', border: 0, padding: 0, cursor: 'pointer' }}
          >
            <CheckBox on={allSelected} />
            <span style={{ font: '600 12px/1 var(--font)', color: 'var(--text-2)' }}>
              {jobs.length} roles · {selected.length} selected
            </span>
          </button>
          <div style={{ flex: '1 1 auto' }} />
          <div style={{ display: 'flex', gap: 6 }}>
            {(['match', 'newest', 'salary'] as const).map((k) => (
              <Chip key={k} small on={filters.sort === k} onClick={() => patchFilters({ sort: k })}>
                {k[0]!.toUpperCase() + k.slice(1)}
              </Chip>
            ))}
          </div>
        </div>

        {isError ? (
          <div style={{ ...card, ...notice }}>
            <span style={{ color: 'var(--failed)' }}><Icon name="alert" size={16} /></span>
            Couldn&apos;t load jobs. Retry in a moment.
          </div>
        ) : isLoading ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} style={{ ...card, height: 118, background: 'linear-gradient(90deg,var(--surface-2),var(--hover),var(--surface-2))', backgroundSize: '200% 100%', animation: 'aaShimmer 1.3s linear infinite' }} />
            ))}
          </div>
        ) : jobs.length === 0 ? (
          <div style={{ ...card, ...notice, flexDirection: 'column', gap: 8, padding: '46px 20px' }}>
            <div style={{ display: 'grid', placeItems: 'center', width: 44, height: 44, borderRadius: 12, background: 'var(--accent-soft)', color: 'var(--jc-accent-2)' }}>
              <Icon name="search" size={20} />
            </div>
            <div style={{ font: '700 14px/1.2 var(--font)', color: 'var(--text)' }}>
              {allJobs.length
                ? 'No roles match these filters'
                : appliedLocation.trim() || appliedQuery.trim()
                  ? 'Nothing stored matches that search'
                  : 'No jobs yet'}
            </div>
            <span>
              {/* Three different situations that all used to render as "No jobs yet". The
                  location filter now runs on the server, so an empty list can mean "nothing
                  in London yet" — which is a prompt to search, not evidence of a broken app. */}
              {allJobs.length
                ? `${allJobs.length} stored roles are hidden by your filters. Each one below says how many it removed — clear it to get them back.`
                : appliedLocation.trim() || appliedQuery.trim()
                  ? `No stored roles${appliedQuery.trim() ? ` matching “${appliedQuery.trim()}”` : ''}${appliedLocation.trim() ? ` in ${appliedLocation.trim()}` : ''}. Run the search to pull fresh ones from the enabled sources.`
                  : 'Run a search above to discover roles across the enabled sources.'}
            </span>
            {allJobs.length > 0 && <FilterCulprits rejected={rejected} />}
            {allJobs.length > 0 && (
              <button onClick={resetFilters} style={{ ...ghostBtn, width: 'auto', padding: '0 14px', marginTop: 6 }}>Clear every filter</button>
            )}
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {jobs.map((j) => (
              <JobRow
                key={j.id} job={j} selected={selected.includes(j.id)}
                onToggle={() => toggleJob(j.id)} onOpen={() => openDrawer(j)}
                onApply={() => { setSelected([j.id]); notify(`Selected · ${j.title}`, 'success'); }}
                onSave={() => toggleSaveJob(j)} saving={updateJobStatus.isPending}
              />
            ))}
          </div>
        )}
      </div>
      </div>

      {/* ---- Selection bar --------------------------------------------------------------
          Rendered through a portal straight into <body>, not as a descendant of this
          page's `animation: '... both'` wrapper above. A `both` fill-mode keeps an
          element "affected by" its animated properties indefinitely after it finishes —
          Chrome then still treats it as a containing block for `position: fixed`
          descendants, so this bar was positioning itself relative to that wrapper's full
          (~11,000px) content height instead of the viewport. It rendered correctly, just
          buried far down the page — indistinguishable from "the feature doesn't exist"
          without scrolling to the exact spot. */}
      {selected.length > 0 && createPortal(
        <div
          data-jc-theme=""
          style={{
            position: 'fixed', left: '50%', bottom: 22, transform: 'translateX(-50%)', zIndex: 80,
            display: 'flex', alignItems: 'center', gap: 14, padding: '11px 12px 11px 18px',
            borderRadius: 'var(--jc-r-lg)', background: 'var(--jc-surface-2)', border: '1px solid var(--jc-border-strong)',
            boxShadow: 'var(--jc-shadow-4), var(--jc-clay-inset)', animation: 'jcPop .18s var(--jc-ease)', flexWrap: 'wrap',
          }}
        >
          <span style={{ font: '700 12.5px/1 var(--font)', color: 'var(--jc-text)' }}>
            {selected.length} role{selected.length === 1 ? '' : 's'} selected
          </span>
          <span style={{ width: 1, height: 20, background: 'var(--jc-border-strong)' }} />
          <span className="jc-meta">CV</span>
          <div className="jc-input" style={{ height: 34, minWidth: 200 }}>
            <select
              value={runResumeId} onChange={(e) => setRunResumeId(e.target.value)}
              style={{ flex: 1, background: 'transparent', border: 0, outline: 'none', color: 'var(--jc-text)', font: '600 12px/1 var(--font)' }}
            >
              <option value="auto">Auto — rule-based per role</option>
              {resumes.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
            </select>
          </div>
          <button onClick={clearSelection} className="jc-btn jc-btn-ghost" style={{ height: 34, padding: '0 12px' }}>
            Clear
          </button>
          <button
            onClick={startRun} disabled={createApps.isPending}
            className="jc-btn jc-btn-primary"
            style={{ height: 34 }}
          >
            {createApps.isPending ? 'Queueing…' : 'Start applying'}
          </button>
        </div>,
        document.body,
      )}

      {drawerJob && (
        <JobDrawer
          job={drawerJob}
          resumes={resumes}
          onClose={() => setDrawerJob(null)}
          onApplyWithAgent={(resumeId) => onApplyWithAgent(drawerJob, resumeId)}
          applying={createApps.isPending}
          onApplyManually={onApplyManually}
          onOpenJobId={(id) => {
            const next = allJobs.find((j) => j.id === id);
            if (next) openDrawer(next);
          }}
        />
      )}
    </div>
  );
}

/* -- pieces ------------------------------------------------------------------------- */

const notice: React.CSSProperties = {
  display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10, padding: '30px 20px',
  color: 'var(--text-3)', font: '500 12.5px/1.4 var(--font)', textAlign: 'center',
};

const ghostBtn: React.CSSProperties = {
  width: '100%', marginTop: 14, height: 32, borderRadius: 'var(--r-md)', background: 'var(--surface-2)',
  border: '1px solid var(--border)', color: 'var(--text-2)', font: '600 12px/1 var(--font)', cursor: 'pointer',
};

function RailHead({ label, action, onAction }: { label: string; action: string; onAction: () => void }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 11 }}>
      <span style={{ font: '700 12.5px/1 var(--font)' }}>{label}</span>
      <button onClick={onAction} style={{ background: 'none', border: 0, color: 'var(--jc-accent-2)', font: '600 11px/1 var(--font)', cursor: 'pointer', padding: 0 }}>
        {action}
      </button>
    </div>
  );
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return <div style={{ font: '600 10px/1 var(--mono)', letterSpacing: '.12em', color: 'var(--text-4)', marginBottom: 8 }}>{children}</div>;
}

function RangeRow({ label, value, min, max, step, current, onChange }: {
  label: string; value: string; min: number; max: number; step: number; current: number; onChange: (v: number) => void;
}) {
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
        <span style={{ font: '600 10px/1 var(--mono)', letterSpacing: '.12em', color: 'var(--text-4)' }}>{label}</span>
        <span style={{ font: '700 11px/1 var(--mono)', color: 'var(--jc-accent-2)' }}>{value}</span>
      </div>
      <input
        type="range" min={min} max={max} step={step} value={current} aria-label={label}
        onChange={(e) => onChange(Number(e.target.value))}
        style={{ width: '100%', accentColor: 'var(--accent)' }}
      />
    </div>
  );
}

function CheckBox({ on }: { on: boolean }) {
  return (
    <span
      style={{
        display: 'grid', placeItems: 'center', width: 17, height: 17, borderRadius: 5, flex: '0 0 auto',
        border: `1px solid ${on ? 'var(--accent)' : 'var(--border-3)'}`, background: on ? 'var(--accent)' : 'transparent',
      }}
    >
      {on && <Icon name="check" size={11} sw={3.4} />}
    </span>
  );
}

function CheckRow({ label, on, onClick }: { label: string; on: boolean; onClick: () => void }) {
  return (
    <button onClick={onClick} style={{ display: 'flex', alignItems: 'center', gap: 9, background: 'none', border: 0, padding: 0, cursor: 'pointer', width: '100%' }}>
      <CheckBox on={on} />
      <span style={{ flex: '1 1 auto', textAlign: 'left', font: '600 12px/1 var(--font)', color: 'var(--text-2)' }}>{label}</span>
    </button>
  );
}

function Chip({ on, small, onClick, children }: { on: boolean; small?: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick} aria-pressed={on}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 6, height: small ? 26 : 28,
        padding: `0 ${small ? 9 : 11}px`, borderRadius: 999, cursor: 'pointer',
        font: `600 ${small ? 11 : 11.5}px/1 var(--font)`,
        border: `1px solid ${on ? 'var(--accent-line)' : 'var(--border)'}`,
        background: on ? 'var(--accent-soft)' : 'var(--surface-2)',
        // Not var(--accent) — on this page's dark ground that resolves to a muted, low-
        // luminosity green whose own text-on-background contrast measured under the
        // craft floor's 4.5:1 minimum. jc-accent-2 is the same accent family at a
        // luminosity actually legible as text.
        color: on ? 'var(--jc-accent-2)' : 'var(--text-3)',
      }}
    >
      {children}
    </button>
  );
}

function SearchField({ icon, label, placeholder, value, onChange, grow }: {
  icon: 'search' | 'mappin'; label: string; placeholder: string; value: string; onChange: (v: string) => void; grow: number;
}) {
  return (
    <div className="jc-input" style={{ flex: `${grow} 1 ${grow === 2 ? 260 : 180}px`, height: 40 }}>
      <span style={{ color: 'var(--jc-text-3)', display: 'grid', placeItems: 'center' }}><Icon name={icon} size={16} /></span>
      <input
        aria-label={label} placeholder={placeholder} value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

function JobRow({ job, selected, onToggle, onOpen, onApply, onSave, saving }: {
  job: Job; selected: boolean; onToggle: () => void; onOpen: () => void; onApply: () => void;
  onSave: () => void; saving: boolean;
}) {
  const pct = atsPercent(job.match_score);
  const src = SOURCE_BY_KEY[job.platform];
  // Level 4 metadata — everything that answers "is this worth reading further" without
  // being a decision signal itself.
  const tags = [job.salary_range, job.job_type, job.experience_level, job.remote ? 'Remote' : null]
    .filter(Boolean) as string[];
  const fitColor = job.match_score == null ? 'var(--jc-text-4)' : atsColor(pct);
  const statusMetaJob = jobStatusMeta(job.status);
  const isSaved = job.status === 'saved';

  return (
    <div className="jc-card" data-selected={selected}>
      {/* Level 5 — select for bulk apply, always available, never competing with identity. */}
      <button onClick={onToggle} aria-label="Select role" style={{ background: 'none', border: 0, padding: 0, cursor: 'pointer', marginTop: 3, flex: '0 0 auto' }}>
        <CheckBox on={selected} />
      </button>

      {/* Level 2 — fit, the first thing worth a glance after identity. */}
      <div
        className="jc-fit-ring"
        title={job.match_score == null ? 'No match score yet' : `${pct}% match`}
        style={{ '--fit-pct': job.match_score == null ? 0 : pct, '--fit-color': fitColor } as React.CSSProperties}
      >
        <span className="jc-fit-ring-inner" style={{ '--fit-color': fitColor } as React.CSSProperties}>
          {job.match_score == null ? '—' : pct}
        </span>
      </div>

      <CompanyLogo name={job.company} />

      {/* Level 1 — identity. */}
      <div style={{ flex: '1 1 auto', minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <button onClick={onOpen} className="jc-card-title">
            {job.title}
          </button>
          {/* Level 3 — status, always visible, never color-only (label + dot). */}
          <span className="jc-status" style={{ background: statusMetaJob.soft, color: statusMetaJob.color }}>
            <span className="jc-status-dot" style={{ background: statusMetaJob.color }} /> {statusMetaJob.label}
          </span>
        </div>
        <div className="jc-body" style={{ marginTop: 4 }}>
          {job.company} · {job.location || (job.remote ? 'Remote' : '—')}
        </div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 9 }}>
          {tags.map((t) => (
            <span key={t} style={{ height: 22, padding: '0 8px', display: 'inline-flex', alignItems: 'center', borderRadius: 6, background: 'var(--jc-surface-3)', color: 'var(--jc-text-3)', font: '600 10.5px/1 var(--font)' }}>
              {t}
            </span>
          ))}
          {/* "Unknown" is the common case (most postings never mention sponsorship) and
              would be pure noise repeated on every row — the drawer shows it explicitly
              for anyone who opens the job. Here, only a genuine signal earns a badge. */}
          {job.sponsor_confidence !== 'unknown' && (() => {
            const sm = jcSponsorMeta(job.sponsor_confidence);
            return (
              <span title={job.sponsor_evidence ?? undefined} className="jc-status" style={{ background: sm.soft, color: sm.color }}>
                {sm.label}
              </span>
            );
          })()}
          {job.posted_date && (
            <span className="jc-meta" style={{ height: 22, display: 'inline-flex', alignItems: 'center' }}>
              {relativeTime(job.posted_date)}
            </span>
          )}
          <span className="jc-meta" style={{ height: 22, display: 'inline-flex', alignItems: 'center', gap: 5 }}>
            <span style={{ width: 5, height: 5, borderRadius: '50%', background: src ? HEALTH_META[src.health].color : 'var(--jc-text-4)' }} />
            {sourceLabel(job.platform)}
          </span>
        </div>
      </div>

      {/* Level 5 — actions: primary (apply), secondary (view posting), tertiary (save). */}
      <div style={{ flex: '0 0 auto', display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 10 }}>
        <button
          onClick={onSave}
          disabled={saving}
          aria-pressed={isSaved}
          title={isSaved ? 'Remove from saved' : 'Save for later'}
          className="jc-btn jc-btn-ghost"
          style={{ width: 30, height: 30, padding: 0, color: isSaved ? 'var(--jc-accent-2)' : 'var(--jc-text-4)' }}
        >
          <Icon name="bookmark" size={15} sw={isSaved ? 2.4 : 1.8} />
        </button>
        <div style={{ display: 'flex', gap: 7 }}>
          <a href={job.url} target="_blank" rel="noreferrer" className="jc-btn jc-btn-secondary" style={{ height: 30, padding: '0 11px', textDecoration: 'none' }}>
            Posting
          </a>
          <button onClick={onApply} className="jc-btn jc-btn-primary" style={{ height: 30, padding: '0 13px' }}>
            Apply
          </button>
        </div>
      </div>
    </div>
  );
}
