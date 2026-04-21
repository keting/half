# 开源准备阶段二 — Code Review（Claude）

- **仓库：** `keting/half`
- **审查分支：** `audit/stage1-open-source`
- **基线：** `cff0db0`（阶段一收尾）
- **提交：** `0fbbb27 docs: package repo as public project`
- **范围：** 阶段二（公开仓库包装、根部文档补齐、agent-facing 文件清理、docs 补拷、LICENSE 移动）

## Findings

### Med-1 — 阶段二补拷的 PRD / tech_spec 还在宣传已废弃的"6 位密码"规则
- **Severity:** Medium
- **Files/Lines:** `docs/prd_final.md:50`, `docs/prd_final.md:98`, `docs/prd_final.md:142`, `docs/prd_final.md:152`; `docs/tech_spec.md:315`
- **Problem:** 四处在 PRD、一处在 tech_spec 仍然写"密码要求包含大小写字母和数字，最少8位 / ≥8位"。而 stage-1 已经把前后端密码规则统一到 **8 位**：后端 `_PASSWORD_PATTERN = .{8,}`、前端 `LoginPage.tsx` / `Layout.tsx` 全部走 8 位、登录页错误文案已改为"密码至少需要8位"。同一份 PRD 的 `docs/prd_final.md:749` 环境变量表里又正确地写了"≥8 字符,大小写+数字"，前后矛盾。
- **Why it matters:** 这正是 stage-1 goal #5 "统一密码规则到 8 位 + 大小写 + 数字"。公开仓库的 PRD 和 tech_spec 是外部读者最权威的接口契约入口，如果文档继续告诉贡献者 / 用户"最少 6 位"，他们按文档写出的集成代码和测试都会和线上实现对不上；同时也让 stage-1 的硬化在文档层面看起来像是被回退了。

### Med-2 — PRD / tech_spec 仍在使用已删除的 `HALF_CORS_ORIGINS` 环境变量名
- **Severity:** Medium
- **Files/Lines:** `docs/prd_final.md:751`, `docs/tech_spec.md:592-593`
- **Problem:** Stage-1 把 CORS 环境变量收敛成 `HALF_CORS_ORIGINS`（后端 `config.py`、`.env.example`、`README`、`SECURITY.md` 全部使用新名），同时删除了"未提供时降级为通配 `*`、`allow_credentials=False`"的 fallback 分支。但被补拷进公开仓的文档：
  - `prd_final.md:751` 的配置表还叫 `HALF_CORS_ORIGINS`，并把"空值时禁用 credentials"作为正式行为描述。
  - `tech_spec.md:592-593` 既叫 `HALF_CORS_ORIGINS`，又在 8.2 节描述"未提供时,降级为通配 `*` 但 **强制** `allow_credentials=False`,封堵 `*+credentials` 的 CSRF 误用"——这一路径在 `src/backend/main.py:408-410` 里已经不存在。
- **Why it matters:** 外部部署者按文档去设 `HALF_CORS_ORIGINS` 时会默默失效（后端根本不读这个名字），CORS 配置直接落回默认 localhost allowlist；而他们在文档里看到的"空值 → 通配 + 不带 credentials"又是死的行为。这同时是 (a) 文档与运行时不一致引发的配置错误来源 和 (b) 阶段一已完成工作在公开文档面前被否认。

### Med-3 — CONTRIBUTING 承诺的 `ruff` / `black` / `eslint` / `prettier` 配置实际并不存在
- **Severity:** Medium
- **File/Line:** `CONTRIBUTING.md:41-44`
- **Problem:** 文件写的是：
  > ## Code Style
  > - Backend: `ruff` defaults, `black` 88-column line length
  > - Frontend: `eslint` + `prettier` configs in the repo

  但仓库里没有 `pyproject.toml` / `ruff.toml` / `.ruff.toml` / 任何 `black` 配置；`src/backend/requirements.txt` 也没有 `ruff` / `black`；`src/frontend/` 下没有 `.eslintrc*` / `.prettierrc*` / `eslint.config.*`；`package.json` 的 `devDependencies` 只有 `@types/react`、`@vitejs/plugin-react`、`typescript`、`vite`、`vitest`，没有 `eslint` / `prettier`。PR checklist 第 2 条还要求"Tests pass locally"——那条能跑，但 code style 这条实际上无从校验。
- **Why it matters:** 这是公开仓对外承诺的贡献者契约。新 contributor 按文档去 `ruff format` / `black` / `npm run lint` 会立刻发现环境里没装、也没配，产生 friction；或者更糟，自带版本一跑就把代码风格改成与仓库实际风格不同的样子。要么补上这些配置和依赖，要么把这段改成"暂无统一 lint/format 配置，风格以现有代码为准"。

### Low-1 — stage-1 审计报告 `os/stage1-review-claude.md` 被打包进了要公开的分支
- **Severity:** Low
- **File/Line:** `os/stage1-review-claude.md`（根部 60 行）
- **Problem:** 这个文件是上一轮按要求写进 `audit/stage1-open-source` 的内部审计报告。它在第 47 行明确写出 `example-org/example-repo` 和 `git@github.com:example-org/example-repo.git` 的字面值（作为"已清零"的历史说明），还提到 `_DEFAULT_INSECURE_PASSWORDS`、"stage-1 / cff0db0" 等只对内部读者有意义的内容。现在它和 README、docs 一起躺在仓库根下的 `os/` 目录，没有被 `.gitignore` 排除。本份 stage-2 审计报告（`os/stage2-review-claude.md`）同样写进 `os/`，问题范围扩大到整个 `os/` 目录。
- **Why it matters:** 阶段二的目标之一是"移除公开仓库中的 agent-facing 文件"。审计/Review 报告严格来说不是 agent-facing，但它 (a) 公开命名了那个私有/已清零的测试仓 `example-org/example-repo`（外部读者只会从这里首次知道该路径的存在），(b) 公开放在了非文档目录 `os/` 下，没有在 README / CONTRIBUTING 里被任何链接引用，看起来像忘了清理的历史工件。在正式打 tag / 对外宣发之前，建议把整个 `os/` 目录从公开分支里删掉（或者把 `os/` 加进 `.gitignore` 并从 tracked 列表移除），或者把对私有仓名字的直接引用改写成中性描述。

### Low-2 — 文档里残留实验室内部工单 / 测试报告路径，公开仓读者无法理解也无法打开
- **Severity:** Low
- **Files/Lines:** `docs/prd_final.md:742`（"依据 0408 全面测试报告(`outputs/proj-10-059e7d/log/0408testResult.md`)与 T1-ANALYZE 修复方案"）、`docs/tech_spec.md:581`（"依据 0408 测试报告与 T1-ANALYZE"）、`docs/tech_spec.md:701`（标题"8.13 Plan 页 0419 稳定性修正"）。
- **Problem:** `outputs/proj-10-059e7d/log/0408testResult.md` 这个路径在公开仓不存在，是某个内部项目（项目 id=10、后缀 059e7d）产出的测试报告。`T1-ANALYZE` / `T2-CODE-FIX` / `0408` / `0419` 是内部工单/迭代日期代号，对外部 reader 毫无语义。
- **Why it matters:** 不算严重泄漏，但属于"公开文档里引用了外部不可达的资源"，会让新来的 reader 觉得这份 spec 是从某个更完整的仓库搬过来、但没做过 sanitize。建议把"依据 0408 测试报告 / T1-ANALYZE / T2-CODE-FIX"之类的依据去掉（变成"本节固化当前安全与主流程约束"这种中性表达），并直接删掉那个 `outputs/proj-10-...` 链接。

### Low-3 — tech_spec 8.1 把"非 strict 时只 warning、允许启动"当正式行为描述，与 stage-1 的默认 true 相悖
- **Severity:** Low
- **File/Line:** `docs/tech_spec.md:587`
- **Problem:** 原文："`HALF_STRICT_SECURITY=true` 时,违规直接 `SystemExit(1)`;否则记录 ERROR 级警告但允许启动(避免破坏现有 dev 环境)"。Stage-1（cff0db0）已经把 Python 侧的 `HALF_STRICT_SECURITY` 默认值改成 `"true"`，compose 里也是 `:-true`，`.env.example` 推荐值也是 `true`。spec 还像是在解释"默认 false、避免破坏 dev"那套旧逻辑。
- **Why it matters:** 读者会以为 HALF 的默认是"宽松启动，打个 warning"，据此做部署判断就会踩坑：他们以为"没设环境变量也能起来"，实际上一启动就被 strict 校验拦死（本轮 runtime verification 已证明，详见下文测试执行汇总）。文字改成"默认 strict=true 时弱值直接退出；仅当显式设 `HALF_STRICT_SECURITY=false` 时降级为 warning（不建议生产使用）"会更准确。

### Low-4 — README 的 `VITE_API_BASE_URL` 说明不对应代码实际
- **Severity:** Low
- **File/Line:** `README.md:80-81`
- **Problem:** 原文："`VITE_API_BASE_URL` is mainly relevant for direct Vite development. In the production Docker image, the frontend talks to the backend via `/api`." 实际上 `src/frontend/src/api/client.ts:1` 是 `const BASE_URL = '';`，整个前端源码（含 `vite.config.ts`）没有任何一处读 `import.meta.env.VITE_API_BASE_URL`。`VITE_API_BASE_URL` 只在 `src/frontend/Dockerfile:10` 的构建命令里被塞进去，构建产物并不消费它；dev 模式走的是 `vite.config.ts` 里写死的 `proxy: { '/api': { target: 'http://localhost:8000' } }`。
- **Why it matters:** 试图靠这个变量把前端指向别的后端地址的人会发现它什么都不做；或者以为这是一条公开的扩展点，据此做客户化。要么在 `client.ts` / `vite.config.ts` 里真的读 `import.meta.env.VITE_API_BASE_URL` 并 fallback 到空串（对应的 Dockerfile 逻辑才有意义），要么删掉 Dockerfile 里的 `VITE_API_BASE_URL=...` 并把 README 这段改成"前端无论 dev 还是 prod 都用相对路径 `/api`，dev 由 Vite proxy，prod 由 nginx proxy"。

### Low-5 — README Quick Start 的 `echo >>` 方式会产出重复 key 的 `.env`
- **Severity:** Low
- **File/Line:** `README.md:49-55`
- **Problem:** 步骤是 `cp .env.example .env` 之后 `echo "HALF_SECRET_KEY=..." >> .env` / `echo "HALF_ADMIN_PASSWORD=..." >> .env`。因为 `.env.example` 已经带了 `HALF_SECRET_KEY=`（空值）和 `HALF_ADMIN_PASSWORD=`（空值），照着做出来的 `.env` 里每个变量各会有两行，一行空、一行有值。docker-compose v2 解析时会取最后一次出现的值，所以功能上能跑起来，但生成的 `.env` 读起来很乱，对 self-hosting 的新人容易造成"到底哪一行生效"的困惑；手动回去删前一行又是 friction。
- **Why it matters:** 小瑕疵，但这是项目的第一印象文件。把指令改成"打开 `.env` 填入这两行"或者在 `.env.example` 里就把这两行注释掉（`# HALF_SECRET_KEY=` / `# HALF_ADMIN_PASSWORD=`）再让用户覆盖，更清爽。

### Low-6 — `.gitignore` 与 `src/.gitignore` 并存，规则重叠且根层 `.gitignore` 覆盖面不全
- **Severity:** Low
- **Files:** `.gitignore:1-29`, `src/.gitignore:1-9`
- **Problem:** 阶段二新加了根 `.gitignore`，但原来的 `src/.gitignore` 还在，两份文件在 `.env` / `docker-compose.override.yml` / Node / Python 相关规则上重复。与此同时，根 `.gitignore` 没收 `*.db` / `backend/half.db` / `repos/`——非 docker 直接 `uvicorn main:app` 跑起来会在 `src/backend/` 下生成 `half.db` 和 `repos/`，这两条现在只靠 `src/.gitignore` 的旧规则兜底。如果未来有人删掉 `src/.gitignore` 认为"已经被根 .gitignore 取代"，半库的数据库就会突然被 track。
- **Why it matters:** 不是 bug，是代码健壮性问题。要么把 `src/.gitignore` 合并进根 `.gitignore`（并补上 `*.db` / `**/repos/`），要么保留两份但在根 `.gitignore` 里显式留一条注释说明"仅存 repo 根级通用规则，src/ 特定规则见 src/.gitignore"，避免未来误删。

### Low-7 — PRD 把 HALF 定位为"实验室内部演示版 MVP"，与 README 的"open-source multi-agent platform"定位不自洽
- **Severity:** Low
- **File/Line:** `docs/prd_final.md:3-18, 22-30` 等多处"实验室"字样
- **Problem:** 根 README / SECURITY / CONTRIBUTING 都是用通用开源项目的口径写的（"A task management console for teams…", "single-tenant self-hosting", etc.）。但 PRD 仍然反复强调"实验室内部使用的研究支撑平台"、"实验室内至少一个真实项目使用本系统"、"AI Coding / Coding Agent 是实验室新开辟的重点研究方向"。两套叙事拼在一起，外部 adopter 读 PRD 时会觉得"原来这东西是实验室自用的，不是给我用的"。
- **Why it matters:** 这不是泄漏，而是公开包装（stage-2 的目标 1 + 5）没走完最后一步：从 halfdev 搬文档时只 sanitized 了明显的敏感字段，但没 sanitize 文档的受众视角。建议在 PRD 顶部加一个一段话的"Open-source context"——说明这份 PRD 的原始读者是实验室内部、但对外部读者而言同样适用，或者在搬运时把"实验室"直接泛化成"小团队/组织"，以后再随需要开分叉。

## 阶段二目标达成情况（未列 findings 的部分）

| 目标 | 结果 |
|---|---|
| 从 halfdev 补拷公开文档到 `docs/` | ✅ 4 份（prd_final / tech_spec / ui-style / story）已到位；内容本身有若干 findings（Med-1 / Med-2 / Low-2 / Low-3 / Low-7） |
| 移除公开仓库中的 agent-facing 文件 | ✅ `AGENTS.md` / `CLAUDE.md` / `docs/agent/shared_guidance.md` / `docs/deploy/safe_deploy.md` 全部清除，全仓对这些路径的引用也清零（唯一残留是 `.gitignore:28` 的 `/LOCAL.md`，那是忽略规则，不是指向链接） |
| 新增 `README.md` / `SECURITY.md` / `CONTRIBUTING.md` / `.gitignore` | ✅ 四份均存在；findings 见 Med-3 / Low-4 / Low-5 / Low-6 |
| `src/LICENSE` 移到根 `LICENSE` | ✅ git 检测到 100% rename，内容未变（MIT License, Copyright (c) 2026 HALF Contributors） |
| 敏感词/私有信息扫描 | ✅ 未发现 `yinkt` / `zju` / `elance2005` / `t0project` / `mynotes` / `43.x.x.x` / `Ykt305300` / `claude_user` / `/home/` / `/Users/` 的命中；`阿里云/腾讯云` 的命中在 `docs/story.md:32` 属于通用 cloud vendor 举例，不泄漏；`keting` 出现在 `SECURITY.md:6` 是公开仓路径，符合预期 |
| 范围控制 | ✅ `git diff --stat cff0db0..0fbbb27` 显示改动只落在根级和 `docs/`，`src/` 下零改动，没有夹带 stage-3 或回退 stage-1 |

## 测试执行汇总（本轮新增，解决历史 testing gap）

装好 Python 3.11.13 + Node 20.20.0 后完整跑了一遍所有 suite：

| Suite | 命令 | 结果 | 时长 |
|---|---|---|---|
| 后端单测 | `python -m pytest tests/ -q` | **175 passed, 18 subtests passed**, 10 warnings（全部为 Pydantic V2 `class-based Config → ConfigDict` deprecation，遗留问题，非本轮） | 94s |
| 前端单测 | `npm test`（vitest） | **44 passed / 8 files** | 3s |
| 前端构建 | `npm run build`（tsc + vite build） | **✓ built in 4.25s**，231 modules，0 error，dist 产物正常 | — |

顺带在 Python 侧验证了 stage-1 runtime 硬化的三条关键场景，把之前审计里"没有运行时验证"这一条 residual 补上：

| 场景 | 期望 | 实际 |
|---|---|---|
| 弱默认值启动（`HALF_SECRET_KEY` / `HALF_ADMIN_PASSWORD` 都不设） | 命中两条 problems 并 `SystemExit(1)` | ✅ 两条 problem 均写入 stderr，`SystemExit(1)` 抛出 |
| `HALF_ADMIN_PASSWORD=aaaaaaaa` + 强 secret（Med-1 的回归点） | 只命中 admin 一条 problem 并 `SystemExit(1)` | ✅ 只命中 admin 一条，`SystemExit(1)` 抛出 |
| 强 secret + `StrongPass1` | 正常通过 | ✅ accepted |

> 补注：因为 alinux3 的 dnf 里没有 `python3.12` 基础解释器，只有零散的 `python3.12-*` 库包，所以本轮用 3.11.13 跑测试。生产 Dockerfile 写的是 `FROM python:3.12-slim`，175 个用例在 3.11 下全绿只能说明代码对 3.11/3.12 的差异不敏感，但不能完全替代在 3.12 下的回归；如需彻底消除版本差，需要从源码编译 3.12 或用 pyenv，再跑一轮。

## Residual risks / testing gaps

- **Python 3.12 下的完整回归未做。** 本轮是 3.11.13 跑的（al8 的 dnf 里没有 3.12 基础包）；代码对版本差异不敏感但不能等同于"3.12 已验证"。如果要做 release 级别的把关，建议容器内（用 `python:3.12-slim` 镜像）再跑一次 pytest。
- **容器启动期健康检查 / 主流程 E2E 没跑。** `docker compose up -d` → backend `validate_security_config` 在容器内的实际退出行为、nginx `/api` 代理到后端的链路、healthcheck 是否过——这些只能 docker 拉起来才能验证，静态检查和 Python 直跑都替代不了。
- **README Quick Start 没有按字面走一遍新手流程。** 配合 Low-5，建议真起一台干净机器照 README 第 49-55 行一字不差地走，把由 `cp + echo >>` 生成的那个两行 `.env` 文件实际看到一次，顺便验证 "Open `http://localhost:3000`… log in as `admin`" 这条路径端到端通。
- **文档-vs-代码不一致（Med-1 / Med-2 / Low-3）需要跟随 PR。** 这三条属于 stage-1 的硬化还没反映到 stage-2 补拷进来的 docs，必须在同一轮 open-source 发布前修正；拖到 stage-3 会让最早一批上游 contributor 按错误文档写代码。
- **SECURITY.md 报告渠道未实证。** 依赖"`keting/half` GitHub profile 上的联系方式"——本轮没有打开那个 profile 页确认上面真的有公开邮箱或 Security contact 入口。如果没有，漏洞报告者会无处可报。建议改成具体 email 或 "private security advisory" 链接。
- **`src/frontend` 的 `npm audit` 有 5 moderate severity vulnerabilities。** 不在阶段二范围，未展开，属 dependency hygiene 跟进项。
