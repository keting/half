# 代码结构导览

> **对应版本**：v0.2.1
> 本文档帮助想要修改 HALF 代码的贡献者快速定位对应模块。以 `main` 分支的当前真实目录结构为准。

---

## 一、仓库根

```
half/
├── CITATION.cff                   # 学术引用元数据（Keting Yin + ORCID）
├── CONTRIBUTING.md                # 贡献指南
├── LICENSE                        # Apache License 2.0
├── README.md                      # 项目总览、快速启动
├── README.zh-CN.md                # 中文项目总览、快速启动
├── SECURITY.md                    # 信任模型、威胁模型、漏洞报告渠道
├── SECURITY.zh-CN.md              # 中文安全政策
├── ROADMAP.md                     # 对外路线图与方向性规划
├── ROADMAP.zh-CN.md               # 中文路线图
├── docs/                          # 公开文档
│   ├── architecture.md            # 系统架构说明
│   ├── task-lifecycle.md          # 运行时机制（状态流转、轮询、契约）
│   ├── project-structure.md       # 本文档
│   ├── quickstart.md              # 快速启动与排错（英文）
│   ├── quickstart.zh-CN.md        # 快速启动与排错（中文）
│   ├── ui-style.md                # 前端设计系统
│   └── releases/                  # 版本发布说明
└── src/                           # 应用代码
    ├── docker-compose.yml
    ├── docker-compose.override.yml.example
    ├── README.md                  # 本地开发补充说明
    ├── backend/                   # Python / FastAPI
    └── frontend/                  # React / TypeScript / Vite
```

---

## 二、后端（`src/backend/`）

```
backend/
├── Dockerfile
├── requirements.txt               # fastapi, uvicorn, sqlalchemy, pyjwt, passlib[bcrypt], bcrypt, python-multipart, json-repair
├── main.py                        # FastAPI app 入口；启动期校验、初始化和 polling worker 启动
├── config.py                      # Settings 类 + validate_security_config（启动期弱密钥/弱密码拒启）
├── database.py                    # SQLAlchemy engine / SessionLocal / Base
├── models.py                      # 12 个 ORM 模型（User / Agent / GlobalSetting / Project / ProjectPlan / ProcessTemplate / Task / AgentTypeConfig / ModelDefinition / AgentTypeModelMap / TaskEvent / AuditLog）
├── schemas.py                     # Pydantic 响应/请求 schema
├── auth.py                        # JWT 签发与校验、bcrypt 密码哈希工具
├── access.py                      # get_owned_project / get_owned_task、Agent 可见性与可用性等业务隔离工具
├── routers/                       # REST API 路由层
│   ├── auth.py                    # /api/auth/*
│   ├── agents.py                  # /api/agents/*
│   ├── agent_settings.py          # /api/agent-settings/*（仅管理员）
│   ├── projects.py                # /api/projects CRUD
│   ├── plans.py                   # /api/projects/:id/plans/*
│   ├── tasks.py                   # /api/tasks/*（无 prefix；在 main 里 include）
│   ├── polling.py                 # /api/projects/:id/poll、polling-config、summary
│   ├── process_templates.py       # /api/process-templates/*
│   ├── settings.py                # /api/settings/polling、/api/settings/prompt
│   └── users.py                   # /api/admin/users/* + /api/admin/audit-logs（仅管理员）
├── services/                      # 业务服务层
│   ├── git_service.py             # clone / fetch / pull / read_file / file_exists / _safe_join / validate_git_url
│   ├── path_service.py            # resolve_expected_output_path / normalize_expected_output_path（路径归一化 + 防越界）
│   ├── prompt_service.py          # generate_plan_prompt / generate_task_prompt / generate_template_prompt
│   ├── prompt_settings.py         # 全局 Prompt 设置（同机分配引导）读写
│   ├── polling_service.py         # polling_loop / poll_project / get_effective_task_timeout_minutes
│   ├── polling_config_service.py  # 项目级轮询参数解析
│   ├── agents.py                  # Agent availability 状态推导、短期/长期重置续推逻辑
│   ├── project_agents.py          # 项目-Agent 绑定校验
│   └── usage_limits.py            # 用量相关辅助
├── middleware/
│   └── rate_limit.py              # 登录限流（5 次失败锁 15 分钟）
├── validators/
│   └── git_url.py                 # Git URL 白名单（见 SECURITY.md）
└── tests/                         # pytest 测试（20+ 个文件）
    ├── test_admin_user_management.py
    ├── test_agent_owner_repair.py
    ├── test_agent_reset_times.py
    ├── test_agent_update_semantics.py
    ├── test_git_service.py
    ├── test_path_service.py
    ├── test_plan_assignee_resolution.py
    ├── test_plan_finalize_validation.py
    ├── test_plan_prompt_reuse.py
    ├── test_polling_service.py
    ├── test_polling_settings.py
    ├── test_process_templates.py
    ├── test_project_agent_availability.py
    ├── test_project_isolation.py
    ├── test_prompt_service.py
    └── ...
```

### 2.1 入口与启动流程

后端入口在 `src/backend/main.py`。启动时主要做四类事情：

1. 校验安全相关配置是否满足最低要求
2. 初始化数据库和默认全局设置
3. 确保管理员账号可用
4. 启动后台 polling worker

FastAPI 应用也在这里实例化，并挂载 auth、agents、projects、plans、tasks、polling、settings、users、process templates 等路由。

### 2.2 核心模块职责速查

| 想改什么 | 去哪 |
|---|---|
| 登录、注册、JWT 有效期 | `routers/auth.py` + `auth.py` |
| 密码强度 / 启动期校验 | `config.py::validate_security_config` |
| Agent 可用性推导、续推 | `services/agents.py` |
| Git 读文件 / 同步策略 | `services/git_service.py::ensure_repo_sync / read_file / dir_has_content` |
| 路径安全 / 归一化 | `services/path_service.py` |
| Prompt 模板 | `services/prompt_service.py` |
| 轮询循环 | `services/polling_service.py::polling_loop / poll_project` |
| 任务超时判定 | `services/polling_service.py::get_effective_task_timeout_minutes` |
| Owner 级隔离 | `access.py` |
| 登录限流 | `middleware/rate_limit.py` |
| Git URL 白名单 | `validators/git_url.py` |

---

## 三、前端（`src/frontend/`）

```
frontend/
├── Dockerfile
├── nginx.conf                     # 生产镜像用 nginx 托管 SPA + /api 代理到后端
├── package.json                   # scripts: dev / build / preview / test
├── vite.config.ts
├── tsconfig.json
├── src/
│   ├── main.tsx                   # React 入口
│   ├── App.tsx                    # 路由总表（React Router + React.lazy 懒加载）
│   ├── auth.ts                    # 本地存储 token / username / role / status 读写
│   ├── contracts.ts               # 与后端共享的类型契约
│   ├── contracts.test.ts
│   ├── api/
│   │   ├── client.ts              # fetch 封装、getCached（SWR 风格）、invalidate、错误解析
│   │   └── client.test.ts
│   ├── pages/                     # 一页一文件
│   │   ├── LoginPage.tsx          # 登录 + 注册（当 allow_register=true 时）
│   │   ├── ProjectListPage.tsx    # /projects 项目列表
│   │   ├── ProjectNewPage.tsx     # /projects/new、/projects/:id/edit
│   │   ├── ProjectDetailPage.tsx  # /projects/:id 核心工作台
│   │   ├── PlanPage.tsx           # /projects/:id/plan 计划生成（双路径）
│   │   ├── TasksPage.tsx          # /projects/:id/tasks DAG + 任务执行
│   │   ├── SummaryPage.tsx        # /projects/:id/summary 执行汇总
│   │   ├── ProjectSettingsPage.tsx # /settings 全局项目参数（仅管理员）
│   │   ├── ProcessTemplatesPage.tsx # /templates/* 模版 CRUD 的统一多视图组件
│   │   ├── AgentsPage.tsx         # /agents 单列卡片 + 拖拽排序 + 重置倒计时
│   │   ├── AgentSettingsPage.tsx  # /agents/settings（仅管理员）
│   │   └── UserManagementPage.tsx # /admin/users（仅管理员）
│   ├── components/                # 通用组件
│   │   ├── Layout.tsx             # 左侧导航 + 欢迎信息 + 修改密码入口
│   │   ├── PageHeader.tsx
│   │   ├── SectionCard.tsx        # ui-style.md 里定义的 section card 组件
│   │   ├── StatusBadge.tsx
│   │   ├── CountdownChip.tsx      # Agent 倒计时（颜色阈值见 ui-style）
│   │   ├── ModelBadge.tsx
│   │   ├── DagView.tsx            # React Flow 包装，用于 Plan 预览和 Tasks 页
│   │   └── TaskDetailPanel.tsx    # Tasks 页右侧面板（预取 prompt + 原子派发）
│   ├── utils/
│   │   ├── agents.ts              # Agent 状态推导
│   │   ├── datetime.ts            # 统一时间格式化（按浏览器本地时区）
│   │   ├── datetime.test.ts
│   │   ├── flowSource.ts          # Plan 页流程来源偏好（localStorage）
│   │   ├── flowSource.test.ts
│   │   ├── planningMode.ts        # 四种规划模式的枚举和说明文案
│   │   ├── processTemplateRoles.ts # 从 JSON 抽取 slot、同步角色说明
│   │   ├── processTemplateRoles.test.ts
│   │   ├── applyTemplatePlan.ts   # 模版路径应用时的前端编排
│   │   └── applyTemplatePlan.test.ts
│   ├── styles/                    # 全局 CSS 变量与组件样式
│   └── types/                     # TypeScript 类型声明
```

### 3.1 路由总表

除 `LoginPage` 和 `ProjectListPage` 外，其他页面统一用 `React.lazy + <Suspense>` 懒加载，避免主包被 React Flow 等重依赖拖大。

完整路由参见 `architecture.md` 第八节。

### 3.2 核心模块职责速查

| 想改什么 | 去哪 |
|---|---|
| 添加/修改路由 | `App.tsx` |
| API 调用封装、缓存、错误解析 | `api/client.ts` |
| 修改左侧导航项 | `components/Layout.tsx` |
| Tasks 页的派发原子性 / 预取 prompt | `components/TaskDetailPanel.tsx` + `pages/TasksPage.tsx` |
| Plan 页的流程来源 / 规划模式 / Prompt 生成 | `pages/PlanPage.tsx` + `utils/flowSource.ts` + `utils/planningMode.ts` |
| 模版 JSON 的 slot 抽取 | `utils/processTemplateRoles.ts` |
| Agent 倒计时颜色阈值 / 状态徽章 | `components/CountdownChip.tsx` + `components/StatusBadge.tsx` |
| 全局视觉（色板、组件样式） | `styles/` + 遵循 `ui-style.md` |

### 3.3 构建脚本

```bash
npm run dev       # 本地开发（Vite proxy /api → 后端）
npm run build     # tsc 类型检查 + vite build
npm run preview   # 本地预览 build 产物
npm test          # vitest 运行单元测试
```

---

## 四、部署编排（`src/`）

```
src/
├── docker-compose.yml                  # backend + frontend 两个 service；frontend 依赖 backend
├── docker-compose.override.yml.example # 若需挂载 SSH deploy key 访问私有 git 仓库，拷贝此文件为 .override.yml 后修改
└── README.md                           # 本地开发与容器运行补充说明
```

### 4.1 容器内路径约定

- 后端数据目录：`/app/data`（SQLite 数据库文件）
- 后端仓库副本目录：`/app/repos/<project_id>`（`git clone` 结果）
- 可选共享工作区挂载：由 override 文件定义

### 4.2 环境变量

完整列表见 `src/.env.example`。关键变量：

| 变量 | 默认 | 说明 |
|---|---|---|
| `HALF_SECRET_KEY` | 必填 | JWT 签名密钥，长度 ≥32 |
| `HALF_ADMIN_PASSWORD` | 必填 | 初始 admin 密码，满足强度规则 |
| `HALF_ALLOW_REGISTER` | `false` | 是否允许自助注册 |
| `HALF_STRICT_SECURITY` | `true` | 启动期弱密钥/弱密码是否硬阻断 |
| `HALF_CORS_ORIGINS` | 本地开发默认 | 逗号分隔的 allow-list |

---

## 五、相关文档

- `architecture.md`：系统整体架构、数据模型、API 分组
- `task-lifecycle.md`：运行时机制、状态流转、轮询
- `quickstart.md` / `quickstart.zh-CN.md`：首次启动与排错
- `ui-style.md`：前端设计系统
- FastAPI `/docs`：完整 API 参考（启动后端后访问）
