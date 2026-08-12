import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { http, HttpResponse } from 'msw';

import { server } from '@/__tests__/mocks/server';
import { downloadResumeFile } from '@/services/resumeService';

describe('downloadResumeFile', () => {
  beforeEach(() => {
    // jsdom doesn't implement these blob-URL helpers.
    (URL as unknown as { createObjectURL: (b: Blob) => string }).createObjectURL = vi.fn(() => 'blob:mock');
    (URL as unknown as { revokeObjectURL: (u: string) => void }).revokeObjectURL = vi.fn();
  });
  afterEach(() => { vi.restoreAllMocks(); });

  it('fetches the file as a blob for the requested format and triggers a download', async () => {
    let requestedFormat: string | null = null;
    server.use(
      http.get('/api/v1/resumes/:id/download', ({ request }) => {
        requestedFormat = new URL(request.url).searchParams.get('format');
        return new HttpResponse(new Blob(['PDFDATA'], { type: 'application/pdf' }), {
          headers: { 'Content-Type': 'application/pdf' },
        });
      }),
    );
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

    await downloadResumeFile('resume-1', 'pdf', 'Alex Morgan — Base');

    expect(requestedFormat).toBe('pdf');
    expect(click).toHaveBeenCalledOnce();
    expect(URL.createObjectURL).toHaveBeenCalledOnce();
    expect(URL.revokeObjectURL).toHaveBeenCalledOnce();
  });
});
