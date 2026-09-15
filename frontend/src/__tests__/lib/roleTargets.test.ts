import { describe, expect, it } from 'vitest';
import { DEFAULT_ACTIVE_TITLES, queryForTitles } from '@/lib/roleTargets';

describe('queryForTitles', () => {
  it('joins titles with a comma and space', () => {
    expect(queryForTitles(['AI PM', 'ML Engineer'])).toBe('AI PM, ML Engineer');
  });

  it('caps at 15 titles even when more are active', () => {
    // Regression: the default 31 active titles joined unbounded produced a ~690-char
    // query, which 422'd against the backend's length cap — job discovery returned
    // zero results with no visible error, which looked like the whole feature (bulk
    // select, previews) was broken since there was nothing on screen to interact with.
    const titles = Array.from({ length: 31 }, (_, i) => `Role Title ${i}`);
    const result = queryForTitles(titles);
    expect(result.split(', ')).toHaveLength(15);
    expect(result).toBe(titles.slice(0, 15).join(', '));
  });

  it('the real default active title list produces a query under the backend limit', () => {
    const result = queryForTitles(DEFAULT_ACTIVE_TITLES);
    expect(result.length).toBeLessThan(2000);
  });

  it('handles an empty list', () => {
    expect(queryForTitles([])).toBe('');
  });
});
