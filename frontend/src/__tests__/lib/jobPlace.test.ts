/**
 * The "City, Country · Posted … · Arrangement" line. The rule these pin: an unknown is said
 * out loud, never filled in from another field — above all, the discovery date is never
 * shown as the posting date.
 */
import { describe, it, expect } from 'vitest';

import { placeLabel, postedInfo, workplaceOf, WORKPLACE_LABEL } from '@/lib/jobPlace';
import type { Job } from '@/types/job';

const base = {
  id: 'j', platform: 'reed', platform_job_id: 'r', title: 'PM', company: 'Acme',
  location: 'EC4N6EU', url: 'https://x', description: '', salary_range: null, job_type: null,
  remote: false, posted_date: null, experience_level: null, match_score: null,
  skills_required: null, status: 'new', created_at: '2026-10-20T00:00:00Z',
  updated_at: '2026-10-20T00:00:00Z', sponsor_confidence: 'unknown', sponsor_evidence: null,
} as Job;

describe('placeLabel', () => {
  it('shows the normalised city and country, not the raw postcode', () => {
    expect(placeLabel({ ...base, city: 'London', country_code: 'GB', country_name: 'United Kingdom' }))
      .toBe('London, United Kingdom');
  });

  it('shows the country alone for a UK-wide role', () => {
    expect(placeLabel({ ...base, city: null, country_code: 'GB', country_name: 'United Kingdom' }))
      .toBe('United Kingdom');
  });

  it('falls back to the raw text for a response from before the policy', () => {
    expect(placeLabel(base)).toBe('EC4N6EU');
  });

  it('says so when there is no location at all', () => {
    expect(placeLabel({ ...base, location: '' })).toBe('Location not stated');
  });
});

describe('postedInfo', () => {
  const now = new Date('2026-10-24T12:00:00Z');

  it('formats a known posting date with its age', () => {
    const info = postedInfo({ ...base, posted_at: '2026-10-03T09:00:00Z' }, now);
    expect(info.known).toBe(true);
    expect(info.label).toBe('Posted 3 Oct 2026');
    expect(info.ago).toBe('21 days ago');
    expect(info.days).toBe(21);
  });

  it('says "today" and "1 day ago" rather than "0 days"', () => {
    expect(postedInfo({ ...base, posted_at: '2026-10-24T08:00:00Z' }, now).ago).toBe('today');
    expect(postedInfo({ ...base, posted_at: '2026-10-23T08:00:00Z' }, now).ago).toBe('1 day ago');
  });

  it('reports an unknown date as unavailable — never substitutes the discovery date', () => {
    const info = postedInfo({ ...base, posted_at: null, discovered_at: '2026-10-20T00:00:00Z' }, now);
    expect(info.known).toBe(false);
    expect(info.label).toBe('Posting date unavailable');
    expect(info.days).toBeNull();
  });

  it('treats an unparseable date as unknown', () => {
    expect(postedInfo({ ...base, posted_at: 'last week' }, now).known).toBe(false);
  });
});

describe('workplaceOf', () => {
  it('prefers the server-derived arrangement', () => {
    expect(workplaceOf({ ...base, workplace_type: 'hybrid', remote: true })).toBe('hybrid');
  });

  it('falls back to the legacy remote flag, else "not stated" rather than guessing on-site', () => {
    expect(workplaceOf({ ...base, remote: true })).toBe('remote');
    expect(workplaceOf(base)).toBe('unspecified');
    expect(WORKPLACE_LABEL.unspecified).toBe('Arrangement not stated');
  });
});
