# HALF 贡献指南

[English](./CONTRIBUTING.md) | [简体中文](./CONTRIBUTING.zh-CN.md)

HALF 仍处于早期开源阶段（v0.x），当前主要维护者人数有限。请优先提交小而
清晰、可 review 的变更；较大的想法请先通过 Issue 或 Discussion 对齐范围。

## 项目阶段与贡献原则

- HALF 的接口、数据模型和产品边界仍可能调整。
- 小改动优先，避免在一个 PR 中混入无关重构、格式化或大范围翻译。
- 涉及 API、数据模型、权限、安全边界、新模块或产品方向的改动，请先开
  Discussion。
- 维护者会根据 roadmap、维护成本、安全边界和项目定位决定是否接受 Issue
  或 PR；创建 Issue 或提交 PR 不代表一定会被接受。
- 实验室内部材料（机器配置、内部账号、组会节奏等）不要写入公开贡献文档。

## 第一次参与建议路径

如果你刚接触 GitHub 或 HALF，请先阅读
[`docs/newcomer-path.zh-CN.md`](./docs/newcomer-path.zh-CN.md)。推荐顺序是：

1. 读 README，浏览产品截图和 [`ROADMAP.zh-CN.md`](./ROADMAP.zh-CN.md)。
2. 按 [`docs/quickstart.zh-CN.md`](./docs/quickstart.zh-CN.md) 跑通 Demo Project。
3. 阅读 [`docs/project-structure.md`](./docs/project-structure.md)，了解代码组织。
4. 从 `good first issue`、文档改进、bug 复现或截图补充开始。

## 你可以如何参与

### 阅读论文、系统或技术报告，提出 roadmap 启发

如果你阅读到与 AI Coding、Coding Agent、多 agent 协作、人机协同、软件工
程自动化相关的论文、技术报告、开源项目或企业实践案例，并认为其中思想可
能对 HALF 有借鉴价值，请优先创建 Discussion。

Discussion 中建议说明资料链接、核心观点、与 HALF 的关系、可验证假设、可
能落地项和风险。讨论收敛为明确任务后，再由维护者转为 Issue。

### 报告 Bug 或明确需求

如果你发现系统 bug、文档错误、UI/UX 问题、明确新功能、测试缺失、部署或
配置问题，请创建 Issue。Issue 应尽量包含背景、当前行为、期望行为、复现
步骤或目标、影响范围、完成标准，以及相关截图、日志或链接。

安全漏洞、敏感信息泄露、权限绕过或权限模型风险不要提交公开 Issue，请按
[`SECURITY.zh-CN.md`](./SECURITY.zh-CN.md) 报告。

### 讨论不成熟想法、方案对比或研究方向

如果想法还没有明确目标、范围和验收标准，请创建 Discussion，而不是 Issue。
这适用于方向性想法、架构方案对比、roadmap 建议、benchmark / evaluation
设计、研究问题、安全和合规边界讨论。

### 认领 Issue 并提交 PR

浏览 Issues 时，优先选择 `status:ready`；初次参与者优先选择
`good first issue`。认领前请在 Issue 下评论说明你希望处理该任务，避免重
复工作。

从 `main` 创建新分支，完成开发后提交 PR。PR 中应关联 Issue 或 Discussion，
说明改动内容、范围、验证方式和未运行测试的原因（如有）。

### 改进文档、示例和 demo

欢迎修复 README 或文档错误，补充 Quick Start、User Manual、FAQ、截图、
GIF、demo case、开发者说明、测试说明和中英文文档同步。小 typo 可直接 PR；
较大的文档结构调整请先开 Issue 或 Discussion。

### 参与测试、复现和 PR 验证

你可以跑通 Quick Start，验证 Demo Project，复现已有 bug，补充复现步骤、
截图、日志或环境信息，帮助确认 PR 是否解决对应 Issue，或补充缺失测试用例。

### 参与 Issue triage、Discussion、PR Review 和 Milestone 维护

熟悉项目后，可以帮助判断 Issue 是否清楚，补充完成标准，把不成熟想法引导
到 Discussion，Review PR 是否解决对应 Issue，检查是否存在超范围改动，并
协助维护 Milestone 和 Roadmap。

### 贡献 workflow 模板、handoff prompt 和 plan DAG case

HALF 关注 AI coding agent 的人机协作流程。欢迎贡献可复用 workflow 模板、
handoff prompt、plan DAG case、demo collaboration case，以及这些流程适用
的场景说明。

### 记录 agent 协作失败模式与人工介入点

研究型贡献可以包括可复现实验记录、agent 协作失败模式、人工介入点、任务
拆分质量观察、人工协调成本观察等。此类材料通常先进入 Discussion，收敛后
再整理为文档、demo 或 benchmark case。

### 提供 UI/UX 可用性反馈

欢迎提交可用性测试记录、截图标注、用户路径反馈、术语不清晰处和操作阻塞
点。明确的小问题可以开 Issue，较大的交互方向建议先 Discussion。

### 设计 Benchmark / Evaluation case

欢迎讨论 agent 协作效果评估、任务拆分质量评估、人工协调成本评估、评测脚
本和数据集。此类贡献通常先通过 Discussion 对齐目标、范围、指标和风险。

### 文档翻译与术语统一

欢迎补充英文 i18n、文档翻译和术语统一。请尽量使用独立 PR，不要把翻译混
入无关功能改动。

### 安全、合规和权限边界建议

涉及威胁模型、权限模型、仓库访问、敏感信息边界、agent 使用合规边界的建
议可以创建 Discussion。重大安全风险请按 SECURITY 文档私下报告。

### 持续参与后申请成为 Collaborator

持续高质量参与 HALF 后，可以向维护者表达成为 Collaborator 的意愿。该权
限不会自动授予，也不代表获得全部仓库权限。维护者会根据贡献记录、协作质
量、review 能力和项目需要，按最小必要原则逐步授予权限。

Collaborator 可以参与 PR Review、Issue triage、Milestone 管理、Roadmap 讨
论、文档维护和新贡献者引导。

## Issue / Discussion / PR 如何选择

简单原则：明确可执行、可验收的事项开 Issue；需要先讨论目标、边界、方案
或价值的问题开 Discussion；小 typo、小文档修复和已有 Issue 的小范围修复
可以直接 PR。

### 创建 Issue

适合直接创建 Issue 的情况：

- 可复现 bug、回归问题或错误提示。
- 明确文档错误、UI/UX 问题、测试缺失、部署或配置问题。
- 小型功能改进。
- 已经从 Discussion 收敛出来的任务。
- 可以写出完成标准的工作。

### 创建 Discussion

适合先创建 Discussion 的情况：

- 论文、系统或技术报告带来的启发。
- Roadmap 建议、架构方向、多方案对比。
- Benchmark / evaluation 设计。
- 安全、合规或权限边界讨论。
- 还无法写出验收标准的想法。

### Discussion 转 Issue 的条件

只有当 Discussion 已经收敛出以下内容时，才建议由维护者转为 Issue：

- 明确目标。
- 明确范围。
- 明确非目标。
- 可执行任务。
- 验收标准。
- 大致优先级或 milestone 判断。

### PR 提交规则

| 改动类别 | 是否需要前置 Issue / Discussion |
|---|---|
| typo、小文档修复、小测试补充 | 可直接 PR |
| 已有关联 Issue 的小范围修复 | 可直接 PR |
| 小型新功能（不改公开 API、不动数据模型、不引入新模块） | 可直接 PR，但 PR 描述需说明动机或关联 feature request |
| 中大型新功能（改公开 API、数据模型、新模块、权限或安全边界） | 必须先 Discussion，由维护者评估后转 Issue，再开 PR |
| 大型重构、无关格式化 | 不接受混入功能 PR |

维护者保留要求先开 Discussion、拆分 PR 或关闭不符合 roadmap 的 PR 的权利。

## Issue 写作要求

请根据模板填写，尽量包含：

- 背景。
- 当前行为。
- 期望行为。
- 复现步骤或实现目标。
- 影响范围。
- 完成标准或验收标准。
- 截图、日志、链接或相关资料。

## Discussion 写作要求

Discussion 建议包含：

- 背景资料或链接。
- 核心观点。
- 与 HALF 的关系。
- 可验证假设。
- 可能落地项。
- 风险和非目标。
- 希望社区讨论的问题。

## Pull Request 要求

- 保持小而聚焦，避免无关重构混入。
- 关联 Issue 或 Discussion。
- 描述为什么改、改了什么、如何验证。
- UI 改动附截图或录屏。
- API、配置、数据模型或部署行为变化应同步更新文档。
- 本地测试与 build 通过。
- 不包含密钥、私有 URL、access token 或个人本机路径。
- 推荐但不强制使用 Conventional Commits 风格。

## 本地开发和测试

请参考 [`README.zh-CN.md`](./README.zh-CN.md) 中的本地开发说明。后端测试
依赖通过 `uv sync` 安装（由 `pyproject.toml` 管理）。

```bash
cd src/backend && uv run python -m pytest tests/ -v
cd src/frontend && npm test && npm run build
```

如果 PR 导致上述任一测试或构建流程失败，将不会被合并。

## Labels 简介

常用 labels 说明见 [`docs/labels.zh-CN.md`](./docs/labels.zh-CN.md)。核心
labels 包括：

- `good first issue`
- `status:ready`、`status:needs-discussion`、`status:blocked`
- `type:bug`、`type:docs`、`type:research`、`type:test`
- `area:frontend`、`area:backend`、`area:docs`

## 安全问题

如果发现安全漏洞、敏感信息泄露、权限绕过或其他安全风险，请不要创建公开
Issue。请按 [`SECURITY.zh-CN.md`](./SECURITY.zh-CN.md) 报告。

## 行为规范

请遵守 [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md)。我们希望 HALF 的公
开协作保持尊重、聚焦、包容和可执行。

## 许可证

提交贡献即表示你同意你的贡献使用 Apache License, Version 2.0 授权。

## GitHub 协作流程

详细 GitHub 协作流程请参考
[`github-collaboration-workflow.md`](https://github.com/keting/aicoding/blob/main/docs/github-collaboration-workflow.md)。

HALF 特定的贡献说明请结合本文档阅读。如果通用协作规范与本文档存在差异，
HALF 仓库以内本文档中的本地约定为准。
