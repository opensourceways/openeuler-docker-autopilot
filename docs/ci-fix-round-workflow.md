# `_ci_fix_round.yml` 工作流介绍报告

> 文件位置：`.github/workflows/_ci_fix_round.yml`
> 类型：可复用工作流（`workflow_call`），不直接触发，只能被其他工作流调用

---

## 1. 一句话定位

`_ci_fix_round.yml` 是**场景二「PR CI 失败自动修复」中的单轮修复单元**：一轮 = 「arm64 首修（仅第 1 轮）→ amd64 续修/回修 → arm64 确定性复验」，复验结果以 `verify_passed` 输出给调用方，由调用方决定是否再开下一轮。

---

## 2. 所属场景

所属场景为**场景二：PR CI 失败自动修复**。该场景解决的问题是：

目标仓库（如 `openeuler/openeuler-docker-images`）的自动升级类 PR 在 CI 中构建失败，人工逐个看日志、改 Dockerfile 成本高。链路用 AI 读取失败日志、定位根因、修改 Dockerfile，并在真实架构上构建验证后，向源仓库提交 Fix PR。

场景二整体链路（`ci_fix_pipeline.yml`）：

```
prepare → ci-log-analysis → round-1 → [round-2] → [round-3] → code-fix
```

本工作流负责其中 `round-N` 这一环，被调用 1~3 次。

---

## 3. 用途

| 用途 | 说明 |
|---|---|
| 双架构修复 | 先在 arm64 上做首修（仅第 1 轮），再在 amd64 上续修，保证产物在两个架构都能构建 |
| 确定性复验 | 复验阶段**不使用 AI**，只做一次真实的 `docker build`，作为本轮唯一的权威判据 |
| 轮次收敛 | 复验失败时不把 job 判失败，而是输出 `verify_passed=false`，由外层决定是否消耗下一轮预算 |
| 可观测 | 每一轮在 Actions 里都是独立的 `Round N: fix / verify` job，修了几次、卡在哪一步一眼可见 |

---

## 4. 目标仓库

本工作流本身运行在 **`opensourceways/openeuler-docker-autopilot`**（即本仓库）的 Actions 上，但它操作的「目标仓库」是另一个仓库，由输入 `source_repo` 指定：

| 项 | 值 |
|---|---|
| 默认/当前唯一监控的源仓库 | `openeuler/openeuler-docker-images`（GitCode 平台） |
| 监控名单配置 | `config/watchlist.json` 的 `watched_repos` |
| 触发标签 | `ci_failed` |
| 轮询周期 | `poll_interval_minutes: 1440`（每天一次，与 cron `0 0 * * *` 同步） |
| 支持的平台 | `gitcode` / `github`，由 `source_platform` 决定检出与推送方式 |
| 修复产物落点 | 源仓库的同名分支 `fix/<pr_number>`，并创建 Fix PR |

也就是说：**修复代码跑在本仓库的 runner 上，改动最终提交到源仓库（或 GitCode fork，见 `GITCODE_FORK_REPO`）。**

---

## 5. 调用方式

```yaml
round-1:
  uses: ./.github/workflows/_ci_fix_round.yml
  with:
    round: "1"
    verify_count: "0"
    include_arm64_fix: true
    ...
```

- 第 1 轮：`include_arm64_fix: true`，`verify_count: "0"`
- 第 2 轮：`include_arm64_fix: false`，`verify_count: "1"`，条件 `round-1.verify_passed == 'false'`
- 第 3 轮：`include_arm64_fix: false`，`verify_count: "2"`，条件 `round-2.verify_passed == 'false'`

整条流水线的入口有两个（在 `ci_fix_pipeline.yml` 上）：

- `repository_dispatch`（`run-ci-fix`）：Monitor 轮询发现 `ci_failed` PR 后自动触发
- `workflow_dispatch`：人工指定 `source_repo` / `pr_number` 手动跑一次

---

## 6. 输入、密钥与输出

### 输入

| 参数 | 类型 | 含义 |
|---|---|---|
| `round` | string | 轮次号（1/2/3），用于 job 命名与日志 |
| `verify_count` | string | 已消耗的修复次数，直接传给 `build-fix.py` 作为 `VERIFY_COUNT` |
| `include_arm64_fix` | boolean | 本轮是否执行 arm64 首修（仅第 1 轮为 true） |
| `source_repo` | string | 目标仓库 `owner/repo` |
| `source_platform` | string | `gitcode` / `github` |
| `pr_number` / `pr_title` / `head_sha` | string | 源 PR 的定位信息 |
| `fix_branch` | string | 修复分支名（`fix/<pr_number>`） |
| `pr_base_branch` | string | 源 PR 的 base 分支 |
| `arm64_runner_labels` | string | arm64 job 的 runner 标签（JSON 数组），**必须是 arm64** |
| `amd64_runner_labels` | string | amd64 修复 job 的 runner 标签（JSON 数组，需 Docker 与 ≥4 CPU） |

### 密钥

`GITCODE_TOKEN`、`DISPATCH_TOKEN`、`AI_API_KEY`、`DEEPSEEK_API_KEY`、`CLAUDE_CREDENTIALS_JSON`（均为可选声明，实际按后端取用）。

### 输出

| 输出 | 含义 |
|---|---|
| `verify_passed` | 最终 Dockerfile 能否在 arm64 上从零构建成功（`true` / `false`），来自 `verify-arm` job |

---

## 7. 三个 Job 详解

### 7.1 `arm64-fix`（仅第 1 轮）

| 项 | 内容 |
|---|---|
| 条件 | `inputs.include_arm64_fix` |
| Runner | `arm64_runner_labels`（默认 `["self-hosted","Linux","ARM64","oe-fix-arm64"]`） |
| 超时 | 240 分钟 |
| 关键 env | `ARCH=arm64`、`MODE=build`、`VERIFY_COUNT` |
| 主要步骤 | 检出本仓库 → 检出源仓库（GitHub / GitCode 两种）→ 检出 PR head → `phase1-setup`（`arch: aarch64`，含 preflight）→ 装依赖 → 加载 conventions → 执行 `scripts/stages/build-fix.py` |

### 7.2 `amd64-fix`（每轮都跑）

| 项 | 内容 |
|---|---|
| 条件 | `always()` 且 `arm64-fix` 为 `success` 或 `skipped`（即首修失败则短路） |
| Runner | `amd64_runner_labels`（默认 `["self-hosted","Linux","X64","oe-fix-amd64"]`） |
| 超时 | 240 分钟 |
| 关键 env | `ARCH=amd64`、`MODE=build` |
| 语义 | 第 1 轮在 arm64 冻结版之上继续修；第 2/3 轮在「上一轮交付但 arm64 复验失败」的版本上回修，修复必须架构中立或加架构守卫 |

### 7.3 `verify-arm`（本轮的收口）

| 项 | 内容 |
|---|---|
| 条件 | `always()` 且 `amd64-fix` 为 `success` |
| Runner | `arm64_runner_labels` |
| 超时 | 300 分钟 |
| 关键 env | `ARCH=arm64`、`MODE=verify` |
| 输出 | `verify_passed`（来自步骤 `verify` 的 output） |
| 特性 | 自托管 runner 上启用**持久 BuildKit 层缓存**：`CI_FIX_BUILD_CACHE_DIR`（默认 `{runner.workspace}/ci-fix-buildkit-cache`），跨轮次/跨天复用前缀层，避免重复编译 conan 依赖 |

---

## 8. 轮次与预算模型

```
Round 1  arm64 首修 → amd64 续修 → arm64 复验 ──通过──> code-fix
                                      └─失败─> Round 2
Round 2  amd64 回修 → arm64 复验 ──通过──> code-fix
                          └─失败─> Round 3
Round 3  amd64 回修 → arm64 复验 ──通过──> code-fix
                          └─失败─> 链路终止（不生成 Fix PR）
```

- 预算常量：`MAX_VERIFY_ROUNDS = 2`，即首修之外最多再回修 2 次，共 3 轮
- **复验失败不判 job 失败**：结果写进 `verify_passed`，让「修了几次」在 job 列表里可读，也避免把「可继续」误判为「流程挂了」
- 只有 `verify_passed=true` 才进入 `code-fix` 落回源码并创建 Fix PR

---

## 9. 运行环境与依赖

| 类别 | 内容 |
|---|---|
| AI 后端 | `AI_RUNNER`（默认 `opencode`；可选 `claude-code` / `claude-code-account`） |
| 模型 | `AI_MODEL` 默认 `gateway/deepseek-v4-pro`（火山引擎 API 网关，OpenAI 兼容模式） |
| 凭证 | `AI_API_KEY` 取 `secrets.AI_API_KEY`，回退 `secrets.DEEPSEEK_API_KEY`；同时写入 `OPENAI_API_KEY` / `DEEPSEEK_API_KEY` 兼容别名 |
| 超时 | `AI_TIMEOUT_MS` 默认 10,800,000 ms（3 小时） |
| 工具链 | `.github/actions/phase1-setup`（按 `arch` 预置 opencode/venv，含 `preflight` 校验） |
| Python 依赖 | `requirements.txt`（运行时仅 `requests`） |

> 注意：可复用工作流**不继承**调用方的 `env`，脚本读取的每个变量都必须在本文件 `env:` 中重新声明，否则会静默失效（历史上「连续失败回帖」开关就这样丢过一次）。

---

## 10. 产物与清理

- **产物**：分析报告、修复摘要、派生的 Dockerfile、构建日志等由脚本写入 `ci-fix-log` 分支（`ci-fix-log/<pr>/...`）
- **容器清理**：三个 job 都有 `if: always()` 的清理步骤，按本次 run 的唯一标签 `oe.ci-fix=<run_id>-<run_attempt>` 删除容器与镜像，保证并发/重复运行互不影响
- **缓存清理**：BuildKit 缓存目录按需手动清理（`docker buildx prune -f --filter until=168h` 或直接删除目录）

---

## 11. 设计要点与边界

1. **架构不可替换**：`arm64_runner_labels` 只能换成「另一台 arm64 机器」，不能换成 x64——arm64 复验本身就是双架构保证。
2. **复验是唯一权威判据**：AI 的自我判断不作数，只有真实 `docker build` 成功才算本轮通过。
3. **失败语义分级**：修不成功（`verify_passed=false`）≠ 流程失败；只有环境/脚本异常才让 job 失败。
4. **轻量 job 与重 job 分离**：`prepare` / `ci-log-analysis` / `code-fix` 默认跑 GitHub 托管 runner，构建类 job 跑自托管 arm64/x64，避免排队阻塞。
5. **串行保证**：同一 PR 的修复由 `ci_fix_pipeline.yml` 的 `concurrency` 组串行化，不并发。

---

## 12. 常见排查点

| 现象 | 优先检查 |
|---|---|
| job 一直排队不动 | `arm64_runner_labels` / `amd64_runner_labels` 是否与自托管 runner 的实际标签一致（`oe-fix-arm64` / `oe-fix-amd64`） |
| `phase1-setup` 报命令找不到（exit 127） | `arch` 入参是否为 `aarch64` / `x86_64`，工具链路径 `opencode_path` 是否为空 |
| AI 调用 403 | `AI_MODEL`、`AI_PROVIDER_ID`、`OPENAI_BASE_URL` 三者是否一致，密钥是否对该模型开通权限 |
| 复验总是失败且耗时很长 | 检查 `CI_FIX_BUILD_CACHE_DIR` 是否存在且可写，缓存未被 `until=168h` 清掉 |
| code-fix 未触发 | 三轮 `verify_passed` 是否都为 `false` |
