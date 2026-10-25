/** Where the AI review is. It runs after the deterministic check and never gates it: while it
 *  works the report is already readable, and if it is unavailable the check still stands. */
import Icon from '@/components/ui/Icon';
import { apiErrorMessage } from '@/lib/apiError';
import type { ResumeReviewResponse } from '@/types/resumeCheck';

/** Drop one trailing full stop so a reason can be followed by our own sentence. */
const clause = (text: string): string => text.replace(/\.\s*$/, '');

export default function ReviewStatus({
  pending, error, review,
}: {
  pending: boolean;
  error: unknown;
  review: ResumeReviewResponse | undefined;
}) {
  return (
    <div className="rc-panel" role="status" aria-live="polite" aria-labelledby="rc-ai-h">
      <h2 id="rc-ai-h" className="rc-label" style={{ margin: '0 0 10px' }}>AI review</h2>
      {pending ? (
        <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
          <span className="rc-spin" aria-hidden="true" style={{ flex: '0 0 auto', marginTop: 2 }} />
          <p className="rc-hint">
            Claude is reading the résumé. This can take a minute or two. The check is ready now
            and doesn&apos;t wait for it. Notes and extra suggestions get added when it finishes.
          </p>
        </div>
      ) : error ? (
        <div className="rc-alert" data-tone="error">
          <Icon name="alert" size={15} />
          <span>AI review failed: {clause(apiErrorMessage(error, 'the request did not complete'))}. The check above still stands.</span>
        </div>
      ) : review && !review.available ? (
        <div className="rc-alert" data-tone="info">
          <Icon name="alert" size={15} />
          <span>AI review unavailable: {clause(review.detail || 'no reason given')}. The check above still stands.</span>
        </div>
      ) : review ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {review.summary ? (
            <p style={{ margin: 0, font: '500 13px/1.55 var(--font)', color: 'var(--text)' }}>{review.summary}</p>
          ) : (
            <p className="rc-hint">Review complete. Its notes are merged into the sections below.</p>
          )}
          {review.rejected_count > 0 && (
            <p className="rc-hint">
              {review.rejected_count} AI suggestion{review.rejected_count === 1 ? ' was' : 's were'} dropped
              because {review.rejected_count === 1 ? 'it' : 'they'} failed validation (for example,
              quoting text that isn&apos;t in the résumé).
            </p>
          )}
          {review.model && <span className="rc-meta">{review.model}</span>}
        </div>
      ) : (
        <p className="rc-hint">Starts automatically after each check.</p>
      )}
    </div>
  );
}
