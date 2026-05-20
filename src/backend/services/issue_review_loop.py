import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from models import ProcessTemplate, Project, ProjectPlan
from services import git_service


FLOW_TYPE = "issue_code_review_loop"
TEMPLATE_NAME = "Issue 编码与双 Agent 评审循环"
TASK_CODES = ["TASK-001", "TASK-002", "TASK-003", "TASK-004", "TASK-005"]
BUSINESS_DISPATCHABLE_STATES = {"unlocked", "needs_fix"}
DEFAULT_REVIEW_PROMPT = """# 任务

你是一名严格但务实的开源项目 PR reviewer。
请评审 PR_URL 指向的 PR 是否可以接受。

重点判断它是否真正解决了 ISSUE_ID 对应的 issue，
并检查代码、文档、测试和仓库规范是否存在问题。

如果 ISSUE_ID 为空，请跳过 issue 对齐检查，
改为根据 PR 标题、描述和实际 diff 判断是否适合合并。

# 评审目标

请给出明确结论：

- 可以接受并合并；
- 需要小修改后再合并；
- 需要较大修改，不建议当前合并；
- 不应合并。

不要只做泛泛评价，要指出具体问题、风险和建议修改点。

# 必须执行的验证步骤（在定级前）

以下步骤是评审质量的硬性前提，不能用"通读 diff"替代。

**适用条件**：

- 若 PR 涉及代码、契约、测试、运行路径、迁移、配置 —— 适用，必须按顺序执行。
- 若 PR 是纯文档 / 纯说明性注释 / 版式调整，且不影响生成产物、示例代码、
  API 文档、配置或运行行为 —— 在评审中明确说明"不适用"，
  跳过步骤 1-3，仅执行步骤 0 和步骤 4。
- 若某一步因环境 / 权限 / 工具不可用而无法执行 —— 必须在评审报告中明确说明
  "未执行 + 原因 + 替代验证方式"，不要假设"作者已确认"或"应该没问题"。

## 步骤 0：读项目背景，校准严重性

在对问题严重性定级之前，必须先读取以下信息以理解项目当前阶段：

- 仓库根目录的 `CLAUDE.md` / `AGENTS.md` / `README.md`
- 项目状态相关的 docs（是否上线？是否有真实用户？是否有历史数据？目标规模？）
- 若 agent 有项目 memory 工具，读取相关项目 memory；
  无 memory 工具或没找到状态描述时，仅以仓库内文件为准，并在评审中说明背景信息来源。

**这一步直接影响严重性判断。**未上线 MVP 项目和成熟生产系统的"够用"标准不同，
不要拿生产标准评 MVP，也不要拿 MVP 标准放过生产系统的真实风险。
具体规则见"严重性分级标准"和"不应纳入评审的事项"。

## 步骤 1：识别 PR 的"访问模式 / 契约 / 签名"变更

从 diff 中提取所有以下类型的变更：

- 函数 / 方法的签名（参数增删、关键字参数改名、位置参数顺序变）
- 共享 helper 的语义（比如 `get_owned_X` → `get_visible_X`）
- 数据访问范式（比如 `Filter.created_by == user.id` → 新的可见性 filter）
- API 路由的请求体 / 响应字段、错误码、状态码
- 数据库字段、约束、索引、迁移
- 鉴权 / 授权 / 资源归属判定逻辑
- 前后端共享类型 / OpenAPI / SDK 契约

对**每一项**变更，必须执行步骤 2、3。

## 步骤 2：搜全仓库找旧范式的所有调用方与依赖点

对步骤 1 中的每一项契约变更，用 `rg`（首选）或 `grep -rn` 在整个仓库
（不只是 PR 改动的文件）搜索：

- 旧函数名 / 旧方法名 / 旧 helper 名
- 旧字段名 / 旧关键字参数名
- 旧导入路径 / 旧模块路径
- 旧路由路径 / 旧 API 端点
- 测试 fixture、mock、stub 中的旧签名引用
- 前后端共享类型定义、OpenAPI 描述、SDK 客户端

列出所有命中位置，逐一判断：是被 PR 修改了？是应该修改但被遗漏了？是应保留的特殊情况？

**关键认知**：issue body 里的"预计影响范围"只是作者的估计，**不是清单**。
PR 实际需要触达的文件可能比 issue 列出的多。漏改一个调用方，等价于一个潜在的功能性 broken。

## 步骤 3：实际运行受影响的测试 / 类型检查 / 构建 / lint

不要只看 PR 描述里作者打勾的 testing checklist。作者宣称"测试通过"经常并不可信。

**先发现项目标准命令**：

- 读 `README.md` / `CLAUDE.md` / `AGENTS.md` / `package.json` / `pyproject.toml`
  / `Makefile` / `pre-commit` 配置，找出项目的标准测试 / typecheck / lint / build 命令。
- 不要凭印象拼 `pytest` / `npm test`；仓库可能用 `uv run pytest` / `pnpm test:unit`
  / `cargo test` 等。

**然后执行**：

- 找出 PR 修改 / 新增的所有测试文件
- 加上调用了被 PR 修改的函数 / 模块 / 字段 / 路由的所有现有测试文件
- 按项目标准命令运行：测试 + 受影响范围的 typecheck + lint；
  涉及前端 / 编译型语言时，运行 build。
- 如运行不了（环境 / 依赖原因），必须在评审报告中标注"未运行 + 原因 + 替代验证方式"，
  并至少做静态对照（比对调用签名、字段引用）。

**特别警示**：如果 PR 改了某函数签名 / 字段，但仓库里还有用旧签名 / 旧字段引用的
测试或代码 —— 这是 Blocker，是单凭通读 diff 最容易漏的一类问题。

## 步骤 4：核对 issue 验收清单的每条对应实现

若 ISSUE_ID 非空，把 issue 的"验收标准 / 已确认规则 / 期望行为"逐条列出，
对**每一条**到 PR diff（含未改动的相关文件）里找对应实现位置。
若 ISSUE_ID 为空，则根据 PR 标题、描述和实际 diff 推断 PR 的验收点，并逐条核对。

特别注意"任务执行 / 流程模板 / 计划生成 / 项目编辑"等容易被遗忘的入口路径，
不要只看 issue 显式提到的几个 router。

# 背景

如果 ISSUE_ID 非空，本 PR 目标是解决 REPO_NAME 仓库中的 issue ISSUE_ID。
请先阅读 issue ISSUE_ID 的描述，再对照 PR 的实际改动判断是否完整解决。
如果 ISSUE_ID 为空，请改为根据 PR 标题、描述和 diff 判断 PR 目标。

重点关注：

1. 是否真正解决了 ISSUE_ID（包括 issue 显式列出的、和隐含的所有受影响入口）；
2. 是否引入不必要改动；
3. 文档修改是否必要、位置是否合理、命名是否规范；
4. 代码实现是否符合当前项目结构和风格；
5. 是否需要测试，现有测试是否足够、是否被 PR 改挂；
6. 是否存在边界情况遗漏；
7. 是否会影响现有功能或用户体验；
8. 是否适合直接合并到 main。

# 具体检查项

以下检查项是步骤 0-4 的补充，不是替代。
凡能通过验证步骤直接覆盖的事项（测试运行结果、契约 grep、issue 验收对齐）
不要在这里重复列出，只列**只能在阅读代码 / 文档时发现**的独有点。

## 1. Issue 对齐与范围控制

- ISSUE_ID 的核心问题是什么？步骤 4 中是否每条验收标准都找到对应实现？
- 是否存在误解 issue 目标的情况？
- 是否有超出 issue 范围的额外改动？是否应拆分？

**重要**：issue 里的"预计影响范围 / 推荐实现方向"是作者的估计性提示，
不要把它当成 PR 必须严格符合的清单 —— 真实需要修改的文件应通过步骤 2 独立确定。

## 2. 代码实现专项

通用检查：

- 实现逻辑是否正确，边界情况是否遗漏（空输入、单元素、最大值、null）；
- 错误信息是否清晰且面向调用方；
- 是否符合项目现有代码风格（**改风格前必须先 grep 仓库其它地方的写法**：
  若仓库已稳定使用 X 写法，不要单独要求 PR 改成 Y；风格统一性优先于个人偏好）。
- 若 issue 或 PR 声称某路径应被禁止 / 拒绝 / 不可见 / 不可编辑，是否验证了旧允许路径现在失败？

**安全 / 权限专项**（PR 改动了鉴权、授权、资源归属、可见性 filter、权限 helper 时强制）：

- 列出所有受新规则影响的入口（router / view / service / SDK），按步骤 2 grep 旧权限范式；
- 跨用户 / 跨租户 / 跨项目的可见性、可修改性是否在每个入口一致？
- 是否存在 IDOR（依赖前端隐藏而后端不校验）？
- 错误码语义是否合理（资源不存在返回 404、有权限读但无权限写返回 403）。

**数据库 schema / 迁移专项**（PR 改动了模型字段、约束、索引时强制）：

- 是否提供 migration 脚本？是否符合仓库迁移惯例，并有前滚 / 回滚 / 失败恢复策略？
- 新字段的默认值、nullable、唯一约束、索引是否合理？
- 现有数据兼容性如何处理（是否需要回填、是否会引发空值崩溃）？
- 数据库类型差异（SQLite vs PostgreSQL）是否考虑？

## 3. 文档与命名专项

- 文档位置是否合适：产品 / 架构文档通常在 `docs/`，提案 / 草稿 / ADR 通常在
  `proposals/` 或 `adr/`，二者不要混；
- 文档命名是否符合仓库已有惯例；
- **是否出现"当前分支未找到 X"、"建议实施顺序"、"实现前状态"等过程性内容** ——
  这类内容属于 PR 评审消息或方案草稿，不应进入 main 的稳定文档；
- 是否和 README、docs、roadmap、issue 描述存在冲突；
- 中英文文档是否需要同步。

## 4. UI / UX 与仓库规范专项

UI / UX（PR 涉及前端时）：

- 错误信息、表单校验是否清楚 / 及时 / 友好；
- 多用户共享资源的操作是否提示影响范围；
- 是否影响现有操作流程或文案 / 样式一致性。

仓库规范：

- 新增配置项 / 环境变量 / feature flag 时，是否同步默认值、示例 env、文档、CI / 容器 / 部署配置？
- 新增依赖是否必要？lockfile 是否同步？是否引入明显许可证、体积或供应链风险？
- `.gitignore` 中是否夹带与本 issue 无关的本地调试条目；
- 是否引入无关文件、临时文件、构建产物或调试日志；
- 是否需要更新 changelog 或相关索引文档。

# 严重性分级标准

严重性分级要严格按以下标准，**不要凭感觉打级**。
打级前对每条问题问自己："如果不修，会发生什么？"

## Blocker（必须修，否则不能合并）

- 现有测试被 PR 改挂（实际运行后报错）；
- issue 验收清单的硬性要求功能性 broken；
- 引入安全漏洞、数据丢失、接口破坏；
- 引入回归（破坏现有功能）。

反面例子（不应作为 Blocker）：性能可优化点、风格不一致、文档可改进、测试覆盖不全。

## Major（必须修，否则有显著质量或维护风险）

- 测试覆盖远不足以验证 issue 关键路径（不是某一两个 case 缺，是整片路径缺）；
- 文档明显不适合进入 main（含过程性自述、严重位置不当）；
- 引入了与本 PR 无关的明显越界改动且范围较大；
- **当前数据规模 / 循环路径 / 用户操作已能触发明显性能退化**（页面卡死、超时、
  显著 O(N²) 路径），不是"未来规模上来后可能慢"的推测。

反面例子（应判为 Minor，不是 Major）：单条 case 覆盖不足、UX 微调建议、
API 错误码精度问题、未影响验收路径和现有调用的 API 语义可改进。

## Minor（小问题，不阻塞合并）

- API 错误码 / 错误信息精度问题；
- 缺少对多用户共享操作的 UI 提示；
- `.gitignore` 等夹带与 issue 无关的少量改动；
- 建议性的语义改进（比如返回 403 vs 404，前提是不影响现有调用的功能）。

## Nit（细节建议）

- 命名、格式、表述细节；
- **仅当 PR 引入的写法偏离仓库已有稳定惯例时才提**；
- 不要提"和仓库已有写法冲突的标准化建议"（比如仓库已有 N 处 `X == True  # noqa`
  写法时，单独要求 PR 改成 `.is_(True)`）。

# 不应纳入评审的事项

以下类别在大多数情况下**不应**出现在评审报告里。
即便你"看到"了，也要主动过滤掉：

## 1. PR 元数据 / 流程纪律

以下事项**原则上不进入代码问题清单**：

- PR 标题格式（是否带 "Closes #X"、用词风格）；
- PR body 格式（checkbox 用 `[x]` 还是 `[√]`、是否有残留占位符）；
- Commit author 是否绑到 GitHub 账号；
- 分支命名（headRefName 是不是 feature 分支）；
- Commit message 风格。

**例外**：仓库明确规定且会阻塞合并的流程要求（DCO / CLA / signoff /
release note policy / changelog 必填等），可以放到"仓库规范"里做人工确认提示，
但仍不混入代码问题清单的 Blocker / Major / Minor / Nit。

## 2. 过早的性能 / 并发优化建议（特别针对未上线 / MVP 项目）

未上线 MVP / 无真实用户 / 无历史数据时：

- **未观察到当前可复现的性能退化时**，性能优化建议（N+1、全表扫描、批量预取）
  不入问题清单，可作为脚注"未来如成长到 X 规模再处理"列出；
- 单实例 + SQLite 等串行化场景下，TOCTOU / 并发竞态建议不入问题清单；
- 不要为"未来规模可能"提前重构。

**反向例外**：若当前数据规模 / 循环路径 / 用户操作已能触发明显退化
（页面卡死、超时、明显 O(N²)）—— 按"严重性分级标准"中 Major 的定义实事求是定级。

## 3. 为不存在的场景写防御代码

提防御性建议（"宽容解析"、"兼容其它类型"、"补 fallback"）前，必须先回答：

- 该输入 / 状态是否来自**真实系统边界**（外部 API、用户输入、第三方回调）？
- 该格式是否来自**真实历史数据**（项目已上线产生的数据）？
- 是否对应**真实存在的客户端**（已发布的 SDK / 移动端旧版本）？
- 是否被 issue 验收标准明确要求兼容？

以上四问全为否时，不要把防御性建议放入问题清单。
未上线 / 无历史数据 / 单一现网客户端时，绝大多数兼容性建议都属于此类。

**例外**：本 PR 自己引入的字段就有多种合法形态时（产品需求决定），需要正常防御。

## 4. 与仓库已有惯例冲突的风格 nit

- 标 nit 之前先 grep 仓库其它地方是不是同样写法；
- 风格统一性优先于个人偏好；
- 详见"严重性分级标准 - Nit"。

## 5. 重复 issue 已解释清楚的设计决策

- 如果 issue 已经明确"采用方案 A，不要方案 B"，不要在评审里要求作者改成方案 B；
- 不要质疑 issue 已经定下的产品语义。

# 输出格式

## 1. 总体结论

结论只能选一个：

- 可以接受并合并；
- 需要小修改后再合并；
- 需要较大修改，不建议当前合并；
- 不应合并。

并用 2-4 句话说明主要理由。

**严重性与结论的对应关系**：

- 任何 Blocker 存在 → 至少"需要较大修改，不建议当前合并"；
- 多个 Blocker 或核心路径 broken → "不应合并 / 暂缓合并"；
- 只有 Minor/Nit → "可以接受并合并"或"需要小修改后再合并"。

## 2. 是否解决 issue ISSUE_ID

请明确说明：

- ISSUE_ID 的核心要求 / 验收清单逐条列出；
- PR 已完成的部分（每条对应到具体文件/函数）；
- PR 未完成或可疑的部分；
- 是否存在偏离 issue 的改动。

## 3. 主要问题清单

按严重程度列出，遵循"严重性分级标准"。

每条问题必须包含：

- 具体定位（文件:行号 或函数名）；
- 触发条件 / 影响；
- 修复建议（一句话即可）。

如果某类没有问题，请写"无"。

### Blocker

### Major

### Minor

### Nit

## 4. 文档与命名检查

单独说明：

- 文档修改是否必要；
- 文档位置是否合理（产品文档 vs 提案文档区分）；
- 文档命名是否规范；
- 是否含过程性自述等不应进入 main 的内容；
- 是否建议调整、合并、删除或移动文档。

## 5. 测试与验证建议

请给出：

- **实际运行结果**：哪些测试跑了，结果如何（如未运行需说明原因）；
- 已有测试是否足够；
- 建议补充哪些测试（按 issue 验收清单覆盖优先级排序）；
- 建议手工验证哪些场景。

## 6. 建议给 PR 作者的修改意见

请整理成可以直接发在 PR review comment 里的文字，
语气专业、具体、可执行。优先列 Blocker 修复指引，再列 Major / Minor。

## 7. 最终建议

请给出一句话最终建议：

> 建议合并 / 修改后合并 / 暂缓合并 / 关闭 PR。

# 提交评审前的自检清单

写完评审报告后、提交给用户前，**逐条核对**：

1. 我是否真的执行了"必须执行的验证步骤"中适用的所有步骤？哪些没做、原因是什么？
   是否在报告中如实标注？
2. 每个 Blocker 是否有"已实际验证"的证据（测试 / typecheck / build 运行结果、
   grep 命中位置、复现步骤）？还是只是推测？
3. 报告中每一条问题，撤掉它对作者有损失吗？没损失就撤掉（不要为凑数堆 Nit）。
4. 我是否打了与仓库已有惯例冲突的风格 nit？
5. 我对未上线 / MVP 项目报的性能 / 并发 / 防御性编码建议，
   是否对应"当前可复现的真实退化 / 真实系统边界 / 真实历史数据 / 真实客户端"？
   都不是的话应该撤掉。
6. 我是否包含了 PR 元数据、commit author、分支命名等流程纪律事项？这些应该撤掉
   （除非是仓库明确规定的合并阻塞规则）。
7. 我对 issue 的"预计影响范围"是当成清单了，还是当成提示了？
   是否独立 grep 了所有需修改入口（含权限 helper、字段、路由、测试 fixture）？
8. 若 PR 改动了鉴权 / 权限 / 资源归属 / 可见性 filter，
   我是否核对了所有受影响入口？是否检查了 IDOR 类问题？
9. 若 PR 声称某路径应被禁止 / 拒绝 / 不可见 / 不可编辑，我是否做了负面验证？
10. 若 PR 改动了 schema / 字段，我是否核对了 migration、默认值、前滚 / 回滚 / 失败恢复策略？
11. 若 PR 新增配置、环境变量或依赖，我是否核对了文档、示例、部署配置和 lockfile？
12. 严重性分级是否符合"严重性分级标准"？是否有把 Minor 当 Major 报、或反过来？
13. 总体结论是否与 Blocker / Major 数量一致？

# 注意事项

- 不要因为 PR 解决了部分问题就轻易建议合并。
- 不要只看 diff 表面，要按"必须执行的验证步骤"做交叉验证。
- 不要信任作者的 testing checklist，自己跑测试 / typecheck / build。
- 不要把 issue 的"预计影响范围"当成清单，要独立 grep。
- 如果 PR 改了权限 / 可见性逻辑，请专门做安全 / 越权检查。
- 如果 PR 改了 schema，请专门做 migration / 兼容性检查。
- 如果 PR 添加了文档，要特别关注文档位置、命名、内容边界和是否适合 main。
- 如果 PR 修改了校验逻辑，要特别关注边界输入和错误提示。
- 如果发现 PR 做了和 ISSUE_ID 无关的大量改动，请明确指出是否应拆分。
- 评审的目的是帮 reviewer 节省判断成本，不是堆砌看上去全面的 checklist。
  少而准 > 多而散。""".strip()


def issue_review_loop_template_json() -> dict[str, Any]:
    return {
        "plan_name": TEMPLATE_NAME,
        "description": "输入 issue URL 后，由编码 Agent 编码、两个评审 Agent 并行评审，并按评审结论循环修复或提交 PR。",
        "flow_type": FLOW_TYPE,
        "agent_roles": [
            {
                "slot": "agent-1",
                "description": "编码与决策 Agent。负责拉取 issue、实现代码、测试、推送工作分支，根据评审意见修复，并在双评审通过后提交 PR。",
            },
            {
                "slot": "agent-2",
                "description": "评审 Agent A。负责从当前工作分支和 commit 独立评审代码，按结构化格式写入本轮 review.json 与 review.md。",
            },
            {
                "slot": "agent-3",
                "description": "评审 Agent B。负责独立执行第二份代码评审，不依赖评审 A 的结论，只写入自己的本轮评审产物。",
            },
        ],
        "tasks": [
            {
                "task_code": "TASK-001",
                "task_name": "拉取 issue 并初始化评审循环状态",
                "description": "读取 issue URL，理解需求，生成实现计划，初始化 flow-state.json，解锁编码任务。",
                "assignee": "agent-1",
                "depends_on": [],
                "expected_output": "outputs/TASK-001/result.json",
            },
            {
                "task_code": "TASK-002",
                "task_name": "编码、测试并推送工作分支",
                "description": "实现 issue 或修复上一轮合理评审意见，执行测试，推送项目仓库工作分支，并更新 flow-state.json 进入等待评审。",
                "assignee": "agent-1",
                "depends_on": ["TASK-001"],
                "expected_output": "outputs/TASK-002/result.json",
            },
            {
                "task_code": "TASK-003",
                "task_name": "评审 A",
                "description": "读取当前轮次 branch.json 和用户评审提示词，对工作分支进行独立评审，仅写入自己的 review.json / review.md。",
                "assignee": "agent-2",
                "depends_on": ["TASK-002"],
                "expected_output": "outputs/TASK-003/result.json",
            },
            {
                "task_code": "TASK-004",
                "task_name": "评审 B",
                "description": "读取当前轮次 branch.json 和用户评审提示词，对工作分支进行独立评审，仅写入自己的 review.json / review.md。",
                "assignee": "agent-3",
                "depends_on": ["TASK-002"],
                "expected_output": "outputs/TASK-004/result.json",
            },
            {
                "task_code": "TASK-005",
                "task_name": "评审决策与 PR 提交",
                "description": "只读取当前轮次两份评审结果，决定提交 PR 或解锁下一轮修复，并更新 flow-state.json。",
                "assignee": "agent-1",
                "depends_on": ["TASK-003", "TASK-004"],
                "expected_output": "outputs/TASK-005/result.json",
            },
        ],
    }


def issue_review_loop_required_inputs() -> list[dict[str, object]]:
    return [
        {"key": "issue_url", "label": "Issue URL", "required": True, "sensitive": False},
        {
            "key": "review_prompt",
            "label": "评审提示词",
            "required": True,
            "sensitive": False,
            "default_value": DEFAULT_REVIEW_PROMPT,
        },
        {"key": "test_command", "label": "测试命令", "required": False, "sensitive": False},
        {"key": "max_review_rounds", "label": "最大评审轮次", "required": True, "sensitive": False},
    ]


def ensure_issue_review_loop_template(db: Session, admin) -> None:
    existing = db.query(ProcessTemplate).filter(ProcessTemplate.name == TEMPLATE_NAME).first()
    now = datetime.now(timezone.utc)
    agent_slots_json = json.dumps(["agent-1", "agent-2", "agent-3"], ensure_ascii=False)
    agent_roles_description_json = json.dumps(
        {
            "agent-1": "编码与决策 Agent，负责实现、测试、修复、推送工作分支和最终提交 PR。",
            "agent-2": "评审 Agent A，负责独立代码评审并写入结构化评审结果。",
            "agent-3": "评审 Agent B，负责独立代码评审并写入结构化评审结果。",
        },
        ensure_ascii=False,
    )
    required_inputs_json = json.dumps(issue_review_loop_required_inputs(), ensure_ascii=False)
    template_json = json.dumps(issue_review_loop_template_json(), ensure_ascii=False)
    desired = {
        "description": "输入 issue URL 后，固定使用编码、双评审、决策 5 个 Task 完成编码评审闭环。",
        "prompt_source_text": "MVP 内置模板：固定 5 个 Task，运行状态由协作仓库 flow-state.json 与当前轮次产物派生。",
        "agent_count": 3,
        "agent_slots_json": agent_slots_json,
        "agent_roles_description_json": agent_roles_description_json,
        "required_inputs_json": required_inputs_json,
        "template_json": template_json,
    }
    if existing is not None:
        changed = False
        for key, value in desired.items():
            if getattr(existing, key) != value:
                setattr(existing, key, value)
                changed = True
        if changed:
            existing.updated_by = admin.id
            existing.updated_at = now
            db.commit()
        return

    template = ProcessTemplate(
        name=TEMPLATE_NAME,
        **desired,
        created_by=admin.id,
        updated_by=admin.id,
        created_at=now,
        updated_at=now,
    )
    db.add(template)
    db.commit()


def _parse_json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def is_issue_review_loop_plan(plan: ProjectPlan | None) -> bool:
    if not plan:
        return False
    data = _parse_json_object(plan.plan_json)
    return data.get("flow_type") == FLOW_TYPE


def get_issue_review_loop_plan(db: Session, project: Project) -> ProjectPlan | None:
    plans = (
        db.query(ProjectPlan)
        .filter(ProjectPlan.project_id == project.id, ProjectPlan.is_selected == True)  # noqa: E712
        .order_by(ProjectPlan.id.desc())
        .all()
    )
    for plan in plans:
        if is_issue_review_loop_plan(plan):
            return plan
    return None


def project_uses_issue_review_loop(db: Session, project: Project) -> bool:
    return get_issue_review_loop_plan(db, project) is not None


def _collab_dir(project: Project) -> str:
    return (project.collaboration_dir or "").strip("/")


def _flow_state_path(project: Project) -> str:
    base = _collab_dir(project)
    return f"{base}/flow-state.json" if base else "flow-state.json"


def _round_dir(current_round: int) -> str:
    return f"round-{current_round:03d}"


def _review_path(project: Project, task_code: str, current_round: int) -> str:
    base = _collab_dir(project)
    path = f"{task_code}/reviews/{_round_dir(current_round)}/review.json"
    return f"{base}/{path}" if base else path


def _decision_path(project: Project, current_round: int) -> str:
    base = _collab_dir(project)
    path = f"TASK-005/decisions/{_round_dir(current_round)}/decision.json"
    return f"{base}/{path}" if base else path


def _branch_path(project: Project, current_round: int) -> str:
    base = _collab_dir(project)
    path = f"TASK-002/rounds/{_round_dir(current_round)}/branch.json"
    return f"{base}/{path}" if base else path


def get_issue_review_branch_path(project: Project, current_round: int) -> str:
    return _branch_path(project, current_round)


def get_issue_review_decision_path(project: Project, current_round: int) -> str:
    return _decision_path(project, current_round)


def _empty_response(enabled: bool) -> dict[str, Any]:
    return {
        "enabled": enabled,
        "exists": False,
        "valid": False,
        "flow_type": None,
        "phase": None,
        "derived_phase": None,
        "current_round": None,
        "round_id": None,
        "work_branch": None,
        "head_commit": None,
        "max_review_rounds": None,
        "task_states": {},
        "effective_task_states": {},
        "reviews": {},
        "decision": {},
        "pr": {},
        "errors": [],
    }


def _validate_review(
    project: Project,
    task_code: str,
    flow_state: dict[str, Any],
    errors: list[str],
) -> dict[str, Any]:
    current_round = flow_state.get("current_round")
    if not isinstance(current_round, int):
        return {"status": "pending", "approve_merge": None, "review_path": None}

    path = _review_path(project, task_code, current_round)
    content = git_service.read_file(
        project.id,
        path,
        git_repo_url=project.git_repo_url,
        prefer_remote=True,
    )
    if content is None:
        return {"status": "pending", "approve_merge": None, "review_path": path}

    try:
        review = json.loads(content)
    except json.JSONDecodeError:
        errors.append(f"{task_code} review.json is not valid JSON: {path}")
        return {"status": "needs_attention", "approve_merge": None, "review_path": path}

    if not isinstance(review, dict):
        errors.append(f"{task_code} review.json must be an object: {path}")
        return {"status": "needs_attention", "approve_merge": None, "review_path": path}

    for key, expected in (
        ("round", flow_state.get("current_round")),
        ("round_id", flow_state.get("round_id")),
        ("work_branch", flow_state.get("work_branch")),
        ("head_commit", flow_state.get("head_commit")),
    ):
        if review.get(key) != expected:
            errors.append(f"{task_code} review.json {key} does not match current flow-state: {path}")
            return {"status": "needs_attention", "approve_merge": None, "review_path": path}

    approve_merge = review.get("approve_merge")
    if type(approve_merge) is not bool:
        errors.append(f"{task_code} review.json approve_merge must be boolean: {path}")
        return {"status": "needs_attention", "approve_merge": None, "review_path": path}

    return {"status": "submitted", "approve_merge": approve_merge, "review_path": path}


def _validate_decision(
    project: Project,
    flow_state: dict[str, Any],
    errors: list[str],
) -> dict[str, Any]:
    current_round = flow_state.get("current_round")
    if not isinstance(current_round, int):
        return {"status": "pending", "decision_path": None}

    path = _decision_path(project, current_round)
    content = git_service.read_file(
        project.id,
        path,
        git_repo_url=project.git_repo_url,
        prefer_remote=True,
    )
    if content is None:
        return {"status": "pending", "decision_path": path}

    try:
        decision = json.loads(content)
    except json.JSONDecodeError:
        errors.append(f"TASK-005 decision.json is not valid JSON: {path}")
        return {"status": "needs_attention", "decision_path": path}

    if not isinstance(decision, dict):
        errors.append(f"TASK-005 decision.json must be an object: {path}")
        return {"status": "needs_attention", "decision_path": path}

    for key, expected in (
        ("round", flow_state.get("current_round")),
        ("round_id", flow_state.get("round_id")),
    ):
        if decision.get(key) != expected:
            errors.append(f"TASK-005 decision.json {key} does not match current flow-state: {path}")
            return {"status": "needs_attention", "decision_path": path}

    for key in ("work_branch", "head_commit"):
        if key in decision and decision.get(key) != flow_state.get(key):
            errors.append(f"TASK-005 decision.json {key} does not match current flow-state: {path}")
            return {"status": "needs_attention", "decision_path": path}

    return {
        "status": "submitted",
        "decision_path": path,
        "approved": decision.get("approved") if type(decision.get("approved")) is bool else None,
        "next_action": decision.get("next_action") if isinstance(decision.get("next_action"), str) else None,
    }


def get_issue_review_flow_state(db: Session, project: Project) -> dict[str, Any]:
    if not project_uses_issue_review_loop(db, project):
        return _empty_response(enabled=False)

    path = _flow_state_path(project)
    content = git_service.read_file(
        project.id,
        path,
        git_repo_url=project.git_repo_url,
        prefer_remote=True,
    )
    if content is None:
        response = _empty_response(enabled=True)
        response["effective_task_states"] = {code: ("unlocked" if code == "TASK-001" else "frozen") for code in TASK_CODES}
        response["errors"] = [f"flow-state.json not found: {path}"]
        return response

    response = _empty_response(enabled=True)
    response["exists"] = True
    try:
        flow_state = json.loads(content)
    except json.JSONDecodeError:
        response["errors"] = [f"flow-state.json is not valid JSON: {path}"]
        response["effective_task_states"] = {code: "frozen" for code in TASK_CODES}
        return response

    if not isinstance(flow_state, dict) or flow_state.get("flow_type") != FLOW_TYPE:
        response["errors"] = [f"flow-state.json flow_type must be {FLOW_TYPE}: {path}"]
        response["effective_task_states"] = {code: "frozen" for code in TASK_CODES}
        return response

    required = ("current_round", "round_id", "phase", "task_states")
    missing = [key for key in required if key not in flow_state]
    if missing:
        response["errors"] = [f"flow-state.json missing required fields: {', '.join(missing)}"]
        response["effective_task_states"] = {code: "frozen" for code in TASK_CODES}
        return response

    task_states = flow_state.get("task_states") if isinstance(flow_state.get("task_states"), dict) else {}
    effective = {code: str(task_states.get(code) or "frozen") for code in TASK_CODES}
    errors: list[str] = []
    reviews = {
        "TASK-003": _validate_review(project, "TASK-003", flow_state, errors),
        "TASK-004": _validate_review(project, "TASK-004", flow_state, errors),
    }
    decision = _validate_decision(project, flow_state, errors)
    both_reviews_submitted = all(item.get("status") == "submitted" for item in reviews.values())
    derived_phase = str(flow_state.get("phase") or "")

    task_005_state = effective.get("TASK-005")
    task_002_state = effective.get("TASK-002")
    can_derive_decision_unlock = (
        both_reviews_submitted
        and derived_phase in {"awaiting_review", "reviewing", "awaiting_decision"}
        and task_002_state == "waiting_review"
        and task_005_state not in {"completed", "approved", "abandoned", "running"}
    )

    if can_derive_decision_unlock:
        effective["TASK-003"] = "frozen"
        effective["TASK-004"] = "frozen"
        effective["TASK-005"] = "unlocked"
        derived_phase = "awaiting_decision"
    elif derived_phase == "needs_attention" and decision.get("status") == "submitted":
        effective["TASK-005"] = "completed"
    elif errors:
        for task_code, item in reviews.items():
            if item.get("status") == "needs_attention":
                effective[task_code] = "needs_attention"

    response.update({
        "valid": True,
        "flow_type": flow_state.get("flow_type"),
        "phase": flow_state.get("phase"),
        "derived_phase": derived_phase,
        "current_round": flow_state.get("current_round"),
        "round_id": flow_state.get("round_id"),
        "work_branch": flow_state.get("work_branch"),
        "head_commit": flow_state.get("head_commit"),
        "max_review_rounds": flow_state.get("max_review_rounds"),
        "task_states": task_states,
        "effective_task_states": effective,
        "reviews": reviews,
        "decision": decision,
        "pr": flow_state.get("pr") if isinstance(flow_state.get("pr"), dict) else {},
        "errors": errors,
    })
    return response


def get_effective_business_state(db: Session, project: Project, task_code: str) -> str | None:
    state = get_issue_review_flow_state(db, project)
    if not state.get("enabled"):
        return None
    effective = state.get("effective_task_states") if isinstance(state.get("effective_task_states"), dict) else {}
    value = effective.get(task_code)
    return str(value) if value is not None else "frozen"


def is_business_dispatch_allowed(state: str | None) -> bool:
    return state in BUSINESS_DISPATCHABLE_STATES
