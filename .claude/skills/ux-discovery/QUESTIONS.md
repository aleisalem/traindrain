# UX Discovery Question Bank

Ask one at a time, in this order, skipping any topic already settled by the codebase or AGENTS.md. Give a recommended answer for each based on what you already know about the app and its users.

## 1. Who and why

- Which role(s) will use this screen/flow (Administrator, Content Manager, Learner, or a mix)? Look up the actual role names/permissions from the codebase rather than asking if they're findable.
- What's the single task this screen exists to let them finish? What does success look like at the end of it?
- How often will they do this — a rare admin setup task, or something learners hit every session? (Drives how much the design should optimize for speed vs. discoverability.)

## 2. Entry and flow

- Where does the user arrive from, and where do they go next? Sketch the flow as a numbered sequence of steps/screens.
- Is this a single screen, a multi-step wizard, or a persistent panel/dashboard?
- What's the primary action (the one button that matters most), and what are the secondary/destructive actions?

## 3. Content and density

- How much information is on screen at once — a focused single-purpose form, or a dense dashboard/table?
- Does this need progressive disclosure (advanced options collapsed, details-on-demand)?
- Any real-time/live-updating data (progress, chat, notifications)?

## 4. States

- What does the empty state look like (no data yet)?
- What does loading look like?
- What does error look like — validation errors vs. system failures?
- What does a permission-denied view look like, given implicit-deny (AGENTS.md security §2)? A user should never see a broken page — only a clear "you don't have access" message or the feature absent entirely.

## 5. Interaction specifics

- Any drag-and-drop, inline editing, bulk actions, multi-select?
- Keyboard navigation expectations beyond baseline accessibility?
- Confirmation patterns for destructive actions (modal, undo-toast, type-to-confirm)?

## 6. Look and feel (only what AGENTS.md leaves open)

AGENTS.md already mandates EN/DE translations, light/dark/colorblind-friendly themes, and an "interactive, modern, responsive" feel — don't re-ask these, just make sure the design doesn't contradict them.

- What tone should this specific screen strike within that (e.g. celebratory on quiz completion vs. neutral on an admin CRUD table)?
- Any specific inspiration/reference screens (inside or outside the app) the user wants to riff on or explicitly avoid?

## 7. Responsive/device targets

- Desktop-first with graceful mobile, or does this need to work well on mobile as a primary use case (e.g. learners doing training on a phone)?
- Any breakpoints already established elsewhere in the app to stay consistent with?

## Brief template

Once the interview and artifact are done, capture:

```markdown
## UX Brief: <screen/flow name>

**Roles:** ...
**Task & success state:** ...
**Flow:** 1. ... 2. ... 3. ...
**States covered:** empty / loading / error / permission-denied / success
**Look & feel notes:** ...
**Accessibility/interaction notes:** ...
**Artifact:** <link to prototype URL or design canvas>
**Open questions:** ...
```
