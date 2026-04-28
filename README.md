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
  polling the project's Git repository.
- **Human-in-the-loop by design.** HALF does not execute agent commands. It
  produces prompts for a human operator to paste into the agent's UI, and
  watches the repository for the resulting outputs.
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

## What HALF is not

- A replacement for Jira, Linear, or a general-purpose project management
  tool.
- An agent runner. It coordinates prompts and outputs; it does not invoke
  LLMs directly.

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

**Q: Why is HALF human-in-the-loop instead of fully automated?**

A: The main reason is compliance.

HALF is designed to support multi-agent collaboration within a compliant
operating model. Many common coding agent products, especially subscription
based ones, are designed for direct use by individuals or teams through their
own interfaces, not as externally hosted services that a third-party system
can automatically invoke. For programmatic integration and automation, teams
usually need separate API products, API keys, billing models, and terms.

Because of that, HALF deliberately sets the system boundary at:

- generating prompts that a human can use directly
- letting a responsible operator manually dispatch them to agents
- tracking results through Git writes and repository polling

In other words, HALF addresses compliant human-and-agent orchestration. It is
not trying to turn subscription agents into a platform-managed runner.

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
   - Git repository URL (must be accessible from the container)
   - Collaboration directory (relative path for outputs)
   - **At least one Agent must be selected** from the pre-seeded demo agents
   - Polling intervals and timeout settings
3. **Generate a Plan** - Select a process template and provide required inputs
   (e.g., doc paths, test URLs) to generate the task DAG.
4. **Dispatch Tasks** - Start tasks from the task board; HALF generates prompts
   for you to paste into your agent's UI.

See [docs/quickstart.md](./docs/quickstart.md) for a detailed walkthrough and
troubleshooting.

## Demo Project

On first startup, HALF seeds a browsable demo project by default:

- Project: `(Demo) 修复一个bug`
- Repository: `https://github.com/keting/half.git`
- Collaboration directory: `demo/half-demo-collaboration`

The demo is for first-time exploration. It shows one completed task, two ready
tasks, and two blocked downstream tasks in a DAG workflow. HALF does not
execute agents automatically; open the demo to inspect the project board, DAG,
task queue, and handoff prompts.

Log in with username `admin` and the `HALF_ADMIN_PASSWORD` value you set in
`.env`, then open the demo project from the project list.

To run your own workflow, use a repository you can write to, such as your own
repository or a fork, then dispatch the generated prompts to your agents
manually. To start without the built-in demo project, set:

```bash
HALF_DEMO_SEED_ENABLED=false
```

## Local Development

Backend:

```bash
cd src/backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
export HALF_SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')
export HALF_ADMIN_PASSWORD='<your-strong-password>'
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

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
cd src/backend && python -m pytest tests/ -v
cd src/frontend && npm test && npm run build
```

## Git Access From The Container

Out of the box, the backend container cannot reach private Git repositories.
HALF does not mount host SSH keys by default. If you need private repository
access, copy `src/docker-compose.override.yml.example` to
`src/docker-compose.override.yml` and mount a dedicated deploy key.

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

See [`CONTRIBUTING.md`](./CONTRIBUTING.md).

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
