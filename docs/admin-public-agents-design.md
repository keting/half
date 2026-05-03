# Agent 公共资源池与私有资源隔离设计

## 背景

当前系统按 `Agent.created_by == current_user.id` 做资源隔离。这个模型能保护用户私有 Agent，但无法支持团队常见的“管理员维护公共 Agent 池，普通用户直接使用”的工作方式。

目标是在不新增数据库 `visibility` 字段的前提下，引入“公共 Agent + 私有 Agent”模型：

- 管理员创建的 Agent 是公共 Agent。
- 普通用户创建的 Agent 是私有 Agent。
- 公共 Agent 对所有登录用户可见、可使用，但仅创建它的管理员可修改。
- 私有 Agent 仅创建者可见、可使用、可修改；管理员也不能查看或接管。

> 说明：当前分支中未找到 `proposals/admin-public-agents/plan.md` 文件；本设计基于现有代码结构和本需求描述编写。

## 当前实现概览

后端关键位置：

- `src/backend/access.py`
  - `get_owned_agent()` 和 `list_owned_agents()` 均只按 `created_by` 查询。
- `src/backend/routers/agents.py`
  - `GET /api/agents` 只返回当前用户创建的 Agent。
  - 更新、状态、重排、重置、确认、删除均复用 `get_owned_agent()`。
  - 删除引用检查只检查当前用户的项目和任务。
- `src/backend/routers/projects.py`
  - 项目创建 / 编辑通过 `_load_owned_agents()` 校验，只能选择自己的 Agent。
- `src/backend/routers/plans.py`
  - 计划 Prompt 生成只按当前用户选择 Agent。
  - `_resolve_assignee_agent_id()` 只在项目 owner 创建的 Agent 中解析 assignee。
- `src/backend/routers/users.py`
  - 管理员升降级、冻结不处理 Agent 资源语义。

前端关键位置：

- `src/frontend/src/types/index.ts`
  - `Agent` 类型没有 `created_by`、`is_public`、`can_edit` 等派生字段。
- `src/frontend/src/pages/AgentsPage.tsx`
  - 列表中所有 Agent 默认可编辑、可改状态、可重置、可确认、可删除、可拖拽重排。
- `src/frontend/src/pages/ProjectNewPage.tsx`
  - 项目创建 / 编辑 Agent 选择依赖 `/api/agents` 返回结果。
- `src/frontend/src/pages/PlanPage.tsx`
  - 计划生成 Agent 选择依赖 `/api/agents` 与项目绑定 Agent。
- `src/frontend/src/pages/UserManagementPage.tsx`
  - 升级 / 降级只提交 `role`，没有公共化确认和降级迁移冲突处理。

## 术语与判定规则

不新增 `agents.visibility` 字段，公共性由创建者角色实时推导：

- `is_public_agent(agent)`：`agent.created_by` 对应的 `User.role == "admin"`。
- `is_private_agent(agent)`：创建者不是管理员。
- `can_view_agent(agent, user)`：
  - `agent.created_by == user.id`，始终可见。
  - 创建者是管理员，且 `agent.is_active == true`，所有登录用户可见。
  - 创建者是管理员，且 `agent.is_active == false`，管理员可见，普通用户不可见。
  - 其他普通用户创建的 Agent 不可见。
- `can_use_agent(agent, user, context)`：
  - 新建项目 / 新建计划选择：必须满足 `can_view_agent` 且 `agent.is_active == true`。
  - 已有项目保留引用：如果 Agent 已经在该项目 `agent_ids_json` 中，允许继续保留并展示，即使公共 Agent 已停用。
  - 后续新 Task 的 assignee 解析：允许解析项目已有引用中的公共 Agent，即使已停用。
- `can_modify_agent(agent, user)`：
  - 只有 `agent.created_by == user.id`。
  - 因为普通用户无法创建公共 Agent，所以普通用户永远不能修改公共 Agent。
  - 非创建者管理员也不能修改、删除、禁用、启用其他管理员创建的公共 Agent。

建议在响应模型中增加派生字段，便于前端做只读和标识：

- `created_by: int | null`
- `owner_role: "admin" | "user" | null`
- `is_public: bool`
- `can_edit: bool`
- `is_disabled_public: bool`

这些字段是 API 输出字段，不是数据库字段。

## 后端设计

### 1. 访问控制集中化

在 `src/backend/access.py` 增加公共查询能力，避免各 router 重复拼条件：

- `admin_user_ids_subquery(db)` 或 `_admin_user_ids_query(db)`
- `agent_visibility_filter(user, include_inactive_public_for_admin=False)`
- `list_visible_agents(db, user, include_inactive_public_for_admin=True)`
- `get_visible_agent(db, agent_id, user, include_inactive_public_for_admin=True)`
- `get_mutable_agent(db, agent_id, user)`
- `load_usable_agents(db, agent_ids, user, allow_keep_ids=None)`
- `is_agent_public(db, agent)` 或批量 owner role map

查询条件建议：

```python
admin_owner_ids = db.query(User.id).filter(User.role == "admin")

visible_for_normal_user = or_(
    Agent.created_by == user.id,
    and_(Agent.created_by.in_(admin_owner_ids), Agent.is_active == True),
)

visible_for_admin = or_(
    Agent.created_by == user.id,
    Agent.created_by.in_(admin_owner_ids),
)
```

这里的 `visible_for_admin` 不包含普通用户私有 Agent，因此满足“管理员不能看到普通用户私有 Agent”。

### 2. `routers/agents.py`

`GET /api/agents`：

- 普通用户：返回自己私有 Agent + 活跃公共 Agent。
- 管理员：返回自己创建的 Agent + 所有管理员创建的 Agent，包括已停用公共 Agent。
- 返回值按 `is_active`、`display_order`、`id` 稳定排序；前端可继续做局部排序。
- 对返回集合执行现有 reset time 归一化。注意公共 Agent 的 reset 字段是共享状态，因此该归一化会影响所有使用者；文档需明确。

修改类接口全部改为 `get_mutable_agent()`：

- `PUT /api/agents/{agent_id}`
- `PATCH /api/agents/{agent_id}/status`
- `POST /short-term-reset/reset`
- `POST /short-term-reset/confirm`
- `POST /long-term-reset/reset`
- `POST /long-term-reset/confirm`
- `DELETE /api/agents/{agent_id}`
- `PUT /api/agents/reorder`

`PUT /api/agents/reorder`：

- 请求体中的每个 id 必须属于当前用户创建的 Agent。
- 不能重排其他管理员创建的公共 Agent。
- 建议只更新请求中的可修改 Agent，返回当前用户可见列表。

`DELETE /api/agents/{agent_id}`：

- 仍要求 `can_modify_agent`。
- 引用检查必须跨所有用户：
  - `tasks.assignee_agent_id == agent_id`
  - 所有 `projects.agent_ids_json` 中包含该 id
  - 可选补充：`project_plans.source_agent_id == agent_id`
  - 可选补充：`project_plans.selected_agent_ids_json` 中包含该 id，用于完整保留计划历史
- 没有任何引用：允许硬删除。
- 有任意引用：
  - 如果 `agent` 是公共 Agent，返回 400，提示只能禁用。
  - 如果 `agent` 是私有 Agent，保持现有“有引用禁止删除”语义。

公共 Agent 禁用：

- 复用 `PUT /api/agents/{agent_id}` 或 `PATCH /status` 之外的 `is_active=false` 更新。
- 仅创建它的管理员可禁用 / 重新启用。
- 普通用户后续 `GET /api/agents` 不再看到它。
- 管理员仍可在 Agent 列表看到它，并可由创建者重新启用。

### 3. `routers/projects.py`

替换 `_load_owned_agents()`、`_validate_owned_agent_assignments()`、`_agent_assignments_from_ids()` 中的 owner-only 查询。

项目创建：

- 用户可选择自己私有 Agent + 活跃公共 Agent。
- 选择已停用公共 Agent 返回 400。
- 选择其他普通用户私有 Agent 返回 400。

项目编辑：

- 新增 Agent 时必须是当前可使用 Agent。
- `allow_keep_ids` 中的既有引用允许保留，即使公共 Agent 已停用。
- 如果用户移除已停用公共 Agent，之后不能再重新添加，除非创建者管理员重新启用。

项目详情：

- `agent_ids_json` 中引用的公共 Agent 即使已停用也保留。
- 后端可选择在项目详情中增加 `inactive_agent_ids` 或前端用 `/api/agents` 附带的管理员可见数据判断；推荐后端在项目详情显式返回引用状态，避免普通用户因 `GET /agents` 不返回停用公共 Agent 而无法标记历史引用。

### 4. `routers/plans.py`

`plan_generate_prompt()`：

- `selected_agent_ids` 校验改为“项目可使用 Agent”：
  - 必须在用户可见可用范围内。
  - 如果 id 属于项目已有引用，允许已停用公共 Agent 继续参与，避免打断存量业务。
  - 如果是新选择且公共 Agent 已停用，拒绝。

`dispatch_plan()`：

- 克隆已完成计划重新生成 prompt 时，重新加载 `selected_agent_ids_json` 对应 Agent。
- 加载规则同上：历史计划使用的项目 Agent 允许保留。

`_resolve_assignee_agent_id()`：

- 当前只按 `owner_user_id` 的自有 Agent 解析，需要改为：
  - 优先在项目已绑定 Agent 集合中解析。
  - 其次在项目 owner 的私有 Agent + 活跃公共 Agent 中解析。
  - 对已有项目后续新 Task，项目已绑定的已停用公共 Agent 仍允许解析。
- 解析优先级保持现有 slug > name > agent_type。
- 如出现公共 Agent 与私有 Agent 同名或同类型，项目已绑定 Agent 优先；否则建议按“自己的私有 Agent 优先于公共 Agent”处理，降低公共池对私有命名习惯的影响。

`finalize_plan_record()`：

- 调用新的 assignee 解析函数时传入 `project`，不要只传 `owner_user_id`。

### 5. `routers/users.py`

#### 管理员降级为普通用户

规则：

- `username == "admin"` 的超级管理员不可降级。
- 其他管理员降级前，其名下所有公共 Agent 自动迁移给超级管理员。
- 迁移前检查 `(name, created_by)` 冲突。
- 如迁移后会与超级管理员现有 Agent 重名，拒绝降级并返回冲突列表。

接口调整：

- `UserRoleUpdateRequest` 可保持 `role` 字段。
- 降级时在事务内执行：
  - 查目标用户。
  - 查超级管理员 `User.username == "admin"`。
  - 查目标管理员 Agent 名称集合。
  - 查超级管理员同名 Agent。
  - 有冲突则 400：

```json
{
  "detail": {
    "message": "Agent name conflicts prevent admin downgrade",
    "conflicts": [
      {"name": "Claude 主力", "target_owner": "old-admin", "new_owner": "admin"}
    ]
  }
}
```

- 无冲突则批量更新 `Agent.created_by = super_admin.id`，再更新用户角色。
- 审计日志记录迁移数量和迁移 Agent id 列表。

#### 普通用户升级为管理员

规则：

- 普通用户升级后，其私有 Agent 立即变为公共 Agent。
- 必须显式确认 `confirm_publicize_agents = true`。
- 未确认时拒绝并返回将公共化的 Agent 列表。

接口调整：

```python
class UserRoleUpdateRequest(BaseModel):
    role: Literal["admin", "user"]
    confirm_publicize_agents: bool = False
```

未确认响应：

```json
{
  "detail": {
    "message": "Promoting this user will publicize their agents",
    "requires_confirmation": true,
    "agents": [{"id": 1, "name": "Codex 本地"}]
  }
}
```

确认后只更新用户角色，不改 Agent owner；公共性由 owner role 推导，角色变更提交后自动生效。

#### 冻结管理员账号

冻结只影响登录，不影响公共 Agent：

- `PUT /status` 不迁移、不禁用、不隐藏该管理员创建的公共 Agent。
- 文档和前端确认文案需说明：冻结管理员不会撤销其公共 Agent。如需撤销公共 Agent，应先降级并触发迁移，再冻结。

## 前端设计

### 1. Agent 类型扩展

`src/frontend/src/types/index.ts` 中扩展 `Agent`：

```ts
created_by: number | null;
owner_role: 'admin' | 'user' | null;
is_public: boolean;
can_edit: boolean;
is_disabled_public: boolean;
```

### 2. Agent 列表页

展示：

- 公共 Agent 显示“公共”标识。
- 私有 Agent 显示“私有”标识。
- 已停用公共 Agent 显示“已停用”标识。

交互：

- `can_edit == false` 时：
  - 禁用编辑、删除、状态切换、短期/长期重置、确认按钮。
  - 禁止拖拽重排。
  - 鼠标提示“公共 Agent 仅创建者可维护”。
- 创建者管理员可以对公共 Agent 禁用 / 重新启用。
- 普通用户看到公共 Agent 时只读，但仍可在项目和计划中选择活跃公共 Agent。

### 3. 项目创建 / 编辑页

- Agent 选择列表使用 `/api/agents` 返回的可见 Agent。
- 活跃公共 Agent 可选。
- 已停用公共 Agent：
  - 新建项目不展示。
  - 编辑已有项目时如果历史已选，需要展示并标记“已停用”，允许保留或移除，但不能新增选择。
- 提交失败中如果后端返回 unavailable ids，继续沿用现有错误展示。

### 4. Plan 页面

- 项目绑定的公共 Agent 可参与计划生成。
- 历史引用的已停用公共 Agent 需要显示“已停用”，但允许继续用于已有项目后续 Task assignee 解析。
- 选择模板角色映射时，已停用但属于项目历史引用的 Agent 可保留；不属于项目的已停用公共 Agent 不展示。

### 5. 用户管理页

升级普通用户为管理员：

- 第一次点击调用接口时如果返回 `requires_confirmation`，弹窗列出将变为公共的 Agent。
- 用户确认后以 `confirm_publicize_agents: true` 重试。

降级管理员为普通用户：

- 如果接口返回冲突列表，展示无法降级及冲突 Agent 名称。
- 对 `username == "admin"` 禁用降级按钮，并提示“超级管理员不可降级”。

冻结管理员：

- 确认文案增加：冻结不会撤销该管理员维护的公共 Agent。

## 数据与约束

不新增 `visibility` 字段，不需要迁移 Agent 表结构。

建议补齐数据库唯一约束：

- 如果当前数据库没有 `(name, created_by)` 唯一约束，而业务已经按该规则做创建校验，建议后续迁移中增加。
- 降级迁移冲突检查以 `(name, created_by)` 为准，即使约束尚未落库，也必须在业务层严格检查。

公共 Agent 共享状态字段：

- `subscription_expires_at`
- `availability_status`
- `short_term_reset_at`
- `short_term_reset_interval_hours`
- `short_term_reset_needs_confirmation`
- `long_term_reset_at`
- `long_term_reset_interval_days`
- `long_term_reset_mode`
- `long_term_reset_needs_confirmation`

这些字段不是 per-user 状态。多个用户使用同一个公共 Agent 时，共享同一份额度、订阅、重置和确认状态。

## 删除与禁用规则

硬删除前必须做跨用户引用检查：

- `Task.assignee_agent_id`
- `Project.agent_ids_json`
- `ProjectPlan.source_agent_id`
- `ProjectPlan.selected_agent_ids_json`

规则：

- 无引用：创建者可硬删除。
- 有引用的公共 Agent：禁止硬删除，只允许创建它的管理员禁用。
- 有引用的私有 Agent：禁止硬删除。
- 已停用公共 Agent 在所有引用自然消化后，创建者可硬删除。

## 测试计划

后端测试建议：

- `test_agent_visibility_public_private.py`
  - 普通用户可见自己 Agent + 活跃公共 Agent。
  - 普通用户不可见其他普通用户 Agent。
  - 管理员不可见普通用户私有 Agent。
  - 管理员可见所有管理员创建的公共 Agent，包括停用项。
- `test_agent_mutation_permissions.py`
  - 普通用户不能更新 / 删除 / 改状态 / 重置 / 确认公共 Agent。
  - 非创建者管理员不能维护其他管理员创建的公共 Agent。
  - 创建者管理员可维护自己的公共 Agent。
- `test_project_public_agent_usage.py`
  - 项目创建 / 编辑可选择活跃公共 Agent。
  - 已停用公共 Agent 不可新增选择。
  - 已有项目历史引用已停用公共 Agent 可保留。
- `test_plan_public_agent_usage.py`
  - 计划 Prompt 可使用公共 Agent。
  - finalize assignee 可解析公共 Agent。
  - 已停用但项目历史引用的公共 Agent 仍可解析。
- `test_agent_delete_disable_references.py`
  - 公共 Agent 被其他用户项目 / 任务引用时禁止硬删除。
  - 无引用时允许硬删除。
  - 有引用时允许创建者管理员禁用。
- `test_user_role_agent_semantics.py`
  - `admin` 超级管理员不可降级。
  - 管理员降级迁移 Agent 给超级管理员。
  - 降级迁移名称冲突时拒绝并返回列表。
  - 普通用户升级未确认时返回将公共化 Agent 列表。
  - 确认后升级成功，Agent 变为公共。
  - 冻结管理员不影响其公共 Agent 可见可用。

前端测试建议：

- Agent 类型契约测试补齐新字段。
- Agent 列表只读公共 Agent 禁用编辑类操作。
- 用户管理升级确认和降级冲突错误展示。
- 项目 / Plan 页面展示公共与停用标识。

## 文档更新

需要更新：

- `SECURITY.md`
  - 说明私有 Agent 不对管理员开放。
  - 说明公共 Agent 由管理员创建并对登录用户可见可用。
  - 说明公共 Agent 修改权限只属于创建者管理员。
- `docs/architecture.md`
  - 增加 Agent 可见性模型。
  - 增加公共 Agent 共享状态语义。
  - 增加删除 / 禁用 / 升降级 / 冻结规则。
- 其他提到 Agent owner-only 隔离的文档同步调整。

## 验收映射

- 管理员创建的 Agent 对所有登录用户可见：由 `list_visible_agents()` 和公共 owner role 推导实现。
- 普通用户创建的 Agent 仅对创建者可见：可见性查询不包含非当前用户的普通 owner。
- 管理员不能看到普通用户私有 Agent：管理员可见条件只包含自己 + 管理员 owner Agent。
- 普通用户不能修改公共 Agent：修改类接口统一 `get_mutable_agent()`。
- 项目和计划流程可使用公共 Agent：项目与计划 Agent 加载改为可使用集合。
- 公共 Agent 删除前跨用户引用检查：删除接口使用全局引用扫描。
- 管理员降级、用户升级、管理员冻结符合规则：`routers/users.py` 事务化处理。
- 公共 Agent 共享状态语义明确：API 响应、前端标识、文档同步说明。

## 实施顺序建议

1. 后端访问控制 helper 和 `AgentResponse` 派生字段。
2. `agents.py` 列表、修改、删除、重排。
3. `projects.py` 和 `plans.py` 可使用 Agent 校验。
4. `users.py` 升级 / 降级 / 冻结语义。
5. 前端类型、Agent 列表只读态、项目和 Plan 选择区。
6. 测试补齐。
7. `SECURITY.md`、`docs/architecture.md` 等文档同步。
