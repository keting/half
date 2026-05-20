# PRD：Issue 编码与双 Agent 评审循环模板

> **创建日期**：2026-05-15
> **状态**：Draft
> **适用范围**：HALF 流程模板、任务执行、评审结果归档、协作文件状态机与前端同步

---

## 1. 背景

当前 HALF 已支持通过流程模板快速生成固定 Task DAG，并通过 HALF 协作仓库中的任务产物和 `result.json` 追踪任务完成状态。用户希望新增一种标准流程：输入一个 issue URL 后，由一个编码 Agent 完成实现、测试和推送，再由两个评审 Agent 并行评审。只有两个评审都同意合并时，编码 Agent 才提交 PR；若任一评审不同意合并，编码 Agent 需要读取评审意见，判断哪些意见合理并修改代码，然后进入下一轮评审。

该功能的核心价值是把“编码 - 双人评审 - 修改 - 再评审 - PR”的协作闭环沉淀为可复用模板，降低项目负责人手工拆任务、串联评审和判断下一步动作的成本。

---

## 2. 目标

1. 在流程模板中新增“Issue 编码与双 Agent 评审循环”模板。
2. 支持用户在应用模板时填写 issue URL、评审提示词、测试命令、最大评审轮次等必要输入。
3. 由编码 Agent 从用户给定的 issue URL 拉取需求，完成编码、测试、推送到项目仓库新分支。
4. 由两个评审 Agent 并行从项目仓库新分支拉取代码，执行评审并把评审结果提交到 HALF 协作仓库。
5. 流程固定使用 5 个 Task，Task 作为角色槽位复用；实际轮次和业务状态记录在 HALF 协作仓库的 `flow-state.json` 和轮次产物文件中。
6. 系统能够根据两份评审结果中的合并结论决定下一步：
   - 两个评审都同意合并：编码 Agent 提交 PR。
   - 至少一个评审不同意合并：编码 Agent 拉取两份评审意见，修复合理问题并进入下一轮评审。
7. 前端能够通过后端读取 `flow-state.json`，同步展示当前轮次、流程阶段、每个 Task 的业务状态，并据此控制派发按钮。

---

## 3. 非目标

1. 不直接接入 GitHub/GitLab 等平台的私有 Agent API。
2. 不要求 HALF 后端自动调用外部 AI Agent；仍沿用当前“生成 prompt，负责人复制给 Agent”的执行模式。
3. 不在 MVP 中自动判断代码质量或自动合并 PR。
4. 不在 MVP 中替代代码托管平台的权限、分支保护、CI 或 PR 审批能力。
5. 不在 MVP 中要求 HALF 后端 clone 或校验项目代码仓库；项目代码仓库仍由 Agent 在自身执行环境中操作。

---

## 4. 角色与职责

| 角色 | 模板槽位 | 职责 |
|---|---|---|
| 编码 Agent | `agent-1` | 拉取 issue、创建项目分支、编码、编写测试、执行测试、推送代码、根据评审意见修复、最终提交 PR |
| 评审 Agent A | `agent-2` | 拉取项目分支，按评审提示词进行独立评审，提交结构化评审结果 |
| 评审 Agent B | `agent-3` | 拉取项目分支，按评审提示词进行独立评审，提交结构化评审结果 |
| 项目负责人 | 人类用户 | 创建项目、选择模板、映射 Agent、填写输入、派发 prompt、处理异常 |

---

## 5. 模板输入

应用模板时支持以下输入：

| 字段 | 必填 | 说明 |
|---|---|---|
| `issue_url` | 是 | 待实现 issue 的 URL。Agent 需要从该 URL 获取需求内容。 |
| `review_prompt` | 是 | 两个评审 Agent 使用的评审提示词或评审维度。 |
| `test_command` | 否 | 建议执行的测试命令。为空时编码 Agent 根据项目约定自行判断。 |
| `max_review_rounds` | 是 | 最大评审循环次数，默认 3。达到上限仍未通过时进入人工处理。 |

当前版本不提供分支输入项：项目代码仓库固定以 `main` 作为基准分支，工作分支名由编码 Agent 根据 issue 编号和时间自动生成，PR 目标分支固定为 `main`。

项目必须配置：

1. HALF 协作仓库地址 `git_repo_url`。
2. 项目代码仓库地址 `project_repo_url`。若为空，则使用 `git_repo_url` 作为项目代码仓库。
3. 至少 3 个可用 Agent，并完成 `agent-1`、`agent-2`、`agent-3` 的槽位映射。

---

## 6. 用户流程

1. 用户创建或编辑项目，填写 HALF 协作仓库、项目代码仓库、协作目录，并选择至少 3 个 Agent。
2. 用户进入 Plan 页，选择“使用模板生成流程”。
3. 用户选择“Issue 编码与双 Agent 评审循环”模板。
4. 用户完成三个角色槽位映射。
5. 用户填写 `issue_url`、`review_prompt`、`max_review_rounds`，并可选填写 `test_command`。
6. HALF 生成任务流程并进入任务执行页。
7. 项目负责人派发 `TASK-001`，由编码 Agent 拉取 issue、理解需求、生成执行计划，并初始化 `flow-state.json`。
8. `TASK-001` 完成后，前端根据 `flow-state.json` 解锁 `TASK-002`。
9. 项目负责人派发 `TASK-002`，编码 Agent 完成编码、测试用例、测试执行和项目仓库分支推送。
10. `TASK-002` 不直接进入“评审通过”，而是把自身业务状态更新为 `waiting_review`，并解锁 `TASK-003` / `TASK-004`。
11. 项目负责人并行派发 `TASK-003` / `TASK-004`，两个评审 Agent 各自写入本轮评审结果。
12. 两个评审结果都提交后，后端读取 `flow-state.json` 和两份评审文件，派生出 `TASK-005 = unlocked`；前端据此冻结 `TASK-003` / `TASK-004`，解锁 `TASK-005`。
13. 项目负责人派发 `TASK-005`，编码 Agent 读取两份评审结果并做决策：
    - 均同意合并：`TASK-002` 业务状态变为 `approved`，`TASK-005` 提交 PR 并完成流程。
    - 任一不同意合并：`TASK-002` 重新变为 `unlocked`，`TASK-003` / `TASK-004` / `TASK-005` 暂时冻结，编码 Agent 回到 `TASK-002` 进行下一轮修复。
14. 每一轮修复、评审、决策都追加写入新的轮次目录，不覆盖旧轮次产物。
15. 流程在以下任一条件结束：
    - 两个评审 Agent 同意合并，编码 Agent 提交 PR 成功。
    - 达到最大评审轮次仍未通过，流程进入 `needs_attention`，等待人工处理。
    - 任一任务超时、产物缺失或结果格式非法，按现有任务异常机制处理。

---

## 7. 流程状态机

### 7.1 状态事实源

本流程不通过新增数据库表保存循环状态。流程运行状态以 HALF 协作仓库中的 `<collaboration_dir>/flow-state.json` 作为事实源。后端在轮询或手动刷新时同步协作仓库，并读取该文件返回给前端。

评审 Agent 不直接修改 `flow-state.json`，避免两个评审并行写同一个文件导致冲突。推荐写入规则：

| 写入方 | 允许写入 |
|---|---|
| `TASK-001` | 初始化 `flow-state.json`，写入计划结果 |
| `TASK-002` | 更新轮次、工作分支、commit、测试结果，把自身置为 `waiting_review`，解锁两个评审 |
| `TASK-003` | 只写自己的 `review.json` / `review.md` |
| `TASK-004` | 只写自己的 `review.json` / `review.md` |
| `TASK-005` | 读取两份评审结果，更新决策、解锁修复或提交 PR |

后端读取流程状态时，不只返回 `flow-state.json` 的原始内容，还需要结合当前轮次下的评审文件派生有效状态。例如：当 `TASK-003/reviews/round-XXX/review.json` 和 `TASK-004/reviews/round-XXX/review.json` 都存在且合法时，即使 `flow-state.json.task_states.TASK-005` 仍是 `frozen`，后端也应在 API 返回中派生 `TASK-005 = unlocked`、`phase = awaiting_decision`。后端 `dispatch` / `redispatch` 校验也应使用派生后的有效状态。

多轮评审必须做目录隔离，避免上一轮产物干扰当前轮判断。后端和 `TASK-005` 只能读取 `flow-state.json.current_round` 对应的目录：

```text
TASK-003/reviews/round-<current_round>/review.json
TASK-004/reviews/round-<current_round>/review.json
```

不得扫描历史目录来寻找“最新”评审结果。每一轮还必须使用 `round_id`、`current_round`、`work_branch`、`head_commit` 四个锚点校验产物是否属于当前轮次。

### 7.2 流程阶段

`flow-state.json.phase` 可取以下值：

| 阶段 | 说明 |
|---|---|
| `planning` | `TASK-001` 正在拉取 issue、理解需求、生成计划 |
| `coding` | `TASK-002` 正在实现 issue 或修复上一轮评审意见 |
| `awaiting_review` | `TASK-002` 已提交代码并等待两个评审 |
| `reviewing` | `TASK-003` / `TASK-004` 至少一个评审仍未完成 |
| `awaiting_decision` | 两个评审都已提交结果，等待 `TASK-005` 决策 |
| `needs_fix` | 决策不通过，等待 `TASK-002` 修复 |
| `approved` | 两个评审都通过，`TASK-002` 已评审通过 |
| `pr_submitting` | `TASK-005` 正在提交 PR |
| `completed` | PR 已提交，流程完成 |
| `needs_attention` | 达到最大轮次或出现不可自动推进的问题 |

### 7.3 Task 业务状态

`flow-state.json.task_states` 用于控制前端展示和派发按钮：

| 状态 | 说明 |
|---|---|
| `frozen` | 当前不允许派发该 Task |
| `unlocked` | 允许项目负责人复制 prompt 并派发 |
| `running` | 该 Task 已派发，正在执行 |
| `waiting_review` | 仅用于 `TASK-002`，表示代码已提交，等待评审 |
| `waiting_decision` | 等待 `TASK-005` 做评审决策 |
| `needs_fix` | 评审未通过，等待编码 Agent 修复 |
| `approved` | 仅用于 `TASK-002`，表示两个评审都同意合并 |
| `completed` | 该 Task 的流程职责完成 |
| `needs_attention` | 需要人工处理 |

### 7.4 `flow-state.json` 最小结构

```json
{
  "schema_version": 1,
  "flow_type": "issue_code_review_loop",
  "current_round": 1,
  "round_id": "round-001-abc123",
  "phase": "awaiting_review",
  "work_branch": "issue-123-fix-login",
  "head_commit": "abc123",
  "max_review_rounds": 3,
  "task_states": {
    "TASK-001": "completed",
    "TASK-002": "waiting_review",
    "TASK-003": "unlocked",
    "TASK-004": "unlocked",
    "TASK-005": "frozen"
  },
  "reviews": {
    "round": 1,
    "TASK-003": {
      "status": "pending",
      "approve_merge": null,
      "review_path": null
    },
    "TASK-004": {
      "status": "pending",
      "approve_merge": null,
      "review_path": null
    }
  },
  "decision": {
    "round": 1,
    "status": "pending",
    "approved": null,
    "reason": null,
    "decision_path": null
  },
  "pr": {
    "status": "not_started",
    "url": null
  },
  "updated_by_task": "TASK-002",
  "updated_at": "2026-05-15T00:00:00Z"
}
```

### 7.5 合并判断规则

1. 只有当两个评审任务都已完成且评审结果均可解析时，才进入合并判断。
2. 每份评审结果必须包含布尔字段 `approve_merge`。
3. `TASK-005` 只允许读取当前轮次目录下的两份 `review.json`，不得读取或回退到历史轮次目录。
4. 每份 `review.json` 必须满足：
   - `round_id == flow-state.json.round_id`
   - `round == flow-state.json.current_round`
   - `work_branch == flow-state.json.work_branch`
   - `head_commit == flow-state.json.head_commit`
5. 当且仅当两份评审结果的 `approve_merge` 都为 `true` 时，流程进入提交 PR 阶段。
6. 只要任一 `approve_merge` 为 `false`，流程进入修复阶段。
7. 若评审结果缺失、JSON 非法、缺少 `approve_merge` 或任一锚点不匹配，该评审任务不得视为完成，任务进入 `needs_attention`。
8. 若当前轮次已达到 `max_review_rounds` 且仍未满足合并条件，流程进入 `needs_attention`，提示项目负责人人工处理。

---

## 8. 任务设计

### 8.1 固定 Task 形态

本流程不预先展开每一轮评审，也不在运行中动态新增 Task。模板固定生成 5 个 Task，Task 表示角色槽位，真实轮次由协作仓库产物记录。

| 任务 | 指派 | 依赖 | 说明 |
|---|---|---|---|
| `TASK-001` | 编码 Agent | 无 | 拉取 issue、理解需求、生成执行计划、初始化 `flow-state.json` |
| `TASK-002` | 编码 Agent | `TASK-001` | 编码、修复、编写测试、执行测试、推送工作分支；可被多轮复用 |
| `TASK-003` | 评审 Agent A | `TASK-002` | 评审槽位 A；每一轮只写自己的评审产物 |
| `TASK-004` | 评审 Agent B | `TASK-002` | 评审槽位 B；每一轮只写自己的评审产物 |
| `TASK-005` | 编码 Agent | `TASK-003`, `TASK-004` | 评审决策与 PR 提交；不通过则解锁 `TASK-002` 进入下一轮 |

说明：

1. `TASK-002` 的业务状态不是简单的 `completed`，而是在 `flow-state.json` 中区分 `unlocked`、`waiting_review`、`needs_fix`、`approved`。
2. `TASK-003` / `TASK-004` 在每轮评审完成后冻结，直到 `TASK-002` 提交下一轮新 commit 后再次解锁。
3. `TASK-005` 只有在两个评审结果都存在且可解析时解锁。
4. 该模板的业务解锁不应只依赖数据库中的 `Task.status = completed`。`TASK-002` 在等待评审时还不能算“评审通过”，但 `TASK-003` / `TASK-004` 已经可以派发；因此前端和后端派发校验必须以 `flow-state.json` 及派生状态为准。
5. `result.json` 仍可作为该角色槽位最终完成的归档哨兵，但每一轮的中间完成状态由 `flow-state.json`、`branch.json`、`review.json`、`decision.json` 表达。

### 8.2 业务流转

```text
TASK-001 计划
   ↓
TASK-002 编码 / 修复
   ↓
TASK-002 waiting_review
   ↓
TASK-003 评审 A + TASK-004 评审 B
   ↓
TASK-005 决策
   ├─ 两个评审都通过 -> TASK-002 approved -> TASK-005 提交 PR -> completed
   └─ 任一评审不通过 -> TASK-002 unlocked -> 下一轮修复
```

### 8.3 前端派发控制

前端在任务页读取后端返回的流程状态，并按 `task_states` 控制按钮：

| Task 状态 | 前端行为 |
|---|---|
| `unlocked` | 显示并允许“复制 Prompt 并派发” |
| `frozen` | 禁用派发按钮，显示冻结原因 |
| `waiting_review` | 显示“等待评审”，禁用编码派发 |
| `waiting_decision` | 显示“等待决策”，只允许派发 `TASK-005` |
| `needs_fix` | 显示“需修复”，允许重新派发 `TASK-002` |
| `approved` | 显示“评审通过”，禁用 `TASK-002` 派发 |
| `completed` | 显示完成状态 |

后端在 `dispatch` / `redispatch` 时也应读取 `flow-state.json` 和当前轮次产物，按派生后的有效状态校验目标 Task 是否允许派发，避免用户绕过前端直接调用接口派发冻结任务。

---

## 9. 产物契约

### 9.1 协作仓库目录结构

推荐目录结构：

```text
<collaboration_dir>/flow-state.json

<collaboration_dir>/TASK-001/
  issue-summary.md
  implementation-plan.md
  result.json

<collaboration_dir>/TASK-002/
  rounds/
    round-001/
      branch.json
      implementation.md
      test-report.md
    round-002/
      branch.json
      fix-summary.md
      review-response.md
      test-report.md

<collaboration_dir>/TASK-003/
  reviews/
    round-001/
      review.json
      review.md

<collaboration_dir>/TASK-004/
  reviews/
    round-001/
      review.json
      review.md

<collaboration_dir>/TASK-005/
  decisions/
    round-001/
      decision.json
      decision.md
  pr.json
  pr.md
```

目录名必须由 `flow-state.json.current_round` 派生，推荐使用三位补零格式 `round-001`、`round-002`。进入新一轮时，编码 Agent 必须创建新的轮次目录，不得覆盖上一轮目录。

### 9.2 编码任务产物

编码 Agent 必须在 HALF 协作仓库当前任务目录写入：

| 文件 | 说明 |
|---|---|
| `rounds/round-XXX/implementation.md` 或 `fix-summary.md` | 本轮实现或修复摘要 |
| `rounds/round-XXX/test-report.md` | 本轮测试命令、结果和失败说明 |
| `rounds/round-XXX/branch.json` | 项目仓库分支信息 |
| `result.json` | 可选。仅在 `TASK-002` 被 `TASK-005` 标记为 `approved` 后用于归档该角色槽位最终完成状态 |

`branch.json` 建议格式：

```json
{
  "round": 1,
  "round_id": "round-001-abc123",
  "project_repo_url": "https://github.com/example/project.git",
  "base_branch": "main",
  "work_branch": "issue-123-fix-login",
  "head_commit": "abc123",
  "tests": [
    {
      "command": "pytest",
      "status": "passed",
      "summary": "128 passed"
    }
  ],
  "pr_url": null
}
```

### 9.3 评审任务产物

每个评审 Agent 必须在 HALF 协作仓库当前任务目录写入：

| 文件 | 说明 |
|---|---|
| `reviews/round-XXX/review.json` | 结构化评审结果 |
| `reviews/round-XXX/review.md` | 面向人类阅读的详细评审意见 |
| `result.json` | 可选。仅在流程最终完成时用于归档评审角色槽位最终完成状态 |

`review.json` 必须包含：

```json
{
  "round": 1,
  "round_id": "round-001-abc123",
  "reviewer": "agent-2",
  "work_branch": "issue-123-fix-login",
  "head_commit": "abc123",
  "approve_merge": false,
  "summary": "发现 2 个阻塞问题，需要修改后再合并。",
  "findings": [
    {
      "severity": "blocking",
      "file": "src/example.py",
      "line": 42,
      "title": "缺少错误分支处理",
      "detail": "当接口返回空响应时会抛出未捕获异常。",
      "recommendation": "补充空响应处理和对应测试。"
    }
  ],
  "tested": [
    {
      "command": "pytest tests/test_example.py",
      "status": "passed",
      "summary": "3 passed"
    }
  ]
}
```

字段规则：

1. `round_id`、`round`、`work_branch`、`head_commit` 必须与 `flow-state.json` 当前值一致。
2. `approve_merge` 为必填布尔值。
3. `findings[].severity` 可选值为 `blocking`、`major`、`minor`、`nit`。
4. 只要存在 `blocking` 级别问题，`approve_merge` 必须为 `false`。
5. `approve_merge = false` 时，`findings` 不得为空。
6. `file` 和 `line` 应尽量指向具体代码位置；无法定位时可以为空，但必须在 `detail` 中说明原因。

### 9.4 决策与 PR 产物

`TASK-005` 在每轮决策时必须写入：

| 文件 | 说明 |
|---|---|
| `decisions/round-XXX/decision.json` | 结构化决策结果 |
| `decisions/round-XXX/decision.md` | 对两份评审意见的汇总与下一步说明 |
| `result.json` | 可选。仅在 PR 已提交或流程进入终止状态时用于归档 `TASK-005` 最终完成状态 |

当两个评审都同意合并时，编码 Agent 必须提交 PR 并在当前任务目录写入：

| 文件 | 说明 |
|---|---|
| `pr.json` | PR URL、目标分支、标题、提交 commit |
| `pr.md` | PR 描述正文 |
| `result.json` | 流程最终完成后的归档哨兵 |

`pr.json` 建议格式：

```json
{
  "project_repo_url": "https://github.com/example/project.git",
  "work_branch": "issue-123-fix-login",
  "target_branch": "main",
  "pr_url": "https://github.com/example/project/pull/456",
  "title": "Fix login error handling",
  "head_commit": "def456"
}
```

`decision.json` 建议格式：

```json
{
  "round": 1,
  "round_id": "round-001-abc123",
  "approved": false,
  "review_a_approve_merge": false,
  "review_b_approve_merge": true,
  "next_action": "fix",
  "reason": "评审 A 发现阻塞问题，需要修复后重新评审。",
  "next_round": 2
}
```

---

## 10. Prompt 要求

### 10.1 编码 Agent Prompt

编码 Agent 的任务 prompt 必须明确要求：

1. 开始前同步 HALF 协作仓库和项目代码仓库。
2. 从 `issue_url` 获取 issue 内容，并在产物中记录 issue 摘要。
3. 固定以项目代码仓库 `main` 分支作为基准分支，并由 Agent 根据 issue 编号和时间自动生成工作分支名。
4. 完成代码修改和必要测试。
5. 执行 `test_command`；若为空，则根据项目约定选择合理测试命令。
6. 只有测试通过且代码已经 push 到项目仓库后，才允许写入本轮 `branch.json` 并把 `flow-state.json` 更新为 `awaiting_review`。
7. 若处于修复轮次，必须读取两个评审任务的 `review.json` / `review.md`，逐条判断意见是否合理。
8. 对拒绝采纳的评审意见必须给出具体理由。
9. 不得在两个评审都同意合并前提交 PR。
10. 开始执行前必须读取 `flow-state.json`；如果 `TASK-002` 当前不是 `unlocked` 或 `needs_fix`，必须停止并说明原因。
11. 完成编码或修复后必须更新 `flow-state.json`：设置最新 `current_round`、`round_id`、`work_branch`、`head_commit`，将 `TASK-002` 置为 `waiting_review`，将 `TASK-003` / `TASK-004` 置为 `unlocked`，将 `TASK-005` 置为 `frozen`。
12. 每一轮必须写入新的 `round-XXX` 目录，不得覆盖或复用上一轮目录。

### 10.2 评审 Agent Prompt

评审 Agent 的任务 prompt 必须明确要求：

1. 开始前同步 HALF 协作仓库和项目代码仓库。
2. 从当前轮次的 `TASK-002/rounds/round-XXX/branch.json` 读取 `round_id`、`work_branch` 和 `head_commit`。
3. 基于用户填写的 `review_prompt` 独立评审。
4. 必须检查代码正确性、测试覆盖、回归风险、可维护性和需求匹配度。
5. 必须输出 `review.json`，并明确 `approve_merge`。
6. 不得依赖另一名评审 Agent 的结论。
7. 只有评审产物写完后，才允许将本轮评审视为已提交。
8. 开始执行前必须读取 `flow-state.json`；如果自己的 Task 不是 `unlocked`，必须停止并说明原因。
9. 评审 Agent 不得修改 `flow-state.json`，只允许写入自己 Task 目录下的本轮评审产物。

### 10.3 决策 Agent Prompt

`TASK-005` 仍由编码 Agent 执行，但 prompt 必须明确它此时承担“评审决策与 PR 提交”职责：

1. 开始前读取 `flow-state.json`；如果 `TASK-005` 不是 `unlocked`，必须停止并说明原因。
2. 只读取 `TASK-003` / `TASK-004` 当前轮次目录下的两份 `review.json`；若任一评审文件缺失、非法或锚点不匹配，必须停止并说明原因。
3. 若任一评审不同意合并，写入 `decision.json` / `decision.md`，更新 `flow-state.json` 为 `needs_fix`，解锁 `TASK-002`，冻结 `TASK-003` / `TASK-004` / `TASK-005`。
4. 若两个评审都同意合并，先把 `TASK-002` 标记为 `approved`，再以 `main` 作为目标分支提交 PR，写入 `pr.json` / `pr.md`，最后把流程标记为 `completed`。
5. 若达到 `max_review_rounds` 且仍未通过，写入人工处理报告，将流程标记为 `needs_attention`。

---

## 11. 前端同步需求

### 11.1 同步链路

前端不直接读取或写入 Git 仓库文件。同步链路为：

```text
Agent 更新协作仓库文件
        ↓
HALF 后端轮询 / 手动刷新时同步协作仓库
        ↓
后端读取并解析 <collaboration_dir>/flow-state.json 和当前轮次产物
        ↓
前端调用 API 获取流程状态
        ↓
页面更新阶段、轮次、Task 业务状态和按钮可用性
```

### 11.2 API 需求

新增或扩展一个读取流程状态的接口：

```text
GET /api/projects/:id/flow-state
```

接口返回 `flow-state.json` 的解析结果、结合当前轮次产物派生后的有效状态，以及文件缺失、JSON 非法、schema 不匹配等错误信息。最小返回字段：

```json
{
  "exists": true,
  "valid": true,
  "current_round": 2,
  "round_id": "round-002-def456",
  "phase": "awaiting_review",
  "derived_phase": "awaiting_review",
  "work_branch": "issue-123-fix-login",
  "head_commit": "def456",
  "task_states": {
    "TASK-002": "waiting_review",
    "TASK-003": "unlocked",
    "TASK-004": "unlocked",
    "TASK-005": "frozen"
  },
  "effective_task_states": {
    "TASK-002": "waiting_review",
    "TASK-003": "unlocked",
    "TASK-004": "unlocked",
    "TASK-005": "frozen"
  },
  "pr": {
    "status": "not_started",
    "url": null
  }
}
```

### 11.3 页面展示

任务执行页需要展示：

1. 当前流程阶段，例如 `awaiting_review`、`needs_fix`、`completed`。
2. 当前评审轮次。
3. 当前工作分支和最新 commit。
4. 两个评审 Agent 的本轮状态和评审结论。
5. `TASK-002` 的业务状态：待编码、等待评审、需修复、评审通过。
6. `TASK-005` 的业务状态：等待评审完成、可决策、PR 已提交。
7. PR URL。

### 11.4 派发约束

前端和后端都必须按 `task_states` 控制派发：

1. `unlocked`：允许派发。
2. `frozen`：禁止派发。
3. `waiting_review`：禁止派发 `TASK-002`，允许派发已解锁评审。
4. `needs_fix`：允许派发 `TASK-002`。
5. `approved`：禁止再次派发 `TASK-002`。
6. `completed`：禁止再次派发流程内 Task，除非用户显式重新打开流程。

---

## 12. HALF 产品能力需求

### 12.1 MVP 必需能力

1. 允许新增一个 `agent_count = 3` 的流程模板。
2. 模板支持声明 `issue_url`、`review_prompt`、`test_command`、`max_review_rounds` 等 `required_inputs`；当前版本不声明分支相关输入。
3. 任务 prompt 中能注入模板输入。
4. 模板固定生成 5 个 Task，并在任务描述中明确每个 Task 的角色槽位语义。
5. 后端能读取 `<collaboration_dir>/flow-state.json` 并提供给前端。
6. 前端能展示流程阶段、当前轮次、工作分支、评审结果和 PR URL。
7. 前端能根据 `task_states` 禁用或启用派发按钮。
8. 后端能在 `dispatch` / `redispatch` 时校验目标 Task 在派生有效状态中是否允许派发。
9. 评审任务能通过协作仓库读取当前轮次的 `branch.json`。
10. 任务结果页能展示每轮编码、评审、决策和 PR 产物路径。

### 12.2 推荐增强能力

1. 新增结构化产物校验：对 `review.json`、`branch.json`、`pr.json` 做 schema 校验。
2. 对 `flow-state.json` 做 schema 校验，并在前端展示具体错误。
3. 在任务页为 `TASK-002`、`TASK-003`、`TASK-004`、`TASK-005` 提供轮次历史视图。
4. 在 `TASK-005` 决策后自动触发一次项目状态刷新。
5. 提供人工修正 `flow-state.json` 的管理员工具，用于处理冲突或异常状态。

---

## 13. 异常处理

| 场景 | 期望处理 |
|---|---|
| issue URL 无法访问 | 编码任务进入 `needs_attention`，产物中记录失败原因 |
| 项目仓库无法拉取或推送 | 对应任务进入 `needs_attention`，提示检查权限、网络和分支保护 |
| 测试失败 | 编码 Agent 不得把 `flow-state.json` 推进到 `awaiting_review`，应输出失败日志并等待人工处理或修复 |
| 评审结果 JSON 非法 | 评审任务不应视为完成，进入 `needs_attention` |
| `flow-state.json` 缺失 | 前端显示流程状态未初始化，只允许派发 `TASK-001` |
| `flow-state.json` JSON 非法或 schema 不匹配 | 前端显示状态文件错误，所有流程 Task 派发进入保护性禁用，等待人工修复 |
| 用户尝试派发 frozen Task | 前端禁用；后端 dispatch 校验拒绝并返回当前 Task 有效业务状态 |
| 评审意见冲突 | 编码 Agent 必须逐条回应两份意见；合理意见应修复，不合理意见应说明拒绝理由 |
| 达到最大评审轮次仍未通过 | 流程进入 `needs_attention`，输出人工处理报告 |
| PR 创建失败 | PR 任务进入 `needs_attention`，记录失败原因和可重试步骤 |

---

## 14. 权限与安全

1. Agent 对项目代码仓库的 clone、push、PR 创建权限由用户在 Agent 执行环境中配置。
2. HALF 不保存项目仓库访问令牌。
3. 协作仓库中的评审意见可能包含代码片段或安全问题描述，应遵循项目已有访问控制。
4. Prompt 中必须提醒 Agent 不要把密钥、令牌、私有凭据写入协作产物。
5. 分支名应避免包含空格、控制字符、shell 特殊字符和路径穿越片段。
6. 评审 Agent 不得修改 `flow-state.json`，避免并行写入造成覆盖或冲突。
7. 后端读取 `flow-state.json` 时必须复用现有安全路径校验，禁止绝对路径、反斜杠和 `..` 越界路径。

---

## 15. 验收标准

1. 用户可以在流程模板列表中看到“Issue 编码与双 Agent 评审循环”模板。
2. 模板要求 3 个 Agent，并能完成 `agent-1`、`agent-2`、`agent-3` 的角色映射。
3. 用户应用模板时必须填写 `issue_url`、`review_prompt` 和 `max_review_rounds`，可选填写 `test_command`。
4. 应用模板后固定生成 `TASK-001` 到 `TASK-005` 五个 Task。
5. `TASK-001` prompt 中包含 issue URL，并要求生成计划和初始化 `flow-state.json`。
6. `TASK-002` prompt 中包含项目代码仓库、固定 `main` 基准分支、自动工作分支策略、测试要求和 `flow-state.json` 更新规则。
7. `TASK-002` 完成编码后，前端能显示 `TASK-002 = waiting_review`，并解锁两个评审任务。
8. 两个评审任务 prompt 中包含同一工作分支、同一 commit、同一评审提示词，并要求输出 `approve_merge`。
9. 两个评审结果都提交后，后端能派生 `TASK-005 = unlocked`，前端能显示该状态，并冻结 `TASK-003` / `TASK-004`。
10. 当任一评审不同意合并时，`TASK-005` 能更新 `flow-state.json`，使 `TASK-002 = unlocked`，并进入下一轮修复。
11. 当两个评审都同意合并时，`TASK-005` 能将 `TASK-002` 标记为 `approved`，提交 PR，并在 HALF 协作仓库记录 PR URL。
12. 前端能通过后端接口同步展示 `phase`、`current_round`、`work_branch`、`head_commit`、`task_states` 和 PR URL。
13. 后端和 `TASK-005` 只读取当前 `round-XXX` 目录下的评审结果，历史轮次评审文件不会影响当前轮判断。
14. `review.json` 的 `round_id`、`round`、`work_branch`、`head_commit` 与 `flow-state.json` 不一致时，不得解锁 `TASK-005`。
15. 前端和后端都能阻止派发 `frozen` 状态的 Task。
16. 达到最大评审轮次仍未通过时，流程进入人工处理状态，并保留完整评审与修复记录。

---

## 16. 待确认问题

1. PR 创建方式是否只通过编码 Agent 在其环境中执行，还是未来由 HALF 提供 Git 平台集成。
2. 评审意见是否需要在 HALF 前端做结构化展示，还是 MVP 仅展示产物文件路径。
3. 是否需要为不同项目预置多套 `review_prompt` 模板。
4. `flow-state.json` 是否需要支持人工修正操作，以及该操作是否仅限管理员。
