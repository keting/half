# HALF Labels 说明

[English](./labels.md) | [简体中文](./labels.zh-CN.md)

Labels 用于帮助贡献者判断任务类型、状态、难度和影响范围。实际标签以 GitHub
仓库为准；如果本文档与仓库 labels 不一致，请以仓库当前配置为准，并欢迎
提交文档修正。

## 新手友好

- `good first issue`：适合第一次参与的任务，范围较小，预期不需要理解复杂
  架构。
- `help wanted`：维护者欢迎社区协助，但不一定适合作为第一次贡献。

## 状态

- `status:ready`：任务目标和完成标准已经比较清楚，可以认领。
- `status:needs-discussion`：还需要先讨论目标、范围、方案或验收标准。
- `status:blocked`：当前被外部依赖、设计决策、权限或其他任务阻塞。
- `status:backlog`：明确但暂不排期。

## 类型

- `type:bug`：可复现缺陷、回归问题或错误行为。
- `type:feature`：明确的新能力或行为改进。
- `type:docs`：README、Quick Start、User Manual、FAQ、截图、demo 文档等。
- `type:test`：测试补充、测试稳定性或 CI 相关工作。
- `type:research`：论文、系统、benchmark、evaluation、agent 协作模式等研
  究型输入。
- `type:security`：安全、权限、敏感信息或威胁模型相关工作。重大安全问题
  不应公开创建 Issue，请按 SECURITY 文档报告。

## 影响范围

- `area:frontend`：前端页面、组件、样式、交互或前端测试。
- `area:backend`：后端 API、数据库模型、服务层、权限、轮询和后端测试。
- `area:docs`：公开文档、截图、demo 文档或 contributor docs。
- `area:workflow`：workflow 模板、handoff prompt、plan DAG case 或任务生命
  周期。
- `area:security`：认证、授权、仓库访问、敏感信息边界或安全配置。

## 优先级

- `priority:high`：影响核心流程、安全边界或阻塞当前 milestone。
- `priority:medium`：重要但不阻塞当前核心流程。
- `priority:low`：有价值但可以延后。

## 使用建议

- 初次贡献优先选择 `good first issue` 或 `type:docs`。
- 想认领工程任务时，优先选择 `status:ready`。
- 如果一个 Issue 缺少完成标准，可以先帮助补充信息，而不是直接开发。
- 如果想法还处于探索阶段，请使用 Discussion，不要强行加 `status:ready`。
