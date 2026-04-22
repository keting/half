# 任务生命周期与运行时机制

> **对应版本**：v0.1.0
> 本文档说明 HALF 的运行时模型：项目 / 计划 / 任务三者关系、计划生成、任务执行、状态流转、`result.json` 契约、轮询机制和 Agent 可用性跟踪。以代码为事实源头；文档与代码不一致时，代码为准。

---

## 一、Project / Plan / Task 三者关系

```
Project（1）
   │
   ├── ProjectPlan（N 个 candidate + 1 个 final）
   │      │
   │      └── finalize 后 ──► Task（按 plan_json 创建一批 task）
   │
   └── Tasks（来自已 finalize 的 final plan，形成 DAG）
```

- **Project**：一个使用 HALF 协调的协作单元。关联唯一 git 仓库 + 参与 Agent 列表 + 协作目录 + 轮询参数快照。
- **ProjectPlan**：一个项目可有多个候选计划（`plan_type = candidate`），最终由 finalize 步骤选定一个为 `final`。计划承载了任务 DAG 的 JSON 原文、生成它的 prompt、轮询状态、用量开关等元数据。
- **Task**：计划 finalize 后从 `plan_json.tasks[]` 派生。每个 task 绑定一个 `assignee_agent_id` + 依赖列表 + 状态 + 预期输出说明 + 超时时间快照。

**计划来源有两种**（在 `ProjectPlan.source_path` 上区分）：

| source_path 形式 | 含义 |
|---|---|
| `<collaboration_dir>/plan-<plan_id>.json` | Prompt 路径生成的计划，通过 git 轮询等待 agent 回写 |
| `template:<template_id>` | 流程模版路径生成的计划，应用模版即 finalize，**不走 git 轮询** |

轮询服务在遇到 `template:` 前缀的 `source_path` 时**直接跳过**，避免把模版来源误判为 git 路径。

---

## 二、计划生成流程

项目创建后，用户进入 `/projects/:id/plan` 选择流程来源。

### 2.1 路径 A：由 Prompt 生成计划（让 agent 规划）

1. **选择 Agent 和模式**：用户勾选本轮参与规划的 Agent，可选地为每个 Agent 指定模型（未指定时系统按 `planning_mode` + 模型能力描述自动匹配）。`planning_mode` 可选 `balanced` / `quality` / `cost_effective` / `speed`。
2. **生成 Prompt**：点击"生成 Prompt"，前端先通过 `PUT /api/projects/:id` 保存任务介绍和 `planning_mode`，然后调用 `POST /api/projects/:id/plans/generate-prompt`。后端：
   - 查找可复用的 pending candidate plan（同项目、`plan_type=candidate`、`status=pending`、未派发、未检测、未选中、无 `plan_json`），若存在则复用其 `id/source_path`，只更新 prompt 输入和派生字段；否则创建新记录
   - 生成规划 prompt：身份句 + 参与 Agent 说明（含模型选择、同服务器标记） + `planning_mode` 策略段 + 同机分配引导 + 输出格式要求
   - 返回 prompt 文本（**不启动轮询**）
3. **拷贝 Prompt 并派发**：用户点击"拷贝 Prompt"，前端同步把 prompt 写入剪贴板（剪贴板写入必须在点击的同步执行栈内完成，见 `architecture.md` 第 3.5 节）。写入成功后调用 `POST /api/projects/:id/plans/:planId/dispatch`，后端把计划推进到 `running` 并启动后台轮询。
4. **Agent 执行规划**：用户手工把 prompt 粘贴给对应 agent；agent 按 prompt 要求输出结构化 JSON 并写回 `<collaboration_dir>/plan-<plan_id>.json`，`git commit`、`git push`。
5. **轮询命中并 finalize**：后端轮询命中文件 → 解析 JSON（允许有限自动修复：去 markdown 围栏、尾逗号修正） → 写入 `plan_json` → 状态推进到 `completed` → 前端自动调用 `POST /api/projects/:id/plans/finalize` 把它定为 `final` 并创建 tasks → 自动跳转 `/projects/:id/tasks`。
6. **超时**：若超过设定时间（默认 30 分钟）仍未检测到合法 JSON，计划进入 `needs_attention`，提示负责人手工检查 agent 是否已发送。

**重复点击"生成 Prompt"**：同一个未派发的 candidate 周期内，重复点击复用同一条记录和同一个 `plan-<id>.json` 路径，只更新 prompt 内容、Agent 选择和模型选择。这样负责人已经交给外部 agent 的旧 prompt 里的文件路径不会失效。

**状态灯**：黄灯（pending / needs_attention）、红灯（running）、绿灯（completed / final）。红灯时 Plan 页显示从本次会话点击"拷贝 Prompt"开始的计时器（`00:00:00` 起始，不自动续接历史计时）。

### 2.2 路径 B：使用流程模版生成计划

1. **选择模版**：用户从流程模版列表选一个。"可用模版"只按 agent 数量判定：`project.agent_ids.length >= template.agent_count`。
2. **槽位映射**：把模版中的抽象角色槽位（`agent-1`、`agent-2`）映射到项目内的具体 Agent。映射必须完整、无重复。每个槽位下方展示角色说明（从模版的 `agent_roles_description_json` 读取）。
3. **填写必需输入**：若模版声明了 `required_inputs`（如"研究主题"、"评审维度"），Plan 页渲染对应表单；必填字段为空时禁用"下一步"。
4. **应用模版**：点击"下一步"后，前端先 `PUT /api/projects/:id` 保存 `{ goal, template_inputs }`（**不保存** `planning_mode`），然后 `POST /api/process-templates/:templateId/apply/:projectId`。后端：
   - 清理同项目下旧的未选中候选计划
   - 把模版中的 `agent-N` 替换为映射后的项目 Agent slug
   - 创建 `source_path = template:<template_id>` 的已完成候选计划
   - 立刻 finalize 为 `final` plan 并创建 tasks
   - 前端跳转 `/projects/:id/tasks`

**不经 git 轮询**：模版路径直接在 HALF 后端完成 finalize，不需要 agent 回写任何文件。

---

## 三、任务执行流程

Finalize 后，`/projects/:id/tasks` 页面按 DAG 展示任务，右侧选中任务时展示详情和操作按钮。

### 3.1 任务状态

| 状态 | 含义 | 负责人可执行动作 |
|---|---|---|
| `pending` / 待派发 | 任务已创建未派发 | 复制 Prompt 并派发 |
| `running` / 执行中 | 已派发，开始计时，后台轮询中 | 等待、手动刷新 |
| `completed` / 已完成 | 检测到 `result.json` 或手动标记 | 查看结果、继续后续任务 |
| `needs_attention` / 需人工处理 | 超时未回写、git 读取失败等 | 重新派发、手动标记完成、标记放弃 |
| `abandoned` / 已放弃 | 负责人主动标记 | 仅查看；**终态不可重开** |

### 3.2 派发约束

- 前序依赖必须全部 `completed` 或 `abandoned`，否则"复制 Prompt 并派发"和"放弃任务"按钮 disabled
- **HALF 页面不检查前序输出文件是否真实存在**——这个检查发生在 agent 自己的执行环境中：派发的 prompt 强制要求 agent 先执行 `git pull` 再检查前序文件
- 前序为 `abandoned` 时，后继任务视为已解除阻塞，不要求前序存在输出文件

### 3.3 派发的原子性（重要实现细节）

"复制 Prompt 并派发 / 重新派发"按钮必须保证**剪贴板 / 按钮提示 / 后端派发记录三者同步**：

1. **预取**：`TaskDetailPanel` 在选中或刷新一个处于 `pending / needs_attention / running` 的任务时，立即后台调用 `POST /api/tasks/:taskId/generate-prompt` 把最新 prompt 缓存到组件 state。任务的 `task_name / description / expected_output_path / status` 任一变化都会重新预取。若有未保存草稿或刚保存但列表未回刷，`cachedPrompt` 立刻失效，按钮变成 "Prompt 准备中..." 且 disabled。
2. **同步写剪贴板**：用户点击时 `performDispatch` 在任何 `await` 之前**直接调用** `copyText(cachedPrompt, navigator.clipboard)`。
3. **失败必须显式中止**：`copyText` 抛错或返回 false（权限被拒、activation 失效等）时必须 `alert` 并 return，**不得**继续调用 `/dispatch` 或 `/redispatch`。
4. **落库**：复制成功后才调用 `POST /api/tasks/:taskId/dispatch` 或 `/redispatch`（纯 DB 写，不触发远端 IO）。

背景：浏览器要求 `navigator.clipboard.writeText` 在 transient user activation 期内调用。如果 `await` 网络请求再写剪贴板，activation 已失效会被静默拒绝。这是历史 bug "task 切换后剪贴板里残留上一个 task prompt" 的根因。

### 3.4 派发的执行 Prompt 结构

```
你是项目 [项目名称] 的执行 Agent。

## 项目任务介绍              ← project.goal 非空时才出现
{goal 去首尾空白后的原文}

## 模版所需信息              ← 仅 task 来自流程模版且 project.template_inputs 有对应值时出现
- {label}: {value}

## 执行前置步骤（必须先做）
1. 在开始本任务前，必须先在项目仓库目录执行 `git pull`...
2. 确认上述前序任务输出文件已经存在...

## 任务信息
- 任务码：TASK-XXX
- 任务名称：...
- 任务描述：...

## 前序任务输出
{前序任务的固定输出目录列表}

## 输出要求
1. 将所有产出文件写入目录：{collaboration_dir}/{task_code}/
2. 所有产出文件写完后，最后生成 result.json
3. 先写入 result.json.tmp，确认 flush 后原子重命名为 result.json
4. result.json 至少包含：task_code / summary / artifacts
5. 完成后执行 git add / commit / push

6. {可选} 在 {collaboration_dir}/{task_code}/usage.json 中写入当前剩余用量信息
```

Prompt 模板的具体填充逻辑在 `services/prompt_service.py` 中；具体模板内容由三个 generate-prompt 端点返回，不在本文档复述。

### 3.5 任务编辑与 prompt 预取的前端约束

若负责人刚修改了任务的 `task_name / description / expected_output`，前端必须**先完成自动保存并基于最新服务端数据重新生成 prompt**，才允许点击派发。在新 prompt 预取完成前，派发按钮保持 disabled，避免旧 prompt 与最新任务文本不一致。

---

## 四、`result.json` 完成契约

HALF 的任务完成契约收敛为**固定任务目录 + `result.json` 哨兵**：

### 4.1 路径约定

| 文件 | 路径 |
|---|---|
| 任务真实产物 | `<collaboration_dir>/<task_code>/` 下任意文件 |
| 完成哨兵 | `<collaboration_dir>/<task_code>/result.json` |
| 可选用量文件 | `<collaboration_dir>/<task_code>/usage.json` |

**所有路径均为仓库根相对**，不得以 `/` 开头。HALF 在创建和更新项目时会 strip 前后斜杠；`services.path_service._safe_join` 在文件操作前再次做防御。

### 4.2 为什么要"先写所有产物、最后原子写 `result.json`"

避免轮询命中半写状态。流程：

1. Agent 把所有真实产物写进任务目录
2. 把 `result.json` 先写为 `result.json.tmp`
3. 确认写入 + flush
4. 原子 `rename` 成 `result.json`
5. `git add && commit && push`

### 4.3 `result.json` 建议字段

```json
{
  "task_code": "TASK-001",
  "summary": "本次任务的简要结果描述",
  "artifacts": ["outputs/proj-.../TASK-001/xxx.md", "..."]
}
```

`task_code / summary / artifacts` 为推荐字段；HALF 当前不强制校验 `result.json` 的 schema，**只校验其存在性**作为完成信号。

### 4.4 `usage.json`（可选）

勾选"输出剩余用量"时，prompt 会要求 agent 额外写入 `usage.json`，格式由 agent 自行决定（HALF 只读取、不强制格式）。

---

## 五、Git 轮询机制

### 5.1 轮询间隔与延迟启动

- **间隔**：可配置随机间隔（全局默认 15-30 秒，支持项目级覆盖）
- **启动延迟**：可配置（全局默认 0 秒，支持项目级覆盖）
- **项目级快照**：创建项目时快照当前全局默认，此后全局变更不追溯影响既有项目
- **前端补充**：进入页面、窗口重聚焦、用户点击"手动刷新"时额外拉取一次；焦点/可见性刷新做 2 秒节流

### 5.2 读取顺序

轮询读取按以下顺序尝试：

1. **本地仓库副本**（`/app/repos/<project_id>` 下的后端维护副本）
2. **共享工作区**（若部署挂载了该目录，且其 `git remote origin` 与项目仓库地址一致）
3. **远端跟踪分支快照**（`origin/HEAD` 指向的分支上的同路径文件）

这样即使结果文件尚未 `push` 到远端，只要写进了当前工作区，就能被检测到；反过来，即使本地缓存仓库分叉、无法 fast-forward，也能读到其他机器 push 的结果。

### 5.3 `ensure_repo_sync` 同步策略（`services/git_service.py`）

轮询前唯一允许的同步入口：

- **TTL 复用**：同一项目在 TTL 窗口内复用最近一次同步结果，避免同一 polling interval 内重复 `git fetch`
- **有限次重试 + 指数退避**：`git fetch origin` 遇到网络抖动时
- **`git pull --ff-only` 失败不会被吞掉**：以 warning 返回给 `poll_project`
- **优先用 `origin/HEAD` 快照**：fetch 成功后使用远端快照读取，避免本地脏工作树

### 5.4 错误传播规则

- `git fetch / clone` 等远端不可达的同步失败 → 任务/计划保留 `running` 状态，写入 `last_error`，**跳过本轮 timeout 判定**；**不得伪装成 "result not found"**
- `git fetch` 成功但 `git pull --ff-only` 因分叉失败 → 只记录 `logger.warning`，**不写入 `last_error`**，**不创建 `error` 类型 `TaskEvent`**，继续执行结果检测；若结果仍未出现且超过超时时间，正常进入 `needs_attention`
- 检测到 `result.json` → 任务推进到 `completed`
- 任务超时未检测到 → 首次从 `running` 转入 `needs_attention` 时写入 `timeout` 事件；**后续重复检测不重复写 timeout 事件**
- `needs_attention` 状态任务**继续参与轮询**；若后续检测到 `result.json`，自动恢复为 `completed` 并清除 `last_error`
- 手动标记完成 → 任务状态变为 `completed` 并清除 `last_error`

### 5.5 任务超时时间

| 来源 | 用途 |
|---|---|
| `global_settings.task_timeout_minutes` | 全局默认（默认 10 分钟，范围 1-120） |
| `projects.task_timeout_minutes` | 项目级默认（项目创建时快照全局值） |
| `tasks.timeout_minutes` | 每个 task 自己的超时（finalize 时快照项目级） |

Task 处于 `pending` 状态可编辑 `timeout_minutes`；`running / needs_attention / completed / abandoned` 后不可编辑。轮询判定用 `polling_service.get_effective_task_timeout_minutes`，兜底顺序为 Task 值、项目默认、全局默认、10 分钟。

---

## 六、信息共享机制

每个任务的产物写进**独立的固定目录**，避免并发写冲突：

- Task A 写 `<collaboration_dir>/TASK-001/`
- Task B 写 `<collaboration_dir>/TASK-002/`

后续任务的 prompt 中列出前序任务的**固定输出目录**，agent 执行任务时直接从本地 git 仓库读取前序目录下的文件。HALF 不负责在前端检查"前序输出是否真实存在"——这个检查发生在 agent 自己的执行环境。

---

## 七、Agent 可用性跟踪

HALF 跟踪每个 Agent 的**订阅到期**和**重置窗口**，避免规划把任务分给不可用的 agent。

### 7.1 四状态模型

| 状态 | 触发/切换方式 |
|---|---|
| **available**（可用） | `availability_status = available` 且 `subscription_expires_at > now` |
| **short_reset_pending**（短期重置后可用） | 用户手动切换；读取 `short_term_reset_at` 显示倒计时 |
| **long_reset_pending**（长期重置后可用） | 用户手动切换；读取 `long_term_reset_at` |
| **unavailable**（不可用） | **派生状态**，不存储；由 `subscription_expires_at <= now` 实时推导 |

四状态切换只修改 `availability_status` 字段，不影响模型、能力、重置策略等其他字段（`PATCH /api/agents/:id/status`）。订阅已过期时切换到 `available` 会被拒绝。

### 7.2 自动续推 + 确认按钮

若 Agent 同时设置了`重置时间`和`重置间隔`，到期后**自动顺延一轮**：

- 短期到期 → 自动更新为"原时间 + 短期间隔（小时）"
- 长期到期 → 自动更新为"原时间 + 长期间隔（天）"

自动续推发生时，后端把 `*_reset_needs_confirmation` 置为 `true`，前端倒计时下方出现两个按钮：

- **重置**（黄色底色）：把对应重置时间改为"当前北京时间 + 对应间隔"，清除确认标记
- **确认**：不修改时间，只清除确认标记

**联动**：点击长期重置的"重置"按钮时，若 Agent 同时设置了短期重置时间和间隔，则**一并重置短期**。反之点击短期重置不影响长期。

用户手动编辑对应重置时间或重置间隔 → 后端立即清除确认标记，前端隐藏按钮。

### 7.3 时区约束

Agent 的 `short_term_reset_at` / `long_term_reset_at` 与系统其他时间字段不同，以"北京时间无时区 datetime"**直接存储**，前端也按存储值直接格式化，**不再做二次时区换算**。这是历史版本把北京时间误当 UTC 存储导致分钟偏移的修复结果。系统启动时有一次性迁移，把已有旧值统一 `+8 hours` 回写。

### 7.4 长期重置模式

`long_term_reset_mode` 支持两种：

- **`days`**（默认）：每隔 N 天重置一次
- **`monthly`**：每月同一天同一时间重置；当月无对应日期时（如 31 日）取当月最后一天

---

## 八、异常与人工介入

### 8.1 任务状态触发条件详表

| 状态 | 触发条件 | 界面展示 | 负责人可执行动作 |
|---|---|---|---|
| **待派发** | 任务已创建未派发 | 灰灯 | 复制 Prompt 并派发 |
| **执行中** | 已派发，轮询中 | 红灯 | 等待、手动刷新 |
| **已完成** | 检测到 `result.json` 或手动标记 | 绿灯 | 查看结果、继续后续任务 |
| **需人工处理** | 超时 / 回写格式错误 / git 读取失败 | 黄灯 + 原因提示 | 重新派发、手动标记完成、标记放弃 |
| **已放弃** | 负责人主动标记 | 灰灯 + 删除线 | 仅查看（终态） |

### 8.2 复制 Prompt 后的容错

若负责人点击"复制 Prompt 并派发"后超过设定时间（默认 5 分钟）仍未检测到任何 git 变更，系统提示"是否已将 Prompt 发送给 Agent？"供负责人确认或重新操作。

### 8.3 重新派发

通过 `POST /api/tasks/:taskId/redispatch`：

- 接受的源状态：`needs_attention` / `running` / `abandoned`
- 前端调用前会先 `generate-prompt` 并复制到剪贴板，再调本接口
- 服务端将原 `last_error` 归档到 `redispatched` 事件 `detail` 后清空

---

## 九、执行汇总

所有任务完成或终止后，`/projects/:id/summary` 页面展示：

- 各任务当前状态
- 各任务产出文件链接
- 人工介入记录（来自 `task_events`）
- 最终项目结果摘要

MVP 以页面展示为主，**不生成结构化报告文档**。

---

## 十、相关文档

- `architecture.md`：系统整体架构、数据模型概览、API 面概览
- `project-structure.md`：代码组织导览
- FastAPI `/docs`（`http://localhost:8000/docs`）：完整 API 签名
