import api from './api';
import type { SourceCatalogue } from '@/types/source';

/** Fetch the job-source catalogue with derived per-source health. */
export async function getSourceCatalogue(): Promise<SourceCatalogue> {
  const { data } = await api.get<SourceCatalogue>('/sources/');
  return data;
}
