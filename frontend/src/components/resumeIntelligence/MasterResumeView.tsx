import { useState } from 'react';

import Icon from '@/components/ui/Icon';
import ChangeLogTimeline from '@/components/resumeIntelligence/ChangeLogTimeline';
import DiffView from '@/components/resumeIntelligence/DiffView';
import ResumeContentView from '@/components/resumeIntelligence/ResumeContentView';
import { useMaster, useMasterVersions, useUpdateMaster } from '@/hooks/useResumeIntelligence';
import { useAppStore } from '@/store/useAppStore';

const card: React.CSSProperties = {
  background: 'var(--surface)', border: '1px solid var(--border)',
  borderRadius: 'var(--r-lg)', boxShadow: 'var(--shadow-1)',
};

export default function MasterResumeView({ onBack }: { onBack: () => void }) {
  const notify = useAppStore((s) => s.showNotification);
  const { data: master, isLoading } = useMaster();
  const { data: versions } = useMasterVersions();
  const updateMaster = useUpdateMaster();
  const [compare, setCompare] = useState<{ from: string; to: string } | null>(null);

  return (
    <div style={{ animation: 'aaUp .4s var(--ease) both', maxWidth: 900 }}>
      <button onClick={onBack} style={{ display: 'inline-flex', alignItems: 'center', gap: 7, height: 30, padding: '0 10px 0 8px', marginBottom: 16, borderRadius: 'var(--r-md)', background: 'transparent', border: 0, color: 'var(--text-3)', font: '600 12.5px/1 var(--font)', cursor: 'pointer' }}>
        <Icon name="chevL" size={15} /> Resume Intelligence
      </button>

      <div style={{ marginBottom: 18 }}>
        <h1 style={{ margin: 0, font: '800 22px/1.2 var(--font)', letterSpacing: '-.02em' }}>Master résumé</h1>
        <p style={{ margin: '6px 0 0', font: '500 13px/1.4 var(--font)', color: 'var(--text-3)' }}>
          The canonical, factual source every role branch derives from. Edits here create a new version — nothing is ever silently rewritten.
        </p>
      </div>

      {isLoading || !master ? (
        <div style={{ ...card, height: 200, background: 'linear-gradient(90deg,var(--surface-2),var(--hover),var(--surface-2))', backgroundSize: '200% 100%', animation: 'aaShimmer 1.3s linear infinite' }} />
      ) : (
        <ResumeContentView
          content={master.content}
          editable
          saving={updateMaster.isPending}
          onSave={(content) =>
            updateMaster.mutate(
              { content, commitMessage: 'Edited master résumé' },
              {
                onSuccess: (v) => notify(`Saved as ${v.version_label}`, 'success'),
                onError: () => notify('Could not save changes', 'error'),
              },
            )
          }
        />
      )}

      <div style={{ marginTop: 28, marginBottom: 12, font: '700 14px/1 var(--font)' }}>Version history</div>
      {compare ? (
        <>
          <button onClick={() => setCompare(null)} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, height: 28, padding: '0 10px', marginBottom: 10, borderRadius: 'var(--r-md)', background: 'var(--surface-2)', border: '1px solid var(--border)', color: 'var(--text-3)', font: '600 11.5px/1 var(--font)', cursor: 'pointer' }}>
            <Icon name="chevL" size={12} /> Back to history
          </button>
          <DiffView fromId={compare.from} toId={compare.to} />
        </>
      ) : (
        <ChangeLogTimeline versions={versions ?? []} onCompare={(from, to) => setCompare({ from, to })} />
      )}
    </div>
  );
}
