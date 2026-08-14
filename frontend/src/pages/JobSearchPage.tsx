import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import CompanyLogo from '@/components/ui/CompanyLogo';
import Icon from '@/components/ui/Icon';
import JobDrawer from '@/components/jobs/JobDrawer';
import { useJobs, useSearchJobs } from '@/hooks/useJobs';
import { useCreateApplicationBatch } from '@/hooks/useApplications';
import { useResumes } from '@/hooks/useResumes';
import { useAppStore } from '@/store/useAppStore';
import { useDiscoveryStore } from '@/store/useDiscoveryStore';
import { atsColor, atsPercent, relativeTime } from '@/lib/status';
import { ROLE_FAMILIES, familyForTitle, queryForTitles, type RoleFamily } from '@/lib/roleTargets';
import {
  HEALTH_META, SOURCE_BY_KEY, SOURCE_TIERS, sourceLabel, sourcesInTier,
} from '@/lib/sources';
import type { Job } from '@/types/job';

const card: React.CSSProperties = {
  background: 'var(--surface)', border: '1px solid var(--border)',
  borderRadius: 'var(--r-lg)', boxShadow: 'var(--shadow-1)',
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
  const search = useSearchJobs();
  const createApps = useCreateApplicationBatch();

  const [drawerJob, setDrawerJob] = useState<Job | null>(null);
  const [runResumeId, setRunResumeId] = useState<string>('auto');

  const resumes = useMemo(() => resumeData?.items ?? [], [resumeData]);
  const allJobs = useMemo(() => data?.items ?? [], [data]);

  /** Client-side filtering. The backend returns the stored corpus; these are the operator's
   *  standing preferences, applied to whatever is in it. */
  const jobs = useMemo(() => {
    const maxAge = POSTED.find((p) => p.key === filters.postedWithin)?.days ?? 3650;
    const out = allJobs.filter((j) => {
      if (enabledSources.length && !enabledSources.includes(j.platform)) return false;
      if (atsPercent(j.match_score) < filters.minAtsScore && j.match_score != null) return false;
      if (filters.remoteOnly && !j.remote) return false;
      if (filters.hideApplied && j.status !== 'new' && j.status !== 'discovered') return false;
      // A missing posted_date is unknown, not old: excluding it would silently drop every
      // source that does not publish one (Arbeitnow, several career pages).
      if (j.posted_date && ageInDays(j.posted_date) > maxAge) return false;
      const band = salaryK(j.salary_range);
      if (filters.publishedSalaryOnly && band == null) return false;
      if (filters.minSalaryK > 0 && band != null && band < filters.minSalaryK) return false;
      if (filters.seniority.length) {
        const level = (j.experience_level ?? '').toLowerCase();
        if (!filters.seniority.some((s) => level.includes(s.toLowerCase()))) return false;
      }
      if (activeFamilies.length && !activeFamilies.includes(familyForTitle(j.title))) return false;
      return true;
    });
    out.sort((a, b) => {
      if (filters.sort === 'match') return atsPercent(b.match_score) - atsPercent(a.match_score);
      if (filters.sort === 'newest') return ageInDays(a.posted_date) - ageInDays(b.posted_date);
      return (salaryK(b.salary_range) ?? 0) - (salaryK(a.salary_range) ?? 0);
    });
    return out;
  }, [allJobs, enabledSources, filters, activeFamilies]);

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


  const runSearch = () => {
    const effective = query.trim() || queryForTitles(activeTitles);
    if (!effective) {
      notify('Add at least one role target, or type a search term', 'warning');
      return;
    }
    const usable = enabledSources.filter((k) => SOURCE_BY_KEY[k]?.implemented);
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

  return (
    <div style={{ animation: 'aaUp .4s var(--ease) both', display: 'flex', gap: 16, alignItems: 'flex-start' }}>
      {/* ---- Left rail: targets, filters, sources ------------------------------------ */}
      <div style={{ flex: '0 0 268px', display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div style={{ ...card, padding: 14 }}>
          <RailHead label="Role targets" action="Edit" onAction={() => navigate('/settings')} />
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
          <RailHead label="Sources" action="Manage" onAction={() => navigate('/settings')} />
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
            style={{
              flex: '0 0 auto', display: 'inline-flex', alignItems: 'center', gap: 7, height: 40,
              padding: '0 18px', borderRadius: 'var(--r-md)', background: 'var(--accent)',
              border: '1px solid var(--accent)', color: 'var(--accent-ink)',
              font: '700 13px/1 var(--font)', cursor: 'pointer',
            }}
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
            <div style={{ display: 'grid', placeItems: 'center', width: 44, height: 44, borderRadius: 12, background: 'var(--accent-soft)', color: 'var(--accent)' }}>
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
                ? `${allJobs.length} stored roles were filtered out. Lower the ATS threshold, widen seniority, or enable more sources.`
                : appliedLocation.trim() || appliedQuery.trim()
                  ? `No stored roles${appliedQuery.trim() ? ` matching “${appliedQuery.trim()}”` : ''}${appliedLocation.trim() ? ` in ${appliedLocation.trim()}` : ''}. Run the search to pull fresh ones from the enabled sources.`
                  : 'Run a search above to discover roles across the enabled sources.'}
            </span>
            {allJobs.length > 0 && (
              <button onClick={resetFilters} style={{ ...ghostBtn, width: 'auto', padding: '0 14px', marginTop: 6 }}>Reset filters</button>
            )}
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {jobs.map((j) => (
              <JobRow
                key={j.id} job={j} selected={selected.includes(j.id)}
                onToggle={() => toggleJob(j.id)} onOpen={() => openDrawer(j)}
                onApply={() => { setSelected([j.id]); notify(`Selected · ${j.title}`, 'success'); }}
              />
            ))}
          </div>
        )}
      </div>

      {/* ---- Selection bar ------------------------------------------------------------- */}
      {selected.length > 0 && (
        <div
          style={{
            position: 'fixed', left: '50%', bottom: 22, transform: 'translateX(-50%)', zIndex: 80,
            display: 'flex', alignItems: 'center', gap: 14, padding: '11px 12px 11px 18px',
            borderRadius: 'var(--r-lg)', background: 'var(--surface-2)', border: '1px solid var(--border-2)',
            boxShadow: 'var(--shadow-pop)', animation: 'aaPop .16s var(--ease)', flexWrap: 'wrap',
          }}
        >
          <span style={{ font: '700 12.5px/1 var(--font)', color: 'var(--text)' }}>
            {selected.length} role{selected.length === 1 ? '' : 's'} selected
          </span>
          <span style={{ width: 1, height: 20, background: 'var(--border-2)' }} />
          <span style={{ font: '600 11.5px/1 var(--font)', color: 'var(--text-3)' }}>CV</span>
          <select
            value={runResumeId} onChange={(e) => setRunResumeId(e.target.value)}
            style={{ height: 32, padding: '0 9px', borderRadius: 'var(--r-sm)', background: 'var(--surface-3)', border: '1px solid var(--border)', color: 'var(--text)', font: '600 12px/1 var(--font)', maxWidth: 240 }}
          >
            <option value="auto">Auto — rule-based per role</option>
            {resumes.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
          </select>
          <button onClick={clearSelection} style={{ height: 32, padding: '0 12px', borderRadius: 'var(--r-sm)', background: 'transparent', border: '1px solid var(--border-2)', color: 'var(--text-2)', font: '700 12px/1 var(--font)', cursor: 'pointer' }}>
            Clear
          </button>
          <button
            onClick={startRun} disabled={createApps.isPending}
            style={{ height: 32, padding: '0 16px', borderRadius: 'var(--r-sm)', background: 'var(--accent)', border: '1px solid var(--accent)', color: 'var(--accent-ink)', font: '700 12px/1 var(--font)', cursor: 'pointer' }}
          >
            {createApps.isPending ? 'Queueing…' : 'Start applying'}
          </button>
        </div>
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
      <button onClick={onAction} style={{ background: 'none', border: 0, color: 'var(--accent)', font: '600 11px/1 var(--font)', cursor: 'pointer', padding: 0 }}>
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
        <span style={{ font: '700 11px/1 var(--mono)', color: 'var(--accent)' }}>{value}</span>
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
        color: on ? 'var(--accent)' : 'var(--text-3)',
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
    <div style={{ flex: `${grow} 1 ${grow === 2 ? 260 : 180}px`, display: 'flex', alignItems: 'center', gap: 9, height: 40, padding: '0 12px', borderRadius: 'var(--r-md)', background: 'var(--surface-3)', border: '1px solid var(--border)' }}>
      <span style={{ color: 'var(--text-3)', display: 'grid', placeItems: 'center' }}><Icon name={icon} size={16} /></span>
      <input
        aria-label={label} placeholder={placeholder} value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{ flex: 1, minWidth: 0, background: 'transparent', border: 0, outline: 'none', color: 'var(--text)', font: '500 13px/1 var(--font)' }}
      />
    </div>
  );
}

function JobRow({ job, selected, onToggle, onOpen, onApply }: {
  job: Job; selected: boolean; onToggle: () => void; onOpen: () => void; onApply: () => void;
}) {
  const pct = atsPercent(job.match_score);
  const src = SOURCE_BY_KEY[job.platform];
  const tags = [job.salary_range, job.job_type, job.experience_level, job.remote ? 'Remote' : null]
    .filter(Boolean) as string[];

  return (
    <div style={{ ...card, padding: '15px 16px', borderColor: selected ? 'var(--accent-line)' : 'var(--border)' }}>
      <div style={{ display: 'flex', gap: 13, alignItems: 'flex-start' }}>
        <button onClick={onToggle} aria-label="Select role" style={{ background: 'none', border: 0, padding: 0, cursor: 'pointer', marginTop: 3, flex: '0 0 auto' }}>
          <CheckBox on={selected} />
        </button>
        <CompanyLogo name={job.company} />
        <div style={{ flex: '1 1 auto', minWidth: 0 }}>
          <button onClick={onOpen} style={{ display: 'block', textAlign: 'left', padding: 0, background: 'none', border: 0, cursor: 'pointer', font: '700 14.5px/1.25 var(--font)', color: 'var(--text)' }}>
            {job.title}
          </button>
          <div style={{ font: '500 12.5px/1.3 var(--font)', color: 'var(--text-2)', marginTop: 4 }}>
            {job.company} · {job.location || (job.remote ? 'Remote' : '—')}
          </div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 9 }}>
            {tags.map((t) => (
              <span key={t} style={{ height: 22, padding: '0 8px', display: 'inline-flex', alignItems: 'center', borderRadius: 6, background: 'var(--surface-2)', border: '1px solid var(--border)', color: 'var(--text-3)', font: '600 10.5px/1 var(--font)' }}>
                {t}
              </span>
            ))}
            {job.posted_date && (
              <span style={{ height: 22, padding: '0 8px', display: 'inline-flex', alignItems: 'center', borderRadius: 6, background: 'var(--surface-2)', border: '1px solid var(--border)', color: 'var(--text-3)', font: '600 10.5px/1 var(--font)' }}>
                {relativeTime(job.posted_date)}
              </span>
            )}
          </div>
        </div>
        <div style={{ flex: '0 0 auto', display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 10 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, height: 22, padding: '0 9px', borderRadius: 999, background: 'var(--surface-2)', border: '1px solid var(--border)', color: 'var(--text-3)', font: '600 10.5px/1 var(--font)' }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: src ? HEALTH_META[src.health].color : 'var(--text-4)' }} />
              {sourceLabel(job.platform)}
            </span>
            <span
              title="ATS match"
              style={{ display: 'inline-grid', placeItems: 'center', minWidth: 44, height: 26, padding: '0 9px', borderRadius: 'var(--r-sm)', font: '700 12.5px/1 var(--mono)', color: job.match_score == null ? 'var(--text-4)' : atsColor(pct), background: 'var(--surface-2)' }}
            >
              {job.match_score == null ? '—' : `${pct}%`}
            </span>
          </div>
          <div style={{ display: 'flex', gap: 7 }}>
            <a href={job.url} target="_blank" rel="noreferrer" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, height: 30, padding: '0 11px', borderRadius: 'var(--r-md)', background: 'var(--surface-2)', border: '1px solid var(--border)', color: 'var(--text-2)', font: '700 11.5px/1 var(--font)', textDecoration: 'none' }}>
              Posting
            </a>
            <button onClick={onApply} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, height: 30, padding: '0 13px', borderRadius: 'var(--r-md)', background: 'var(--accent)', border: '1px solid var(--accent)', color: 'var(--accent-ink)', font: '700 11.5px/1 var(--font)', cursor: 'pointer' }}>
              Apply
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
