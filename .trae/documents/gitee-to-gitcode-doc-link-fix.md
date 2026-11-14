# PR 提交前文档地址检查（gitee → gitcode）

## Context

自动化在提交 PR 时，README / doc 文档里常残留 `gitee.com` 地址，而目标平台是 **gitcode**（`openeuler/openeuler-docker-images` 托管在 gitcode.com）。需要在“提交 PR”前加一步检查，把**本次 PR 新增/追加的文档行**里的 `gitee.com` 自动改写为 `gitcode.com`，让正确地址随 PR 一起提交。

已确认的关键事实：
- 真正会 **commit + push 出 PR** 的只有两条链路：
  1. **候选式新增镜像流程**（场景一）：`create_new_images.yml` → 密封候选补丁 → `deliver-fork-pr` 作业 → `flow.py fork-deliver` → `scripts/lib/pr_delivery.py deliver_validated_candidate` → `scripts/lib/candidate_bundle.py promote_candidate` → `scripts/lib/git_workspace.py TargetWorkspace.commit_candidate`（`git add --all` + `git commit`）→ push → 建 PR。
  2. **PR CI 修复**（场景二）：`scripts/stages/code-fix.py` 第 211 行 `git commit`。
- `upgrade_openeuler_versions.yml` / `upgrade_upstream_versions.yml` 是 **legacy/不可用**：从不 clone 目标仓库、无任何 `git add/commit/push`，`compose-pr` 跑在源码 checkout 上。**无可插入的提交点**，本次不处理（仅在计划中标注）。

约束：场景一要求“存量只读、README 只能末尾追加”，由 `scripts/harness/gate_diff.py` 强制。因此改写**只作用于本次 diff 的新增行**（新增文件=全文），不动存量行，保持“只追加”约束成立。

## 方案

### 1. 新增公共库 `scripts/lib/doc_links.py`

对所有流程共用的纯逻辑 + CLI：

- `_GITEE_RE = re.compile(r'(?<![0-9A-Za-z-])gitee\.com(?![0-9A-Za-z-])', re.I)`，替换为 `gitcode.com`。
  - 命中 `gitee.com`、`www.gitee.com`、`https://gitee.com/...`；不命中 `mygitee.com`、`gitee.com.cn`。
- `is_doc_path(rel_path) -> bool`：basename 以 `readme` 开头（大小写不敏感），或后缀为 `.md` / `.mdx` / `.rst`。
- `rewrite_gitee(text) -> tuple[str, int]`：返回改写后文本与命中次数。
- `_added_line_numbers(repo_dir, base_ref, rel_path) -> set[int] | None`：
  - 文件不在 base（`git cat-file -e <base>:<path>` 失败）→ 返回 `None` 表示“全文都是新增”。
  - 否则解析 `git diff -U0 <base> -- <path>` 的 hunk 头 `@@ -a,b +c,d @@`，收集 `+` 行对应的**新文件行号**集合。
- `fix_added_lines(repo_dir, base_ref, rel_path) -> bool`：只对新增行号做 `rewrite_gitee` 并写回；`None`（新文件）则整文件改写。返回是否有改动。
- `fix_changed_docs(repo_dir, base_ref) -> list[str]`：`git diff --name-only <base>...HEAD` → 过滤 `is_doc_path` → 逐个 `fix_added_lines` → 返回改动文件列表。
- `main()` CLI：`python scripts/lib/doc_links.py --repo <dir> --base <ref>`，改写后打印 `fixed: <path>` 列表，无改动打印 `no gitee links in changed docs`，退出码 0。

### 2. 接入候选式新增镜像流程

文件：`.github/workflows/create_new_images.yml`
- 在 `Enforce final target gates and lint`（约 636–663 行）之后、`Seal immutable candidate bundle`（约 665 行）**之前**，新增一步：
  - 重新读取 `${RUNNER_TEMP}/package-base-sha.txt` 得 `base_sha`；
  - 执行 `"${RUNNER_TEMP}/phase1-venv/bin/python" scripts/lib/doc_links.py --repo "${RUNNER_TEMP}/phase1-target" --base "$base_sha"`。
- 因为候选补丁在 `Seal` 阶段（`flow.py target-create-patch`，约 694 行）生成，在此之前改写即可随补丁被验证、密封、提升、提交、推送。

### 3. 接入 PR CI 修复流程

文件：`scripts/stages/code-fix.py`
- 在 `_cleanup_ai_artifacts(...)` 之后、暂存 `pr_files` 循环（约 172 行）**之前**调用：
  `doc_links.fix_changed_docs(SOURCE_REPO_DIR, f"origin/{env['pr_base_branch']}")`，并 `log_stage('code-fix', ...)` 记录改动文件。
- 改动只落在 `pr_files`（PR 涉及文件）内的文档上，故仍通过“只暂存 pr_files”的既有校验。

### 4. 不处理的部分（明确记录）

- `upgrade_openeuler_versions.yml` / `upgrade_upstream_versions.yml`：legacy、无目标仓库 clone 与 commit/push，无可插入点，本次不改。

### 5. 测试

新增 `tests/test_doc_links.py`（用临时 git 仓库）：
- `rewrite_gitee`：`gitee.com` → `gitcode.com`；`www.gitee.com` → `www.gitcode.com`；不误伤 `mygitee.com` / `gitee.com.cn`；无变化时 count=0。
- `is_doc_path`：`README.md` / `docs/a.md` / `x.rst` 命中；`Dockerfile` / `meta.yml` 不命中。
- 只改新增行：仓库中 README 已有存量 `gitee.com` 行 + 追加一行含 `gitee.com` → 运行后仅追加行被改，存量行保持不变。
- 新文件：整文件改写。
- 修改非文档文件（Dockerfile）不被触碰。

## 待修改/新增文件

- 新增 `scripts/lib/doc_links.py`（公共库 + CLI）
- 修改 `.github/workflows/create_new_images.yml`（密封前插入改写步骤）
- 修改 `scripts/stages/code-fix.py`（暂存前调用改写）
- 新增 `tests/test_doc_links.py`

## 验证

1. `python -m pytest tests/test_doc_links.py -q` 全绿。
2. `python -m pytest tests/test_ci_fix_workflow.py tests/test_gate_diff.py -q` 回归不破。
3. 手动：在本仓库临时 clone 一份，造一个含 `gitee.com` 的 README 追加行，执行
   `python scripts/lib/doc_links.py --repo <clone> --base origin/main`，确认只改新增行、其余不变。
4. 检查 `create_new_images.yml` YAML 可解析（`python -c "import yaml,sys;yaml.safe_load(open(...))"`）。