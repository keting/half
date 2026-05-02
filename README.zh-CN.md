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
  作计划，分发任务 prompt，并通过轮询项目 Git 仓库跟踪状态。
- **天然的人在回路中。** HALF 不会执行 agent 命令，而是生成人工可直接粘
  贴到 agent UI 的 prompt，并通过仓库结果回写来观察执行产物。
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
- 不是 agent runner。它协调 prompt 和结果，但不会直接调用 LLM。

## FAQ

**问：为什么要使用多个 AI coding agent？**

答：常见原因包括：

- **能力互补。** 不同 agent 在架构设计、代码实现、测试检查、文档整理等任
  务上的表现并不完全相同。
- **提供不同视角。** 不同模型或工具面对同一份需求、代码或方案时，往往会
  给出不同判断，有助于更早发现问题。
- **保持工具选择的灵活性。** agent 和底层模型迭代很快，同时使用多种
  agent，通常比长期只依赖单一工具更稳妥。

**问：为什么 HALF 采用 human-in-the-loop，而不是全自动调用 agent？**

答：最主要的原因是合规。

HALF 当前的设计目标，是在合规前提下支持多 agent 协作。很多常见的 coding
agent 产品，尤其是订阅式产品，主要面向个人或团队直接交互使用，而不是作
为一个可被外部系统统一托管和自动调用的服务来设计。对于程序化集成和自动
化编排场景，通常需要使用单独的 API 产品、API key、计费方式和相应条款。

因此，HALF 有意把系统边界放在：

- 生成人工可直接使用的 prompt
- 由负责人手工分发给 agent
- 通过 Git 回写和仓库轮询跟踪执行结果

也就是说，HALF 解决的是合规前提下的人机协同多 agent 编排问题，而不是把
订阅式 agent 当作可由平台统一托管和自动调用的 runner。

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
- [`docs/architecture.md`](./docs/architecture.md) - 系统架构、数据模型概
  览、API 面概览
- [`docs/task-lifecycle.md`](./docs/task-lifecycle.md) - 运行机制：状态流
  转、`result.json` 协议、轮询机制
- [`docs/project-structure.md`](./docs/project-structure.md) - 面向贡献者
  的代码组织说明
- [`docs/ui-style.md`](./docs/ui-style.md) - UI 与交互原则
- [`docs/quickstart.zh-CN.md`](./docs/quickstart.zh-CN.md) - 详细的快速上手
  指南和故障排除
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
   - Git 仓库地址（必填；填写仓库根地址或 clone URL）
   - 协作目录（用于存放输出的相对路径）
   - **必须选择至少一个 Agent**（从预置的 demo agents 中选择）
   - 轮询间隔和超时设置
3. **生成 Plan** - 选择流程模板并填写必填参数，生成任务 DAG。
4. **派发任务** - 从任务看板启动任务；HALF 生成 prompt 供你粘贴到 agent UI。

详细步骤和故障排除请参阅
[docs/quickstart.zh-CN.md](./docs/quickstart.zh-CN.md)。

## Demo 项目

首次启动时，HALF 默认会创建一个可浏览的 Demo 项目：

- 项目：`(Demo) 修复一个bug`
- 仓库：`https://github.com/keting/half.git`
- 协作目录：`demo/half-demo-collaboration`

这个 Demo 用于首次试用和理解产品形态。它展示了一个已完成任务、两个可执
行任务，以及两个被下游依赖阻塞的任务。HALF 不会自动执行 agent；你可以
打开 Demo 查看项目看板、DAG、任务队列和 handoff prompt。

使用用户名 `admin` 和 `.env` 中设置的 `HALF_ADMIN_PASSWORD` 登录后，即可
在项目列表中打开该 Demo 项目。

如果要实际运行自己的流程，请使用你有写权限的仓库，例如自己的仓库或 fork，
然后手工把生成的 prompt 分发给对应 agent。若希望首次启动时不创建内置
Demo 项目，可以设置：

```bash
HALF_DEMO_SEED_ENABLED=false
```

## 本地开发

后端：

```bash
cd src/backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
export HALF_SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')
export HALF_ADMIN_PASSWORD='<your-strong-password>'
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

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
cd src/backend && python -m pytest tests/ -v
cd src/frontend && npm test && npm run build
```

## 容器内访问 Git

默认情况下，后端容器无法访问私有 Git 仓库。HALF 不会默认挂载宿主机 SSH
key。如果你需要访问私有仓库，请将 `src/docker-compose.override.yml.example`
复制为 `src/docker-compose.override.yml`，并挂载专用 deploy key。
私有仓库建议使用专用 SSH deploy key、credential helper 或后端容器专门配置
的凭据；不要把 access token 或 password 写进仓库 URL。

创建和编辑项目时必须填写 Git 仓库地址。HALF 接受仓库根地址和 clone URL，
例如 `https://github.com/org/repo`、`https://github.com/org/repo.git`、
`ssh://git@github.com/org/repo.git`、`git@github.com:org/repo.git`。GitHub、
Gitee、Bitbucket、Codeberg 的仓库根地址必须是 `owner/repo` 两段；GitLab
也接受 `https://gitlab.com/group/subgroup/repo` 这类 subgroup 仓库根地址。
保存时只做 URL 格式和安全校验，不证明仓库真实存在，也不证明容器已有访问权限。
不要填 issues、pull、tree、blob、graphs 等仓库内页面 URL，也不要把凭据、
access token 或 deploy token 内嵌在 URL 的 userinfo、query 或 fragment 中。

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

贡献说明请参阅 [`CONTRIBUTING.zh-CN.md`](./CONTRIBUTING.zh-CN.md)。

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
