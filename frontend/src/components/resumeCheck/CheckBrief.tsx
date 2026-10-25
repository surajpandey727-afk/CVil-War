/** The question the report answers: which résumé, checked against what (one job, or the
 *  Skill Radar role set). The backend owns the "exactly one target" rule, so its 422 sentence
 *  is what shows when the target is missing — the page does not maintain a second copy of it. */
import { Link } from 'react-router-dom';

import Icon from '@/components/ui/Icon';
import RolePicker from '@/components/skills/RolePicker';
import type { Resume } from '@/types/resume';
import JobPicker from './JobPicker';

export type TargetMode = 'job' | 'roles';

interface Props {
  resumes: Resume[];
  resumesLoading: boolean;
  resumesError: boolean;
  resumeId: string;
  onResume: (id: string) => void;
  mode: TargetMode;
  onMode: (m: TargetMode) => void;
  jobId: string;
  onJob: (id: string) => void;
  roles: string[];
  selectedRoles: string[];
  onToggleRole: (t: string) => void;
  onSetRoles: (titles: string[]) => void;
  onRun: () => void;
  running: boolean;
  error: string | null;
}

export default function CheckBrief(p: Props) {
  return (
    // A section, not a <form>: RolePicker's chips are untyped buttons and would submit one.
    <section className="rc-panel rc-brief" aria-label="Résumé check setup">
      <div className="rc-field">
        <label className="rc-label" htmlFor="rc-resume">Résumé</label>
        {p.resumesError ? (
          <p className="rc-hint" role="alert">Couldn&apos;t load your résumés.</p>
        ) : !p.resumesLoading && p.resumes.length === 0 ? (
          <p className="rc-hint">
            No résumés yet. <Link to="/resumes" style={{ color: 'var(--accent)' }}>Upload one on the Résumés page</Link> first.
          </p>
        ) : (
          <select id="rc-resume" className="rc-control" value={p.resumeId} onChange={(e) => p.onResume(e.target.value)} disabled={p.resumesLoading}>
            <option value="">{p.resumesLoading ? 'Loading résumés…' : 'Choose a résumé…'}</option>
            {p.resumes.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
          </select>
        )}
      </div>

      <fieldset className="rc-field">
        <legend className="rc-label" style={{ marginBottom: 7 }}>Check against</legend>
        <div className="rc-seg">
          <label>
            <input type="radio" name="rc-mode" value="job" checked={p.mode === 'job'} onChange={() => p.onMode('job')} />
            A job
          </label>
          <label>
            <input type="radio" name="rc-mode" value="roles" checked={p.mode === 'roles'} onChange={() => p.onMode('roles')} />
            Skill Radar roles
          </label>
        </div>
      </fieldset>

      <div className="rc-target-body">
        {p.mode === 'job' ? (
          <JobPicker jobId={p.jobId} onChange={p.onJob} />
        ) : (
          <RolePicker
            roles={p.roles} selected={p.selectedRoles} onToggle={p.onToggleRole}
            onSetMany={p.onSetRoles} onClear={() => p.onSetRoles([])}
          />
        )}
      </div>

      <div className="rc-actions">
        <button type="button" className="rc-btn" onClick={p.onRun} disabled={!p.resumeId || p.running}>
          <Icon name="check" size={14} /> {p.running ? 'Checking…' : 'Run check'}
        </button>
        {!p.resumeId && !p.resumesLoading && p.resumes.length > 0 && (
          <span className="rc-hint">Choose a résumé to run the check.</span>
        )}
      </div>

      {p.error && (
        <div className="rc-alert" data-tone="error" role="alert" style={{ gridColumn: '1 / -1' }}>
          <Icon name="alert" size={15} />
          <span>{p.error}</span>
        </div>
      )}
    </section>
  );
}
