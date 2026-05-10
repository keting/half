# HALF 用户手册（页面版）

[English](./user-manual.md) | [简体中文](./user-manual.zh-CN.md)

> **对应版本**：v0.2.x（当前仓库实现）
>
> 本文档仅说明“每个页面做什么、在页面里怎么操作”，不包含部署/启动/环境变量内容（请参考 `quickstart.zh-CN.md`）。

---

## 1. 阅读说明

- 本手册按页面拆分，适合给最终用户或项目负责人按图操作。
- 每个页面都包含：**页面用途**、**进入方式**、**操作步骤**、**截图**。

---

## 2. 页面操作指南

### 2.1 登录页（`/login`）

**页面用途**

- 进行账号登录。
- 在开放注册时创建新账号。

**进入方式**

- 访问系统入口地址后自动进入登录页。

**操作步骤**

1. 输入用户名和密码，点击登录。
2. 若页面提供“注册”切换入口（由系统配置控制，例如 `HALF_ALLOW_REGISTER=true`），可切换到注册表单创建普通账号。

---

### 2.2 项目列表页（`/projects`）

![user-manual-projects-list-page](./images/user-manual-projects-list-page.png)

**页面用途**

- 查看所有项目。
- 进入项目详情。
- 发起新建、编辑、删除项目操作。

**进入方式**

- 登录后默认进入，或从导航栏进入“项目”。

**操作步骤**

1. 点击“新建项目”进入创建页。
2. 点击项目卡片标题/描述进入对应项目详情。
3. 点击“编辑”修改项目信息。
4. 点击“删除”移除项目（会同步移除关联计划与任务）。
5. 所有用户均可通过“通知设置”入口配置个人飞书通知；管理员还可在此调整全局项目参数。

---

### 2.3 新建项目页（`/projects/new`）

**页面用途**

- 配置项目基本信息。
- 选择参与执行的 Agent。
- 配置轮询与超时等运行参数。

**进入方式**

- 从项目列表点击“新建项目”。

**操作步骤**

1. 填写项目名称、项目目标。
2. 填写 Git 仓库地址和协作目录（留空可走默认目录策略）。若使用私有仓库，请先按 `quickstart.zh-CN.md` 完成 GitHub 访问配置（SSH key 或令牌）。
3. 设置轮询参数（轮询间隔、启动延迟、任务超时）。
4. 选择至少 1 个可用 Agent。
5. 按需为已选 Agent 勾选“同服务器”。
6. 点击“创建项目”提交。

![user-manual-project-create-page](./images/user-manual-project-create-page.png)

---

### 2.4 编辑项目页（`/projects/:id/edit`）

**页面用途**

- 修改已有项目配置与参数。

**进入方式**

- 从项目列表点击目标项目的“编辑”。

**操作步骤**

1. 进入编辑页后，按需修改项目名称、项目目标、仓库地址、协作目录。
2. 按需调整轮询参数和 Agent 分配设置。
3. 点击“更新项目”提交修改。

![user-manual-project-edit-page](./images/user-manual-project-edit-page.png)

---

### 2.5 项目详情页（`/projects/:id`）

**页面用途**

- 作为单项目总览页查看当前执行状态。
- 快速跳转到计划、任务执行、执行总结页面。

**进入方式**

- 从项目列表点击目标项目进入。

**操作步骤**

1. 查看项目基础信息（状态、仓库、协作目录、项目目标）。
2. 查看执行快照（总任务、待处理、运行中、已完成、需关注）。
3. 查看任务队列（就绪/运行中/阻塞/需关注）。
4. 点击“手动刷新”同步最新状态。
5. 使用页面快捷入口跳转 Plan、任务页、总结页。

![user-manual-project-detail-page](./images/user-manual-project-detail-page.png)

---

### 2.6 Plan 规划页（`/projects/:id/plan`）

**页面用途**

- 生成并定稿任务 DAG（依赖图）。
- 支持“模板生成”和“Prompt 生成”两条路径。

![user-manual-plan-page-overview](./images/user-manual-plan-page-overview.png)

**进入方式**

- 从项目详情页进入“Plan 规划”。

**操作步骤（模板路径）**

1. 选择“使用模板生成流程”。
2. 选择模板并完成角色槽位映射（`agent-N` -> 项目 Agent）。
3. 填写 `required_inputs`。
4. 点击“下一步”生成任务并进入执行页。

![user-manual-plan-template-mode](./images/user-manual-plan-template-mode.png)

**操作步骤（Prompt 路径）**

1. 选择“由 Prompt 生成流程”。
2. 选择规划模式（`balanced / quality / cost_effective / speed`）。
3. 勾选参与规划的 Agent，按需指定模型。
4. 点击“生成 Prompt”。
5. 点击“拷贝 Prompt”后，将内容发送给外部规划 Agent。
6. 待系统检测到合法 `plan-<id>.json` 后自动定稿并跳转任务页。

![user-manual-plan-prompt-mode](./images/user-manual-plan-prompt-mode.png)

---

### 2.7 计划修改与执行页（`/projects/:id/tasks`）

**页面用途**

- 按 DAG 依赖关系派发任务。
- 在执行中处理异常任务（重派发、人工完成、放弃）。

**进入方式**

- 从项目详情或 Plan 完成后进入任务执行页。

**操作步骤**

1. 在左侧 DAG 选中任务节点，右侧查看任务详情。
2. 对已解锁的 `pending` 任务，点击“复制 Prompt 并派发”。
3. 对 `running` 或 `needs_attention` 任务，执行“重新派发”或“手动标记完成”。
4. 对不再继续的未完成任务执行“放弃任务”。
5. 点击“手动刷新”同步状态。

**关键规则**

- 前序任务未完成（或未放弃）时，后继任务不可派发。
- Prompt 复制失败时，派发会中止，避免提示与实际内容不一致。

![user-manual-tasks-page](./images/user-manual-tasks-page.png)

---

### 2.8 执行总结页（`/projects/:id/summary`）

**页面用途**

- 查看项目交付结果和人工干预记录。

**进入方式**

- 从项目详情页点击“执行总结”。

**操作步骤**

1. 查看任务结果表（任务码、状态、Agent、输出文件、完成时间）。
2. 点击输出文件路径进行复制。
3. 查看人工干预记录（`manual_complete`、`redispatched`、`abandoned`）。

![user-manual-summary-page](./images/user-manual-summary-page.png)

---

### 2.9 智能体页（`/agents`）

**页面用途**

- 管理系统中可参与项目的 Agent。

**进入方式**

- 从导航栏进入“智能体”。

**操作步骤**

1. 新增 Agent（名称、类型、模型、订阅到期、重置策略等）。
2. 编辑或删除已有 Agent。
3. 通过拖拽或“自动排序”调整卡片顺序。
4. 通过状态徽章切换可用状态。
5. 对 `chatgpt-pro` Agent，可在卡片上完成 OpenAI OAuth 登录并刷新 Codex 额度。

![user-manual-agents-page](./images/user-manual-agents-page.png)

---

### 2.10 流程模板页（`/templates`、`/templates/new`、`/templates/:templateId`、`/templates/:templateId/edit`）

**页面用途**

- 沉淀并复用标准流程模板。

**进入方式**

- 从导航栏进入“流程模板”。

**操作步骤**

1. 在列表页查看模板并进入详情。
2. 新建/编辑模板时维护基本信息、模板 JSON、角色说明和 `required_inputs`。
3. 保存后可在 Plan 页直接复用。

**权限说明**

- 所有登录用户可查看和使用模板。
- 模板创建者与管理员可编辑/删除模板。

![user-manual-templates-page](./images/user-manual-templates-page.png)

---

### 2.11 设置页（`/settings`）

**页面用途**

- **所有登录用户**：配置个人飞书（Feishu）Webhook 通知。
- **管理员额外可见**：调整全局项目轮询参数与规划 Prompt 设置。

**进入方式**

- 所有用户均可从项目列表页右上角的“通知设置”入口进入；管理员入口文字显示为“设置”。

**操作步骤（飞书通知）**

1. 在“飞书通知”区块填入个人机器人 Webhook URL。
   - URL 格式：`https://open.feishu.cn/open-apis/bot/v2/hook/<token>`
   - 留空表示当前账户不接收飞书通知。
2. 勾选需要接收通知的事件类型：
   - **任务完成**（`completed`）：任务轮询识别到完成时触发。
   - **任务超时**（`timeout`）：任务超过设定时间未完成时触发。
   - **项目完成**（`project_completed`）：项目所有任务均完成时触发。
3. 点击“保存设置”。

**操作步骤（全局参数，仅管理员可见）**

1. 设置全局轮询区间、启动延迟、默认任务超时。
2. 设置规划 Prompt 的同机分配引导文案。
3. 点击“保存设置”。

**说明**

- 飞书通知是**按账户隔离**的：每位用户只收到自己创建的项目/任务产生的通知。
- 推送失败（网络异常或 Webhook 无效）仅记录警告日志，**不会中断后台轮询**。
- 全局轮询参数是全局默认值；项目创建时会快照这些参数，此后修改不追溯影响既有项目。

![user-manual-project-settings-page](./images/user-manual-project-settings-page.png)

---

### 2.12 智能体设置页（管理员，`/agents/settings`）

**页面用途**

- 维护系统级 Agent 类型和模型目录。

**进入方式**

- 管理员从导航或设置入口进入“智能体设置”。

**操作步骤**

1. 新增、编辑、删除 Agent 类型。
2. 在类型下新增、编辑、删除模型（名称、别名、能力说明）。
3. 拖拽调整类型与模型顺序。

![user-manual-agent-settings-page](./images/user-manual-agent-settings-page.png)

---

### 2.13 用户管理页（管理员，`/admin/users`）

**页面用途**

- 管理用户角色与账号状态。

**进入方式**

- 管理员从导航或后台入口进入“用户管理”。

**操作步骤**

1. 查看用户列表（创建时间、最近登录、角色、状态）。
2. 调整用户角色（管理员/普通用户）。
3. 冻结或解冻账号。

**限制**

- 不能冻结自己。
- 不能降级或冻结系统最后一个激活管理员。

![user-manual-user-management-page](./images/user-manual-user-management-page.png)

---

## 3. 最小闭环：Git 回写与完成判定

为了让任务从“执行中”进入“已完成”，Agent 应遵循以下最小闭环：

1. 将任务产物写入目录：`<collaboration_dir>/<task_code>/`
2. 所有产物写完后，最后写入（并提交）`<collaboration_dir>/<task_code>/result.json` 作为完成哨兵
3. 将本次变更 `git add`、`git commit`、`git push`
4. HALF 后端轮询检测到 `result.json` 后，任务状态推进为完成，并可在“执行总结”页查看结果

说明：`result.json` 是完成信号文件，应在其他产物准备好后最后落盘并提交。
