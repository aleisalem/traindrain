# Frontend design refresh

Applied a bolder, more interactive visual language to the existing Release 0 UI (no
functional or routing changes): pill-shaped buttons and inputs, gradient primary actions,
a `Space Grotesk` / `Manrope` type pairing, elevated cards with a soft shadow token, and a
sticky/blurred admin nav with hover-lift micro-interactions.

## What changed

- `src/frontend/src/styles/themes.css`: new palette per theme (light/dark/colorblind),
  plus two new tokens — `--bg-elevated` (card/input surfaces, distinct from the page
  background) and `--shadow` (theme-tuned elevation). `--accent` now doubles as the second
  stop of `--gradient`, the shared primary-action gradient.
- `src/frontend/src/index.css`: maps `--bg-elevated` into Tailwind, sets the `Manrope`
  body / `Space Grotesk` heading font pairing.
- `index.html`: loads the two Google Fonts.
- Every page under `src/frontend/src/features/**` and `Dashboard.tsx`: buttons, inputs,
  and card containers restyled to the new tokens (no markup/behavior changes). Confirmed
  via `npx tsc -b` and the full Vitest suite (74/74 passing) after updating one test
  selector (`AdminGroupsPage.test.tsx`) that matched the old `rounded-lg` card class.
- `AdminShell.tsx` / `Dashboard.tsx`: added a small gradient logo mark, switched the admin
  nav to `NavLink` with an active-state underline, and made the admin header sticky with a
  backdrop blur.

## Why

Direct design feedback: the Release 0 visual language (flat borders, no motion, `rounded-md`
everywhere) read as dry for a platform meant to make e-learning "fun, not boring" per
`AGENTS.md`. The new direction draws on modern SaaS/agency product sites (bold gradient
accents, pill controls, subtle hover motion) while keeping the existing component
structure, all three required themes, and full accessibility (reduced-motion is not yet
special-cased here since the only motion added is a CSS `transition` on hover, not a
looping animation).

## Not done here

- No new shared component library was introduced — each page still owns its Tailwind
  classes, matching the existing Release 0 convention.
- Learning-module screens (list/editor/import/assign) are still only a design-canvas
  mockup under `.scratch/release-1-learning-modules/design/`, not implemented code.
