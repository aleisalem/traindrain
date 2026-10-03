---
name: ux-discovery
description: Interview the user about a screen or flow's UI/UX requirements, then hand off to the `design` or `prototype` skill to produce the actual wireframe/mockup. Use when the user wants to design a new screen, rework a flow, or figure out "what should this look like" before a spec exists.
---

# UX Discovery

A specialized interview for UI/UX decisions, followed by a handoff to whichever artifact-producing skill fits the answer. This skill does not draw anything itself — it earns the right questions to ask `design` or `prototype` to draw.

## When to use this vs `grilling`

- Plain `grilling` interrogates a plan or backend design.
- `ux-discovery` interrogates a *screen or flow* — the topics are visual/interaction specific (see [QUESTIONS.md](QUESTIONS.md)), and it always ends by producing a concrete artifact instead of just shared understanding.

Use `ux-discovery` when the destination is a screen, flow, or component's look-and-feel; use `grilling` for everything else. A `wayfinder` "Prototype" ticket whose question is "how should this look?" is exactly the case this skill is for.

## Process

1. **Interview, one question at a time.** Work through [QUESTIONS.md](QUESTIONS.md) topic by topic — skip a topic outright if the codebase or AGENTS.md already settles it (e.g. don't ask about language support or theme options; AGENTS.md already mandates EN/DE and light/dark/colorblind-friendly themes). For every question, give a recommended answer and wait for the user's response before moving to the next. Look up facts (existing components, existing pages, role names) yourself rather than asking.

2. **Pick the artifact.** Once the shape of the screen/flow is clear, decide which existing skill produces it — ask the user if genuinely ambiguous:
   - **`/prototype` (UI.md branch)** — when the question is "which of these structurally different layouts feels right," and there's a real page to bolt variants onto. Produces switchable in-app variants.
   - **`design`** (the built-in design-canvas skill) — when the goal is a presentable set of mockups/wireframes/screen flow to react to or share, independent of live app code, or before a page exists at all.

   Don't build both for the same question — pick the one whose output the user will actually act on.

3. **Invoke that skill** with the interview's answers as its brief — persona, flow, look-and-feel decisions, states needed, accessibility notes. Let that skill do the actual design work; don't duplicate its process here.

4. **Write the UX brief.** Once the artifact exists, capture the interview's decisions using the [brief template](QUESTIONS.md#brief-template), in the conversation or a `NOTES.md` beside the artifact if the user isn't around to read it live. This is what feeds `to-spec`'s "Implementation Decisions" and "Testing Decisions" for the feature — link the artifact rather than re-describing it.

## Rules

- Never guess at look-and-feel decisions the user hasn't given — if a recommended answer is rejected, ask a follow-up rather than picking a different guess yourself.
- Don't skip straight to building the artifact without the interview — a mockup built on unstated assumptions wastes the same day-of-picking-between-vague-options that `/prototype` exists to avoid.
- Don't re-litigate what AGENTS.md already mandates (EN/DE, three themes, role-based implicit deny) — treat those as constraints the interview must respect, not open questions.
- If the interview surfaces that this is bigger than one screen (a whole new section of the app, multiple flows), stop and suggest `wayfinder` instead — `ux-discovery` is sized for one screen or flow per run.
