# 场景四：存量镜像功能测试脚本自动生成

## Context

openeuler/openeuler-docker-images 中约 789 个应用仅约 45 个有功能测试脚本。用户已将该仓库的 CI 与功能测试绑定（新提交 → Dockerfile 变更触发构建 → 构建成功后按 `{app}/tests/test.sh` 执行功能测试）。本方案新增"场景四"定时工作流：爬取 Kunpeng 上游看板获取软件清单 → 与目标仓库对比找出缺测试脚本的软件 → AI Agent 按 KunpengTest 规范生成 `test.sh` → 静态校验 → 一软件一 PR（附 Dockerfile 空行变更以触发用户绑定的 CI 构建+测试）。

**用户确认的决策**：定时自动跑（每天一轮）；看板 API 免认证全量拉取；名称宽松匹配（匹配不上记报告跳过）；脚本完全遵循 KunpengTest 规范（禁 `set -e`、脚本内自行拉起服务等就绪、适配 5 个注入环境变量）；仅静态校验不实跑（失败喂回 Agent 修复，最多 2 轮重试）；一软件一 PR；每轮限量 10 个分批推进。

**复用策略**：Agent 栈复用场景一 `agent_runtime.run_agent`（JSON 契约校验/超时/恢复机制成熟）；交付复用场景二轻量 fork 推送模式（`GITCODE_FORK_REPO` 变量，不碰场景一硬编码 fork 的 `pr_delivery.py` 链）；workflow 骨架照 `upgrade_openeuler_versions.yml` 的 scan outputs → `fromJSON` matrix 扇出；跨轮状态照 `ci_data.py` 的分支标记模式。

## 新增/修改文件

### 新增

| 文件 | 职责 |
|---|---|
| `scripts/lib/testgen_dashboard.py` | 看板客户端。`fetch_dashboard_software(domain="kunpeng") -> list[DashboardSoftware]`，分页拉 `https://upstream-dashboard.test.osinfra.cn/api/v1/software?domain=kunpeng&page_size=100&page=N` 直到 items 空；dataclass：name/repo_url/latest_version/is_active；异常重试一次，失败返回 None（本轮空转，宁可晚一天） |
| `scripts/lib/kunpeng_test_contract.py` | KunpengTest 静态校验器。`check_test_script(path) -> list[dict]`（findings 结构照 `target_contract._test_finding`：code/message/check）。规则清单见下 |
| `scripts/lib/testgen_state.py` | 跨轮状态（复用 `ci_data.read_file/write_file` 的 branch 参数，分支 `testgen-log`）：`is_done(app)` / `mark_done(app, pr_url)` / `is_exhausted(app)` / `mark_exhausted(app, reason)`，路径 `testgen-log/{app}/done|exhausted` |
| `scripts/harness/testgen_scan.py` | scan CLI：拉看板 + 遍历目标仓 + 匹配 + 缺口判定 + 去重 + 限量截取，写 GITHUB_OUTPUT |
| `scripts/harness/testgen_generate.py` | 单 app 生成 CLI：prompt 组装 → run_agent → 静态校验 → 重试闭环 → Dockerfile 空行 → commit/push/PR |
| `.github/agents/testgen-creator.md` | Creator 提示词（KunpengTest 规范内嵌为硬规则清单） |
| `.github/workflows/generate_test_scripts.yml` | 入口 workflow |

### 修改

- [agent_runtime.py](file:///d:/openeuler-docker-autopilot/scripts/lib/agent_runtime.py) L91：`_WRITE_ROLES` 加 `"testgen_creator"`
- [task_spec.py](file:///d:/openeuler-docker-autopilot/scripts/lib/task_spec.py) L31 `_SCENARIOS` 加 `"test-script"`（分支名不用其派生规则，固定 `auto/test-script/{app}`）
- [ci_data.py](file:///d:/openeuler-docker-autopilot/scripts/lib/ci_data.py) L64：`_ensure_ci_fix_branch` 泛化为 `ensure_branch(branch)`，write_file 对任意 branch 调用
- README.md / DESIGN.md / docs/repository-overview.md：场景表加"场景四：存量镜像功能测试补齐"

## Workflow 结构（generate_test_scripts.yml）

```yaml
on:
  schedule: [{cron: '0 2 * * *'}]   # 每天 UTC 2 点，避开场景二的 0 点
  workflow_dispatch: {inputs: app(可选，单软件调试), limit(默认10), runner_labels}
concurrency: {group: testgen, cancel-in-progress: false}
jobs:
  scan:   # 20 分钟超时
    - checkout 本仓 + phase1-setup + pip install
    - git clone --depth 1 oauth2:GITCODE_TOKEN 目标仓 → target-repo
    - python scripts/harness/testgen_scan.py --repo target-repo --format github-output
      # env: GITCODE_TOKEN, TESTGEN_LIMIT=inputs.limit||vars.TESTGEN_MAX_PER_ROUND||10, DISPATCH_TOKEN
    outputs: candidates (JSON 数组，每项 {app,domain,version,os_version,source_url})
  generate:  # if candidates != '[]'
    needs: scan
    strategy: {fail-fast: false, max-parallel: vars.TESTGEN_MAX_PARALLEL||2,
              matrix: {item: fromJSON(needs.scan.outputs.candidates)}}
    timeout-minutes: 90
    - checkout 本仓 + pip install + 安装 opencode
    - 克隆目标仓
    - python scripts/harness/testgen_generate.py --item toJSON(matrix.item)
      # env: DEEPSEEK_API_KEY, GITCODE_TOKEN, GITCODE_FORK_REPO, GIT_COMMIT_NAME/EMAIL
```

Secrets：`DEEPSEEK_API_KEY`、`GITCODE_TOKEN`、`DISPATCH_TOKEN`。Vars：`GITCODE_FORK_REPO`（跨仓 PR 必填）、`TESTGEN_MAX_PER_ROUND`(10)、`TESTGEN_MAX_PARALLEL`(2)、`TESTGEN_RUNNER_LABELS`、`GIT_COMMIT_NAME/EMAIL`。

## Scan 算法

1. 拉看板全量（约 560 条），失败 → 空列表退出 0
2. 遍历目标仓：domain 列表照 [query_version.py L98](file:///d:/openeuler-docker-autopilot/scripts/harness/query_version.py#L98) 硬编码 `["AI","Bigdata","Storage","Database","Cloud","Distroless","HPC","Others"]`（不存在的跳过）
3. 归一化匹配：`normalize(name)=name.lower()` 后 `[-_.\s]+`→`-`。一对多歧义 → 跳过记 report
4. 缺口判定：`{Domain}/{app}` 下 `tests/test.sh`、`test.sh`、`*/*/test.sh`（任一 version/os）三候选皆无才缺；app 目录无任何 Dockerfile → 跳过记 report
5. 推导最新版本：version 目录取 `sorted()` 最大者，os 目录取其中名称排序最大者
6. 去重三层：`is_exhausted` → `is_done` → `ci_gitcode_api.find_any_pr_by_head_branch(repo, "auto/test-script/{app}", token, open_only=True)`（[L106](file:///d:/openeuler-docker-autopilot/scripts/lib/ci_gitcode_api.py#L106)）
7. 按看板顺序截前 N，写 GITHUB_OUTPUT

## Generate 流程（单 app）

1. 解析 item → TaskSpec(scenario="test-script")，分支 `auto/test-script/{app}`
2. 读取 `{Domain}/{app}/{version}/{os}/Dockerfile`、`meta.yml`；同 domain 挑 1-2 个现有 `tests/test.sh` 作 few-shot 样例路径
3. **build_prompt**（testgen_generate.py 内实现，照 [generation_pipeline.build_role_prompt L371](file:///d:/openeuler-docker-autopilot/scripts/lib/generation_pipeline.py#L371) 结构但不复用其场景一契约）：testgen-creator.md 全文 + Immutable task contract（app/domain/路径/上游 repo_url/样例路径/EXPECTED_VERSION=latest_version）+ 重试时追加静态校验 findings JSON + Final response contract
4. `run_agent(role="testgen_creator", executable=opencode, workspace=目标仓, api_key=DEEPSEEK_API_KEY, required_keys=("success","files_created","test_script_path","summary"), timeout=3600)`
5. **静态校验规则**（kunpeng_test_contract.py，逐条）：
   - `bash -n` 语法（照 `_lint_shell_file` L538 模式）+ 非空 + 可执行位（代码强制 chmod +x）
   - shebang 首行 `#!/bin/bash`
   - 禁 `set -e`（正则 `^\s*set\s+[-a-zA-Z]*e`）
   - 函数名：捕获 `^\s*(function\s+)?(\w+)\s*\(\)`，test 开头的必须匹配 `^test[A-Za-z0-9_]+$`；至少一个用例函数
   - `EXPECTED_VERSION` 存在守卫（`:?`/`-z`/`-n` 之一）
   - 至少一处 `PASS: ` 与 `FAIL: ` 字面量（约定 A 输出）
   - 禁 docker 命令：`\bdocker\s+(build|run|exec|stop|rm|pull|logs)\b`
   - 用 `mktemp` 则必须有 `trap` 清理
   - 全文件禁手动 `exit 0`（提示词要求用 return）
6. findings 非空 → 带报告重跑，最多 2 轮重试；仍败 → `mark_exhausted(app)` 退出 0（不阻塞 matrix）
7. **Dockerfile 空行**（确定性代码追加，非 Agent）：字节级读，CRLF 检测（含 `\r\n` 则补 `\r\n` 否则 `\n`）；先确保结尾恰一个换行再追加空行；结果不变则跳过 commit（幂等）
8. 交付（照 [ci_fix_pipeline.yml L388-493](file:///d:/openeuler-docker-autopilot/.github/workflows/ci_fix_pipeline.yml) 轻量模式）：bot 身份 commit → push `GITCODE_FORK_REPO` → `find_any_pr_by_head_branch` 查重（有 open PR 跳过）→ `create_pull_request(repo, f"{fork_owner}:auto/test-script/{app}", "master", title, body, token)`（[L491](file:///d:/openeuler-docker-autopilot/scripts/lib/ci_gitcode_api.py#L491)）。标题 `test: add functional test for {app}`；正文含看板软件名/repo_url、规范来源链接、校验通过清单、Dockerfile 空行用途说明。成功 `mark_done(app, pr_url)`

## 提示词（testgen-creator.md）

照 testcase-creator.md 骨架：角色定位 → 工作目录（目标仓根）→ 输入上下文表 → 步骤：① 读 Dockerfile/meta 定软件类型与入口；② 从上游 repo_url 推导命令语义（服务型必须在脚本内拉起服务+轮询就绪，因 `--entrypoint bash` 覆盖入口）；③ 写 `{domain}/{app}/tests/test.sh`，KunpengTest 硬规则清单全文内嵌（shebang、禁 set -e、一行 PASS:/FAIL:/FATAL:、test* 函数名、mktemp+trap、禁 docker 命令、禁打印容器日志、timeout/轮询计数控制、不依赖相对路径、只读挂载 + /tmp/eptest 工作目录）；④ JSON 响应契约（success/files_created/test_script_path/summary）。核心约束：只允许在 `{domain}/{app}/tests/` 下创建文件，不得修改任何现有文件（Dockerfile 空行由确定性代码负责）。

## 测试计划

| 文件 | 关键用例 |
|---|---|
| `tests/test_kunpeng_test_contract.py` | 每条规则正/反样本（tmp_path）；findings 结构 |
| `tests/test_testgen_dashboard.py` | patch requests（照 test_ci_gitcode_api 模式）：分页、终止、超时 None |
| `tests/test_testgen_scan.py` | tmp_path 真目录树：归一化匹配、歧义跳过、三候选位置、去重、限量 |
| `tests/test_testgen_generate.py` | mock AgentRunner：一次通过/二轮修复/三轮 exhausted；空行幂等+CRLF；PR 已存在不重建 |
| `tests/test_testgen_workflow.py` | YAML 结构（照 test_ci_fix_workflow.py）：cron/dispatch/matrix/concurrency |
| 修改 `tests/test_agent_runtime.py` | testgen_creator 白名单 |

## 风险与边界

- 看板 API 失败 → 本轮空转；结构断言 items 为 list
- 匹配歧义/无 Dockerfile → 跳过记 report 不猜
- fork 分支已存在无 open PR（被拒）→ force-with-lease 覆盖重提
- CRLF 按字节检测处理；每轮全量重扫天然收敛（已合入 app 不再缺）

## 实施顺序

1. `kunpeng_test_contract.py` + 测试（零外部依赖）
2. `testgen_dashboard.py` + 测试
3. agent_runtime 注册角色 + ci_data 泛化 + `testgen_state.py` + 测试
4. `.github/agents/testgen-creator.md`
5. `testgen_generate.py` + 测试
6. `testgen_scan.py` + 测试
7. workflow yml + 测试
8. 文档场景表更新

## 验证

- 单测：`python -m pytest tests/test_kunpeng_test_contract.py tests/test_testgen_dashboard.py tests/test_testgen_scan.py tests/test_testgen_generate.py tests/test_testgen_workflow.py tests/test_agent_runtime.py -x`
- 手动端到端：`workflow_dispatch` 传 `app=<某缺脚本软件>` 跑单软件路径，确认 scan→generate→PR 全链路（PR 出现在 fork + 目标仓，Dockerfile diff 恰一行空行）
- 看 job summary 中 report（跳过原因、缺口统计）
