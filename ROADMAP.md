# ROADMAP

HALF is still in `v0.x`. The project is usable, but interfaces, data model
details, and some operational behaviors may still change between minor
versions. This roadmap is intended to communicate direction and priorities, not
to guarantee exact dates or scope.

## Current Focus

The current focus is to make HALF easier for external users to understand,
trial, and contribute to:

- keep the core human-in-the-loop multi-agent workflow reliable
- improve first-run clarity and onboarding
- tighten public documentation and release discipline

## v0.2

Planned focus areas:

- improve onboarding with screenshots, demo data, and clearer setup guidance
- continue refining public-facing docs and compatibility guidance
- publish a short positioning piece explaining the human-in-the-loop design choice
- improve project/agent usability around visibility, workflows, and operator UX
- strengthen repository maintenance signals such as release notes and dependency upkeep

What v0.2 is not expected to be:

- a stable multi-tenant SaaS release
- a fully automated agent runner
- a long-term compatibility guarantee for every API shape and internal model

## v0.3

Planned focus areas:

- continue improving workflow reuse and process template ergonomics
- expand contributor-friendly entry points such as i18n and documentation tasks
- deepen design decision documentation for major permission and workflow changes
- improve trialability for self-hosted teams

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
- removing the human-in-the-loop boundary
- promising hardened multi-tenant isolation
- adding roadmap items that do not directly improve usability, reliability, or
  contributor onboarding
