# openeuler-docker-images-workflow

面向 [openeuler-docker-images](https://gitcode.com/openeuler/openeuler-docker-images) 的**应用容器镜像自动化流水线**：把「新增镜像 / 上游版本更新 / openEuler 版本升级」这三类重复劳动，变成由 GitHub Actions 编排、AI Agent 执行、双架构原生构建与功能测试背书的 Pull Request。

确定性代码承载主流程（解析、门禁、构建、测试、交付），Agent 只负责不确定的部分（Dockerfile 编写、测试语义、故障修复），且全程不持有仓库写权限。

---

## 受众导航

| 你是… | 直接跳到 |
|-------|---------|
| **想提需求的社区用户**（希望某个软件有 openEuler 镜像） | [1. 提交新镜像需求](#1-提交新镜像需求) → [8. 常见问题](#8-常见问题) |
| **仓库维护者**（部署 Runner、配置凭据、看流水线是否正常） | [2. 部署与配置](#2-部署与配置) → [3. 场景一：Issue 驱动新增镜像](#3-场景一issue-驱动新增镜像) → [4. 场景二：应用自动升级](#4-场景二应用自动升级) → [8. 常见问题](#8-常见问题) |
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
- [4. 场景二：应用自动升级](#4-场景二应用自动升级)
- [5. 场景三：openEuler 版本升级](#5-场景三openeuler-版本升级)
- [6. 系统设计要点](#6-系统设计要点)
- [7. 产物规范](#7-产物规范)
- [8. 常见问题](#8-常见问题)
- [9. 目录结构](#9-目录结构)
- [10. 模块说明](#10-模块说明)
- [11. 延伸阅读](#11-延伸阅读)

---

## 概述

### 背景

openEuler 社区维护着一批应用容器镜像。系统覆盖四个场景，对应四类高度重复的变更动作：

1. **社区希望新增一个应用镜像**（场景一）——需要研究上游构建方式，按仓库规范写 Dockerfile、`meta.yml`、README、`doc/image-info.yml`，还要补一套能证明镜像真的可用的功能测试。
2. **openEuler 发布新版本**（场景三）——所有存量应用都要补齐新 openEuler 版本的镜像，批量且机械。
3. **应用上游发布了新版本**（场景二）——需要为存量应用补一个新版本镜像目录与测试，还要判断已有最新版本的 Dockerfile 是否可信，量大且需要理解上游构建方式。
4. **存量镜像缺功能测试脚本**（场景四）——目标仓把功能测试与 CI 构建绑定（Dockerfile 变更即构建 + 按 `tests/test.sh` 功能测试），但多数应用没有测试脚本，需要按 [KunpengTest 规范](https://github.com/opensourceways/upstream-dashboard/blob/KunpengTest/README.md)逐个补齐。

场景一、三两类工作共享同一批固定规范，但也都夹着不确定的部分：上游依赖怎么装、服务怎么起、构建失败怎么修。前者适合代码，后者适合 Agent。场景二处理的是版本升级：目标版本与上游证据由 GitCode `【new-version】` Issue 提供，扫描阶段只负责定位目标仓目录，目录复制与元数据登记是确定性的，但 Dockerfile 必须结合 Issue 证据与固定上游源码重新生成，目标版本目录已存在时还要审计现有镜像，因此 AI 同时承担生成与审计。场景四与场景一共享「Agent 生成测试 + 静态校验」的质量机制，但脚本规范遵循目标仓 CI 的 KunpengTest 约定（禁 `set -e`、脚本内自拉服务、注入五个环境变量），走独立的**手动指定软件 → 定位镜像 → 生成 → 校验 → 提 PR** 链路。

> **PR CI 失败修复**不再作为独立场景自动轮询：它抽成可复用组件 [`_ci_repair.yml`](.github/workflows/_ci_repair.yml)，由 [`ci_fix_pipeline.yml`](.github/workflows/ci_fix_pipeline.yml) 手动或显式 dispatch 调用。升级 PR 的 CI 若失败，交人工决定是否触发修复。

### 解决方案

本项目用一套流水线覆盖四个场景。场景一 / 三**共享同一套生成、门禁、双架构验证与交付能力**，差异只在触发输入与调度方式；场景二由 GitCode `【new-version】` Issue 提供版本与上游证据，对落后应用做**AI 依证据生成 Dockerfile + 双架构原生验证 + 一应用一 PR**，对目标版本目录已存在的应用做**AI 审计与修复**；场景四为存量应用补功能测试脚本，走独立的**手动指定软件 → 定位镜像 → 生成 → 校验 → 提 PR** 链路：

| 场景 | 触发源 | 执行内容 | 输出 |
|------|--------|----------|------|
| **① 新增应用镜像** | GitCode Issue（标题含 `【new-image】`） | 解析需求 → 生成镜像文件与测试 → 门禁 → 双架构构建测试 → 有界修复 | 单个应用的完整镜像目录 PR |
| **② 应用自动升级** | GitCode Issue（标题含 `【new-version】`，正文带上游证据 JSON）/ 手动触发 | 解析 Issue 证据 → 对比目标仓已有目录 → 缺新版本：补测试 + AI 依证据生成 Dockerfile + 元数据落盘 + 双架构验证；已是最新：AI 审计并修复 Dockerfile 与 doc/image-info.yml | 一应用一 PR |
| **③ openEuler 版本升级** | `oe-new-version` 事件或手动 | 枚举全部应用 → Matrix 并行补齐缺失的 oe 版本 | 批量 PR + 失败应用报告 |
| **④ 功能测试脚本补齐** | 手动触发（指定软件名） | 定位该软件最新镜像目录 → AI 按 KunpengTest 规范生成 `tests/test.sh` → 静态校验（失败重试 2 轮） | 一软件一 PR（含 Dockerfile 空行触发目标仓构建 + 功能测试） |

场景一 / 三的共同骨架：

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

**关键约束：双架构必须在同一个候选上同时通过。** 构建在 x86_64 与 aarch64 的原生 Runner 上分别执行，不使用 QEMU 等跨架构模拟——模拟会掩盖架构差异，使双架构验证失去意义。场景二同样守这条线：升级分支在 x86_64 / aarch64 上各自真实构建并跑功能测试，两个都通过才开 PR。

场景二的骨架（一应用一 PR，详见 [4. 场景二：应用自动升级](#4-场景二应用自动升级)）：

```
monitor_upgrade_issues.yml（扫描 【new-version】 Issue）
         ↓ dispatch（app / version / os_version / evidence / source_issue）
upgrade_upstream_versions.yml（也可手动 app+version）
         ↓
discover：Issue 证据 / 清单（手动 version / source_url）+ 目标仓已有版本 → 升级矩阵（缺字段 / 已有 PR 跳过；目标版本已存在转审计）
         ↓
_升级应用（matrix，一应用一 PR）
  prepare：完整克隆 → AI 依证据生成 Dockerfile → 缺测试则补 tests/test.sh → 确定性落盘 → commit → 推 auto/version-update/... 分支
         ↓
  validate-x86_64 ∥ validate-aarch64：原生构建 + 功能测试（证据 artifact）
         ↓ 两个架构都通过
  open-pr：跨仓 PR（变更说明 + 功能测试状态 + 上游证据）
```

PR CI 失败修复保留为**手动组件**：入口 `ci_fix_pipeline.yml` → `_ci_repair.yml`（prepare → 分析 → 3 轮修复 → code-fix），同一 PR 最多 6 个 run，不再有 cron 自动轮询。

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
| **升级候选发现** | GitCode `【new-version】` Issue 提供目标版本与上游证据，扫描阶段只与目标仓已有目录对比（**不查询看板**）；缺字段 / 已有 open PR 跳过，目标版本目录已存在转审计；手动触发可用清单兜底 |
| **确定性版本升级** | 复制最新版本目录，Dockerfile 由 AI 依据 Issue 证据与上游源码重新生成（禁止机械替换版本号）；README / `doc/image-info.yml` 更新版本、追加 `meta.yml`；生成内容缺目标版本号即失败交人工 |
| **目标版本已存在的审计与修复** | 目标版本目录已在目标仓时不跳过：确定性检查版本/tag/meta/测试脚本/image-info，AI 审计后由修复 Agent 更新 Dockerfile 与 doc/image-info.yml，推分支并先过双架构原生校验，通过后再开 PR |
| **升级证据** | 由触发 Issue 提供证据包（`source=gitcode-issue`，含 L1 证据、`l3_evidence`、`install_candidates`），作为镜像构建、测试生成与 PR 留痕的参考，不参与门禁；手动路径回落最小 `source=manual` 证据 |
| **PR CI 失败修复（手动组件）** | `_ci_repair.yml` 复用原自动修复链路：诊断 → 容器内逐条执行修复 → arm64 复验，同一 PR 最多 6 个 run；入口为手动 / 显式 dispatch，不再自动轮询 |
| **容器内逐条执行式修复** | 不在文本上盲改：在自托管 Runner 的容器里逐条执行 Dockerfile 指令、失败即修，跑通后反推 Dockerfile 并用 `docker build` 验证 |
| **精准日志抓取** | 从 PR 评论表格逐行解析 FAILED 行，只取实际失败架构的构建 job 日志、排除 trigger/编排层；日志与 `ci_failed` 状态矛盾时主动标记「证据不足」而不是猜根因 |
| **CI 失败知识库** | [`docs/ci-failure-patterns.md`](docs/ci-failure-patterns.md) 按失败模式归档，修复通过 CI 后追加案例，下次诊断参考 |
| **生成类场景只增不改** | 场景一 / 三 / 四的存量镜像目录只读，`meta.yml` / README 仅允许末尾追加，由 `gate_diff.py` 差分强制；场景二升级只新增版本目录并追加 `meta.yml` |
| **可复现工具链** | hadolint / jq / opencode 版本与 SHA256 锁定在 `.github/toolchain.lock.yml`，Python 依赖锁定在 `python-phase1.lock.txt` |
| **失败可追踪** | 无法自动收敛时保留构建、测试与修复证据，Issue 转为 `needs-human-review` 交维护者判断 |

### 当前状态

| 阶段 | 范围 | 状态 |
|------|------|------|
| 一 | 场景一：新增应用镜像 | **已打通**。完整走通「Issue 认领 → 生成 → 门禁 → 4 轮双架构验证 → 候选封存 → fork 分支 → 跨仓 PR」 |
| 二 | 场景二：应用自动升级 | **已打通**。GitCode Issue 提供版本与上游证据 → 对比目标仓已有目录 → 缺测试则补 → 确定性复制 + Dockerfile 由 AI 依证据生成 + `meta.yml` → 双架构原生验证 → 一应用一 PR（`monitor_upgrade_issues.yml` → `upgrade_upstream_versions.yml`）。原 PR CI 修复链路保留为手动组件 `_ci_repair.yml` |
| 三 | 场景三：openEuler 版本升级 | 工作流骨架已就位（检测新 oe 版本 → Matrix 并行补齐 → 批量 PR），仍走 legacy `run.py` 链路，尚未接入阶段一的候选包 / 门禁 / 证据体系 |
| 四 | 场景四：功能测试脚本补齐 | **已打通（手动触发）**。指定软件名 → 定位目标仓最新镜像目录 → Agent 按 KunpengTest 规范生成 `tests/test.sh` → 静态校验（失败重试 2 轮）→ 一软件一 PR（`generate_test_scripts.yml`）；看板爬取已下线，需配置 `GITCODE_FORK_REPO` 与 `TESTGEN_RUNNER_LABELS` |

> 升级版本与上游证据由 GitCode `【new-version】` Issue 提供，手动触发时可由软件清单兜底；不再依赖 anitya / upstream-dashboard 做版本发现。PR CI 失败修复不再自动轮询，改为手动 / 显式调用（见 [4.6](#46-pr-ci-修复组件手动)）。

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
| `[self-hosted, Linux, X64, oe-image-x86]` | x86_64 原生构建与测试（场景一 / 二 / 三；CI 修复组件的 amd64 修复） |
| `[self-hosted, Linux, ARM64, oe-image-arm64]` | aarch64 原生构建与测试（场景一 / 二 / 三；CI 修复组件的 arm64 修复与复验） |
| `[self-hosted, Linux, X64]` | 监控、查询、生成、发现与交付等轻量 Job（场景二 / 三） |

Runner 需预装 **Docker 与 buildx**。能力由 Job 启动时的 `scripts/runner_preflight.py` 自检把关——**缺失即失败，不做临时安装**。同一 Runner 上会有并发 Job，镜像 tag 与容器名均携带唯一标识，避免互相覆盖。

Issue 监控每 5 分钟轮询一次：由 hwyx86 上的 `oe-issue-poll.timer` 调 `workflow_dispatch`，跑在专用 `oe-issue-poll` Runner 上（与镜像构建机隔离，不会被长任务卡住）。GitHub 自带 cron 只保留每小时一次的兜底，因为其 5 分钟 schedule 属于 best-effort，可能长期延迟或丢跑；需要换机器时设置 Variable `ISSUE_POLL_RUNNER_LABELS`。

场景二的发现 / 交付 Job 只需要 Python、git 与网络；双架构验证 Job 额外需要 Docker（由 preflight 把关）。AI Agent 统一使用锁定工具链中的 opencode，**Runner 无需安装 Node.js**；只有把 `AI_RUNNER` 切到 `claude-code` / `claude-code-account` 时才需要 Node 与 Claude Code CLI。

**场景二的机器可换，架构不可换。** 发现 / 汇总 Job 的标签可用手动输入或 Variable `UPGRADE_RUNNER_LABELS` 覆盖；验证 Job 的默认标签是 `oe-image-x86` / `oe-image-arm64`，arm64 只能换成另一台 arm64 机器：

| Job 类别 | 默认标签 | 覆盖方式 |
|---------|---------|---------|
| `discover`（轻量） | `["self-hosted","Linux","X64","oe-upgrade-x64"]` | 输入 `runner_labels`，Variable `UPGRADE_RUNNER_LABELS` |
| `summary`（轻量） | `["self-hosted","Linux","X64","oe-image-x86"]` | 输入 `runner_labels`，Variable `UPGRADE_RUNNER_LABELS` |
| `validate-x86_64` | `["self-hosted","Linux","X64","oe-image-x86"]` | `_upgrade_app.yml` 的输入 `x64_runner_labels` |
| `validate-aarch64`（**必须 arm64**） | `["self-hosted","Linux","ARM64","oe-image-arm64"]` | `_upgrade_app.yml` 的输入 `arm64_runner_labels` |
| CI 修复组件（`_ci_repair.yml`） | 轻量 `oe-image-x86`；amd64 `oe-fix-amd64`；arm64 `oe-fix-arm64` | 输入 `x64_runner_labels` / `amd64_runner_labels` / `arm64_runner_labels`，Variables `CI_FIX_*_RUNNER_LABELS` |

**arm64 复验使用持久 BuildKit 层缓存。** 复验是对 derived Dockerfile 的从零 `docker build`，重型镜像（例如 bolt：conan 从源码编 34 个依赖，x86_64 上实测单个编译层就要 4427.6s）每次都从头编，很容易撞 `BUILD_DOCKER_TIMEOUT`（默认 7200s）。因此 `verify-arm` 会带 `CI_FIX_BUILD_CACHE_DIR` 走 `buildx --load` + `type=local, mode=max` 把层缓存留在自托管机器上：同一 PR 下一轮 / 下一天复验同一份 derived Dockerfile 时前缀层直接命中，不同 PR 之间同 base、同版本的层也能复用。缓存目录默认在 `<runner.workspace>/ci-fix-buildkit-cache`（checkout 之外，不会被清理）；builder 不存在时会自动创建一个 docker-container builder，创建/启动失败则**自动退回普通 `docker build`**（缓存是加速手段，不能让它在环境不满足时把构建弄失败）。磁盘占用按需清理：`docker buildx prune -f --filter until=168h`，或直接删缓存目录。

> ⚠️ 缓存只覆盖 `docker build` 的层。Dockerfile 内部的 conan / pip 下载与源码编译要复用，需要在 Dockerfile 里用 `RUN --mount=type=cache`（属于源仓库的改动，不在本仓控制范围内）。

**轻量 Job 默认也走自托管 Runner。** CI 修复组件的 `prepare` / 分析 / `code-fix` 与 Monitor 默认跑 `oe-image-x86`：本仓库所在账号的 GitHub 托管 Runner 额度不可用（`ubuntu-latest` 会在 `prepare` 阶段直接失败），自托管是当前唯一可跑通的选择。若账号额度可用，可通过 `CI_FIX_X64_RUNNER_LABELS` 等 Variable 切到 `["ubuntu-latest"]`——托管 Runner 上 `/opt` 不可写，工具链缓存会自动降级到 Job 临时目录（[`phase1-setup`](.github/actions/phase1-setup/action.yml) 已处理），代价是每个 Job 重新下载一次工具链。

⚠️ 标签必须是合法 JSON 数组字符串（写成 `ubuntu-latest` 这种不带方括号的形式就是错的），否则 Job 会在**调度阶段**直接失败——这类错误发生在 `prepare` 能启动之前，GitHub 只会给一句 invalid expression，所以改完建议先手动触发一次验证。

### 2.2 Secrets

在 **Settings → Secrets and variables → Actions → Secrets** 配置：

| Secret | 用途 | 必需 |
|--------|------|------|
| `GITCODE_TOKEN` | GitCode 读写：读 Issue/PR、克隆目标仓、推送升级分支、创建 PR、评论与打标签；CI 修复组件读日志同样依赖它 | 必填 |
| `AI_API_KEY` | **所有场景统一的模型 Key**（当前为火山引擎 API 网关 Key）；留空时回退 `DEEPSEEK_API_KEY` | 除 `pipeline_smoke` 外必填 |
| `DEEPSEEK_API_KEY` | 兼容别名：仅在未配置 `AI_API_KEY` 时作为 Key 使用 | 可选 |
| `DISPATCH_TOKEN` | CI 修复组件专用：触发本仓 `repository_dispatch`、读写 `ci-fix-log` 数据分支、checkout 源仓库、推送 fix 分支、创建 Fix PR（GitHub PAT，需 `repo` + `workflow` scope） | 使用 CI 修复组件时必填 |
| `CLAUDE_CREDENTIALS_JSON` | `AI_RUNNER=claude-code-account` 时的 Claude.ai OAuth 凭证 | 可选 |

> `pipeline_smoke` 确定性收敛、绝不触发修复，因此调用方**不向它传递 API Key**——这是一条被工作流签名固化的约束，也是验证部署是否正确最省成本的方式。

### 2.3 Variables

在 **Settings → Secrets and variables → Actions → Variables** 配置：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `MAX_PARALLEL_IMAGES` | 场景三 Matrix 并行的镜像数上限 | `4` |
| `MAX_PARALLEL_UPGRADES` | 场景二同一轮并发升级的应用数上限 | `2` |
| `UPGRADE_RUNNER_LABELS` | 场景二发现 / 汇总 Job 的 runner 标签，JSON 数组 | 未设置时 discover 回退 `oe-upgrade-x64`、summary 回退 `oe-image-x86` |
| `GITCODE_BOT_USERNAME` | 交付阶段用于推送分支的 GitCode 账号名 | _(无)_ |
| `AI_RUNNER` | 所有场景的 AI 后端：`opencode` / `claude-code-account` | `opencode` |
| `AI_MODEL` | 所有场景统一的模型名（`provider/model`） | `gateway/deepseek-v4-pro` |
| `AI_PROVIDER_ID` | 自定义 OpenAI 兼容服务商的 provider id（与模型名前缀一致） | `gateway` |
| `AI_TIMEOUT_MS` | 所有场景单次 Agent 调用超时（毫秒） | `10800000` |
| `GITCODE_FORK_REPO` | 场景二 / 四分支的推送去向（`owner/repo`）；留空则直推目标仓 | _(空)_ |
| `PR_COMMENT_ON_FAILURE` | CI 修复组件连续失败时是否回帖源 PR（回帖是 outward-facing 动作，故默认不回；覆盖位置：arm64 复验三轮失败、同一 PR 跑满 6 个 run 停手） | _(空)_ |
| `GIT_COMMIT_NAME` / `GIT_COMMIT_EMAIL` | 场景二升级 commit 的 git 身份 | `github-actions[bot]` / `...@users.noreply.github.com` |
| `OPENAI_BASE_URL` | 所有场景统一的模型 API 地址（OpenAI 兼容） | `https://st8tp3ajl0df3n8b8l8qu.apigateway-cn-beijing.volceapi.com/v1` |
| `UPGRADE_RUNNER_LABELS` | 场景二发现 / 汇总 Job 的 runner 标签，JSON 数组 | 未设置时 discover 回退 `oe-upgrade-x64`、summary 回退 `oe-image-x86` |
| `UPGRADE_REPAIR_INSTRUCTIONS` | 验证失败后自动 repair 的默认说明（留空则 AI 按失败证据自行修复） | _(空)_ |
| `AUTO_REPAIR_UPGRADES` | 设为 `false` 关闭验证失败后的自动 repair | `true` |
| `CI_FIX_X64_RUNNER_LABELS` | CI 修复组件轻量 Job（prepare / 分析 / code-fix / 监控）的 runner 标签，JSON 数组 | `["self-hosted","Linux","X64","oe-image-x86"]` |
| `CI_FIX_AMD64_RUNNER_LABELS` | CI 修复组件 amd64 修复 Job 的 runner 标签（需 Docker + ≥4 CPU） | `["self-hosted","Linux","X64","oe-fix-amd64"]` |
| `CI_FIX_ARM64_RUNNER_LABELS` | CI 修复组件 arm64 首修 / 复验 Job 的 runner 标签（必须 arm64） | `["self-hosted","Linux","ARM64","oe-fix-arm64"]` |
| `CI_FIX_BUILD_CACHE_DIR` | arm64 复验的持久 BuildKit 层缓存目录（自托管机器上的路径，跨 run 复用；留空则退化为不缓存的 `docker build`） | `<runner.workspace>/ci-fix-buildkit-cache` |
| `CI_FIX_BUILDKIT_BUILDER` | 缓存用的 buildx builder 名（不存在则自动创建 docker-container builder） | `oe-ci-fix` |
| `TESTGEN_RUNNER_LABELS` | 场景四 generate Job 的 runner 标签，JSON 数组 | `["self-hosted","Linux","X64","oe-image-x86"]` |
| `ISSUE_POLL_RUNNER_LABELS` | Issue 轮询 Job 的 runner 标签，JSON 数组 | `["self-hosted","Linux","X64","oe-issue-poll"]` |

场景四复用场景一的 Agent 栈（`gateway/deepseek-v4-pro` + 网关 provider 注入），跨仓 PR 与场景二共用 `GITCODE_FORK_REPO`。看板爬取已下线，不再有跨轮 done / exhausted 状态。

**所有场景共用一套服务商配置**，唯一事实来源是 [`scripts/lib/ai_provider.py`](scripts/lib/ai_provider.py)：模型、provider id、baseURL、API Key 与超时都从同一组环境变量解析。最少只需配置 `AI_API_KEY`（或兼容的 `DEEPSEEK_API_KEY`），其余参数都有默认值。

默认走**火山引擎 API 网关**（OpenAI 兼容模式）：`AI_MODEL=gateway/deepseek-v4-pro`、`OPENAI_BASE_URL=https://st8tp3ajl0df3n8b8l8qu.apigateway-cn-beijing.volceapi.com/v1`、Key 放 `AI_API_KEY`。`gateway` 不是 opencode 内置 provider，[`ai_provider.py`](scripts/lib/ai_provider.py) 会按 `AI_PROVIDER_ID` + `OPENAI_BASE_URL` 在 `OPENCODE_CONFIG_CONTENT` 里声明一个自定义 provider（`npm=@ai-sdk/openai-compatible`），Key 以 `{env:OPENAI_API_KEY}` 引用、不落明文。

`OPENCODE_MODEL` 保留为兼容别名：未设置 `AI_MODEL` 时生效。

已内置完整能力声明的模型：`glm-5.3`（256k 输入）与 `deepseek-v4-pro`（1M 输入 / 384k 输出 / thinking / reasoning_content 交错）。其他模型只下发 `{"name": "<model-id>"}` 的最小声明；如需开启 thinking、图片输入或指定上下文长度，在 [`ai_provider.py`](scripts/lib/ai_provider.py) 的 `_MODEL_OPTIONS` 中补充。

换成其它 OpenAI 兼容服务商：改 `OPENAI_BASE_URL` + `AI_MODEL`（`<provider_id>/<model>`）+ `AI_PROVIDER_ID` 三者一致即可。若要用 opencode 内置 provider（如 `deepseek/…`、`anthropic/…`），把 `AI_MODEL` 前缀改成对应内置 id 即可——前缀与 `AI_PROVIDER_ID` 不一致时不会注入自定义 provider，会走 opencode 内置配置。

### 2.4 冒烟验证

部署完成后，从 Actions 页面手动运行 **Create New Images**，`operation` 选 `pipeline_smoke`：它跑完整编排链路，但不调用 AI、不做任何 GitCode 写操作，用于确认 Runner、工具链与编排本身健康。

场景二的正式入口是 GitCode **`【new-version】` Issue**：标题给出应用名、目标版本与 openEuler 版本，正文给出上游看板返回的完整证据 JSON。运行 `monitor_upgrade_issues.yml` 认领待处理 Issue 后，把 `app` / `version` / `os_version` / `evidence` / `source_issue` 派发给 **App Version Upgrade**，流程口径是：Issue 证据 → 对比两个目标仓已有目录 → 驱动镜像构建与测试生成，最终是否通过由双架构构建与功能测试决定。也可手动触发该工作流，用 `app` 指定单个应用并给 `version` / `source_url`；手动路径不带证据时回落到最小 manual 证据，不传 `app` 即按清单全量扫描。`limit` 控制单轮最多升级几个应用。并发组按 `app` 隔离（`app-version-upgrade-<app>`，app 为空时按 ref）：逐 app 派发时不同应用并行、同一应用串行，避免固定并发组下排队 run 互相顶掉丢请求。

CI 修复组件（**Fix PR CI failures**）只保留手动 / 显式调用：`workflow_dispatch` 指定 `source_repo` / `pr_number` / `source_platform` 触发一次完整修复链（会真实写 fix 分支与 Fix PR），可用 `x64_runner_labels` / `amd64_runner_labels` / `arm64_runner_labels` 临时指定机器。**Watch CI failed PRs** 也只保留手动触发，不再有 cron。

场景四的入口是 **Generate Test Scripts**：只支持 `workflow_dispatch` 手动触发，`app` 必填（目标仓目录名，如 `kvrocks`），同名应用跨域时用 `domain` 消歧，`source_url` 可选（仅作为生成提示）。应用不存在、已有 `tests/test.sh` 或缺 Dockerfile 会直接失败，不会静默跳过。

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

## 4. 场景二：应用自动升级

> 取代社区 anitya + easysoftware-autoupgrade 的升级链路。正式入口是 GitCode `【new-version】` Issue：目标版本与上游证据都由 Issue 提供，自动升级**不查询 upstream-dashboard**；Dockerfile 由 AI 按 Issue 证据与上游源码生成，不做版本串机械替换。手动触发时版本由清单或参数手动维护。

### 4.1 触发与候选发现

正式入口是 [`monitor_upgrade_issues.yml`](.github/workflows/monitor_upgrade_issues.yml) 扫描 GitCode `【new-version】` Issue，认领后调用 [`upgrade_upstream_versions.yml`](.github/workflows/upgrade_upstream_versions.yml)。Issue 标题格式 `【new-version】upgrade <app> to <version> on openEuler <os>`；正文必须是上游看板返回的完整证据 JSON（`software` / `version` / `upstream_evidence` / `l3_evidence` / `install_candidates`），模板见 [`templates/new-version-issue.md`](templates/new-version-issue.md)，字段与拒绝原因见 [`docs/new-version-issue-guide.md`](docs/new-version-issue-guide.md)。解析后随 `evidence` 输入透传。

工作流也可手动触发：

| 输入 | 含义 |
|------|------|
| `app` | 只处理这一个应用（留空 = 扫描全部应用） |
| `version` | 手动指定目标版本（配合 `app` 使用） |
| `tag` | 手动指定版本对应的上游 tag（留空则不校验 tag） |
| `source_url` | 手动指定上游仓库 HTTPS 地址（配合 `version`） |
| `os_version` | 目标 openEuler 版本（Issue 触发时用于 conda 登记；留空则用各包最新段） |
| `evidence` | Issue 正文的上游证据 JSON（由 `upgrade-issue-watch` 自动填写；手动触发留空） |
| `source_issue` | 来源 GitCode Issue 编号（由 `upgrade-issue-watch` 自动填写） |
| `apps_file` | 本轮使用的软件清单（留空 = `config/upgrade-apps.yml`；可指向 `config/upgrade-apps-l5.yml` 等子集） |
| `limit` | 本轮最多升级几个应用（`0` = 不限） |
| `audit_limit` | 本轮最多审计几个「目标版本已存在」的应用（`0` = 不限） |
| `runner_labels` | 发现 / 汇总 job 的 runner 标签（JSON 数组） |
| `x64_runner_labels` | x86_64 构建 / 验证 runner 标签（JSON 数组，留空 = 变量 `UPGRADE_X64_RUNNER_LABELS` / 默认 `oe-upgrade-x64`） |
| `arm64_runner_labels` | aarch64 构建 / 验证 runner 标签（JSON 数组，留空 = 变量 `UPGRADE_ARM64_RUNNER_LABELS` / 默认 `oe-upgrade-arm64`） |
| `max_parallel` | 单轮最多并发几个应用（留空 = 变量 `MAX_PARALLEL_UPGRADES` / 默认 `4`） |

> 升级验证用统一标签 `oe-upgrade-x64` / `oe-upgrade-arm64` 圈定本仓的 4 台构建机（每台 2 个 runner 实例），避免误调度到其他仓库共用 `self-hosted,Linux,X64` 的临时 Runner；一台 Runner 同时只跑一个 Job，`max_parallel` 与实例总数对齐即可吃满机器。

`discover` job 浅克隆目标仓后调用 [`upgrade_scan.py`](scripts/harness/upgrade_scan.py)，**不查询 upstream-dashboard**：

- Issue 驱动时，版本来自 Issue 标题、证据来自 Issue 正文（`--evidence`），扫描阶段只负责定位两个目标仓里的目录、判断目标版本是否已存在；证据只作用于同名应用；
- 手动触发时，软件清单来自 [`config/upgrade-apps.yml`](config/upgrade-apps.yml)（人工维护，**不遍历目标仓**）；清单项包含 `name`（软件名）、`app`（目标仓目录名）、`domain`（目标仓一级目录），以及手动维护的 `version`（目标版本）、`source_url`（上游仓库 HTTPS 地址）和可选的 `tag`；
- 缺 `version` / `source_url` → 跳过并记录原因；`version` 为 `Undefined` / `latest` 等占位值、或纯数字版本低于仓库现有版本 → 跳过，避免降级 PR；
- 清单里的软件在目标仓不存在 → 跳过并标记「尚未入库，待场景一新建镜像」；目标分支已有同名升级分支的 open PR → 跳过；
- 目标版本目录已存在 → **不跳过**，产出 `audits` 条目交给 AI 审计；否则产出 `{app, domain, version, os_version, source_url, evidence}` 升级矩阵，`os_version` 沿用该应用最新的 os 目录；Issue 驱动时 `evidence.source` 为 `gitcode-issue`，手动路径为 `manual`。

### 4.2 单应用升级链路

每个应用由可复用组件 [`_upgrade_app.yml`](.github/workflows/_upgrade_app.yml) 独立执行（一应用一 PR，互不影响）：

```
prepare            完整克隆目标仓 → AI 依证据生成 Dockerfile → 缺测试则补 tests/test.sh → 确定性落盘 → commit → 推分支
   ↓
replay-aarch64     同一份 Dockerfile 在 arm64 容器里再完整重放一遍，修架构差异（无差异则不改分支）
   ↓
validate-x86_64    x86_64 原生构建 + 功能测试（flow.py phase1-native-validate）
validate-aarch64   aarch64 原生构建 + 功能测试（与 x86 并行）
   ↓ 两者都通过
open-pr            跨仓 PR：变更说明 + 功能测试状态 + 上游证据
   ↑
plan-repairs/repair 任一验证失败时自动挑出失败应用，在原分支上修一轮后重新验证
```

- **Dockerfile 生成**（[`upgrade_apply.py`](scripts/harness/upgrade_apply.py)）：把旧版本 Dockerfile、目标版本、上游地址与 Issue 提供的证据包（`support_level`、`check_id`、`test_depth`、`ci_workflows`、`install_candidates` 等）一起注入升级 Agent，参考上游源码重新生成完整 Dockerfile；**不做版本串机械替换**，生成结果缺目标版本号或 `FROM` 即失败。
- **安装方式**（`install_candidates`）：候选安装方式，供 Dockerfile 生成参考；最终采用 `binary` 还是 `source` 由 Agent 根据该版本实际可用的产物和最终 Dockerfile 决定。选择只作用于 Dockerfile，不改测试脚本与元数据。
- **PR 元数据**：升级 PR 标题为 `【自动升级】[kunpeng-install:<source|binary>] <app> <version>`，标记取 Agent 根据最终 Dockerfile 返回的 `install_mode`；commit message 为 `feat: upgrade <app> to <version>`，含软件与版本。审计修复 PR 使用同一标题格式。
- **双架构容器重放**：生成阶段先在 x86_64 容器里把候选 Dockerfile 逐条跑通，随后在 arm64 Runner 上用同一份文件再做一次完整重放（[`upgrade_repair.py --mode replay`](scripts/harness/upgrade_repair.py)）；只修架构相关问题，没有差异时不产生空提交。
- **确定性落盘**（[`version_upgrade.py`](scripts/lib/version_upgrade.py)）：把该应用最新的 `{old_version}/{os}/` 复制为 `{new_version}/{os}/`，写入 AI 生成的 Dockerfile，更新应用根目录 `README.md` / `doc/image-info.yml` 的版本号，并向 `meta.yml` 追加 `{new_version}-{oe_tag}` 条目。失败时清理半成品目录。
- **补测试**（复用场景四）：应用没有 `tests/test.sh` 时调用 `testgen_generate.generate_test_script`，把上游证据作为额外上下文；生成失败**不阻断**升级，PR 正文标注「测试脚本待补」。
- **双架构原生验证**：x86_64 / aarch64 各自真实构建并跑功能测试，不使用 QEMU；任一架构失败则不开 PR，证据留在 artifact，分支保留供自动/人工修复继续处理。
- **App note 自动沉淀**：升级、修复、审计 Agent 都会在 JSON 里返回 `app_note`；流水线把本次经验写入 [`config/app-notes/<app>.md`](config/app-notes) 的「自动沉淀」章节。同一 `version/os_version` 原地替换，人工正文与 YAML front matter（构建预算等）保持不变；note 推到 `auto/app-note/<app>` 分支并开独立 notes PR，不阻塞升级 PR。仓库需允许 GitHub Actions 创建 PR（`Settings → Actions → General`），发布步骤失败只记日志、不影响升级结果。
- **分支**：`auto/version-update/<app>/<version>-<oe_tag>`，推送到 `GITCODE_FORK_REPO`（留空则直推目标仓），再从 fork 向目标仓提跨仓 PR。

### 4.3 验证失败后的自动修复

`upgrade` 有任何应用验证失败时，同一轮里的 `plan-repairs` 会查 Actions jobs 列表，挑出 `Upgrade <app> / Validate *` 失败的 app（prepare 失败不修，因为分支还没推上去），再用 `repair_run_id=<本次 run id>` 自动调用 `_upgrade_app.yml` 的 repair 模式：

- 只修**一轮**：`plan-repairs` 不依赖 `repair`，修复后的验证再失败不会继续自动重试；
- 修复说明取自 Variable `UPGRADE_REPAIR_INSTRUCTIONS`（可留空，AI 按失败证据自行判断）；
- 分支不重建，修完直接重新走双架构验证与 open-pr；
- 设 `AUTO_REPAIR_UPGRADES=false` 可关闭自动修复。

人工兜底入口是 [`repair_upgrade.yml`](.github/workflows/repair_upgrade.yml)（手动触发，可指定具体修复说明，也可对自动修复失败的结果再修一轮）：

| 输入 | 含义 |
|------|------|
| `source_run_id` | 失败的升级运行 ID（artifact 名称里的 run id） |
| `app` | 要修复的应用名 |
| `instructions` | 给 AI 的修复说明（失败原因判断、希望保留/调整的构建步骤），可留空 |

它复用 `_upgrade_app.yml` 的 repair 模式：下载失败运行的 `task-spec` 与双架构 evidence（含诊断日志尾部），由 [`upgrade_repair.py`](scripts/harness/upgrade_repair.py) 在**已有的升级分支**上修复 `Dockerfile` / `tests/test.sh` 并推回同一分支，然后走同一套双架构验证与开 PR。分支不存在时直接报错——repair 只修复已有分支。

### 4.4 已是最新版本的审计与修复

Issue（或手动清单）给出的目标版本已在目标仓时不跳过，由 [`_audit_app.yml`](.github/workflows/_audit_app.yml) 审计并修复（独立分支 + PR，不直接改主分支）：

```
clone 目标仓 → 确定性检查 → upgrade_auditor Agent → upgrade_fixer Agent
→ 更新 Dockerfile / doc/image-info.yml → 推 auto/image-audit 分支
→ x86_64 + aarch64 原生构建与功能测试 → 两个架构都通过才开 PR
```

- **确定性检查**（[`upgrade_audit.py`](scripts/harness/upgrade_audit.py)）：`ARG VERSION` / `ARG TAG` / `git clone -b` 是否指向清单版本与 tag、`meta.yml` 是否登记该版本、是否存在 `tests/test.sh`、是否使用 `EXPECTED_VERSION`，以及 `doc/image-info.yml` 是否合法、是否包含目标版本与测试脚本命令。
- **AI 审计**（[`upgrade-auditor.md`](.github/agents/upgrade-auditor.md)）：判断 Dockerfile 是否有问题、是否按上游证据构建、构建出的镜像版本是否正确、测试脚本是否足够；输出 `ok / issues / critical` 与逐条问题。
- **AI 修复**（[`upgrade-fixer.md`](.github/agents/upgrade-fixer.md)）：修正 Dockerfile 的版本/tag/构建源，并按测试脚本更新 `doc/image-info.yml` 的 `usage`、`tags` 与结构；修复结果先过确定性校验，再ersion>` 分支。
- **双架构原生校验**：与升级链路一致，修复分支在 x86_64 / aarch64 各自真实构建并跑功能测试，任一架构失败都不开 PR（证据留在 artifact），避免把编译错误丢给目标仓 CI 再回流。
- **报告**：`audit.json`、`audit.md` 写入 job summary 与 artifact；没有实际改动时只出报告，不开 PR。
- **本地试跑**：`upgrade_audit.py --item '<audit item>' --repo source-repo --dry-run` 只跑确定性检查；加 `--deliver` 会调用 AI 修复并推送/开 PR；`--prepare` 只推分支（工作流用），`--open-pr --delivery <delivery.json>` 在校验通过后开 PR。

### 4.5 升级证据

升级证据来自触发 Issue 的正文，自动升级不再抓取 upstream-dashboard：

- Issue 正文是证据 JSON：`software`（`name` / `repo_url` / `version`）必填，`upstream_evidence`、`l3_evidence`、`install_candidates` 可省略；字段约束见 [`docs/new-version-issue-guide.md`](docs/new-version-issue-guide.md)；
- [`parse_issue.py`](scripts/harness/parse_issue.py) 校验必填字段，并要求 `software.name` / `software.version` 与标题一致；[`upstream_evidence.py`](scripts/lib/upstream_evidence.py) 把它归一化为 `source=gitcode-issue` 的证据包，保留原始字段；
- [`upgrade_scan.py`](scripts/harness/upgrade_scan.py) 只在应用同名时把该证据写入升级矩阵，其它条目仍回落到 `source=manual`；
- 证据会出现在 PR 正文、Dockerfile 生成提示与测试生成提示里，**只作参考，不参与门禁**；上游版本是否真实可用，由 AI 生成与双架构构建/功能测试兜底验证。
- `install_candidates` 是候选安装方式，最终由 Agent 按实际 Dockerfile 决定 `install_mode`；升级 PR 标题携带该方式对应的 `[kunpeng-install:<source|binary>]` 标记。

### 4.6 PR CI 修复组件（手动）

入口是 [`ci_fix_pipeline.yml`](.github/workflows/ci_fix_pipeline.yml)，真正链路在可复用组件 [`_ci_repair.yml`](.github/workflows/_ci_repair.yml)。`workflow_dispatch` 指定 `source_repo` / `pr_number`，或 `repository_dispatch`（`run-ci-fix`）由外部系统显式调用；Monitor [`monitor_ci_failed_prs.yml`](.github/workflows/monitor_ci_failed_prs.yml) 只保留手动触发，**不再有 cron 自动轮询**。需要批量重扫时人工运行 Monitor。

#### 4.6.1 单 run 串行的修复链路

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

**轮次怎么推进：** 复验把 `verify_passed` 交给 workflow——失败且仍有预算时开下一轮（job 名字里直接写着第几轮），预算用尽（`MAX_VERIFY_ROUNDS=2`，合计 3 轮）时该轮 job 失败、链路终止并保留证据。跨周期预算按 run 计数：同一 PR 最多 6 个 run，是第几次修复写在 run 标题的 `attempt` 上（`ci-fix PR#1234 · attempt 3 · <repo>`）；跑满 6 次即停止重试并在源 PR 上提示人工。

**日志抓取策略：** 从 PR 评论表格逐行（`<tr>`）解析，排除 `/trigger/`、`/gate/`、`/pre-check/` 编排层 URL，只取同行带 FAILED 标记的架构构建 URL，并按架构标识加权评分；日志取末尾 500 行（失败几乎总在尾部）。重试时 CI 结果表格出现在 Fix PR 评论中，会自动切换到 Fix PR 编号查询。若日志末尾是 `Finished: SUCCESS` 却仍带 `ci_failed` 标签，说明拉到的是编排层日志，诊断报告会标记「证据不足」而不是猜根因。

#### 4.6.2 Agent 分工

| Agent | 职责 |
|-------|------|
| [`ci-failure-analyst.md`](.github/agents/ci-failure-analyst.md) | CI 失败诊断师：错误类型分类、前置一致性检查、结构化诊断报告 |
| [`dockerfile-builder.md`](.github/agents/dockerfile-builder.md) | 容器构建修复工程师：起容器 → 逐条执行 → 失败即修 → 反推 Dockerfile → `docker build` 验证（最小 diff + 双架构约束） |

两个 Agent 只产出报告与 Dockerfile，不做任何 git / 平台写操作；写操作集中在 `code-fix` 阶段由确定性代码执行。

#### 4.6.3 数据分支与知识库

| 分支 | 内容 |
|------|------|
| `main` | 工作流代码 + [`docs/ci-failure-patterns.md`](docs/ci-failure-patterns.md)（按失败模式分类的知识库） |
| `ci-fix-log` | `{pr-number}/ci-analysis.md`（诊断报告）+ `fix-summary.md`（修复摘要） |

修复通过 CI 后，再次手动运行 Monitor 会把该 PR 的诊断与修复摘要追加进知识库；下次诊断时作为历史模式注入提示，同类问题置信度显著提升。

#### 4.6.4 本地验证

```bash
python -m pytest tests/test_ci_fix_workflow.py tests/test_ci_gitcode_api.py \
  tests/test_fix_pr_body.py tests/test_process_pr_events.py \
  tests/test_build_runner.py tests/test_build_fix_feedback.py \
  tests/test_opencode_run.py tests/test_stage_common.py -v
```

覆盖编排结构（单 run 串行、轮次门控）、URL 评分与日志抓取、Fix PR 标题/正文生成、跳过规则、Dockerfile 解析/定位/diff、复验结果的轮次交付。

---

## 5. 场景三：openEuler 版本升级

上游应用版本升级由[场景二](#4-场景二应用自动升级)承接。场景三只保留 openEuler 大版本升级链路，验证组件 [`_upgrade_versions.yml`](.github/workflows/_upgrade_versions.yml) 负责：生成候选 → 双架构构建 → 运行既有测试套件；重试时跳过生成，只重跑构建与测试（Fixer 的改动已落盘）。

| 工作流 | 触发 | 流程 |
|--------|------|------|
| [`upgrade_openeuler_versions.yml`](.github/workflows/upgrade_openeuler_versions.yml) | `repository_dispatch: oe-new-version` / 手动 | 检测新 oe 版本 → 枚举全部应用 Matrix 并行（`fail-fast: false`）→ 成功者汇总批量 PR，失败者出报告 |

**升级版本**由 GitCode `【new-version】` Issue 提供（正文带上游证据），手动触发时也可用软件清单维护 `version` / `source_url`（可选 `tag`）；清单项缺字段时跳过并记录原因，也可用场景二手动入口指定 `app` + `version` + `source_url` 完成单个应用升级。

**PR 去重**：场景一 / 三 / 四按标题精确匹配；场景二按升级分支 `auto/version-update/<app>/<version>-<oe_tag>` 判断目标仓是否已有 open PR。

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

### Q: CI 修复组件手动跑了但没有触发修复，怎么排查？

1. 目标仓 PR 是否确实带 `ci_failed` 标签（不是拼写变体）；
2. `config/watchlist.json` 中该仓库的 `enabled` 是否为 `true`；
3. PR 标题是否命中跳过规则（预发布版本或 `fix:` 前缀）；
4. `DISPATCH_TOKEN` / `GITCODE_TOKEN` 是否具备所需权限；
5. 查看 **Watch CI failed PRs** 的运行日志，搜索 `→ Skipping` 或 `❌`。

### Q: Fix PR 的 CI 又失败了怎么办？

手动再触发一次修复：对**原始 PR** 重新 dispatch，`ci-log-analysis` 会结合新的失败日志，AI 对 Fix PR 追加 commit 重试；同一 PR 累计 6 个 run 仍未通过则停止并提示人工介入。

### Q: CI 修复组件为什么要在容器里逐条执行，而不是直接改 Dockerfile？

文本层面的盲改无法证明改动真的能构建通过。在容器里逐条执行 `RUN` 并即时修复，跑通的命令序列才是"已被证明可行"的；再反推回 Dockerfile 并用 `docker build` 从零复验一次，确保反推没有引入偏差。

### Q: 想手动跳过某条 PR 怎么做？

移除该 PR 的 `ci_failed` 标签即可，下次手动扫描不再处理它。

### Q: 不想搭自托管机器，能直接跑在 GitHub 托管 Runner 上吗？

可以，手动触发 **Fix PR CI failures** 时把三个标签输入换成托管标签：轻量的用 `["ubuntu-latest"]`，amd64 修复用 `["ubuntu-latest"]`，arm64 修复/复验用 `["ubuntu-24.04-arm"]`（arm64 托管 Runner 目前**仅公开仓免费**）。三点注意：

1. **缓存退化**：托管 Runner 每次都是干净环境，工具链（hadolint / jq / opencode）会在每个 Job 重新下载；`/opt/oe-image-tools` 的跨 Job 缓存只有自托管 Runner 才有。
2. **6 小时/job 上限**：托管 Runner 超过即被砍；自托管没有这个限制。重型镜像（如源码编译的 milvus）整轮修复可能被砍在构建中途——那属于预算不足，不是修复失败。
3. **预装差异**：托管的 Ubuntu Runner 自带 Docker、buildx 与 `gh`；自托管机器需要自己装（`gh` 只在 GitHub 平台的 Fix PR 创建路径上用到）。

要把选择固定下来就设对应 Variables。

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
│   │   ├── testcase-creator.md              # ①④ 测试生成者
│   │   ├── testcase-qa.md                   # ①④ 测试挑战者
│   │   ├── ci-failure-analyst.md            # CI 修复组件：失败诊断师
│   │   ├── dockerfile-builder.md            # CI 修复组件：容器构建修复工程师
│   │   └── code-fixer.md                    # ①③ 修复者（内置故障诊断）
│   ├── workflows/
│   │   ├── monitor_new_image_issues.yml     # ① Issue 扫描与认领（cron */5）
│   │   ├── create_new_images.yml            # ① 主编排（prepare → 4 轮 → 交付）
│   │   ├── _create_new_image_rounds.yml     # ① 单轮验证-修复-决策组件
│   │   ├── upgrade_upstream_versions.yml    # ② 应用自动升级主编排（手动；定时测试期关闭）
│   │   ├── _upgrade_app.yml                 # ② 单应用升级组件（prepare → x64/arm64 容器重放 → 双架构验证 → PR）
│   │   ├── generate_test_scripts.yml        # ④ 存量补功能测试（手动单应用）
│   │   ├── monitor_ci_failed_prs.yml        # CI 修复组件：扫 ci_failed PR（仅手动）
│   │   ├── ci_fix_pipeline.yml              # CI 修复组件入口薄壳（手动 / repository_dispatch）
│   │   ├── _ci_repair.yml                   # CI 修复组件（prepare → 分析 → 3 轮修复 → 落回）
│   │   ├── _ci_fix_round.yml                # CI 修复组件：单轮修复（arm64 首修 → amd64 → arm64 复验）
│   │   ├── upgrade_openeuler_versions.yml   # ③ openEuler 版本升级
│   │   ├── _upgrade_versions.yml            # ③ 共享验证组件
│   │   ├── issue_contract_test.yml          # GitCode Issue API 契约冒烟
│   │   └── test-e2e.yml                     # 开发自测（不创建真实 PR）
│   ├── toolchain.lock.yml                   # 工具链版本 + SHA256 锁
│   └── python-phase1.lock.txt               # Python 依赖锁
├── config/
│   ├── watchlist.json                       # CI 修复组件的仓库列表与轮询参数（仅手动扫描使用）
│   └── upgrade-apps.yml                     # ② 场景二软件清单（人工维护，不遍历目标仓）
├── scripts/
│   ├── harness/
│   │   ├── flow.py                          # 阶段一确定性编排入口
│   │   ├── run.py                           # 场景③ legacy Agent/测试入口
│   │   ├── parse_issue.py                   # Issue 解析与领域映射
│   │   ├── query_version.py                 # 上游 / oe 版本对比查询
│   │   ├── validate_meta.py                 # meta.yml schema 校验
│   │   ├── gate_diff.py                     # "只能新增"差分门禁
│   │   ├── compose_pr.py                    # PR 内容组装
│   │   ├── upgrade_scan.py                  # ② 版本发现（清单版本 vs 目标仓 → 升级矩阵）
│   │   ├── upgrade_apply.py                 # ② 单应用升级（补测试 + AI 生成 Dockerfile + 推分支）
│   │   ├── upgrade_open_pr.py               # ② 升级 PR 正文与跨仓 PR
│   │   ├── testgen_scan.py                  # ④ 指定应用解析
│   │   └── testgen_generate.py              # ④ 测试脚本生成与静态校验
│   ├── stages/                              # CI 修复组件阶段脚本：ci-log-analysis / build-fix / code-fix
│   ├── watch/                               # CI 修复组件：PR 轮询与入口解析
│   ├── lib/                                 # 见下节模块说明
│   ├── utils/scoring.py                     # 置信度计算
│   ├── bootstrap_tools.py                   # 工具链落地
│   └── runner_preflight.py                  # Runner 能力自检
├── docs/
│   ├── failure-patterns.yml                 # verified 结构化故障模式
│   ├── failure-patterns.md                  # 知识库维护策略
│   ├── ci-failure-patterns.md               # CI 修复组件的失败模式知识库
│   └── runbooks/                            # 运维手册
├── templates/
│   ├── new-image-issue.md                   # 场景一 Issue 模板
│   ├── new-version-issue.md                 # 场景二 Issue 模板（标题 + 上游证据 JSON）
│   └── pr.md                                # PR 模板
├── tests/                                   # 本仓单元、契约与工作流回归测试
├── requirements.txt                         # 运行时依赖（requests）
├── DESIGN.md                                # 系统设计与关键决策
└── REQUIREMENTS.md                          # 项目目标与约束
```

> ① = 场景一（新增镜像）　② = 场景二（应用自动升级）　③ = 场景三（openEuler 版本升级）　④ = 场景四（补功能测试）　其余为共享能力（CI 修复组件为手动入口）

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
| [`scripts/lib/agent_runtime.py`](scripts/lib/agent_runtime.py) | Agent 进程管理与结构化输出契约 |
| [`scripts/lib/ai_provider.py`](scripts/lib/ai_provider.py) | 所有场景统一的模型、provider、baseURL、API Key 与超时配置 |
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

### 10.5 场景二：应用自动升级

| 模块 | 职责 |
|------|------|
| [`scripts/lib/upstream_dashboard.py`](scripts/lib/upstream_dashboard.py) | 独立的 upstream-dashboard 客户端（`version/resolve` + 证据抓取），仅供工具/历史脚本使用；场景二自动升级**不再调用** |
| [`scripts/lib/upstream_evidence.py`](scripts/lib/upstream_evidence.py) | 证据适配与 PR / 提示词渲染：把 Issue 上游证据归一化为 `source=gitcode-issue`（保留 L1 证据、`l3_evidence`、`install_candidates`），也支持手动 `source=manual` 证据，生成 PR 正文与提示词片段 |
| [`scripts/lib/app_notes.py`](scripts/lib/app_notes.py) | 应用注意点：读取 `config/app-notes/<app>.md` 注入提示与构建预算；把 Agent 返回的 `app_note` 合并为按版本隔离的「自动沉淀」章节，保留人工内容 |
| [`scripts/harness/publish_app_note.py`](scripts/harness/publish_app_note.py) | 把 Agent 总结的 app note 推到 `auto/app-note/<app>` 分支并向本仓开独立 notes PR |
| [`scripts/harness/upgrade_scan.py`](scripts/harness/upgrade_scan.py) | 版本发现：Issue 证据 / 清单手动 `version` / `source_url` × 目标仓已有版本 → 升级矩阵 + 目标版本已存在的审计矩阵 |
| [`scripts/harness/upgrade_audit.py`](scripts/harness/upgrade_audit.py) | 目标版本已存在的审计与修复：确定性检查版本/tag/meta/测试脚本/image-info，AI 审计后调修复 Agent，更新 Dockerfile 与 doc/image-info.yml，推修复分支，双架构原生校验通过后开 PR |
| [`scripts/utils/scrape_upgrade_apps.py`](scripts/utils/scrape_upgrade_apps.py) | 一次性工具：从看板拉软件列表（`--domain kunpeng` / `ascend`），匹配目标仓目录，生成初始 `config/upgrade-apps.yml` |
| [`scripts/lib/version_upgrade.py`](scripts/lib/version_upgrade.py) | 确定性落盘：复制版本目录、写入 AI 生成的 Dockerfile、更新 README/doc 版本号、追加 `meta.yml`；生成内容不符合目标版本即失败并清理 |
| [`scripts/harness/upgrade_apply.py`](scripts/harness/upgrade_apply.py) | 单应用升级：切分支、AI 依 Issue 证据 / 清单版本与上游源码生成 Dockerfile、缺测试则补、确定性落盘、commit、推送，并产出 `task-spec.json` |
| [`scripts/harness/upgrade_open_pr.py`](scripts/harness/upgrade_open_pr.py) | 升级 PR 正文（变更 + 功能测试状态 + 升级证据）与跨仓 PR 创建 |

### 10.6 CI 修复组件（手动，独立子系统）

CI 修复组件自带一套平台与 AI 调用层（`ci_*` 与 `ai_runner` / `opencode_run`），与场景一的 `gitcode_client.py` / `agent_runtime.py` 并存且互不依赖——它面向的是"修复别人仓库里已有的 PR"，与场景一的生成交付链路没有共享状态。

| 模块 | 职责 |
|------|------|
| [`scripts/watch/process_pr_events.py`](scripts/watch/process_pr_events.py) | 手动扫描：PR 状态、Fix PR 决策、跳过规则与 dispatch（含 attempt 计数） |
| [`scripts/watch/resolve_pr.py`](scripts/watch/resolve_pr.py) | 入口解析（prepare）：两种入口统一成一份 PR 元数据并写入 `$GITHUB_OUTPUT` |
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
| [`docs/failure-patterns.md`](docs/failure-patterns.md) | 场景一 / 三 故障知识库的组织与维护策略 |
| [`docs/ci-failure-patterns.md`](docs/ci-failure-patterns.md) | CI 修复组件的失败模式知识库（按模式分类，修复通过 CI 后追加） |
| [`docs/runbooks/`](docs/runbooks/) | 运维手册 |
| [openeuler-docker-images](https://gitcode.com/openeuler/openeuler-docker-images) | 目标仓库与其现行规范 |
| [easysoftware-autoupgrade](https://github.com/opensourceways/easysoftware-autoupgrade) | 社区已有的镜像升级系统；场景二取代其升级链路（版本与上游证据改由 `【new-version】` Issue 提供） |
| [docker-images-workflow](https://github.com/FdeCad/docker-images-workflow) | CI 修复组件的来源仓库：CI 失败自动修复流水线（容器内逐条修复、arm64 复验、Fix PR 自管理） |
