# openeuler-docker-autopilot 仓库介绍

> 仓库：`opensourceways/openeuler-docker-autopilot`

---

## 1. 项目定位

**把 openEuler 容器镜像仓库里「重复但夹着不确定性」的维护工作，交给「确定性流水线 + AI Agent」自动完成。**

仓库本身不是镜像仓库，而是一套 **GitHub Actions 驱动的自动化流水线**：输入是 Issue / 事件 / PR 标签，输出是规范化的镜像目录或「最小 diff 的修复 PR」。

系统只建设四个场景：**新增应用镜像（场景一）、应用上游版本自动升级（场景二）、openEuler 大版本升级（场景三）、存量镜像功能测试脚本补齐（场景四）**。另有可复用的 **PR CI 失败修复组件**（手动 / 显式调用，不再自动轮询）。

---

## 2. 背景

`openeuler/openeuler-docker-images` 维护着一批应用容器镜像，其中四类变更高度重复：

1. **社区希望新增一个应用镜像**（场景一）——需要研究上游构建方式，按仓库规范写 Dockerfile、`meta.yml`、README、`doc/image-info.yml`，还要补一套能证明镜像真的可用的功能测试；
2. **应用上游发布了新版本**（场景二）——需要为存量应用补一个新版本镜像目录：复制上一版、替换版本串、补 `meta.yml` 与功能测试，机械但量大；版本号与上游证据由 GitCode `【new-version】` Issue 提供；
3. **openEuler 发布新版本**（场景三）——所有存量应用都要补齐新 openEuler 版本的镜像，批量且机械；
4. **存量镜像缺功能测试脚本**（场景四）——目标仓已把功能测试与 CI 构建绑定（Dockerfile 变更即构建，成功后按 `{app}/tests/test.sh` 执行功能测试），但多数应用没有测试脚本，需要按 [KunpengTest 规范](https://github.com/opensourceways/upstream-dashboard/blob/KunpengTest/README.md)批量补齐；

场景一、三共享同一批固定规范，但也都夹着不确定的部分：上游依赖怎么装、服务怎么起、构建失败怎么修。前者适合代码，后者适合 Agent。场景二处理版本升级——目标版本与上游证据由触发 Issue 提供，扫描阶段只负责定位目标仓目录，Dockerfile 由 AI 依证据与固定上游源码重新生成，目录复制与元数据登记由确定性代码承担。场景四与场景一共享「Agent 生成 + 静态校验」的质量机制，但脚本规范遵循目标仓 CI 的 KunpengTest 约定（禁 `set -e`、脚本内自拉服务、注入五个环境变量），走独立的「手动指定软件 → 定位镜像 → 生成 → 校验 → 提 PR」链路。PR CI 失败修复（原场景二能力）抽成手动组件 `_ci_repair.yml`，升级 PR 的 CI 失败时由人工决定是否触发。

---

## 3. 四个场景总览

| 场景 | 触发源 | 执行内容 | 输出 |
|---|---|---|---|
| **① 新增应用镜像** | GitCode Issue（标题含 `【new-image】`） | 解析需求 → 生成镜像文件与测试 → 门禁 → 双架构构建测试 → 有界修复 | 单个应用的完整镜像目录 PR |
| **② 应用自动升级** | GitCode Issue（`【new-version】`，正文带上游证据 JSON）/ 手动 | 解析 Issue 证据 → 对比已有目录 → 缺新版本：补功能测试 + AI 依证据包生成 Dockerfile + 确定性目录/元数据落盘 + 双架构原生验证；已是最新：AI 审计后修复 Dockerfile 与 doc/image-info.yml | 一应用一 PR |
| **③ openEuler 版本升级** | `oe-new-version` 事件或手动 | 枚举全部应用 → Matrix 并行补齐缺失的 oe 版本 | 批量 PR + 失败应用报告 |
| **④ 功能测试脚本补齐** | 手动触发（指定软件名） | 定位该软件最新镜像目录 → AI 按 KunpengTest 规范生成 `tests/test.sh` → 静态校验（失败重试 2 轮） | 一软件一 PR（含 Dockerfile 空行触发目标仓构建 + 功能测试） |

场景 ①/③ 共享同一套「生成 → 门禁 → 双架构验证 → 交付」能力，差异只在触发输入与调度；场景 ② 由 GitCode Issue 提供版本与上游证据，扫描阶段只对比目标仓已有目录，Dockerfile 由 AI 结合证据包重新生成（不做版本串机械替换），补测试也调用 AI，目录复制与元数据登记由确定性代码承担；已是最新版本的应用不跳过，审计后由修复 Agent 更新 Dockerfile 与 `doc/image-info.yml` 并开 PR。场景 ④ 走独立的「手动指定软件 → 定位镜像 → 生成 → 静态校验 → 提 PR」链路，一次运行只处理一个应用。

---

## 4. 目标仓库与写入边界

| 项 | 内容 |
|---|---|
| 主要操作对象 | `openeuler/openeuler-docker-images`（GitCode） |
| 场景一/二/三/四交付方式 | **测试模式**：分支推送到配置的 fork 仓库，再向目标仓提跨仓 PR |
| 生产直推模式 | `direct_branch_pr` 已在 `DeliveryConfig` 中定义，但未接入任何 workflow，需显式开启 |
| 场景二升级落点 | 分支 `auto/version-update/<app>/<version>-<oe_tag>`，推送到 `GITCODE_FORK_REPO`（留空则直推目标仓）后提跨仓 PR |
| CI 修复组件落点 | 源仓库分支 `fix/<pr_number>` 与 `fix:` 前缀的 Fix PR；可用 `GITCODE_FORK_REPO` 改为推 fork |
| 监控范围 | 仅 CI 修复组件的 `config/watchlist.json`（`openeuler/openeuler-docker-images`，标签 `ci_failed`），**手动扫描**；场景二由 GitCode `【new-version】` Issue 驱动，不再轮询 upstream-dashboard |
| 写权限边界 | Agent 在生成/升级/修复阶段无任何仓库写能力；git 与平台写操作集中在验证通过之后的确定性交付代码里 |

**生成类场景只增不改**：场景一 / 三 / 四的存量镜像目录视为只读，由四层机制保证——`git diff` 差分检查、`meta.yml`/`README.md` 仅允许末尾追加、`<app-ver, oe-ver>` 幂等检查、提 PR 前按标题去重。场景二只新增版本目录并追加 `meta.yml`，不修改存量版本目录。

---

## 5. AI Agent 的作用、贡献与必要性

### 5.1 Agent 在哪些环节介入

| 场景 | 环节 | Agent | 输入 | 产出 |
|---|---|---|---|---|
| ① 新增镜像 | 生成 | `image-creator.md` | Issue 解析出的 TaskSpec、上游源码、目标仓规范 | Dockerfile、`meta.yml`、README、`doc/image-info.yml` |
| ① 新增镜像 | 测试 | `testcase-creator.md` ⇄ `testcase-qa.md` | 已生成的镜像与规范 | 共享测试入口 `tests/test.sh`（Creator 生成、QA 对抗复核，最多 2 轮） |
| ①③ | 有界修复 | `code-fixer.md` | 双架构失败证据（构建/测试报告） | 白名单范围内的最小修复 |
| ② 应用升级 | 生成 Dockerfile | `upgrade-creator.md` | 旧版本 Dockerfile、目标版本、Issue 上游证据（`support_level`、`check_id`、`test_depth`、`ci_workflows`、`install_candidates`） | 新版本完整 Dockerfile（不做版本串机械替换；缺目标版本号/`FROM` 即重写或失败） |
| ② 已是最新 | 审计 + 修复 | `upgrade-auditor.md` → `upgrade-fixer.md` | 现有 Dockerfile、meta.yml、测试脚本、image-info、Issue 上游证据与 tag/commit | 审计报告 + 修复 PR（Dockerfile 与 doc/image-info.yml 按测试脚本同步） |
| ② 应用升级 | 补测试 | `testgen-creator.md` | 应用镜像目录、KunpengTest 契约、上游证据 | `tests/test.sh`（静态校验失败最多回修 2 轮；生成失败不阻断升级） |
| CI 修复组件 | 诊断 | `ci-failure-analyst.md` | 失败架构的 Jenkins 日志尾部 + PR diff + 知识库 | 结构化诊断报告（失败类型、根因、修复建议） |
| CI 修复组件 | 修复 | `dockerfile-builder.md` | 诊断报告 + 源码 | 容器内逐条执行并跑通的命令序列 → 反推出的 Dockerfile |

其余环节（触发、阶段推进、门禁、双架构验证、交付）全部由确定性代码承担，不经过 Agent。

升级 / 修复 / 审计 Agent 还会在 JSON 中返回 `app_note`：流水线把它合并到本仓 [`config/app-notes/<app>.md`](../config/app-notes) 的按版本「自动沉淀」章节，保留人工正文与构建预算，并推 `auto/app-note/<app>` 分支开独立 notes PR，不阻塞镜像升级 PR。

### 5.2 Agent 带来的贡献

1. **承接不可枚举的调研工作**：上游项目的构建方式（autotools / cmake / conan / 自研脚本）、依赖来源、服务启动参数各不相同，无法用固定模板覆盖；Agent 直接读上游 README、Makefile、CI 配置后给出可构建方案。
2. **一次产出整套规范文件**：MDU 内的 Dockerfile、`meta.yml`、README、`doc/image-info.yml`、测试脚本一次性生成，避免"文件齐了但规范不对"的返工。
3. **测试语义把关**：要求断言精确版本与真实功能路径，经 QA Agent 对抗式质疑，降低"进程活着就算通过"这类弱测试。
4. **失败根因定位**：从非结构化日志 + diff 中判断是缺编译依赖、链接参数变更还是路径假设失效，并给出修复方向；证据矛盾时标记"证据不足"而不是猜。
5. **可验证的修复而非文本盲改**：CI 修复组件在容器里逐条执行 Dockerfile 指令、失败即改，跑通后反推 Dockerfile，再由 `docker build` 从零复验——AI 的修改被真实构建验证过。
6. **知识沉淀**：修复通过 CI 后，失败模式追加到 `docs/ci-failure-patterns.md`，下次诊断作为历史模式注入，同类问题收敛更快。

对应到人工成本：单条 CI 失败 PR 的人工处理（翻日志、定位、改 Dockerfile、重提）平均 15–30 分钟，且需要熟悉该应用构建细节的维护者；Agent 把这部分转成一次显式触发的 run。

### 5.3 为什么必须使用 AI

| 环节 | 为什么规则/模板不够 |
|---|---|
| 上游构建方案 | 输入空间不可枚举：不同语言、不同构建系统、不同依赖组合，写死规则等于为每个应用单独开发 |
| 日志诊断 | Jenkins 日志是非结构化文本，根因可能跨多行、与 diff 语义相关，规则匹配容易误判；需要"读日志 + 看改动 + 比对知识库"的综合推理 |
| 测试正确性 | 判断"测试是否真的验证了功能"是语义判断，不是模式匹配；弱断言无法用 lint 覆盖 |
| 构建修复 | 需要在容器反馈下多轮试错（装依赖 → 编译 → 报错 → 换方案），这是搜索式过程，不是固定脚本能穷举的 |

同时，AI 的介入被刻意限制在**不可判定**的部分：

- 可判定的一律交给代码——目录边界、文件规范、`meta.yml` 结构、hadolint、双架构构建与测试、PR 去重、交付；
- Agent 的产出必须通过确定性门禁与原生双架构验证才算成立；
- 因此"用 AI"不是把判断权交出去，而是把**生成与诊断**交给 AI、把**验收**留给代码。

### 5.4 使用边界（AI 不会失控的原因）

- Agent 不持有任何仓库写能力：不执行 `git commit` / `git push`，不调用平台写 API；
- 只能修改任务契约白名单内的文件，不得改 CI 配置、不得删除或弱化测试、不得禁用 lint；
- 测试语义分歧不 veto，最终由本地构建/测试验证裁决；
- 无法收敛时停止并保留证据（场景一 4 轮后 `needs-human-review`，CI 修复组件 3 轮后链路终止），不靠降低标准换取绿色。

### 5.5 使用的 Agent 软件

| 项 | 内容 |
|---|---|
| Agent 运行时 | **opencode**（默认），版本、下载地址与 SHA256 锁定在 `.github/toolchain.lock.yml`，Runner 无需安装 Node.js |
| 可选后端 | **Claude Code**：`AI_RUNNER=claude-code`（`ANTHROPIC_API_KEY`）或 `claude-code-account`（`CLAUDE_CREDENTIALS_JSON`），需在 Runner 上安装 `@anthropic-ai/claude-code` |
| 统一入口 | [`scripts/lib/ai_runner.py`](../scripts/lib/ai_runner.py)：按 `AI_RUNNER` 选择后端，并在调用前校验凭证；opencode 走 [`opencode_run.py`](../scripts/lib/opencode_run.py)，Claude Code 走 [`claude_code_run.py`](../scripts/lib/claude_code_run.py) |
| Agent 定义 | `.github/agents/` 下 7 份提示词：`image-creator`、`testcase-creator`、`testcase-qa`、`testgen-creator`、`code-fixer`、`ci-failure-analyst`、`dockerfile-builder` |
| 服务商配置 | 所有场景统一由 [`scripts/lib/ai_provider.py`](../scripts/lib/ai_provider.py) 解析 `AI_MODEL` / `AI_PROVIDER_ID` / `OPENAI_BASE_URL` / `AI_API_KEY` / `AI_TIMEOUT_MS` |
| 默认模型 | `gateway/deepseek-v4-pro`（火山引擎 API 网关，OpenAI 兼容模式）；1M 上下文、384k 输出、thinking + reasoning_content；Key 以 `{env:OPENAI_API_KEY}` 引用、不落明文 |
| 兼容别名 | `OPENCODE_MODEL`（模型）、`DEEPSEEK_API_KEY` / `OPENAI_API_KEY`（Key） |
| 调用超时 | `AI_TIMEOUT_MS` 默认 10,800,000 ms（3 小时） |

> 换服务商只需让 `AI_MODEL`（`<provider_id>/<model>`）、`AI_PROVIDER_ID`、`OPENAI_BASE_URL` 三者保持一致；使用 opencode 内置 provider（如 `deepseek/…`、`anthropic/…`）时前缀改成对应内置 id 即可。

---


