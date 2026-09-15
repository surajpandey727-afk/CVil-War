import Icon from '@/components/ui/Icon';
import { useResumePreviewUrl } from '@/hooks/useResumes';
import type { Resume } from '@/types/resume';

interface ResumeThumbnailProps {
  resume: Resume;
  height: number;
}

/** A scaled-down live render of the résumé's actual PDF — not a decorative mock. Falls back to
 *  a plain file glyph when there's no PDF on file yet or the fetch fails. */
export default function ResumeThumbnail({ resume, height }: ResumeThumbnailProps) {
  const { url, loading, error } = useResumePreviewUrl(resume.id, resume.has_pdf);

  if (!resume.has_pdf || error) {
    return (
      <div style={{ height, borderRadius: 'var(--r-md)', background: 'var(--surface-2)', border: '1px solid var(--border)', display: 'grid', placeItems: 'center', color: 'var(--text-4)' }}>
        <Icon name="file" size={22} />
      </div>
    );
  }

  // US Letter at 96dpi is 816px wide; scale that down to fit the thumbnail's width so the
  // rendered page (not just a viewport crop) fills the tile.
  const pageWidth = 816;
  const scale = height / (pageWidth * 1.294);

  return (
    <div style={{ height, borderRadius: 'var(--r-md)', background: '#fff', border: '1px solid var(--border)', overflow: 'hidden', position: 'relative' }}>
      {url && (
        <iframe
          src={`${url}#toolbar=0&navpanes=0&view=FitH`}
          title={`${resume.name} thumbnail`}
          tabIndex={-1}
          aria-hidden="true"
          style={{
            width: pageWidth, height: pageWidth * 1.294, border: 0,
            transform: `scale(${scale})`, transformOrigin: 'top left', pointerEvents: 'none',
          }}
        />
      )}
      {loading && (
        <div style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', background: 'var(--surface-2)' }}>
          <Icon name="file" size={22} />
        </div>
      )}
    </div>
  );
}
