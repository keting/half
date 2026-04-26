# HALF Quick Start Guide

This guide walks through running HALF for the first time in a clean environment.

## Prerequisites

- Docker 20.10+ and Docker Compose v2+
- 2GB available RAM
- Ports 3000 (frontend) and 8000 (backend) available, or configure custom ports

## Step 1: Configure Environment

```bash
cd src
cp .env.example .env
```

Edit `.env` and set the **required** values:

```bash
# Generate a secure random key:
# python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
HALF_SECRET_KEY=your-generated-secret-key

# Must be at least 8 characters
HALF_ADMIN_PASSWORD=YourSecurePass123
```

Optional settings:

```bash
# Set to 'false' to start without the demo project
HALF_DEMO_SEED_ENABLED=true

# Allow self-registration (default: false, only enable for internal demos)
HALF_ALLOW_REGISTER=false
```

## Step 2: Start Services

```bash
docker compose up -d --build
```

Wait for services to be healthy (usually 10-30 seconds):

```bash
docker compose ps
```

You should see:
- `src-backend-1` status: `healthy`
- `src-frontend-1` status: `running`

## Step 3: First Login

Open `http://localhost:3000` in your browser.

Login credentials:
- Username: `admin`
- Password: The `HALF_ADMIN_PASSWORD` value you set in `.env`

## Step 4: Explore the Demo Project

On first startup, HALF seeds a demo project:

- **Name**: `(Demo) 修复一个bug`
- **Repository**: `https://github.com/keting/half.git`
- **Status**: Contains 5 tasks in various states (completed, ready, blocked)

Navigate to the project to see:
1. **Task Board** - Kanban view of tasks by status
2. **DAG View** - Visual dependency graph
3. **Task Queue** - Tasks ready for execution
4. **Handoff Prompts** - Generated prompts for agents

The demo is read-only exploration. HALF does not execute agents automatically.

## Step 5: Create Your First Project

1. Click "新建项目" (New Project)
2. Fill in the form:
   - **项目名称**: Your project name
   - **项目目标**: Description of what you want to achieve
   - **Git 仓库地址**: Repository URL (e.g., `https://github.com/your/repo.git`)
   - **协作目录**: Relative path for outputs (e.g., `projects/my-project`)
   - **轮询间隔**: How often to check for task completion (seconds)
   - **任务超时**: Task timeout in minutes

3. **Select Agents** (Required)
   - At least one agent must be selected
   - Pre-seeded demo agents: Claude Max, Codex Pro, Copilot Pro
   - Configure co-location settings per agent

4. Click "创建项目"

## Step 6: Generate a Plan

1. Open your project
2. Click "生成 Plan" (Generate Plan)
3. Select a **流程模板** (Process Template)
4. Fill in required inputs:
   - `docPath`: Path to your PRD or spec document
   - `test_url`: URL for testing (if applicable)
   - Other template-specific inputs
5. Select which agents to use for plan generation
6. Click "生成 Plan"

HALF will:
- Generate a task DAG based on the template
- Assign tasks to selected agents
- Create handoff prompts for each task

## Step 7: Dispatch and Execute Tasks

1. Go to the **任务列表** (Task List) tab
2. Find tasks with status "待处理" (Pending)
3. Click "派发" (Dispatch) to generate the prompt
4. Copy the prompt and paste it into your agent's UI
5. The agent works in the Git repository
6. HALF polls for `result.json` to detect completion

## Troubleshooting

### Services fail to start

**Check logs:**
```bash
docker compose logs backend
docker compose logs frontend
```

**Port conflicts:**
If ports 3000 or 8000 are in use, edit `docker-compose.yml`:
```yaml
frontend:
  ports:
    - "3001:80"  # Change host port

backend:
  ports:
    - "8001:8000"  # Change host port
```

**Weak password error:**
HALF refuses to start with weak defaults. Ensure:
- `HALF_SECRET_KEY` is set and sufficiently random
- `HALF_ADMIN_PASSWORD` is at least 8 characters

### Login fails

- Verify `HALF_ADMIN_PASSWORD` in `.env`
- Check browser console for CORS errors
- Ensure you're using `http://localhost:3000`, not `https`

### "At least one agent must be selected" error

When creating a project, you must:
1. Select at least one agent from the list
2. Configure agent assignments with co-location settings

### Demo project not showing

Check if seeding is enabled:
```bash
HALF_DEMO_SEED_ENABLED=true docker compose up -d
```

### Git repository access fails

For private repositories, create `docker-compose.override.yml`:
```yaml
services:
  backend:
    volumes:
      - ~/.ssh/id_rsa:/root/.ssh/id_rsa:ro
```

Or use HTTPS with a deploy token in the URL.

## Next Steps

- Read [architecture.md](./architecture.md) for system design
- Read [task-lifecycle.md](./task-lifecycle.md) for task state transitions
- Review the API docs at `http://localhost:8000/docs`

## Clean Up

To remove all data and start fresh:

```bash
docker compose down -v
```

This removes containers and volumes (SQLite database, cloned repos).
