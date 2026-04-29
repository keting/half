# HALF 贡献指南

[English](./CONTRIBUTING.md) | [简体中文](./CONTRIBUTING.zh-CN.md)

HALF 仍处于早期开源阶段（v0.x），当前主要维护者人数有限。请尽量保持变更小
而清晰；较大的想法请先通过 issue 或 discussion 对齐范围。

## 开始之前

1. 先搜索已有 issue 和 pull request，确认是否已经有人报告或处理。
2. 对于较大改动，请先开 issue 或 discussion，再提交 PR。
3. 较大重构前，请先阅读 [`docs/architecture.md`](./docs/architecture.md)
   和 [`docs/task-lifecycle.md`](./docs/task-lifecycle.md)；如需定位模块，
   请参考 [`docs/project-structure.md`](./docs/project-structure.md)。

## Issue 与 Discussion

请根据问题的确定程度选择合适入口：

- 创建 issue：<https://github.com/keting/half/issues/new/choose>
- 发起 discussion：<https://github.com/keting/half/discussions/new/choose>

### 适合直接创建 Issue

如果事项已经比较明确、可以被修复、实现或验收，请直接创建 issue：

- 可复现的 bug、回归问题或错误提示
- 安全、权限、数据一致性、部署失败等风险问题
- 明确的小功能或 UI / 文档改进
- 文档缺口、示例缺口、截图 / demo 素材补充
- 已经在 roadmap / tracking issue 中确认的任务
- 可以写出清晰验收标准的工作项

Issue 应尽量包含背景、复现步骤或目标行为、预期结果、实际结果、验收标准，
以及相关截图、日志或链接。

### 建议先发 Discussion

如果事项还处在探索阶段，范围较大，或者可能影响产品方向，请先发
discussion：

- 大型功能或跨模块能力
- 会影响数据模型、API、权限模型、任务生命周期的改动
- 需要拆成多个子任务的 epic
- 未来 roadmap 的候选承诺项
- 可能改变 HALF 产品定位或边界的设计
- 还没有明确验收标准、需要先比较多个方案的问题
- 研究性想法、论文 / 实验方向、长期演进主题

Discussion 的目标是先对齐问题、目标、非目标、方案和风险。方向明确后，维
护者可以创建 tracking issue 或拆分为具体 implementation issues，并视情况
加入 milestone。

简单原则：明确可执行的开 issue；需要先讨论边界和方案的开 discussion。

## 开发环境

请参考 [`README.zh-CN.md`](./README.zh-CN.md) 中的本地开发说明。
后端测试依赖位于
[`src/backend/requirements-dev.txt`](./src/backend/requirements-dev.txt)。

## 运行测试

```bash
cd src/backend && python -m pytest tests/ -v
cd src/frontend && npm test && npm run build
```

如果 PR 导致上述任一测试或构建流程失败，将不会被合并。

## Pull Request 检查清单

- [ ] 本地测试通过（`pytest` + `npm test` + `npm run build`）。
- [ ] 新行为有对应测试覆盖。
- [ ] 如果修改了环境变量，已同步更新 `src/.env.example`。
- [ ] 如果修改了 API 形状或数据模型，已按需更新 `docs/architecture.md`
      （字段级 API 签名由 FastAPI `/docs` 自动生成）。
- [ ] Commit message 说明了为什么改，而不只是改了什么。
- [ ] diff 中不包含密钥、私有 URL 或个人本机路径。

## UI 文案与 i18n

当前 UI 主要为简体中文。欢迎补充英文 i18n，但请优先提交独立的 i18n PR，
不要把翻译工作混入无关功能改动。

## 代码风格

- Backend：遵循现有代码风格
- Frontend：遵循现有代码风格

## 许可证

提交贡献即表示你同意你的贡献使用 Apache License, Version 2.0 授权。
