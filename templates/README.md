# HALF 流程模板示例

本目录提供可复用的流程模板 JSON，帮助用户从常见协作流程开始使用 HALF，
而不必从空白模板设计任务 DAG。

## 示例列表

| 文件 | 场景 | 协作方式 |
|---|---|---|
| [`bug-fix-with-dual-review.json`](./bug-fix-with-dual-review.json) | 复现、修复并验证一个 Bug | 一个 Agent 负责修复，两个 Agent 并行测试和评审 |
| [`feature-development-with-dual-review.json`](./feature-development-with-dual-review.json) | 设计、实现并验收一个功能 | 一个 Agent 负责开发，两个 Agent 并行验收和评审 |

两个示例均采用 `1+2` 协作方式：`agent-1` 负责主要工作，`agent-2` 和
`agent-3` 在主任务完成后从不同角度独立检查，最后由 `agent-1` 汇总结论并
完成交付。使用模板时，需要将这些槽位分别绑定到项目中可用的 Agent。

## 使用方法

HALF 当前不支持直接从文件导入模板，需要手动复制 JSON：

1. 打开需要使用的 `.json` 文件并复制完整内容。
2. 在 HALF 中进入“流程模板”，选择“新建流程模板”。
3. 将内容粘贴到“模板 JSON”输入框，点击“预览 JSON”。
4. 检查自动填充的模板名称、描述、Agent 角色和任务 DAG。
5. 根据项目需要调整任务描述和角色说明，然后保存模板。

示例文件只对应创建页面中的“模板 JSON”字段。必需输入等其他字段需要在
页面中单独配置。

## 贡献新模板

新增模板时，请保持一个文件只描述一种明确的协作流程，并满足以下要求：

- 文件名使用小写英文和连字符，扩展名为 `.json`。
- `tasks` 非空，且每个 `task_code` 在模板内唯一。
- `task_name` 和 `description` 清楚说明任务目标与交付要求。
- `assignee` 使用 `agent-N` 槽位，不绑定具体 Agent。
- `depends_on` 只引用模板内已有任务，并保持任务图无环。
- `expected_output` 使用仓库内相对路径，例如
  `outputs/TASK-001/result.json`。
- 在本文件的示例列表中补充模板用途和协作方式。

提交前运行后端测试，确认所有示例都能通过当前模板 schema 校验：

```bash
cd src/backend
uv run pytest tests/test_process_template_examples.py -v
```
