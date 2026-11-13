#!/usr/bin/env python3
"""
Stage: 场景二单应用升级（upgrade_apply）

在目标仓完整克隆上，对一个应用执行：

1. 切出升级分支 ``auto/version-update/<app>/<ver>-<oe_tag>``；
2. 若该应用缺功能测试脚本，复用场景四的 ``generate_test_script`` 生成
   ``tests/test.sh``（**只写工作树，不提交、不建 PR**）；生成失败不阻断升级；
3. 确定性复制 + 版本串替换 + meta.yml 追加（:mod:`scripts.lib.version_upgrade`）；
4. commit，推送到 fork，并把 ``self-probe`` 之外的上游证据写入
   ``$RUNNER_TEMP/task-spec.json`` 供双架构验证复用。

输入: --item '<json>'（upgrade_scan 的产物）
环境: GITCODE_TOKEN, GITCODE_FORK_REPO(可选), SOURCE_REPO_DIR, TARGET_REPO,
      TARGET_BRANCH, GIT_COMMIT_NAME/EMAIL, AI_API_KEY, OPENCODE_BIN
输出: GITHUB_OUTPUT 写 branch/test_status；状态文件 task-spec.json
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

from scripts.lib import ai_provider, upstream_evidence, version_upgrade  # noqa: E402
from scripts.lib.stage_common import log_stage, normalize_repo  # noqa: E402
from scripts.lib.task_spec import TaskSpec, _os_tag  # noqa: E402

DEFAULT_SOURCE_REPO_DIR = os.path.join(PROJECT_ROOT, "source-repo")
DEFAULT_TARGET_REPO = "openeuler/openeuler-docker-images"
DEFAULT_TARGET_BRANCH = "master"


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _redact(text: str) -> str:
    return re.sub(r"oauth2:[^@]+@", "oauth2:***@", text)


def _git(repo_dir: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    completed = subprocess.run(
        ["git", "-C", str(repo_dir), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if check and completed.returncode != 0:
        detail = _redact((completed.stderr or completed.stdout or "").strip())
        raise RuntimeError(
            f"git {_redact(' '.join(args))} failed ({completed.returncode}): {detail[:2000]}"
        )
    return completed


def _emit_output(**values: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT", "")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def _ensure_test_script(
    *,
    repo_dir: Path,
    app: str,
    domain: str,
    plan: version_upgrade.UpgradePlan,
    item: dict,
) -> str:
    """缺测试就生成；返回 added / existing / pending。"""
    from scripts.harness import testgen_scan
    from scripts.harness.testgen_generate import generate_test_script

    app_dir = repo_dir / domain / app
    if testgen_scan.has_any_test_script(app_dir):
        return "existing"

    api_key = ai_provider.api_key()
    executable = os.environ.get("OPENCODE_BIN") or shutil.which("opencode")
    if not api_key or not executable:
        log_stage("upgrade-apply", f"{app}: 缺少 AI 凭证/opencode，跳过补测试")
        return "pending"

    findings = generate_test_script(
        repo_dir=repo_dir,
        app=app,
        domain=domain,
        dockerfile_rel=f"{domain}/{app}/{plan.old_version}/{plan.os_version}/Dockerfile",
        source_url=str(item.get("source_url") or ""),
        latest_version=str(item["version"]),
        api_key=api_key,
        executable=Path(executable),
        extra_context=upstream_evidence.render_prompt(item.get("evidence")),
    )
    if findings:
        detail = "; ".join(f"{f['code']}: {f['message']}" for f in findings)
        log_stage("upgrade-apply", f"{app}: 测试脚本生成未通过（非阻断）: {detail}")
        return "pending"
    return "added"


def run(item: dict, *, task_spec_out: Path) -> int:
    app = str(item["app"])
    domain = str(item["domain"])
    new_version = str(item["version"])

    repo_dir = Path(_env("SOURCE_REPO_DIR", DEFAULT_SOURCE_REPO_DIR))
    if not repo_dir.is_dir():
        raise SystemExit(f"source repo not found: {repo_dir}")
    app_dir = repo_dir / domain / app
    if not app_dir.is_dir():
        raise SystemExit(f"{app}: 目标仓里没有 {domain}/{app}")

    plan = version_upgrade.plan_upgrade(app_dir)
    branch = f"auto/version-update/{app}/{new_version}-{_os_tag(plan.os_version)}"
    base_branch = _env("TARGET_BRANCH", DEFAULT_TARGET_BRANCH)

    checkout = _git(repo_dir, "checkout", "-B", branch, f"origin/{base_branch}", check=False)
    if checkout.returncode != 0:
        _git(repo_dir, "checkout", "-B", branch, base_branch, check=False)

    log_stage(
        "upgrade-apply",
        f"{app}: {plan.old_version} -> {new_version} (os={plan.os_version})",
    )
    test_status = _ensure_test_script(
        repo_dir=repo_dir, app=app, domain=domain, plan=plan, item=item
    )
    changed = version_upgrade.apply_upgrade(app_dir, plan, new_version)

    _git(repo_dir, "add", "-A", str(app_dir.relative_to(repo_dir)))
    commit_name = _env("GIT_COMMIT_NAME", "github-actions[bot]")
    commit_email = _env("GIT_COMMIT_EMAIL", "github-actions[bot]@users.noreply.github.com")
    _git(
        repo_dir,
        "-c", f"user.name={commit_name}",
        "-c", f"user.email={commit_email}",
        "commit", "-m", f"feat: upgrade {app} to {new_version}",
    )

    token = _env("GITCODE_TOKEN")
    if not token:
        raise SystemExit("GITCODE_TOKEN is required to push the upgrade branch")
    target_repo = _env("TARGET_REPO", DEFAULT_TARGET_REPO)
    push_repo = normalize_repo(_env("GITCODE_FORK_REPO")) or target_repo
    push_url = f"https://oauth2:{token}@gitcode.com/{push_repo}.git"
    _git(repo_dir, "push", push_url, f"+refs/heads/{branch}:refs/heads/{branch}")
    log_stage("upgrade-apply", f"{app}: pushed {branch} -> {push_repo}")

    task = TaskSpec(
        app=app,
        version=new_version,
        os_version=plan.os_version,
        domain=domain,
        source_url=str(item.get("source_url") or ""),
        scenario="version-update",
    )
    task_spec_out.parent.mkdir(parents=True, exist_ok=True)
    payload = json.loads(task.to_json())
    payload["evidence"] = item.get("evidence") or {}
    task_spec_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    _emit_output(branch=branch, test_status=test_status, push_repo=push_repo)
    log_stage(
        "upgrade-apply",
        f"{app}: done changed={[str(p.relative_to(repo_dir)) for p in changed]} "
        f"tests={test_status}",
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--item", required=True, help="upgrade_scan 产出的单条 item JSON")
    parser.add_argument(
        "--task-spec-out",
        default=os.path.join(os.environ.get("RUNNER_TEMP", PROJECT_ROOT), "task-spec.json"),
    )
    args = parser.parse_args()
    return run(json.loads(args.item), task_spec_out=Path(args.task_spec_out))


if __name__ == "__main__":
    sys.exit(main())
