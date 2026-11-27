# openEuler 容器镜像自动化系统设计

> 版本 2.1，基于 openEuler 社区规范、现有 Agent 实验及 easysoftware-autoupgrade 实践的综合研究

---

## 目录

1. [系统概览](#1-系统概览)
2. [仓库规范与目录结构](#2-仓库规范与目录结构)
3. [核心工作流设计](#3-核心工作流设计)
4. [Agent 协作架构](#4-agent-协作架构)
5. [测试策略](#5-测试策略)
6. [构建流水线](#6-构建流水线)
7. [版本管理](#7-版本管理)
8. [PR 自动化规范](#8-pr-自动化规范)
9. [技术选型](#9-技术选型)
10. [风险与缓解](#10-风险与缓解)
11. [项目结构](#11-项目结构)

---

## 1. 系统概览

### 1.1 定位

通过 GitHub Actions 部署，实现 openEuler 应用容器镜像的全自动化创建、更新和维护。由确定性代码承载主流程，Agent 处理不确定性决策，构成对抗协作闭环。

### 1.2 核心场景

| 场景 | 触发方式 | 输出 |
|------|---------|------|
| ① 新增应用镜像 | GitCode Issue（`【自动升级需求】add <app> <version> docker image on openEuler <version>`） | PR：完整镜像目录 + 文档 + 测试 |
| ② 应用上游版本升级 | GitCode Issue（`【自动升级需求】upgrade <app> to <version> on openEuler <version>`，正文带上游证据字段）/ 手动 | PR：新版本镜像目录（或审计修复）+ conda 版本登记 |
| ③ openEuler 大版本升级 | GitCode Issue（`【自动升级需求】upgrade openEuler to <version>`） | 一任务一 PR：应用新增 oe 版本子目录 |
| ④ 存量补功能测试 | 手动指定软件名 | PR：`tests/test.sh` + Dockerfile 空行 |

> PR CI 失败修复抽成可复用的手动组件（`_ci_repair.yml`），不再自动轮询，不作为独立场景。

### 1.3 设计原则

- **确定性承载不确定**：主流程由代码承载（GitHub Actions Workflow + Python），不可预见的决策（Dockerfile 编写、故障诊断、测试生成）由 Agent 处理
- **只能新增，不能修改**：已有镜像目录为只读，新版本只能追加新目录
- **分层协作**：Image Creator 不再经过 Image QA 复核，生成结果直接进入确定性镜像门禁；Testcase Creator + Testcase QA 保留 QA 对抗复核，之后统一进入本地验证
- **本地验证**：提 PR 前在 Actions Runner 上完成双架构构建 + 测试，结果内嵌 PR 描述
- **一次性执行模型**：每次事件（webhook / workflow_dispatch）触发后独立运行，执行完毕后退出（参考 easysoftware 的 `System.exit(0)` 模式）

### 1.4 与 easysoftware-autoupgrade 的关系

`easysoftware-autoupgrade` 是 openEuler 社区已有的容器镜像自动升级系统（Java SpringBoot 应用），与本系统操作同一目标仓库 `openeuler/openeuler-docker-images`。我们从它的实现中提取了已验证的模式并作出适应性调整：

**采纳的模式：**

| 模式 | easysoftware 的实现 | 本系统的采用 |
|------|--------------------|-------------|
| 一次性执行 | `Application.main()` 调用任务后 `System.exit(0)`，由 cron 容器定时拉起 | 每个 GitHub Actions Workflow 独立运行，编排器执行完毕后退出。由 GitCode Issue 轮询或 `workflow_dispatch` 触发 |
| 上游版本监控 | easysoftware 的 `projectsInfoUrl` 数据来自 anitya，覆盖 GitHub / PyPI / npm / Rubygems / CPAN 等生态的上游版本跟踪 | **不再复用**。版本与上游证据由 `【自动升级需求】` Issue 提供（`add` / `upgrade` / `upgrade openEuler` 三种后缀，旧标题已下线）；新应用仍在 `doc/image-info.yml` 中补齐 `upstream` 块与顶层 `homepage`（见 2.3 节），供人工判断上游 |
| PR 去重 | `checkHasCreatePR()` 遍历已有 open PR，按 title 精确匹配，命中则跳过 | 同样按 title 匹配去重，PR 生成前检查，防止重复提交 |
| 批量更新 | `batchUpdatePremiumApp()` 遍历 DockerHub 上所有 openEuler OS 版本，对缺最新镜像的版本生成 Dockerfile | oe-upgrade 场景改为按 Issue 驱动、一次推进一个任务的串行调度，避免整批并发抢占构建机与重复开 PR |
| 差异化 Dockerfile | 复制已有版本的目录树，替换 Dockerfile 中的版本字符串，更新 meta.yml | 复制已有版本目录 + 追加 meta.yml；Dockerfile 不机械替换版本串，由升级 Agent 结合触发 Issue 的上游证据包与固定 tag 源码重新生成，再经双架构构建裁决 |
| 分支策略 | Fork 到 bot 账号 → 跨仓库 PR | **按凭据权限二选一**：无目标仓写权限时推 fork、提跨仓 PR；有写权限时直推目标仓、提同仓 PR。两者只差一个配置项（见 8.3 节） |

**调整的决策：**

| 维度 | easysoftware | 本系统选择 | 原因 |
|------|-------------|-----------|------|
| 文件操作 | easysoftware 通过 Git Data API 直接操作 tree/blob，不 clone | **Git clone → modify → commit → push** | 我们需要 build + test 验证，必须有本地文件系统；API 模式适合纯文本替换，不适合构建验证 |
| 构建验证 | 无（由仓库 CI 单独处理） | **PR 生成前在 Runner 上完成** | 这是需求的硬要求：提 PR 前必须证明 Dockerfile 可构建且通过测试 |
| 运行载体 | SpringBoot 独立部署 | **GitHub Actions** | 这是系统部署约束：必须通过 GitHub Actions 部署 |

**互补关系：** 两个系统操作同一仓库但触发条件和覆盖范围不同。easysoftware 侧重持续性的版本跟踪和批量升级，本系统改为 GitCode Issue 驱动，并在此基础上增加了新镜像创建、分层 Agent 协作质量保障、双架构构建验证。两者不共享版本检测服务，互不冲突。

#### easysoftware 完整接口清单

通过分析 `EasysoftwareVersionHelper`、`CollectConfig`、`ApplicationVersionTask`、`ApplicationUpdateHandler` 等源码，梳理出 easysoftware 的全部上游接口及操作模式。本设计明确注明每个接口的采用策略。

**上游接口（数据获取）：**

| 接口 | 后端 | 用途 | 来源文件 | 本系统采用 |
|------|------|------|---------|-----------|
| `projectsInfoUrl` + appName | anitya | 返回上游最新版本（`app_up`）、社区版本（`app_openeuler`）、OS 版本（`raw_versions`） | `EasysoftwareVersionHelper.initUpdateInfo()` | **未采用**：版本与证据由 Issue 提供 |
| `backupProjectsInfoUrl` + appName | anitya（备用） | 主源返回空时的 fallback | 同上 | 未采用 |
| `apppkgInfoUrl` + 分页（pageSize=50） | 软件市场 | 获取全量"精品应用"清单（name + pkgId） | `EasysoftwareVersionHelper.getEasysoftApppkgSet()` | 未采用 |
| `apppkgDetailUrl` + pkgId | 软件市场 | 获取应用详情（维护者邮箱等） | `EasysoftwareVersionHelper.setAppkgMail()` | 未采用 |
| `openEulerOsVersionInfoUrl` | datastat.openeuler.org | 获取 openEuler 最新 OS 版本 | `EasysoftwareVersionHelper.getOpeneulerLatestOsVersion()` | 未采用：目标版本由 Issue 指定 |
| `dockerHubOpeneulerOsVersionInfoUrl` | DockerHub | 获取 openEuler 全部 OS 版本列表 | `EasysoftwareVersionHelper.getDockerHubOpeneulerOsVersion()` | 未采用 |

**下游操作：**

easysoftware 通过 API 完成 fork → branch → tree API → commit → PR 的调用链。本系统操作 GitCode 仓库，通过 GitCode API 实现对应操作，核心差异在于：

- **分支去向随凭据权限变化**：有目标仓写权限则直推，无则推 fork 后提跨仓 PR。PR 与 Issue 始终落在目标仓
- **clone 而非 API 操作文件**：本系统需要 build + test 验证，必须有完整本地文件系统
- **PR 去重后创建**：逻辑与 easysoftware 一致，但调用 GitCode PR API

easysoftware 的 SMTP 邮件通知改为 GitHub Actions workflow 通知 + PR/Issue 描述。

### 1.5 实施阶段

场景一 / 三共享同一套编排、生成、验证、交付能力，差异只在触发输入与调度方式；场景二是独立的升级链路（见 3.3 节），CI 修复组件是独立的手动链路（见 3.4 节）。因此按场景分阶段交付，每阶段以一条可独立验证的能力收口：

| 阶段 | 范围 | 完成判据 |
|------|------|---------|
| 一 | 场景一：新增应用镜像 | 创建标题为 `【自动升级需求】add ...` 的 Issue 后，无人工介入即产出通过全部门禁、双架构构建与测试均有证据的 PR |
| 二 | 场景二：应用上游版本自动升级 | GitCode `【自动升级需求】upgrade ...` Issue 驱动：缺新版本即补测试 + AI 依证据生成 Dockerfile + 双架构验证；已是最新则审计并修复，一应用一 PR |
| 三 | 场景三：openEuler 大版本升级 | GitCode `【自动升级需求】upgrade openEuler to <version>` Issue 驱动：控制器按领域串行推进，每个任务完成 prepare → 4 轮双架构校验 → 封存 → PR，并回写 Issue 汇总 |
| 四 | 场景四：功能测试脚本补齐 | 手动指定软件后，为最新镜像目录产出通过 KunpengTest 静态校验的一软件一 PR（附 Dockerfile 空行触发目标仓构建 + 功能测试 CI） |

**场景二的来源与边界：** 取代社区 anitya + easysoftware-autoupgrade 的升级链路。版本与上游证据由 GitCode `【自动升级需求】upgrade ...` Issue 提供（旧标题已下线），扫描阶段只对比目标仓已有目录；Dockerfile 由 AI 结合证据包与固定上游源码重新生成，目录复制与元数据登记由确定性代码承担。目标版本已存在时不跳过，审计后由修复 Agent 更新 Dockerfile 与 `doc/image-info.yml` 并开 PR。

**CI 修复组件的来源与边界：** 完整移植自 [docker-images-workflow](https://github.com/FdeCad/docker-images-workflow)，保留其独立子系统（`scripts/stages/`、`scripts/watch/`、`config/watchlist.json` 与 `ci_*` 库），仅适配本仓的 Runner 标签、锁定工具链与凭据约定。它与其它场景不共享 TaskSpec / 候选包 / 门禁体系——它操作的是目标仓已有的 PR，不生成新的镜像目录，且只保留手动 / 显式 dispatch 入口。

**场景四的来源与边界：** 目标仓把功能测试与 CI 构建绑定（Dockerfile 变更即构建，成功后按 `{app}/tests/test.sh` 执行功能测试），但存量应用大多缺测试脚本。场景四手动指定软件名后，定位目标仓该软件的最新镜像目录，Agent 按 [KunpengTest 规范](https://github.com/opensourceways/upstream-dashboard/blob/KunpengTest/README.md)生成脚本，静态校验通过后一软件一 PR，并给该软件最新 Dockerfile 追加一个空行以触发目标仓绑定的构建 + 测试 CI。它复用场景一的 Agent 运行时（`agent_runtime.run_agent`）与场景二的 fork / 跨仓 PR 交付，但脚本规范独立（KunpengTest：禁 `set -e`、脚本内自拉服务、五个注入环境变量、PASS/FAIL 输出约定），不做实跑验证（仅静态校验，失败重试 2 轮后写 `testgen-log` 分支的 exhausted 标记转人工）。不再定时轮询外部服务，也不再批量扫描。

**写入目标的分级。** 阶段一的写入目标限定为测试仓，生产仓需显式配置开启。配置缺失、为空或错误时一律解析为测试仓，任何情况下都不得回退到生产仓——自动化对目标仓持有 push 权限，误写的代价由社区承担。

---

## 2. 仓库规范与目录结构

### 2.1 目标仓库顶层

```
openeuler-docker-images/
├── AI/                  # AI 软件栈
├── Base/                # 基础镜像（openeuler 基础镜像的 Dockerfile）
├── Bigdata/             # 大数据组件
├── Storage/             # 存储组件
├── Database/            # 数据库
├── Cloud/               # 云原生
├── Distroless/          # 无发行版
├── HPC/                 # 高性能计算
├── Security/            # 安全相关
├── Others/              # 其他
├── config/              # 仓库配置
└── tests/               # 历史测试套件（不再新增，新应用用 <app>/tests/）
```

每个场景目录含 `image-list.yml`，维护应用名到路径的映射。

### 2.2 最小目录单元（MDU）

```
<app-name>/
├── README.md                        # 快速参考、功能描述、Tag 表、使用方法、FAQ
├── meta.yml                         # Tag 与 Dockerfile 路径映射
├── doc/                             # 软件中心展示（可选）
│   ├── picture/logo.png
│   └── image-info.yml
└── <app-version>/                   # 如 1.27.2
    └── <oe-version>/                # 如 24.03-lts
        └── Dockerfile
```

### 2.3 doc/image-info.yml

包含两类内容：软件中心的展示字段（`name`、`category`、`description`、`environment`、`tags`、`download`、`usage`、`license`、`similar_packages`、`dependency`），以及版本监控配置（`upstream` 块与顶层 `homepage`）。

```yaml
name: mariadb
category: database
# ... 展示字段 ...
upstream:
  version_url: MariaDB/server                  # 上游项目标识，非完整 URL
  version_prefix: mariadb-                     # 上游 tag 的版本前缀，剥离后为版本号
  backend: GitHub                              # anitya backend
  version_scheme: RPM                          # 版本比较方案
  version_filter: alpha;rc;candidate;beta;pre  # 预发布过滤
homepage: https://github.com/MariaDB/server
```

`homepage` 与 `upstream` **平级**，不在 `upstream` 内部。

| 字段 | 必填 | 说明 |
|------|------|------|
| `upstream.version_url` | 是 | 上游项目标识，GitHub backend 下形如 `owner/repo` |
| `upstream.backend` | 是 | `GitHub` / `PyPI` / `npm` / `Rubygems` / `CPAN` 等，对应 anitya `Project.backend` |
| `upstream.version_scheme` | 是 | 版本比较方案，如 `RPM` |
| `upstream.version_filter` | 是 | 预发布过滤，惯例值 `alpha;rc;candidate;beta;pre` |
| `upstream.version_prefix` | 上游 tag 带前缀时必填 | 如 `mariadb-` |
| `upstream.regex` | 否 | 上述字段无法表达时，用正则自定义版本抽取 |
| `homepage` | 是 | 上游主页 URL |

生成器**读时宽容**（缺失字段不阻断）、**写时严格**（按上表产出，字段顺序固定）。

**字段用途：** `upstream` 块是目标仓的展示与上游元数据约定，本流水线生成时仍按此规范产出，但**不再**据此查询 anitya：升级版本与上游证据由触发 Issue 提供。项目在上游平台不存在或字段缺失时不阻断生成，只要求写时按上表产出。

### 2.4 meta.yml

`path` 为 **MDU 相对路径**（相对 `meta.yml` 所在目录），不带应用名前缀：

```yaml
# Bigdata/kylin/meta.yml
# Tag: <app-ver>-oe<oe-ver-short>
5.0.2-oe2403sp1:
  path: 5.0.2/24.03-lts-sp1/Dockerfile
  arch: aarch64          # 可选；省略 = 双架构
5.0.3-oe2403sp4:
  path: 5.0.3/24.03-lts-sp4/Dockerfile
```

目标仓存量数据中另有两种少数写法：仓库根相对（`Database/redis/8.0.2/...`）与带前导斜杠（`/7.4.1/...`）。解析器按 MDU 相对 → 仓库根相对 → 去前导斜杠依次尝试，生成一律产出 MDU 相对。

`meta.yml` 校验只针对本次变更的 MDU；范围外的存量问题记为 warning，不阻断本次变更。

### 2.5 Dockerfile 规范

```dockerfile
ARG BASE=openeuler/openeuler:24.03-lts-sp2
FROM ${BASE}

RUN yum install -y <packages> && \
    yum clean all
```

- 基础镜像：`openeuler/openeuler:<version>`
- 包管理器：`yum`
- 多阶段构建用于编译型应用

### 2.6 "只能新增"约束实现

1. 本地差分检查：`git diff --name-only origin/main...HEAD`，拒绝已有文件修改
2. meta.yml 和 README.md 为例外：仅允许在末尾追加条目（结构化解析验证）
3. 幂等检查：解析已有 `meta.yml` 确认 `<app-ver, oe-ver>` 组合不存在
4. PR 去重：提 PR 前遍历目标仓库已有 open PR，按 title 精确匹配。若已存在同名 PR（如 `[new-image] Add nginx 1.28.0 on 24.03-lts`），则跳过不创建。title 命名规则保证相同场景+相同应用+相同版本的 PR 只会存在一个。此机制直接借鉴 easysoftware 的 `checkHasCreatePR()`——其遍历所有 open PR（每页 100 条，多页），按 title 匹配判断是否已存在

---

## 3. 核心工作流设计

### 3.1 整体架构

```
                    ┌──────────────────────────┐
                    │   GitHub Actions 触发层    │
                    └──────────┬───────────────┘
                               │
                    ┌──────────▼───────────────┐
                    │     确定性编排器           │
                    │     (flow.py)             │
                    └──────────┬───────────────┘
                               │
                               │
                    ┌──────────▼───────────┐
                    │   Image Creator 生成    │
                    └──────────┬───────────┘
                               │
                    ┌──────────▼───────────┐
                    │ 确定性镜像门禁与 lint   │
                    └──────────┬───────────┘
                               │
                    ┌──────────▼───────────┐
                    │ Testcase Creator ↔ QA │
                    │     最多 2 轮          │
                    └──────────┬───────────┘
                               │
                    ┌──────────▼───────────┐
                    │ 双架构本地构建与测试    │
                    └──────────┬───────────┘
                               │
                    ┌──────────┴───────────┐
                    ▼                      ▼
                 提交 PR                 Fixer
                                           │
                                      最多 3 轮
                                           │
                                    needs-human-review
```

**关键时序：**
- Image Creator 不再进入 Image QA 语义复核；镜像预检、身份契约、hadolint 等确定性检查在 Testcase Creator 启动前完成，确定性失败仍可触发定向修复
- 镜像侧不再进行 Agent 语义复核，也不存在 QA 驱动的镜像修复轮次；固定 UID/GID 因缺少语义证明链而禁止，只允许动态身份或复用基础镜像已有身份
- Testcase Creator → QA1 → Creator 修正 → QA2；分歧不 veto，完成后由本地验证裁决
- Fixer **仅在本地验证失败后介入**，与本地验证形成 loop（最多 3 轮）
- 本地验证通过是提 PR 的唯一路径

### 3.2 场景一：新增应用镜像

```
GitCode Issue 创建（标题 `【自动升级需求】add ...`）
  → Webhook / Polling Bridge
    → parse_issue.py 解析 (package_name, source_repo_url, domain, os_version)
      → Image Creator 生成 → 确定性镜像门禁
      → Testcase Creator 生成 → QA1 → Creator 修正 → QA2；分歧不 veto
      → docker build（x86_64 + ARM64 并行）+ 测试执行
        ┌─ 通过？→ 最终目标门禁 → fork-deliver → 提 PR（附 Testcase QA 审查记录）
        └─ 失败？→ Fixer 分析日志 + 修复 → 重新本地验证
                                            ↑                    │
                                            └── loop（最多 3 轮）──┘
            3 轮后仍失败？→ 标记 needs-human-review
```

### 3.3 场景二：应用上游版本自动升级

正式入口是 GitCode `【自动升级需求】upgrade <app> to <version> on openEuler <version>` Issue，旧标题已下线：正文用平铺字段给出上游证据（`软件名` / `源码仓库` / `软件版本` 必填，可附 `上游支持检查点`、`中游检查点`、`安装候选`；旧的 JSON 块仍可识别），解析后归一化成 `software` / `upstream_evidence` / `l3_evidence` / `install_candidates`。手动触发时版本可由清单或参数兜底。

```
【自动升级需求】upgrade ... Issue
  → monitor_auto_upgrade_issues.yml（唯一 Issue 入口）
    → upgrade_upstream_versions.yml
    → discover：对比 openeuler-docker-images 与 conda-ecopkgs 已有版本
      → 缺新版本：_upgrade_app.yml
          prepare：AI 依证据生成 Dockerfile → 缺测试则补 → 确定性落盘 → 推分支
          validate-x86_64 ∥ validate-aarch64：原生构建 + 功能测试
          open-pr：两个架构都通过 → 跨仓 PR
      → 目标版本已存在：_audit_app.yml 审计 → 修复 Agent → 双架构复验 → 修复 PR
      → conda-ecopkgs：校验 anaconda.org 产物 → 登记 supported-versions.yml → PR
```

**为什么 Dockerfile 不机械替换版本串：** 上游新版本的构建方式可能变化，AI 必须结合证据包与固定 tag 源码重新生成；生成内容缺目标版本号或 `FROM` 即失败交人工。

**写入边界：** 只新增版本目录并追加 `meta.yml`，不改存量版本目录；每个应用一个 PR，互不影响。

### 3.4 PR CI 失败修复组件（手动）

此场景移植自 [docker-images-workflow](https://github.com/FdeCad/docker-images-workflow)，处理的是「PR 已经提出、但 CI 失败」的存量 PR。它不创建镜像目录，也不使用 TaskSpec 契约——输入是目标仓 PR 与 CI 日志，输出是落回源码的最小 diff。

```
目标仓 PR 需要修复
  → 手动运行 Watch CI failed PRs（扫描 watchlist）→ 跳过规则过滤
    → dispatch ci_fix_pipeline.yml（repository_dispatch: run-ci-fix，attempt=N）
      → prepare：两种入口统一解析 PR 元数据（标题 / head SHA / base 分支现查源仓库）
        → 分析：PR diff + 失败架构的 Jenkins 日志 + 知识库 → ci-analysis.md（写入 ci-fix-log 分支）
          → Round 1（_ci_fix_round.yml）：arm64 首修 → amd64 续修 → arm64 确定性复验
            → 复验失败且仍有预算 → Round 2：amd64 回修（架构中立）→ arm64 复验
              → 仍失败 → Round 3：同上（预算用尽即终止，run 标红并保留证据）
                → 任一轮复验通过 → code-fix：最终 Dockerfile 作为最小 diff 落回源码
                     → commit → push → Fix PR
                       → Fix PR CI 通过 → 评论原始 PR 通知 reviewer 合并 + 写入知识库
                       → Fix PR CI 再失败 → 再次手动运行 Monitor 重新 dispatch（attempt=N+1，最多 6 次，
                          超限关闭 Fix PR 并通知人工）
```

**一次修复 = 一个 run。** 阶段推进全部由 `needs:` 与 `verify_passed` 输出承担，
轮次是显式 job（`Round 1/2/3: fix and verify`），修复了几次、还剩几轮预算在
Actions 的 job 列表里直接可读；只有 Monitor 的跨周期重试是新 run，第几次写在 run
标题的 `attempt` 上。

**机器可换、架构不可换。** 三类 job（轻量 / amd64 修复 / arm64 首修与复验）的
runner 标签由 `prepare` 统一解析：手动入口读 `workflow_dispatch` 输入，自动入口
读 Variables，最后落到默认的自托管标签；解析结果经 job outputs 传给轮次组件。
架构相关的 job 只允许换"哪台 arm64/x64 机器"，不允许换架构——复验就是双架构保证
本身。托管 Runner 上 `/opt` 不可写时，工具链缓存根自动降级到 job 临时目录
（`phase1-setup`），因此同一套 workflow 在自托管与托管 Runner 上都能跑。

**与其它场景的差异：**

| 维度 | 场景一 / 三 | CI 修复组件 |
|------|-----------------|--------|
| 输入 | 结构化 Issue / webhook / 手动 | 目标仓已有的 PR + `ci_failed` 标签 |
| 修复方式 | 生成候选 → 双架构验证 → Fixer 依据报告改文件 | 容器内逐条执行 Dockerfile 指令、失败即修，再反推回 Dockerfile |
| 交付 | 新增目录的 PR | 落回源码的最小 diff Fix PR（`fix:` 前缀，可追加 commit 重试） |
| 状态存储 | 不可变候选包 + 验证证据 artifact | `ci-fix-log` 数据分支（诊断报告 + 修复摘要）+ 知识库 |

**为什么不直接改 Dockerfile：** 文本层面的盲改无法证明改动真的可构建。容器内逐条执行得到的命令序列是「已被证明可行」的，反推回 Dockerfile 后再用 `docker build` 从零复验一次，确保反推没有引入偏差。

**跳过与终止规则：** 预发布版本（`-alpha` / `-beta` / `-rc` 等）与 `fix:` 前缀的 PR 不触发修复；连续 6 次仍未通过 CI 时关闭 Fix PR 并通知人工，不做无限重试。

### 3.5 场景三：openEuler 大版本升级

上游应用版本升级由场景二承接；本节只处理「openEuler 发布新版本后，所有存量应用补齐新 oe 版本子目录」。

**触发与请求。** GitCode `【自动升级需求】upgrade openEuler to <version>` Issue 给出目标版本（正文 `Target openEuler Version` 必须与标题一致）与 `Scope`（领域列表或 `all`）；控制器把它固化成 `UpgradeRequest`，`request_key` 由 Issue 编号与版本哈希得到。

```
【自动升级需求】upgrade openEuler to <版本> Issue
  → monitor_oe_upgrade_issues.yml（plan / deliver）
    → 固定 base_sha → 按 Scope 扫描目标仓 MDU → 任务清单
    → 同一活动同一时刻只派发一个未完成任务
      → oe_upgrade_worker.yml
        → prepare：复用或生成共享 tests/test.sh → 确定性生成候选 → 门禁
        → round-1..4：x86_64 ∥ aarch64 原生构建 + 共享测试；失败由 Fixer 有界修复
        → package-candidate：封存不可变候选
        → deliver：推分支 → 跨仓 PR
        → finalize：回写 Issue 结果 → 唤醒控制器
    → 全部任务结束：写活动汇总，Issue 置为「已挂起」
```

**为什么串行推进一个任务。** 整批 Matrix 并发会同时抢占有限的构建机，同一应用也容易重复开 PR；控制器按固定顺序逐个派发，worker 并发组按 `request_key` 串行，任务之间通过 Issue 评论与 GitHub run 状态对齐。

**失败与跳过。** 单个任务失败写入 Issue 评论并继续后续任务；目标分支已有同名 PR 的任务跳过；规划阶段缺少可用源版本、版本号不可比较等记入 plan summary。

**代码落地。** `scripts/lib/oe_upgrade_contract.py`（请求契约）、`oe_upgrade_planner.py`（规划）、`oe_upgrade_advance.py`（状态投影）、`oe_upgrade_controller.py`（派发与收口）、`oe_upgrade_candidate.py`（确定性候选）、`oe_upgrade_test_prep.py`（测试复用 / 生成）。

---

## 4. Agent 协作架构

### 4.1 角色定义

场景一 / 三共 4 个 Agent 角色：Image Creator、Testcase Creator、Testcase QA 和 Code Fixer。只有测试用例生成保留 QA 对抗复核；CI Failure Analyst 在这些场景中不设为独立角色，其诊断能力作为 Fixer 的内置能力通过知识库驱动。

场景二（3.3 节）之外，CI 修复组件（3.4 节）自带 2 个独立 Agent 角色：CI Failure Analyst（诊断）与 Dockerfile Builder（容器内修复）。两者只产出报告与 Dockerfile，不做任何 git / 平台写操作。

#### Image Creator（镜像生成者）

| 属性 | 说明 |
|------|------|
| 职责 | 根据应用信息生成完整镜像目录，不经过 Image QA 复核 |
| 输入 | package_name, source_repo_url, domain, os_version, os_tag |
| 输出 | Dockerfile + meta.yml + README.md + 可选 doc/ 资产 |
| 后续检查 | 确定性镜像预检、身份契约、hadolint、差分所有权门禁和双架构原生验证 |
| 身份限制 | 只允许动态身份或复用基础镜像已有身份；禁止固定数字 UID/GID |
| 禁止 | 修改已有版本目录、生成镜像语义复核证据或依赖语义反馈修复 |

#### Testcase Creator + Testcase QA

| | Testcase Creator（生成者） | Testcase QA（挑战者） |
|------|------|------|
| 职责 | 独立编写功能测试用例 | 审查测试用例质量，挑战其充分性与有效性 |
| 输入 | package_name, version, dockerfile_path, binary_name, category（不读 Creator 推理链） | Testcase Creator 的全部输出：test.sh、可选 helper 和结构化证据 |
| 输出 | tests/ 目录 + test-ai-result.json | 审查报告（覆盖缺口 + 误报风险 + 遗漏的攻击面） |
| 对抗方式 | 根据 QA 反馈补充测试用例 | 从以下角度挑战：是否覆盖所有攻击面（依赖、端口、权限、启动、边界）？是否有误报风险？是否遗漏关键功能验证？ |
| 禁止 | 读取 Creator 推理链 | 直接修改文件 |

#### Code Fixer（修复者，内置故障分析）

| 属性 | 说明 |
|------|------|
| 职责 | 本地验证失败后介入：分析日志、诊断根因、实施最小化修复 |
| 修复对象 | Dockerfile、meta.yml、README.md、doc/image-info.yml、test.sh 和可选 helper |
| 输入 | 构建日志、测试输出、PR 文件清单（白名单）、fix_branch、故障模式知识库 |
| 输出 | 代码/文档变更 + 修复摘要（含根因分析） |
| 禁止 | 创建新文件、修改白名单外文件、禁用 lint 规则、删除测试 |

### 4.2 对抗模型

Image Creator 完成生成后由确定性门禁检查，不进入语义审查或 QA 修复闭环；确定性门禁仍可要求 Creator 定向修复。对抗关系只存在于 Testcase Creator 与 Testcase QA 之间；Fixer 仅在本地验证失败后介入。

```
Orchestrator（确定性代码）
  → Image Creator 生成（无 Image QA 复核）
  → 镜像预检 + 身份契约 + hadolint
  → 冻结镜像归属快照
  → Testcase Creator 生成
  → 测试用例预检 + 镜像归属检查
  → Testcase QA 挑战
      ├─ 有候选问题：Creator 定向修正，最多再审 1 次
      └─ 无候选问题：直接继续
  → 最终目标契约 + 双架构本地验证
      ├─ 通过：提交 PR，附测试用例复核记录
      └─ 失败：Fixer 修复并重试，最多 3 轮
                    └─ 仍失败：needs-human-review
```

**对抗的本质：**

Testcase QA 与 Testcase Creator 形成**开发-QA 对抗关系**。QA 不直接动手改，而是提出问题促使 Creator 修正。测试用例对抗发生在本地验证之前；QA 的结论用于提高候选质量，但不拥有工作流的一票否决权，本地验证负责最终裁决。镜像内容没有对应的语义复核角色。

### 4.3 收敛策略

系统有两层收敛控制：

**第一层：测试用例 QA 轮次（最多 2 轮）**
```
QA1 → Creator 修正 → QA2
  → QA2 认可？→ 通过，进入本地验证
  → QA2 仍不认可？→ 记录分歧，标注在 PR 中，仍进入本地验证
```
Testcase QA 不认可不代表阻塞——复核的任务是尽可能提高测试质量，但最终裁决权在本地验证。

**第二层：Fixer 修复轮次（最多 3 轮）**
```
第 1 次本地验证失败 → Fixer 分析 + 修复 → 重新验证
第 2 次本地验证失败 → Fixer 分析 + 修复 → 重新验证
第 3 次本地验证失败 → 标记 needs-human-review，附完整诊断记录
```
- Fixer 只接收 `docs/failure-patterns.yml` 中与本轮证据匹配的 verified 通用模式
- 日志不足时标注 "insufficient evidence"，不得猜测

### 4.3.1 证据所有权与生成期门禁

以下契约在数据结构和 legacy 入口上与场景无关，差异只体现在
`TaskSpec.scenario`。场景三的 worker 已按 TaskSpec v2 准备目标仓工作区与完整任务契约（场景二走独立链路，不涉及 TaskSpec）。

1. Creator 直接提交结构化 `evidence`，并在 `command_evidence` 中通过 evidence ID 引用；Creator 提供的 URL 和摘录只构成待固定的输入，不等于已经验证。
2. Harness 仅从受支持的官方代码托管域解析证据；证据 URL 必须与 TaskSpec 同仓且 ref 精确等于固定 revision。Harness 固定原文件、摘录和 SHA-256，并把结果交给 QA。证据不可用不阻断，不单独触发 Creator 修复。
3. QA 始终收到最后一次 Creator 完整结构化输出和对应的 Harness resolved evidence bundle。第二轮仍为 `needs_fix` 时记录分歧并进入本地验证，不把模型意见升级为工作流 veto。
4. 生成期门禁确定性检查 `test.sh` 的存在性、可执行位、Bash 语法和修改范围，并拒绝候选引入目标仓等待、mode 或 Agent 控制文件；真实运行断言统一由 Native Validation 的 `runtime_test` 执行。
5. Native Fixer 修改候选后不插入另一套测试预检查；下一轮完整 Native Validation 会重新执行同一个 `runtime_test`，并由既有 Fixer 循环处理失败。

Agent Markdown 只保存长期稳定的角色规则。单次日志和应用特例放在运行证据中；可复用根因经验证和泛化后写入结构化知识库，禁止把截断 PR 摘要或未经验证的猜测追加到角色提示。

### 4.4 置信度评分

| 因子 | 权重 | 衡量方式 |
|------|------|---------|
| 构建成功（双架构） | 0.35 | x86_64 + ARM64 build exit code = 0 |
| 测试通过率 | 0.30 | 双架构均通过 |
| Linter 合规 | 0.20 | Hadolint 违规数 |
| 元数据一致性 | 0.15 | meta.yml 与实际文件匹配 |

阈值：≥ 0.85 自动合入就绪；0.75~0.85 自动提 PR 需 Review；< 0.75 退回循环

---

## 5. 测试策略

### 5.1 核心决策：每应用共享测试套件

**推荐：每个应用一套共享测试套件，对所有版本执行。**

| 维度 | 共享套件（推荐） | 按版本独立 |
|------|-----------------|-----------|
| 维护成本 | 一处修复，所有版本受益 | N 份拷贝需同步 |
| 公众可信性 | 同一标准，公平比较 | 版本特化易被质疑 |
| 新版本成本 | 零新增测试代码 | 需复制整套 |

### 5.2 测试分层

```
第 3 层：运行时测试 (Harness + test.sh)
  · 容器生命周期与就绪调度  · 版本验证  · 真实协议或核心数据路径

第 2 层：静态分析 (Hadolint + Dockle)
  · Dockerfile 最佳实践  · 镜像标签合规

第 1 层：预构建检查
  · meta.yml schema  · "只能新增" 差分检查
```

场景一的 Native Validation 只保留 `native_build/runtime_test`。Harness 在最长 120 秒内观察默认容器终止事件；镜像有有效 `HEALTHCHECK` 时等待 `healthy`，没有时完整观察 120 秒。随后按容器是否仍在运行选择原容器或同一 image ID 的一次性测试容器，并且一次验证只执行一次共享 `test.sh`。`EXPOSE` 端口不参与就绪调度，最终由脚本中的真实功能断言和 Harness 的 post-inspect 共同裁决。

> openEuler 目前不支持 Trivy CVE 扫描，未纳入测试流水线。

### 5.3 测试用例与结果归档目录设计

**现状问题：** 目标仓库当前将测试用例放在顶层 `tests/<app-name>/` 目录下，与应用的 Dockerfile 目录分离。例如 `tests/rust/` 和 `Bigdata/kylin/` 分属两处，测试用例和被测对象之间没有目录关联。

**设计方案：测试用例与 Dockerfile 同目录，测试结果归档在应用目录内。**

```
openeuler-docker-images/
├── Bigdata/
│   └── kylin/
│       ├── README.md
│       ├── meta.yml
│       ├── doc/
│       │   └── image-info.yml
│       ├── tests/                         # 应用级共享测试用例
│       │   ├── test_helpers.sh            # 可选辅助函数
│       │   └── test.sh                    # 唯一功能测试入口
│       ├── results/                       # 测试结果归档
│       │   └── 5.0.3/                     # 按应用版本归档
│       │       └── 24.03-lts-sp4/         # 按 oe 版本归档
│       │           ├── x86_64.junit.xml   # x86_64 测试结果
│       │           ├── aarch64.junit.xml  # ARM64 测试结果
│       │           └── version_info.json  # 运行环境摘要
│       └── 5.0.3/                         # 应用版本
│           └── 24.03-lts-sp4/             # oe 版本
│               └── Dockerfile
└── tests/                                 # 废弃（不再使用）
```

**关键设计决策：**

| 决策 | 说明 |
|------|------|
| 测试用例放在 `<app>/tests/` | 与 Dockerfile 同目录，应用级共享，所有版本复用 |
| 测试结果放在 `<app>/results/` | 按 `<app-ver>/<oe-ver>/` 双层归档，与 Dockerfile 路径一一对应 |
| `<app>/tests/test.sh` 是唯一入口 | Harness 向共享测试注入当前版本并在已启动容器内执行 |
| 结果按架构独立存储 | `x86_64.junit.xml` 和 `aarch64.junit.xml`，一一对应，一个架构通过不代表另一个 |
| 不修改顶层 `tests/` 目录 | 已有内容保留不动，新应用不再使用顶层目录 |

**共享用例的版本参数化。** 用例在应用级共享，而断言中的版本号随版本变化，因此 `<app>/tests/` 下的断言必须支持 Harness 通过环境变量注入当前版本。版本号一旦硬编码进共享用例，该用例就退化为"每版本独有"，与共享结论矛盾。

**共享用例的修改。** 修改 `<app>/tests/` 会影响该应用的所有历史版本，因此允许修改，但 PR 正文必须声明受影响的版本范围。

**结果归档内容。**

```
<app>/results/<app-ver>/<oe-ver>/
├── x86_64.junit.xml      # 双架构独立
├── aarch64.junit.xml
└── version_info.json     # 运行环境：test_time / Model / architecture / kernel / os /
                          #   cpu_model / cpu_cores / software_name / software_version /
                          #   python_version / numpy_version
```

字段沿用目标仓 `tests/` 下既有的归档格式。schema v1 的聚合 `results.json` 和完整构建日志只进入生产 candidate/artifact，不写入目标仓，避免内部证据扩大目标 patch 或让仓库体积随构建次数增长。

**`results/` 只增不改。** 同一 `(app-ver, oe-ver)` 组合的结果一经写入不得覆盖。重复触发由幂等检查（§2.6）在构建前短路，不进入构建与归档环节。

**与当前仓库的对比：**

| 维度 | 当前仓库（`tests/<app>/`） | 本设计（`<app>/tests/` + `<app>/results/`） |
|------|--------------------------|---------------------------------------------|
| 测试用例位置 | 顶层 `tests/`，与 Dockerfile 分离 | 应用目录内，与 Dockerfile 同属一个目录树 |
| 结果归档 | `tests/<app>/results/<version>/` | `<app>/results/<app-ver>/<oe-ver>/`，与 Dockerfile 路径一一对应 |
| 可发现性 | 需知道顶层有 `tests/` 目录 | 进入应用目录即可看到测试和结果 |
| 版本对应 | 结果只按应用版本归档 | 结果按应用版本 + oe 版本双层归档，精确对应每个 Dockerfile |

### 5.4 公众可信性

可信性来自可复现验证与公开复核，而非 Agent 自证：

1. **镜像验证可复现**：镜像差分、身份契约、lint、双架构原生构建和运行测试由确定性代码执行并记录；不把镜像正确性归因于语义审查
2. **测试用例复核公开**：PR 内嵌 Testcase QA 审查报告及分歧；即使通过本地验证也保留未解决意见
3. **JUnit XML 归档**：测试结果以机器可解析格式作为 Artifact 归档（不可变、带时间戳、绑定构建 SHA）
4. **双架构独立**：x86_64 和 ARM64 各自独立记录，一个架构通过不代表另一个通过

---

## 6. 构建流水线

### 6.1 并行模型

每个镜像包含 x86_64 和 ARM64 两个架构。系统的并行有双层含义：

1. **同一镜像内**：x86_64 和 ARM64 两个 Job 并行执行（一个镜像的必选项）
2. **不同镜像间**：多个镜像的构建并行执行，每个镜像占用 1 组 Runner 对

```
批量 N 个镜像并行构建示意：

镜像 A:                          镜像 B:                          镜像 C:
build-arm64 [ARM64 Runner]       build-arm64 [ARM64 Runner]       build-arm64 [ARM64 Runner]
     │ 并行                            │ 并行                            │ 并行
build-amd64 [x86_64 Runner]      build-amd64 [x86_64 Runner]      build-amd64 [x86_64 Runner]
     │                                │                                │
     ▼                                ▼                                ▼
manifest merge                   manifest merge                   manifest merge

     ↑ 所有镜像同时执行 ↑（并发上限 = 可用 Runner 对数）
```

| 场景 | 并行粒度 | 资源 |
|------|---------|------|
| 新增单个镜像 | 1 镜像 × 2 架构 | x86_64×1 + ARM64×1 |
| N 个应用版本更新 | N 镜像并行 | x86_64×N + ARM64×N |
| M 个应用 oe 升级 | M 镜像并行 | x86_64×M + ARM64×M |
| PR CI 修复组件 | 单 PR 串行（arm64 → amd64 → arm64 复验），跨 PR 由 Runner 队列并行 | ARM64×1 + x86_64×1 |

### 6.2 单个镜像构建流程

```
Phase 1: 双架构原生构建（无 QEMU，各跑在原生硬件上）
  Job build-amd64 [self-hosted, Linux, x64]:
    docker buildx build --platform linux/amd64 --output type=image,push-by-digest=true
  Job build-arm64 [self-hosted, Linux, ARM64]:
    docker buildx build --platform linux/arm64 --output type=image,push-by-digest=true

Phase 2: Manifest 合并
  docker buildx imagetools create -t openeuler/<app>:<tag> \
    <registry>/<app>@<amd64-digest> \
    <registry>/<app>@<arm64-digest>
```

- `fail-fast: false` — 单架构失败不取消另一架构
- `push-by-digest=true` — 按 digest 推送，不直接打 tag
- 每架构独立 `type=registry` cache scope，避免并行碰撞

**Runner 前提。** Runner 预装 Docker 与 buildx，workflow 不引入 `docker/setup-qemu-action` 与 `docker/setup-buildx-action`。前者的跨架构模拟会掩盖架构差异——包在某架构不可用、二进制不兼容这类问题在模拟环境下不会暴露，而它们正是双架构验证要发现的目标，用模拟构建做架构验证等于没做；后者在预装环境下冗余，且会让实际生效的构建栈变得不可观测。

替代手段是 Job 启动时的能力自检：校验 Docker daemon、buildx、Hadolint、磁盘水位与工作区可写，任一不满足即失败退出并给出可操作提示，**不做临时安装**。某架构 Runner 不可用时明确失败；需要发布单架构镜像时通过 `meta.yml` 的 `arch` 字段声明。

**并发隔离。** 同一 Runner 上会有并发 Job，镜像 tag 与容器名必须携带唯一标识，否则并发 Job 之间会互相覆盖镜像、互相删除容器：

- 镜像 tag：`openeuler/<app>:ci-<run-id>-<run-attempt>-<arch>`
- 容器名：`oe-<app>-<run-id>-<arch>`

Job 收尾（含失败路径）只清理本 Job 创建的资源。

### 6.3 多阶段 Dockerfile

```dockerfile
# Stage 1: 依赖层（鲜少变化，利用缓存）
FROM openeuler/openeuler:24.03-lts AS deps
RUN --mount=type=cache,target=/var/cache/yum \
    yum install -y <build-tools> && yum clean all

# Stage 2: 构建
FROM deps AS builder
COPY src/ /build/
WORKDIR /build
RUN make

# Stage 3: 最小运行时
FROM openeuler/openeuler:24.03-lts
COPY --from=builder /build/output /usr/local/bin/app
ENTRYPOINT ["/usr/local/bin/app"]
```

---

## 7. 版本管理

### 7.1 上游版本来源（Issue 驱动）

应用上游版本升级由场景二承接，版本与上游证据由 GitCode `【自动升级需求】` Issue 提供（旧标题已下线），不依赖外部版本监控服务：

```
【自动升级需求】upgrade ... Issue
  → monitor_auto_upgrade_issues.yml（唯一 Issue 入口）
    → upgrade_upstream_versions.yml
    → 对比目标仓已有目录：缺新版本 → AI 生成 Dockerfile + 补测试 + 双架构验证 → PR
    → 目标版本已存在 → 审计现有镜像 → 修复 Agent → 双架构复验 → PR
    → conda-ecopkgs 同名包：校验上游产物后登记 supported-versions.yml → PR
```

手动触发时可用 `config/upgrade-apps.yml` 的 `version` / `source_url` 兜底；两者都缺时跳过并记录原因。

### 7.2 openEuler 版本来源

- 目标版本由 GitCode `【自动升级需求】upgrade openEuler to <version>` Issue 指定
- 版本模式：`{YY}.{MM}-lts`、`{YY}.{MM}-lts-sp{N}`

### 7.3 命名约定

| 层级 | 格式 | 示例 |
|------|------|------|
| 应用版本目录 | 上游版本号 | `1.27.2/` |
| oe 版本目录 | oe 官方版本名 | `24.03-lts/` |
| 复合版本 | 软件栈组合 | `2.1.0-cann7.0.RC1.alpha002/` |
| Tag | `{app-ver}-{oe-ver-short}` | `3.3.1-oe2203lts` |

---

## 8. PR 自动化规范

### 8.1 PR 必含内容

1. **Dockerfile** — 仅新增
2. **更新的 meta.yml** — 追加新 Tag
3. **更新的 README.md** — 追加版本行
4. **doc/** — 新应用时生成
5. **测试文件** — 新应用时生成
6. **构建证明** — 折叠 `<details>`，双架构独立日志 + SHA256 digest
7. **测试结果** — JUnit XML，双架构独立展示
8. **差分摘要** — 机器生成的文件变更列表
9. **Agent 声明** — 生成者 + 置信度

### 8.2 PR 模板

```markdown
## Automated PR: {app-name} {new-version} on {oe-version}

### Changes
- Added `{app-name}/{version}/{oe-version}/Dockerfile`
- Updated `{app-name}/meta.yml` (appended tag)
- Updated `{app-name}/README.md` (appended version row)

### Build Proof
<details>
<summary>x86_64 build (exited 0, digest: sha256:...)</summary>

```
... full build output ...
```
</details>

<details>
<summary>ARM64 build (exited 0, digest: sha256:...)</summary>

```
... full build output ...
```
</details>

### Adversarial Review Records

<details>
<summary>Testcase Creator ↔ Testcase QA</summary>

| 角色 | 结论 |
|------|------|
| Testcase Creator | 生成 N 个测试用例 (confidence: 0.88) |
| Testcase QA | 审查通过，补充 X 个覆盖缺口，修正 Y 个误报 |

QA 审查角度：攻击面覆盖 ✓、误报风险 ✓、关键功能验证 ✓、边界条件 ✓

</details>

### Test Results
<details>
<summary>x86_64 — all assertions passed</summary>

```
... JUnit XML ...
```
</details>

<details>
<summary>ARM64 — all assertions passed</summary>

```
... JUnit XML ...
```
</details>

### Generated By
- Image Creator（无 Image QA 复核，后接确定性镜像门禁）
- Testcase Creator + Testcase QA（最多 2 轮）
```

### 8.3 分支与 PR 提交方式

**PR 与 Issue 始终提交到目标仓**，不因阶段而变。变的只有分支推到哪——取决于运行账号是否具备目标仓写权限。

```
clone   目标仓 master                     # 匿名，无需凭据
push    $PUSH_REPO:auto/<scenario>/<app>/<app-ver>-<oe-ver>
PR      head = <branch>          （$PUSH_REPO == 目标仓）
        head = <owner>:<branch>  （$PUSH_REPO != 目标仓，跨仓形式）
        base = master
Issue   创建在目标仓
```

`PUSH_REPO` 是唯一的配置变量，其余全部派生：

| | 无目标仓写权限 | 有目标仓写权限 |
|---|---|---|
| `PUSH_REPO` | 运行账号名下的目标仓 fork | 目标仓本身 |
| PR 形态 | 跨仓（head 带 owner 前缀） | 同仓 |
| 凭据要求 | 对自己的 fork 可写；在公开仓开 PR/Issue 只需认证，不需目标仓权限 | 对目标仓可写 |
| 附加要求 | 运行前将 fork 的 `master` 同步到目标仓 | 无 |

**fork 基线同步**（仅前一种形态需要）：fork 与目标仓一旦分叉，PR 的差异视图会掺入无关提交。同步失败即终止，不使用过期基线继续执行。

**分支命名**为 `auto/<scenario>/<app>/<app-ver>-<oe-ver>`，不含时间戳或随机串。同一目标重跑复用同一分支名，配合 PR 去重构成幂等——命名中一旦引入时间戳，每次运行都会产生新分支，失败的运行会持续沉积。流程失败或 PR 创建失败时删除已推分支。

**分级执行。** PR 创建是不可逆的外部动作，因此拆成两段：默认执行到"分支已推、PR 未建"为止并输出 PR 正文供检查，建 PR 由独立开关控制。调试构建、测试、门禁等环节时不会在目标仓产生 PR。

---

## 9. 技术选型

### 9.1 技术栈

| 层次 | 技术 | 说明 |
|------|------|------|
| CI/CD 平台 | GitHub Actions | 系统约束 |
| Runner | Self-hosted VMs (x86 + ARM64) | 多组云上虚拟机 |
| 确定性代码 | Python 3 | 主流程编排 + API 封装 |
| Agent 运行时 | opencode（可选 Claude Code） | 不确定性决策 |
| 容器构建 | Docker BuildKit + buildx | 多架构原生构建 |
| 测试框架 | 确定性 Harness + Bash `test.sh` | 生命周期调度与真实功能验证 |
| Lint | Hadolint + Dockle | Dockerfile + 镜像检查 |
| Git 平台 | GitCode（主） | GitLab 风格 API（`/api/v5`），同时提供 GitHub 兼容别名；认证用 `PRIVATE-TOKEN` 头 |
| 版本来源 | GitCode Issue | `【自动升级需求】` 的 `add` / `upgrade` / `upgrade openEuler` 三种后缀提供目标版本与上游证据（旧前缀已下线） |

**GitCode API 客户端约定。** 响应同时携带 GitLab 与 GitHub 两套字段名（如 `iid` / `number`、`web_url` / `html_url`），客户端读取时须做别名兜底，不假设任一风味；列表类接口返回 JSON 数组而非对象；PR 的 Web 地址形如 `/merge_requests/<id>`。

### 9.2 关键约束

| 约束 | 应对 |
|------|------|
| GitCode 文件 API 只读 | Git 操作（clone → modify → commit → push） |
| GitCode API 50 req/min | 合并请求 + 指数退避重试 |
| Issue 未被扫描或处理失败 | `workflow_dispatch` 手动兜底 + Issue 状态幂等 |
| Self-hosted Runner 数量有限 | Matrix 限流 + 队列管理 |
| 外部端点不可达 | 端点地址与鉴权作为部署配置注入；启动时做连通性自检，不可达即明确失败，不静默返回空结果 |
| 只能新增不能修改 | meta.yml 索引 + 本地差分检查 |
| 运行账号未必具备目标仓写权限 | `PUSH_REPO` 单一配置项切换直推 / fork 跨仓两种形态，其余派生（见 8.3 节） |

---

## 10. 风险与缓解

| 风险 | 概率 | 缓解 |
|------|------|------|
| Agent 生成的 Dockerfile 无法构建 | 高 | 确定性构建验证 + Fixer 3 轮（内置故障知识库） |
| Issue 未被及时扫描 | 低 | 新标题 `【自动升级需求】` 由轮询机 `auto-upgrade-issue-poll.timer` 每 5 分钟派发统一监控，GitHub cron 低频兜底；旧标题由各自的旧 monitor 定时派发；均可手动触发 |
| 多个升级任务抢占构建机 | 中 | 场景三控制器一次只推进一个任务；场景二用 `max_parallel` 与 runner 标签限流 |
| Agent 幻觉生成错误元数据 | 中 | CI schema 验证 + Testcase Creator 独立检查 |
| 双架构构建结果不一致 | 低 | 每架构独立测试，全部通过才合并 manifest |
| 知识库过时 | 低 | 历史案例先进入候选区，核对日志、diff 与适用条件后再人工提升为 verified 模式 |

---

## 11. 项目结构

```
openeuler-docker-images-workflow/
├── .github/
│   ├── workflows/
│   │   ├── create_new_images.yml      # 场景一：新镜像请求（编排 4 轮收敛）
│   │   ├── _create_new_image_rounds.yml # 场景一：单轮验证-修复-决策组件
│   │   ├── monitor_ci_failed_prs.yml  # CI 修复组件：ci_failed PR 扫描（仅手动）
│   │   ├── ci_fix_pipeline.yml        # CI 修复组件：修复主编排（手动 / 显式 dispatch）
│   │   ├── _ci_fix_round.yml          # CI 修复组件：单轮修复（arm64 首修 → amd64 续修/回修 → arm64 复验）
│   │   ├── monitor_auto_upgrade_issues.yml # 唯一 Issue 入口（三个场景统一认领）
│   │   ├── upgrade_upstream_versions.yml # 场景二：应用上游版本升级主编排
│   │   ├── _upgrade_app.yml           # 场景二：单应用升级组件
│   │   ├── monitor_oe_upgrade_issues.yml # 场景三：控制器（按 Issue 编号派发任务）
│   │   ├── oe_upgrade_worker.yml      # 场景三：单任务 worker（prepare → 4 轮 → 封存 → PR）
│   │   ├── upgrade_openeuler_versions.yml # 场景三：旧批量入口（已禁用）
│   │   ├── generate_test_scripts.yml  # 场景四：功能测试脚本补齐（手动单应用）
│   │   └── test-e2e.yml              # 开发自测（不创建真实 PR）
│   └── agents/
│       ├── image-creator.md           # Image Creator（生成者）
│       ├── testcase-creator.md        # Testcase Creator（生成者）
│       ├── testcase-qa.md             # Testcase QA（挑战者）
│       ├── upgrade-creator.md         # 场景二：升级 Dockerfile 生成者
│       ├── upgrade-auditor.md         # 场景二：已是最新版本的审计者
│       ├── upgrade-fixer.md           # 场景二：审计后修复 Agent
│       ├── ci-failure-analyst.md      # CI 修复组件：失败诊断师
│       ├── dockerfile-builder.md      # CI 修复组件：容器构建修复工程师
│       ├── testgen-creator.md         # 场景四：KunpengTest 测试脚本生成者
│       └── code-fixer.md              # Fixer（修复者，内置故障分析）
├── config/
│   └── watchlist.json                 # CI 修复组件：仓库列表与扫描参数（仅手动）
├── scripts/
│   ├── harness/
│   │   ├── flow.py                    # 阶段一确定性编排入口
│   │   ├── run.py                     # legacy Agent/test 入口
│   │   ├── parse_issue.py             # Issue 解析
│   │   ├── query_version.py           # 版本对比查询
│   │   ├── validate_meta.py           # meta.yml schema 校验
│   │   ├── gate_diff.py               # "只能新增" 差分检查
│   │   └── compose_pr.py              # PR 内容组装
│   ├── stages/                        # CI 修复组件：ci-log-analysis / build-fix / code-fix
│   ├── watch/                         # CI 修复组件：PR 扫描、入口解析（resolve_pr）
│   ├── lib/
│   │   ├── generation_pipeline.py     # Creator/QA 生成期流水线
│   │   ├── agent_runtime.py           # Agent 进程与结构化契约（场景一/三/四）
│   │   ├── evidence_resolver.py       # Harness 受限取证
│   │   ├── target_contract.py         # 候选目录确定性门禁
│   │   ├── native_validation.py       # 原生构建、就绪调度、功能测试
│   │   ├── native_repair.py           # Native Fixer 收敛循环
│   │   ├── task_spec.py               # 场景无关任务契约
│   │   ├── failure_knowledge.py       # verified 结构化故障知识
│   │   ├── ci_api.py / ci_gitcode_api.py / ci_github_api.py # CI 修复组件：平台 API 与 CI 日志抓取
│   │   ├── ci_data.py                 # CI 修复组件：ci-fix-log / main 分支读写
│   │   ├── build_runner.py            # CI 修复组件：Dockerfile 解析/定位/diff + docker CLI
│   │   ├── ai_runner.py / opencode_run.py / claude_code_run.py # 所有场景的 Agent 调用入口
│   │   ├── stage_common.py            # CI 修复组件：阶段公共工具与 dispatch
│   │   ├── fix_pr_body.py             # CI 修复组件：Fix PR 标题与正文
│   │   └── discover_conventions.py    # CI 修复组件：源仓库规范读取
│   └── utils/
│       └── scoring.py                 # 置信度计算
├── docs/
│   ├── issue-guide.md                 # 三个场景的 Issue 提交指南（标题 + 正文 + 示例）
│   ├── failure-patterns.yml           # verified 结构化故障模式
│   ├── failure-patterns.md            # 知识库维护策略
│   └── ci-failure-patterns.md         # CI 修复组件：失败模式知识库（自动维护）
├── templates/
│   └── pr.md                          # PR 模板
├── tests/                             # 本仓单元测试
├── DESIGN.md
├── README.md
└── REQUIREMENTS.md                     # openeuler-images-requirements.md
```

## 12. 命名规范

### 12.1 多轮（round）命名标准

**语义**：round（轮）= 一次完整的验证尝试，编号从 1 开始；修复（fix）= 轮与轮之间的桥，
`Fix failures (round N)` 表示修复第 N 轮验证发现的失败，产出第 N+1 轮的输入。

| 场景 | 格式 | 示例 |
|---|---|---|
| 验证轮 job 显示名 | `Round N: <verb> <object>` | `Round 1: verify images` |
| 合并型轮 job 显示名（验证+修复同轮） | `Round N: <verb> and <verb>` | `Round 1: validate and fix` |
| 修复 job 显示名 | `Fix failures (round N)` | `Fix failures (round 1)` |
| step 名 | round 一律小写，编号用空格分隔 | `Download round 1 decision evidence`（禁 `round-1`） |
| step 名（无编号） | `<verb> round <noun>` | `Download round evidence`、`Emit next round candidate` |
| job id（验证轮） | `round-{n}`，与显示名 `Round N:` 同构 | `round-1`、`round-3` |
| job id（修复） | `fix-{n}`，编号 = 被修复的轮次 | `fix-1`（修复第 1 轮失败） |
| job id（其他） | kebab-case，显示名动词短语转连字符 | `query`、`compose-pr`、`seed-resume` |

**约束**：
- 同一 workflow 内 job 显示名必须唯一（round 编号 + 动作组合），`Round N:` 前缀只用于验证轮，修复 job 不得复用该前缀。
- **job id 与显示名同构**：验证轮 `round-{n}`、修复 `fix-{n}`（场景 3 的 `verify`/`fix-r1` 与场景 1 的 `round1` 均已统一到该标准），其他 job 用 kebab-case。`needs.round-1` / `needs.fix-1` 引用随 id 同步。CI 修复组件沿用 `round-{n}` 表示修复轮次（`Round N: fix and verify`），另有 `prepare` / `ci-log-analysis` / `code-fix` 三个 kebab-case 阶段 job。
- round 相关输入沿用 `round` / `next_round` / `max_rounds`；artifact 名保留 `phase1-` 前缀（跨 run 恢复契约，见 `resume` 机制）。以下内部标识属于跨 run 契约，**不随 job id 改名**：seed-decisions 目录（`phase1-seed-decisions/roundN`）、`phase1-decideN-` artifact、operation 值（`failure_issue_contract_test`）。

### 12.2 workflow 与 job/step 命名风格

- **workflow 文件名**：功能名 + 场景，`_` 前缀标记内部共享组件（workflow_call）。
- **job 显示名**：完整职责描述，`Verb + object`。
- **step 名**：`Verb + object`，架构一律放尾随括号：`Validate natively (x86_64)`。
- **共享组件**：checkout 步骤统一 `Check out workflow source`；工具链准备统一 `Set up tooling`。
