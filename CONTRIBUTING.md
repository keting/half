# Contributing To HALF

[English](./CONTRIBUTING.md) | [简体中文](./CONTRIBUTING.zh-CN.md)

HALF is in early open source (v0.x), and the current maintainer is a single
developer. Keep changes small and discuss larger ideas in an issue first.

## Before You Start

1. Search existing issues and pull requests.
2. For non-trivial changes, open an issue before sending a PR.
3. Read [`docs/architecture.md`](./docs/architecture.md) and
   [`docs/task-lifecycle.md`](./docs/task-lifecycle.md) before larger refactors;
   consult [`docs/project-structure.md`](./docs/project-structure.md) to locate
   the right module.

## Issues vs. Discussions

Please choose the right entry point based on how well-scoped the topic is:

- Create an issue: <https://github.com/keting/half/issues/new/choose>
- Start a discussion: <https://github.com/keting/half/discussions/new/choose>

### Create An Issue

Create an issue when the work is clear enough to be fixed, implemented, or
verified:

- Reproducible bugs, regressions, or confusing error messages
- Security, permission, data consistency, or deployment risks
- Small, concrete feature, UI, or documentation improvements
- Missing docs, examples, screenshots, or demo materials
- Tasks already confirmed in the roadmap or a tracking issue
- Work that can be described with clear acceptance criteria

Issues should include the background, reproduction steps or target behavior,
expected result, actual result, acceptance criteria, and relevant screenshots,
logs, or links where applicable.

If the work is clear but not currently planned, it is still appropriate to
create an issue. Leave it out of milestones and make the scheduling status
explicit, for example by using a backlog, deferred, or blocked label when
available. The issue should explain why it is not scheduled yet and what would
make it worth revisiting.

### Start A Discussion

Start with a discussion when the topic is still exploratory, broad, or likely
to affect product direction:

- Large features or cross-module capabilities
- Changes that affect the data model, API, permission model, or task lifecycle
- Epics that will need multiple implementation issues
- Proposals for future roadmap commitments
- Designs that may change HALF's product positioning or boundaries
- Questions where multiple approaches need to be compared before acceptance
  criteria can be written
- Research ideas, paper / experiment directions, or long-term evolution topics

The goal of a discussion is to align on the problem, goals, non-goals, options,
and risks first. Once the direction is clear, maintainers can create a tracking
issue or split the work into implementation issues, then add a milestone if
appropriate.

Simple rule: use an issue for clear executable work; use a discussion when the
scope or approach needs alignment first.

## GitHub Collaboration Workflow

For the detailed GitHub collaboration workflow, follow
[`github-collaboration-workflow.md`](https://github.com/keting/aicoding/blob/main/docs/github-collaboration-workflow.md).

For HALF-specific contribution details, use this file together with the
shared workflow. If the shared workflow and this file differ, the local
repository conventions in this file take precedence for HALF.

## Development Setup

See the local development section of [`README.md`](./README.md).
For backend tests, run `uv sync` to install dev dependencies (managed via `pyproject.toml`).

## Running Tests

```bash
cd src/backend && uv run python -m pytest tests/ -v
cd src/frontend && npm test && npm run build
```

A PR that breaks either of these will not be merged.

## Pull Request Checklist

- [ ] Tests pass locally (`pytest` + `npm test` + `npm run build`).
- [ ] New behavior is covered by tests.
- [ ] If you changed environment variables, `src/.env.example` is updated.
- [ ] If you changed API shapes or data model, `docs/architecture.md` is updated where needed (field-level API signatures auto-update via FastAPI `/docs`).
- [ ] Commit messages describe why, not just what.
- [ ] No secrets, private URLs, or personal paths in the diff.

## UI Strings And i18n

The UI is currently mostly in Simplified Chinese. English i18n is welcome, but
prefer a dedicated i18n PR rather than mixing translation work into unrelated
feature changes.

## Code Style

- Backend: follow the style of the existing codebase
- Frontend: follow the style of the existing codebase

## License

By contributing, you agree that your contributions are licensed under the
Apache License, Version 2.0.
