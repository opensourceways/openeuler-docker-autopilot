# 场景二改回「应用自动升级」实施方案

## Context

当前场景二被 PR CI 失败自动修复占用，应用自动升级由社区 anitya + easysoftware-autoupgrade 承担。目标是让本系统**完全替代**这两个社区服务：每天用 upstream-dashboard 的 `GET /api/v1/version/resolve` 解析各软件最新上游版本，为缺新版本的存量应用生成新版本镜像目录、双架构原生验证、按需补功能测试，一应用一 PR。

已确认的四条决定：

1. 升级 PR **同 PR 补测试**；存量缺测试保留独立手动入口（场景四）。
2. 现有 PR CI 修复链路抽成可复用组件，**只保留手动 / 显式调用**，取消 Monitor 自动轮询。
3. 版本源只认 upstream-dashboard `version/resolve`。
4. **上游证据**：接口目前只返回版本号，后续会补充采集到的上游证据。系统必须能处理这份证据（**仅供 AI 参考，不作为阻断门禁**）；证据缺失时**系统自探兜底**（探测上游 tag/release/源码包可达性）；接口层**原样透传未知字段 + 证据归一化适配层**，后续接口加字段不用改 workflow。

现状盘点（已核实）：

- `upgrade_upstream_versions.yml` + `_upgrade_versions.yml` + `run.py adversarial-pair` 是 **legacy 骨架，跑不通**：不 clone 目标仓、在 workflow 根目录 `docker build .`、`run.py test` 直接 `SystemExit(2)`、`query_version.py` 打的是 easysoftware-monitoring 且模板参数非法（`${%-%...%}`）。
- 现代 TaskSpec 管线（`scripts/lib/generation_pipeline.py` + `native_validation.validate_native_image`）只接入了 `new-image`，但 `TaskSpec` 已支持 `version-update`，`flow.py phase1-native-validate` 可直接复用做双架构原生验证。
- `testgen_generate.generate_test_script()` 只依赖工作树、不碰分支/PR，可独立复用；`testgen_scan.index_target_apps/latest_dockerfile/has_any_test_script` 可复用来定位应用。

## 目标形态

| 场景 | 入口 | 触发 |
|---|---|---|
| ① 新增镜像 | `create_new_images.yml` | Issue / 手动（不变） |
| ② **应用自动升级** | `upgrade_upstream_versions.yml`（重写） | 每日定时 + 手动 `app` / `version` |
| ③ openEuler 版本升级 | `upgrade_openeuler_versions.yml` | 不变（legacy，暂不动） |
| ④ 存量补功能测试 | `generate_test_scripts.yml` | 手动（保留，作为场景二子能力的独立入口） |
| 公共组件 | `_ci_repair.yml`（新增，`workflow_call`）+ `ci_fix_pipeline.yml` 薄壳 | 手动 / 显式 dispatch，无 cron |

## 实施步骤

### 1. upstream-dashboard 客户端（新）

`scripts/lib/upstream_dashboard.py`

- `resolve_version(name, version=None) -> dict`：`GET {UPSTREAM_DASHBOARD_BASE}/api/v1/version/resolve`，默认 `https://upstream-dashboard.test.osinfra.cn`，可用环境变量 / 仓库 Variable 覆盖。
- 返回**原始 payload**（`name/tag/version/display_version/tag_url/commit_sha/source/blocked_reason/fetched_at` + 未来新增字段一律保留）。
- `is_usable(payload)`：`blocked_reason is None`。
- 错误语义按文档：400/404 确定性失败 → `None` + 日志；502 重试 2 次；503 直接失败。
- 带浏览器 UA（看板前置 WAF 对默认 UA 返回 418，场景四已踩过）。

### 2. 上游证据适配层（新）

`scripts/lib/upstream_evidence.py`

- `normalize(payload) -> dict`：**适配层**。已知字段抽成结构化 `{tag, tag_url, commit_sha, source, fetched_at, repo_url}`；其余未知字段原样放进 `raw`，并尝试若干常见键名（`evidence` / `upstream_evidence` / `checks` / `items`）提升为 `collector` 证据列表。接口改造后新增字段无需改 workflow。
- `probe(version_info) -> dict`：**自探兜底**。证据缺失时自行探测上游是否真的存在该版本：
  - GitHub API `/repos/{owner}/{repo}/git/ref/tags/{tag}`、`/releases/tags/{tag}`；
  - `HEAD` 源码归档 URL（`archive/refs/tags/{tag}.tar.gz`，或 `tag_url` 指向的归档）确认可下载；
  - 产出 `{source: "self-probe", tag_exists, release_exists, archive_url, archive_status, checked_at}`。
  - 非 GitHub 仓库（`source=watched`、gitcode 等）跳过探测，记录 `skipped`；单次 10s 超时，探测失败只告警、不阻断。
- `render_markdown(evidence) -> str`：PR 正文的「上游证据」段；`render_prompt(evidence) -> str`：注入 testgen / 生成提示的上下文段。
- **定位**：证据只作 AI 参考与 PR 留痕，**不参与门禁判定**；是否可用仍以双架构原生构建 + 功能测试结果为准。

### 3. 升级候选发现

`scripts/harness/upgrade_scan.py`（新）

- 输入：`--repo <目标仓克隆>`、可选 `--app`、`--version`（手动指定时跳过看板）。输出 `--format github-output` 写 `updates=<json>`。
- 遍历 `{domain}/{app}/{version}/{os}/Dockerfile`（复用 `testgen_scan` 的 `index_target_apps` / `latest_dockerfile` / `_version_key`）。
- 对每个应用调 `resolve_version`（线程池并发 ≤8、超时 30s），再 `upstream_evidence.normalize` + `probe`：
  - `blocked_reason != null` → skip（记录原因）；
  - 解析版本已存在同版本目录（去 `v` 前缀、忽略大小写）→ skip；
  - 已存在 open PR（`auto/version-update/<app>/...`）→ skip；
  - 命中 → `{app, domain, version, os_version=<该应用最新 os 目录>, source_url, evidence:{...}}`。

### 4. 确定性版本升级（新）

`scripts/lib/version_upgrade.py`

- `plan_upgrade(app_dir) -> UpgradePlan(old_version, os_version, src_dir)`：取最高 `(version, os)`。
- `apply_upgrade(app_dir, plan, new_version) -> list[Path]`：`copytree` 到 `{new_version}/{os_version}/`；替换 `Dockerfile` / `README.md` / `doc/image-info.yml` 里的旧版本整串；`meta.yml` 追加 `"<new_version>-<oe_tag>": {path: <new_version>/<os>/Dockerfile}`（`oe_tag` 复用 `task_spec._os_tag`）。
- **Fail closed**：Dockerfile 里找不到旧版本串时报 `UpgradeError`（特化写法，交人工），不产出半成品目录。

### 5. 功能测试补写（复用场景四）

- 干净克隆上（bump 之前）用 `has_any_test_script()` 判断缺失；缺失则调 `generate_test_script(...)`，只生成本地文件（不调 `run_generate` / `deliver`）。
- `upstream_evidence.render_prompt(evidence)` 作为额外上下文拼进生成提示（角色契约不变）。
- 生成失败**非阻断**：记录 findings，PR 正文标注「测试脚本待补」，版本升级照常推进。

### 6. 场景二编排（重写 `upgrade_upstream_versions.yml`）

触发：

```yaml
on:
  schedule: [{cron: '0 1 * * *'}]     # 每天 UTC 1:00，避开 ci-fix 0:00
  workflow_dispatch:
    inputs: {app, version, runner_labels}
```

Job 图（一应用一 PR）：

1. `discover`（自托管 X64）：clone 目标仓（**完整克隆**，后面要 push）→ `upgrade_scan.py` → `updates` matrix。
2. `prepare`（matrix: app）：clone → 补测试（步骤 5）→ 确定性 bump（步骤 4）→ commit → push `auto/version-update/<app>/<ver>-oe<os>` 到 `GITCODE_FORK_REPO`；产出 `task-spec.json`（`TaskSpec(scenario="version-update")`）+ patch artifact。
3. `validate`（matrix: app × arch，`x86_64`→`oe-image-x86`、`aarch64`→`oe-image-arm64`）：`phase1-setup`（arch/preflight）+ `flow.py phase1-native-validate`（照 `_create_new_image_rounds.yml` 的调用），`continue-on-error: true` + 证据 artifact。
4. `open-pr`（needs validate 全绿）：`gate_diff.py task-contract --phase final` → `create_pull_request` 跨仓 PR；正文包含版本信息 + **上游证据段**（`tag` / `tag_url` / `commit_sha` / `source` / `fetched_at` + collector 证据或自探结果）+「测试脚本：新增 / 已存在 / 待补」。
5. 失败应用在 job summary 汇总；不自动修复（失败 PR 的 CI 交给公共修复组件手动触发）。

删除 legacy 引用：`_upgrade_versions.yml` 仍被场景三使用，**保留**；`upgrade_upstream_versions.yml` 中 `run.py` / `_upgrade_versions.yml` 全部移除。

### 7. CI 修复抽成公共组件 + 取消自动轮询

- 新增 `_ci_repair.yml`：把 `ci_fix_pipeline.yml` 的 job 图原样搬成 `workflow_call`（输入 `source_repo/pr_number/source_platform/fix_pr_number/attempt/三类 runner 标签`，secrets 全量声明）。
- `ci_fix_pipeline.yml` 变薄壳：`workflow_dispatch` + `repository_dispatch: [run-ci-fix]` → 单 job `uses: _ci_repair.yml` + `secrets: inherit`。
- `monitor_ci_failed_prs.yml`：**删除 `schedule`**，只留 `workflow_dispatch`。
- `sync_ci_poll_interval.yml` + `scripts/watch/sync_poll_interval.py`（只负责改写上述 cron）→ 删除（含测试）。
- `scripts/watch/process_pr_events.py` 保留（手动轮询仍用）。

### 8. 文档与测试

文档：`README.md`（场景表/触发源/阶段表/新增 `UPSTREAM_DASHBOARD_BASE`/2.4 验证）、`docs/repository-overview.md`、`docs/ci-fix-round-workflow.md`。

测试：

- `tests/test_upstream_dashboard.py`：正常返回、`blocked_reason`、400/404、502 重试、503、未知字段透传。
- `tests/test_upstream_evidence.py`：normalize 适配层（含未知字段/collector 提升）、probe 三类结果（tag/release/archive 可下载、不可下载、跳过）、render 输出。
- `tests/test_upgrade_scan.py`：命中/已存在/open PR/blocked、`--app`/`--version` 覆盖、os 取最新。
- `tests/test_version_upgrade.py`：copytree、三处替换、meta.yml 追加、找不到旧版本串 fail closed。
- `tests/test_upgrade_workflow.py`：定时 + 手动输入、job 图、arch runner 标签、无 `run.py`、无字面 `ubuntu-latest`。
- 更新 `tests/test_ci_fix_workflow.py`（薄壳 + `_ci_repair.yml`、Monitor 无 `schedule`）。

## 验证

1. `python -m pytest tests -q`（本地已知 2 个 `bash -n` 环境性失败 + 1 个 contract 用例，与本次无关）。
2. 真实链路：`gh workflow run upgrade_upstream_versions.yml -f app=<存量落后应用>`，观察 discover（含证据段）→ prepare（bump + 补测试）→ 双架构 validate → PR。
3. 证据：先在不支持探测的上游确认 `skipped` 不报错；再用 GitHub 上游确认自探结果（tag/release/archive 状态）出现在 PR 正文。
4. 失败面：对 Dockerfile 无版本串的应用确认 `UpgradeError` 直接失败、不产生分支。
5. 修复组件：手动触发 `ci_fix_pipeline.yml` 一次（复用 PR #6204）确认行为不变。

## 风险与回滚

- 看板测试环境前置 WAF，`version/resolve` 可能 418：discover 明确失败并打印 URL/状态码；可用 `UPSTREAM_DASHBOARD_BASE` 切换地址。
- 定时全量可能一次产生多个 PR：首轮先手动单应用验证，稳定后再放开 `app` 缺省。
- 证据字段未知：适配层不猜测必填项，只做归纳与透传；证据异常绝不影响升级主流程。
- `_ci_repair.yml` 抽取只搬 job、不改脚本，回滚即恢复单体 workflow。
