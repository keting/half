# HALF - Human-AI Loop Framework

A task management platform for orchestrating multi-agent collaboration. Designed for teams that use multiple AI coding agents (Claude Code, Codex, etc.) via subscriptions and need to coordinate task planning, dispatch, and tracking across agents through Git-based workflows.

## Features

- **Project Management** - Create projects, set goals, assign participating agents
- **Plan Generation** - Generate structured work plans via agent-assisted planning with DAG visualization
- **Task Dispatch** - One-click prompt copying for manual agent dispatch
- **Status Tracking** - Git polling-based task status detection with timeout and error handling
- **Agent Overview** - Monitor agent availability, subscription expiry, and reset schedules
- **Execution Summary** - Review task outcomes, manual interventions, and output files

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12 + FastAPI + SQLite |
| Frontend | React 18 + TypeScript + Vite + React Flow |
| Deployment | Docker Compose |

## Quick Start

```bash
docker compose up --build -d
```

Access the application at `http://localhost:3000`.

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HALF_ADMIN_PASSWORD` | `example-insecure-password-placeholder` | Default admin password |
| `HALF_SECRET_KEY` | (built-in) | JWT signing key |

> Change the default password and secret key before exposing to any network.

## License

MIT License. See [LICENSE](./LICENSE) for details.
