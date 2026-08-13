import { SOURCES } from '@/lib/sources';

/**
 * Helpers behind `components/ui/CompanyLogo`.
 *
 * They live here rather than in the component file because the project lints with
 * `--max-warnings 0`, and `react-refresh/only-export-components` (correctly) objects to a
 * component module also exporting plain functions — it breaks fast refresh.
 */

/** Known employer domains, so the guess below is only a last resort. */
const KNOWN: Record<string, string> = Object.fromEntries(
  SOURCES.map((s) => [s.label.toLowerCase(), s.domain]),
);

const SUFFIXES = /\b(ltd|limited|plc|llc|inc|group|technology|technologies|labs|uk|holdings)\b/g;

/** Best-effort company → domain. Wrong guesses simply fall back to the monogram. */
export function domainForCompany(company: string): string {
  const key = company.trim().toLowerCase();
  if (KNOWN[key]) return KNOWN[key]!;
  const slug = key
    .replace(/&/g, 'and')
    .replace(SUFFIXES, '')
    .replace(/[^a-z0-9]+/g, '');
  return slug ? `${slug}.com` : '';
}

/** Up to two uppercase initials for the monogram fallback. */
export function initials(name: string): string {
  const parts = name.replace(/[^A-Za-z0-9 ]/g, ' ').trim().split(/\s+/);
  return ((parts[0]?.[0] ?? '?') + (parts[1]?.[0] ?? '')).toUpperCase();
}
