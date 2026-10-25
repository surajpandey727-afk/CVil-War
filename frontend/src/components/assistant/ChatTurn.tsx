/** One turn of the assistant conversation: the text, the tools it used, and any action cards. */
import Icon from '@/components/ui/Icon';
import ConfirmCard, { type ConfirmState } from '@/components/assistant/ConfirmCard';
import RichText from '@/components/assistant/RichText';
import type { PendingAction, ToolCallSummary } from '@/types/assistant';

export interface PendingEntry extends PendingAction {
  state?: ConfirmState;
  message?: string;
}

export interface Turn {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  toolCalls?: ToolCallSummary[];
  pending?: PendingEntry[];
}

interface Props {
  turn: Turn;
  onResolve: (turnId: string, token: string, state: ConfirmState, message: string) => void;
}

export default function ChatTurn({ turn, onResolve }: Props) {
  const mine = turn.role === 'user';
  return (
    <li className="as-turn" data-role={turn.role}>
      <span className="as-who">{mine ? 'You' : 'Assistant'}</span>
      {!mine && turn.toolCalls && turn.toolCalls.length > 0 && (
        <ul className="as-tools" aria-label="Tools used">
          {turn.toolCalls.map((c, i) => (
            <li
              key={`${c.name}-${i}`}
              className="as-tool"
              data-ok={c.ok}
              title={[c.input_summary, c.result_summary].filter(Boolean).join(' → ')}
            >
              <span className="as-tool-used">used:</span> {c.name}{' '}
              <span aria-label={c.ok ? 'succeeded' : 'failed'}>
                <Icon name={c.ok ? 'check' : 'x'} size={11} sw={2.4} style={{ display: 'inline-block', verticalAlign: '-1px' }} />
              </span>
            </li>
          ))}
        </ul>
      )}
      {turn.role === 'assistant' ? (
        <div className="as-bubble" data-rich="true"><RichText text={turn.content} /></div>
      ) : (
        <div className="as-bubble">{turn.content}</div>
      )}
      {turn.pending?.map((p) => (
        <ConfirmCard
          key={p.token}
          pending={p}
          state={p.state}
          message={p.message}
          onResolved={(state, message) => onResolve(turn.id, p.token, state, message)}
        />
      ))}
    </li>
  );
}
