/** Concrete rewrite suggestions, rules and AI together, grouped by résumé section.
 *
 *  The honesty rule is load-bearing: any suggestion that says something the résumé does not
 *  already evidence (a skill, a number, a tool) carries an unmissable "Add only if true" banner
 *  in plain text — not a hover-only tooltip — so it can never be read as a fact about the person.
 */
import { useEffect, useRef, useState } from 'react';

import Icon from '@/components/ui/Icon';
import { useAppStore } from '@/store/useAppStore';
import type { SectionKey, Suggestion } from '@/types/resumeCheck';
import { SECTION_LABEL, SECTION_ORDER } from './reportMeta';

const UNVERIFIED_NOTE = "The résumé doesn't show this yet — include it only if it's genuinely true.";

function CopyButton({ text }: { text: string }) {
  const notify = useAppStore((s) => s.showNotification);
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      notify('Suggestion copied to clipboard', 'success');
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setCopied(false), 2000);
    } catch {
      notify('Could not copy — select the text and copy it manually', 'error');
    }
  };

  return (
    <button type="button" className="rc-btn rc-btn-quiet" onClick={() => void copy()}>
      <Icon name={copied ? 'check' : 'file'} size={13} />
      {copied ? 'Copied' : 'Copy'}<span className="rc-sr"> suggested text</span>
    </button>
  );
}

function SuggestionItem({ s }: { s: Suggestion }) {
  const unverified = s.evidence_status === 'add_only_if_true';
  return (
    <li className="rc-sugg" data-unverified={unverified} data-testid="suggestion">
      {unverified && (
        <div className="rc-warn" role="note">
          <span style={{ color: 'var(--review)' }}><Icon name="alert" size={16} /></span>
          <span>
            <strong>Add only if true</strong>
            {UNVERIFIED_NOTE}
          </span>
        </div>
      )}
      <div className="rc-diff">
        {s.original && (
          <div>
            <span className="lbl">Now</span>
            <del>{s.original}</del>
          </div>
        )}
        <div>
          <span className="lbl">{s.kind === 'add' ? 'Consider adding' : 'Suggested'}</span>
          <ins>{s.suggested}</ins>
        </div>
      </div>
      <p className="rc-why">{s.reason}</p>
      <div className="rc-sugg-foot">
        <span className="rc-tag" data-k={s.source === 'llm' ? 'ai' : 'rules'}>{s.source === 'llm' ? 'AI' : 'Rules'}</span>
        <span className="grow" />
        <CopyButton text={s.suggested} />
      </div>
    </li>
  );
}

export default function SuggestionList({ suggestions }: { suggestions: Suggestion[] }) {
  if (!suggestions.length) {
    return <p className="rc-empty">No rewrites to suggest — nothing here the rules flagged.</p>;
  }
  const groups = new Map<SectionKey, Suggestion[]>();
  for (const s of suggestions) groups.set(s.section, [...(groups.get(s.section) ?? []), s]);

  return (
    <div>
      {SECTION_ORDER.filter((k) => groups.has(k)).map((k) => (
        <div key={k} className="rc-part">
          <h3>{SECTION_LABEL[k]}</h3>
          <ul className="rc-list" style={{ gap: 10 }}>
            {(groups.get(k) ?? []).map((s, i) => <SuggestionItem key={`${s.source}-${i}`} s={s} />)}
          </ul>
        </div>
      ))}
    </div>
  );
}
