import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';

import { server } from '@/__tests__/mocks/server';
import { useDiscoveryStore, DEFAULT_FILTERS } from '@/store/useDiscoveryStore';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import type { ComponentType } from 'react';

import ApplicationsPage from '@/pages/ApplicationsPage';
import AutomationPage from '@/pages/AutomationPage';
import CommunicationsPage from '@/pages/CommunicationsPage';
import DashboardPage from '@/pages/DashboardPage';
import JobSearchPage from '@/pages/JobSearchPage';
import ResumesPage from '@/pages/ResumesPage';
import SettingsPage from '@/pages/SettingsPage';
import SourcesPage from '@/pages/SourcesPage';

/**
 * A sweep over every control the operator can reach, on every main screen.
 *
 * Written after a round of per-component tests missed that a large share of the buttons in
 * the product had no tooltip and no accessible name. Those tests all passed, because each one
 * asserted the behaviour its author had thought of. This one asserts a property of the whole
 * surface instead, so a control added tomorrow without a label fails without anyone
 * remembering to write a test for it.
 *
 * "Accessible name" here is what a screen reader announces and, for an icon-only control,
 * what a sighted user gets from hovering: visible text, aria-label, or title. A control with
 * none of those is unusable by anyone who does not already know what it does.
 */

const PAGES: Array<[string, ComponentType]> = [
  ['Jobs', JobSearchPage],
  ['Applications', ApplicationsPage],
  ['Résumés', ResumesPage],
  ['Dashboard', DashboardPage],
  ['Sources', SourcesPage],
  ['Settings', SettingsPage],
  ['Automation', AutomationPage],
  ['Communications', CommunicationsPage],
];

function renderPage(Page: ComponentType) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <Page />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** What a user or a screen reader can learn about this control without clicking it. */
function accessibleName(el: HTMLElement): string {
  const aria = el.getAttribute('aria-label');
  if (aria?.trim()) return aria.trim();

  const labelledBy = el.getAttribute('aria-labelledby');
  if (labelledBy) {
    const names = labelledBy
      .split(/\s+/)
      .map((id) => document.getElementById(id)?.textContent?.trim() ?? '')
      .filter(Boolean);
    if (names.length) return names.join(' ');
  }

  const title = el.getAttribute('title');
  if (title?.trim()) return title.trim();

  // A nested element may carry the label even when the control itself does not.
  const inner = el.querySelector('[aria-label],[title]');
  const innerName =
    inner?.getAttribute('aria-label')?.trim() || inner?.getAttribute('title')?.trim();
  if (innerName) return innerName;

  return (el.textContent ?? '').replace(/\s+/g, ' ').trim();
}

function describeElement(el: HTMLElement): string {
  const cls = el.getAttribute('class');
  const id = el.getAttribute('id');
  return [
    el.tagName.toLowerCase(),
    id ? `#${id}` : '',
    cls ? `.${cls.split(/\s+/).slice(0, 2).join('.')}` : '',
  ]
    .filter(Boolean)
    .join('');
}

describe('every interactive control tells the user what it does', () => {
  it.each(PAGES)('%s', async (_label, Page) => {
    const { container } = renderPage(Page);

    // Let the first data fetch settle so controls rendered from a response are included.
    await waitFor(() => expect(container.querySelector('button, a, input')).toBeTruthy(), {
      timeout: 4000,
    });

    const controls = Array.from(
      container.querySelectorAll<HTMLElement>(
        'button, a[href], input:not([type="hidden"]), select, textarea, [role="button"], [role="tab"], [role="switch"]',
      ),
    );

    const unnamed = controls.filter((el) => {
      if (el.getAttribute('aria-hidden') === 'true') return false;
      // A placeholder is what an empty field shows the user; count it as a name.
      const placeholder = el.getAttribute('placeholder')?.trim();
      if (placeholder) return false;
      return !accessibleName(el);
    });

    expect(
      unnamed.map(describeElement),
      `${unnamed.length} control(s) on this screen have no accessible name. Give each one ` +
        'visible text, an aria-label, or a title.',
    ).toEqual([]);
  });
});

describe('icon-only controls carry a tooltip', () => {
  it('Jobs: every control with no visible text explains itself on hover', async () => {
    const { container } = renderPage(JobSearchPage);
    await waitFor(() => expect(container.querySelector('button')).toBeTruthy(), {
      timeout: 4000,
    });

    const iconOnly = Array.from(container.querySelectorAll<HTMLElement>('button, a[href]')).filter(
      (el) => !(el.textContent ?? '').trim(),
    );

    // aria-label alone serves a screen reader but leaves a sighted user hovering a mystery
    // glyph with nothing to read, so an icon-only control needs the title too.
    const withoutTooltip = iconOnly.filter((el) => !el.getAttribute('title')?.trim());

    expect(withoutTooltip.map(describeElement)).toEqual([]);
  });
});

describe('the job card shows what a candidate decides on', () => {
  beforeEach(() => {
    // The store is persisted, so a filter left on by another test hides every row and the
    // card under test never renders.
    localStorage.removeItem('cvil-war-discovery');
    useDiscoveryStore.setState({
      filters: DEFAULT_FILTERS, activeFamilies: [], enabledSources: [], selectedJobIds: [],
      appliedLocation: '', appliedQuery: '',
    });
  });

  it('renders salary and the experience bar as their own labelled pills', async () => {
    server.use(
      http.get('/api/v1/jobs/', () =>
        HttpResponse.json({
          items: [{
            id: 'j1', platform: 'remotive', platform_job_id: 'rm1',
            title: 'Senior Product Manager', company: 'Northwind Labs',
            location: 'London, UK', url: 'https://x', description: 'Own the roadmap.',
            salary_range: '£90,000 - £110,000', job_type: 'Full-time', remote: true,
            posted_date: null, experience_level: 'Senior', match_score: 0.9,
            skills_required: null, status: 'new', sponsor_confidence: 'unknown',
            posting_data: { years_required: 5 }, enriched_at: '2026-09-01T00:00:00Z',
            created_at: '2026-08-08T00:00:00Z', updated_at: '2026-08-08T00:00:00Z',
          }],
          total: 1, page: 1, page_size: 20, has_next: false,
        }),
      ),
    );
    renderPage(JobSearchPage);

    // Both are rendered even when absent: "not published" and "not fetched yet" are facts a
    // candidate wants, and a blank space communicates neither.
    expect(await screen.findByText('£90,000 - £110,000', {}, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.getByTitle(/salary as the posting states it/i)).toBeInTheDocument();

    // The experience bar comes from the posting's own wording, not a guess.
    expect(screen.getByText('5+ yrs')).toBeInTheDocument();
    expect(screen.getByTitle(/asks for 5\+ years/i)).toBeInTheDocument();
  });
});
