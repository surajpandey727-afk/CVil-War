/** Toggle chip used across the Jobs rail (role families, salary, location, arrangement). */
export default function Chip({ on, small, title, onClick, children }: {
  on: boolean; small?: boolean; title?: string; onClick: () => void; children: React.ReactNode;
}) {
  return (
    <button
      type="button" onClick={onClick} aria-pressed={on} title={title}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 6, height: small ? 26 : 28,
        padding: `0 ${small ? 9 : 11}px`, borderRadius: 999, cursor: 'pointer',
        font: `600 ${small ? 11 : 11.5}px/1 var(--font)`,
        border: `1px solid ${on ? 'var(--accent-line)' : 'var(--border)'}`,
        background: on ? 'var(--accent-soft)' : 'var(--surface-2)',
        // Not var(--accent) — on this page's dark ground that resolves to a muted, low-
        // luminosity green whose own text-on-background contrast measured under the
        // craft floor's 4.5:1 minimum. jc-accent-2 is the same accent family at a
        // luminosity actually legible as text.
        color: on ? 'var(--jc-accent-2)' : 'var(--text-3)',
      }}
    >
      {children}
    </button>
  );
}
