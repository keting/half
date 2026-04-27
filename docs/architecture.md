# HALF 架构说明

> **对应版本**：v0.2.0
> 本文档描述当前代码已经实现的系统结构、关键设计决策和公开面。以代码为事实源头；文档与代码不一致时，代码为准。

---

## 一、系统定位

HALF（Human-AI Loop Framework）是一个人机协同多智能体任务管理平台。它面向同时使用多个 AI coding agent（Claude Code、Codex、Copilot、GLM、Kimi 等）的研究者和团队，通过纯人工触发的方式协调任务编排、prompt 分发、状态跟踪和结果归档：系统生成 prompt，负责人手工粘贴到 agent 执行，agent 把产物写回项目 git 仓库，HALF 后台轮询 git 仓库识别完成。整个闭环不调用 agent 平台的非公开接口，不做接口逆向。

---

## 二、整体架构

```
┌────────────────────────────────────────────┐
│              浏览器（项目负责人）           │
│   项目 / Plan / 任务执行 / 模版 / Agent 管理 │
└──────────────────┬─────────────────────────┘
                   │ HTTP API (JWT Bearer)
┌──────────────────▼─────────────────────────┐
│         FastAPI 后端服务（Python 3.12）     │
│  ┌──────────┐ ┌──────────┐ ┌────────────┐  │
│  │ 项目管理  │ │ Prompt   │ │ 状态推进    │  │
│  │ 路由与鉴权│ │ 生成服务  │ │ 引擎        │  │
│  └──────────┘ └──────────┘ └────────────┘  │
│  ┌──────────┐ ┌──────────┐                  │
│  │ DAG 解析 │ │ Git 轮询 │                  │
│  │ 与校验   │ │ Worker   │                  │
│  └──────────┘ └────┬─────┘                  │
│                    │                        │
│  ┌─────────────────▼──────────────────────┐ │
│  │   SQLite（系统状态、项目元数据、       │ │
│  │   任务状态、审计日志）                  │ │
│  └────────────────────────────────────────┘ │
└──────────────────┬─────────────────────────┘
                   │ git CLI: clone / fetch / pull / read
┌──────────────────▼─────────────────────────┐
│            Git Repository（每项目一个）     │
│   <collaboration_dir>/plan-<id>.json       │
│   <collaboration_dir>/<task_code>/result.json │
│   <collaboration_dir>/<task_code>/usage.json  │
└────────────────────────────────────────────┘

        ┌──────────┐              ┌──────────┐
        │  机器 A   │              │  机器 B   │
        │Claude Code│              │  Codex   │
        │   ↕ git   │              │  ↕ git   │
        └──────────┘              └──────────┘
```

**三层划分**：

- **前端**：React 18 + TypeScript + Vite SPA，负责页面渲染、交互编辑、手工触发复制操作；通过 JWT Bearer 访问后端 REST API。
- **后端**：FastAPI（Python 3.12）服务，负责鉴权、业务状态维护、prompt 生成、DAG 解析、Git 轮询调度。后端 **不主动调用 agent**。
- **存储**：**SQLite 承载系统内部状态**（项目、计划、任务、用户、审计日志等）；**Git 仓库承载项目协同产物**（每个项目一个独立仓库，任务输出、`result.json` 哨兵、`usage.json` 用量记录）。SQLite 与 Git 通过轮询桥接。

---

## 三、核心设计决策

### 3.1 为什么把协同数据放 Git

- 命令行类 agent（Claude Code、Codex）本身就具备 git 读写能力，以 git 仓库承载任务输出**零额外集成成本**
- git 的版本历史满足可追溯与审计需求
- Agent 与人类成员使用同一份协同数据，没有双向同步问题

### 3.2 为什么系统状态不完全存 Git

登录态、项目元数据、任务状态主记录、页面交互状态不适合放 git。HALF 采用 **SQLite 存系统状态 + Git 存协同产物** 的双层方案：轮询读取 git 仓库内的哨兵文件后，回写 SQLite 中的任务状态。

### 3.3 为什么用 Git 轮询而不是 webhook / 事件驱动

- 合规约束下不能调用 agent 平台的非公开接口
- 不能在 agent 侧植入回调钩子
- 轮询是在该约束下**最可行**的状态检测方式

轮询采用**可配置随机间隔**（全局默认 15-30 秒，支持项目级覆盖），支持**可配置延迟启动**，并提供**手动刷新**按钮。

### 3.4 任务完成契约：固定目录 + `result.json` 哨兵

早期版本依赖 `expected_output` 字段里的自然语言路径做轮询检测，容易被 agent 输出中的括号注释、多文件说明、自然语言描述污染。当前版本把完成契约收敛为：

- 每个任务固定写入 `<collaboration_dir>/<task_code>/`
- 所有产物先写入该目录，最后**原子提交 `result.json`** 作为完成哨兵
- 可选 `usage.json` 与其放同目录

这样同时覆盖单文件和多文件任务，显著降低轮询误判漏判。具体状态流转参见 `task-lifecycle.md`。

### 3.5 人工派发模式（Human-in-the-Loop）

MVP 所有任务分发均由项目负责人手工完成——系统生成 prompt，负责人点击"复制 Prompt 并派发"按钮把内容送到剪贴板，再手工粘贴给对应 agent。HALF 不会自动发送任何 prompt。

**剪贴板 user-activation 约束**：浏览器要求 `navigator.clipboard.writeText` 必须在用户点击产生的同步执行栈内调用。前端因此采用"预取 prompt + 同步写剪贴板"的编排：选中任务时后台预取最新 prompt 缓存；用户点击时 `copyText` 在任何 `await` 之前直接写剪贴板；写入失败必须显式中止，不得继续调用 `/dispatch`。这避免了"按钮显示已复制但剪贴板里残留的是上一个任务 prompt"的历史 bug。

---

## 四、技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.12 + FastAPI + SQLAlchemy |
| 数据库 | SQLite |
| 认证 | JWT（HS256 签名）+ bcrypt 密码哈希 |
| 前端 | React 18 + TypeScript + Vite |
| 路由 | React Router |
| DAG 可视化 | React Flow |
| 前端测试 | Vitest |
| 后端测试 | pytest |
| Git 集成 | git CLI（必要时使用 GitPython） |
| 部署 | Docker Compose |

详见 `project-structure.md` 的代码组织和 `README.md` 的快速启动。

---

## 五、角色与权限模型

### 5.1 角色

系统本身作为基础设施，负责任务编排、状态轮询、页面展示，不作为参与者介入执行。具体角色：

- **项目负责人（Owner）**：项目的创建者和驱动者。创建项目、选择 agent、生成/调整计划、派发任务，并承担所有人工操作（复制 prompt、粘贴给 agent、异常处理等）。
- **Agent 成员**：参与执行的 AI 工具，以本地 CLI 形式运行。

### 5.2 用户权限

账号分两类：

- **管理员（`admin`）**：可访问系统级设置、智能体类型配置、项目参数设置、用户管理页面
- **普通用户（`user`）**：可管理自己创建的智能体、项目、计划、任务、模版

**Owner 级业务隔离（应用层）**：所有业务资源（Agent / Project / Plan / Task / 轮询记录）在 `access.py` 中强制按当前登录用户的 `created_by` 字段过滤——**应用层面管理员不会看到其他用户创建的项目和智能体**，跨用户访问返回资源不存在或参数非法。这是当前代码实际的权限边界。

**部署层信任模型（参见根目录 `SECURITY.md`）**：HALF 默认面向单租户自托管场景。部署层面假设管理员被完全信任（可以访问 HALF 数据库、git 仓库副本、宿主机文件系统等）。换句话说：应用层不依赖管理员的额外权限（比如接管别人的项目），但**部署者必须默认管理员有能力绕过应用层访问所有数据**。

**流程模版（process_templates）例外**：所有登录用户可列出、查看、使用模版；只有创建者和管理员可更新或删除。

### 5.3 用户状态

- `active`：正常，可登录
- `frozen`：冻结，禁止登录；已签发的 token 在后续请求时也会被拒绝

系统强制**至少保留一个激活状态的管理员**；管理员不能冻结自己、不能修改自己的角色。

### 5.4 注册控制

注册开关由部署配置 `HALF_ALLOW_REGISTER` 决定：

- `true` 时登录页展示注册入口
- `false` 时前端不展示，后端也拒绝 `/api/auth/register`（生产部署默认保持 `false`）

---

## 六、数据模型概览

> 这里只描述**核心实体 + 关系 + 关键行为约束**。字段级定义以 `src/backend/models.py` 为事实源头；SQLAlchemy model 代码本身就是 schema 的真相源。

### 6.1 核心实体

| 实体 | 说明 |
|---|---|
| `User` | 系统用户（admin / user）；`status` 为 `active` 或 `frozen` |
| `Agent` | 用户登记的 AI agent，含多模型配置（`models_json`）、订阅到期、短期/长期重置时间与间隔 |
| `AgentTypeConfig` + `ModelDefinition` + `AgentTypeModelMap` | Agent 类型目录与模型定义的全局配置，由管理员维护 |
| `Project` | 项目。含 `git_repo_url`、`collaboration_dir`、`planning_mode`、`template_inputs_json`、轮询配置快照、`goal`（任务介绍） |
| `ProjectPlan` | 计划。每个项目可有多个 `candidate` 计划和一个 `final` 计划 |
| `ProcessTemplate` | 可复用的流程模版。任务中的 `assignee` 使用抽象槽位 `agent-N`，应用到项目时替换为真实 Agent |
| `Task` | 计划 finalize 后产生的执行任务；`status` 覆盖 `pending / running / completed / needs_attention / abandoned` |
| `TaskEvent` | 任务状态变更事件（dispatched / completed / timeout / manual_complete / abandoned / redispatched / updated / error） |
| `GlobalSetting` | 全局项目参数（轮询间隔、启动延迟、默认超时）+ 规划 prompt 的同机分配引导 |
| `AuditLog` | 密码修改、用户角色/状态变更的操作审计日志 |

### 6.2 关键关系

```
User ──owns──► Agent, Project, ProcessTemplate
Project ──has many──► ProjectPlan (1 final + N candidate)
Project ──has many──► Task (from the final plan)
ProjectPlan ──generates──► Task (on finalize)
Task ──writes──► TaskEvent (状态变更时)
ProcessTemplate ──applied to──► Project ──creates──► ProjectPlan (source_path = template:<id>)
```

### 6.3 关键行为约束（代码级细节分散在 service/validator/test 中，这里列出最重要的几条）

- **Agent 的可用状态是派生的**：持久字段 `availability_status` 接受 `available / short_reset_pending / long_reset_pending`；同时因为 `models.py` 定义默认值为 `unknown`，旧数据和默认插入值里仍可能出现 `unknown`——运行时 `services/agents.py::derive_agent_status` 把 `unknown` 当作 `available` 处理。`unavailable` 是派生状态（**不存储**），由 `subscription_expires_at` 实时推导
- **项目轮询配置是快照**：创建项目时把当前的全局默认（`polling_interval_min/max`、`polling_start_delay_*`、`task_timeout_minutes`）快照写入项目；此后全局配置变更**不追溯**影响既有项目
- **Task 超时时间是快照**：最终计划生成 Task 时把项目级 `task_timeout_minutes` 写入 `tasks.timeout_minutes`；`pending` 状态可编辑，进入 `running` 后不可编辑
- **Owner 隔离在后端强制**：业务接口在 Session 层按 `created_by = current_user.id` 过滤，历史 `NULL` 值启动时自动回填到默认管理员
- **路径统一仓库根相对**：`collaboration_dir`、`source_path`、`expected_output_path` 创建/更新时 strip 前后斜杠；`services.git_service._safe_join` 保证 `..` 越界等非法路径被拒绝
- **时间语义分两组**：
  - *业务运行事件时间*（项目/计划/任务/事件/用户/审计日志）按 UTC 存储传输，API 响应带 UTC 标记；前端按浏览器本地时区展示
  - *Agent 相关时间*（`subscription_expires_at`、`short_term_reset_at`、`long_term_reset_at`）以"北京时间无时区" datetime 直接存储；`services/agents.py::derive_agent_status` 和前端 `utils/agents.ts::deriveAgentStatus` 都以北京时间为基准做比较，不经 UTC 换算

---

## 七、API 面（概览）

> 这里只给分组和端点类别；**完整端点签名、请求/响应 schema 请直接查看 FastAPI 自动生成的交互式文档**：
>
> - **Swagger UI**：`http://localhost:8000/docs`
> - **ReDoc**：`http://localhost:8000/redoc`
>
> 后端启动后两者自动可用，且始终与代码对齐。

### 7.1 认证方式

所有业务接口要求 `Authorization: Bearer <token>` 头部。token 由 `POST /api/auth/login` 签发，有效期 24 小时，使用 HS256 签名。冻结用户的 token 在 `get_current_user` 层直接返回 403。

### 7.2 分组

| 分组 | 路由前缀 | 职责 |
|---|---|---|
| 认证 | `/api/auth` | 登录、注册、获取当前用户、修改密码、运行配置（`allow_register`） |
| 健康检查 | `/health` | 返回 `{"status": "ok"}` |
| Agent 管理 | `/api/agents` | 当前用户的 Agent CRUD；短期/长期重置的 reset / confirm；状态切换；类型只读目录 |
| 智能体设置 | `/api/agent-settings` | Agent 类型和模型的全局配置，**仅管理员可用** |
| 项目管理 | `/api/projects` | 项目 CRUD；获取项目详情含"下一步"提示 |
| 工作计划 | `/api/projects/:id/plans/...` | 生成 prompt、派发、finalize；候选/最终计划查询 |
| 流程模版 | `/api/process-templates` | 模版 CRUD、生成模版编写 prompt、应用模版到项目 |
| 任务管理 | `/api/tasks/...` | 任务详情、更新、生成 prompt、派发、重新派发、标记完成、标记放弃、前序状态查询（兼容保留） |
| 状态与汇总 | `/api/projects/:id/...` | 手动轮询触发、获取轮询配置、获取执行汇总 |
| 全局设置 | `/api/settings` | 轮询默认值、Prompt 设置（同机分配引导）；写接口**仅管理员可用** |
| 用户管理 | `/api/admin/users` + `/api/admin/audit-logs` | 用户列表、改角色、冻结/解冻、审计日志；**仅管理员可用** |

**分页说明**：当前版本没有统一的分页抽象，大多数列表接口直接返回全量。仅 `GET /api/admin/audit-logs` 接受 `limit` query 参数（默认 50，最大 200）。

---

## 八、前端页面与路由

| 路由 | 页面 | 说明 |
|---|---|---|
| `/login` | 登录/注册 | 加载时先查 `/api/auth/config` 决定是否展示注册入口 |
| `/projects` | 项目列表 | 项目卡片；右上角"创建项目"；管理员可见"设置"入口 |
| `/projects/new`、`/projects/:id/edit` | 项目创建/编辑 | 名称、目标、Git 地址、参与 Agent、轮询参数快照；**规划模式不在本页**展示 |
| `/projects/:id` | 项目详情 | 核心工作台："下一步"提示 + 状态总览 + 阶段入口 |
| `/projects/:id/plan` | 计划生成 | 流程来源选择（左：使用模版；右：由 Prompt）、任务介绍、规划模式（仅 Prompt 路径）、Agent 勾选、Prompt 生成与复制、状态灯与计时器 |
| `/projects/:id/tasks` | 任务执行 | DAG 视图 + 右侧任务详情面板 + Prompt 复制 + 异常处理 |
| `/projects/:id/summary` | 执行汇总 | 任务状态总览 + 产出文件链接 + 人工介入记录 |
| `/settings` | 项目参数设置 | 全局轮询参数、默认 Task 超时、Prompt 设置；**仅管理员可访问** |
| `/templates` | 模版列表 | 所有登录用户可查看/使用；创建者与管理员可编辑/删除 |
| `/templates/new`、`/templates/:templateId`、`/templates/:templateId/edit` | 模版新建/详情/编辑 | 三段式：基本信息 / 输入描述 / 编辑 JSON；DAG 预览；角色说明；必需输入声明 |
| `/agents` | 智能体总览 | 单列卡片；自动排序按状态分组；支持拖拽手动排序；卡片内显示短期/长期重置倒计时 |
| `/agents/settings` | 智能体设置 | Agent 类型和模型的全局配置；**仅管理员可访问** |
| `/admin/users` | 用户管理 | 用户列表 + 改角色 + 冻结/解冻；**仅管理员可访问** |

**路由级代码分割**：除 `LoginPage` 和 `ProjectListPage` 外的页面统一用 `React.lazy + <Suspense>` 懒加载，避免主包被重依赖（React Flow 等）拖大。

---

## 九、部署形态

- **Docker Compose**：前后端各一个容器。后端挂载 SQLite 数据目录和 Git 仓库副本目录。
- **自托管**：HALF 设计为自托管部署，可以运行在个人服务器、团队服务器或云主机上。
- **Git 访问**：容器默认不挂载宿主 SSH key；如需访问私有仓库，参考 `src/docker-compose.override.yml.example`。
- **共享工作区（可选）**：当后端与用户工作区在同一台机器上时，轮询在仓库副本未命中文件时可回退到共享工作区的同路径文件（前提是 `git remote origin` 与项目仓库地址一致）。

---

## 十、相关文档

- `task-lifecycle.md`：任务从创建到完成的完整生命周期、状态流转、`result.json` / `usage.json` 契约、轮询逻辑、Agent 可用性跟踪
- `project-structure.md`：代码组织导览——后端模块、前端模块、测试目录、入口文件
- `ui-style.md`：前端设计系统（视觉定位、组件、排版、色板、review checklist）
- `README.md`：快速启动、本地开发、生产部署要点
- `SECURITY.md`：信任模型、威胁模型、漏洞报告渠道
