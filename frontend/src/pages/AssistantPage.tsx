/** Assistant — a chat with the platform's own Claude-backed chief of staff.
 *
 *  The assistant reads through tools as the signed-in user and shows which ones it used.
 *  Anything consequential comes back as a confirmation card; nothing changes until the user
 *  presses Confirm. History is text-only and lives in this tab's session storage. */
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { Link } from 'react-router-dom';

import Icon from '@/components/ui/Icon';
import ChatTurn, { type Turn } from '@/components/assistant/ChatTurn';
import type { ConfirmState } from '@/components/assistant/ConfirmCard';
import { useAssistantChat } from '@/hooks/useAssistant';
import { apiErrorMessage } from '@/lib/apiError';
import type { ChatMessage } from '@/types/assistant';
import '@/styles/assistant.css';

const STORAGE_KEY = 'cvw.assistant.turns.v1';
const MAX_CHARS = 8000;

const STARTERS = [
  'What needs my attention today?',
  'Show my best UK matches',
  'Check my résumé against my top match',
  'How are my agents doing?',
];

function loadTurns(): Turn[] {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? (parsed as Turn[]) : [];
  } catch {
    return [];
  }
}

function saveTurns(turns: Turn[]) {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(turns.slice(-40)));
  } catch {
    /* storage unavailable (private mode): history just isn't kept */
  }
}

let seq = 0;
const newId = () => `t${Date.now().toString(36)}${(seq++).toString(36)}`;

export default function AssistantPage() {
  const [turns, setTurns] = useState<Turn[]>(loadTurns);
  const [draft, setDraft] = useState('');
  const chat = useAssistantChat();
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => saveTurns(turns), [turns]);
  useEffect(() => {
    const el = endRef.current;
    if (el && typeof el.scrollIntoView === 'function') el.scrollIntoView({ block: 'end' });
  }, [turns.length, chat.isPending]);

  const send = (history: Turn[]) => {
    const messages: ChatMessage[] = history.map((t) => ({ role: t.role, content: t.content }));
    chat.mutate(messages, {
      onSuccess: (res) =>
        setTurns((cur) => [
          ...cur,
          { id: newId(), role: 'assistant', content: res.reply, toolCalls: res.tool_calls, pending: res.pending },
        ]),
    });
  };

  const submit = (text: string) => {
    const content = text.trim();
    if (!content || chat.isPending) return;
    const next = [...turns, { id: newId(), role: 'user' as const, content }];
    setTurns(next);
    setDraft('');
    send(next);
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    submit(draft);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit(draft);
    }
  };

  const onResolve = (turnId: string, token: string, state: ConfirmState, message: string) =>
    setTurns((cur) =>
      cur.map((t) =>
        t.id !== turnId
          ? t
          : { ...t, pending: t.pending?.map((p) => (p.token === token ? { ...p, state, message } : p)) },
      ),
    );

  const clear = () => {
    setTurns([]);
    chat.reset();
    inputRef.current?.focus();
  };

  const lastReply = [...turns].reverse().find((t) => t.role === 'assistant');
  const awaitingRetry = chat.isError && turns[turns.length - 1]?.role === 'user';

  return (
    <div className="as">
      <header className="as-head">
        <div>
          <h1>Assistant</h1>
          <p>
            Ask about your jobs, applications and résumé, or have it run your{' '}
            <Link to="/agents">AI agents</Link>. It reads freely and asks before it changes anything.
          </p>
        </div>
        {turns.length > 0 && (
          <button type="button" className="as-btn as-btn-quiet" onClick={clear}>
            <Icon name="refresh" size={13} /> New conversation
          </button>
        )}
      </header>

      <section className="as-panel" aria-label="Conversation with the assistant">
        <div className="as-sr" aria-live="polite" aria-atomic="true">
          {chat.isPending ? 'Assistant is working…' : lastReply ? `Assistant: ${lastReply.content}` : ''}
        </div>

        {turns.length === 0 ? (
          <div className="as-empty">
            <span className="as-empty-icon" aria-hidden="true"><Icon name="sparkle" size={18} /></span>
            <div>
              <p className="as-empty-title">Your job-search chief of staff</p>
              <p className="as-hint">Try one of these, or ask anything.</p>
              <div className="as-starters">
                {STARTERS.map((s) => (
                  <button key={s} type="button" className="as-starter" onClick={() => submit(s)}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          </div>
        ) : (
          <ol className="as-log" aria-label="Messages">
            {turns.map((t) => (
              <ChatTurn key={t.id} turn={t} onResolve={onResolve} />
            ))}
            {chat.isPending && (
              <li className="as-turn" data-role="assistant">
                <span className="as-who">Assistant</span>
                <div className="as-bubble as-thinking">
                  <span className="as-spin" aria-hidden="true" /> Working on it…
                </div>
              </li>
            )}
          </ol>
        )}

        {chat.isError && (
          <div className="as-alert" role="alert">
            <Icon name="alert" size={15} />
            <span className="as-alert-text">{apiErrorMessage(chat.error, 'The assistant could not answer.')}</span>
            {awaitingRetry && (
              <button type="button" className="as-btn as-btn-quiet" onClick={() => send(turns)}>
                Try again
              </button>
            )}
          </div>
        )}
        <div ref={endRef} />

        <form className="as-composer" onSubmit={onSubmit}>
          <label htmlFor="as-input" className="as-sr">Message the assistant</label>
          <textarea
            id="as-input"
            ref={inputRef}
            className="as-input"
            rows={2}
            maxLength={MAX_CHARS}
            value={draft}
            placeholder="Ask, or tell it what to do… (Enter to send, Shift+Enter for a new line)"
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
          />
          <button type="submit" className="as-btn" disabled={!draft.trim() || chat.isPending}>
            {chat.isPending ? <span className="as-spin" aria-hidden="true" /> : <Icon name="arrowU" size={14} />}
            Send
          </button>
        </form>
      </section>
    </div>
  );
}
