# HALF — Human-AI Loop Framework

A task management console for teams orchestrating multiple AI coding agents
(Claude Code, Codex, Copilot, GLM, Kimi, etc.) across git-based workflows.

> ⚠️ **v0.x / early open source.** Interfaces and data model may change between
> minor versions. Not recommended for production multi-tenant use.

## What HALF does

- **Project-scoped agent coordination.** Bind a set of agents to a project,
  generate DAG-shaped work plans, dispatch task prompts, and track status by
  polling the project's git repo.
- **Human-in-the-loop by design.** HALF does not execute agent commands; it
  produces prompts for a human operator to paste into the agent's UI, and
  watches the repo for the resulting outputs.
- **Agent availability model.** Tracks per-agent subscription expiry, short-term
  reset windows, and long-term reset windows so that planners don't dispatch to
  an unavailable agent.

## What HALF is not

- A replacement for Jira / Linear / a generic project management tool.
- An agent runner. It coordinates prompts and outputs; it does not invoke LLMs.

## Architecture

| Layer | Tech |
|---|---|
| Backend | Python 3.12 + FastAPI + SQLAlchemy + SQLite |
| Frontend | React 18 + TypeScript + Vite + React Flow |
| Deployment | Docker Compose |
| Auth | JWT, bcrypt-hashed passwords |

Application code lives under [`src/`](./src). Design and product docs live under
[`docs/`](./docs):

- [`docs/prd.md`](./docs/prd.md) — product requirements
- [`docs/tech_spec.md`](./docs/tech_spec.md) — technical specification
- [`docs/ui-style.md`](./docs/ui-style.md) — UI / interaction principles

## Quick Start

HALF refuses to start with weak defaults. Copy the example env and fill it in
before the first `docker compose up`.

```bash
cd src
cp .env.example .env
# Edit .env and set:
# HALF_SECRET_KEY=<generated-secret>
# HALF_ADMIN_PASSWORD=<your-strong-password>
docker compose up -d
```

Open `http://localhost:3000` and log in as `admin` with the password you set.

## Local Development

Backend:

```bash
cd src/backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export HALF_SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')
export HALF_ADMIN_PASSWORD='LocalDevA1'
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Frontend:

```bash
cd src/frontend
npm install
npm run dev
```

The frontend uses relative `/api` requests. In local development, Vite proxies
`/api` to the backend; in the production Docker image, nginx proxies `/api`.

## Testing

```bash
cd src/backend && python -m pytest tests/ -v
cd src/frontend && npm test && npm run build
```

## Git Access From The Container

Out of the box, the backend container cannot reach private git repositories.
HALF does not mount host SSH keys by default. If you need private repo access,
copy `src/docker-compose.override.yml.example` to
`src/docker-compose.override.yml` and mount a dedicated deploy key.

## Production Deployment Notes

HALF is typically self-hosted on modest hardware. Practical guidance:

- Rebuild serially instead of in parallel.
- Check free memory and disk before rebuilding.
- If you only changed one service, restart just that service.
- Keep `HALF_STRICT_SECURITY=true` in production.

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

## Screenshots

Screenshots will be added in v0.2.

## License

Apache License 2.0. See [`LICENSE`](./LICENSE).
