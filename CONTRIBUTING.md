# Contributing To HALF

[English](./CONTRIBUTING.md) | [简体中文](./CONTRIBUTING.zh-CN.md)

HALF is in early open source (v0.x), and the current maintainer capacity is
limited. Please keep changes small, clear, and reviewable. Discuss larger ideas
in an Issue or Discussion before implementation.

## Project Stage And Principles

- HALF's APIs, data model, and product boundaries may still change.
- Prefer small changes. Do not mix unrelated refactors, formatting-only churn,
  or large translation work into feature PRs.
- Changes that touch APIs, data models, permissions, security boundaries, new
  modules, or product direction should start with a Discussion.
- Maintainers decide whether to accept Issues and PRs based on the roadmap,
  maintenance cost, security boundaries, and project scope. Opening an Issue or
  PR does not guarantee acceptance.
- Keep lab-internal materials, such as machine setup, private accounts, and
  meeting process, out of public contribution docs.

## First-Time Contributor Path

If you are new to GitHub or HALF, start with
[`docs/newcomer-path.md`](./docs/newcomer-path.md). The recommended path is:

1. Read the README, browse the screenshots, and scan [`ROADMAP.md`](./ROADMAP.md).
2. Run the Demo Project from [`docs/quickstart.md`](./docs/quickstart.md).
3. Read [`docs/project-structure.md`](./docs/project-structure.md) to learn the code layout.
4. Start with a `good first issue`, docs improvement, bug reproduction, or
   screenshot update.

## Ways To Contribute

### Share Roadmap Ideas From Papers, Systems, Or Technical Reports

If you read a paper, technical report, open source project, or industry case
related to AI Coding, Coding Agents, multi-agent collaboration, human-in-the-loop
systems, or software engineering automation, and it may inform HALF's roadmap,
start a Discussion.

Include the source link, core idea, relationship to HALF, testable hypothesis,
possible follow-up work, and risks. Once the discussion converges into concrete
work, maintainers can turn it into an Issue.

### Report Bugs Or Concrete Needs

Open an Issue for system bugs, documentation errors, UI/UX problems, concrete
features, missing tests, deployment problems, or configuration problems. Include
the background, current behavior, expected behavior, reproduction steps or goal,
impact, acceptance criteria, and relevant screenshots, logs, or links.

Do not report vulnerabilities, sensitive information leaks, permission bypasses,
or permission-model risks in public Issues. Follow [`SECURITY.md`](./SECURITY.md).

### Discuss Exploratory Ideas, Design Options, Or Research Directions

Use Discussions when an idea does not yet have clear goals, scope, and
acceptance criteria. This includes directional ideas, architecture tradeoffs,
roadmap proposals, benchmark / evaluation design, research questions, and
security or compliance boundary discussions.

### Claim Issues And Submit Pull Requests

When browsing Issues, prefer `status:ready`. First-time contributors should
start with `good first issue`. Before taking an Issue, comment that you would
like to work on it to avoid duplicate work.

Create a branch from `main`, make the change, and open a PR. Link the related
Issue or Discussion, describe the scope, explain how you verified the change,
and list any tests you did not run with a reason.

### Improve Docs, Examples, And Demos

Documentation contributions include README fixes, Quick Start updates, user
manual improvements, FAQ entries, screenshots, GIFs, demo cases, developer
notes, testing notes, and English / Chinese doc synchronization. Small typos
can go directly to PR; larger documentation restructuring should start with an
Issue or Discussion.

### Help With Testing, Reproduction, And PR Verification

You can run the Quick Start, verify the Demo Project, reproduce existing bugs,
add reproduction steps, collect screenshots or logs, confirm whether a PR fixes
an Issue, or add missing tests.

### Help With Triage, Discussions, PR Review, And Milestones

After becoming familiar with the project, you can help clarify Issues, add
acceptance criteria, guide exploratory ideas to Discussions, review whether a
PR resolves its Issue, check for out-of-scope changes, and assist with
milestones and roadmap discussions.

### Contribute Workflow Templates, Handoff Prompts, And Plan DAG Cases

HALF focuses on human-in-the-loop workflows for AI coding agents. Contributions
can include reusable workflow templates, handoff prompts, plan DAG cases, demo
collaboration cases, and notes on when those workflows are appropriate.

### Record Agent Collaboration Failure Modes And Human Intervention Points

Research contributions can include reproducible experiment notes, agent
collaboration failure modes, human intervention points, task decomposition
quality observations, and coordination-cost observations. These usually start
as Discussions and may later become docs, demos, or benchmark cases.

### Provide UI/UX Usability Feedback

Usability test notes, annotated screenshots, user journey feedback, unclear
terms, and blocked workflows are welcome. Concrete small issues can be Issues;
broader interaction direction should start in Discussions.

### Design Benchmark / Evaluation Cases

Benchmark and evaluation work can cover agent collaboration quality, task
decomposition quality, human coordination cost, evaluation scripts, and
datasets. Start with a Discussion to align on goals, scope, metrics, and risks.

### Improve Translation And Terminology

English i18n, documentation translation, and terminology cleanup are welcome.
Prefer dedicated PRs rather than mixing translation work into unrelated feature
changes.

### Discuss Security, Compliance, And Permission Boundaries

Threat-model, permission-model, repository-access, sensitive-information, and
agent-use compliance suggestions can be Discussions. Report serious security
risks privately through the SECURITY policy.

### Apply To Become A Collaborator

After sustained high-quality participation, you may tell maintainers that you
are interested in becoming a Collaborator. This is not automatic and does not
imply full repository permissions. Maintainers grant permissions gradually under
the least-privilege principle, based on contribution history, collaboration
quality, review ability, and project needs.

Collaborators may help with PR review, Issue triage, milestone management,
roadmap discussions, documentation maintenance, and onboarding new contributors.

## Issues, Discussions, Or PRs

Simple rule: use Issues for clear executable and verifiable work; use
Discussions when goals, boundaries, approach, or value need alignment first;
small typos, small docs fixes, and scoped fixes for existing Issues can go
directly to PR.

### Create An Issue

Create an Issue for:

- Reproducible bugs, regressions, or confusing errors.
- Clear documentation errors, UI/UX problems, missing tests, deployment
  problems, or configuration problems.
- Small feature improvements.
- Tasks that have converged from Discussions.
- Work with clear acceptance criteria.

### Start A Discussion

Start a Discussion for:

- Ideas from papers, systems, or technical reports.
- Roadmap proposals, architecture direction, and design tradeoffs.
- Benchmark / evaluation design.
- Security, compliance, or permission-boundary discussion.
- Ideas that cannot yet be described with acceptance criteria.

### When A Discussion Becomes An Issue

A Discussion should become an Issue only after it has converged on:

- Goal.
- Scope.
- Non-goals.
- Executable work.
- Acceptance criteria.
- Rough priority or milestone judgment.

### Pull Request Rules

| Change type | Required prior Issue / Discussion |
|---|---|
| Typo, small docs fix, small test addition | Direct PR is OK |
| Scoped fix for an existing Issue | Direct PR is OK |
| Small feature that does not change public APIs, data models, or add a new module | Direct PR is OK, but explain the motivation or link a feature request |
| Medium or large feature that changes public APIs, data models, new modules, permissions, or security boundaries | Start with a Discussion; maintainers can turn it into an Issue before PR work |
| Large refactor or unrelated formatting | Do not mix into a feature PR |

Maintainers may ask for a Discussion first, request PR splitting, or close PRs
that do not fit the roadmap.

## Issue Writing Requirements

Please use the templates and include:

- Background.
- Current behavior.
- Expected behavior.
- Reproduction steps or implementation goal.
- Impact.
- Completion or acceptance criteria.
- Screenshots, logs, links, or references.

## Discussion Writing Requirements

Discussions should include:

- Background references or links.
- Core idea.
- Relationship to HALF.
- Testable hypothesis.
- Possible follow-up work.
- Risks and non-goals.
- Questions for the community.

## Pull Request Requirements

- Keep the change small and focused.
- Link the related Issue or Discussion.
- Explain why the change is needed, what changed, and how it was verified.
- Include screenshots or recordings for UI changes.
- Update docs for API, config, data model, or deployment behavior changes.
- Run local tests and builds.
- Do not include secrets, private URLs, access tokens, or local machine paths.
- Conventional Commits style is recommended but not required.

## Development And Testing

See the local development section of [`README.md`](./README.md). For backend
tests, run `uv sync` to install dev dependencies managed by `pyproject.toml`.

```bash
cd src/backend && uv run python -m pytest tests/ -v
cd src/frontend && npm test && npm run build
```

A PR that breaks either of these will not be merged.

## Labels

Common labels are described in [`docs/labels.md`](./docs/labels.md). Core
labels include:

- `good first issue`
- `status:ready`, `status:needs-discussion`, `status:blocked`
- `type:bug`, `type:docs`, `type:research`, `type:test`
- `area:frontend`, `area:backend`, `area:docs`

## Security Issues

Do not open public Issues for vulnerabilities, sensitive information leaks,
permission bypasses, or other security risks. Follow [`SECURITY.md`](./SECURITY.md).

## Code Of Conduct

Please follow [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md). Public collaboration
in HALF should stay respectful, focused, inclusive, and actionable.

## License

By contributing, you agree that your contributions are licensed under the
Apache License, Version 2.0.

## GitHub Collaboration Workflow

For the detailed GitHub collaboration workflow, follow
[`github-collaboration-workflow.md`](https://github.com/keting/aicoding/blob/main/docs/github-collaboration-workflow.md).

For HALF-specific contribution details, use this file together with the shared
workflow. If the shared workflow and this file differ, the local repository
conventions in this file take precedence for HALF.
