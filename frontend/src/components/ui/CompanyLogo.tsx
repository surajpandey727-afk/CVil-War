import { useMemo, useState } from 'react';

import { domainForCompany, initials } from '@/lib/companyLogo';


/**
 * Company / source logo with an initials fallback.
 *
 * Three things matter here and each one is a bug that was hit without it:
 *
 * 1. **The monogram is always rendered, underneath the image.** A failed logo therefore
 *    degrades to initials with no layout shift and no broken-image glyph.
 * 2. **Failures are cached in sessionStorage.** Without it, a table of 30 rows re-requests
 *    the same dead logo on every re-render and every route change.
 * 3. **No `onError` attribute on a server-rendered string.** The handler is bound in React,
 *    never as an inline attribute.
 *
 * Set `VITE_LOGO_BASE` to point at a self-hosted logo cache; it receives `?domain=&sz=`.
 * The default is the public favicon service, which needs no key.
 */

const LOGO_BASE = (import.meta.env['VITE_LOGO_BASE'] as string | undefined)
  ?? 'https://www.google.com/s2/favicons';

const FAILED_KEY = 'cvil-war-logo-failures';

function failedSet(): Set<string> {
  try {
    return new Set(JSON.parse(sessionStorage.getItem(FAILED_KEY) ?? '[]') as string[]);
  } catch {
    return new Set();
  }
}

function rememberFailure(domain: string): void {
  try {
    const set = failedSet();
    set.add(domain);
    sessionStorage.setItem(FAILED_KEY, JSON.stringify([...set]));
  } catch {
    /* storage disabled — the monogram still shows, so this is not worth surfacing */
  }
}

interface Props {
  /** Company or source name — used for the monogram and, if no domain is given, the guess. */
  name: string;
  /** Explicit domain. Preferred: pass `SOURCE_BY_KEY[key].domain` where you have it. */
  domain?: string;
  size?: number;
  radius?: number;
}

export default function CompanyLogo({ name, domain, size = 44, radius = 10 }: Props) {
  const resolved = domain || domainForCompany(name);
  const [broken, setBroken] = useState(() => !resolved || failedSet().has(resolved));
  const src = useMemo(
    () => (resolved ? `${LOGO_BASE}?domain=${encodeURIComponent(resolved)}&sz=64` : ''),
    [resolved],
  );

  return (
    <div
      aria-hidden
      style={{
        position: 'relative',
        flex: '0 0 auto',
        width: size,
        height: size,
        borderRadius: radius,
        background: 'var(--surface-2)',
        border: '1px solid var(--border)',
        display: 'grid',
        placeItems: 'center',
        overflow: 'hidden',
      }}
    >
      <span style={{ font: `700 ${Math.round(size / 3.1)}px/1 var(--font)`, color: 'var(--text-3)' }}>
        {initials(name)}
      </span>
      {!broken && (
        <img
          src={src}
          alt=""
          loading="lazy"
          onError={() => {
            rememberFailure(resolved);
            setBroken(true);
          }}
          style={{
            position: 'absolute',
            inset: 0,
            width: '100%',
            height: '100%',
            objectFit: 'contain',
            padding: Math.round(size * 0.16),
          }}
        />
      )}
    </div>
  );
}
