# Security Policy

[English](./SECURITY.md) | [简体中文](./SECURITY.zh-CN.md)

## Reporting A Vulnerability

Please report security issues privately to `osscontact@163.com`. Do not open
public issues for security problems.

We will acknowledge reports within 5 business days.

## Trust Model

HALF is designed for **single-tenant self-hosting**. The deployment model
assumes:

- The administrator and users all belong to the same organization.
- At the application layer, business resources are owner-scoped. Regular users
  cannot access each other's projects, agents, plans, tasks, or polling records.
  Administrators use separate management surfaces, but application APIs do not
  depend on administrators taking over user-owned projects.
- At the deployment layer, the administrator or host operator is fully trusted:
  they can access the HALF database, repository clones, container volumes, host
  filesystem mounts, and git remotes configured for HALF.
- Process templates are shared resources: all logged-in users can list, view,
  and use templates, while only the creator or an administrator can update or
  delete them.

HALF is not suitable for hosting untrusted users.

## Threat Model

In scope:

- **SSRF via user-supplied git URLs.** `src/backend/validators/git_url.py`
  rejects `file://`, `ext::`, injection-prefix strings, loopback/private
  network hosts, and the AWS metadata IP.
- **Weak default credentials.** The backend refuses to start when
  `HALF_STRICT_SECURITY=true` and either `HALF_SECRET_KEY` or
  `HALF_ADMIN_PASSWORD` is weak. This is the default in the bundled
  `docker-compose.yml`.
- **Open registration.** Self-registration is off by default
  (`HALF_ALLOW_REGISTER=false`). When enabled for demo deployments, the server
  assigns `role=user` and ignores client-supplied role / status fields.
- **Login brute force.** A per-username rate limiter is applied in
  `src/backend/middleware/rate_limit.py`.

Out of scope in v0.x:

- Hardened multi-tenant isolation
- Supply-chain attestation of installed dependencies
- Formal cryptographic review

## Mandatory Configuration

Before exposing HALF beyond localhost:

1. Set `HALF_SECRET_KEY` to a value generated with
   `python3 -c 'import secrets; print(secrets.token_urlsafe(48))'`.
2. Set `HALF_ADMIN_PASSWORD` to a value that is at least 8 characters long and
   contains uppercase, lowercase, and digits.
3. Leave `HALF_STRICT_SECURITY=true` and `HALF_ALLOW_REGISTER=false` unless you
   have a reason to change them.
4. Do not mount your host `~/.ssh` directory into the container. Use a
   dedicated deploy key via `docker-compose.override.yml`.
5. Put HALF behind a reverse proxy that terminates TLS.

## CORS

`HALF_CORS_ORIGINS` defaults to local development origins only. Set it
explicitly in production.
