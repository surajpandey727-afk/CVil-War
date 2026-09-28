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

const JOB = {
  id: 'j1', platform: 'remotive', platform_job_id: 'rm1', title: 'Senior Product Manager',
  company: 'Northwind Labs', location: 'London, UK', url: 'https://example.invalid/j1',
  description: 'Own the roadmap.', salary_range: '£90,000 - £110,000', job_type: 'Full-time',
  remote: true, posted_date: '2026-09-01T00:00:00Z', experience_level: 'Senior',
  match_score: 0.9, skills_required: null, status: 'new', sponsor_confidence: 'unknown',
  posting_data: { years_required: 5 }, enriched_at: '2026-09-01T00:00:00Z',
  created_at: '2026-08-08T00:00:00Z', updated_at: '2026-08-08T00:00:00Z',
};


const RESUME = {
  id: 'r1', name: 'Base CV', type: 'base', template_id: 'modern', base_resume_id: null,
  job_id: null, has_pdf: true, has_docx: true, ats_score: 0.8, used_in_applications: 1,
  submitted_applications: 0, archived: false, tailoring_audit: null,
  created_at: '2026-08-01T00:00:00Z', updated_at: '2026-08-01T00:00:00Z',
};

const page = (items: object[]) => ({
  items, total: items.length, page: 1, page_size: 20, has_next: false,
});

/**
 * Seed every list endpoint the audited pages read.
 *
 * Without this the sweep runs against empty states. Apply, Approve and Disconnect are all
 * rendered per row, so with no rows there is nothing to audit and the suite passes while
 * checking nothing -- which is exactly how a screenful of unexplained buttons reached the
 * operator with a green test run behind it.
 */
function seedPages() {
  server.use(
    http.get('/api/v1/jobs/', () => HttpResponse.json(page([JOB]))),
    http.get('/api/v1/resumes/', () =>
      HttpResponse.json({ items: [RESUME], total: 1, archived_count: 0 }),
    ),
  );
}

const PAGES: Array<[string, ComponentType, string | null]> = [
  ['Jobs', JobSearchPage, 'Senior Product Manager'],
  ['Applications', ApplicationsPage, null],
  ['Résumés', ResumesPage, 'Base CV'],
  ['Dashboard', DashboardPage, null],
  ['Sources', SourcesPage, null],
  ['Settings', SettingsPage, null],
  ['Automation', AutomationPage, null],
  ['Communications', CommunicationsPage, null],
];

/** Wait until the page has rendered its seeded data, not merely its chrome. */
async function settled(container: HTMLElement, marker: string | null): Promise<void> {
  if (marker) {
    await waitFor(() => expect(container.textContent).toContain(marker), { timeout: 5000 });
    return;
  }
  await waitFor(() => expect(container.querySelector('button, a, input')).toBeTruthy(), {
    timeout: 5000,
  });
}

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
  beforeEach(() => {
    localStorage.removeItem('cvil-war-discovery');
    useDiscoveryStore.setState({
      filters: DEFAULT_FILTERS, activeFamilies: [], enabledSources: [], selectedJobIds: [],
      appliedLocation: '', appliedQuery: '',
    });
  });

  it.each(PAGES)('%s', async (_label, Page, marker) => {
    seedPages();
    const { container } = renderPage(Page);
    await settled(container, marker);

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
            salary_range: '£90,000 - £110,000',
            salary_min: 90000, salary_max: 110000, salary_currency: 'GBP',
            salary_period: 'year', salary_annualised: false,
            sponsorship_status: 'not_specified',
            job_type: 'Full-time', remote: true,
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
    // The pill shows the canonical band -- the same figures the salary filter and sort read --
    // and its tooltip quotes the posting's own wording so the two can be checked against
    // each other.
    expect(await screen.findByText('£90k–£110k', {}, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.getByTitle(/the posting states £90,000 - £110,000/i)).toBeInTheDocument();

    // Sponsorship is now on every card, including when the posting never mentions it.
    expect(screen.getByText('Not stated')).toBeInTheDocument();

    // The experience bar comes from the posting's own wording, not a guess.
    expect(screen.getByText('5+ yrs')).toBeInTheDocument();
    expect(screen.getByTitle(/asks for 5\+ years/i)).toBeInTheDocument();
  });
});

/**
 * Verbs whose consequence the label does not carry.
 *
 * "Cancel" on a dialog explains itself and a tooltip on every control is noise. These are the
 * actions where the word names what happens but not to what, or not how permanently:
 * approving releases work to the agent, disconnecting deletes a stored sign-in, clearing a
 * filter changes what the operator is looking at. This list is the gap the name-only sweep
 * above could not see -- every one of these controls had an accessible name and still told
 * the user nothing about what pressing it would do.
 */
const CONSEQUENTIAL =
  /^(apply|run|generate|delete|remove|approve|reject|sync|connect|disconnect|enable|disable|test|commit|retry|reset|clear|archive|submit|queue|start|stop|publish|send|import|export|score|optimi[sz]e)\b/i;

describe('actions that do something explain what they will do', () => {
  beforeEach(() => {
    localStorage.removeItem('cvil-war-discovery');
    useDiscoveryStore.setState({
      filters: DEFAULT_FILTERS, activeFamilies: [], enabledSources: [], selectedJobIds: [],
      appliedLocation: '', appliedQuery: '',
    });
  });

  it.each(PAGES)('%s', async (_label, Page) => {
    seedPages();
    const { container } = renderPage(Page);
    await waitFor(() => expect(container.querySelector('button')).toBeTruthy(), {
      timeout: 4000,
    });

    const consequential = Array.from(
      container.querySelectorAll<HTMLElement>('button, [role="button"]'),
    ).filter((el) => {
      if (el.hasAttribute('disabled')) return false;
      const text = (el.textContent ?? '').replace(/\s+/g, ' ').trim();
      return CONSEQUENTIAL.test(text);
    });

    const unexplained = consequential.filter((el) => !el.getAttribute('title')?.trim());

    expect(
      unexplained.map((el) => `${describeElement(el)} "${(el.textContent ?? '').trim().slice(0, 40)}"`),
      'These controls start work, change stored state or cannot be undone. Give each a ' +
        'title saying what it will do and to what.',
    ).toEqual([]);
  });
});

describe('the sweep is not passing vacuously', () => {
  beforeEach(() => {
    localStorage.removeItem('cvil-war-discovery');
    useDiscoveryStore.setState({
      filters: DEFAULT_FILTERS, activeFamilies: [], enabledSources: [], selectedJobIds: [],
      appliedLocation: '', appliedQuery: '',
    });
  });

  it('finds a real population of controls to audit on the Jobs screen', async () => {
    seedPages();
    const { container } = renderPage(JobSearchPage);
    await settled(container, 'Senior Product Manager');

    // The first version of this suite reported zero consequential controls on all eight
    // pages and passed. A guard that cannot fail is worse than no guard, because it is
    // mistaken for coverage.
    const consequential = Array.from(container.querySelectorAll<HTMLElement>('button')).filter(
      (el) => CONSEQUENTIAL.test((el.textContent ?? '').replace(/\s+/g, ' ').trim()),
    );
    expect(consequential.length).toBeGreaterThan(0);
  });
});
