# UX recommendations

Shipped in this pass:

* **Facts first.** Every card and the drawer open with *Employer · City, Country · Posted date
  (N days ago) · Arrangement*. Unknowns are stated, never back-filled from another field.
* **Location as one click.** UK city chips (London includes boroughs, districts and
  postcodes), "All UK", and an explicit work-arrangement row — all applied on the server, so
  counts and pages are real.
* **Say what is hidden.** "UK roles only · N outside the UK hidden · M with an unverified
  location held back" — a short list is never mistaken for an empty market.
* **Paging** past the first 100 results, resetting when the search changes.
* **Layout** that cannot be widened by its contents, collapsing on its own width.

Recommended next (not built):

1. **Quarantine review.** A small "Held back (89)" view listing ambiguous locations with one-tap
   *This is UK* / *Not UK* that writes `location_evidence_source = "operator"`. The API already
   supports `include_quarantined=true`.
2. **Batch enrichment** for the 64 UK jobs with no description, so their match scores are not
   blank until opened.
3. **Freshness.** Show "Last seen live N days ago" from `last_verified_at` and fade cards not
   seen in 21+ days — the data is now stored.
4. **Sidebar** should re-expand when the window grows back past 900 px (D-017).
5. **Posted-within filter** now meaningfully applies to newly discovered jobs; show a count of
   jobs it cannot evaluate ("no posting date: 1,014") so the 30-day default is not misread.
