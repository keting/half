# HALF Quickstart

[English](./quickstart.md) | [简体中文](./quickstart.zh-CN.md)

This guide walks through the first run of HALF in a clean environment.

## Prerequisites

- Docker 20.10+ and Docker Compose v2+
- 2GB available memory
- Ports 3000 (frontend) and 8000 (backend) available, or custom ports configured

## Step 1: Configure The Environment

```bash
cd src
cp .env.example .env
```

Edit `.env` and set the required values:

```bash
# Generate a secure random secret:
# python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
HALF_SECRET_KEY=your-generated-secret-key

# At least 8 characters, containing uppercase, lowercase, and digits
HALF_ADMIN_PASSWORD=YourSecurePass123
```

Optional settings:

```bash
# Set to 'false' to start without the demo project
HALF_DEMO_SEED_ENABLED=true

# Allow self-registration (default: false; only enable for internal demos)
HALF_ALLOW_REGISTER=false
```

## Step 2: Start The Services

```bash
docker compose up -d --build
```

Wait for the services to become healthy, usually 10-30 seconds:

```bash
docker compose ps
```

Expected state:

- `src-backend-1`: `healthy`
- `src-frontend-1`: `running`

## Step 3: First Login

Open `http://localhost:3000` in your browser.

Credentials:

- Username: `admin`
- Password: the `HALF_ADMIN_PASSWORD` value you set in `.env`

## Step 4: Explore The Demo Project

On first startup, HALF initializes a demo project:

- **Name**: `(Demo) 修复一个bug`
- **Repository**: `https://github.com/keting/half.git`
- **State**: includes tasks in different states, such as completed, ready, and
  blocked

Open the project to inspect:

1. **Task board** - tasks grouped by status
2. **DAG view** - visual dependency graph
3. **Task queue** - executable tasks
4. **Handoff prompts** - prompts generated for agents

The demo is for browsing and learning. HALF does not execute agents
automatically.

## Step 5: Create Your First Project

1. Click "新建项目".
2. Fill in the form:
   - **Project name**: your project name
   - **Project goal**: what you want to accomplish
   - **Git repository URL**: repository URL, for example
     `https://github.com/your/repo.git`
   - **Collaboration directory**: relative output path, for example
     `projects/my-project`
   - **Polling interval**: how often HALF checks for task completion
   - **Task timeout**: task timeout in minutes
3. **Select Agents** (required):
   - select at least one agent from the list
   - pre-seeded demo agents include Claude Max, Codex Pro, and Copilot Pro
   - configure same-machine deployment settings for each agent where needed
4. Click "创建项目".

## Step 6: Generate A Plan

1. Open your project.
2. Open the Plan page and choose a flow source.
3. For the template path:
   - select a process template
   - map each template role slot to a project agent
   - fill in required inputs
   - click "下一步" to create executable tasks and open the task page
4. For the prompt path:
   - select planning agents and models where needed
   - click "生成 Prompt"
   - click "拷贝 Prompt" and paste the prompt into the planning agent UI
   - wait for the planning result to be written back to Git; when HALF detects
     a valid plan, it finalizes the plan and opens the task page automatically

Common required inputs may include:

- `docPath`: PRD or specification document path
- `test_url`: test URL, when applicable
- other template-specific inputs

HALF will:

- create a task DAG from the selected template or detected planning result
- assign tasks to selected agents
- create handoff prompts for each task

## Step 7: Dispatch And Execute Tasks

1. Open the task list tab.
2. Find a task with status "待处理" (pending).
3. Click "复制 Prompt 并派发" to copy the prompt and mark the task as dispatched.
4. Paste the copied prompt into your agent UI.
5. The agent works in the Git repository.
6. HALF polls for `result.json` to detect completion.

## Troubleshooting

### Services Fail To Start

Check logs:

```bash
docker compose logs backend
docker compose logs frontend
```

Port conflict:

If ports 3000 or 8000 are already in use, edit `docker-compose.yml`:

```yaml
frontend:
  ports:
    - "3001:80"  # change host port

backend:
  ports:
    - "8001:8000"  # change host port
```

Weak password error:

HALF refuses to start with weak defaults. Make sure:

- `HALF_SECRET_KEY` is set and sufficiently random
- `HALF_ADMIN_PASSWORD` is at least 8 characters long and contains uppercase,
  lowercase, and digits

### Login Fails

- Verify `HALF_ADMIN_PASSWORD` in `.env`.
- Check the browser console for CORS errors.
- Make sure you are using `http://localhost:3000`, not `https`.

### "At Least One Agent Must Be Selected"

When creating a project, you must:

1. Select at least one agent from the list.
2. Configure agent assignment settings where required.

### Demo Project Does Not Appear

Check whether demo seeding is enabled:

```bash
HALF_DEMO_SEED_ENABLED=true docker compose up -d
```

### Git Repository Access Fails

For private repositories, copy `src/docker-compose.override.yml.example` to
`src/docker-compose.override.yml` and mount a dedicated deploy key. Do not mount
your whole `~/.ssh` directory into the container.

Alternatively, use HTTPS with a deploy token in the repository URL.

## Next Steps

- Read [architecture.md](./architecture.md) for system design.
- Read [task-lifecycle.md](./task-lifecycle.md) for task state transitions.
- Open `http://localhost:8000/docs` for the API reference.

## Cleanup

Remove all data and start again:

```bash
docker compose down -v
```

This removes containers and volumes, including the SQLite database and cloned
repositories.
