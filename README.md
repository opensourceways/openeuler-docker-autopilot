# openeuler-docker-images-workflow

面向 [openeuler-docker-images](https://gitcode.com/openeuler/openeuler-docker-images) 的**应用容器镜像自动化流水线**：把「新增镜像 / 上游版本更新 / openEuler 版本升级」这三类重复劳动，变成由 GitHub Actions 编排、AI Agent 执行、双架构原生构建与功能测试背书的 Pull Request。

确定性代码承载主流程（解析、门禁、构建、测试、交付），Agent 只负责不确定的部分（Dockerfile 编写、测试语义、故障修复），且全程不持有仓库写权限。

---

## 受众导航

| 你是… | 直接跳到 |
|-------|---------|
| **想提需求的社区用户**（希望某个软件有 openEuler 镜像） | [1. 提交新镜像需求](#1-提交新镜像需求) → [8. 常见问题](#8-常见问题) |
| **仓库维护者**（部署 Runner、配置凭据、看流水线是否正常） | [2. 部署与配置](#2-部署与配置) → [3. 场景一：Issue 驱动新增镜像](#3-场景一issue-驱动新增镜像) → [4. 场景二：PR CI 失败自动修复](#4-场景二pr-ci-失败自动修复) → [8. 常见问题](#8-常见问题) |
| **开发者**（读懂系统、扩展能力） | [6. 系统设计要点](#6-系统设计要点) → [9. 目录结构](#9-目录结构) → [10. 模块说明](#10-模块说明) |

## 目录

- [概述](#概述)
  - [背景](#背景)
  - [解决方案](#解决方案)
  - [核心能力](#核心能力)
  - [当前状态](#当前状态)
- [1. 提交新镜像需求](#1-提交新镜像需求)
- [2. 部署与配置](#2-部署与配置)
- [3. 场景一：Issue 驱动新增镜像](#3-场景一issue-驱动新增镜像)
- [4. 场景二：PR CI 失败自动修复](#4-场景二pr-ci-失败自动修复)
- [5. 场景三 / 四：版本升级](#5-场景三--四版本升级)
- [6. 系统设计要点](#6-系统设计要点)
- [7. 产物规范](#7-产物规范)
- [8. 常见问题](#8-常见问题)
- [9. 目录结构](#9-目录结构)
- [10. 模块说明](#10-模块说明)
- [11. 延伸阅读](#11-延伸阅读)

---

## 概述

### 背景

openEuler 社区维护着一批应用容器镜像。它们在四个时刻需要变更，且每次变更的动作高度重复：

1. **社区希望新增一个应用镜像**——需要研究上游构建方式，按仓库规范写 Dockerfile、`meta.yml`、README、`doc/image-info.yml`，还要补一套能证明镜像真的可用的功能测试。
2. **上游应用发布新版本**——复制既有版本目录、替换版本串、补 `meta.yml` 条目，再重新构建验证。
3. **openEuler 发布新版本**——所有存量应用都要补齐新 openEuler 版本的镜像，批量且机械。
4. **已有的版本升级 PR 卡在 CI**——构建环境、依赖、编译参数一变就红，维护者要翻 Jenkins 日志、定位根因、改 Dockerfile 再重提，单条 PR 平均 15–30 分钟。

前三类工作共享同一批固定规范，但也都夹着不确定的部分：上游依赖怎么装、服务怎么起、构建失败怎么修。前者适合代码，后者适合 Agent。第四类处理的就是失败本身——它的根因往往是已知的构建失败模式（缺编译依赖、链接参数变更、Makefile 路径假设失效），因此把「诊断 + 修复」整体交给 Agent，只把触发、阶段推进、确定性复验与交付留给代码。

### 解决方案

本项目用一套流水线覆盖四个场景。场景一 / 三 / 四**共享同一套生成、门禁、双架构验证与交付能力**，差异只在触发输入与调度方式；场景二处理的是「别人已经提出、但 CI 失败」的 PR，走独立的**监控 → 诊断 → 容器内修复 → 复验 → 落回**链路：

| 场景 | 触发源 | 执行内容 | 输出 |
|------|--------|----------|------|
| **① 新增应用镜像** | GitCode Issue（标题含 `【new-image】`） | 解析需求 → 生成镜像文件与测试 → 门禁 → 双架构构建测试 → 有界修复 | 单个应用的完整镜像目录 PR |
| **② PR CI 失败自动修复** | 目标仓 PR 被打上 `ci_failed` 标签（Monitor 轮询） | 抓 Jenkins 失败日志 → AI 诊断根因 → 容器内逐条执行 Dockerfile 并修复 → 反推 Dockerfile → 双架构复验 | 落回源码的最小 diff Fix PR（`fix:` 前缀） |
| **③ 上游版本更新** | anitya webhook（`anitya-version-update`）或手动 | 查询上游新版本 → 复制既有目录树并换版本 → 双架构构建测试 | 新增版本子目录的 PR |
| **④ openEuler 版本升级** | `oe-new-version` 事件或手动 | 枚举全部应用 → Matrix 并行补齐缺失的 oe 版本 | 批量 PR + 失败应用报告 |

场景一 / 三 / 四的共同骨架：

```
                        触发（Issue / webhook / 手动）
                                    │
                                    ▼
                       确定性编排器（flow.py / run.py）
                                    │
                                    ▼
                        Image Creator 生成镜像文件
                                    │
                                    ▼
                    确定性门禁（目录边界 · 规范 · hadolint）
                                    │
                                    ▼
                 Testcase Creator ⇄ Testcase QA 对抗（最多 2 轮）
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
             x86_64 原生构建 + 测试          aarch64 原生构建 + 测试
                    └───────────────┬───────────────┘
                                    │
                          ┌─────────┴─────────┐
                     失败 │                   │ 双架构均通过
                          ▼                   ▼
                  Code Fixer 有界修复     不可变候选 + 验证证据
                          │                   │
                          └──► 重新验证        ▼
                          （最多 4 轮）    分支推送 → 目标仓 PR
                                │
                        仍不收敛 → needs-human-review
```

**关键约束：双架构必须在同一个候选上同时通过。** 构建在 x86_64 与 aarch64 的原生 Runner 上分别执行，不使用 QEMU 等跨架构模拟——模拟会掩盖架构差异，使双架构验证失去意义。场景二同样守这条线：容器内修复按 arm64 → amd64 串行推进（amd64 的修复必须架构中立或加架构守卫），最终 Dockerfile 再回到 arm64 从零 `docker build` 复验。

场景二的骨架（一次修复 = 一个 run，轮次显式，详见 [4. 场景二：PR CI 失败自动修复](#4-场景二pr-ci-失败自动修复)）：

```
目标仓库 PR 获得 ci_failed 标签
         ↓
monitor_ci_failed_prs.yml（cron 轮询）→ 跳过规则过滤 → dispatch 一次完整修复
         ↓
prepare：解析入口、现查 PR 元数据
         ↓
ci-log-analysis：只取实际失败架构的 Jenkins job 日志 + PR diff → AI 诊断报告
         ↓
Round 1：arm64 首修（容器内逐条执行 → 失败即修 → 反推 Dockerfile）→ amd64 续修 → arm64 从零复验
         ├─ 通过 ────────────────────────────────┐
         └─ 失败（仍有预算）→ Round 2：amd64 回修 → arm64 复验
                 ├─ 通过 ────────────────────────┤
                 └─ 失败 → Round 3：同上（预算用尽即终止，run 标红）┤
                                                        ↓
code-fix：最终 Dockerfile 作为最小 diff 落回源码 → commit → push → Fix PR
         ↓
Fix PR CI 结果
  ├─ ci_successful   ─→ 评论原始 PR，通知 reviewer 合并
  ├─ ci_processing   ─→ 等待，下次轮询再判断
  ├─ ci_failed（< 6）─→ 重新 dispatch（attempt+1，对 Fix PR 追加 commit 重试）
  └─ ci_failed（≥ 6）─→ 关闭 Fix PR，通知人工介入
```

### 核心能力

| 能力 | 说明 |
|------|------|
| **Issue 驱动零干预** | 从结构化 `【new-image】` Issue 提取软件包、上游源码、版本、openEuler 版本与所属领域，自动认领并全程回写状态 |
| **镜像内容生成** | 基于固定版本的上游源码与目标仓规范，生成 Dockerfile、`meta.yml`、README、`doc/image-info.yml` 及附属文件 |
| **功能测试生成** | 为应用生成共享测试入口 `tests/test.sh`，断言精确版本与真实功能路径，而非仅检查进程或端口存活 |
| **Agent 对抗审查** | Testcase Creator 生成、Testcase QA 质疑，分歧不 veto，交由本地验证裁决，降低弱测试与错误断言风险 |
| **确定性质量门禁** | 目录边界、文件规范、候选补丁、工具链与测试契约由代码检查，Agent 无法绕过 |
| **双架构原生验证** | x86_64 与 aarch64 各自独立产出构建与测试结论，一个架构通过不代表整体通过 |
| **健康驱动的就绪判定** | 有 `HEALTHCHECK` 时等待 `healthy`，没有时完整观察 120 秒容器行为；`EXPOSE` 端口不参与就绪调度 |
| **有界自动修复** | Fixer 依据结构化失败证据做最小范围修复，超出轮次上限即停止并保留证据 |
| **PR CI 失败自动修复** | 轮询带 `ci_failed` 标签的 PR，按 Fix PR 状态决策：不存在则首次修复、CI 再失败则追加 commit 重试，超过 6 次自动关闭并通知人工 |
| **容器内逐条执行式修复** | 不在文本上盲改：在自托管 Runner 的容器里逐条执行 Dockerfile 指令、失败即修，跑通后反推 Dockerfile 并用 `docker build` 验证 |
| **精准日志抓取** | 从 PR 评论表格逐行解析 FAILED 行，只取实际失败架构的构建 job 日志、排除 trigger/编排层；日志与 `ci_failed` 状态矛盾时主动标记「证据不足」而不是猜根因 |
| **CI 失败知识库** | [`docs/ci-failure-patterns.md`](docs/ci-failure-patterns.md) 按失败模式归档，修复通过 CI 后自动追加案例，下次诊断自动参考 |
| **只能新增，不能修改** | 存量镜像目录只读，`meta.yml` / README 仅允许末尾追加，由 `gate_diff.py` 差分强制 |
| **可复现工具链** | hadolint / jq / opencode 版本与 SHA256 锁定在 `.github/toolchain.lock.yml`，Python 依赖锁定在 `python-phase1.lock.txt` |
| **失败可追踪** | 无法自动收敛时保留构建、测试与修复证据，Issue 转为 `needs-human-review` 交维护者判断 |

### 当前状态

| 阶段 | 范围 | 状态 |
|------|------|------|
| 一 | 场景一：新增应用镜像 | **已打通**。完整走通「Issue 认领 → 生成 → 门禁 → 4 轮双架构验证 → 候选封存 → fork 分支 → 跨仓 PR」 |
| 二 | 场景二：PR CI 失败自动修复 | **已集成**。移植上游 [docker-images-workflow](https://github.com/FdeCad/docker-images-workflow) 的修复链路（编排改造为单 run 串行、轮次显式）、Agent、脚本与测试；`config/watchlist.json` 默认 `enabled: false`，需显式开启后才会对目标仓 PR 动手 |
| 三 | 场景三：应用版本更新 | 工作流骨架已就位（查询 → 验证 → 修复 → 提 PR），仍走 legacy `run.py` 链路，尚未接入阶段一的候选包 / 门禁 / 证据体系 |
| 四 | 场景四：openEuler 版本升级 | 同上，Matrix 并行与批量 PR 骨架已就位 |

**写入目标分级：** 阶段一的交付固定为测试模式——推送到配置的 fork 仓库，再向 `openeuler/openeuler-docker-images` 提跨仓 PR。生产直推模式（`direct_branch_pr`）已在 `DeliveryConfig` 中定义但**尚未接入任何 workflow**，需要显式开启；配置缺失或错误时一律解析为测试模式，任何情况下都不回退到生产仓。

---

## 1. 提交新镜像需求

在 [openeuler-docker-images Issues](https://gitcode.com/openeuler/openeuler-docker-images/issues) 提交 Issue 即可，无需接触本仓库。

**① 标题必须包含 `【new-image】`：**

```text
【new-image】add <软件包> <应用版本> docker image on openEuler <openEuler版本>
```

例如：

```text
【new-image】add kvrocks 2.16.0 docker image on openEuler 24.03-LTS-SP4
```

**② 正文至少提供三个字段**（模板见 [`templates/new-image-issue.md`](templates/new-image-issue.md)）：

```markdown
**软件包名称（Package Name）：** kvrocks
**源码仓库（Source Repository）：** https://github.com/apache/kvrocks/tree/v2.16.0
**所属领域（Domain）：** 数据库
```

> 源码仓库建议指向**具体 tag 或 release**，而不是默认分支——任务契约会把它固定下来，避免生成过程中上游漂移。

**③ 领域 → 目标目录映射**（中英文均可识别，未命中的值原样使用）：

| 领域关键词 | 目标目录 |
|-----------|---------|
| 人工智能、AI、机器学习、ML | `AI/` |
| 大数据、bigdata | `Bigdata/` |
| 数据库、db、database | `Database/` |
| 云计算、云原生、虚拟化、网络、cloud | `Cloud/` |
| 高性能计算、HPC | `HPC/` |
| 存储、storage | `Storage/` |
| 安全、security | `Security/` |
| distroless | `Distroless/` |
| 其他、others | `Others/` |

**④ 提交之后会发生什么：**

1. 监控工作流每 5 分钟扫描一次待处理 Issue，认领后立即回写状态；
2. 生成、门禁、双架构验证过程中持续更新 Issue；
3. 验证通过 → 回复生成的 PR 链接；
4. 无法自动收敛 → 附带诊断证据，打上 `needs-human-review` 标签交维护者判断。

---

## 2. 部署与配置

只有需要自行运行这套流水线的维护者才需要本节。

### 2.1 前置条件：self-hosted Runner

所有构建与验证 Job 都跑在自托管 Runner 上，且必须成对提供两种架构：

| Runner 标签 | 用途 |
|------------|------|
| `[self-hosted, Linux, X64, oe-image-x86]` | x86_64 原生构建与测试（场景一 / 三 / 四；场景二的 amd64 修复） |
| `[self-hosted, Linux, ARM64, oe-image-arm64]` | aarch64 原生构建与测试（场景一 / 三 / 四；场景二的 arm64 修复与复验） |
| `[self-hosted, Linux, X64]` | 监控、查询、生成、修复与交付等轻量 Job（场景二 / 三 / 四） |

Runner 需预装 **Docker 与 buildx**。能力由 Job 启动时的 `scripts/runner_preflight.py` 自检把关——**缺失即失败，不做临时安装**。同一 Runner 上会有并发 Job，镜像 tag 与容器名均携带唯一标识，避免互相覆盖。

Issue 监控工作流使用 `oe-image-x86` 自托管 Runner。

场景二的监控与交付 Job 只需要 Python、git 与网络；容器内修复 Job 额外需要 Docker（由 preflight 把关）。AI Agent 统一使用锁定工具链中的 opencode，**Runner 无需安装 Node.js**；只有把 `AI_RUNNER` 切到 `claude-code` / `claude-code-account` 时才需要 Node 与 Claude Code CLI。

**场景二的机器可换，架构不可换。** 三类 Job 的标签都能在手动触发时覆盖，或用 Variables 固定（标签写 JSON 数组字符串）：

| Job 类别 | 默认标签 | 覆盖方式 |
|---------|---------|---------|
| `prepare` / 日志分析 / `code-fix`（轻量） | `["self-hosted","Linux","X64"]` | 输入 `x64_runner_labels`，Variables `CI_FIX_X64_RUNNER_LABELS` |
| amd64 修复（需 Docker + ≥4 CPU） | `["self-hosted","Linux","X64","oe-fix-amd64"]` | 输入 `amd64_runner_labels`，Variables `CI_FIX_AMD64_RUNNER_LABELS` |
| arm64 首修 / 复验（**必须 arm64**） | `["self-hosted","Linux","ARM64","oe-fix-arm64"]` | 输入 `arm64_runner_labels`，Variables `CI_FIX_ARM64_RUNNER_LABELS` |
| 监控 / cron 同步 | 同轻量 Job | Variables `CI_FIX_X64_RUNNER_LABELS`（监控另有输入 `runner_labels`） |

例如把重活放到免费托管 Runner：`["ubuntu-latest"]`（x86）与 `["ubuntu-24.04-arm"]`（arm64，公开仓免费）。

⚠️ 标签必须是合法 JSON 数组字符串（写成 `ubuntu-latest` 这种不带方括号的形式就是错的），否则 Job 会在**调度阶段**直接失败——这类错误发生在 `prepare` 能启动之前，GitHub 只会给一句 invalid expression，所以改完建议先手动触发一次验证。`prepare` 里另有一次内容校验：空数组、非字符串元素会得到一句可读报错。

托管 Runner 上 `/opt/oe-image-tools` 不可写时，工具链缓存自动降级到 Job 临时目录——不需要 sudo，代价是每个 Job 重新下载一次工具链。

### 2.2 Secrets

在 **Settings → Secrets and variables → Actions → Secrets** 配置：

| Secret | 用途 | 必需 |
|--------|------|------|
| `GITCODE_TOKEN` | GitCode 读写：读 Issue/PR、克隆目标仓、推送分支、创建 PR、评论与打标签；场景二读 CI 日志同样依赖它 | 必填 |
| `DEEPSEEK_API_KEY` | Agent 模型调用（经 opencode，走 `https://api.deepseek.com/anthropic`） | 除 `pipeline_smoke` 外必填 |
| `DISPATCH_TOKEN` | 场景二专用：触发本仓 `repository_dispatch`、读写 `ci-fix-log` 数据分支、checkout 源仓库、推送 fix 分支、创建 Fix PR（GitHub PAT，需 `repo` + `workflow` scope） | 场景二必填 |
| `AI_API_KEY` | 场景二的模型 Key；留空时自动回退使用 `DEEPSEEK_API_KEY` | 可选 |
| `CLAUDE_CREDENTIALS_JSON` | `AI_RUNNER=claude-code-account` 时的 Claude.ai OAuth 凭证 | 可选 |

> `pipeline_smoke` 确定性收敛、绝不触发修复，因此调用方**不向它传递 API Key**——这是一条被工作流签名固化的约束，也是验证部署是否正确最省成本的方式。

### 2.3 Variables

在 **Settings → Secrets and variables → Actions → Variables** 配置：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `MAX_PARALLEL_IMAGES` | 场景三 / 四 Matrix 并行的镜像数上限 | `4` |
| `GITCODE_BOT_USERNAME` | 交付阶段用于推送分支的 GitCode 账号名 | _(无)_ |
| `AI_RUNNER` | 场景二 AI 后端：`opencode` / `claude-code-account` | `opencode` |
| `AI_MODEL` | 场景二模型名 | `deepseek/deepseek-v4-pro` |
| `AI_TIMEOUT_MS` | 场景二单次 Agent 调用超时（毫秒） | `1800000` |
| `GITCODE_FORK_REPO` | 场景二 fix 分支的推送去向（`owner/repo`）；留空则直推源仓库 | _(空)_ |
| `PR_COMMENT_ON_FAILURE` | 场景二自动修复连续失败时是否回帖源 PR（回帖是 outward-facing 动作，故默认不回） | _(空)_ |
| `GIT_COMMIT_NAME` / `GIT_COMMIT_EMAIL` | 场景二 Fix commit 的 git 身份 | `github-actions[bot]` / `...@users.noreply.github.com` |
| `OPENAI_BASE_URL` | 自定义模型 API 代理地址 | _(空)_ |
| `CI_FIX_X64_RUNNER_LABELS` | 场景二轻量 Job（prepare / 分析 / code-fix / 监控 / cron 同步）的 runner 标签，JSON 数组 | `["self-hosted","Linux","X64"]` |
| `CI_FIX_AMD64_RUNNER_LABELS` | 场景二 amd64 修复 Job 的 runner 标签（需 Docker + ≥4 CPU） | `["self-hosted","Linux","X64","oe-fix-amd64"]` |
| `CI_FIX_ARM64_RUNNER_LABELS` | 场景二 arm64 首修 / 复验 Job 的 runner 标签（必须 arm64） | `["self-hosted","Linux","ARM64","oe-fix-arm64"]` |

场景一的 Agent 模型默认取 `deepseek/deepseek-flash`（定义在 [`scripts/lib/agent_runtime.py`](scripts/lib/agent_runtime.py)），可用 `OPENCODE_MODEL` / `OPENCODE_TIMEOUT` 覆盖；场景二默认取 `deepseek/deepseek-v4-pro`，用 `AI_MODEL` 覆盖。

### 2.4 冒烟验证

部署完成后，从 Actions 页面手动运行 **Create New Images**，`operation` 选 `pipeline_smoke`：它跑完整编排链路，但不调用 AI、不做任何 GitCode 写操作，用于确认 Runner、工具链与编排本身健康。

场景二的入口是 **Fix PR CI failures**：`workflow_dispatch` 指定 `source_repo` / `pr_number` / `source_platform` 可手动触发一次完整修复链（会真实写 fix 分支与 Fix PR），同时可用 `x64_runner_labels` / `amd64_runner_labels` / `arm64_runner_labels` 临时指定跑在哪些机器上。日常运行由 **Watch CI failed PRs** 按 `config/watchlist.json` 轮询驱动（跑在哪台机器由 `CI_FIX_X64_RUNNER_LABELS` 决定），首次接入时建议先保持 `enabled: false`，确认凭据与 Runner 就绪后再开启。

---

## 3. 场景一：Issue 驱动新增镜像

### 3.1 执行链路

```
monitor_new_image_issues.yml  (cron: */5 * * * *)
   │ 扫描 GitCode 【new-image】Issue → 认领 → 建立 TaskSpec
   ▼ workflow_dispatch
create_new_images.yml  (operation = scenario_one)
   ├─ prepare        解析 Issue、锁定工具链、生成第 1 轮候选
   ├─ round-1..4     调用 _create_new_image_rounds.yml，每轮：
   │                   x86_64 构建测试 ∥ aarch64 构建测试 → decide 汇总
   │                   未收敛且未终止 → Fixer 修复（每轮上限 3 次）→ 下一轮
   ├─ package        双架构同时通过 → 封存不可变候选与验证证据
   ├─ release        产出候选补丁与 PR 内容
   └─ deliver        推送 fork 分支 → 向目标仓创建跨仓 PR → 回写 Issue
```

**收敛规则：**

- 一轮同时验证两个架构，因此**通过的那一轮本身就是双架构证明**；
- 验证失败**不会让 Job 失败**——decide 阶段需要读到两份报告才能裁决，失败的构建也必须交出证据；
- 4 轮仍未收敛 → 终止状态 `needs-human-review`，保留全部证据。

### 3.2 五种 operation

`create_new_images.yml` 用一个显式的 `operation` 输入区分用途，避免"同一个按钮做不同的事"：

| operation | 是否调用 AI | 是否写 GitCode | 用途 |
|-----------|:----------:|:-------------:|------|
| `pipeline_smoke` | ✗ | ✗ | 确定性冒烟，验证编排与 Runner |
| `validate_only` | ✓ | ✗ | 完整验证，停在交付之前 |
| `scenario_one` | ✓ | ✓ | 生产入口，从 GitCode Issue 认领并在同一次运行内交付 |
| `resume` | ✓ | 视续跑点 | 从上一次运行的某一轮或 package 阶段续跑 |
| `fork_pr` | ✗ | ✓ | 交付一个已验证的候选 |

`resume` 通过 `source_run_id`（也支持 `issue:<number>` 形式）与 `resume_from`（`1`–`4` 或 `package`）定位续跑点。

### 3.3 Agent 分工

| Agent | 职责 | 对抗关系 |
|-------|------|---------|
| [`image-creator.md`](.github/agents/image-creator.md) | 按目标仓规范生成 Dockerfile、`meta.yml`、README、`doc/image-info.yml` | 无 QA 语义复核，直接进确定性门禁 |
| [`testcase-creator.md`](.github/agents/testcase-creator.md) | 生成共享测试入口 `tests/test.sh` 与可选辅助函数 | 被 Testcase QA 质疑 |
| [`testcase-qa.md`](.github/agents/testcase-qa.md) | 对抗式复核测试语义与证据链 | Creator → QA1 → 修正 → QA2；分歧不 veto |
| [`code-fixer.md`](.github/agents/code-fixer.md) | 依据结构化失败证据做最小范围修复，内置故障诊断 | 仅在本地验证失败后介入 |

**镜像侧为什么没有 QA？** 镜像语义复核被确定性检查取代——镜像预检、身份契约、hadolint 在 Testcase Creator 启动前完成。固定 UID/GID 因缺少语义证明链而被禁止，只允许动态身份或复用基础镜像已有身份。

---

## 4. 场景二：PR CI 失败自动修复

> 本能力完整移植自 [FdeCad/docker-images-workflow](https://github.com/FdeCad/docker-images-workflow)，并适配本仓的 Runner 标签、锁定工具链与凭据约定。

### 4.1 触发与决策

[`monitor_ci_failed_prs.yml`](.github/workflows/monitor_ci_failed_prs.yml) 按 `config/watchlist.json` 的 `poll_interval_minutes` 定时轮询（cron 由 [`sync_ci_poll_interval.yml`](.github/workflows/sync_ci_poll_interval.yml) 自动同步），对每条带 `ci_failed` 标签的 PR 决策：

| Fix PR 状态 | 动作 |
|-------------|------|
| 不存在 | dispatch 一次完整修复（`run-ci-fix`，首次 attempt=1） |
| open + `ci_successful` | 评论原始 PR 通知 reviewer 合并（一次性），并把本次修复模式写入知识库 |
| open + `ci_processing` | CI 运行中，跳过等待 |
| open + `ci_failed`，commit 次数 < 6 | 重新 dispatch，对 Fix PR 追加 commit 重试 |
| open + `ci_failed`，commit 次数 ≥ 6 | 关闭 Fix PR，通知人工介入 |
| open + 无状态标签 | CI 尚未开始，跳过 |
| closed | 重新 dispatch（可能被人工关闭后需重试） |
| merged | 已合并，跳过 |

**跳过规则：** 预发布版本（标题含 `-alpha` / `-beta` / `-rc` / `-preview` / `-dev` / `-snapshot` / `-nightly`）与工作流自身创建的 Fix PR（标题以 `fix:` 开头）不触发修复。

### 4.2 单 run 串行的修复链路

[`ci_fix_pipeline.yml`](.github/workflows/ci_fix_pipeline.yml) **一次 run 跑完整个修复**（与场景一 `create_new_images.yml` 同构），修复轮次是显式 job，不是隐式 dispatch：

```
prepare                   解析入口、现查 PR 元数据（标题 / head SHA / base 分支）
   ↓
ci-log-analysis           失败架构日志 + PR diff + 知识库 → AI 诊断报告（写入 ci-fix-log）
   ↓
Round 1: fix and verify   arm64 首修 → amd64 续修 → arm64 确定性复验
   ↓ 复验失败（仍有预算）
Round 2: fix and verify   amd64 回修（架构中立）→ arm64 复验
   ↓ 复验失败
Round 3: fix and verify   amd64 回修 → arm64 复验（预算用尽即终止，run 标红）
   ↓ 任一轮复验通过
code-fix                  最终 Dockerfile 作为最小 diff 落回源码 → commit → push → Fix PR
```

每轮修复由 [`_ci_fix_round.yml`](.github/workflows/_ci_fix_round.yml) 组件承担（仿场景一的 `_create_new_image_rounds.yml`）：

| 轮次 | Runner | 执行内容 |
|------|--------|----------|
| Round 1 | arm64 → x86 → arm64 | arm64 首修（容器内逐条执行、失败即修）→ amd64 续修 → arm64 从零 `docker build` 复验 |
| Round 2 / 3 | x86 → arm64 | 在 arm64 冻结版之上回修（修复必须架构中立或加架构守卫）→ arm64 复验 |

**轮次怎么推进：** 复验把 `verify_passed` 交给 workflow——失败且仍有预算时开下一轮（job 名字里直接写着第几轮），预算用尽（`MAX_VERIFY_ROUNDS=2`，合计 3 轮）时该轮 job 失败、链路终止并保留证据。跨周期的重试另计：Monitor 对同一条 PR 最多重试 6 次，每次是一个新 run，是第几次修复写在 run 标题的 `attempt` 上（`ci-fix PR#1234 · attempt 3 · <repo>`）。

**日志抓取策略：** 从 PR 评论表格逐行（`<tr>`）解析，排除 `/trigger/`、`/gate/`、`/pre-check/` 编排层 URL，只取同行带 FAILED 标记的架构构建 URL，并按架构标识加权评分；日志取末尾 500 行（失败几乎总在尾部）。重试时 CI 结果表格出现在 Fix PR 评论中，会自动切换到 Fix PR 编号查询。若日志末尾是 `Finished: SUCCESS` 却仍带 `ci_failed` 标签，说明拉到的是编排层日志，诊断报告会标记「证据不足」而不是猜根因。

### 4.3 Agent 分工

| Agent | 职责 |
|-------|------|
| [`ci-failure-analyst.md`](.github/agents/ci-failure-analyst.md) | CI 失败诊断师：错误类型分类、前置一致性检查、结构化诊断报告 |
| [`dockerfile-builder.md`](.github/agents/dockerfile-builder.md) | 容器构建修复工程师：起容器 → 逐条执行 → 失败即修 → 反推 Dockerfile → `docker build` 验证（最小 diff + 双架构约束） |

两个 Agent 只产出报告与 Dockerfile，不做任何 git / 平台写操作；写操作集中在 `code-fix` 阶段由确定性代码执行。

### 4.4 数据分支与知识库

| 分支 | 内容 |
|------|------|
| `main` | 工作流代码 + [`docs/ci-failure-patterns.md`](docs/ci-failure-patterns.md)（按失败模式分类的知识库） |
| `ci-fix-log` | `{pr-number}/ci-analysis.md`（诊断报告）+ `fix-summary.md`（修复摘要） |

修复通过 CI 后，Monitor 会把该 PR 的诊断与修复摘要自动追加进知识库；下次诊断时作为历史模式注入提示，同类问题置信度显著提升。

### 4.5 本地验证

```bash
python -m pytest tests/test_ci_fix_workflow.py tests/test_ci_gitcode_api.py \
  tests/test_fix_pr_body.py tests/test_process_pr_events.py \
  tests/test_build_runner.py tests/test_build_fix_feedback.py \
  tests/test_opencode_run.py tests/test_stage_common.py -v
```

覆盖编排结构（单 run 串行、轮次门控）、URL 评分与日志抓取、Fix PR 标题/正文生成、跳过规则、Dockerfile 解析/定位/diff、复验结果的轮次交付。

---

## 5. 场景三 / 四：版本升级

两个场景共用验证组件 [`_upgrade_versions.yml`](.github/workflows/_upgrade_versions.yml)：生成候选 → 双架构构建 → 运行既有测试套件；重试时跳过生成，只重跑构建与测试（Fixer 的改动已落盘）。

| 工作流 | 触发 | 流程 |
|--------|------|------|
| [`upgrade_upstream_versions.yml`](.github/workflows/upgrade_upstream_versions.yml) | `repository_dispatch: anitya-version-update` / 手动指定应用 | 查询上游新版本 → 逐应用验证 → 失败则修复重试（最多 3 轮）→ 通过者提 PR |
| [`upgrade_openeuler_versions.yml`](.github/workflows/upgrade_openeuler_versions.yml) | `repository_dispatch: oe-new-version` / 手动 | 检测新 oe 版本 → 枚举全部应用 Matrix 并行（`fail-fast: false`）→ 成功者汇总批量 PR，失败者出报告 |

**上游版本监控直接复用社区已有的 [anitya](https://easysoftware-monitoring.test.osinfra.cn/) 服务**，本系统不自建轮询：应用名即 anitya 的查找键，新应用只需在 `doc/image-info.yml` 中补齐 `upstream` 块与顶层 `homepage`。

**PR 去重**按标题精确匹配：相同场景 + 相同应用 + 相同版本只会存在一个 PR。

---

## 6. 系统设计要点

### 6.1 确定性与不确定性的分界

- **主流程必须由确定性代码承载**：输入解析、变更边界、构建测试、结果聚合与交付全部是可测试的 Python，不交给 Agent 判断；
- **Agent 只处理不可预见的部分**：上游研究、Dockerfile 编写、测试语义、故障修复；
- **任务契约（TaskSpec）是唯一事实来源**：应用、版本、源码引用、目标路径与允许修改范围在运行开始时固定，Agent 与后续所有阶段都以它为准。

### 6.2 权限与写操作隔离

Agent 在生成与修复阶段**不持有任何仓库写能力**：

- 不得执行 `git commit` / `git push` 或任何仓库、API 写操作；
- 不得读取、输出或提及环境中的凭据；
- 不得修改 whitelist 之外的文件；
- 不得禁用 lint 规则、删除或弱化测试、修改 CI 配置。

Git 与平台写操作集中在验证完成后的交付阶段，由确定性代码执行。

### 6.3 失败显式化

不通过弱化测试、吞退出码或伪造健康检查制造成功。自动修复无法收敛时**停止并保留证据**，而不是降低标准让流水线变绿。诊断证据不足时（例如日志与状态互相矛盾）会主动标记，而不是猜一个根因。

### 6.4 只能新增，不能修改

存量镜像目录视为只读，由四层机制保证：

1. `git diff --name-only origin/main...HEAD` 差分检查，拒绝对已有文件的修改；
2. `meta.yml` 与 `README.md` 为例外，但仅允许末尾追加，且经结构化解析验证；
3. 幂等检查：解析已有 `meta.yml`，确认 `<app-ver, oe-ver>` 组合尚不存在；
4. PR 去重：提 PR 前遍历目标仓 open PR，按标题精确匹配。

---

## 7. 产物规范

### 7.1 最小目录单元（MDU）

```text
<domain>/<app-name>/
├── README.md                  # 快速参考、Tag 表、使用方法、FAQ
├── meta.yml                   # Tag → Dockerfile 路径映射
├── doc/                       # 软件中心展示（可选）
│   ├── picture/logo.png
│   └── image-info.yml         # 展示字段 + upstream 监控配置
├── tests/                     # 应用级共享测试套件
│   ├── test.sh                # 唯一功能测试入口
│   └── test_helpers.sh        # 可选
├── results/<app-ver>/<oe-ver>/ # 双架构测试结果，只增不改
└── <app-ver>/<oe-ver>/
    └── Dockerfile
```

### 7.2 为什么测试用例按应用共享，而不是按版本复制

- 一处修复，所有版本受益；按版本复制则 N 份需要同步；
- 同一套标准便于横向比较，版本特化的用例难以自证公允；
- 新增版本无需新增测试代码。

**两条前提：**共享用例必须支持版本参数注入、不得硬编码版本号，否则会退化成"每版本独有"；修改共享用例会影响该应用所有历史版本，须在 PR 中声明受影响的版本范围。

### 7.3 结果归档

结果按**应用版本 + openEuler 版本**双层归档，与每个 Dockerfile 一一对应。目标仓只归档双架构 JUnit 与 `version_info.json`；完整构建日志与聚合 `results.json` 只进入 candidate/artifact，避免仓库体积随构建次数增长。

> 该布局超出目标仓 README 当前定义的最小目录单元，批量产出前需与仓库 maintainer 确认。

### 7.4 meta.yml

`path` 为 **MDU 相对路径**（相对 `meta.yml` 所在目录），不带应用名前缀：

```yaml
5.0.2-oe2403sp1:
  path: 5.0.2/24.03-lts-sp1/Dockerfile
  arch: aarch64          # 可选；省略 = 双架构
```

解析器兼容存量数据中的仓库根相对路径与前导斜杠写法，但生成一律产出 MDU 相对路径。校验只针对本次变更的 MDU，范围外的存量问题记为 warning，不阻断本次变更。

---

## 8. 常见问题

### Q: 提了 Issue 但一直没有反应，怎么排查？

1. 标题是否包含 `【new-image】`（全角方括号）；
2. 正文三个必填字段是否齐全：软件包名称、源码仓库、所属领域；
3. 单次扫描默认最多认领 3 个新 Issue，高峰期可能排队；
4. 查看 **Watch GitCode new-image Issues** 工作流的运行日志。

### Q: 为什么不用 QEMU 做跨架构构建，而要准备两组 Runner？

跨架构模拟会掩盖架构差异——依赖在模拟层"能跑"不代表在原生 aarch64 上能跑，这会让双架构验证失去意义。因此构建必须在对应架构的原生 Runner 上执行。

### Q: 一个架构通过、另一个失败，会怎么处理？

整轮判定为未收敛。Fixer 拿到两份报告后做一次最小修复，产出下一轮候选重新验证。**双架构必须在同一个候选上同时通过**，不接受"分别通过过"。

### Q: 4 轮修复仍然失败会怎样？

流水线停止，Issue 转为 `needs-human-review` 并保留全部构建、测试与修复证据。系统不会为了让流水线变绿而弱化测试。

### Q: Agent 会不会直接改到目标仓？

不会。生成与修复阶段的 Agent 没有仓库写能力，只能修改任务契约白名单内的候选文件；所有 Git 与平台写操作集中在验证完成后的交付阶段，由确定性代码执行。

### Q: 生成的 PR 会直接提到 openeuler 官方仓吗？

当前交付固定为测试模式：分支推送到配置的 fork 仓库，再向 `openeuler/openeuler-docker-images` 提**跨仓 PR**。生产直推模式（`direct_branch_pr`）虽已定义但尚未接入任何 workflow，需要显式开启并同时恢复重复 PR 守卫。

### Q: 测试用例怎么保证不是"假测试"？

三道防线：① Testcase QA 对抗复核，专门质疑弱断言；② 测试必须断言精确版本与真实功能路径，仅检查进程或端口存活不被接受；③ 就绪判定基于 `HEALTHCHECK` 或 120 秒容器行为观察，`EXPOSE` 端口不参与调度——脚本的真实功能断言才是结论依据。

### Q: 工具链版本会不会随时间漂移？

不会。hadolint / jq / opencode 的版本、下载地址与 SHA256 锁定在 [`.github/toolchain.lock.yml`](.github/toolchain.lock.yml)，Python 依赖锁定在 [`.github/python-phase1.lock.txt`](.github/python-phase1.lock.txt)，缓存于 Runner 的 `/opt/oe-image-tools`。场景二的 AI Agent 同样用这份锁定工具链里的 opencode。

### Q: 场景二跑了但没有触发修复，怎么排查？

1. 目标仓 PR 是否确实带 `ci_failed` 标签（不是拼写变体）；
2. `config/watchlist.json` 中该仓库的 `enabled` 是否为 `true`；
3. PR 标题是否命中跳过规则（预发布版本或 `fix:` 前缀）；
4. `DISPATCH_TOKEN` / `GITCODE_TOKEN` 是否具备所需权限；
5. 查看 **Watch CI failed PRs** 的运行日志，搜索 `→ Skipping` 或 `❌`。

### Q: Fix PR 的 CI 又失败了怎么办？

无需人工操作。Fix PR 再次带上 `ci_failed` 后，下次轮询会对**原始 PR** 重新发起 `ci-log-analysis`，AI 结合新的失败日志对 Fix PR 追加 commit；累计 6 次仍未通过则自动关闭 Fix PR 并评论通知人工介入。

### Q: 场景二为什么要在容器里逐条执行，而不是直接改 Dockerfile？

文本层面的盲改无法证明改动真的能构建通过。在容器里逐条执行 `RUN` 并即时修复，跑通的命令序列才是"已被证明可行"的；再反推回 Dockerfile 并用 `docker build` 从零复验一次，确保反推没有引入偏差。

### Q: 想手动跳过某条 PR 怎么做？

移除该 PR 的 `ci_failed` 标签即可，下次轮询不再处理它。

### Q: 不想搭自托管机器，能直接跑在 GitHub 托管 Runner 上吗？

可以，手动触发 **Fix PR CI failures** 时把三个标签输入换成托管标签：轻量的用 `["ubuntu-latest"]`，amd64 修复用 `["ubuntu-latest"]`，arm64 修复/复验用 `["ubuntu-24.04-arm"]`（arm64 托管 Runner 目前**仅公开仓免费**）。三点注意：

1. **缓存退化**：托管 Runner 每次都是干净环境，工具链（hadolint / jq / opencode）会在每个 Job 重新下载；`/opt/oe-image-tools` 的跨 Job 缓存只有自托管 Runner 才有。
2. **6 小时/job 上限**：托管 Runner 超过即被砍；自托管没有这个限制。重型镜像（如源码编译的 milvus）整轮修复可能被砍在构建中途——那属于预算不足，不是修复失败。
3. **预装差异**：托管的 Ubuntu Runner 自带 Docker、buildx 与 `gh`；自托管机器需要自己装（`gh` 只在 GitHub 平台的 Fix PR 创建路径上用到）。

要把选择固定下来（自动轮询也生效）就设对应 Variables。

---

## 9. 目录结构

```text
openeuler-docker-images-workflow/
├── .github/
│   ├── actions/
│   │   ├── phase1-setup/                    # 工具链准备与 Runner 自检（各场景共用）
│   │   ├── phase1-replay/                   # 候选回放
│   │   └── phase1-emit-patch/               # 候选补丁产出
│   ├── agents/
│   │   ├── image-creator.md                 # ① 镜像生成者
│   │   ├── testcase-creator.md              # ① 测试生成者
│   │   ├── testcase-qa.md                   # ① 测试挑战者
│   │   ├── ci-failure-analyst.md            # ② CI 失败诊断师
│   │   ├── dockerfile-builder.md            # ② 容器构建修复工程师
│   │   └── code-fixer.md                    # ①③④ 修复者（内置故障诊断）
│   ├── workflows/
│   │   ├── monitor_new_image_issues.yml     # ① Issue 扫描与认领（cron */5）
│   │   ├── create_new_images.yml            # ① 主编排（prepare → 4 轮 → 交付）
│   │   ├── _create_new_image_rounds.yml     # ① 单轮验证-修复-决策组件
│   │   ├── monitor_ci_failed_prs.yml        # ② ci_failed PR 轮询（cron，间隔由 watchlist 控制）
│   │   ├── ci_fix_pipeline.yml              # ② 修复主编排（prepare → 分析 → 3 轮修复 → 落回）
│   │   ├── _ci_fix_round.yml                # ② 单轮修复组件（arm64 首修 → amd64 → arm64 复验）
│   │   ├── sync_ci_poll_interval.yml        # ② watchlist 变更时同步 cron 表达式
│   │   ├── upgrade_upstream_versions.yml    # ③ 上游版本更新
│   │   ├── upgrade_openeuler_versions.yml   # ④ openEuler 版本升级
│   │   ├── _upgrade_versions.yml            # ③④ 共享验证组件
│   │   ├── issue_contract_test.yml          # GitCode Issue API 契约冒烟
│   │   └── test-e2e.yml                     # 开发自测（不创建真实 PR）
│   ├── toolchain.lock.yml                   # 工具链版本 + SHA256 锁
│   └── python-phase1.lock.txt               # Python 依赖锁
├── config/
│   └── watchlist.json                       # ② 监控仓库列表与轮询参数
├── scripts/
│   ├── harness/
│   │   ├── flow.py                          # 阶段一确定性编排入口
│   │   ├── run.py                           # 场景③④ legacy Agent/测试入口
│   │   ├── parse_issue.py                   # Issue 解析与领域映射
│   │   ├── query_version.py                 # 上游 / oe 版本对比查询
│   │   ├── validate_meta.py                 # meta.yml schema 校验
│   │   ├── gate_diff.py                     # "只能新增"差分门禁
│   │   └── compose_pr.py                    # PR 内容组装
│   ├── stages/                              # ② 阶段脚本：ci-log-analysis / build-fix / code-fix
│   ├── watch/                               # ② PR 轮询、入口解析与 cron 同步
│   ├── lib/                                 # 见下节模块说明
│   ├── utils/scoring.py                     # 置信度计算
│   ├── bootstrap_tools.py                   # 工具链落地
│   └── runner_preflight.py                  # Runner 能力自检
├── docs/
│   ├── failure-patterns.yml                 # verified 结构化故障模式
│   ├── failure-patterns.md                  # 知识库维护策略
│   ├── ci-failure-patterns.md               # ② CI 失败模式知识库（自动维护）
│   └── runbooks/                            # 运维手册
├── templates/
│   ├── new-image-issue.md                   # Issue 模板
│   └── pr.md                                # PR 模板
├── tests/                                   # 本仓单元、契约与工作流回归测试
├── requirements.txt                         # ② 阶段脚本运行时依赖（requests）
├── DESIGN.md                                # 系统设计与关键决策
└── REQUIREMENTS.md                          # 项目目标与约束
```

> ① = 场景一　② = 场景二（PR CI 失败自动修复）　③ = 场景三　④ = 场景四　其余为共享能力

---

## 10. 模块说明

### 10.1 编排与门禁

| 模块 | 职责 |
|------|------|
| [`scripts/harness/flow.py`](scripts/harness/flow.py) | 阶段一全部确定性子命令：prepare、replay、package、release、fork-deliver、issue 生命周期 |
| [`scripts/lib/task_spec.py`](scripts/lib/task_spec.py) | 场景无关的任务契约：应用、版本、源码引用、目标路径与允许变更范围 |
| [`scripts/lib/target_contract.py`](scripts/lib/target_contract.py) | 候选目录的确定性门禁：目录边界、必需文件、命名规范 |
| [`scripts/harness/gate_diff.py`](scripts/harness/gate_diff.py) | "只能新增"差分检查 |
| [`scripts/lib/candidate_bundle.py`](scripts/lib/candidate_bundle.py) | 不可变候选包的封存与校验 |

### 10.2 生成与对抗

| 模块 | 职责 |
|------|------|
| [`scripts/lib/generation_pipeline.py`](scripts/lib/generation_pipeline.py) | Creator / QA 生成期流水线与轮次控制 |
| [`scripts/lib/agent_runtime.py`](scripts/lib/agent_runtime.py) | Agent 进程管理、结构化输出契约、模型与超时配置 |
| [`scripts/lib/evidence_resolver.py`](scripts/lib/evidence_resolver.py) | Harness 受限取证——Agent 声称的证据由 Harness 固定，不由 Agent 自证 |
| [`scripts/lib/upstream_format_check.py`](scripts/lib/upstream_format_check.py) | 上游引用格式校验 |

### 10.3 验证与修复

| 模块 | 职责 |
|------|------|
| [`scripts/lib/native_validation.py`](scripts/lib/native_validation.py) | 原生构建、健康驱动的就绪调度、功能测试执行 |
| [`scripts/lib/native_repair.py`](scripts/lib/native_repair.py) | Fixer 收敛循环与轮次预算 |
| [`scripts/lib/failure_classification.py`](scripts/lib/failure_classification.py) | 失败分类，决定是否可修复以及交给谁修 |
| [`scripts/lib/failure_knowledge.py`](scripts/lib/failure_knowledge.py) | verified 结构化故障知识库读写 |
| [`scripts/lib/result_aggregation.py`](scripts/lib/result_aggregation.py) | 双架构结果聚合与轮次裁决 |

### 10.4 平台与交付

| 模块 | 职责 |
|------|------|
| [`scripts/lib/gitcode_client.py`](scripts/lib/gitcode_client.py) | GitCode API 封装与 `DeliveryConfig`（环境 / 交付模式 / 推送去向） |
| [`scripts/lib/pr_delivery.py`](scripts/lib/pr_delivery.py) | 已验证候选的交付：分支推送、PR 创建、去重守卫 |
| [`scripts/lib/issue_lifecycle.py`](scripts/lib/issue_lifecycle.py) | Issue 认领、状态回写、`needs-human-review` 终止处理 |
| [`scripts/lib/git_workspace.py`](scripts/lib/git_workspace.py) | 目标仓克隆与工作区隔离 |
| [`scripts/lib/toolchain.py`](scripts/lib/toolchain.py) | 锁文件驱动的工具链解析与校验 |

### 10.5 场景二：CI 修复（独立子系统）

场景二自带一套平台与 AI 调用层（`ci_*` 与 `ai_runner` / `opencode_run`），与场景一的 `gitcode_client.py` / `agent_runtime.py` 并存且互不依赖——它面向的是"修复别人仓库里已有的 PR"，与场景一的生成交付链路没有共享状态。

| 模块 | 职责 |
|------|------|
| [`scripts/watch/process_pr_events.py`](scripts/watch/process_pr_events.py) | PR 轮询、Fix PR 状态决策、跳过规则与 dispatch（含 attempt 计数） |
| [`scripts/watch/resolve_pr.py`](scripts/watch/resolve_pr.py) | 入口解析（prepare）：两种入口统一成一份 PR 元数据并写入 `$GITHUB_OUTPUT` |
| [`scripts/watch/sync_poll_interval.py`](scripts/watch/sync_poll_interval.py) | `poll_interval_minutes` → cron 表达式同步 |
| [`scripts/stages/ci-log-analysis.py`](scripts/stages/ci-log-analysis.py) | 阶段 1：取 PR diff + 失败日志 + 知识库 → AI 诊断报告 → 写入 `ci-fix-log` |
| [`scripts/stages/build-fix.py`](scripts/stages/build-fix.py) | 阶段 2/3：容器内逐条执行与修复、反推 Dockerfile、arm64 复验 |
| [`scripts/stages/code-fix.py`](scripts/stages/code-fix.py) | 阶段 4：最终 Dockerfile 落回源码树 |
| [`scripts/lib/ci_api.py`](scripts/lib/ci_api.py) | 平台工厂：按仓库 URL 在 GitCode / GitHub 实现间分发 |
| [`scripts/lib/ci_gitcode_api.py`](scripts/lib/ci_gitcode_api.py) | GitCode v5 PR 读写 + v4 Pipeline / Jenkins 日志抓取（逐行解析、编排层过滤、架构评分） |
| [`scripts/lib/ci_github_api.py`](scripts/lib/ci_github_api.py) | GitHub REST API（PR 读写） |
| [`scripts/lib/ci_data.py`](scripts/lib/ci_data.py) | `ci-fix-log` / `main` 分支文件读写（GitHub Contents API）与知识库追加 |
| [`scripts/lib/build_runner.py`](scripts/lib/build_runner.py) | Dockerfile 解析 / 定位 / diff 纯逻辑 + docker CLI 封装（容器清理、`docker build`） |
| [`scripts/lib/fix_pr_body.py`](scripts/lib/fix_pr_body.py) | Fix PR 标题（软件名 + 版本）与正文生成 |
| [`scripts/lib/ai_runner.py`](scripts/lib/ai_runner.py) | Agent 统一入口：按 `AI_RUNNER` 分发 opencode / claude-code |
| [`scripts/lib/opencode_run.py`](scripts/lib/opencode_run.py) / [`claude_code_run.py`](scripts/lib/claude_code_run.py) | 两个 AI 后端的调用封装（实时日志转发、超时进程组清理） |
| [`scripts/lib/stage_common.py`](scripts/lib/stage_common.py) | 阶段公共工具：Agent 提示词定位、规范文件发现、仓库标识归一、阶段日志 |
| [`scripts/lib/discover_conventions.py`](scripts/lib/discover_conventions.py) | 读取源仓库规范文件并注入 Agent 提示 |

---

## 11. 延伸阅读

| 文档 | 内容 |
|------|------|
| [`REQUIREMENTS.md`](REQUIREMENTS.md) | 项目目标、部署约束、测试策略结论及其论证 |
| [`DESIGN.md`](DESIGN.md) | 系统设计全文：仓库规范、工作流、Agent 协作、构建流水线、命名规范、风险与缓解 |
| [`docs/failure-patterns.md`](docs/failure-patterns.md) | 场景一 / 三 / 四 故障知识库的组织与维护策略 |
| [`docs/ci-failure-patterns.md`](docs/ci-failure-patterns.md) | 场景二 CI 失败模式知识库（按模式分类，修复通过 CI 后自动追加） |
| [`docs/runbooks/`](docs/runbooks/) | 运维手册 |
| [openeuler-docker-images](https://gitcode.com/openeuler/openeuler-docker-images) | 目标仓库与其现行规范 |
| [easysoftware-autoupgrade](https://github.com/opensourceways/easysoftware-autoupgrade) | 社区已有的镜像升级系统，本项目复用了其版本监控与批量更新模式 |
| [docker-images-workflow](https://github.com/FdeCad/docker-images-workflow) | 场景二的来源仓库：CI 失败自动修复流水线（容器内逐条修复、arm64 复验、Fix PR 自管理） |
