[English](./README.md) | [简体中文](./README.zh-CN.md)

[![DOI](https://zenodo.org/badge/1196783873.svg)](https://doi.org/10.5281/zenodo.19809712)
[![CI](https://github.com/keting/half/actions/workflows/ci.yml/badge.svg)](https://github.com/keting/half/actions/workflows/ci.yml)

# HALF - Human-AI Loop Framework

A task management console for teams orchestrating multiple AI coding agents
(Claude Code, Codex, Copilot, GLM, Kimi, etc.) across Git-based workflows.

> [!WARNING]
> **v0.x / early open source.** Interfaces and the data model may change
> between minor versions. Not recommended for production multi-tenant use.

## What HALF does

- **Project-scoped agent coordination.** Bind a set of agents to a project,
  generate DAG-shaped work plans, dispatch task prompts, and track status by
  polling a configured Git collaboration repository.
- **Dual dispatch modes.** Manual mode produces prompts for a human operator
  to paste into the agent's UI. Auto mode directly invokes API-capable agents
  (using a per-instance API key) when a task's dependencies are satisfied,
  enabling unattended execution for teams using API-accessible agents.
- **Agent availability model.** Track per-agent subscription expiry,
  short-term reset windows, and long-term reset windows so planners do not
  dispatch work to an unavailable agent.

## Product Preview

The built-in demo project gives first-time users a non-empty workspace for
understanding the project board, task dependencies, and agent availability.

| Plan DAG | Available agents | Agent settings |
|---|---|---|
| <img src="./docs/images/readme-plan-dag.png" alt="Demo plan DAG" width="300"> | <img src="./docs/images/readme-available-agents.png" alt="Available demo agents" width="300"> | <img src="./docs/images/readme-agent-settings.png" alt="Demo agent settings" width="220"> |

<details>
<summary>Project board screenshot</summary>

<img src="./docs/images/readme-project-board.png" alt="Demo project board" width="520">

</details>
<details>
<summary>Minimum closed-loop demonstration</summary>

<img src="./docs/images/readme-minimal-loop.gif" alt="Demo project board" width="520">

</details>


## What HALF is not

- A replacement for Jira, Linear, or a general-purpose project management
  tool.
- A general-purpose agent runner. For subscription-based agents, HALF
  coordinates prompts and tracks outputs. For API-capable agents configured
  in auto mode, HALF invokes them directly through the configured API key.

## FAQ

**Q: Why use multiple AI coding agents?**

A: Common reasons include:

- **Complementary strengths.** Different agents perform differently in
  architecture design, implementation, testing, and documentation tasks.
- **Different perspectives.** Different models and tools often make different
  judgments about the same requirement, codebase, or solution, which helps
  surface problems earlier.
- **Tooling flexibility.** Agents and underlying models evolve quickly. Using
  multiple agents is often more resilient than depending on a single tool over
  time.

**Q: When should I use manual mode vs. auto mode?**

A: The choice depends on whether your agents support API access.

**Manual mode** is designed for subscription-based agents (Claude.ai, Copilot,
Cursor, etc.) where interaction happens through a UI rather than an API. HALF
generates a handoff prompt that an operator pastes into the agent's interface.
This is the compliant path for agents whose terms are intended for direct human
use rather than automated invocation by a third-party system.

**Auto mode** is designed for agents with API access (e.g. Claude Code via an
Anthropic API key). The agent type is configured with an SDK type (`claude` is
currently supported), and each agent instance is given its own API base URL and
API key. When a task's dependencies are satisfied, HALF dispatches and runs it
without any manual step.

Both modes track outputs through the same Git collaboration repository and task
board. A project is either fully manual or fully auto; mixed-mode projects are
not supported.

**Q: What problems appear when coordinating multiple subscription-based agents?**

A: When several agents participate in one task and they cannot call each other
directly, a human operator usually has to repeat the same coordination steps.
For many subscription-based coding agents, the practical workflow is still
manual interaction through a UI instead of automatic invocation by another
system or agent.

That usually means the operator must repeatedly:

- copy prompts and send them to different agents manually
- track whether each task has finished
- decide who should receive the next prompt based on the previous result
- watch each agent's availability and reset schedule

As the number of steps and participants grows, this manual coordination easily
causes omissions, ordering mistakes, and context-switching overhead.

**Q: What problem does HALF solve?**

A: HALF focuses on workflow organization, state tracking, and execution
handoff in multi-agent collaboration:

- **Task flow organization.** Break a project into tasks with dependencies so
  work can proceed in stages.
- **Task board and handoff guidance.** Show plans, tasks, and execution state
  in one interface, and clearly indicate what should happen next and which
  agent should receive the next prompt.
- **Reusable workflow templates.** Capture common collaboration patterns to
  reduce repeated coordination overhead.
- **Agent availability management.** View agent availability and reset times in
  one place to avoid unexpected blocking during execution.
- **Unattended execution for API-capable agents.** When all project agents are
  configured in auto mode, HALF dispatches tasks automatically in DAG
  dependency order — no manual prompt-copying needed.
- **Archival and traceability.** Persist task outputs in a Git collaboration
  repository so the process and results remain reviewable.

## Architecture

| Layer | Tech |
|---|---|
| Backend | Python 3.12 + FastAPI + SQLAlchemy + SQLite |
| Frontend | React 18 + TypeScript + Vite + React Flow |
| Deployment | Docker Compose |
| Auth | JWT, bcrypt-hashed passwords |

Application code lives under [`src/`](./src). Documentation lives under
[`docs/`](./docs):

- [`ROADMAP.md`](./ROADMAP.md) - current roadmap and directional planning
- [`docs/architecture.md`](./docs/architecture.md) - system architecture, data
  model overview, API surface overview
- [`docs/task-lifecycle.md`](./docs/task-lifecycle.md) - runtime mechanism:
  state transitions, `result.json` contract, polling
- [`docs/project-structure.md`](./docs/project-structure.md) - code
  organization for contributors
- [`docs/ui-style.md`](./docs/ui-style.md) - UI and interaction principles
- [`docs/quickstart.md`](./docs/quickstart.md) - step-by-step setup guide with
  troubleshooting
- [`docs/user-manual.md`](./docs/user-manual.md) - page-oriented user manual
  (purpose, steps, and screenshots)
- `docs/roadmap/` - version-specific execution plans (coming)
- `docs/research/` - research notes for exploratory work (coming)
- `docs/adr/` - architecture decision records (coming)

The **API reference** is auto-generated by FastAPI and available at
`http://localhost:8000/docs` (Swagger UI) or `http://localhost:8000/redoc`
once the backend is running.

## Quick Start

HALF refuses to start with weak defaults. Copy the example environment file
and fill it in before the first `docker compose up`.

```bash
cd src
cp .env.example .env
# Edit .env and set:
# HALF_SECRET_KEY=<generated-secret>
# HALF_ADMIN_PASSWORD=<your-strong-password>
docker compose up -d
```

Open `http://localhost:3000` and log in as `admin` with the password you set.
The `HALF_ADMIN_PASSWORD` value must be set in `.env` before the first
deployment; HALF uses it to create the initial `admin` account.

### First Steps

After logging in:

1. **Explore the Demo Project** - A browsable demo `(Demo) 修复一个bug` is
   pre-loaded with sample tasks. Review it to understand the task board, DAG
   view, and handoff prompts.
2. **Create Your Own Project** - Click "新建项目" and configure:
   - HALF collaboration repository URL (required; repository root or clone URL)
   - Project code repository URL (optional; leave it the same as the
     collaboration repository for single-repository workflows)
   - Collaboration directory (relative path inside the collaboration repository)
   - **At least one Agent must be selected** from the pre-seeded demo agents
   - Polling intervals and timeout settings
3. **Generate a Plan** - Select a process template and provide required inputs
   (e.g., doc paths, test URLs) to generate the task DAG.
4. **Dispatch Tasks** - For manual-mode projects, start tasks from the task
   board; HALF generates prompts for you to paste into your agent's UI. For
   auto-mode projects, tasks are dispatched and executed automatically once
   their dependencies are satisfied — no manual step required.

See [docs/quickstart.md](./docs/quickstart.md) for a detailed walkthrough and
troubleshooting.

## Demo Project

On first startup, HALF seeds a browsable demo project by default:

- Project: `(Demo) 修复一个bug`
- HALF collaboration repository: `https://github.com/keting/half.git`
- Collaboration directory: `demo/half-demo-collaboration`

The demo is for first-time exploration. It shows one completed task, two ready
tasks, and two blocked downstream tasks in a DAG workflow. HALF does not
execute agents automatically; open the demo to inspect the project board, DAG,
task queue, and handoff prompts.

Log in with username `admin` and the `HALF_ADMIN_PASSWORD` value you set in
`.env`, then open the demo project from the project list.

To run your own workflow, use a collaboration repository you can write to, such
as your own repository or a fork, then dispatch the generated prompts to your
agents manually. If your code lives in a separate repository, configure it as
the project code repository during project creation. To start without the
built-in demo project, set:

```bash
HALF_DEMO_SEED_ENABLED=false
```

## Local Development

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) before running the backend locally:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Backend:

```bash
cd src/backend
export HALF_SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')
export HALF_ADMIN_PASSWORD='<your-strong-password>'
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

> `uv` reads `pyproject.toml` and automatically creates a virtual environment
> on first run. To install dev dependencies explicitly:
>
> ```bash
> uv sync
> ```

Frontend:

```bash
cd src/frontend
npm install
npm run dev
```

The frontend uses relative `/api` requests. In local development, Vite proxies
`/api` to the backend. In the production Docker image, nginx proxies `/api`.

## Testing

```bash
cd src/backend && uv run pytest tests/ -v
cd src/frontend && npm test && npm run build
```

## Git Access From The Container

Out of the box, the backend container cannot use credentials from your host
machine. Being able to clone a repository on the host does not mean the backend
container can clone it.

Use HTTPS URLs for public GitHub repositories when you only need anonymous
read-only access, for example `https://github.com/org/repo.git`. SSH URLs such
as `git@github.com:org/repo.git` always require an SSH authentication setup in
the backend runtime, even when the repository is public. Private repositories
require credentials with repository access whether you use SSH or HTTPS.

For Docker deployments that need SSH access, copy
`src/docker-compose.override.yml.example` to `src/docker-compose.override.yml`
and mount only a dedicated deploy key plus `known_hosts` into the backend
container. Do not mount your whole `~/.ssh` directory. A typical setup is:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/half_deploy_key -C half-backend
ssh-keyscan github.com >> ~/.ssh/known_hosts
```

Add `~/.ssh/half_deploy_key.pub` to the target repository as a deploy key, then
uncomment and adjust the key and `known_hosts` volume lines in
`src/docker-compose.override.yml`. For private HTTPS access, use a credential
helper or another container-side Git credential setup to provide a token; do
not put access tokens or passwords in the repository URL.

Project creation and editing require a HALF collaboration repository URL. This
is the repository HALF clones and polls for plans, task outputs, `result.json`,
and optional usage records. A separate project code repository URL can also be
provided; when omitted, HALF treats the project code repository as the same
repository as the collaboration repository. HALF passes the project code
repository to generated prompts, but does not clone or verify it during polling.

Both repository fields accept repository roots and clone URLs such as
`https://github.com/org/repo`, `https://github.com/org/repo.git`,
`ssh://git@github.com/org/repo.git`, and `git@github.com:org/repo.git`. On
GitHub, Gitee, Bitbucket, and Codeberg, root URLs must be exactly
`owner/repo`; GitLab subgroup root URLs such as
`https://gitlab.com/group/subgroup/repo` are also accepted. Save-time validation
checks URL shape and safety only; it does not prove that the repository exists
or that the container or agents have access. Do not enter issues, pull request,
tree, blob, graphs, or other repository-internal page URLs, and do not embed
credentials, access tokens, or deploy tokens in the URL's userinfo, query, or
fragment.

## Production Deployment Notes

HALF is typically self-hosted. For production deployments, keep
`HALF_STRICT_SECURITY=true` and review [`SECURITY.md`](./SECURITY.md) before
exposing the service.

## Configuration

See [`src/.env.example`](./src/.env.example) for the full set of environment
variables and defaults.

## Language

The current UI is primarily in Simplified Chinese. English i18n contributions
are welcome.

## Security

See [`SECURITY.md`](./SECURITY.md) for the trust model, threat model, and how
to report vulnerabilities.

## Contributing

HALF welcomes many kinds of contributions, not only code:

- Read AI Coding / Coding Agent papers, systems, or technical reports and
  share roadmap ideas in Discussions.
- Report bugs, documentation errors, or concrete needs by opening Issues.
- Use Discussions for exploratory ideas, design tradeoffs, benchmarks, and
  compliance or security-boundary questions.
- Claim `status:ready` or `good first issue` Issues and submit Pull Requests.
- Improve the README, Quick Start, user manuals, FAQ, screenshots, demos, and
  tests.
- Contribute workflow templates, handoff prompts, plan DAG cases, or records of
  agent collaboration failure modes.
- After becoming familiar with the project, help with Issue triage, PR review,
  milestones, and roadmap discussions.

First-time contributors can start with this path:

1. Read the README, browse the screenshots, and scan the roadmap.
2. Run the Demo Project from the Quick Start.
3. Start with a `good first issue` or a documentation improvement.
4. For medium or large changes that touch APIs, data models, or new modules,
   start a Discussion before implementation.

See [`CONTRIBUTING.md`](./CONTRIBUTING.md) and
[`docs/newcomer-path.md`](./docs/newcomer-path.md) for the full guide.

Do **not** open public Issues for vulnerabilities, sensitive information leaks,
permission bypasses, or permission-model risks. Follow
[`SECURITY.md`](./SECURITY.md) instead. Community expectations are described in
[`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md).

## Citation

If you use HALF in your research, teaching, or software engineering
experiments, please cite the archived Zenodo project record:

Keting. (2026). HALF: Human-AI Loop Framework. Zenodo.
https://doi.org/10.5281/zenodo.19809712

The citation metadata is also available in [`CITATION.cff`](./CITATION.cff).

DOI maintenance note: HALF uses the Zenodo Concept DOI for repository-level
citation and metadata. Version-specific DOIs are managed by Zenodo and are not
written back into the repository for every release. For exact reproducibility,
use the version-specific DOI shown on the corresponding Zenodo record.

## License

Apache License 2.0. See [`LICENSE`](./LICENSE).
