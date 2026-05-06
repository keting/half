# HALF 快速入门指南

[English](./quickstart.md) | [简体中文](./quickstart.zh-CN.md)

本指南介绍在干净环境中首次运行 HALF 的完整流程。

## 前置要求

- Docker 20.10+ 和 Docker Compose v2+
- 2GB 可用内存
- 端口 3000（前端）和 8000（后端）可用，或配置自定义端口

## 步骤 1：配置环境

```bash
cd src
cp .env.example .env
```

编辑 `.env` 并设置**必需**值：

```bash
# 生成安全随机密钥：
# python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
HALF_SECRET_KEY=your-generated-secret-key

# 至少 8 个字符，包含大写字母、小写字母和数字
HALF_ADMIN_PASSWORD=YourSecurePass123
```

可选设置：

```bash
# 设为 'false' 以不带演示项目启动
HALF_DEMO_SEED_ENABLED=true

# 允许自助注册（默认：false，仅供内部演示启用）
HALF_ALLOW_REGISTER=false
```

## 步骤 2：启动服务

```bash
docker compose up -d --build
```

等待服务健康，通常 10-30 秒：

```bash
docker compose ps
```

应看到：

- `src-backend-1` 状态：`healthy`
- `src-frontend-1` 状态：`running`

## 步骤 3：首次登录

在浏览器中打开 `http://localhost:3000`。

登录凭证：

- 用户名：`admin`
- 密码：你在 `.env` 中设置的 `HALF_ADMIN_PASSWORD` 值

## 步骤 4：浏览演示项目

首次启动时，HALF 会初始化演示项目：

- **名称**：`(Demo) 修复一个bug`
- **仓库**：`https://github.com/keting/half.git`
- **状态**：包含已完成、就绪、阻塞等不同状态的任务

导航到项目可查看：

1. **任务看板** - 按状态分栏的任务视图
2. **DAG 视图** - 可视化依赖图
3. **任务队列** - 可执行的任务
4. **Handoff 提示** - 为 Agent 生成的提示

演示仅用于浏览和理解产品形态。HALF 不会自动执行 Agent。

## 步骤 5：创建你的第一个项目

1. 点击"新建项目"。
2. 填写表单：
   - **项目名称**：你的项目名称
   - **项目目标**：你想完成的描述
   - **Git 仓库地址**：必填的仓库根地址或 clone URL，如
     `https://github.com/your/repo` 或 `https://github.com/your/repo.git`
   - **协作目录**：输出的相对路径，如 `projects/my-project`
   - **轮询间隔**：检查任务完成的频率
   - **任务超时**：任务超时时间（分钟）
3. **选择 Agent**（必需）：
   - 必须从列表中选择至少一个 Agent
   - 预置演示 Agent 包括 Claude Max、Codex Pro、Copilot Pro
   - 按需为每个 Agent 配置同机部署设置
4. 点击"创建项目"。

## 步骤 6：生成计划

1. 打开你的项目。
2. 打开 Plan 页面并选择流程来源。
3. 如果使用模板路径：
   - 选择流程模板
   - 将每个模板角色槽位映射到项目 Agent
   - 填写必填输入
   - 点击"下一步"创建可执行任务并进入任务页面
4. 如果使用 Prompt 路径：
   - 按需选择规划 Agent 和模型
   - 点击"生成 Prompt"
   - 点击"拷贝 Prompt"，并将 prompt 粘贴到规划 Agent UI
   - 等待规划结果写回 Git；HALF 检测到合法计划后会自动定稿并进入任务页面

常见必填输入可能包括：

- `docPath`：PRD 或规格文档路径
- `test_url`：测试 URL（如适用）
- 其他模板特定输入

HALF 将：

- 基于所选模板或检测到的规划结果创建任务 DAG
- 分配任务给选定的 Agent
- 为每个任务创建 handoff 提示

## 步骤 7：派发和执行任务

1. 进入任务列表标签页。
2. 找到状态为"待处理"的任务。
3. 点击"复制 Prompt 并派发"，复制提示并将任务标记为已派发。
4. 将已复制的提示粘贴到你的 Agent UI。
5. Agent 在 Git 仓库中工作。
6. HALF 轮询 `result.json` 以检测完成。

## 故障排除

### 服务启动失败

检查日志：

```bash
docker compose logs backend
docker compose logs frontend
```

端口冲突：

如果端口 3000 或 8000 被占用，编辑 `docker-compose.yml`：

```yaml
frontend:
  ports:
    - "3001:80"  # 更改主机端口

backend:
  ports:
    - "8001:8000"  # 更改主机端口
```

弱密码错误：

HALF 拒绝以弱默认值启动。确保：

- `HALF_SECRET_KEY` 已设置且足够随机
- `HALF_ADMIN_PASSWORD` 至少 8 个字符，且包含大写字母、小写字母和数字

### 登录失败

- 验证 `.env` 中的 `HALF_ADMIN_PASSWORD`
- 检查浏览器控制台是否有 CORS 错误
- 确保使用 `http://localhost:3000`，而非 `https`

### "必须选择至少一个 Agent"错误

创建项目时，必须：

1. 从列表中选择至少一个 Agent。
2. 按需配置 Agent 分配设置。

### 演示项目未显示

检查是否启用了初始化：

```bash
HALF_DEMO_SEED_ENABLED=true docker compose up -d
```

### Git 仓库访问失败

对于私有仓库，将 `src/docker-compose.override.yml.example` 复制为
`src/docker-compose.override.yml` 并挂载专用 deploy key。不要将整个
`~/.ssh` 目录挂载到容器中。
私有仓库建议使用专用 SSH deploy key、credential helper 或后端容器专门配置
的凭据；不要把 access token 或 password 写进仓库 URL。

HALF 接受仓库根地址和 clone URL，例如 `https://github.com/org/repo`、
`https://github.com/org/repo.git`、`ssh://git@github.com/org/repo.git`、
`git@github.com:org/repo.git`。GitHub、Gitee、Bitbucket、Codeberg 的仓库
根地址必须是 `owner/repo` 两段；GitLab 也接受
`https://gitlab.com/group/subgroup/repo` 这类 subgroup 仓库根地址。不要填写
issues、pull、tree、blob、graphs 等仓库内页面 URL。带有不安全协议、query、
fragment，或在 userinfo、query、fragment 中内嵌凭据、access token、deploy
token，以及本地/内网地址的 URL 会被拒绝。

保存时只做 URL 格式和安全校验，不证明仓库真实存在，也不证明后端容器已有访问
权限。如果仓库不存在或容器缺少凭据，后续 Git 同步和轮询会失败，项目页面会显示
仓库访问错误并由 HALF 自动重试。

## 下一步

- 阅读 [architecture.md](./architecture.md) 了解系统设计。
- 阅读 [task-lifecycle.md](./task-lifecycle.md) 了解任务状态流转。
- 在 `http://localhost:8000/docs` 查看 API 文档。

## 清理

移除所有数据并重新开始：

```bash
docker compose down -v
```

这会移除容器和卷，包括 SQLite 数据库和克隆的仓库。
