import Icon from '@/components/ui/Icon';
import { useResumeUsage } from '@/hooks/useResumes';
import type { Resume } from '@/types/resume';

interface Props {
  resume: Resume;
  busy: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * Confirmation for removing a résumé.
 *
 * Deliberately not a generic "are you sure": what happens depends on whether this CV has been
 * sent to an employer, and the user needs to know *which* before clicking, not after. A CV
 * that went out is archived rather than deleted, because the applications that used it are
 * supposed to answer "what did they actually receive" — and the FK is ON DELETE SET NULL, so
 * a hard delete would blank that silently.
 *
 * The list of applications is fetched live rather than inferred from the card's counter, so
 * the user sees the actual roles rather than a number they have to trust.
 */
export default function DeleteResumeDialog({ resume, busy, onConfirm, onCancel }: Props) {
  const { data: usage, isLoading } = useResumeUsage(resume.id);
  const submitted = usage?.submitted ?? resume.submitted_applications;
  const willArchive = submitted > 0;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={willArchive ? 'Archive résumé' : 'Delete résumé'}
      style={{
        position: 'fixed', inset: 0, zIndex: 60, display: 'grid', placeItems: 'center',
        background: 'rgba(0,0,0,.55)', padding: 20,
      }}
    >
      <div style={{
        width: 'min(520px,100%)', maxHeight: '80vh', overflowY: 'auto',
        background: 'var(--surface)', border: '1px solid var(--border)',
        borderRadius: 'var(--r-lg)', boxShadow: 'var(--shadow-2)', padding: 20,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
          <span style={{
            width: 32, height: 32, borderRadius: 8, display: 'grid', placeItems: 'center',
            background: 'var(--surface-2)', color: willArchive ? 'var(--pending)' : 'var(--rejected)',
          }}>
            <Icon name={willArchive ? 'archive' : 'trash'} size={16} />
          </span>
          <h2 style={{ margin: 0, font: '800 16px/1.2 var(--font)' }}>
            {willArchive ? 'Archive this CV?' : 'Delete this CV?'}
          </h2>
        </div>

        <p style={{ margin: '0 0 14px', font: '500 12.5px/1.55 var(--font)', color: 'var(--text-2)' }}>
          <strong style={{ color: 'var(--text)' }}>{resume.name}</strong>
          {isLoading ? (
            <> — checking where it has been used…</>
          ) : willArchive ? (
            <>
              {' '}was sent with {submitted} application{submitted === 1 ? '' : 's'}, so it is
              kept and archived rather than deleted. Those applications need to keep showing
              what the employer actually received. It disappears from this list and from every
              CV picker.
            </>
          ) : (
            <> has never been sent to an employer, so it is deleted outright along with its
              stored PDF and DOCX. This cannot be undone.
            </>
          )}
        </p>

        {usage && usage.items.length > 0 && (
          <div style={{ marginBottom: 16 }}>
            <div style={{ font: '600 10px/1 var(--mono)', letterSpacing: '.12em', color: 'var(--text-4)', marginBottom: 8 }}>
              USED IN
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {usage.items.slice(0, 6).map((item) => (
                <div key={item.application_id} style={{
                  display: 'flex', alignItems: 'center', gap: 10, padding: '8px 10px',
                  borderRadius: 'var(--r-md)', background: 'var(--surface-2)',
                  border: '1px solid var(--border)',
                }}>
                  <div style={{ flex: '1 1 auto', minWidth: 0 }}>
                    <div style={{ font: '600 12px/1.3 var(--font)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {item.job_title || 'Untitled role'}
                      {item.company && <span style={{ color: 'var(--text-3)', fontWeight: 500 }}> · {item.company}</span>}
                    </div>
                  </div>
                  <span style={{
                    font: '700 9.5px/1 var(--mono)', letterSpacing: '.06em', textTransform: 'uppercase',
                    color: item.submitted ? 'var(--applied)' : 'var(--text-4)',
                  }}>
                    {item.submitted ? 'sent' : item.status.replace('_', ' ')}
                  </span>
                </div>
              ))}
              {usage.items.length > 6 && (
                <div style={{ font: '500 11.5px/1.4 var(--font)', color: 'var(--text-4)' }}>
                  …and {usage.items.length - 6} more.
                </div>
              )}
            </div>
          </div>
        )}

        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button
            onClick={onCancel}
            style={{
              height: 34, padding: '0 14px', borderRadius: 'var(--r-md)',
              background: 'var(--surface-2)', border: '1px solid var(--border)',
              color: 'var(--text-2)', font: '600 12.5px/1 var(--font)', cursor: 'pointer',
            }}
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={busy || isLoading}
            style={{
              height: 34, padding: '0 16px', borderRadius: 'var(--r-md)',
              background: willArchive ? 'var(--surface-2)' : 'var(--rejected)',
              border: `1px solid ${willArchive ? 'var(--border)' : 'var(--rejected)'}`,
              color: willArchive ? 'var(--text)' : '#fff',
              font: '700 12.5px/1 var(--font)', cursor: busy ? 'default' : 'pointer',
            }}
          >
            {busy ? 'Working…' : willArchive ? 'Archive it' : 'Delete permanently'}
          </button>
        </div>
      </div>
    </div>
  );
}
