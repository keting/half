# ADR 0003: 执行边界与 Agent 集成

状态: proposed

## 背景

HALF 当前通过 human-in-the-loop 派发来协调 AI 编码工作：系统生成提示，人工操作员发送给 agent，HALF 通过 Git 制品跟踪结果。此边界保持系统与常见订阅制 coding agent 兼容，这些 agent 并非设计为通过第三方自动化调用。

未来版本可能支持暴露官方 API 和用户管理 API key 的 agent。此路径应与私有 API、UI 自动化、逆向工程或凭证共享区分开来。

## 决策

HALF v0.3 保持手工派发作为默认执行边界。

未来版本可能仅通过显式、用户配置的、官方支持的基于 API 的集成来支持自动化 agent 调用。

HALF 不会依赖私有 API、UI 自动化、逆向工程或凭证共享来自动化订阅制 coding agent。

## 后果

以下方向需要未来设计审查后才能实施：

- 本地 Agent 桥接
- API Agent 连接器
- 配额感知执行
- 受控自动化

本 ADR 不阻塞未来基于 API key 的自动化。它定义了此类集成必须遵守的合规边界。
