# Shared Agent Guidance

## Project identity

This repository is **HALF (Human-AI Loop Framework)**.

HALF is a **human-in-the-loop multi-agent management platform** for users who build, manage, and operate agents.
It should be treated as a real product for agent developers, not as a generic internal admin template.

The product should communicate:

- multi-agent coordination
- human-AI collaboration
- operational clarity
- technical credibility
- efficient daily use

## Important files and directories

Key references:

- `docs-internal/prd/prd_final.md` — product requirements document
- `docs-internal/design/tech_spec.md` — technical specification
- `docs-internal/design/ui-style.md` — UI style guide
- `docs/deploy/safe_deploy.md` — mandatory safe deploy rules for this server
- `src/` — application source code

## GitHub SSH preference

This repository should prefer **SSH key-based GitHub access**.

Guidance:

- When reading from or writing to GitHub remotes, prefer SSH remotes.
- Do not default to HTTPS remotes or account-login-based GitHub flows when SSH is already configured.
- Before suggesting authentication changes, inspect `git remote -v` first.
- If a remote uses HTTPS but the task assumes normal developer Git access, suggest switching to SSH rather than introducing account-based login workarounds.
- Only use or recommend non-SSH access methods when the user explicitly asks for them or when SSH is confirmed unavailable.

## How to read context efficiently

Use the smallest relevant context first.

### For UI / styling / layout / interaction tasks

Read in this order:

1. `docs-internal/design/ui-style.md`
2. relevant files in `src/`
3. `docs-internal/prd/prd_final.md` or `docs-internal/design/tech_spec.md` only if business meaning is unclear

### For business logic / workflow / field meaning

Read in this order:

1. `docs-internal/prd/prd_final.md`
2. `docs-internal/design/tech_spec.md`
3. relevant files in `src/`

### For implementation / refactor / bug-fix tasks

Read the relevant code in `src/` first, then consult docs only where needed.

### For deployment / compose / server rollout tasks

Read in this order:

1. `docs/deploy/safe_deploy.md`
2. relevant compose / Docker files in `src/`
3. runtime status on the host

Do not default to the old full rebuild path on the server when a staged deploy is safer.

Do not consume large docs unnecessarily for small local tasks.

## Design direction

Follow a **professional developer dashboard** style suitable for a multi-agent operations product.

Style keywords:

- calm
- clean
- systematic
- efficient
- modern
- trustworthy
- slightly technical
- high-signal

Reference mood:

- Linear
- Vercel
- GitHub
- Stripe Dashboard

Avoid:

- neon-heavy AI visuals
- cyberpunk styling
- glassmorphism-heavy surfaces
- excessive gradients
- oversized marketing-site patterns
- overly playful components
- generic default admin-panel aesthetics

## What to optimize

When improving UI, prioritize:

1. information hierarchy
2. page scanning speed
3. consistency of layout and spacing
4. readable forms
5. readable tables and dense lists
6. clear state indication
7. reusable shared components
8. lower visual noise

## Visual language rules

- a dark sidebar is acceptable
- the main work area should remain bright, clean, and focused
- use cards and section containers to organize information
- use restrained color
- use semantic status colors consistently
- reduce visual clutter in dense data views
- use typography and spacing to create hierarchy before using stronger colors

## Product-specific UI interpretation

Because HALF is a human-AI loop platform, the UI should feel like an **agent operations console**.

That means pages should clearly express:

- which agent is being viewed or configured
- its model and provider
- status and timing information
- what actions are available
- where human intervention or configuration matters

## Page priorities

Highest-priority pages for redesign:

1. agent list page
2. edit agent page
3. edit project page

## Page guidance

### Agent list page

Goals:

- improve row readability
- make comparison across agents fast
- surface name, model, status, expiration, and reset timing clearly
- reduce the weight of long capability text
- keep row actions compact and consistent

Recommended patterns:

- badges for status / model / provider
- chips for timing or countdown-related metadata
- truncated ability summaries
- clear separation between edit and destructive actions

### Edit Agent page

Goals:

- break long forms into grouped cards
- separate configuration concerns clearly
- keep label / help / input rhythm consistent
- use stable bottom actions for save / cancel
- improve readability of time and timezone fields

Recommended sections:

1. Basic information
2. Model and capability
3. Short reset policy
4. Long reset policy

### Edit Project page

Goals:

- improve project information density without making it cramped
- make agent assignment feel intentional
- make selected state obvious
- present agent metadata in a structured way

Recommended patterns:

- selectable agent cards or polished structured list items
- clear selected state through border, background, and indicator
- concise metadata layout for each agent option

## Constraints

Unless explicitly requested, do not:

- change backend contracts
- remove business fields
- alter business rules
- change database semantics
- rename core concepts without strong reason
- rewrite unrelated pages
- make product decisions that are not grounded in existing docs or code

## Multi-agent CLI collaboration rules

This repository may be edited by both Codex and Claude Code, possibly in the same working directory, but not at the same time.

Rules:

1. Assume another agent may have edited the repo recently.
2. Before making changes, inspect the current git diff and modified files.
3. Treat uncommitted changes as intentional unless the user explicitly asks to replace them.
4. Avoid rewriting unrelated files only for stylistic consistency.
5. Prefer focused, reviewable edits.
6. Reuse existing shared components before creating parallel ones.
7. When changing shared UI primitives, note which pages may be affected.
8. Preserve the design direction defined in `docs-internal/design/ui-style.md`.
9. Do not change backend contracts, database semantics, or business rules unless explicitly requested.
10. If the working tree already contains in-progress edits, extend them carefully instead of starting over.

## Working style

When asked to redesign or modify something:

1. inspect the relevant code first
2. identify the minimum necessary docs to read
3. read `docs-internal/design/ui-style.md` for UI tasks
4. propose a concise redesign or implementation plan
5. identify reusable components
6. implement the change
7. run a consistency pass
8. summarize touched files, what changed, and any follow-up suggestions

## Quality bar

A good result should feel like:

- an internal tool that matured into a real product
- an operations dashboard built for frequent daily use
- a multi-agent control panel with consistent visual rules
- a system designed for technical users who value clarity and efficiency

## Preferred shared components

Prefer reusing or extracting components such as:

- PageHeader
- SectionCard
- FormSection
- StatusBadge
- ModelBadge
- CountdownChip
- ActionBar
- EmptyState
- AgentSelectCard
