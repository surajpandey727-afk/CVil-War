import { http, HttpResponse } from 'msw';

import { DEFAULT_AUTOMATION } from '@/types/settings';

/** The stored policy the catalogue handler reports. Shipped defaults, so a test that cares
 *  about a specific value overrides the handler rather than depending on this one. */
const DEFAULT_TEST_POLICY = DEFAULT_AUTOMATION;

/** Sample job listing used across tests. */
const sampleJob = {
  id: 'job-1',
  platform: 'linkedin',
  platform_job_id: 'ln-12345',
  title: 'Senior Frontend Engineer',
  company: 'Acme Corp',
  location: 'San Francisco, CA',
  url: 'https://linkedin.com/jobs/12345',
  description: 'We are looking for a senior frontend engineer.',
  salary_range: '$150k - $200k',
  job_type: 'Full-time',
  remote: true,
  posted_date: '2026-03-10',
  experience_level: 'Senior',
  match_score: 0.85,
  skills_required: { react: true, typescript: true },
  status: 'new',
  created_at: '2026-03-10T12:00:00Z',
  updated_at: '2026-03-10T12:00:00Z',
};

const sampleJob2 = {
  ...sampleJob,
  id: 'job-2',
  platform_job_id: 'ln-67890',
  title: 'Backend Developer',
  company: 'Tech Inc',
  location: 'Remote',
  match_score: 0.62,
  remote: false,
  salary_range: null,
  job_type: null,
};

/** MSW v2 request handlers for all API endpoints. */
export const handlers = [
  // Auth
  http.post('/api/v1/auth/register', async ({ request }) => {
    const body = (await request.json()) as { email: string; full_name?: string };
    return HttpResponse.json(
      { id: 'user-1', email: body.email, full_name: body.full_name ?? null, is_active: true },
      { status: 201 },
    );
  }),

  http.post('/api/v1/auth/login', () => {
    return HttpResponse.json({ access_token: 'test-access-token', token_type: 'bearer' });
  }),

  http.get('/api/v1/auth/me', ({ request }) => {
    if (!request.headers.get('Authorization')) {
      return new HttpResponse(null, { status: 401 });
    }
    return HttpResponse.json({
      id: 'user-1',
      email: 'test@example.com',
      full_name: null,
      is_active: true,
    });
  }),

  http.get('/api/v1/auth/ws-ticket', () => {
    return HttpResponse.json({ ticket: 'test-ws-ticket' });
  }),

  // Phase-0 has no refresh endpoint; default to "no session".
  http.post('/api/v1/auth/refresh', () => {
    return new HttpResponse(null, { status: 401 });
  }),

  // Jobs
  http.get('/api/v1/jobs/', () => {
    return HttpResponse.json({
      items: [sampleJob, sampleJob2],
      total: 2,
      page: 1,
      page_size: 20,
      has_next: false,
    });
  }),

  http.post('/api/v1/jobs/search', () => {
    return HttpResponse.json({
      items: [sampleJob],
      total: 1,
      page: 1,
      page_size: 20,
      has_next: false,
    });
  }),

  http.get('/api/v1/jobs/:jobId', ({ params }) => {
    if (params['jobId'] === 'job-1') {
      return HttpResponse.json(sampleJob);
    }
    return new HttpResponse(null, { status: 404 });
  }),

  http.patch('/api/v1/jobs/:jobId', async ({ request, params }) => {
    const body = (await request.json()) as { status: string };
    return HttpResponse.json({ ...sampleJob, id: params['jobId'], status: body.status });
  }),

  http.post('/api/v1/jobs/:jobId/analyze', () => {
    return HttpResponse.json({
      job_id: 'job-1',
      match_score: 0.85,
      skill_match: 0.9,
      keyword_match: 0.8,
      missing_skills: ['GraphQL'],
      suggestions: ['Add GraphQL experience to resume'],
    });
  }),

  // Fit + company. Default to "nothing stored yet" so a drawer that opens does not
  // silently render a cached analysis a test did not set up.
  http.get('/api/v1/jobs/:jobId/fit', () => HttpResponse.json(null)),

  http.post('/api/v1/jobs/:jobId/fit', () =>
    HttpResponse.json({
      job_id: 'job-1', resume_id: 'resume-1', resume_name: 'my_resume.pdf',
      overall: 0.72,
      categories: [
        { key: 'required_skills', label: 'Required skills', score: 0.8, rationale: '', method: 'Average of match levels.' },
      ],
      not_assessed: [], matches: [], recommendations: [],
      method: 'keyword', model: '', analysed_at: null, cached: false, stale_reason: '',
    }),
  ),

  http.get('/api/v1/jobs/:jobId/company', () =>
    HttpResponse.json({
      name: 'Acme Corp', available: true, website: null, website_source: '',
      industry: null, description: null, source: 'linkedin',
      other_jobs: [], other_jobs_count: 0,
      unavailable_fields: ['Website', 'Industry', 'Company size'],
      unavailable_reason: 'This job came from an aggregator.',
    }),
  ),

  // Résumé recommendation (floating ATS widget). Default to "no résumés yet" so a drawer
  // that opens in a test does not silently render a made-up score no test set up.
  http.get('/api/v1/jobs/:jobId/resume-recommendation', ({ params }) =>
    HttpResponse.json({
      job_id: params.jobId, recommended_resume_id: null, rankings: [], synopsis: '',
    }),
  ),

  http.delete('/api/v1/jobs/:jobId', () => {
    return new HttpResponse(null, { status: 204 });
  }),

  // Resumes
  http.get('/api/v1/resumes/', () => {
    return HttpResponse.json({
      items: [
        {
          id: 'resume-1',
          filename: 'my_resume.pdf',
          template: 'modern',
          created_at: '2026-03-01T00:00:00Z',
          updated_at: '2026-03-01T00:00:00Z',
        },
      ],
      total: 1,
      page: 1,
      page_size: 20,
      has_next: false,
    });
  }),

  http.get('/api/v1/resumes/:resumeId/download', () => {
    return new HttpResponse(new Blob(['%PDF-1.4 test'], { type: 'application/pdf' }), {
      headers: { 'Content-Type': 'application/pdf' },
    });
  }),

  http.get('/api/v1/resumes/:resumeId/usage', ({ params }) => {
    return HttpResponse.json({
      resume_id: params['resumeId'],
      total: 0,
      submitted: 0,
      items: [],
    });
  }),

  http.delete('/api/v1/resumes/:resumeId', ({ params }) => {
    return HttpResponse.json({
      resume_id: params['resumeId'],
      deleted: true,
      archived: false,
      used_by: 0,
      detail: 'Deleted, along with its stored files. It had never been sent to an employer.',
    });
  }),

  http.post('/api/v1/resumes/upload', () => {
    return HttpResponse.json({
      id: 'resume-2',
      filename: 'uploaded_resume.pdf',
      status: 'uploaded',
    });
  }),

  http.post('/api/v1/resumes/generate', () => {
    return HttpResponse.json({
      id: 'resume-3',
      filename: 'generated_resume.pdf',
      template: 'modern',
      created_at: '2026-03-15T00:00:00Z',
      updated_at: '2026-03-15T00:00:00Z',
    });
  }),

  http.post('/api/v1/resumes/:resumeId/score', () => {
    return HttpResponse.json({
      resume_id: 'resume-1',
      job_id: 'job-1',
      score: 78,
      suggestions: ['Add more keywords'],
    });
  }),

  http.post('/api/v1/resumes/:resumeId/optimize', () => {
    return HttpResponse.json({
      id: 'resume-1',
      filename: 'optimized_resume.pdf',
      template: 'modern',
      created_at: '2026-03-01T00:00:00Z',
      updated_at: '2026-03-15T00:00:00Z',
    });
  }),

  // Applications
  http.get('/api/v1/applications/', () => {
    return HttpResponse.json({
      items: [
        {
          id: 'app-1',
          job_id: 'job-1',
          resume_id: 'resume-1',
          status: 'pending',
          created_at: '2026-03-12T00:00:00Z',
          updated_at: '2026-03-12T00:00:00Z',
        },
      ],
      total: 1,
      page: 1,
      page_size: 20,
      has_next: false,
    });
  }),

  http.post('/api/v1/applications/', () => {
    return HttpResponse.json({
      id: 'app-2',
      job_id: 'job-1',
      resume_id: 'resume-1',
      status: 'pending',
      created_at: '2026-03-15T00:00:00Z',
      updated_at: '2026-03-15T00:00:00Z',
    });
  }),

  http.post('/api/v1/applications/batch', () => {
    return HttpResponse.json([
      {
        id: 'app-3',
        job_id: 'job-1',
        resume_id: 'resume-1',
        status: 'pending',
        created_at: '2026-03-15T00:00:00Z',
        updated_at: '2026-03-15T00:00:00Z',
      },
    ]);
  }),

  http.get('/api/v1/applications/:appId', () => {
    return HttpResponse.json({
      id: 'app-1',
      job_id: 'job-1',
      resume_id: 'resume-1',
      status: 'pending',
      created_at: '2026-03-12T00:00:00Z',
      updated_at: '2026-03-12T00:00:00Z',
    });
  }),

  http.put('/api/v1/applications/:appId/approve', () => {
    return HttpResponse.json({
      id: 'app-1',
      job_id: 'job-1',
      resume_id: 'resume-1',
      status: 'approved',
      created_at: '2026-03-12T00:00:00Z',
      updated_at: '2026-03-15T00:00:00Z',
    });
  }),

  http.put('/api/v1/applications/:appId/status', () => {
    return HttpResponse.json({
      id: 'app-1',
      job_id: 'job-1',
      resume_id: 'resume-1',
      status: 'submitted',
      created_at: '2026-03-12T00:00:00Z',
      updated_at: '2026-03-15T00:00:00Z',
    });
  }),

  // Analytics
  http.get('/api/v1/analytics/dashboard', () => {
    return HttpResponse.json({
      total_jobs: 150,
      total_applications: 45,
      interviews_scheduled: 5,
      avg_match_score: 0.72,
    });
  }),

  http.get('/api/v1/analytics/funnel', () => {
    return HttpResponse.json([
      { stage: 'Applied', count: 45 },
      { stage: 'Screening', count: 20 },
      { stage: 'Interview', count: 5 },
      { stage: 'Offer', count: 1 },
    ]);
  }),

  http.get('/api/v1/analytics/ats-scores', () => {
    return HttpResponse.json([
      { range: '0-25', count: 5 },
      { range: '26-50', count: 15 },
      { range: '51-75', count: 20 },
      { range: '76-100', count: 10 },
    ]);
  }),

  http.get('/api/v1/analytics/llm-usage', () => {
    return HttpResponse.json([
      { provider: 'openai', tokens_used: 50000, cost: 2.5 },
      { provider: 'anthropic', tokens_used: 30000, cost: 1.8 },
    ]);
  }),

  http.get('/api/v1/analytics/timeline', () => {
    return HttpResponse.json([
      { date: '2026-03-10', applications: 5, jobs_found: 20 },
      { date: '2026-03-11', applications: 3, jobs_found: 15 },
    ]);
  }),

  // Application evidence. Deliberately a *complete* bundle here; individual tests override
  // this handler to exercise the "not recorded" paths, which is where the interesting
  // behaviour lives.
  http.get('/api/v1/applications/:appId/evidence', ({ params }) => {
    return HttpResponse.json({
      application_id: params['appId'],
      job: {
        recorded: true,
        job_id: 'job-1',
        title: 'Senior Product Manager',
        company: 'Zartis',
        location: 'London, UK',
        salary: '£75,000 - £95,000',
        remote: false,
        source: 'reed',
        job_url: 'https://www.reed.co.uk/jobs/senior-product-manager/56654149',
        application_url: null,
        posted_at: null,
      },
      submission: {
        status: 'applied',
        method: 'automated',
        confirmation_state: 'confirmed',
        confirmation_detail: 'Application submitted — reference REED-88213',
        external_reference: 'REED-88213',
        submitted_at: '2026-08-13T21:05:00Z',
        ats_score: 0.72,
        apply_mode: 'review',
        origin: 'discovery',
        actor: 'agent',
        recorded: true,
      },
      resume: {
        recorded: true,
        document_id: 'resume-1',
        name: 'AI Product Manager CV',
        kind: 'tailored',
        ats_score: 0.88,
        created_at: '2026-08-12T10:00:00Z',
        archived: false,
        has_pdf: true,
        has_docx: false,
      },
      cover_letter: { recorded: true, used: true, name: 'zartis-cl-v2.pdf', origin: 'generated' },
      account: {
        recorded: true,
        platform: 'reed',
        account: 'sur***@example.com',
        connected: true,
        state: 'session_active',
        detail: null,
        last_used_at: '2026-08-13T21:04:00Z',
      },
      failure: null,
      log: [
        { at: '2026-08-13T21:04:12Z', source: 'application', kind: 'discovered', message: 'Job discovered', detail: null, actor: 'system' },
        { at: '2026-08-13T21:05:05Z', source: 'automation', kind: 'step_1', message: 'Submission confirmation detected', detail: null, actor: 'agent' },
      ],
      log_recorded: true,
    });
  }),

  // The source registry. Settings now renders platforms from this rather than a list kept
  // on the page, so it is part of the default set — the setup runs MSW with
  // onUnhandledRequest:'error', which is what caught the omission.
  http.get('/api/v1/sources/', () => {
    return HttpResponse.json({
      total: 55,
      tiers: [
        {
          id: 'aggregator',
          label: 'Aggregators',
          sources: [
            { key: 'remotive', label: 'Remotive', health: 'live', implemented: true },
            { key: 'adzuna', label: 'Adzuna', health: 'live', implemented: true },
          ],
        },
      ],
      live_keys: ['remotive', 'adzuna'],
    });
  }),

  // Settings
  http.get('/api/v1/settings/', () => {
    return HttpResponse.json({
      id: 'settings-1',
      default_template: 'modern',
      auto_apply: false,
      platforms: ['linkedin', 'indeed'],
      llm_provider: 'openai',
    });
  }),

  http.put('/api/v1/settings/', () => {
    return HttpResponse.json({
      id: 'settings-1',
      default_template: 'modern',
      auto_apply: true,
      platforms: ['linkedin', 'indeed'],
      llm_provider: 'openai',
    });
  }),

  // The automation policy catalogue. Only a few rules, one per control kind that the page
  // renders differently — the point of the schema-driven page is that it does not know the
  // real list, so a test that mirrored the backend's twenty-odd rules would be asserting on
  // a copy rather than on the rendering.
  http.get('/api/v1/settings/automation-policy', () => {
    return HttpResponse.json({
      policy_version: 1,
      document: 'docs/AUTOMATION_POLICY.md',
      groups: [
        {
          id: 'oversight',
          title: 'Human oversight',
          rules: [
            {
              id: 'oversight.kill_switch',
              clause: '§4.2',
              title: 'Pause all automation',
              rationale: 'Everything queued stays queued.',
              enforcement: 'gate',
              verdict: 'hold',
              locked: false,
              control: { kind: 'toggle', min: null, max: null, step: null, unit: '', options: [] },
              field_name: 'paused',
              enforced_by: '',
              value: false,
            },
            {
              id: 'oversight.high_value_review',
              clause: '§4.3',
              title: 'Review roles above',
              rationale: 'The cost of a bad automated application scales with the role.',
              enforcement: 'gate',
              verdict: 'escalate',
              locked: false,
              control: { kind: 'money_k', min: 0, max: 500, step: 10, unit: '£k', options: [] },
              field_name: 'require_review_above_salary_k',
              enforced_by: '',
              value: 120,
            },
          ],
        },
        {
          id: 'volume',
          title: 'Volume & rate',
          rules: [
            {
              id: 'volume.daily_cap',
              clause: '§2.1',
              title: 'Applications per day',
              rationale: 'Above a considered human pace, below anything read as scripted.',
              enforcement: 'gate',
              verdict: 'hold',
              locked: false,
              control: { kind: 'integer', min: 0, max: 200, step: 1, unit: 'per day', options: [] },
              field_name: 'max_per_day',
              enforced_by: '',
              value: 20,
            },
          ],
        },
        {
          id: 'integrity',
          title: 'Integrity — not configurable',
          rules: [
            {
              id: 'integrity.no_fabrication',
              clause: '§1.1',
              title: 'Never invent experience',
              rationale: 'The agent may re-word what is in your CV. It may not invent it.',
              enforcement: 'elsewhere',
              verdict: 'hold',
              locked: true,
              control: { kind: 'locked', min: null, max: null, step: null, unit: '', options: [] },
              field_name: '',
              enforced_by: 'app.services.resume',
              value: null,
            },
          ],
        },
      ],
      policy: {
        ...DEFAULT_TEST_POLICY,
      },
    });
  }),

  http.post('/api/v1/settings/automation-policy/preview', () => {
    return HttpResponse.json({
      evaluated: 2,
      allow: 1,
      hold: 1,
      escalate: 0,
      block: 0,
      items: [
        {
          application_id: 'app-1',
          job_title: 'Product Manager',
          company: 'Monzo',
          verdict: 'allow',
          reasons: [],
          rule_ids: [],
        },
        {
          application_id: 'app-2',
          job_title: 'Staff Product Manager',
          company: 'Wise',
          verdict: 'hold',
          reasons: ['ATS match 61% is below your 75% threshold.'],
          rule_ids: ['match.min_ats_score'],
        },
      ],
    });
  }),

  // The AI control plane. Shaped like the real gateway's /v1/models response, trimmed —
  // tests that care about a specific state override these.
  http.get('/api/v1/settings/platforms', () =>
    HttpResponse.json({
      total: 3,
      usable: 2,
      connected: 1,
      platforms: [
        {
          key: 'remotive', label: 'Remotive', tier: 'aggregator', health: 'live',
          implemented: true, needs_credential: false, capabilities: ['search'],
          enabled: true, connected: false, connection_state: 'not_connected',
          account: null, last_used_at: null, expires_at: null, detail: null, last_error: null,
          actions: [
            { key: 'toggle', label: 'Enable for discovery', available: true, reason: '' },
            { key: 'connect', label: 'Connect', available: false, reason: 'This source is a public API and needs no login.' },
            { key: 'test', label: 'Test', available: true, reason: '' },
          ],
        },
        {
          key: 'linkedin', label: 'LinkedIn', tier: 'board', health: 'degraded',
          implemented: true, needs_credential: true, capabilities: ['search'],
          enabled: false, connected: true, connection_state: 'session_active',
          account: 'sur***@example.com', last_used_at: null, expires_at: null,
          detail: null, last_error: null,
          actions: [
            { key: 'toggle', label: 'Enable for discovery', available: true, reason: '' },
            { key: 'connect', label: 'Reconnect', available: true, reason: '' },
            { key: 'disconnect', label: 'Disconnect', available: true, reason: '' },
            { key: 'test', label: 'Test', available: false, reason: 'Nothing to test until an adapter can reach this source.' },
          ],
        },
        {
          key: 'careers:starling', label: 'Starling Bank', tier: 'careers',
          health: 'not_implemented', implemented: false, needs_credential: false,
          capabilities: [], enabled: false, connected: false,
          connection_state: 'not_connected', account: null, last_used_at: null,
          expires_at: null, detail: null,
          last_error: 'No public ATS board found.',
          actions: [
            { key: 'toggle', label: 'Enable for discovery', available: false, reason: 'No adapter can serve this source yet.' },
            { key: 'connect', label: 'Connect', available: false, reason: 'This source is a public API and needs no login.' },
            { key: 'test', label: 'Test', available: false, reason: 'Nothing to test until an adapter can reach this source.' },
          ],
        },
      ],
    }),
  ),

  http.delete('/api/v1/platform-sessions/:platform', () => new HttpResponse(null, { status: 204 })),

  // Interactive login capture. The default handler settles immediately as connected; tests
  // that care about the waiting states override it.
  http.post('/api/v1/platform-sessions/connect', async ({ request }) => {
    const body = (await request.json()) as { platform: string };
    return HttpResponse.json(
      {
        id: 'attempt-1',
        platform: body.platform,
        state: 'awaiting_login',
        done: false,
        instructions: 'Sign in to LinkedIn as you normally would.',
        detail: '',
        seconds_remaining: 600,
      },
      { status: 202 },
    );
  }),

  http.get('/api/v1/platform-sessions/connect/:id', ({ params }) =>
    HttpResponse.json({
      id: params['id'],
      platform: 'linkedin',
      state: 'connected',
      done: true,
      instructions: '',
      detail: 'Connected. 4 session cookies for linkedin were stored, encrypted.',
      seconds_remaining: 0,
    }),
  ),

  http.delete('/api/v1/platform-sessions/connect/:id', ({ params }) =>
    HttpResponse.json({
      id: params['id'],
      platform: 'linkedin',
      state: 'cancelled',
      done: true,
      instructions: '',
      detail: 'Cancelled before sign-in completed.',
      seconds_remaining: 0,
    }),
  ),

  http.get('/api/v1/settings/ai/catalogue', () => {
    return HttpResponse.json({
      reachable: true,
      error: null,
      base_url: 'http://localhost:20128/v1',
      provider_count: 2,
      model_count: 3,
      default_model: 'openai/Full-Send',
      default_model_available: true,
      providers: [
        {
          id: 'combo',
          model_count: 2,
          models: [
            { id: 'Full-Send', provider: 'combo', capabilities: ['tool_calling', 'reasoning'], context_length: 128000, max_input_tokens: null, max_output_tokens: null, is_default: true },
            { id: 'combo/fast', provider: 'combo', capabilities: [], context_length: null, max_input_tokens: null, max_output_tokens: null, is_default: false },
          ],
        },
        {
          id: 'groq',
          model_count: 1,
          models: [
            { id: 'groq/llama-3.3-70b', provider: 'groq', capabilities: ['tool_calling'], context_length: 8192, max_input_tokens: null, max_output_tokens: null, is_default: false },
          ],
        },
      ],
    });
  }),

  http.get('/api/v1/settings/ai/usage', ({ request }) => {
    const period = new URL(request.url).searchParams.get('period') ?? '7d';
    return HttpResponse.json({
      period,
      recorded: true,
      requests: 12,
      errors: 1,
      prompt_tokens: 820_000,
      completion_tokens: 420_000,
      total_tokens: 1_240_000,
      cost_usd: 0,
      by_provider: [{ key: 'combo', total_tokens: 1_240_000, cost_usd: 0, requests: 12 }],
      by_model: [{ key: 'Full-Send', total_tokens: 1_240_000, cost_usd: 0, requests: 12 }],
      by_purpose: [{ key: 'job_analysis', total_tokens: 1_240_000, cost_usd: 0, requests: 12 }],
      top_model: 'Full-Send',
      top_purpose: 'job_analysis',
    });
  }),

  http.get('/api/v1/settings/llm-providers', () => {
    return HttpResponse.json([
      { provider: 'openai', status: 'active', model: 'gpt-4' },
      { provider: 'anthropic', status: 'active', model: 'claude-3' },
    ]);
  }),

  http.get('/api/v1/settings/llm-key', () => HttpResponse.json([])),
  http.put('/api/v1/settings/llm-key', async ({ request }) => {
    const body = (await request.json()) as { provider: string; default_model?: string };
    return HttpResponse.json({
      provider: body.provider, has_key: true, is_active: true,
      default_model: body.default_model ?? null,
    });
  }),
  http.delete('/api/v1/settings/llm-key/:provider', () => new HttpResponse(null, { status: 204 })),

  // Static assets, not API calls. The setup runs MSW with onUnhandledRequest:'error' — a
  // deliberate guard that catches a component quietly calling an endpoint nobody mocked. The
  // logo <img> would otherwise trip it on every page that renders the sidebar or auth shell,
  // so it is answered here rather than by loosening the guard for real requests too.
  http.get(/\/(logo|favicon)-\d+\.png$/, () =>
    HttpResponse.arrayBuffer(new ArrayBuffer(0), {
      headers: { 'Content-Type': 'image/png' },
    }),
  ),

  // The dashboard now renders the action queue, so every test that mounts DashboardPage
  // hits these. Without default handlers MSW's onUnhandledRequest:'error' throws
  // asynchronously *after* the test completes: the assertions still pass, but vitest records
  // an unhandled error and exits non-zero — a green suite that fails CI. Individual tests
  // still override these with server.use().
  http.get('/api/v1/command-centre/queue', () =>
    HttpResponse.json({ items: [], total: 0, by_priority: {} }),
  ),

  http.get('/api/v1/command-centre/summary', () =>
    HttpResponse.json({
      total_applications: 0, needs_attention: 0, high_priority: 0,
      by_status: {}, by_health: {}, upcoming_interviews: 0,
      pending_assessments: 0, top_actions: [],
    }),
  ),

  http.get('/api/v1/agent-runs/', () =>
    HttpResponse.json({
      items: [],
      total: 0,
      nodes: ['discovery', 'eligibility', 'scoring', 'application', 'tracking'].map((agent_name) => ({
        agent_name, status: null, last_run: null,
      })),
    }),
  ),

  http.get('/api/v1/communications/gmail/status', () =>
    HttpResponse.json({ configured: false, connected: false, authorize_url: null }),
  ),
  http.get('/api/v1/communications/apollo/status', () =>
    HttpResponse.json({ configured: false }),
  ),
  http.get('/api/v1/communications/', () =>
    HttpResponse.json({ items: [], total: 0, unmatched: 0 }),
  ),
];
