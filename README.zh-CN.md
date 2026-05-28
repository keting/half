[English](./README.md) | [简体中文](./README.zh-CN.md)

[![DOI](https://zenodo.org/badge/1196783873.svg)](https://doi.org/10.5281/zenodo.19809712)
[![CI](https://github.com/keting/half/actions/workflows/ci.yml/badge.svg)](https://github.com/keting/half/actions/workflows/ci.yml)

# HALF - Human-AI Loop Framework

一个面向团队的任务管理控制台，用于在基于 Git 的工作流中编排多个 AI
coding agent（Claude Code、Codex、Copilot、GLM、Kimi 等）的协作。

> [!WARNING]
> **v0.x / 早期开源版本。** 接口和数据模型可能会在次版本间发生变化，暂不建议用于生产级多租户场景。

## HALF 是什么

- **面向项目的 agent 协调。** 将一组 agent 绑定到项目，生成 DAG 形式的工
  作计划，分发任务 prompt，并通过轮询配置的 Git 协作仓库跟踪状态。
- **双模式派发。** 手动模式为操作人生成可粘贴到 agent UI 的 prompt；自动
  模式在任务依赖满足时通过 API 直接调用 agent（使用每个实例独立配置的
  API Key），实现无人值守的连续执行——适用于支持 API 调用的 agent 团队。
- **agent 可用性模型。** 跟踪每个 agent 的订阅到期时间、短周期重置窗口和
  长周期重置窗口，避免规划器把任务派发给当前不可用的 agent。

## 产品预览

内置 Demo 项目会为首次使用者提供一个非空工作区，用于理解项目看板、任务
依赖关系和 agent 可用性。

| Plan DAG | 可用 agents | Agent 设置 |
|---|---|---|
| <img src="./docs/images/readme-plan-dag.png" alt="Demo Plan DAG" width="300"> | <img src="./docs/images/readme-available-agents.png" alt="可用 Demo agents" width="300"> | <img src="./docs/images/readme-agent-settings.png" alt="Demo agent 设置" width="220"> |

<details>
<summary>项目看板截图</summary>

<img src="./docs/images/readme-project-board.png" alt="Demo 项目看板" width="520">

</details>

<details>
<summary>最小闭环演示</summary>

<img src="./docs/images/readme-minimal-loop.gif" alt="Demo 项目看板" width="520">

</details>


## HALF 不是什么

- 不是 Jira、Linear 或通用项目管理工具的替代品。
- 不是通用 agent runner。对于订阅式 agent，HALF 协调 prompt 并跟踪结果；
  对于配置了 API 凭证并开启自动模式的 agent，HALF 可通过配置的 API Key
  直接调用执行。

## FAQ

**问：为什么要使用多个 AI coding agent？**

答：常见原因包括：

- **能力互补。** 不同 agent 在架构设计、代码实现、测试检查、文档整理等任
  务上的表现并不完全相同。
- **提供不同视角。** 不同模型或工具面对同一份需求、代码或方案时，往往会
  给出不同判断，有助于更早发现问题。
- **保持工具选择的灵活性。** agent 和底层模型迭代很快，同时使用多种
  agent，通常比长期只依赖单一工具更稳妥。

**问：什么时候用手动模式，什么时候用自动模式？**

答：取决于你的 agent 是否支持 API 调用。

**手动模式**适用于订阅式 agent（如 Claude.ai、Copilot、Cursor 等）——这类
agent 通过 UI 交互，而非通过 API 调用。HALF 生成一份 handoff prompt，由操作人
粘贴到 agent 界面。这是针对"以直接人工交互为设计目标的订阅式产品"的合规使用路
径。

**自动模式**适用于支持 API 调用的 agent（如配置了 Anthropic API Key 的 Claude
Code）。智能体类型配置 SDK 类型（目前支持 `claude`），每个智能体实例单独填写
API Base URL 和 API Key。任务的所有前置依赖完成后，HALF 自动派发并执行该任务，
无需任何人工干预。使用自动模式需在部署机上安装 `claude` CLI 和 `bubblewrap`。

两种模式均通过相同的 Git 协作仓库和任务看板跟踪产物。项目必须为纯手动或纯自动
模式，不支持混合模式。

**问：订阅制下使用多个 agent 协同会遇到什么问题？**

答：当任务需要多个 agent 参与，而这些 agent 又不能直接互相调用时，负责
人通常就要反复执行相同的协调动作。对很多订阅式 coding agent 而言，实际
可用的方式往往仍然是通过交互界面手工触发，而不是由另一个系统或 agent 直
接自动调用。

这通常意味着负责人需要反复：

- 复制 prompt 并手工发送给不同 agent
- 跟踪每个任务是否已经完成
- 根据前一步结果决定下一步该发给谁
- 关注每个 agent 的可用状态和重置时间

当步骤和参与者增多时，这种人工协调很容易带来遗漏、乱序和上下文切换成
本。

**问：HALF 解决了什么问题？**

答：HALF 主要解决多 agent 协作中的流程组织、状态跟踪和执行衔接问题：

- **任务流程组织。** 把项目拆成带依赖关系的任务，便于分阶段执行。
- **任务看板与衔接提示。** 在一个界面里查看计划、任务和执行状态，并在多
  步骤、串行依赖流程中明确提示下一步要做什么、该把 prompt 发给谁。
- **流程模版复用。** 把常用协作流程沉淀成模版，减少重复组织成本。
- **agent 可用性管理。** 集中查看 agent 的可用状态和重置时间，避免在执
  行过程中临时卡住。
- **API agent 的无人值守执行。** 当项目中所有 agent 均为自动模式时，HALF
  按 DAG 依赖顺序自动推进任务，无需手工粘贴 prompt。
- **结果归档与可追溯性。** 把任务产物统一沉淀到 Git 协作仓库中，便于回
  看过程和结果。

## 架构

| 层级 | 技术 |
|---|---|
| Backend | Python 3.12 + FastAPI + SQLAlchemy + SQLite |
| Frontend | React 18 + TypeScript + Vite + React Flow |
| Deployment | Docker Compose |
| Auth | JWT, bcrypt 哈希密码 |

应用代码位于 [`src/`](./src)，文档位于 [`docs/`](./docs)：

- [`ROADMAP.md`](./ROADMAP.md) - 当前路线图与方向性规划
- [`docs/prd.zh-CN.md`](./docs/prd.zh-CN.md) - 当前版本产品需求文档
- [`docs/architecture.md`](./docs/architecture.md) - 系统架构、数据模型概
  览、API 面概览
- [`docs/task-lifecycle.md`](./docs/task-lifecycle.md) - 运行机制：状态流
  转、`result.json` 协议、轮询机制
- [`docs/project-structure.md`](./docs/project-structure.md) - 面向贡献者
  的代码组织说明
- [`docs/ui-style.md`](./docs/ui-style.md) - UI 与交互原则
- [`docs/quickstart.zh-CN.md`](./docs/quickstart.zh-CN.md) - 详细的快速上手
  指南和故障排除
- [`docs/user-manual.zh-CN.md`](./docs/user-manual.zh-CN.md) - 页面级用户手册（用途、操作步骤、截图说明）
- `docs/roadmap/` - 版本级执行计划（即将推出）
- `docs/research/` - 探索性工作的调研记录（即将推出）
- `docs/adr/` - 架构决策记录（即将推出）

**API 参考文档** 由 FastAPI 自动生成。后端启动后，可访问
`http://localhost:8000/docs`（Swagger UI）或
`http://localhost:8000/redoc`。

## 快速开始

HALF 不会在弱默认配置下启动。第一次执行 `docker compose up` 之前，请先
复制示例环境变量文件并完成配置。

```bash
cd src
cp .env.example .env
# 编辑 .env 并设置：
# HALF_SECRET_KEY=<generated-secret>
# HALF_ADMIN_PASSWORD=<your-strong-password>
docker compose up -d
```

打开 `http://localhost:3000`，使用用户名 `admin` 和你设置的密码登录。
`HALF_ADMIN_PASSWORD` 必须在第一次部署前写入 `.env`；HALF 会用它创建初
始 `admin` 账号。

### 首次使用步骤

登录后：

1. **浏览 Demo 项目** - 预置的 `(Demo) 修复一个bug` 包含示例任务。查看任务
   看板、DAG 视图和 handoff prompt，了解产品形态。
2. **创建自己的项目** - 点击"新建项目"并配置：
   - HALF 协作仓库地址（必填；填写仓库根地址或 clone URL）
   - 项目代码仓库地址（可选；单仓库工作流保持与协作仓库相同即可）
   - 协作目录（协作仓库内用于存放输出的相对路径）
   - **必须选择至少一个 Agent**（从预置的 demo agents 中选择）
   - 轮询间隔和超时设置
3. **生成 Plan** - 选择流程模板并填写必填参数，生成任务 DAG。
4. **派发任务** - 手动模式项目：从任务看板启动任务，HALF 生成 prompt 供
   你粘贴到 agent UI。自动模式项目：依赖满足后任务自动派发执行，无需任
   何手工操作。

详细步骤和故障排除请参阅
[docs/quickstart.zh-CN.md](./docs/quickstart.zh-CN.md)。

## Demo 项目

首次启动时，HALF 默认会创建一个可浏览的 Demo 项目：

- 项目：`(Demo) 修复一个bug`
- HALF 协作仓库：`https://github.com/keting/half.git`
- 协作目录：`demo/half-demo-collaboration`

这个 Demo 用于首次试用和理解产品形态。它展示了一个已完成任务、两个可执
行任务，以及两个被下游依赖阻塞的任务。HALF 不会自动执行 agent；你可以
打开 Demo 查看项目看板、DAG、任务队列和 handoff prompt。

使用用户名 `admin` 和 `.env` 中设置的 `HALF_ADMIN_PASSWORD` 登录后，即可
在项目列表中打开该 Demo 项目。

如果要实际运行自己的流程，请使用你有写权限的协作仓库，例如自己的仓库或
fork，然后手工把生成的 prompt 分发给对应 agent。如果项目代码在另一个仓库，
创建项目时再单独填写项目代码仓库地址。若希望首次启动时不创建内置 Demo
项目，可以设置：

```bash
HALF_DEMO_SEED_ENABLED=false
```

## 本地开发

运行后端前，请先安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

后端：

```bash
cd src/backend
export HALF_SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')
export HALF_ADMIN_PASSWORD='<your-strong-password>'
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

> `uv` 会读取 `pyproject.toml`，并在首次运行时自动创建虚拟环境。
> 如需显式安装开发依赖，可执行：
>
> ```bash
> uv sync
> ```

前端：

```bash
cd src/frontend
npm install
npm run dev
```

前端使用相对路径 `/api` 发请求。在本地开发环境下，Vite 会把 `/api` 代理
到后端；在生产 Docker 镜像中，nginx 会代理 `/api`。

## 测试

```bash
cd src/backend && uv run pytest tests/ -v
cd src/frontend && npm test && npm run build
```

## 容器内访问 Git

默认情况下，后端容器不能直接使用宿主机上的 Git 凭据。宿主机能 clone
某个仓库，不代表后端容器也能 clone。

只需要匿名只读访问 GitHub public 仓库时，优先使用 HTTPS 地址，例如
`https://github.com/org/repo.git`。`git@github.com:org/repo.git` 这类 SSH
地址即使访问 public 仓库，也要求后端运行环境配置 SSH key 和 `known_hosts`。
private 仓库无论使用 SSH 还是 HTTPS，都需要具备目标仓库权限的凭据。

Docker 部署需要 SSH 访问时，请将 `src/docker-compose.override.yml.example`
复制为 `src/docker-compose.override.yml`，并只挂载专用 deploy key 和
`known_hosts` 到后端容器。不要将整个 `~/.ssh` 目录挂载到容器中。典型流程：

```bash
ssh-keygen -t ed25519 -f ~/.ssh/half_deploy_key -C half-backend
ssh-keyscan github.com >> ~/.ssh/known_hosts
```

将 `~/.ssh/half_deploy_key.pub` 添加到目标仓库的 deploy key 后，再取消注释并
调整 `src/docker-compose.override.yml` 中的私钥、公钥和 `known_hosts` 挂载。
private 仓库如果使用 HTTPS，建议通过容器侧 Git credential 配置或
credential helper 提供 token；不要把 access token 或 password 写进仓库 URL。

创建和编辑项目时必须填写 HALF 协作仓库地址。它是 HALF clone 并轮询的仓库，
用于保存计划、任务产物、`result.json` 和可选用量记录。项目代码仓库地址可
以单独填写；留空或勾选“与 HALF 协作仓库相同”时，HALF 会把项目代码仓库视为
同一个仓库。项目代码仓库地址会进入生成的 prompt，但 HALF 轮询时不会 clone
或校验该仓库。

两个仓库字段都接受仓库根地址和 clone URL，例如
`https://github.com/org/repo`、`https://github.com/org/repo.git`、
`ssh://git@github.com/org/repo.git`、`git@github.com:org/repo.git`。GitHub、
Gitee、Bitbucket、Codeberg 的仓库根地址必须是 `owner/repo` 两段；GitLab
也接受 `https://gitlab.com/group/subgroup/repo` 这类 subgroup 仓库根地址。
保存时只做 URL 格式和安全校验，不证明仓库真实存在，也不证明容器或 agent
已有访问权限。不要填 issues、pull、tree、blob、graphs 等仓库内页面 URL，
也不要把凭据、access token 或 deploy token 内嵌在 URL 的 userinfo、query
或 fragment 中。

## 生产部署说明

HALF 通常以自托管方式部署。用于生产环境时，请保持
`HALF_STRICT_SECURITY=true`，并在暴露服务前先阅读
[`SECURITY.md`](./SECURITY.md)。

## 配置

完整环境变量及默认值请参考 [`src/.env.example`](./src/.env.example)。

## 语言

当前 UI 主要为简体中文。欢迎补充英文 i18n 贡献。

## 安全

关于信任模型、威胁模型以及漏洞报告方式，请参阅
[`SECURITY.zh-CN.md`](./SECURITY.zh-CN.md)。

## 贡献

HALF 欢迎不同形式的贡献，不限于提交代码：

- 阅读 AI Coding / Coding Agent 论文、系统或技术报告，在 Discussion 提出对
  roadmap 的启发。
- 报告 bug、文档错误或明确需求，请创建 Issue。
- 方向性想法、方案对比、benchmark、合规边界等，请发起 Discussion。
- 认领 `status:ready` 或 `good first issue` 的 Issue 并提交 PR。
- 改进 README、Quick Start、User Manual、FAQ、截图、demo 和测试。
- 贡献 workflow 模板、handoff prompt、plan DAG case，或记录 agent 协作失败
  模式。
- 熟悉项目后参与 Issue triage、PR Review、Milestone 与 Roadmap 讨论。

第一次参与建议按这条路径开始：

1. 读 README，浏览产品截图和 ROADMAP（约 15 分钟）。
2. 按 Quick Start 跑通 Demo Project（约半天）。
3. 从 `good first issue` 或文档改进提交你的第一个 PR。
4. 中大型改动（涉及 API、数据模型或新模块）请先开 Discussion 对齐范围。

完整说明请阅读 [`CONTRIBUTING.zh-CN.md`](./CONTRIBUTING.zh-CN.md) 和
[`docs/newcomer-path.zh-CN.md`](./docs/newcomer-path.zh-CN.md)。

发现安全漏洞、敏感信息泄露、权限绕过或权限模型风险，**不要**创建公开
Issue，请按 [`SECURITY.zh-CN.md`](./SECURITY.zh-CN.md) 私下报告。社区行为
规范见 [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md)。

## 引用

如果你在研究、教学或软件工程实验中使用 HALF，请引用 Zenodo 项目归档记录：

Keting. (2026). HALF: Human-AI Loop Framework. Zenodo.
https://doi.org/10.5281/zenodo.19809712

引用元数据也可以在 [`CITATION.cff`](./CITATION.cff) 中查看。

DOI 维护说明：HALF 使用 Zenodo Concept DOI 作为仓库级引用和元数据 DOI。
版本级 DOI 由 Zenodo 管理，不会在每个 release 后都回写到仓库。若需要精确
复现某个版本，请使用对应 Zenodo 记录中显示的版本级 DOI。

## 许可证

Apache License 2.0。详见 [`LICENSE`](./LICENSE)。
