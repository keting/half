# 多 Agent 协作与 Coding Agent 编排产品调研

> 调研日期：2026-07-28  
> 状态：首版，供 Discussion 和 Roadmap 讨论  
> 范围：公开官方文档与开源仓库，不包含付费企业功能的实测

## 一、结论摘要

1. HALF 的直接定位不是多 Agent 运行时，也不是 Coding Agent 本身，而是不同
   Agent 产品之上的人工协调层。它的核心边界是“组织、分发、追踪，但不直接
   执行 Agent”。
2. OpenHands Agent Canvas 是本次调研中形态最接近 HALF 的产品：两者都提供
   面向多个 Coding Agent 的控制台。关键差异是 Agent Canvas 通过本地、远程或
   云端 Agent Server 直接运行 Agent，而 HALF 保留人工分发并通过 Git 回写追踪
   结果。
3. CrewAI、LangGraph 与 AutoGen / Microsoft Agent Framework 属于可编程 Agent
   运行时。它们适合作为状态、暂停恢复、可观测性和工作流表达的设计参考，但
   不是 HALF 当前产品边界内应复制的执行层。
4. Claude Code、Codex 与 GitHub Copilot cloud agent 是任务执行者或执行平台，
   更适合被 HALF 编排或观察，而不是被视为同层竞品。
5. HALF 的短期研究价值不在于增加更多“自动化”按钮，而在于记录人工协调
   成本、handoff 质量、Agent 分歧和失败恢复过程。缺少这些数据，难以验证
   多 Agent 是否真的优于单 Agent。

## 二、调研方法与口径

本报告只采用项目官方仓库和官方文档，记录文档在调研日期明确公开的能力。
“支持”表示官方资料明确描述该能力，不根据宣传图或第三方文章推断。产品更新
较快，因此本报告不记录 Star 数、短期价格或模型榜单。

对比对象分为四类：

- 通用 Agent 运行时：AutoGen / Microsoft Agent Framework、CrewAI、LangGraph；
- 软件工程 SOP 型多 Agent 框架：MetaGPT；
- Coding Agent 控制台：OpenHands Agent Canvas；
- Coding Agent 产品：Claude Code、Codex、GitHub Copilot cloud agent。

## 三、定位与能力对比

| 系统 | 主要形态 | 是否直接执行 Agent / 模型 | 工作流与状态 | 人工介入 | Git 的角色 |
|---|---|---|---|---|---|
| HALF | 自托管多 Agent 协调控制台 | 否；人工把 prompt 发送到 Agent UI | DAG、流程模板、任务状态、Agent 可用性 | 人工负责每次分发和最终判断 | 协作仓库保存任务产物，HALF 轮询 `result.json` |
| AutoGen / Microsoft Agent Framework | 可编程多 Agent 运行时 | 是；通过模型客户端、工具和运行时执行 | 消息传递、事件驱动、群聊和分布式运行时 | 可编程加入，人为策略由应用负责 | 无固定 Git 协作协议，需自行集成 |
| CrewAI | Python 多 Agent 自动化框架与控制平台 | 是；Crew 和 Flow 执行 Agent、工具与 LLM 调用 | 角色化 Crew；事件驱动 Flow 支持状态、分支与路由 | 支持 human input / review 节点 | 通用集成对象，不以 Git 作为任务状态协议 |
| LangGraph | 低层有状态 Agent 工作流框架 | 是；图节点执行模型、工具或代码 | 图、持久化 checkpoint、暂停恢复、长期状态 | interrupt 可暂停并检查或修改状态 | 无固定 Git 协作协议，需自行集成 |
| MetaGPT | 软件团队 SOP 型多 Agent 框架 | 是；不同角色按 SOP 生成文档和代码 | 产品、架构、项目管理、工程等角色化流程 | 可扩展人工参与，核心范式偏自动角色协作 | 代码和文档是产物，但 Git 不是主要协调协议 |
| OpenHands Agent Canvas | 自托管 Coding Agent 控制台 | 是；连接本地、Docker、VM 或云端 Agent Server | 会话、Agent 后端、自动化、定时或事件触发 | 人可在会话和自动化配置中控制 | 可连接 GitHub 等服务并由 Agent 直接修改项目 |
| Claude Code | 终端、IDE、Web 与 GitHub 中的 Coding Agent | 是；在授权范围内读取、修改和执行 | 以 Agent 会话和任务为中心 | 通过权限模式和交互确认介入 | 可处理本地 Git 工作流或 GitHub 任务 |
| Codex | CLI、IDE、桌面与云端 Coding Agent | 是；在本地沙箱或云环境中执行 | 任务、会话及可并行的 subagent 工作流 | 沙箱、审批和用户 review | 可在仓库内修改、测试和评审代码，云任务可形成可审阅变更 |
| GitHub Copilot cloud agent | GitHub 托管的异步 Coding Agent | 是；在 GitHub Actions 临时环境执行 | 从研究、计划到分支修改，可由事件或计划触发 | 用户可先迭代，再决定是否创建或合并 PR | Issue、分支、commit、日志和 PR 是核心载体 |

### 3.1 AutoGen / Microsoft Agent Framework

AutoGen 官方仓库已标记为维护模式，不再增加新功能，并建议新项目采用
Microsoft Agent Framework。AutoGen 仍提供 AgentChat、消息传递、事件驱动
Agent、本地或分布式运行时及代码执行扩展。这说明它更接近“构建和运行 Agent
应用的基础设施”，而非外部 Agent 产品的人工协调台。

对 HALF 的启发是事件模型和运行记录，而不是把 AutoGen runtime 嵌入 HALF。
Roadmap 和竞品列表应标明 AutoGen 的维护状态，避免把已经迁移的技术路线当作
主要新项目基线。

### 3.2 CrewAI

CrewAI 同时提供强调角色自治的 Crews 和强调确定性控制的 Flows。Flows 支持
状态、分支、路由、checkpoint 和 human-in-the-loop，商业控制平面还强调 tracing
与集中管理。其核心前提仍是由程序持有模型或工具访问方式并直接执行工作流。

HALF 可以参考 Crew / Flow 的分层：流程模板负责稳定结构，具体 Agent 选择和
输入在实例化时填写。但 HALF 不应因此把模板扩展成通用代码工作流引擎。

### 3.3 LangGraph

LangGraph 把长时、有状态 Agent 表达成图，重点能力包括 durable execution、
checkpoint、memory 和 interrupt。interrupt 允许在节点处暂停运行，让人检查或
修改状态后恢复。这是一种“运行时内部的人在回路中”，与 HALF 的“人负责跨
产品分发”不同。

HALF 最值得借鉴的是可恢复性语义：任务状态应区分“等待人工分发”“等待外部
结果”“等待人工决策”和“执行失败”，而不能只用一个宽泛的 pending 状态。

### 3.4 MetaGPT

MetaGPT 将产品经理、架构师、项目经理和工程师等角色组织成软件公司的 SOP，
强调 `Code = SOP(Team)`。它证明了结构化角色和标准交付物可以降低多 Agent
自由对话中的信息损失，但其流程主要由框架自动执行。

HALF 可以复用“角色 + 交付物契约”的思想，但角色名称不应替代可验收的任务
输入、输出和责任边界。

### 3.5 OpenHands Agent Canvas

OpenHands 当前将 Agent Canvas 定位为自托管的 Coding Agent 控制中心，可运行
OpenHands、Claude Code、Codex、Gemini 及兼容 ACP 的 Agent，并连接本地、
Docker、VM 和云端后端。它还支持定时或 webhook 触发的自动化，并可连接
GitHub、Slack、Linear 等服务。

这是 HALF 最需要持续跟踪的直接对照对象：

- 共同点：多 Agent 入口、任务/会话可视化、自托管、外部工具集成；
- Agent Canvas：平台直接启动 Agent，自动化程度高，但需要处理凭据、执行环境、
  权限和沙箱风险；
- HALF：不启动 Agent，自动化程度较低，但可以保留订阅式产品的人工交互边界，
  并用 Git 产物形成跨产品的最小协作协议。

HALF 不宜追赶 Agent Canvas 的全部 runtime 能力。更有区分度的方向是把人工
协调动作、handoff 和跨产品结果追踪做得可度量、可审计。

### 3.6 Claude Code、Codex 与 GitHub Copilot cloud agent

三者都能直接执行软件工程任务，但作用面不同：

- Claude Code 以终端和 IDE 交互为基础，也覆盖 Web 与 GitHub 场景；
- Codex 覆盖 CLI、IDE、桌面和云端，并支持并行 subagent 工作流；
- Copilot cloud agent 在 GitHub Actions 临时环境中异步工作，以 Issue、分支、
  commit 和 PR 作为主要协作载体。

这些产品正在内建更多任务管理、并行 Agent 和代码评审能力，会压缩“只负责
展示任务列表”的外部工具空间。HALF 需要聚焦它们单独难以解决的问题：跨厂商
协作、异构 Agent 分工、订阅可用性、统一 handoff，以及人在多个产品之间的
协调成本。

## 四、合规与安全边界

不同系统的自动化能力不能脱离凭据与产品条款讨论：

1. AutoGen、CrewAI、LangGraph 和 MetaGPT 通常由应用通过官方模型 API 或本地
   模型执行。应用开发者负责 API 凭据、费用、工具权限和运行环境安全。
2. OpenHands Agent Canvas 直接连接 Agent 后端。自托管并不自动等于安全；若
   Agent 在宿主机运行，它可能访问宿主机文件，官方文档也明确提示使用沙箱和
   安全加固。
3. Claude Code、Codex 与 Copilot 的本地、云端、订阅和 API 形态具有不同授权
   方式。能在 UI 中手工使用某项订阅，不等于可以共享凭据或由第三方平台批量
   自动调用。
4. HALF 当前的人工分发边界规避了代管第三方订阅凭据和模拟 UI 操作的问题，
   但仍需保护协作仓库、任务 prompt 和输出中可能出现的密钥或内部数据。

因此建议继续明确以下非目标：

- 不通过 UI 自动化绕过第三方产品提供的集成方式；
- 不集中保存或共享个人订阅凭据；
- 不默认获得 Agent 所在机器的执行权限；
- 不把 HALF 扩展成通用 LLM / Agent runtime。

如未来支持自动派发，应只讨论具有明确官方 API、独立凭据、计费和审计边界的
可选适配器，并在独立 Discussion 中重新评估产品定位与威胁模型。

## 五、对 HALF Roadmap 的建议

### 5.1 短期：不改变产品边界

1. **版本化任务卡片与 handoff schema。** 明确输入、约束、产物、未决问题、
   风险和验收结果，避免跨 Agent 只传递自由文本摘要。
2. **记录人工协调事件。** 至少记录 prompt 生成、复制、确认已分发、结果发现、
   人工驳回和重新派发的时间与责任人。
3. **补充可复用模板。** 优先提供 Bug 修复、功能开发、PR Review 和“一执行
   Agent + 两独立评审 Agent”等可验证流程。
4. **建立失败原因分类。** 区分上下文缺失、任务拆分错误、Agent 不可用、执行
   失败、评审分歧、Git 回写失败和人工超时。
5. **公开维护本报告。** 外部产品发生定位变化时更新快照日期和相关行，不在
   文档中维护容易失真的功能数量或市场排名。

### 5.2 中期：先做实验，再扩能力

1. 提供 task card、handoff 和结果包的导出/导入，降低人工复制时的结构损失。
2. 在不获取写权限的前提下读取 Issue、PR、CI 和 commit 状态，减少重复录入。
3. 建立流程级指标面板：完成率、总耗时、人工操作次数、返工轮次、评审分歧和
   失败恢复时间。
4. 将 Agent 能力、可用性和适合角色分开建模，避免只按产品名称分配任务。

### 5.3 长期观察项

- ACP、MCP、A2A 等协议是否能提供稳定且合规的跨 Agent 互操作边界；
- Coding Agent 自带的并行 Agent 能力是否降低外部编排价值；
- 官方 API 适配器能否与人工分发在同一个任务模型中共存；
- 企业是否真正需要跨厂商 Agent，还是单一平台内的专业角色已经足够。

## 六、可复现实验建议

### 实验 A：单 Agent 与 `1+2` 协作效果

- 任务：从多个公开仓库选取规模相近、测试可自动判定的 Issue；
- 对照组：一个 Agent 实现并自测；
- 实验组：一个 Agent 实现，两个 Agent 分别做测试和代码评审，再由原 Agent
  收敛；
- 控制变量：同一代码基线、相同任务说明、相同工具权限，并交叉轮换模型角色；
- 指标：任务通过率、遗漏缺陷、返工轮次、评审分歧、总墙钟时间、人工操作
  次数和人工协调时间；
- 分析重点：质量提升是否足以抵消额外 token、等待时间和协调成本。

### 实验 B：自由文本与结构化 handoff

- 对照组：上游 Agent 只提供自由文本总结；
- 实验组：使用固定字段传递摘要、必需输入、产物、未决问题和风险；
- 下游任务：测试、评审或继续实现同一任务；
- 指标：澄清次数、遗漏约束数、无效工具调用、完成时间、结果正确率和人工修订
  handoff 的字数；
- 分析重点：结构化 handoff 是否减少上下文丢失，以及收益是否随任务长度增加。

实验记录应保留 Agent 与模型版本、prompt、仓库 commit、工具权限、运行时间和
失败日志。公开数据前需删除凭据、个人信息和内部仓库内容。

## 七、局限

- 本报告没有使用需要付费账号或企业租户的功能，不能验证所有权限和审计选项。
- 不同产品对 “Agent”“workflow”“human-in-the-loop” 的定义不同，表格只按
  实际执行边界归一化比较。
- 本报告不评价模型能力排名；模型、产品权限和计费变化不应被误认为编排架构
  本身的优劣。
- OpenHands 与 AutoGen 在调研时均发生了明显产品演进，后续引用应重新核对
  官方文档。

## 八、官方来源

- HALF：[README](https://github.com/keting/half/blob/main/README.md)、
  [Architecture](https://github.com/keting/half/blob/main/docs/architecture.md)
- AutoGen：[官方仓库](https://github.com/microsoft/autogen)、
  [Microsoft Agent Framework](https://github.com/microsoft/agent-framework)
- CrewAI：[官方仓库](https://github.com/crewAIInc/crewAI)、
  [Human-in-the-Loop](https://docs.crewai.com/en/learn/human-in-the-loop)
- LangGraph：[官方仓库](https://github.com/langchain-ai/langgraph)、
  [Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
- MetaGPT：[官方仓库](https://github.com/FoundationAgents/MetaGPT)、
  [官方文档](https://docs.deepwisdom.ai/main/en/guide/get_started/introduction.html)
- OpenHands：[官方仓库](https://github.com/OpenHands/OpenHands)、
  [Agent Canvas](https://docs.openhands.dev/openhands/usage/agent-canvas/overview)
- Claude Code：[官方仓库](https://github.com/anthropics/claude-code)、
  [官方文档](https://code.claude.com/docs/en/overview)
- Codex：[官方仓库](https://github.com/openai/codex)、
  [官方文档](https://developers.openai.com/codex/)、
  [Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)
- GitHub Copilot cloud agent：
  [官方文档](https://docs.github.com/en/copilot/concepts/agents/cloud-agent/about-cloud-agent)
