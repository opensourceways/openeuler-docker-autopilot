# docker-images-workflow — 数据模型文档

**状态:** 已发布
**日期:** 2026-06-15
**版本:** 1.0

---

## 目录

1. [概述](#1-概述)
2. [watchlist.json](#2-watchlistjson)
3. [repository_dispatch payload](#3-repository_dispatch-payload)
4. [ci-analysis.md](#4-ci-analysismd)
5. [code-fix-summary.md](#5-code-fix-summarymd)
6. [ci-failure-patterns.md（知识库）](#6-ci-failure-patternsmd知识库)
7. [fix-notified（状态标记文件）](#7-fix-notified状态标记文件)
8. [Git 分支存储结构](#8-git-分支存储结构)
9. [Fix PR 标题与正文规范](#9-fix-pr-标题与正文规范)
10. [环境变量一览](#10-环境变量一览)
11. [数据流依赖关系](#11-数据流依赖关系)

---

## 1. 概述

### 1.1 存储体系

系统使用 **Git 分支** 作为唯一持久化存储，无数据库、无对象存储：

| 存储 | 位置 | 用途 | 维护方式 |
|------|------|------|---------|
| **ci-fix-log 分支** | `{workflow_repo}/ci-fix-log/` | per-PR 诊断报告、修复摘要、通知状态 | 全自动（由工作流写入） |
| **main 分支（知识库）** | `{workflow_repo}/docs/ci-failure-patterns.md` | 跨 PR 共享的失败模式知识库 | 自动追加（Fix PR 通过 CI 后触发） |
| **main 分支（配置）** | `{workflow_repo}/config/watchlist.json` | 监控仓库列表与轮询参数 | 手动维护 |

所有文件读写通过 **GitHub Contents API** 完成，无需 git clone workflow 仓库。

### 1.2 文件清单

| 文件 | 存储位置 | 生命周期 | 维护方式 |
|------|---------|---------|---------|
| `watchlist.json` | `main` 分支 `config/` | 持久（手动更新） | 手动 |
| `ci-analysis.md` | `ci-fix-log` 分支 `ci-fix-log/{pr_number}/` | 持久（per-PR） | 全自动 |
| `code-fix-summary.md` | `ci-fix-log` 分支 `ci-fix-log/{pr_number}/` | 持久（per-PR） | 全自动 |
| `fix-notified` | `ci-fix-log` 分支 `ci-fix-log/{pr_number}/` | 持久（per-PR） | 全自动 |
| `ci-failure-patterns.md` | `main` 分支 `docs/` | 持久（累积追加） | 自动（CI 验证后） |

### 1.3 命名约定

| 规则 | 格式 | 示例 |
|------|------|------|
| PR 编号 | 整数，目标仓库的 PR number | `2546` |
| Fix 分支名 | `fix/{pr_number}` | `fix/2546` |
| Fix PR 标题 | `fix: {软件名} {版本} (fix #{pr_number})` | `fix: netty 4.2.13 (fix #2546)` |
| 模式 ID | `模式{NN}：` 两位数字，冒号后加标题 | `模式01：Apache CDN Maven 版本 404` |
| 时间戳 | ISO 8601 | `2026-06-15T10:00:00Z` |

---

## 2. watchlist.json

**路径：** `config/watchlist.json`（`main` 分支）

**用途：** 定义监控目标仓库列表和轮询行为参数，`stream-pr-events.yml` 每次运行时读取。

### 2.1 顶层结构

```json
{
  "watched_repos": [ ... ],
  "settings": {
    "poll_interval_minutes": 10,
    "max_events_per_run": 50,
    "lookback_minutes": 100000
  }
}
```

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `watched_repos` | WatchedRepo[] | ✅ | 监控仓库列表 |
| `settings.poll_interval_minutes` | integer | ✅ | 轮询间隔（分钟）；修改后自动触发 `sync-poll-interval.yml` 更新 cron |
| `settings.max_events_per_run` | integer | ✅ | 每次运行最多处理的 PR 数量，防止 Action 超时 |
| `settings.lookback_minutes` | integer | ✅ | 只处理 `updated_at` 在此时间窗口内的 PR（0 表示不限制） |

### 2.2 WatchedRepo 对象

```json
{
  "repo": "https://gitcode.com/openeuler/openeuler-docker-images",
  "trigger_labels": ["ci_failed"],
  "enabled": true,
  "description": "openEuler 容器镜像"
}
```

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `repo` | string (URL) | ✅ | 目标仓库完整 URL；含 `gitcode.com` 则识别为 GitCode，否则为 GitHub |
| `trigger_labels` | string[] | ✅ | 触发修复的 label 列表；取第一个元素作为主触发 label（通常为 `ci_failed`） |
| `enabled` | boolean | ✅ | `false` 时完全跳过该仓库，不计入轮询 |
| `description` | string | ❌ | 仓库描述，仅供人类阅读，不影响逻辑 |

**约束：**
- `repo` 中的 URL scheme 和域名决定平台类型，`get_api()` 据此选择 API 实现
- `trigger_labels[0]` 同时用于：①获取 PR 列表的过滤条件；②判断 Fix PR 是否处于 ci_failed 状态

---

## 3. repository_dispatch payload

**类型：** GitHub repository_dispatch，event_type 为 `run-ci-fix-phase`。

### 3.1 ci-log-analysis 阶段 payload

```json
{
  "event_type": "run-ci-fix-phase",
  "client_payload": {
    "phase": "ci-log-analysis",
    "source_repo": "openeuler/openeuler-docker-images",
    "source_platform": "gitcode",
    "pr_number": 2546,
    "pr_title": "【自动升级】netty容器镜像升级至4.2.13版本.",
    "head_sha": "abc123def456",
    "fix_branch": "fix/2546",
    "pr_base_branch": "master",
    "fix_pr_number": 0
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `phase` | `"ci-log-analysis"` | 固定值，决定触发哪个 Job |
| `source_repo` | string | `{owner}/{repo}` 格式，不含 URL scheme |
| `source_platform` | `"gitcode"` \| `"github"` | 平台标识，影响 API 选择和 checkout 方式 |
| `pr_number` | integer | 原始 PR 编号（目标仓库） |
| `pr_title` | string | 原始 PR 标题 |
| `head_sha` | string | 原始 PR 的 HEAD commit SHA |
| `fix_branch` | string | fix 分支名，格式 `fix/{pr_number}` |
| `pr_base_branch` | string | 原始 PR 的目标分支（通常为 `master` 或 `main`） |
| `fix_pr_number` | integer | 首次为 `0`；重试时为 Fix PR 的编号（用于从 Fix PR 评论查最新构建 URL） |

### 3.2 code-fix 阶段 payload

```json
{
  "event_type": "run-ci-fix-phase",
  "client_payload": {
    "phase": "code-fix",
    "source_repo": "openeuler/openeuler-docker-images",
    "source_platform": "gitcode",
    "pr_number": 2546,
    "pr_title": "【自动升级】netty容器镜像升级至4.2.13版本.",
    "pr_head_sha": "abc123def456",
    "fix_branch": "fix/2546",
    "pr_base_branch": "master"
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `phase` | `"code-fix"` | 固定值 |
| `pr_head_sha` | string | 原始 PR 的 HEAD SHA（用于 checkout 起始点） |
| 其他字段 | — | 同 ci-log-analysis payload（相同含义） |

**注意：** code-fix payload 不包含 `analysis` 字段。分析报告从 ci-fix-log 分支读取（`ci_data.read_file(analysis_path(pr_number))`），不通过 payload 传递，以避免大小限制问题。

---

## 4. ci-analysis.md

**路径：** `ci-fix-log/{pr_number}/ci-analysis.md`（`ci-fix-log` 分支）

**生成者：** `ci-failure-analyst` Agent（由 `ci-log-analysis.py` 驱动）

**用途：** 结构化 CI 失败诊断报告，是 code-fix 阶段的核心输入；同时在 Fix PR 通过后提取元数据写入知识库。

### 4.1 文件结构规范

```markdown
# CI 失败分析报告

## 基本信息
- PR: #{pr_number} — {pr_title}
- 失败类型: {type}
- 置信度: 高 | 中 | 低
- 知识库匹配: 模式NN | 新模式
- 新模式标题: {3-8字标题}          ← 仅"新模式"时填写
- 新模式症状关键词: {关键词,逗号分隔}  ← 仅"新模式"时填写

## 根因分析

### 直接错误
（日志中最关键的错误信息，不超过 20 行）

### 根因定位
- 失败位置: {文件路径}:{行号}
- 失败原因: {一句话描述}

### 与 PR 变更的关联
（PR 的哪些改动触发了这个失败，或说明与 PR 无关）

## 修复方向

### 方向 1（置信度: 高/中/低）
{修复思路描述，不含代码}

### 方向 2（可选）
{多种可能的根因时填写}

## 需要进一步确认的点
（日志不足时，列出需要查阅的内容）
```

### 4.2 失败类型枚举

| 类型 | 描述 | infra-error 时行为 |
|------|------|-------------------|
| `build-error` | 编译/构建失败 | — |
| `test-failure` | 测试用例失败 | — |
| `lint-error` | 代码风格检查失败 | — |
| `type-error` | 类型检查失败 | — |
| `dependency-error` | 依赖安装/版本冲突 | — |
| `runtime-error` | 运行时崩溃 | — |
| `timeout` | 超时 | — |
| `infra-error` | CI 基础设施问题（或证据不足） | code-fix 阶段不做代码修改，输出说明摘要 |

### 4.3 知识库元数据字段（由 ci_data.append_pattern 提取）

| 字段名（报告中） | 说明 | 用途 |
|---------------|------|------|
| `知识库匹配` | `模式NN` 或 `新模式` | 决定追加到已有模式还是新建章节 |
| `新模式标题` | 3-8 字简短标题 | 新模式章节标题 |
| `新模式症状关键词` | 逗号分隔的关键词 | 新模式的检索关键词 |
| `根因定位`（章节） | 根因描述段落 | 新模式的根因字段（取前 300 字符） |

### 4.4 证据不足报告（infra-error 路径）

当日志末尾显示 `Finished: SUCCESS` 但 PR 仍有 `ci_failed` label 时，输出固定格式：

```markdown
# CI 失败分析报告

## 基本信息
- PR: #{pr_number} — {pr_title}
- 失败类型: infra-error
- 置信度: 低
- 知识库匹配: 新模式
- 新模式标题: 证据不足（日志来自编排层）

## 根因分析

### 直接错误
日志末尾：Finished: SUCCESS

### 根因定位
- 失败位置: 未知（日志来自 trigger/编排层 job）
- 失败原因: 提供的日志来自编排层，真正失败在下游架构 job 中

## 需要进一步确认的点
- 需获取下游架构构建 job 的日志（如 /job/x86-64/... 或 /job/aarch64/...）
```

---

## 5. code-fix-summary.md

**路径：** `ci-fix-log/{pr_number}/code-fix-summary.md`（`ci-fix-log` 分支）

**生成者：** `code-fixer` Agent（由 `code-fix.py` 驱动）

**用途：** 修复摘要，是 Fix PR 正文的来源，也是知识库写入时提取修复描述的数据源。

### 5.1 文件结构规范

```markdown
# 修复摘要

## 修复的问题
{一句话描述修复了什么}

## 修改的文件
- `{文件路径}`: {改动说明}
- ...

## 修复逻辑
{说明为什么这样修复，修复了分析报告中的哪个根因}

## 潜在风险
{影响说明，或"无"}
```

### 5.2 无修改路径的摘要

当 AI 判断无需代码修改（如 infra-error），摘要内容类似：

```markdown
# 修复摘要

## 修复的问题
无需代码修改：CI 失败属于 infra-error（日志来自编排层，实际错误在下游 job 中）

## 修改的文件
（无）

## 修复逻辑
根据 CI 日志分析，提供的日志末尾显示成功，无法定位实际失败点，不做代码修改。

## 潜在风险
无
```

### 5.3 知识库提取字段（由 ci_data.append_pattern 使用）

| 章节 | 用途 |
|------|------|
| `修复的问题` | 历史案例行中的修复描述（取首行，不超过 60 字符） |
| `修改的文件` | 历史案例行中的文件路径（取第一个反引号包裹路径） |

---

## 6. ci-failure-patterns.md（知识库）

**路径：** `docs/ci-failure-patterns.md`（`main` 分支）

**维护方式：** Fix PR 通过 CI 后自动追加，不应手动覆盖（手动编辑可以补充描述，但不应改变已有模式的结构）。

### 6.1 文件头部

```markdown
# CI 失败模式知识库

> **按失败模式分类**，每个模式包含：典型报错、根因分析、修复方法、历史案例。
> 处理新失败 PR 时，**用报错关键词搜索对应章节**，直接找到修复方法。
```

### 6.2 模式章节结构

```markdown
---

## 模式{NN}：{标题}

**症状关键词**: {关键词1} {关键词2} ...

**根因**: {一句话根因描述}

**修复方法**:
1. **{方法1名称}**：{描述}
2. **{方法2名称}**：{描述}（可选）

**历史案例**:
- PR #{pr_number}: `{文件路径}` — {修复描述}
- PR #{pr_number}: `{文件路径}` — {修复描述}
```

### 6.3 模式编号规则

| 规则 | 说明 |
|------|------|
| 格式 | `模式{NN}：` 两位数字，全角冒号，后接中文标题 |
| 自动递增 | `_count_patterns(content)` 统计现有模式数量，新模式编号 = 现有数量 + 1 |
| 不可复用 | 删除模式后，编号不可重新分配（避免历史案例引用混乱） |

### 6.4 自动追加逻辑

`ci_data.append_pattern()` 的决策流程：

```
从 ci-analysis.md 提取 "知识库匹配" 字段
        │
        ├─ 如 "模式05"（含数字，无"新模式"字样）
        │       ↓
        │  在 docs/ci-failure-patterns.md 中定位 "## 模式05：" 章节
        │       ↓
        │  在该章节的 "**历史案例**:" 列表末尾插入一行：
        │  "- PR #{pr_number}: `{file_path}` — {fix_desc}"
        │       ↓
        │  写回文件
        │
        └─ 如 "新模式" 或匹配失败
                ↓
           在文件末尾追加新章节：
           "## 模式{next_num}：{new_title}"
           含 症状关键词 / 根因 / 修复方法 / 历史案例（一条）
                ↓
           写回文件（main 分支）
```

---

## 7. fix-notified（状态标记文件）

**路径：** `ci-fix-log/{pr_number}/fix-notified`（`ci-fix-log` 分支）

**用途：** 布尔标记文件，文件存在即表示已通知原始 PR 维护者合并 Fix PR，防止重复评论。

**内容：** 字符串 `"notified"`（固定值，内容无实际意义）

**写入时机：** `process_pr_events.py` 向原始 PR 添加 `🎉 AI 修复 PR #XX 已通过 CI` 评论成功后

**读取逻辑：**

```python
def is_fix_notified(pr_number: int) -> bool:
    return bool(read_file(fix_notified_path(pr_number), branch=CI_FIX_BRANCH))
```

---

## 8. Git 分支存储结构

### 8.1 ci-fix-log 分支

```
ci-fix-log/          ← 分支根目录（非 main 分支，不含源码）
└── ci-fix-log/
    ├── {pr_number}/
    │   ├── ci-analysis.md        ← CI 失败诊断报告
    │   ├── code-fix-summary.md   ← 代码修复摘要
    │   └── fix-notified          ← 已通知标记（存在即为已通知）
    ├── {pr_number}/
    │   └── ...
    └── ...
```

**分支初始化：** 首次写入时，若 `ci-fix-log` 分支不存在，`_ensure_ci_fix_branch()` 自动从 `main` 分支的 HEAD commit 创建。

### 8.2 main 分支（workflow 仓库）

```
main/
├── .github/
│   ├── agents/
│   │   ├── ci-failure-analyst.md
│   │   └── code-fixer.md
│   └── workflows/
│       ├── stream-pr-events.yml
│       ├── pr-ci-fix-trigger.yml
│       └── sync-poll-interval.yml
├── config/
│   └── watchlist.json         ← 监控配置（手动维护）
├── docs/
│   ├── ci-failure-patterns.md ← 知识库（自动追加）
│   └── design/
│       ├── PRD.md
│       ├── system-design.md
│       └── data-model.md
├── scripts/
│   └── ...
└── tests/
    └── ...
```

---

## 9. Fix PR 标题与正文规范

### 9.1 标题格式

```
fix: {软件名} {版本号} (fix #{原始PR号})
```

**软件名/版本提取规则（`fix_pr_body.py`）：**

```python
# 从原始 PR 标题中提取软件名和版本
# 常见格式：
# "【自动升级】netty容器镜像升级至4.2.13版本."
# "chore: bump netty from 4.2.12 to 4.2.13"

# 正则：尝试识别 "升级至X.Y.Z版本"、"from X to Y" 等模式
# 若提取失败，回退到：fix: (fix #{pr_number})
```

**示例：**

| 原始 PR 标题 | Fix PR 标题 |
|------------|------------|
| `【自动升级】netty容器镜像升级至4.2.13版本.` | `fix: netty 4.2.13 (fix #2546)` |
| `chore: bump netty from 4.2.12 to 4.2.13` | `fix: netty 4.2.13 (fix #2546)` |
| `【自动升级】developer-tool升级至1.0.0版本.` | `fix: developer-tool 1.0.0 (fix #2550)` |

### 9.2 正文结构

```markdown
## CI 修复说明

本 PR 由 AI 自动生成，修复了 #{原始PR号} 的 CI 失败。

### 修复的问题
{从 code-fix-summary.md 的"修复的问题"章节提取}

### 修改的文件
{从 code-fix-summary.md 的"修改的文件"章节提取}

### 修复逻辑
{从 code-fix-summary.md 的"修复逻辑"章节提取}

---
🤖 Generated by docker-images-workflow
```

**数据来源优先级：**

1. `ci-fix-log/{pr_number}/code-fix-summary.md`（ci-fix-log 分支）
2. 若文件不存在，回退到最小正文（仅标注 fix #pr_number，无修复详情）

---

## 10. 环境变量一览

### 10.1 GitHub Actions Secrets

| Secret | 必需 | 用途 |
|--------|------|------|
| `DISPATCH_TOKEN` | ✅ | GitHub 操作：触发 dispatch、ci-data 分支读写、checkout、推送 fix 分支、创建 Fix PR（GitHub） |
| `GITCODE_TOKEN` | GitCode 仓库时 ✅ | GitCode 操作：读 PR/CI 日志、推送 fork、创建 Fix PR、评论 |
| `AI_API_KEY` | `AI_RUNNER=opencode` 时 ✅ | AI 模型 API Key（同时注入为 `OPENAI_API_KEY` 和 `DEEPSEEK_API_KEY`） |
| `CLAUDE_CREDENTIALS_JSON` | `AI_RUNNER=claude-code-account` 时 ✅ | Claude.ai OAuth 凭证 JSON 内容 |

### 10.2 GitHub Actions Variables

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `AI_RUNNER` | `opencode` | AI 后端：`opencode` 或 `claude-code-account` |
| `AI_MODEL` | `deepseek/deepseek-v4-pro` | 模型名称；OpenCode 填 `{provider}/{model}`，Claude Code 填 Claude 模型 ID |
| `AI_TIMEOUT_MS` | `1800000`（30分钟） | 单次 AI 调用超时毫秒数 |
| `OPENAI_BASE_URL` | `''` | OpenCode 的 API 代理地址（留空使用默认端点） |
| `GITCODE_FORK_REPO` | `''` | GitCode Fix PR 的 fork 仓库路径（留空则直接 push 原仓库） |
| `GIT_COMMIT_NAME` | `github-actions[bot]` | Fix commit 的 git user.name |
| `GIT_COMMIT_EMAIL` | `github-actions[bot]@users.noreply.github.com` | Fix commit 的 git user.email |

### 10.3 工作流运行时环境变量（pr-ci-fix-trigger.yml 注入）

| 变量 | 来源 | 说明 |
|------|------|------|
| `SOURCE_REPO` | client_payload | `{owner}/{repo}` 格式 |
| `SOURCE_PLATFORM` | client_payload | `gitcode` 或 `github` |
| `PR_NUMBER` | client_payload | 原始 PR 编号 |
| `PR_TITLE` | client_payload | 原始 PR 标题 |
| `HEAD_SHA` | client_payload | 原始 PR HEAD SHA（ci-log-analysis Job） |
| `PR_HEAD_SHA` | client_payload | 原始 PR HEAD SHA（code-fix Job） |
| `FIX_BRANCH` | client_payload | `fix/{pr_number}` |
| `PR_BASE_BRANCH` | client_payload | 原始 PR 目标分支 |
| `FIX_PR_NUMBER` | client_payload | Fix PR 编号（首次为 0） |
| `GITHUB_TOKEN` | Secret DISPATCH_TOKEN | GitHub API 认证 |
| `DISPATCH_TOKEN` | Secret DISPATCH_TOKEN | repository_dispatch 认证 |
| `GITCODE_TOKEN` | Secret GITCODE_TOKEN | GitCode API 认证 |

---

## 11. 数据流依赖关系

```
watchlist.json（手动维护）
    │
    └─▶ process_pr_events.py（Monitor 轮询）
              │
              ├─ 读取 API（目标仓库 PRs + Fix PR 状态）
              │
              └─ dispatch run-ci-fix-phase [ci-log-analysis]
                        │
                        ▼
               ci-log-analysis.py
                  ├─ 读: 目标仓库 PR diff（平台 API）
                  ├─ 读: CI 日志（Jenkins URL，来自 PR/Fix PR 评论）
                  ├─ 读: docs/ci-failure-patterns.md（知识库，main 分支）
                  ├─ 写: ci-fix-log/{pr_number}/ci-analysis.md（ci-fix-log 分支）
                  └─ dispatch run-ci-fix-phase [code-fix]
                            │
                            ▼
                   code-fix.py
                      ├─ 读: ci-fix-log/{pr_number}/ci-analysis.md（ci-fix-log 分支）
                      ├─ 读: 目标仓库 PR 文件列表（git diff 或平台 API）
                      ├─ 写: 目标仓库 fix/{pr_number} 分支（git commit + push）
                      ├─ 写: Fix PR（平台 API 创建或更新）
                      └─ 写: ci-fix-log/{pr_number}/code-fix-summary.md（ci-fix-log 分支）
                                │
                                ▼
                   Fix PR 通过 CI（ci_successful label）
                                │
                                ▼
                   process_pr_events.py（下次轮询）
                      ├─ 写: 原始 PR 评论（通知维护者）
                      ├─ 写: ci-fix-log/{pr_number}/fix-notified（ci-fix-log 分支）
                      └─ 写: docs/ci-failure-patterns.md（追加模式，main 分支）
```
