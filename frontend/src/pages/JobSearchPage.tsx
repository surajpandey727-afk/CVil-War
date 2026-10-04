import { useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate } from 'react-router-dom';

import CompanyLogo from '@/components/ui/CompanyLogo';
import Icon from '@/components/ui/Icon';
import JobDrawer from '@/components/jobs/JobDrawer';
import { useAutoScoreJobs, useJobs, useSearchJobs, useUpdateJobStatus } from '@/hooks/useJobs';
import { useCreateApplicationBatch } from '@/hooks/useApplications';
import { useDashboardStats } from '@/hooks/useAnalytics';
import { useResumes } from '@/hooks/useResumes';
import { useSettings } from '@/hooks/useSettings';
import { useSources } from '@/hooks/useSources';
import { useAppStore } from '@/store/useAppStore';
import { useDiscoveryStore } from '@/store/useDiscoveryStore';
import { atsColor, atsPercent, relativeTime, jobStatusMeta } from '@/lib/status';
import { ROLE_FAMILIES, queryForTitles, type RoleFamily } from '@/lib/roleTargets';
import { HEALTH_META, sourceLabel } from '@/lib/sources';
import {
  SALARY_BRACKETS, SPONSORSHIP_META, formatSalary, salaryBand, sponsorshipStatus,
} from '@/lib/jobModel';
import { POSTED_WINDOWS, applyJobFilters } from '@/lib/jobFilter';
import '@/styles/jobs-command.css';
import type { Job, SponsorshipStatus } from '@/types/job';
import type { SourceRecord } from '@/types/source';

const card: React.CSSProperties = {
  background: 'var(--jc-surface)', border: '1px solid var(--jc-border)',
  borderRadius: 'var(--jc-r-lg)', boxShadow: 'var(--jc-shadow-1)',
};

const SENIORITY = ['Junior', 'Mid', 'Senior', 'Lead', 'Principal'];

const SPONSORSHIP_ORDER: SponsorshipStatus[] = ['available', 'not_specified', 'none'];

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
    salaryBrackets: {
      label: 'Salary brackets', clear: () => patchFilters({ salaryBrackets: [] }),
    },
    salaryCustom: {
      label: 'Custom salary range',
      clear: () => patchFilters({ salaryCustomMinK: null, salaryCustomMaxK: null }),
    },
    sponsorship: { label: 'Visa sponsorship', clear: () => patchFilters({ sponsorship: [] }) },
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
            title="Clear this filter and bring the roles it is hiding back into the list."
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
    setQuery, setLocation, commitSearch, toggleFamily, setSources, patchFilters, resetFilters,
    toggleJob, setSelected, clearSelection,
    recordSearch, setRecentResultCount, restoreSearch,
  } = useDiscoveryStore();

  // The location and title filters go to the server, which matches them against the stored
  // job location rather than the rendered text. Doing this in the browser is what made a
  // London search return a Cleveland accounts-payable role: the filter was never applied at
  // all, and `total` counted every job the account had ever cached.
  const { data, isLoading, isError } = useJobs(1, 100, undefined, {
    location: appliedLocation,
    query: appliedQuery,
  });
  // Every listed role gets a match score: unscored ones are scored in one batch request and saved.
  const { scoring: scoringJobs, unscorable: unscorableJobs } = useAutoScoreJobs(data?.items);
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
  /** Everything the server holds for this search, as opposed to the page fetched above. */
  const stored = data?.total ?? allJobs.length;
  // An empty selection means "no restriction", not "exclude everything" — the operator has
  // simply never narrowed the list.
  const restrictSources = enabledSources.length > 0;
  const knownKeys = useMemo(
    () => new Set(liveCatalogue.tiers.flatMap((t) => t.sources.map((src) => src.key))),
    [liveCatalogue],
  );
  const sourceByKey = useMemo(
    () => {
      const map: Record<string, SourceRecord> = {};
      for (const tier of liveCatalogue.tiers) for (const src of tier.sources) map[src.key] = src;
      return map;
    },
    [liveCatalogue],
  );

  /**
   * The sources the rail shows, grouped by tier.
   *
   * Only sources that can actually return a result right now, and that Settings has not
   * switched off. Everything else — unbuilt adapters, sources behind a sign-in, ones the
   * operator disabled — lives on the Manage screen, which is where you go to change that.
   * The rail previously listed all of them inline, tagged "SOON", and then truncated each
   * tier to its first six entries: of 69 career-page sources, six were reachable and the
   * other 63 could not be seen or toggled at all.
   */
  const { railTiers, hiddenSourceCount } = useMemo(() => {
    const settingsEnabled = settings?.platforms_enabled;
    const permitted = (key: string) =>
      liveCatalogue.live_keys.includes(key)
      && (!settingsEnabled?.length || settingsEnabled.includes(key));

    let hidden = 0;
    const tiers = liveCatalogue.tiers
      .map((tier) => {
        const shown = tier.sources.filter((src) => permitted(src.key));
        hidden += tier.sources.length - shown.length;
        return { id: tier.id, name: tier.name, sources: shown };
      })
      .filter((tier) => tier.sources.length > 0);

    return { railTiers: tiers, hiddenSourceCount: hidden };
  }, [liveCatalogue, settings]);

  const { jobs, rejected } = useMemo(
    () => applyJobFilters(allJobs, { filters, activeFamilies, enabledSources, knownKeys }),
    [allJobs, enabledSources, knownKeys, filters, activeFamilies],
  );

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


  /**
   * Include or exclude one source.
   *
   * An empty selection means "every source", which is the right default but makes the first
   * click ambiguous: adding the source you just switched *off* is the opposite of what the
   * operator asked for. So the first exclusion writes the implied list down and removes one
   * from it, and re-selecting everything collapses back to the empty list — which keeps
   * sources added to the registry later switched on rather than silently excluded.
   */
  const toggleSourceExplicit = (key: string) => {
    const railKeys = railTiers.flatMap((t) => t.sources.map((s) => s.key));
    const next = restrictSources
      ? (enabledSources.includes(key)
          ? enabledSources.filter((k) => k !== key)
          : [...enabledSources, key])
      : railKeys.filter((k) => k !== key);
    setSources(railKeys.every((k) => next.includes(k)) ? [] : next);
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
    // The live registry decides what can be searched, not the static catalogue in lib/sources:
    // that file is an offline fallback, and a source the backend had shipped but it had not
    // caught up with was silently dropped from every manual search.
    const usable = enabledSources.length > 0
      ? enabledSources.filter((k) => liveCatalogue.live_keys.includes(k))
      : respectingSettings;
    if (!usable.length) {
      notify('None of the enabled sources have a working adapter yet', 'warning');
      return;
    }
    // Promote the typed boxes to the filter the list is fetched with, so the results shown
    // after a search are the results of *that* search.
    commitSearch();
    // Recorded before the request, not after it: a search that fails or is still running is
    // still one the operator ran, and the history is most useful precisely then.
    const recentId = recordSearch({
      query: effective,
      location: location.trim(),
      sources: usable,
      filters,
    });
    search.mutate(
      { query: effective, location: location.trim() || undefined, platforms: usable, limit: 100 },
      {
        onSuccess: (r) => {
          setRecentResultCount(recentId, r.total);
          notify(`Found ${r.total} matching roles across ${usable.length} sources`, 'success');
        },
        onError: () => notify('Search failed — try again', 'error'),
      },
    );
  };

  /** Re-run a search from the history, under the conditions it was originally run with. */
  const runRecentSearch = (id: string) => {
    const entry = restoreSearch(id);
    if (!entry) return;
    commitSearch();
    search.mutate(
      {
        query: entry.query,
        location: entry.location || undefined,
        platforms: entry.sources.filter((k) => liveCatalogue.live_keys.includes(k)),
        limit: 100,
      },
      {
        onSuccess: (r) => {
          setRecentResultCount(id, r.total);
          notify(`Found ${r.total} matching roles`, 'success');
        },
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
          <FieldLabel>SALARY</FieldLabel>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 9 }}>
            {SALARY_BRACKETS.map((b) => (
              <Chip
                key={b.id} small on={filters.salaryBrackets.includes(b.id)}
                title={`Show roles whose published band overlaps ${b.label}. Roles that publish no salary are never hidden by this.`}
                onClick={() => patchFilters({
                  salaryBrackets: filters.salaryBrackets.includes(b.id)
                    ? filters.salaryBrackets.filter((x) => x !== b.id)
                    : [...filters.salaryBrackets, b.id],
                })}
              >
                {b.label}
              </Chip>
            ))}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
            <KRange
              label="Custom minimum salary in thousands" placeholder="Min"
              value={filters.salaryCustomMinK}
              onChange={(v) => patchFilters({ salaryCustomMinK: v })}
            />
            <span style={{ font: '600 11px/1 var(--mono)', color: 'var(--text-4)' }}>to</span>
            <KRange
              label="Custom maximum salary in thousands" placeholder="Max"
              value={filters.salaryCustomMaxK}
              onChange={(v) => patchFilters({ salaryCustomMaxK: v })}
            />
          </div>
          {/* Said once, here, rather than left for the operator to deduce from an empty list:
              most UK postings publish no salary, and a window that dropped them would remove
              the majority of the market. "Published salary only" below is the control for
              that, and it is a separate decision. */}
          <div style={{ font: '500 10.5px/1.45 var(--font)', color: 'var(--text-4)', marginBottom: 16 }}>
            Roles with no published salary are kept. Use “Published salary only” to exclude them.
          </div>

          <FieldLabel>VISA SPONSORSHIP</FieldLabel>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 16 }}>
            {SPONSORSHIP_ORDER.map((s) => (
              <Chip
                key={s} small on={filters.sponsorship.includes(s)}
                title={SPONSORSHIP_META[s].hint}
                onClick={() => patchFilters({
                  sponsorship: filters.sponsorship.includes(s)
                    ? filters.sponsorship.filter((x) => x !== s)
                    : [...filters.sponsorship, s],
                })}
              >
                {SPONSORSHIP_META[s].chip}
              </Chip>
            ))}
          </div>

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
            {POSTED_WINDOWS.map((p) => (
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

          <button
            onClick={resetFilters}
            title="Return every filter to its default. No roles or applications are affected."
            style={ghostBtn}
          >
            Reset filters
          </button>
        </div>

        <div style={{ ...card, padding: 14 }}>
          {/* Deep link, not a bare /settings: "Manage" landing at the top of a long page with
              no indication of where to look is what made this flow a dead end. */}
          <RailHead label="Sources" action="Manage" onAction={() => navigate('/settings?section=platforms')} />
          {railTiers.length === 0 ? (
            <div style={{ font: '500 11.5px/1.45 var(--font)', color: 'var(--text-4)' }}>
              No source can return results right now. Open Manage to connect or re-enable one.
            </div>
          ) : (
            railTiers.map((tier) => (
              <div key={tier.id} style={{ marginBottom: 10 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', padding: '6px 2px' }}>
                  <span style={{ font: '600 10px/1 var(--mono)', letterSpacing: '.12em', color: 'var(--text-4)' }}>
                    {/* Never `tier.name.replace(...)` unguarded: one tier arriving without a
                        name would take the whole Jobs page down, which is how an unknown
                        health value once took down SourcesPage entirely. */}
                    {(tier.name ?? tier.id).replace(/ —.*/, '').toUpperCase()}
                  </span>
                  <span style={{ font: '600 10px/1 var(--mono)', color: 'var(--text-4)' }}>
                    {tier.sources.filter((s) => enabledSources.includes(s.key)).length}/{tier.sources.length}
                  </span>
                </div>
                {tier.sources.map((src) => {
                  // An empty selection means "all of them", so every row reads as on until
                  // the operator narrows it. Rendering them all grey until something is
                  // ticked said the opposite of what the search actually does.
                  const on = !restrictSources || enabledSources.includes(src.key);
                  const meta = HEALTH_META[src.health] ?? HEALTH_META.live;
                  return (
                    <button
                      key={src.key}
                      onClick={() => toggleSourceExplicit(src.key)}
                      aria-pressed={on}
                      title={src.note || `${src.label} — ${meta.label}. Click to ${on ? 'exclude from' : 'include in'} searches.`}
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
                    </button>
                  );
                })}
              </div>
            ))
          )}
          {hiddenSourceCount > 0 && (
            <button
              onClick={() => navigate('/settings?section=platforms')}
              title="Sources with no working adapter, or ones you have switched off, are managed here rather than listed above."
              style={{ ...ghostBtn, marginTop: 4 }}
            >
              {hiddenSourceCount} more in Manage
            </button>
          )}
        </div>

        <RecentSearches onRun={runRecentSearch} />
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
          {/* The list endpoint is fetched one page deep, so filters run over the first 100
              stored roles rather than the whole corpus. Said out loud: a candidate filtering
              to "£75k+" and seeing four results should know whether that is the market or
              the page size. Silence here reads as the former. */}
          {stored > allJobs.length && (
            <span
              className="jc-meta"
              title={`Filters run over the ${allJobs.length} most recent stored roles. ${stored - allJobs.length} older ones are not on this page.`}
            >
              of {stored} stored
            </span>
          )}
          {scoringJobs && (
            <span className="jc-meta" role="status" title="Matching each role against your best-fitting résumé">
              Scoring matches…
            </span>
          )}
          {!scoringJobs && unscorableJobs > 0 && (
            <span className="jc-meta" title="These postings have no description, so there is nothing to score against">
              {unscorableJobs} without a description
            </span>
          )}
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
              <button
                onClick={resetFilters}
                title="Clear every filter at once and show all stored roles."
                style={{ ...ghostBtn, width: 'auto', padding: '0 14px', marginTop: 6 }}
              >
                Clear every filter
              </button>
            )}
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {jobs.map((j) => (
              <JobRow
                key={j.id} job={j} selected={selected.includes(j.id)}
                sourceMeta={sourceByKey[j.platform]}
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
          <button
            onClick={clearSelection}
            title="Deselect every role. Nothing is applied to or discarded."
            className="jc-btn jc-btn-ghost"
            style={{ height: 34, padding: '0 12px' }}
          >
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

/** One end of the custom salary window, in thousands.
 *
 *  Empty means unbounded, and is stored as `null` rather than `0`: a filter reading "£0k and
 *  above" is indistinguishable on screen from no filter at all, but excludes every posting
 *  that publishes no salary the moment anything else reads it as a floor.
 */
function KRange({ label, placeholder, value, onChange }: {
  label: string; placeholder: string; value: number | null; onChange: (v: number | null) => void;
}) {
  return (
    <div className="jc-input" style={{ flex: '1 1 0', height: 30, minWidth: 0, gap: 2 }}>
      <span style={{ font: '600 11px/1 var(--mono)', color: 'var(--text-4)' }}>£</span>
      <input
        aria-label={label} placeholder={placeholder} inputMode="numeric" value={value ?? ''}
        onChange={(e) => {
          const raw = e.target.value.replace(/[^\d]/g, '');
          onChange(raw === '' ? null : Number(raw));
        }}
        style={{
          flex: '1 1 auto', minWidth: 0, background: 'transparent', border: 0, outline: 'none',
          color: 'var(--text)', font: '600 11.5px/1 var(--font)',
        }}
      />
      <span style={{ font: '600 11px/1 var(--mono)', color: 'var(--text-4)' }}>k</span>
    </div>
  );
}

/**
 * The searches the operator has actually run, most recent first.
 *
 * Restores the whole search, not just its words: the same query means something different
 * against a different location, a different set of sources and a different salary window, so
 * re-running one puts those conditions back before it fires. Re-running a search you already
 * ran updates its entry rather than adding a second copy — checking a saved search for new
 * postings is the normal way to use this, and a history that fills up with ten copies of the
 * same search is not a history.
 */
function RecentSearches({ onRun }: { onRun: (id: string) => void }) {
  const { recentSearches, removeRecentSearch, clearRecentSearches } = useDiscoveryStore();

  if (!recentSearches.length) {
    return (
      <div style={{ ...card, padding: 14 }}>
        <div style={{ font: '700 12.5px/1 var(--font)', marginBottom: 8 }}>Recent searches</div>
        <div style={{ font: '500 11.5px/1.45 var(--font)', color: 'var(--text-4)' }}>
          Searches you run appear here, with the location, sources and filters they used.
        </div>
      </div>
    );
  }

  return (
    <div style={{ ...card, padding: 14 }}>
      {/* "Clear all", not "Clear": the filter diagnostic on this same screen puts a "Clear"
          button beside every filter that is hiding jobs, and two controls with one label that
          do very different things is how you delete your search history meaning to unset a
          filter. */}
      <RailHead label="Recent searches" action="Clear all" onAction={clearRecentSearches} />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {recentSearches.map((r) => (
          <div key={r.id} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <button
              onClick={() => onRun(r.id)}
              // The visible text is the query alone, which on its own does not say what the
              // button will do. The accessible name spells out the whole search, and still
              // contains the visible words so speaking the label matches what is on screen.
              aria-label={`Re-run this search: ${r.query}${r.location ? ` in ${r.location}` : ''}`}
              title={`Re-run this search: ${r.query}${r.location ? ` in ${r.location}` : ''}, across ${r.sources.length} source${r.sources.length === 1 ? '' : 's'}, with the filters it was run under.`}
              style={{
                flex: '1 1 auto', minWidth: 0, display: 'flex', flexDirection: 'column',
                alignItems: 'flex-start', gap: 2, padding: '6px 8px', borderRadius: 'var(--r-sm)',
                border: 0, background: 'transparent', cursor: 'pointer', textAlign: 'left',
              }}
            >
              <span
                style={{
                  maxWidth: '100%', font: '600 11.5px/1.3 var(--font)', color: 'var(--text-2)',
                  whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                }}
              >
                {r.query}
              </span>
              <span style={{ font: '500 10px/1.3 var(--mono)', color: 'var(--text-4)' }}>
                {[
                  r.location || 'Anywhere',
                  `${r.sources.length} src`,
                  // "running" is a real third state, not zero: a search whose count has not
                  // come back yet is not a search that found nothing.
                  r.resultCount === null ? 'running' : `${r.resultCount} found`,
                  relativeTime(new Date(r.at).toISOString()),
                ].join(' · ')}
              </span>
            </button>
            <button
              onClick={() => removeRecentSearch(r.id)}
              title="Remove this search from the history. Nothing else is affected."
              aria-label={`Remove ${r.query} from recent searches`}
              style={{
                flex: '0 0 auto', width: 22, height: 22, display: 'grid', placeItems: 'center',
                borderRadius: 'var(--r-sm)', border: 0, background: 'transparent',
                color: 'var(--text-4)', cursor: 'pointer',
              }}
            >
              <Icon name="trash" size={12} />
            </button>
          </div>
        ))}
      </div>
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

function Chip({ on, small, title, onClick, children }: {
  on: boolean; small?: boolean; title?: string; onClick: () => void; children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick} aria-pressed={on} title={title}
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

/** Tone decides how loudly a pill reads. Pay is the number candidates look for first. */
const PILL_TONE: Record<string, { bg: string; fg: string; border: string }> = {
  money: { bg: 'var(--applied-soft, var(--jc-surface-3))', fg: 'var(--applied, var(--jc-text-2))', border: 'transparent' },
  bar: { bg: 'var(--accent-soft, var(--jc-surface-3))', fg: 'var(--accent, var(--jc-text-2))', border: 'transparent' },
  remote: { bg: 'var(--jc-surface-3)', fg: 'var(--jc-text-2)', border: 'transparent' },
  plain: { bg: 'var(--jc-surface-3)', fg: 'var(--jc-text-3)', border: 'transparent' },
  absent: { bg: 'transparent', fg: 'var(--jc-text-4)', border: 'var(--jc-border, rgba(255,255,255,.12))' },
};

/**
 * One labelled fact about a role.
 *
 * A missing value is rendered rather than hidden. "Not published" and "Not fetched yet" are
 * different facts about a salary, and both are things the candidate wants to know — an empty
 * space tells them neither, and silently dropping the pill makes two very different jobs look
 * identical on the list.
 */
function MetaPill({
  label, value, tone, hint, absent,
}: {
  label: string;
  value: string | null | undefined;
  tone: keyof typeof PILL_TONE;
  hint: string;
  absent?: string;
}) {
  const missing = !value;
  if (missing && !absent) return null;
  // `plain` is always defined; the fallback keeps an unknown tone from rendering unstyled.
  const palette = PILL_TONE[missing ? 'absent' : tone] ?? PILL_TONE['plain']!;

  return (
    <span
      title={hint}
      style={{
        height: 22, padding: '0 8px', display: 'inline-flex', alignItems: 'center', gap: 5,
        borderRadius: 6, background: palette.bg, color: palette.fg,
        border: `1px solid ${palette.border}`, font: '600 10.5px/1 var(--font)',
        maxWidth: 220, overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis',
      }}
    >
      {label && (
        <span style={{ opacity: 0.62, fontWeight: 700, letterSpacing: '.03em' }}>{label}</span>
      )}
      <span>{missing ? absent : value}</span>
    </span>
  );
}


function JobRow({ job, selected, sourceMeta, onToggle, onOpen, onApply, onSave, saving }: {
  job: Job; selected: boolean;
  /** From the live registry, not the static catalogue — `undefined` for a source the
   *  registry has never heard of, which is shown by name rather than dropped. */
  sourceMeta: SourceRecord | undefined;
  onToggle: () => void; onOpen: () => void; onApply: () => void;
  onSave: () => void; saving: boolean;
}) {
  const pct = atsPercent(job.match_score);
  const src = sourceMeta;
  const band = salaryBand(job);
  const sponsorship = sponsorshipStatus(job);
  // The registry's own label when it knows the source, the static catalogue next, and the
  // raw key last. A source the catalogue has not caught up with is named, not hidden.
  const label = src?.label ?? sourceLabel(job.platform);
  // Level 4 metadata — everything that answers "is this worth reading further" without
  // being a decision signal itself.
  // Salary, the experience bar and employment type each answer a different question, and
  // pouring them into one undifferentiated row of grey pills made the card unreadable at a
  // glance — the number a candidate most wants (pay) looked identical to the one they care
  // least about. Each now carries its own label, its own tone and its own tooltip.
  const yearsRequired = job.posting_data?.years_required ?? null;
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
          <button
            onClick={onOpen}
            title={`Open ${job.title} - fit, company and the full posting`}
            className="jc-card-title"
          >
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
          {/* The same band the salary filter and the salary sort read, so a card can never
              show a figure the filter behind it disagrees with. It used to: this pill
              rendered the posting's raw text while the filter re-parsed that text for
              itself and got a different number. */}
          <MetaPill
            label="Salary"
            value={formatSalary(band) ?? job.salary_range}
            tone="money"
            absent="Not published"
            hint={
              band.published
                ? `The posting states ${job.salary_range}.${band.annualised ? ' Shown as a yearly equivalent.' : ''}`
                : job.salary_range
                  ? `The posting says “${job.salary_range}” and gives no figure`
                  : 'This posting does not publish a salary'
            }
          />
          <MetaPill
            label="Experience"
            value={yearsRequired ? `${yearsRequired}+ yrs` : null}
            tone="bar"
            absent={job.enriched_at ? 'Not stated' : 'Not fetched'}
            hint={
              yearsRequired
                ? `The posting asks for ${yearsRequired}+ years. Taken from its own wording.`
                : job.enriched_at
                  ? 'The posting was read and states no minimum years of experience'
                  : 'Open this job to fetch the full posting and read its experience bar'
            }
          />
          {job.job_type && (
            <MetaPill label="Type" value={job.job_type} tone="plain" hint="Employment type" />
          )}
          {job.experience_level && (
            <MetaPill
              label="Level"
              value={job.experience_level}
              tone="plain"
              hint="Seniority as the posting labels it"
            />
          )}
          {job.remote && (
            <MetaPill label="" value="Remote" tone="remote" hint="This role is remote or hybrid" />
          )}
          {/* Shown on every card, including "not specified", and read from the same field
              the sponsorship filter matches on. Hiding the common case was defensible as
              noise reduction right up until sponsorship became a filter: a candidate who
              filters for "not specified" then had no way to see, on the card, why a row
              was in their results. */}
          <MetaPill
            label="Visa"
            value={SPONSORSHIP_META[sponsorship].card}
            tone={sponsorship === 'available' ? 'bar' : 'plain'}
            hint={
              job.sponsor_evidence
                ? `${SPONSORSHIP_META[sponsorship].label} — ${job.sponsor_evidence}`
                : SPONSORSHIP_META[sponsorship].hint
            }
          />
          {job.posted_date && (
            <span
              className="jc-meta"
              title={`Posted ${new Date(job.posted_date).toLocaleDateString()}`}
              style={{ height: 22, display: 'inline-flex', alignItems: 'center' }}
            >
              {relativeTime(job.posted_date)}
            </span>
          )}
          <span
            className="jc-meta"
            title={
              src
                ? `Found on ${label} - source is ${(HEALTH_META[src.health] ?? HEALTH_META.live).label.toLowerCase()}`
                : `Found on ${label}`
            }
            style={{ height: 22, display: 'inline-flex', alignItems: 'center', gap: 5 }}
          >
            <span style={{ width: 5, height: 5, borderRadius: '50%', background: src ? (HEALTH_META[src.health] ?? HEALTH_META.live).color : 'var(--jc-text-4)' }} />
            {label}
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
          <a
            href={job.url}
            target="_blank"
            rel="noreferrer"
            title={`Open the original posting for ${job.title} at ${job.company}`}
            className="jc-btn jc-btn-secondary"
            style={{ height: 30, padding: '0 11px', textDecoration: 'none' }}
          >
            Posting
          </a>
          <button
            onClick={onApply}
            title={`Start an application for ${job.title} at ${job.company}`}
            className="jc-btn jc-btn-primary"
            style={{ height: 30, padding: '0 13px' }}
          >
            Apply
          </button>
        </div>
      </div>
    </div>
  );
}
