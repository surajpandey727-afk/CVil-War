# DESIGN.md — CVil-War

<!-- impeccable:design-schema 1 -->

## Direction

**Dark Neumorphism on premium Italian leather.** A forest-green ground (#0c2d1c-derived tonal
ramp) is the dominant field; Crema (#FAE7C9) is the single warm highlight, spent only on
primary actions and the numbers that matter (KPIs, ATS scores, CTAs). Every raised surface —
cards, buttons, inputs — reads as pressed leather: soft dual light/dark shadows (never a flat
drop shadow), a subtle grain + hide-mottling texture on the page canvas and primary chrome, low
contrast, restrained depth. The world is felt more than decorated — texture and shadow do the
work that borders and gradients used to.

Brief-pinned (user-specified): palette, material, era, and typeface were all named directly by
the product owner. No concept tournament was run — see the session record for that
substitution. Operate-mode surface: expression never outranks the task, state, or a familiar
affordance; a technical, dense, control-oriented reading suits this operator (see PRODUCT.md).

## Palette

Two-color story, inverted between themes rather than swapped for a different one.

**Dark (default):** forest-green ground (`--bg #081f13` → `--surface-2 #103322`), Crema accent
(`--accent #fae7c9`), brass secondary (`--secondary #c9a24a`), warm crema-tinted text
(`--text #f4ecda`) and hairline borders (`rgba(250,231,201,.07–.21)`).

**Light:** the same two colors with roles swapped — Crema ground (`--surface #fae7c9`), deep
forest ink/accent (`--accent #0e3320`), deepened brass for AA contrast on a light field.

**Status colors** (queued/review/approved/applied/interview/offer/rejected/failed) were
retuned off the old blue-brand palette into earth/leather-family hues — amber, brass-gold,
dusty sky-blue, mint, lavender, terracotta, rust — chosen so each stays distinguishable from
the Crema accent and from the green ground, not just from each other. Full values in
`src/styles/theme.css`.

## Type

**Geist Sans**, self-hosted variable font (`geist` npm package → `/public/fonts`,
`font-weight: 100 900` range) — "subtle variations" is a weight/optical choice on one file, not
a second typeface. Geist Mono for anything tabular/code-like. `--font` / `--mono` in
`theme.css`; nothing outside that file should hardcode a font-family.

## Material: the neumorphic shadow pair

```
--neu-lite: rgba(96,168,124,.07)   /* hue-tinted highlight, never white-on-color */
--neu-dark: rgba(0,0,0,.62)
--neu-out:  -7px -7px 15px var(--neu-lite), 9px 9px 20px var(--neu-dark)   /* raised */
--neu-in:   inset 4px 4px 10px var(--neu-dark), inset -3px -3px 9px var(--neu-lite) /* pressed */
```

`--shadow-1` **is** `var(--neu-out)` — every card in the app already asked for `--shadow-1`,
so the whole product went soft-UI by changing one token, not by touching every call site.
`--shadow-2` / `--shadow-pop` stay conventional cast shadows on purpose: modals, the command
palette, toasts, and dropdown menus float *above* the page, which an embossed inset/outset
pair can't sell — only re-tinted warm instead of cool black.

Use `--neu-in` / `--neu-in-sm` for anything that should read as a well (form inputs, the
active/pressed state of a toggle). Use `--neu-pressed` for a genuinely depressed/active state
(a selected filter chip, a submitting button).

Borders were kept (very faint, 7–21% opacity) alongside the shadow pair rather than removed —
pure shadow-only neumorphism has a known definition/accessibility problem where elements blend
into the ground; the hairline is what keeps edges legible at a glance without diluting the
soft-UI read.

## Material: leather

`src/styles/leather.css` — three SVG-`feTurbulence` layers composited per surface:
fine grain (pores), slow large-scale mottling (hide variation, no two patches match), and a
soft directional sheen. Two utility classes, `.leather` (content cards) and `.leather-deep`
(ambient chrome — sidebar, auth shell, the page canvas via `body::before`).

**Implementation note, load-bearing:** apply via a `::before` overlay, never the element's own
`background-image`. Almost every surface in this app sets `background: var(--surface)` inline,
and the `background` shorthand resets `background-image` to `none` as part of the shorthand —
inline styles always win that fight over an external class, however specific. The pseudo-element
sidesteps it entirely by painting in its own box. `.leather > *` gets `z-index: 1` so real
content always sits above the grain.

Applied so far: page canvas (global, every route), Sidebar, AuthShell (login/register/forgot/
reset). Individual content cards rely on the neumorphic shadow for their material read rather
than carrying their own grain layer — deliberate, both for the "restrained, not overdone"
constraint and because grain on every small control reads as dirt, not leather.

## Radii & rhythm

`--r-sm:10px --r-md:14px --r-lg:20px --r-xl:27px` — bumped up from the previous flat-design
scale; soft-UI reads as pillowy, and sharper corners undercut the embossed shadow's illusion of
a molded surface.

## What stayed untouched

Every layout, every data flow, every interaction, every route. This was a token- and
material-level pass, not a restructure — `PRODUCT.md`'s constraint that all APIs, filters,
search, sort, pagination, and application actions keep working exactly as before was verified
against the real production API (Jobs, Dashboard, Résumés spot-checked live with real data
post-deploy), not just "it compiles."

## Open / next

- Individual page cards (Jobs list rows, Application cards, Communications feed) inherit the
  neumorphic shadow via the token cascade but were not individually re-authored with their own
  leather grain or hand-tuned spacing — a `polish` pass per page would sharpen this further.
- No dedicated dark/light theme comparison screenshots were captured beyond spot checks; a
  follow-up should confirm the light theme (Crema-dominant) reads as intentionally *inverted*
  and not just "the dark theme's colors swapped and now slightly wrong."

## Process note (disclosed per skill contract)

Code-led build: no image-generation tool was available this session, so the direction was
recorded as a contract and built directly against the user's fully-pinned brief (palette,
material, type, and era were all named explicitly — no concept-seed tournament applies to an
already-decided identity). The full multi-agent finish-reviewer/documenter pipeline was
substituted with an in-thread screenshot review + this document, disclosed here rather than
silently, because the session was running unattended against a large concurrent backend
workstream in the same window and a multi-agent design review was judged lower-value than
finishing the functional P0s in the same pass. A follow-up `impeccable polish` pass with the
full pipeline is a reasonable next step if more design budget opens up.
