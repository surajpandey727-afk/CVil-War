/**
 * Location and work-arrangement controls for the Jobs rail.
 *
 * Every job the list returns is already UK-eligible (the server enforces that), so these narrow
 * *within* the UK: a city, London including its boroughs and postcodes, or the whole country.
 * The counts underneath say how many stored jobs the UK policy is keeping off the list, so a
 * short list is never mistaken for an empty market.
 */
import Chip from '@/components/jobs/Chip';
import { useLocationSummary } from '@/hooks/useJobs';
import { useDiscoveryStore, type WorkplaceFilter } from '@/store/useDiscoveryStore';

/** `value` is what the server's location filter receives. "" means the whole UK. */
const UK_PLACES: { label: string; value: string; hint: string }[] = [
  { label: 'All UK', value: '', hint: 'Every verified UK role, nationwide' },
  { label: 'London', value: 'London', hint: 'Greater London: the boroughs, districts such as Canary Wharf, and London postcodes' },
  { label: 'Manchester', value: 'Manchester', hint: 'Manchester and Salford' },
  { label: 'Birmingham', value: 'Birmingham', hint: 'Birmingham, UK' },
  { label: 'Leeds', value: 'Leeds', hint: 'Leeds' },
  { label: 'Bristol', value: 'Bristol', hint: 'Bristol' },
  { label: 'Edinburgh', value: 'Edinburgh', hint: 'Edinburgh' },
  { label: 'Glasgow', value: 'Glasgow', hint: 'Glasgow' },
  { label: 'Cambridge', value: 'Cambridge', hint: 'Cambridge, UK' },
  { label: 'Oxford', value: 'Oxford', hint: 'Oxford' },
  { label: 'Cardiff', value: 'Cardiff', hint: 'Cardiff' },
  { label: 'Belfast', value: 'Belfast', hint: 'Belfast' },
];

const ARRANGEMENTS: { key: WorkplaceFilter; label: string; hint: string }[] = [
  { key: 'any', label: 'Any', hint: 'On-site, hybrid, remote, and postings that do not say' },
  { key: 'onsite', label: 'On-site', hint: 'The posting says the role is office-based' },
  { key: 'hybrid', label: 'Hybrid', hint: 'The posting says hybrid' },
  { key: 'remote', label: 'UK remote', hint: 'Remote roles open to UK-based candidates' },
];

/** Normalise the applied location so "London, UK" and "London" light the same chip. */
function activePlace(applied: string): string {
  const head = applied.split(',')[0]?.trim().toLowerCase() ?? '';
  if (['', 'uk', 'united kingdom', 'gb', 'great britain'].includes(head)) return '';
  return UK_PLACES.find((p) => p.value.toLowerCase() === head)?.value ?? applied;
}

export default function LocationRail({ cardStyle }: { cardStyle: React.CSSProperties }) {
  const { appliedLocation, applyLocation, filters, patchFilters } = useDiscoveryStore();
  const { data: summary } = useLocationSummary();
  const current = activePlace(appliedLocation);
  const custom = current !== '' && !UK_PLACES.some((p) => p.value === current);

  return (
    <div style={{ ...cardStyle, padding: 14 }}>
      <div style={{ font: '700 12.5px/1 var(--font)', marginBottom: 12 }}>Location</div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 12 }} role="group" aria-label="UK location">
        {UK_PLACES.map((p) => (
          <Chip key={p.label} small on={current === p.value} title={p.hint} onClick={() => applyLocation(p.value)}>
            {p.label}
          </Chip>
        ))}
        {custom && (
          <Chip small on title={`Filtering to "${appliedLocation}" — typed in the search bar`} onClick={() => applyLocation('')}>
            {appliedLocation} ×
          </Chip>
        )}
      </div>
      <div style={{ font: '600 10px/1 var(--mono)', letterSpacing: '.12em', color: 'var(--text-4)', marginBottom: 8 }}>
        WORK ARRANGEMENT
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }} role="group" aria-label="Work arrangement">
        {ARRANGEMENTS.map((a) => (
          <Chip key={a.key} small on={filters.workplace === a.key} title={a.hint} onClick={() => patchFilters({ workplace: a.key })}>
            {a.label}
          </Chip>
        ))}
      </div>
      {summary && summary.total > summary.uk_eligible && (
        <div
          style={{ font: '500 10.5px/1.45 var(--font)', color: 'var(--text-4)', marginTop: 12 }}
          title="CVil-War lists UK roles only. Jobs whose own location places them outside the UK are hidden; ones whose location is ambiguous (e.g. 'Remote', 'EMEA', a bare 'Cambridge') are held back until verified. Nothing is deleted."
        >
          UK roles only · {summary.outside_uk} outside the UK hidden
          {summary.quarantined > 0 && ` · ${summary.quarantined} with an unverified location held back`}
        </div>
      )}
    </div>
  );
}
