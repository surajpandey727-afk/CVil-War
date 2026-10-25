/** A proposed consequential action, waiting for the user's explicit Confirm.
 *
 *  Nothing has happened while this card is open: the backend only acts when the signed token
 *  comes back through /assistant/confirm. Cancel just closes the card; the token expires on
 *  its own after ten minutes. */
import { useState } from 'react';

import Icon from '@/components/ui/Icon';
import { useConfirmAction } from '@/hooks/useAssistant';
import { apiErrorMessage } from '@/lib/apiError';
import type { ConfirmResponse, PendingAction } from '@/types/assistant';

export type ConfirmState = 'open' | 'done' | 'failed' | 'cancelled';

interface Props {
  pending: PendingAction;
  /** Persisted outcome (the chat keeps it in session storage across reloads). */
  state?: ConfirmState;
  message?: string;
  onResolved?: (state: ConfirmState, message: string) => void;
}

export default function ConfirmCard({ pending, state = 'open', message, onResolved }: Props) {
  const confirm = useConfirmAction();
  const [local, setLocal] = useState<{ state: ConfirmState; message: string } | null>(null);
  const current = local ?? { state, message: message ?? '' };

  const settle = (s: ConfirmState, m: string) => {
    setLocal({ state: s, message: m });
    onResolved?.(s, m);
  };

  const onConfirm = () => {
    confirm.mutate(pending.token, {
      onSuccess: (res: ConfirmResponse) => settle(res.ok ? 'done' : 'failed', res.message),
      onError: (err) => settle('failed', apiErrorMessage(err, 'Could not run that action.')),
    });
  };

  const open = current.state === 'open';
  return (
    <div className="as-confirm" data-state={current.state} role="group" aria-label="Action awaiting confirmation">
      <div className="as-confirm-head">
        <span aria-hidden="true"><Icon name={open ? 'shield' : current.state === 'done' ? 'check' : 'x'} size={15} /></span>
        <span className="as-confirm-kicker">
          {open ? 'Needs your confirmation' : current.state === 'done' ? 'Done' : current.state === 'cancelled' ? 'Cancelled' : 'Not done'}
        </span>
      </div>
      <p className="as-confirm-summary">{pending.summary}</p>
      {open ? (
        <div className="as-confirm-actions">
          <button type="button" className="as-btn" onClick={onConfirm} disabled={confirm.isPending}>
            {confirm.isPending ? <span className="as-spin" aria-hidden="true" /> : <Icon name="check" size={14} />}
            {confirm.isPending ? 'Working…' : 'Confirm'}
          </button>
          <button
            type="button"
            className="as-btn as-btn-quiet"
            onClick={() => settle('cancelled', 'Nothing was changed.')}
            disabled={confirm.isPending}
          >
            Cancel
          </button>
        </div>
      ) : (
        current.message && <p className="as-confirm-result" role="status">{current.message}</p>
      )}
    </div>
  );
}
