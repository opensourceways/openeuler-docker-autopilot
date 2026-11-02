# openeuler-docker-autopilot 仓库介绍

> 仓库：`opensourceways/openeuler-docker-autopilot`

---

## 1. 项目定位

**把 openEuler 容器镜像仓库里「重复但夹着不确定性」的维护工作，交给「确定性流水线 + AI Agent」自动完成。**

仓库本身不是镜像仓库，而是一套 **GitHub Actions 驱动的自动化流水线**：输入是 Issue / 事件 / PR 标签，输出是规范化的镜像目录或「最小 diff 的修复 PR」。

系统只建设三个场景：**新增应用镜像（场景一）、PR CI 失败自动修复（场景二）、openEuler 大版本升级（场景三）**。

---

## 2. 背景

`openeuler/openeuler-docker-images` 维护着一批应用容器镜像，其中三类变更高度重复：

1. **社区希望新增一个应用镜像**（场景一）——需要研究上游构建方式，按仓库规范写 Dockerfile、`meta.yml`、README、`doc/image-info.yml`，还要补一套能证明镜像真的可用的功能测试；
2. **已有的版本升级 PR 卡在 CI**（场景二）——由于dockerfile在编写时鲁棒性不足，导致自动升级系统在仅替换版本串时会出现构建失败，因此开发一个PR Fix流水线接入AI Agent，当PR被打上`ci_failed`标签时，自动抓取Jenkins失败日志，调用AI Agent诊断根因，容器内逐条执行Dockerfile并修复，最后反推Dockerfile并提交修复PR；
3. **openEuler 发布新版本**（场景三）——所有存量应用都要补齐新 openEuler 版本的镜像，批量且机械；

场景一、三共享同一批固定规范，但也都夹着不确定的部分：上游依赖怎么装、服务怎么起、构建失败怎么修。前者适合代码，后者适合 Agent。场景二处理的就是失败本身——根因往往是已知的构建失败模式（缺编译依赖、链接参数变更、Makefile 路径假设失效），因此把「诊断 + 修复」整体交给 Agent，只把触发、阶段推进、确定性复验与交付留给代码。

---

## 3. 三个场景总览

| 场景 | 触发源 | 执行内容 | 输出 |
|---|---|---|---|
| **① 新增应用镜像** | GitCode Issue（标题含 `【new-image】`） | 解析需求 → 生成镜像文件与测试 → 门禁 → 双架构构建测试 → 有界修复 | 单个应用的完整镜像目录 PR |
| **② PR CI 失败自动修复** | 目标仓 PR 被打上 `ci_failed` 标签（Monitor 轮询） | 抓 Jenkins 失败日志 → AI 诊断根因 → 容器内逐条执行 Dockerfile 并修复 → 反推 Dockerfile → 双架构复验 | 落回源码的最小 diff Fix PR（`fix:` 前缀） |
| **③ openEuler 版本升级** | `oe-new-version` 事件或手动 | 枚举全部应用 → Matrix 并行补齐缺失的 oe 版本 | 批量 PR + 失败应用报告 |

场景 ①/③ 共享同一套「生成 → 门禁 → 双架构验证 → 交付」能力，差异只在触发输入与调度；场景 ② 走独立的「监控 → 诊断 → 容器内修复 → 复验 → 落回」链路，与其它场景不共享 TaskSpec / 候选包 / 门禁体系。

---

## 4. 目标仓库与写入边界

| 项 | 内容 |
|---|---|
| 主要操作对象 | `openeuler/openeuler-docker-images`（GitCode） |
| 场景一/三交付方式 | **测试模式**：分支推送到配置的 fork 仓库，再向目标仓提跨仓 PR |
| 生产直推模式 | `direct_branch_pr` 已在 `DeliveryConfig` 中定义，但未接入任何 workflow，需显式开启 |
| 场景二修复落点 | 源仓库分支 `fix/<pr_number>`，并创建 `fix:` 前缀的 Fix PR；可用 `GITCODE_FORK_REPO` 改为推 fork |
| 监控范围 | `config/watchlist.json`，当前仅 `openeuler/openeuler-docker-images`，标签 `ci_failed`，每天轮询 |
| 写权限边界 | Agent 在整个生成/修复阶段无任何仓库写能力；git 与平台写操作集中在验证通过之后的确定性交付代码里 |

**只能新增，不能修改**：存量镜像目录视为只读，由四层机制保证——`git diff` 差分检查、`meta.yml`/`README.md` 仅允许末尾追加、`<app-ver, oe-ver>` 幂等检查、提 PR 前按标题去重。

---

## 5. AI Agent 的作用、贡献与必要性

### 5.1 Agent 在哪些环节介入

| 场景 | 环节 | Agent | 输入 | 产出 |
|---|---|---|---|---|
| ① 新增镜像 | 生成 | `image-creator.md` | Issue 解析出的 TaskSpec、上游源码、目标仓规范 | Dockerfile、`meta.yml`、README、`doc/image-info.yml` |
| ① 新增镜像 | 测试 | `testcase-creator.md` ⇄ `testcase-qa.md` | 已生成的镜像与规范 | 共享测试入口 `tests/test.sh`（Creator 生成、QA 对抗复核，最多 2 轮） |
| ①③ | 有界修复 | `code-fixer.md` | 双架构失败证据（构建/测试报告） | 白名单范围内的最小修复 |
| ② CI 修复 | 诊断 | `ci-failure-analyst.md` | 失败架构的 Jenkins 日志尾部 + PR diff + 知识库 | 结构化诊断报告（失败类型、根因、修复建议） |
| ② CI 修复 | 修复 | `dockerfile-builder.md` | 诊断报告 + 源码 | 容器内逐条执行并跑通的命令序列 → 反推出的 Dockerfile |

其余环节（触发、阶段推进、门禁、双架构验证、交付）全部由确定性代码承担，不经过 Agent。

### 5.2 Agent 带来的贡献

1. **承接不可枚举的调研工作**：上游项目的构建方式（autotools / cmake / conan / 自研脚本）、依赖来源、服务启动参数各不相同，无法用固定模板覆盖；Agent 直接读上游 README、Makefile、CI 配置后给出可构建方案。
2. **一次产出整套规范文件**：MDU 内的 Dockerfile、`meta.yml`、README、`doc/image-info.yml`、测试脚本一次性生成，避免"文件齐了但规范不对"的返工。
3. **测试语义把关**：要求断言精确版本与真实功能路径，经 QA Agent 对抗式质疑，降低"进程活着就算通过"这类弱测试。
4. **失败根因定位**：从非结构化日志 + diff 中判断是缺编译依赖、链接参数变更还是路径假设失效，并给出修复方向；证据矛盾时标记"证据不足"而不是猜。
5. **可验证的修复而非文本盲改**：场景二在容器里逐条执行 Dockerfile 指令、失败即改，跑通后反推 Dockerfile，再由 `docker build` 从零复验——AI 的修改被真实构建验证过。
6. **知识沉淀**：修复通过 CI 后，失败模式自动追加到 `docs/ci-failure-patterns.md`，下次诊断作为历史模式注入，同类问题收敛更快。

对应到人工成本：单条 CI 失败 PR 的人工处理（翻日志、定位、改 Dockerfile、重提）平均 15–30 分钟，且需要熟悉该应用构建细节的维护者；Agent 把这部分转成一次自动 run。

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
- 无法收敛时停止并保留证据（场景一 4 轮后 `needs-human-review`，场景二 3 轮后链路终止），不靠降低标准换取绿色。

### 5.5 使用的 Agent 软件

| 项 | 内容 |
|---|---|
| Agent 运行时 | **opencode**（默认），版本、下载地址与 SHA256 锁定在 `.github/toolchain.lock.yml`，Runner 无需安装 Node.js |
| 可选后端 | **Claude Code**：`AI_RUNNER=claude-code`（`ANTHROPIC_API_KEY`）或 `claude-code-account`（`CLAUDE_CREDENTIALS_JSON`），需在 Runner 上安装 `@anthropic-ai/claude-code` |
| 统一入口 | [`scripts/lib/ai_runner.py`](../scripts/lib/ai_runner.py)：按 `AI_RUNNER` 选择后端，并在调用前校验凭证；opencode 走 [`opencode_run.py`](../scripts/lib/opencode_run.py)，Claude Code 走 [`claude_code_run.py`](../scripts/lib/claude_code_run.py) |
| Agent 定义 | `.github/agents/` 下 6 份提示词：`image-creator`、`testcase-creator`、`testcase-qa`、`code-fixer`、`ci-failure-analyst`、`dockerfile-builder` |
| 场景一/三模型 | 默认 `deepseek/deepseek-flash`（见 [`scripts/lib/agent_runtime.py`](../scripts/lib/agent_runtime.py)），可用 `OPENCODE_MODEL` / `OPENCODE_TIMEOUT` 覆盖 |
| 场景二模型 | 默认 `bailian/deepseek-v4.1-flash-1017`（阿里云百炼 DashScope，OpenAI 兼容模式）；`AI_PROVIDER_ID` + `OPENAI_BASE_URL` 注入自定义 provider，Key 以 `{env:OPENAI_API_KEY}` 引用、不落明文 |
| 调用超时 | 场景二 `AI_TIMEOUT_MS` 默认 10,800,000 ms（3 小时） |

> 换服务商只需让 `AI_MODEL`（`<provider_id>/<model>`）、`AI_PROVIDER_ID`、`OPENAI_BASE_URL` 三者保持一致；使用 opencode 内置 provider（如 `deepseek/…`、`anthropic/…`）时前缀改成对应内置 id 即可。

---


