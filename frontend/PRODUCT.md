# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary and currently only user: Suraj Pandey, the product's own owner/operator, using it as a personal job-search command centre for AI Product Manager / ML Engineering / MLOps roles in the UK. He is a technical, senior user — not a mainstream consumer audience — who reads dense information comfortably and wants control and evidence, not hand-holding. Not currently multi-tenant in practice, though the backend architecture supports multiple users.

*(Inferred from direct session context — the user built and operates this product himself — rather than confirmed via interview, per explicit instruction to proceed without a clarifying round.)*

## Product Purpose

CVil-War is a full-stack AI career operating system: discover job opportunities across dozens of sources (official APIs like Reed/Adzuna/Apollo, plus company career pages), score and tailor résumés against a target job, track every application through a real status lifecycle, and surface exactly what needs the operator's attention next. Success is a working, trustworthy pipeline the operator can act on quickly, not a passive job board.

## Positioning

Distinguishing mechanism: this is not a job board — it's an evidence-driven pipeline that refuses to fabricate. Résumé tailoring runs through a claim-guard that rejects any employer/institution the LLM invents and only lets through skills genuinely restated in the job's terminology. Application status is a real state machine with human-checkpoint gates (CAPTCHA/2FA, sponsorship questions), not an "applied" button that lies about what happened. A "Needs your attention" queue answers "what should I do right now" rather than leaving the operator to scan a list.

## Operating Context

- Runs as two Vercel deployments (React/Vite frontend, FastAPI Python backend) against Supabase Postgres, with an LLM gateway (OmniRoute) for tailoring/fit-analysis/cover-letter generation.
- Serverless hosting means several capabilities are explicitly degraded/unavailable in this deployment: live browser-based auto-apply, a background Redis-backed apply queue, WebSocket live-run console, and full ATS NLP scoring — all documented, not silent failures.
- The operator's daily workflow: land on Dashboard → resolve "needs attention" items → go to Jobs to discover/search/bulk-select → open a job's detail drawer to check fit → attach a résumé and queue for review → track through Applications.

## Capabilities and Constraints

- Job discovery via ~85 cataloged sources (official APIs + career-page monitors), toggled per-source in Settings; a source disabled there now also affects the default set a manual search fans out to.
- Résumé upload (PDF/DOCX, magic-byte validated), scoring against a job (multi-factor ATS breakdown), LLM-based tailoring with fabrication rejection, PDF/DOCX generation.
- Application lifecycle: queued → pending_review → approved → applying → applied/failed, plus withdrawn/rejected, each with a real timeline and evidence trail.
- Bulk-select jobs on the Jobs page to queue a batch of applications with one chosen (or auto-selected) résumé.
- Constraint: this redesign is UI/UX and frontend-architecture only. All APIs, data models, auth, routing, filters, search, sort, pagination, and application actions must keep working exactly as today — verified via the existing automated test suites (1550 backend / 280 frontend passing) plus live manual verification, not just "it compiles."
- Terminology: "résumé"/"CV" used interchangeably in-product (UI copy prefers "résumé" with the accent).

## Brand Commitments

Product name "CVil-War" (styled "CVil-War" — the CV is the point, "your CV, fighting for every role"). Existing hand-rolled CSS design system at `src/styles/theme.css` + `src/components/ui/` — no MUI, no Tailwind; this is a documented, deliberate choice from the project's own audit history (adding a second styling system was previously flagged and rejected as needless duplication).

## Evidence on Hand

Live production data only — no fixtures/mocks in this product surface. At last check: real jobs from Spotify, Adzuna, ASOS, GoCardless, OpenAI, etc.; one real résumé (`Suraj_N_Pandey_MLOps.pdf`); real applications in the pipeline (e.g. a Ginmon GmbH Product Manager role, approved at 72% fit). The redesign must render this real data, never placeholder/dummy content.

## Product Principles

1. Evidence over assertion — never let the interface imply something happened (applied, verified, matched) that the backend cannot actually back up.
2. Attention is the scarce resource — surface what needs a decision now; let everything else recede until asked for.
3. Precision reads as trust — a technical, dense, control-oriented interface suits this operator better than a friendly, simplified one.
4. Real data only — no dummy/mock/placeholder content ships in this product surface, in design work or otherwise.
5. Preserve working behavior — visual/architectural improvements never regress functionality; every change is retested end-to-end against the real API.

## Accessibility & Inclusion

No explicit standard mandated by the user; maintain or improve existing keyboard navigation, focus states, and contrast rather than regressing them for visual effect (user's own instruction: neumorphism/claymorphism must not compromise accessibility).
