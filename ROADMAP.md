# ROADMAP

[English](./ROADMAP.md) | [简体中文](./ROADMAP.zh-CN.md)

HALF is still in `v0.x`. The project is usable, but interfaces, data model
details, and some operational behaviors may still change between minor
versions. This roadmap is intended to communicate direction and priorities, not
to guarantee exact dates or scope.

## Current Focus

The current focus is to make HALF easier for external users to understand,
trial, and contribute to:

- keep the core human-in-the-loop multi-agent workflow reliable
- improve first-run clarity and onboarding
- standardize reusable task, workflow, and handoff conventions
- tighten public documentation, design records, and release discipline

## v0.3

Planned focus areas:

- standardize task inputs and outputs as structured task cards
- evolve the existing process template model with reusable workflow presets
- define a lightweight handoff format between directly connected task nodes
- add mobile-friendly task-status notification support
- improve shared-agent catalog behavior for administrator-managed public agents
- improve first-run trialability through documentation and demo assets

Detailed v0.3 execution scope, non-goals, dependencies, and acceptance notes live
in [`docs/roadmap/v0.3.md`](docs/roadmap/v0.3.md). Research-only work is tracked
under [`docs/research/`](docs/research/), and durable architecture decisions are
tracked under [`docs/adr/`](docs/adr/).

What v0.3 is not expected to be:

- a stable multi-tenant SaaS release
- a fully automated agent runner
- a full context assembly engine
- a workflow engine with branching, loops, or dynamic routing
- a long-term compatibility guarantee for every API shape and internal model

## v0.4+ Directional Themes

The following are directional themes, not fixed commitments. Their scope and
priority will be adjusted based on v0.3 implementation results, research
feedback, enterprise pilot findings, and open-source maintenance capacity.

- **Experiment and evaluation.** Add experiment run logs, failure or experience
  cards, and better links between workflow execution and evaluation signals.
- **Skill-driven workflows.** Introduce a skill registry and bind reusable
  skills to workflow templates.
- **Externalized state.** Explore cumulative externalized state after the v0.3
  task-card and handoff formats have been validated with real usage.
- **Governance hooks.** Explore policy checks and human review points for
  controlled AI coding workflows.
- **Pilot-informed enterprise records.** Use enterprise pilot reports to decide
  whether reusable enterprise case records should become documentation,
  experiment records, or product features.
- **Compliant agent integration research.** Explore whether and how future
  versions could support automated agent invocation through explicit,
  user-configured, officially supported API-based integrations. HALF will not
  rely on private APIs, UI automation, reverse engineering, or credential
  sharing to automate subscription-based coding agents.

Requirement-to-test workflows are treated as an important workflow-template
example, not as a separate platform track.

## Stability Boundary

During `v0.x`:

- API fields may still evolve
- database and runtime behaviors may still be adjusted
- documentation and workflow conventions may continue to be refined

Users evaluating HALF should treat current releases as early open-source
versions intended for controlled self-hosted use, feedback, and iteration.

## Out Of Scope For Now

The following are not current roadmap priorities:

- positioning HALF as a generic project management replacement
- automating subscription-based coding agents through private APIs, UI
  automation, reverse engineering, or credential sharing
- promising hardened multi-tenant isolation
- adding roadmap items that do not directly improve usability, reliability, or
  contributor onboarding
