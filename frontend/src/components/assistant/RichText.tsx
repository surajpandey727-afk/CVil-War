/** Renders the small Markdown subset the assistant writes — paragraphs, "- " bullets,
 *  "1." lists, **bold** and `code` — as React nodes. No HTML is ever injected, so a model
 *  reply (or text it quotes from a job posting) cannot smuggle markup into the page. */
import type { ReactNode } from 'react';

function inline(text: string, key: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    out.push(
      tok.startsWith('**')
        ? <strong key={`${key}-${i}`}>{tok.slice(2, -2)}</strong>
        : <code key={`${key}-${i}`} className="as-code">{tok.slice(1, -1)}</code>,
    );
    last = m.index + tok.length;
    i += 1;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export default function RichText({ text }: { text: string }) {
  const blocks = text.replace(/\r\n/g, '\n').split(/\n{2,}/);
  return (
    <>
      {blocks.map((block, b) => {
        const lines = block.split('\n').filter((l) => l.trim() !== '');
        const bullets = lines.length > 0 && lines.every((l) => /^\s*[-*•]\s+/.test(l));
        const numbered = lines.length > 0 && lines.every((l) => /^\s*\d+[.)]\s+/.test(l));
        if (bullets || numbered) {
          const items = lines.map((l, i) => (
            <li key={i}>{inline(l.replace(/^\s*([-*•]|\d+[.)])\s+/, ''), `${b}-${i}`)}</li>
          ));
          return numbered ? <ol key={b} className="as-list">{items}</ol> : <ul key={b} className="as-list">{items}</ul>;
        }
        return (
          <p key={b} className="as-para">
            {lines.map((l, i) => (
              <span key={i}>{i > 0 && <br />}{inline(l.replace(/^#+\s*/, ''), `${b}-${i}`)}</span>
            ))}
          </p>
        );
      })}
    </>
  );
}
