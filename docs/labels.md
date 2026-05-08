# HALF Labels

[English](./labels.md) | [简体中文](./labels.zh-CN.md)

Labels help contributors understand task type, status, difficulty, and impact
area. The GitHub repository is the source of truth. If this document differs
from the current repository labels, follow the repository and feel free to send
a docs update.

## Newcomer Friendly

- `good first issue`: Small, well-scoped tasks suitable for first-time
  contributors.
- `help wanted`: Maintainers welcome community help, but the task may not be
  suitable for a first contribution.

## Status

- `status:ready`: The goal and acceptance criteria are clear enough to claim.
- `status:needs-discussion`: Goals, scope, approach, or acceptance criteria need
  more discussion.
- `status:blocked`: Blocked by an external dependency, design decision,
  permission issue, or another task.
- `status:backlog`: Clear, but not currently scheduled.

## Type

- `type:bug`: Reproducible defects, regressions, or incorrect behavior.
- `type:feature`: Concrete new capabilities or behavior improvements.
- `type:docs`: README, Quick Start, user manuals, FAQ, screenshots, demo docs,
  or contributor docs.
- `type:test`: Test coverage, test stability, or CI work.
- `type:research`: Papers, systems, benchmarks, evaluation, or agent
  collaboration patterns.
- `type:security`: Security, permission, sensitive-information, or threat-model
  work. Do not open public Issues for serious security risks; follow the
  SECURITY policy.

## Area

- `area:frontend`: Frontend pages, components, styles, interactions, or tests.
- `area:backend`: Backend APIs, database models, services, permissions,
  polling, or tests.
- `area:docs`: Public docs, screenshots, demo docs, or contributor docs.
- `area:workflow`: Workflow templates, handoff prompts, plan DAG cases, or task
  lifecycle work.
- `area:security`: Authentication, authorization, repository access,
  sensitive-information boundaries, or security configuration.

## Priority

- `priority:high`: Impacts core flows, security boundaries, or the current
  milestone.
- `priority:medium`: Important but not blocking the current core flow.
- `priority:low`: Valuable but deferrable.

## Usage Notes

- First-time contributors should prefer `good first issue` or `type:docs`.
- When claiming engineering work, prefer `status:ready`.
- If an Issue lacks acceptance criteria, help clarify it before implementing.
- If an idea is still exploratory, use a Discussion instead of forcing it into
  `status:ready`.
