# Admin Public Agents Plan

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
- 不把普通用户的 agent 暴露给管理员或其他普通用户
- 不在本次改动中引入新的角色类型
- 不在本次改动中引入 per-user quota / per-user availability 视图

## 最终语义

### 1. 可见性规则

对任意登录用户：

- 自己创建的 agent 始终可见
- 管理员创建的 agent 始终可见
- 其他普通用户创建的 agent 不可见

这条规则对管理员同样成立：

- 管理员可以看到自己创建的 agent
- 管理员可以看到其他管理员创建的 agent
- 管理员**不能看到**普通用户创建的私有 agent

### 2. 可使用规则

对任意登录用户：

- 可以在项目创建/编辑、计划生成、任务执行等流程中使用：
  - 自己创建的 agent
  - 管理员创建的 agent

### 3. 可修改规则

- **公共 agent（管理员创建）**
  - 所有登录用户可见、可使用
  - 只有创建者本人可以更新、改状态、重排、重置、确认、删除或禁用
  - 普通用户对公共 agent 纯只读

- **私有 agent（普通用户创建）**
  - 只有创建者本人可见、可使用、可修改
  - 管理员也不可见、不可接管

### 4. 公共 agent 的共享状态语义

公共 agent 的以下字段是**全员共享的一份状态**：

- `subscription_expires_at`
- `availability_status`
- `short_term_reset_at`
- `short_term_reset_interval_hours`
- `short_term_reset_needs_confirmation`
- `long_term_reset_at`
- `long_term_reset_interval_days`
- `long_term_reset_mode`
- `long_term_reset_needs_confirmation`

也就是说：

- 多个用户共同使用同一个公共 agent，本质上是在共享同一份额度和状态
- 不存在“每个用户各自拥有一份独立剩余额度”或“每个用户看到不同状态”的语义

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
- 公共 agent 的额度与状态天然为全员共享
- 如果未来管理员角色发生变化，需要额外规则兜底

## 生命周期规则

### 1. 删除与禁用

对公共 agent：

- 如果没有被任何用户引用（既无任意项目 `agent_ids_json` 引用，也无任意任务 `assignee_agent_id` 引用），允许管理员硬删除
- 如果已被任意用户引用，则**禁止硬删除**
- 有引用时，只允许管理员把它设为**禁用**（复用现有 `is_active = false`）

### 2. 禁用语义

公共 agent 被禁用后：

- 普通用户 `GET /agents` 不再返回它
- 项目创建/编辑页的 agent 选择面板不再展示它
- 已经在项目 `agent_ids_json` 里的历史引用保留，前端显示为“已停用”
- 已在运行的 task 继续执行，不被打断
- 已存在项目后续新 task 的 assignee 解析仍可继续使用它，避免存量业务突然中断
- 管理员仍可见该 agent，并可重新启用
- 当所有引用自然消化完后，允许再做硬删除

### 3. 管理员降级

- `username = "admin"` 的超级管理员不可降级
- 其他管理员降级为普通用户时，其名下所有公共 agent 自动迁移给超级管理员
- 迁移前必须检查 `(name, created_by)` 唯一约束冲突
- 如果迁移到超级管理员名下会发生重名冲突，则拒绝降级，并返回冲突列表

### 4. 普通用户升级为管理员

- 普通用户升级为管理员后，其名下私有 agent 会立即变成公共 agent
- 这会导致这些 agent 对所有用户可见可用
- 因此升级接口必须要求显式确认，例如 `confirm_publicize_agents = true`
- 如果未确认，则返回冲突/确认提示，并给出即将被公共化的 agent 列表

### 5. 冻结管理员账号

- 冻结只影响该管理员账号不能登录
- 其名下公共 agent 继续作为公共资源存在，对全员可见可用
- 如果需要撤销公共资源，应通过“先降级、再冻结”的路径处理

## 代码影响面

### 1. 访问控制层

当前文件：

- `src/backend/access.py`

建议新增：

- `is_public_agent(agent)`
- `list_visible_agents(db, user)`
- `get_visible_agent(db, agent_id, user)`
- `get_editable_agent(db, agent_id, user)`

建议语义拆分：

- **可见**：自己创建，或管理员创建
- **可编辑**：当前用户就是该 agent 的 `created_by`

原有 `get_owned_agent` / `list_owned_agents` 不建议继续承担新语义。

### 2. Agent 路由

当前文件：

- `src/backend/routers/agents.py`

需要改动：

- 列表接口：返回“当前用户自己创建 + 管理员创建”的 agent
- 详情接口：允许普通用户读取公共 agent
- 更新接口：公共 agent 只允许创建它的管理员修改
- 状态切换接口：公共 agent 只允许创建它的管理员修改
- 短期/长期 reset / confirm 接口：公共 agent 只允许创建它的管理员执行
- 删除接口：
  - 删除前必须跨用户扫描项目和任务引用
  - 有引用则不允许硬删除，只允许禁用
- `GET /agents` 中如果存在会自动推进 reset 时间或翻转确认标记的逻辑，必须只对“当前用户自己拥有的 agent”执行，不能因为普通用户的一次读取去修改管理员的公共 agent

### 3. 重排逻辑

当前文件：

- `src/backend/routers/agents.py::reorder_agents`

当前按 `Agent.created_by == user.id` 限定的过滤逻辑可保留：

- 管理员维护自己公共 agent 的顺序
- 普通用户维护自己私有 agent 的顺序

前端展示时应分组排序：

- 公共 agent 一组
- 我的 agent 一组

两组顺序互不干扰。

### 4. 项目与计划相关路由

当前文件：

- `src/backend/routers/projects.py`
- `src/backend/routers/plans.py`
- `src/backend/routers/process_templates.py`

需要改动：

- 项目创建/编辑时，可选 agent 列表改成“当前用户可见的 agent 集合”
- 计划生成时，参与规划 agent 的候选集合改成“当前用户可见的 agent 集合”
- assignee 解析逻辑改成在“当前用户可见的 agent 集合”中解析，而不是只在 `created_by == user.id` 中解析

重点点位：

- `projects.py::_load_owned_agents`
- `plans.py::_resolve_assignee_agent_id(...)`
- `plans.py` 里其他直接按 `Agent.created_by == user.id` 过滤的查询

否则公共 agent 即使前端可选，计划 finalize 和后续 task 解析仍会失败。

### 5. 用户角色变更接口

当前文件：

- `src/backend/routers/users.py`

需要改动：

- 禁止降级超级管理员 `username = "admin"`
- 管理员降级时：
  - 预检重名冲突
  - 原子迁移 agent 到超级管理员
  - 写入审计日志
- 普通用户升级为管理员时：
  - 必须显式确认公共化
  - 未确认则返回待公共化 agent 列表
  - 写入审计日志

## 前端影响面

当前文件：

- `src/frontend/src/pages/AgentsPage.tsx`
- `src/frontend/src/pages/ProjectNewPage.tsx`
- `src/frontend/src/pages/PlanPage.tsx`
- 以及相关类型、工具函数

建议改动：

- Agent 总览页按两组展示：
  - 公共 agent
  - 我的 agent
- 对公共 agent：
  - 普通用户不显示编辑/删除/状态变更/reset 操作
  - 管理员正常维护
- 对已停用的历史引用：
  - 在项目和相关页面显示“已停用”标记
- 项目创建页和计划页的 agent 选择卡片增加来源标记，例如：
  - `公共`
  - `我的`
- 升级/降级用户角色的前端交互要配合后端确认与冲突返回

## 数据兼容性

### 现有数据的解释

如果按“管理员创建即公共”实现，则历史数据天然兼容：

- 历史管理员 agent 自动变成公共 agent
- 历史普通用户 agent 保持私有

无需额外迁移。

### 风险点

如果历史上管理员创建过一些仅供自己使用、不希望公开的 agent，那么这次改动后它们会变成所有用户可见。

因此上线前建议做一次人工检查：

- 列出当前管理员名下全部 agent
- 确认是否都适合作为公共 agent 暴露给普通用户

如果不适合，则需要在正式上线前：

- 转移 owner
- 或删除这些 agent
- 或延后采用显式 `visibility` 字段方案

## 测试建议

至少补以下测试：

1. 普通用户可以看到管理员创建的 agent
2. 普通用户看不到其他普通用户创建的 agent
3. 管理员看不到普通用户创建的私有 agent
4. 普通用户不能更新、删除、改状态、重置管理员的公共 agent
5. 项目创建时可以选择公共 agent
6. 计划 finalize 时可以正确解析公共 agent 作为 assignee
7. 管理员删除公共 agent 时会跨用户检查项目和任务引用
8. 公共 agent 被他人引用时，删除被拒绝，只允许禁用
9. 公共 agent 禁用后：
   - 普通用户 `GET /agents` 不返回
   - 新建项目选择面板不显示
   - 已在运行的 task 不受影响
   - 已有项目后续 task 解析仍可继续使用
10. 非超级管理员降级时，若存在重名冲突，返回冲突并拒绝迁移
11. 非超级管理员降级无冲突时，agent 成功迁移到超级管理员名下
12. 超级管理员降级被拒绝
13. 普通用户升级为管理员时，未确认公共化则返回待确认信息
14. 普通用户升级为管理员并确认后，其 agent 立即公共化
15. 冻结管理员账号后，其公共 agent 仍对全员可见可用
16. 普通用户访问 `GET /agents` 时，不会触发对非本人公共 agent 的自动 reset 推进或确认标记写入

## 文档同步

这项改动会改变当前系统的 agent 权限模型，至少需要同步：

- `README.md`（如有资源可见性说明）
- `docs/architecture.md`
- `SECURITY.md`

建议新增或改写的文档点：

- 管理员创建 = 公共 agent，普通用户创建 = 私有 agent
- 管理员对普通用户私有 agent 不可见
- 公共 agent 的额度与状态为全员共享资源
- 角色变动的资源语义：
  - 降级迁移
  - 升级确认公共化
  - 冻结不迁移

## 推荐实施顺序

1. 后端 `access.py`：新增可见/可编辑 agent 查询抽象
2. 后端 `agents.py`：列表、详情、更新、删除、状态变更、reset 相关鉴权和副作用修正
3. 后端 `projects.py` / `plans.py`：把 owner agent 过滤替换为“可见 agent 集合”
4. 后端 `users.py`：实现降级迁移、升级确认、超级管理员保护、审计日志
5. 前端：分组展示、来源标记、禁用态显示、角色变更确认交互
6. 测试：补完上述覆盖
7. 文档：同步权限模型和共享状态语义
8. 上线前人工检查：确认管理员名下历史 agent 是否都适合公共化

## 一句话结论

这个需求合理，推荐实现。最小可行方案是不新增字段，直接按“管理员创建 = 公共、普通用户创建 = 私有”推导 agent 可见性；同时补上删除/禁用策略、角色变动语义、公共 agent 状态共享语义和跨用户引用校验，才能形成一个可上线的完整规则集。
