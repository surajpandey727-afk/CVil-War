/**
 * The sentence the server gave for a failed request, or `fallback` when it gave none.
 *
 * The api client rejects with `{ detail, status_code }` for any HTTP error. Showing that detail
 * is the difference between "Could not generate the résumé" and "The stored PDF for this
 * résumé is missing — upload it again", and only the second tells the person what to do.
 */
export function apiErrorMessage(err: unknown, fallback: string): string {
  if (typeof err === 'object' && err !== null && 'detail' in err) {
    const detail = (err as { detail?: unknown }).detail;
    if (typeof detail === 'string' && detail.trim()) return detail;
  }
  return fallback;
}
