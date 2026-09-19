import { useEffect, useRef, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import * as resumeService from '@/services/resumeService';
import type { ResumeGenerateRequest } from '@/types/resume';

const RESUMES_KEY = ['resumes'] as const;

/** Fetch all resumes. */
export function useResumes() {
  return useQuery({
    queryKey: [...RESUMES_KEY, 'list'],
    queryFn: () => resumeService.listResumes(),
  });
}

/** Upload a resume file. */
export function useUploadResume() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => resumeService.uploadResume(file),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: RESUMES_KEY });
    },
  });
}

/** Generate a tailored resume. */
export function useGenerateResume() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: ResumeGenerateRequest) => resumeService.generateResume(request),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: RESUMES_KEY });
    },
  });
}

/** Score a resume against a job. */
export function useScoreResume() {
  return useMutation({
    mutationFn: ({ resumeId, jobId }: { resumeId: string; jobId: string }) =>
      resumeService.scoreResume(resumeId, jobId),
  });
}

/** Optimize a resume for ATS. */
export function useOptimizeResume() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (resumeId: string) => resumeService.optimizeResume(resumeId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: RESUMES_KEY });
    },
  });
}

/** Fill in the account's work history/education from a résumé already on file. */
export function useExtractProfile() {
  return useMutation({
    mutationFn: (resumeId: string) => resumeService.extractProfile(resumeId),
  });
}

/** On-demand deep AI ATS review. A mutation, not a query — it costs an LLM call, so it only
 *  runs when the operator explicitly asks, never passively on mount/focus like useScoreResume
 *  consumers such as the floating widget. */
export function useAiAtsReview() {
  return useMutation({
    mutationFn: ({ resumeId, jobId }: { resumeId: string; jobId: string }) =>
      resumeService.reviewResumeWithAI(resumeId, jobId),
  });
}

/** Fetch where one résumé has been used. Only enabled once an id is chosen. */
export function useResumeUsage(resumeId: string | null) {
  return useQuery({
    queryKey: [...RESUMES_KEY, 'usage', resumeId],
    queryFn: () => resumeService.getResumeUsage(resumeId!),
    enabled: Boolean(resumeId),
  });
}

/**
 * Object-URL for a résumé's actual PDF, for inline preview. Re-fetches when the resume changes
 * and revokes the previous URL so blobs don't leak across selections or unmounts.
 */
export function useResumePreviewUrl(resumeId: string | null, hasPdf: boolean) {
  const [url, setUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const urlRef = useRef<string | null>(null);

  useEffect(() => {
    urlRef.current = null;
    setUrl(null);
    setError(false);
    if (!resumeId || !hasPdf) return;

    let cancelled = false;
    setLoading(true);
    resumeService
      .fetchResumePreviewUrl(resumeId)
      .then((objectUrl) => {
        if (cancelled) {
          URL.revokeObjectURL(objectUrl);
          return;
        }
        urlRef.current = objectUrl;
        setUrl(objectUrl);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
      if (urlRef.current) {
        URL.revokeObjectURL(urlRef.current);
        urlRef.current = null;
      }
    };
  }, [resumeId, hasPdf]);

  return { url, loading, error };
}

/** Delete (or archive) a résumé. */
export function useDeleteResume() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (resumeId: string) => resumeService.deleteResume(resumeId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: RESUMES_KEY });
      // An archived CV stays attached to its applications, and those rows render its name
      // and archived flag — leaving them cached would show it as still live.
      void queryClient.invalidateQueries({ queryKey: ['applications'] });
    },
  });
}
