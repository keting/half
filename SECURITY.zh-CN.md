# 安全政策

[English](./SECURITY.md) | [简体中文](./SECURITY.zh-CN.md)

## 报告漏洞

请通过邮件 `osscontact@163.com` 私下报告安全问题。不要为安全问题开公开 issue。

我们将在 5 个工作日内确认收到报告。

## 信任模型

HALF 设计用于**单租户自托管**。部署模型假设：

- 管理员和用户都属于同一组织。
- 在应用层，业务资源按所有者隔离。普通用户无法访问彼此的项目、私有 agent、计划、任务或轮询记录。管理员创建的 agent 构成公共 agent 池：活跃公共 agent 对所有登录用户可见且可用，但只有创建该公共 agent 的管理员可以修改、停用、重置或删除它。管理员不能查看或接管普通用户的私有 agent。管理员使用独立的管理界面，但应用 API 不依赖管理员接管用户拥有的项目。
- 在部署层，管理员或主机操作员被完全信任：他们可以访问 HALF 数据库、仓库克隆、容器卷、主机文件系统挂载和为 HALF 配置的 git 远程地址。
- 流程模板是共享资源：所有登录用户都可以列出、查看和使用模板，但只有创建者或管理员可以更新或删除模板。

HALF 不适合托管不受信任的用户。

## 威胁模型

范围内：

- **用户提供的 git URL 导致的 SSRF。** `src/backend/validators/git_url.py` 拒绝 `file://`、`ext::`、注入前缀字符串、回环/私有网络主机和 AWS 元数据 IP。
- **弱默认凭证。** 当 `HALF_STRICT_SECURITY=true` 且 `HALF_SECRET_KEY` 或 `HALF_ADMIN_PASSWORD` 为弱密码时，后端拒绝启动。这是捆绑的 `docker-compose.yml` 中的默认设置。
- **开放注册。** 自助注册默认关闭（`HALF_ALLOW_REGISTER=false`）。为演示部署启用时，服务器分配 `role=user` 并忽略客户端提供的角色/状态字段。
- **登录暴力破解。** `src/backend/middleware/rate_limit.py` 中应用了按用户名的速率限制。

v0.x 范围外：

- 加固的多租户隔离
- 已安装依赖的供应链证明
- 正式密码学审查

## 强制配置

在将 HALF 暴露到本地主机之外之前：

1. 将 `HALF_SECRET_KEY` 设置为使用 `python3 -c 'import secrets; print(secrets.token_urlsafe(48))'` 生成的值。
2. 将 `HALF_ADMIN_PASSWORD` 设置为至少 8 个字符且包含大写、小写和数字的密码。
3. 保持 `HALF_STRICT_SECURITY=true` 和 `HALF_ALLOW_REGISTER=false`，除非有理由更改。
4. 不要将主机的 `~/.ssh` 目录挂载到容器中。使用通过 `docker-compose.override.yml` 配置的专用 deploy key。
5. 将 HALF 放在终止 TLS 的反向代理后面。

## CORS

`HALF_CORS_ORIGINS` 默认仅允许本地开发来源。生产环境请显式设置。
