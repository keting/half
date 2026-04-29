# HALF 用户手册

> **对应版本**：v0.2.x（当前仓库实现）
>  
> 本手册覆盖：
> 1) 快速部署与启动命令  
> 2) 标准使用流程  
> 3) 每个页面的操作方法

---

## 1. 产品定位与边界

HALF 是一个用于多 AI coding agent 协作的任务管理控制台，特点是：

- 基于 Git 协作目录组织任务产物
- 通过 Plan（DAG）编排任务依赖
- 由人手工分发 Prompt 给各个 Agent
- 后端轮询 Git 结果并推进任务状态

HALF **不是** Agent 自动执行器：不会直接替你调用 Claude/Codex/Copilot 等产品接口。

---



## 2. 快速部署（Docker Compose）

### 2.1 前置条件

- Docker 20.10+、Docker Compose v2+
- 可用端口：`3000`（前端）、`8000`（后端）
- 建议至少 2GB 可用内存

#### 2.1.1 Windows部署前置条件

##### 2.1.1.1 Docker Desktop

**Setting - Docker Engine**

```
{
  "builder": {
    "gc": {
      "defaultKeepStorage": "20GB",
      "enabled": true
    }
  },
  "dns": [
    "8.8.8.8",
    "114.114.114.114"
  ],
  "experimental": false
}
```

点击下方`Apply & Restart`

**Setting - General**

勾选`Use the WSL 2 based engine`

##### 2.1.1.2 网络条件

*也可以自己配置下载镜像(不推荐, 尝试过国内两个镜像站均无法完整下载)*

**Clash for Window**

- 启用"允许局域网连接入Clash", "TUN模式", "系统代理"
- 下载并启用"服务模式"
- 在代理页面中选择"规则"

![user-manual-clash-index](D:\code\half\docs\images\user-manual-clash-index.png)

**Docker Desktop - setting - Resources - Proxies**

- 启用"Manual proxy configuration"
- "Web Server(HTTP)"填入`http://host.docker.internal:[你的Clash代理端口, 如上图是20172]`
- "Secure Web Server(HTTPS)"填入`http://host.docker.internal:[你的Clash代理端口, 如上图是20172]`
- "Bypass proxy settings for these hosts && domains"填入`localhost, 127.0.0.1, host.docker.internal, gateway.docker.internal`
- 点击`Apply`

### 2.2 部署与启动命令

在仓库根目录执行：

```bash
cd src
cp .env.example .env
```

> Windows PowerShell 可用：
>
> ```powershell
> cd src
> Copy-Item .env.example .env
> ```

编辑 `src/.env`，至少填写：

```bash
HALF_SECRET_KEY=<随机强密钥>
HALF_ADMIN_PASSWORD=<强密码，至少8位，含大小写字母和数字>
```

Demo试用建议修改，否则可能出现密码强度过低无法启动的问题
```bash
HALF_STRICT_SECURITY=false
```

启动服务：

```bash
docker compose up -d --build
```

查看状态：

```bash
docker compose ps
```

查看日志（排障）：

```bash
docker compose logs backend
docker compose logs frontend
```

访问地址：

- 前端：`http://localhost:3000`
- 后端 API 文档：`http://localhost:8000/docs`

首次登录账号：

- 用户名：`admin`
- 密码：`HALF_ADMIN_PASSWORD` 的值

### 2.3 常用运维命令

停止：

```bash
docker compose down
```

停止并清空数据卷（重置环境）：

```bash
docker compose down -v
```

### 2.4 可选配置

是否加载内置 Demo 项目（默认开启）：

```bash
HALF_DEMO_SEED_ENABLED=true
```

是否允许自注册（默认关闭）：

```bash
HALF_ALLOW_REGISTER=false
```

如需访问私有 Git 仓库，可复制并编辑：

```bash
cp src/docker-compose.override.yml.example src/docker-compose.override.yml
```

然后按注释挂载**专用 deploy key**（不要挂载整个 `~/.ssh`）。

---



## 3. 快速上手（推荐流程）

1. 登录后先打开内置 Demo 项目，理解任务状态、依赖关系和 Prompt 分发方式。  
2. 到“智能体”页确认可用 Agent。  
3. 在“项目”页创建新项目，填写仓库地址、协作目录并选择 Agent。  
4. 进入项目后，在“Plan 规划”页生成计划（模板方式或 Prompt 方式）。  
5. 在“计划修改与执行”页按依赖派发任务。  
6. Agent 将结果写入协作目录并 push 后，HALF 自动轮询更新状态。  
7. 在“执行总结”页查看结果和人工干预记录。

---



## 4. 页面操作指南

### 4.1 登录页（`/login`）

用途：登录、（可选）注册。  
操作：

1. 输入用户名和密码登录。
2. 如果环境开放注册（`HALF_ALLOW_REGISTER=true`），可切换到注册模式创建普通用户。

---

### 4.2 项目页（`/projects`）

用途：查看项目列表、新建项目、进入项目详情。  
操作：

1. 点击“新建项目”进入创建页。
2. 点击项目卡片标题或描述进入项目详情。
3. 点击“编辑”修改项目基础信息。
4. 点击“删除”删除项目（会删除关联任务与计划）。
5. 管理员可见“设置”按钮，进入全局项目参数页。

---

### 4.3 新建/编辑项目页（`/projects/new`、`/projects/:id/edit`）

用途：配置项目元数据、轮询参数和参与 Agent。  
操作：

1. 填写“项目名称”“项目目标”。
2. 填写“Git 仓库地址”和“协作目录”（留空可自动生成默认目录）。
3. 配置轮询参数：
   - 轮询间隔最小/最大值（秒）
   - 启动延迟（分钟/秒）
   - Task 超时（分钟）
4. 选择至少 1 个 Agent（不可用 Agent 不能新增到项目）。
5. 可为已选 Agent 勾选“同服务器”。
6. 点击“创建项目”或“更新项目”。

---

### 4.4 项目详情页（`/projects/:id`）

用途：项目总览、任务队列、执行入口。  
操作：

1. 查看项目概览（状态、仓库、协作目录、项目目标）。
2. 查看执行快照（总任务、待处理、运行中、已完成、需关注、可用 Agent）。
3. 在任务队列里查看四类任务：
   - 准备执行
   - 运行中
   - 阻塞
   - 需关注
4. 点击“手动刷新”拉取最新状态。
5. 用“快捷入口”进入：
   - Plan 页面
   - 任务执行页面
   - 执行总结页面（项目完成后）

---

### 4.5 Plan 规划页（`/projects/:id/plan`）

用途：生成并定稿任务 DAG。  
流程分两种：

#### 4.5.1. 使用模板生成流程

1. 选择“使用模版生成流程”。
2. 选择模板。
3. 完成角色槽位映射（`agent-N` -> 项目内 Agent）。
4. 填写模板要求的输入项（required_inputs）。
5. 点击“下一步”直接生成任务并进入执行页。

#### 4.5.2. 由 Prompt 生成流程

1. 选择“由 Prompt 生成流程”。
2. 选择规划模式（balanced / quality / cost_effective / speed）。
3. 勾选参与规划的 Agent，可选指定模型。
4. 点击“生成 Prompt”（仅生成，不启动轮询）。
5. 点击“拷贝 Prompt”（复制成功后会 dispatch 并启动轮询）。
6. 将 Prompt 粘贴给外部 Agent，让其写回 `plan-<id>.json`。
7. HALF 检测到合法计划后会自动定稿并跳转任务页。

---

### 4.6 计划修改与执行页（`/projects/:id/tasks`）

用途：按 DAG 派发任务与处理异常。  
操作：

1. 左侧 DAG 选择任务节点，右侧查看详情。
2. 对 `pending` 且已解锁任务：
   - 编辑任务名/描述/预期输出/超时（自动保存）
   - 点击“复制 Prompt 并派发”
3. 对 `running` 或 `needs_attention` 任务：
   - 重新派发
   - 手动标记完成
4. 非完成任务可“放弃任务”。
5. 页面支持“手动刷新”触发轮询。

关键规则：

- 前序任务未完成（或未放弃）时，不能派发后继任务。
- 复制 Prompt 失败会中止派发，避免错误提示与实际复制内容不一致。

---

### 4.7 执行总结页（`/projects/:id/summary`）

用途：查看项目交付结果。  
操作：

1. 查看任务结果表（任务码、状态、指派 Agent、输出文件、完成时间）。
2. 点击输出文件路径可复制。
3. 查看人工干预记录（如 manual_complete / redispatch / abandoned）。

---

### 4.8 智能体页（`/agents`）

用途：管理项目可用 Agent。  
操作：

1. 新增智能体：填写名称、类型、模型、订阅到期、重置策略等。
2. 编辑/删除智能体。
3. 拖拽排序智能体卡片，或点击“自动排序”。
4. 在状态徽章上切换状态：
   - 可用
   - 短期重置后可用
   - 长期重置后可用
5. 使用倒计时卡片上的“重置 / 确认”按钮处理重置窗口。

---

### 4.9 流程模版页（`/templates`、`/templates/new`、`/templates/:templateId`、`/templates/:templateId/edit`）

用途：沉淀可复用流程模板。  
操作：

1. 列表页查看模板、进入详情、创建新模板。
2. 新建/编辑流程：
   - 填写基本信息
   - 通过描述生成模板 Prompt（可复制）
   - 粘贴/编辑模板 JSON
   - 预览 DAG
   - 维护角色说明（slot 描述）
   - 配置 required_inputs（字段名、标签、是否必填、是否敏感）
3. 保存后可在 Plan 页复用。

权限：

- 所有登录用户可查看和使用模板；
- 模板创建者和管理员可编辑、删除。

---

### 4.10 项目参数设置页（管理员，`/settings`）

用途：设置全局默认参数。  
操作：

1. 配置全局轮询区间、启动延迟、默认任务超时。
2. 配置规划 Prompt 的“同机分配引导”文案。
3. 点击“保存设置”。

说明：这里修改的是**全局默认值**；项目创建时会快照这些值。

---

### 4.11 智能体设置页（管理员，`/agents/settings`）

用途：维护系统级“Agent 类型 + 模型目录”。  
操作：

1. 新增/编辑/删除 Agent 类型。
2. 为类型添加、编辑、移除模型（名称、别名、能力描述）。
3. 拖拽调整类型和模型顺序。

---

### 4.12 用户管理页（管理员，`/admin/users`）

用途：管理用户账号。  
操作：

1. 查看用户列表（创建时间、最近登录时间/IP、角色、状态）。
2. 调整用户角色（管理员/普通用户）。
3. 冻结或解冻账号。

限制：

- 不能冻结自己。
- 不能把系统最后一个激活管理员降级或冻结。

---



## 5. 任务产物与完成判定

任务目录约定（仓库相对路径）：

- 产物目录：`<collaboration_dir>/<task_code>/`
- 完成哨兵：`<collaboration_dir>/<task_code>/result.json`

建议 Agent 执行顺序：

1. 先写全部产物；
2. 写 `result.json.tmp`；
3. flush 后原子重命名为 `result.json`；
4. `git add && git commit && git push`。

---



## 6. 常见问题速查

1. 无法登录：确认 `.env` 中管理员密码与登录输入一致。  
2. 注册入口不显示：确认 `HALF_ALLOW_REGISTER=true`。  
3. 创建项目时报 Agent 不可用：检查 Agent 订阅状态与可用状态。  
4. 任务长期未完成：确认 Agent 是否将 `result.json` 写入正确目录并 push。  
5. 私有仓库访问失败：按 `docker-compose.override.yml.example` 挂载专用 deploy key。  
6. 启动报安全配置错误：检查 `HALF_SECRET_KEY` 与 `HALF_ADMIN_PASSWORD` 强度。

