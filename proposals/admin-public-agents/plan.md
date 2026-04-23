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
