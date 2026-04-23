# Admin Public Agents Plan

## 评审意见（2026-04-23）

以下是对 plan 的评审结论。和作者 Q&A 对齐后形成的决策、plan 原稿遗漏的代码点、以及实施前必须补充的语义定义，均记录在本节。plan 正文后续应按这些决策修订；在 plan 正文完成同步前，本节内容优先于正文。

### 一、整体判断

方案方向合理，"最小改动 + 按创建者角色推导可见性"的思路可以采纳。但 plan 正文把不少关键点留成了"需要检查"的模糊表述，其中若干是真正的语义决策点和正确性缺口（非实现细节），直接照 plan 原稿实现会留坑。以下决策需固化进 plan 正文后再进入开发。

### 二、已对齐的决策

1. **可见性不对称**：管理员对"普通用户创建的私有 agent"**不可见**；管理员只对"公共 agent 池"有特权。普通用户 `GET /agents` 返回"自己创建 + 管理员创建（即公共）"的并集，管理员 `GET /agents` 返回"自己创建 + 其他管理员创建（即公共）"的并集——均不包含其他普通用户的私有 agent。

2. **公共 agent 状态变更权限只归管理员**：`PUT /{agent_id}`、`PATCH /{agent_id}/status`、`POST /{agent_id}/short-term-reset/reset|confirm`、`POST /{agent_id}/long-term-reset/reset|confirm`、`PUT /reorder`——对公共 agent 一律要求"当前用户即为该 agent 的 `created_by`"，普通用户对公共 agent 纯只读。

3. **`GET /agents` 不跨 owner 触发副作用**：`_normalize_agent_reset_times(..., mark_confirmation=True)` 仅对"当前用户名下的 agent"执行，不对别人创建的公共 agent 跑自动推进 / 翻转 `needs_confirmation`，避免任意登录用户的一次 GET 隐式修改管理员的 agent 行。公共 agent 的 reset 推进由其所有者（管理员）自身访问或独立定时任务负责。

4. **删除/禁用策略**：
   - 无引用（既无其他用户的 project `agent_ids_json`、也无 task `assignee_agent_id`）时，允许管理员硬删除公共 agent；
   - 有任意用户在引用时，禁止硬删除，只允许管理员"禁用"（复用现有 `is_active` 字段，置为 `False`）；
   - 删除前必须跨用户扫描引用（当前 `agents.py::delete_agent` 只扫 `Project.created_by == user.id`，这是一个 plan 完全遗漏的正确性缺口）。

5. **"禁用"（`is_active=False`）语义——软禁用**：
   - 普通用户 `GET /agents` 不返回已禁用的公共 agent；
   - 项目创建/编辑页的 agent 选择面板过滤掉已禁用的公共 agent；
   - 候选池 `agent_ids_json` 已存在的引用保留，前端标记"已停用"灰显；
   - 已在运行的 task 继续跑完；
   - 已存在项目的新 task 解析（`plans.py::_resolve_assignee_agent_id`）**仍可用**，避免突然打断跨用户存量业务；
   - 管理员仍可见已禁用的公共 agent，可重新启用；所有引用自然消化完之后允许硬删。

6. **角色变动 · 降级**：
   - `username = "admin"` 的超级管理员不可降级（`main.py:154` 和 `main.py:371-376` 保证其存在且 role 为 admin）；
   - 其他 admin 被降级时，名下所有 agent 的 `created_by` 迁移至超级管理员，使其继续作为公共 agent 存在；
   - 迁移前必须扫描 `(name, created_by)` 唯一约束冲突（当前 agent name 按创建者隔离；迁移至超级管理员名下时可能与其已有 agent 重名）。一旦有冲突，`PUT /users/{id}/role` 返回 `409` + 冲突列表（`[{agent_id, name, conflicts_with_agent_id}]`），拒绝降级，要求操作者先改名（或改超级管理员那边的）再重试。

7. **角色变动 · 升级**：
   - 普通用户升级为 admin 时，其名下所有私有 agent 会**立即**对全员可见可用，涉及隐式数据暴露（包括 agent 携带的 `subscription_expires_at` 等个人配置）；
   - `PUT /users/{id}/role` 要求显式传 `confirm_publicize_agents=true`，不带则返回 `409` + 即将被公共化的 agent 列表。API 层强制确认，不依赖前端 dialog（避免 CLI / 第三方集成绕过）。

8. **冻结 admin 不影响 agent 语义**：`status=frozen` 只锁账户登录，其名下公共 agent 继续对全员可见可用。如果确实要撤销公共资源，路径是"先降级（走第 6 条的迁移逻辑）再冻结"，两个动作语义分离。

### 三、plan 正文遗漏的代码影响面

plan 正文列的代码点只覆盖了"可见 agent 查询"层面，以下同样必须改，但原稿未列出：

- **`src/backend/routers/agents.py::delete_agent`（第 534-555 行）**：当前跨用户引用扫描缺失。按决策 4，删除前需扫描所有用户的 `Project.agent_ids_json` 和所有 `Task.assignee_agent_id`，有任意引用则改走"只允许禁用"分支。

- **`src/backend/routers/projects.py::_load_owned_agents`（第 181-193 行）**：当前按 `Agent.created_by == user.id` 过滤候选 agent。需改为"可见 agent 集合"过滤（自己 + 管理员创建 + `is_active=True`）。

- **`src/backend/routers/plans.py`**：除 plan 已点到的 `_resolve_assignee_agent_id`（第 163-168 行）外，第 225、340 行同样按 `Agent.created_by == user.id` 过滤，均需改。

- **`src/backend/routers/users.py::update_user_role`（第 70-103 行）**：需要新增：
  - 拦截 `username == "admin"` 的降级；
  - 降级时的 name 冲突预检和 agent 迁移（原子事务）；
  - 升级时的 `confirm_publicize_agents` 强制参数；
  - 相关 `AuditLog` 写入（迁移了哪些 agent / 公共化了哪些 agent）。

- **`src/backend/routers/agents.py::reorder_agents`（第 393-412 行）**：当前按 `Agent.created_by == user.id` 限定，管理员改到的正好是公共 agent 的顺序、普通用户改到的正好是自己私有的顺序——**这个过滤本身不用改**，天然符合"公共 agent 顺序只允许管理员维护、私有 agent 顺序只允许创建者维护"的诉求。但前端组合展示时应按 `(is_public_desc, display_order, id)` 排序，两组各自维护一套顺序，不要互相干扰。

- **`src/backend/routers/agents.py::create_agent`（第 415-435 行）**：同名检查仍按 `(name, created_by)` 做即可，普通用户创建同名 `MyAgent` 和管理员公共 `MyAgent` 在不同创建者下**允许并存**；前端列表分组展示（"公共" / "我的"）就能避免歧义。

- **`src/backend/access.py`**：按 plan 建议新增 `get_visible_agent` / `get_editable_agent` / `list_visible_agents`，以及一个内部辅助 `is_public_agent(agent)`（`agent.created_by.role == "admin"`）；原 `get_owned_agent` / `list_owned_agents` 不要直接删除，改造期保留一段时间以便灰度。

### 四、状态共享语义（plan 未明说，但属于系统约束）

公共 agent 的 `subscription_expires_at`、`availability_status`、`short_term_reset_at`、`long_term_reset_at` 等字段是**全局单值，全员共享**：

- 管理员的订阅额度被所有使用者共同消耗；
- 任一时刻 `availability_status` 只有一个值（如 `quota_exhausted`），所有用户看到同一状态；
- 没有"per-user view"或"per-user quota"概念。

这是"最小改动方案"的一个固有代价，不是缺陷。但 plan 正文应当**显式记录**这一语义，避免未来出现"为什么 Alice 和 Bob 都在用管理员的 agent，只用了半小时就 quota 耗尽"之类的困惑期待。`SECURITY.md` / `docs/architecture.md` 需要新增一段"公共 agent 的额度与状态为全员共享资源"的说明。

### 五、测试覆盖（plan 正文 6 条基础用例 + 以下补充）

- `admin X（非超级管理员）降级时若 agent name 与超级管理员冲突，`PUT /role` 返回 409，不修改任何数据
- 降级无冲突时，agent 成功迁移至超级管理员名下，其他用户仍能看到这些 agent
- `username == "admin"` 降级被拒绝
- 升级为 admin 时若未传 `confirm_publicize_agents`，返回 409 + 待公共化 agent 列表
- 升级带确认参数后，该用户的私有 agent 立即对其他用户可见
- 管理员尝试硬删除被其他用户项目引用的公共 agent，被拒绝
- 管理员"禁用"公共 agent 后：其他用户的 `GET /agents` 不返回；新建项目选择面板看不到；已在运行的 task 不中断；已有项目新 task 解析仍能用
- 普通用户调 `GET /agents` 时，非当前用户所有的公共 agent 不会触发 `_normalize_agent_reset_times` 的 DB 写入副作用（用 mock / 前后对比 `updated_at` 验证）
- 冻结 admin 的公共 agent 仍对全员可见可用

### 六、文档同步

plan 已列 `README.md`、`docs/architecture.md`、`SECURITY.md`。补充要求：

- `SECURITY.md` 中与 "HALF-scoped resources ... authored by admin" 相关表述需同步为"管理员创建 = 公共、普通用户创建 = 私有 + 管理员不可见"；
- 新增章节"Role transitions and resource visibility"说明降级迁移、升级确认、冻结不迁移三条规则；
- 新增章节"Shared state of public agents"说明第四节的状态共享语义。

### 七、实施顺序（对 plan 正文"推荐实施顺序"的修订）

1. 后端 `access.py`：新增 `get_visible_agent / list_visible_agents / get_editable_agent / is_public_agent`
2. 后端 `agents.py`：路由改造（list / detail / update / delete / status / reset 端点的鉴权分叉；`GET /agents` 自动推进只对自己 own 的 agent 执行；`delete_agent` 跨用户引用扫描 + 禁用分支）
3. 后端 `projects.py` / `plans.py`：可见 agent 集合替换原 owner 过滤
4. 后端 `users.py`：降级迁移、升级确认、超级管理员保护、审计日志
5. 前端：分组展示、标记、禁用态 UI、升级 / 降级二次确认
6. 测试：第五节列出的补充覆盖
7. 文档：第六节的同步
8. 上线前的人工审查（plan 正文"数据兼容性"一节的建议保留）

---

## 背景

当前系统中，`Agent` 资源按 `created_by == current_user.id` 做 owner 级隔离：

- 管理员创建的 agent，其他用户看不到
- 普通用户创建的 agent，管理员在应用层接口里也看不到

这与很多团队对“管理员维护公共资源池”的直觉不一致。当前需求希望把 agent 的可见性调整为：

- **管理员创建的 agent：所有登录用户都可见、可使用**
- **普通用户创建的 agent：仅创建者自己可见、可使用**

同时保持修改权限收敛：

- 公共 agent 仍由管理员维护
- 私有 agent 仍由创建者自己维护

## 目标

引入“公共 agent + 私有 agent”两级可见性模型，在不破坏现有项目/任务执行逻辑的前提下，让管理员可以维护一组全员可用的 agent。

## 非目标

- 不引入更细粒度的资源分享（例如按项目分享、按用户组分享）
- 不改变流程模版的权限模型
- 不把普通用户的 agent 暴露给管理员之外的其他普通用户
- 不在本次改动中引入新的角色类型

## 需求定义

### 可见性规则

对任意登录用户：

- 自己创建的 agent 始终可见
- 管理员创建的 agent 始终可见
- 其他普通用户创建的 agent 不可见

### 可使用规则

对任意登录用户：

- 可以在项目创建/编辑、计划生成、任务执行等流程中使用：
  - 自己创建的 agent
  - 管理员创建的 agent

### 可修改规则

- 管理员创建的 agent：
  - 只有管理员可以更新、重排、删除
  - 普通用户只能查看和使用，不能修改
- 普通用户创建的 agent：
  - 只有创建者本人可以更新、重排、删除
  - 其他用户不可见，也无修改权限

## 推荐实现策略

### 方案选择

推荐采用**最小改动方案**：不新增 `visibility` 字段，直接按创建者角色推导可见性。

推导规则：

- `agent.created_by` 对应用户角色是 `admin` → 视为公共 agent
- 否则 → 视为私有 agent

### 选择理由

- 不需要新增数据库列
- 不需要做一次性的 agent 可见性数据迁移
- 与当前需求完全一致
- 后续如果未来要支持更细粒度分享，再独立引入 `visibility` 字段也不迟

### 代价

- 可见性语义绑定在“创建者角色”上，而不是显式字段
- 如果未来管理员角色发生变化，资源语义会变复杂，需要额外规则兜底

## 代码影响面

### 1. 访问控制层

当前文件：

- `src/backend/access.py`

需要改动：

- `get_owned_agent`
- `list_owned_agents`

建议新增一个统一查询条件函数，例如：

- `visible_agent_query(db, user)`

逻辑类似：

- 自己创建的 agent
- 或创建者是管理员的 agent

注意：

- “可见”与“可编辑”应拆开，不要继续把 `get_owned_agent` 同时承担“能看到”和“能修改”两种语义

建议拆成：

- `get_visible_agent(...)`
- `get_editable_agent(...)`

### 2. Agent 路由

当前文件：

- `src/backend/routers/agents.py`

需要检查和调整：

- 列表接口：返回“自己 + 管理员”的 agent
- 详情接口：允许普通用户读取管理员创建的 agent
- 更新 / 删除接口：普通用户不能修改管理员 agent
- 重排接口：只能重排自己可编辑的 agent，不应把管理员公共 agent 混进用户私有排序里

重点风险：

- 当前 `display_order` 如果是单一序列，公共 agent 和私有 agent 混排后，排序语义可能不清晰

建议：

- 公共 agent 与私有 agent 在前端分组显示
- 私有 agent 的拖拽排序只作用于“自己创建的 agent”
- 公共 agent 的顺序只允许管理员维护

### 3. 项目与计划相关路由

当前文件：

- `src/backend/routers/projects.py`
- `src/backend/routers/plans.py`
- `src/backend/routers/process_templates.py`

需要检查：

- 项目创建/编辑时，可选 agent 列表是否只取当前用户自己的 agent
- 计划生成时，参与规划 agent 的可选集合是否要扩展为“自己 + 管理员”
- assignee 解析时，是否仍只在 `created_by == user.id` 的 agent 集合中查找

重点点位：

- `plans.py::_resolve_assignee_agent_id(...)`

这部分需要改成：

- 在“当前用户可见的 agent 集合”中解析 assignee

否则公共 agent 虽然前端可选，但计划 finalize 时仍会解析失败。

### 4. 前端页面

当前文件：

- `src/frontend/src/pages/AgentsPage.tsx`
- `src/frontend/src/pages/ProjectNewPage.tsx`
- `src/frontend/src/pages/PlanPage.tsx`
- 以及相关类型、工具函数

建议改动：

- Agent 总览页把 agent 分成两组：
  - 公共 agent（管理员维护）
  - 我的 agent
- 对公共 agent：
  - 普通用户不显示编辑/删除按钮
  - 管理员可正常维护
- 项目创建页、计划页的 agent 选择卡片支持显示公共来源标记，例如：
  - `公共`
  - `我的`

这能避免用户误以为所有可见 agent 都是自己创建的。

## 权限与安全语义

改动后，系统的 agent 权限语义应明确为：

- Agent 不再是纯 owner 私有资源
- Agent 分为：
  - **公共 agent**：管理员创建，全员可见可用，仅管理员可维护
  - **私有 agent**：普通用户创建，仅自己可见可用，仅自己可维护

这意味着以下文档都需要同步：

- `README.md`（如有说明）
- `docs/architecture.md`
- `SECURITY.md`

尤其是 `SECURITY.md` 里关于“HALF-scoped resources such as agents ... authored by admin”的表述，改动后会和代码重新一致。

## 数据兼容性

### 现有数据的解释

如果按“管理员创建即公共”实现，则历史数据天然可兼容：

- 历史管理员 agent 自动变成公共 agent
- 历史普通用户 agent 继续保持私有

无需额外迁移。

### 风险点

如果历史上管理员创建过一些仅供自己使用、不希望公开的 agent，那么这次改动后它们会变成所有用户可见。

因此上线前建议做一次人工检查：

- 列出当前管理员名下全部 agent
- 确认是否都适合作为公共 agent 暴露给普通用户

如果不适合，则需要在正式上线前：

- 转移 owner
- 或删除这些 agent
- 或改为后续引入显式 `visibility` 字段

## 测试建议

至少补以下测试：

1. 普通用户可以看到管理员创建的 agent
2. 普通用户看不到其他普通用户创建的 agent
3. 普通用户不能更新/删除管理员创建的 agent
4. 普通用户创建项目时可以选择管理员公共 agent
5. 计划 finalize 时可以正确解析管理员公共 agent 作为 assignee
6. 管理员仍可正常维护自己创建的公共 agent

## 推荐实施顺序

1. 后端：抽象“可见 agent”与“可编辑 agent”查询
2. 后端：修正项目/计划相关 agent 解析逻辑
3. 前端：按“公共 / 我的”分组展示 agent
4. 测试：补 owner/visibility 相关覆盖
5. 文档：同步权限模型描述

## 一句话结论

这个需求是合理的，推荐实现。最小可行方案是不新增字段，直接按“管理员创建 = 公共、普通用户创建 = 私有”推导可见性；但上线前应先检查现有管理员名下 agent 是否都适合公开给所有用户。
