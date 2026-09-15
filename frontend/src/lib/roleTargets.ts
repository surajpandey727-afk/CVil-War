/** The candidate's role-target table — the source of truth for what the agent searches for.
 *
 *  `fit` is the 1–5 star assessment; `family` groups titles so a single résumé-selection rule
 *  can cover a whole group (see `Settings.resume_rules` on the automation screen).
 *  Titles marked `defaultOn` seed a new profile; after that the operator's edits are
 *  persisted in `useDiscoveryStore`.
 */

export type RoleFamily = 'product' | 'engineering' | 'architecture' | 'data';

export interface RoleTarget {
  title: string;
  fit: number;
  why: string;
  family: RoleFamily;
}

export const ROLE_FAMILIES: Record<RoleFamily, { label: string; short: string }> = {
  product: { label: 'Product management', short: 'AI PM' },
  engineering: { label: 'ML / AI engineering', short: 'ML Eng' },
  architecture: { label: 'Architecture & consulting', short: 'Architect' },
  data: { label: 'Data science & analytics', short: 'Data Sci' },
};

export const ROLE_TARGETS: RoleTarget[] = [
  { title: 'AI Product Manager', fit: 5, why: 'Your strongest match', family: 'product' },
  { title: 'Technical Product Manager', fit: 5, why: 'Architecture + engineering + product ownership', family: 'product' },
  { title: 'AI/ML Product Manager', fit: 5, why: 'Directly supported by your current work', family: 'product' },
  { title: 'Product Manager – AI/ML', fit: 5, why: 'Excellent', family: 'product' },
  { title: 'AI Product Owner', fit: 5, why: 'Strong Agile + requirements + delivery background', family: 'product' },
  { title: 'Technical Product Owner', fit: 5, why: 'APIs, architecture, engineering teams', family: 'product' },
  { title: 'ML Engineer', fit: 5, why: 'Genuine production ML experience', family: 'engineering' },
  { title: 'Machine Learning Engineer', fit: 5, why: 'Strong fit', family: 'engineering' },
  { title: 'Applied AI Engineer', fit: 5, why: 'Very strong GenAI + CV + production systems', family: 'engineering' },
  { title: 'AI Engineer', fit: 5, why: 'Strong', family: 'engineering' },
  { title: 'GenAI Engineer', fit: 5, why: 'One of your strongest technical niches', family: 'engineering' },
  { title: 'LLM Engineer', fit: 5, why: 'RAG, agents, embeddings, NL2SQL, LLM governance', family: 'engineering' },
  { title: 'AI Solutions Engineer', fit: 5, why: 'Excellent hybrid fit', family: 'engineering' },
  { title: 'AI Solutions Architect', fit: 4.5, why: 'Architecture is a major part of your CV', family: 'architecture' },
  { title: 'ML Solutions Architect', fit: 4.5, why: 'Strong cloud + ML architecture', family: 'architecture' },
  { title: 'AI Technical Consultant', fit: 4.5, why: 'Technical + client/business experience', family: 'architecture' },
  { title: 'Data & AI Consultant', fit: 4.5, why: 'Very good hybrid fit', family: 'architecture' },
  { title: 'AI Implementation Consultant', fit: 4.5, why: 'Strong', family: 'architecture' },
  { title: 'Data Product Manager', fit: 4.5, why: 'Excellent combination', family: 'product' },
  { title: 'Computer Vision Engineer', fit: 4.5, why: 'YOLO/OpenCV/multimodal production work', family: 'engineering' },
  { title: 'Forward Deployed AI Engineer', fit: 4.5, why: 'Technical + product/client-facing background', family: 'engineering' },
  { title: 'ML Platform Engineer', fit: 4, why: 'MLOps/cloud/production architecture', family: 'engineering' },
  { title: 'MLOps Engineer', fit: 4, why: 'Deployment, monitoring, pipelines, Kubernetes, CI/CD', family: 'engineering' },
  { title: 'Data Scientist', fit: 4, why: 'Your earlier DS experience + strong ML stack', family: 'data' },
  { title: 'Applied Scientist', fit: 4, why: 'Strong technical AI background, though research credentials are lighter', family: 'data' },
  { title: 'Analytics Product Manager', fit: 4, why: 'MSc Business Analytics + product', family: 'product' },
  { title: 'Data Platform Product Manager', fit: 4, why: 'Architecture/data/ML experience', family: 'product' },
  { title: 'AI Program Manager', fit: 4, why: 'Cross-functional leadership, but less direct programme-management evidence', family: 'product' },
  { title: 'ML Data Engineer', fit: 4, why: 'Good intersection of your skills', family: 'data' },
  { title: 'Decision Scientist', fit: 4, why: 'Analytics + AI + business background', family: 'data' },
  { title: 'Innovation / AI Strategy Manager', fit: 4, why: 'Strong technical/product/business crossover', family: 'architecture' },
  { title: 'Digital Product Manager', fit: 3.5, why: 'Transferable PM experience', family: 'product' },
  { title: 'Data Engineer', fit: 3.5, why: 'Strong data engineering components, but not your primary profile', family: 'data' },
  { title: 'Product Analyst', fit: 3, why: 'Overqualified technically for many roles', family: 'data' },
  { title: 'Data Analyst', fit: 3, why: 'Capable, but higher-level roles are the better target', family: 'data' },
  { title: 'Quantitative/Product Analytics', fit: 3, why: 'Possible, but not your strongest market', family: 'data' },
];

/** Titles active by default: everything at four stars or better. */
export const DEFAULT_ACTIVE_TITLES = ROLE_TARGETS.filter((r) => r.fit >= 4).map((r) => r.title);

/** "★★★★½" for a 4.5 fit. */
export function fitStars(fit: number): string {
  return '★'.repeat(Math.floor(fit)) + (fit % 1 ? '½' : '');
}

/** Best-guess family for an arbitrary job title, used to pick a résumé. */
export function familyForTitle(title: string): RoleFamily {
  const t = title.toLowerCase();
  if (/(product manager|product owner|head of product|product lead)/.test(t)) return 'product';
  if (/(machine learning|\bml\b|genai|llm|computer vision|\bai\b engineer|mlops)/.test(t)) return 'engineering';
  if (/(architect|consultant|solutions engineer|strategy)/.test(t)) return 'architecture';
  if (/(scientist|analyst|analytics|data engineer)/.test(t)) return 'data';
  return 'engineering';
}

// Keeps real headroom under the backend's 2000-char cap (JobSearchRequest.query) even as
// more role targets get added later, and keeps the query focused: platform search APIs
// treat this as one literal string, so cramming in every active title dilutes relevance
// rather than widening the match the way "OR-ing" titles would.
const MAX_QUERY_TITLES = 15;

/** The exact query string the backend search takes for a set of active titles.
 *
 * Caps at `MAX_QUERY_TITLES` — sending all active titles unbounded is what made the
 * default 31-title search 422 against the backend's length limit, which looked like
 * "job discovery is completely broken" (nothing to select or preview) with no visible
 * error on screen.
 */
export function queryForTitles(titles: string[]): string {
  return titles.slice(0, MAX_QUERY_TITLES).join(', ');
}
