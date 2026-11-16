#!/usr/bin/env python3
"""
Stage: 场景二单应用升级（upgrade_apply）

在目标仓完整克隆上，对一个应用执行：

1. 切出升级分支 ``auto/version-update/<app>/<ver>-<oe_tag>``；
2. AI 结合看板证据包与上游源码生成新版本 Dockerfile（**不做版本串机械替换**）；
3. 若该应用缺功能测试脚本，复用场景四的 ``generate_test_script`` 生成
   ``tests/test.sh``（**只写工作树，不提交、不建 PR**）；生成失败不阻断升级；
4. 确定性复制目录 + 写入 AI 生成的 Dockerfile + README/doc 版本更新 +
   meta.yml 追加（:mod:`scripts.lib.version_upgrade`）；
5. commit，推送到 fork，并把上游证据写入 ``$RUNNER_TEMP/task-spec.json``
   供双架构验证复用。

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
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

from scripts.lib import ai_provider, upstream_evidence, version_upgrade  # noqa: E402
from scripts.lib.agent_runtime import run_agent  # noqa: E402
from scripts.lib.stage_common import (  # noqa: E402
    agent_prompt_file,
    log_stage,
    normalize_repo,
)
from scripts.lib.task_spec import TaskSpec, _os_tag  # noqa: E402

DEFAULT_SOURCE_REPO_DIR = os.path.join(PROJECT_ROOT, "source-repo")
DEFAULT_TARGET_REPO = "openeuler/openeuler-docker-images"
DEFAULT_TARGET_BRANCH = "master"

DOCKERFILE_AGENT_ROLE = "upgrade_creator"
DOCKERFILE_REQUIRED_KEYS = ("success", "dockerfile", "summary")
# 首次生成 + 最多 1 轮按校验问题重写。
MAX_DOCKERFILE_ROUNDS = 2
# prepare job 还要补测试与推送，单轮生成不能占满整个 job 预算。
DOCKERFILE_AGENT_TIMEOUT_SECONDS = 1800


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


def build_dockerfile_prompt(
    *,
    app: str,
    domain: str,
    plan: version_upgrade.UpgradePlan,
    item: dict,
    old_dockerfile: str,
    findings: list[str] | None = None,
) -> str:
    """组装升级 Dockerfile 生成提示：角色规则 + 任务契约 + 旧文件 + 证据包。"""
    prompt = Path(agent_prompt_file("upgrade-creator")).read_text(encoding="utf-8")
    evidence = item.get("evidence") or {}
    contract = {
        "app": app,
        "domain": domain,
        "old_version": plan.old_version,
        "new_version": str(item["version"]),
        "os_version": plan.os_version,
        "dockerfile_path": (
            f"{domain}/{app}/{plan.old_version}/{plan.os_version}/Dockerfile"
        ),
        "source_url": str(item.get("source_url") or ""),
        "tag": evidence.get("tag"),
        "tag_url": evidence.get("tag_url"),
        "commit_sha": evidence.get("commit_sha"),
        "output_field": "dockerfile",
    }
    prompt += (
        "\n\n## Immutable task contract\n\n"
        + json.dumps(contract, indent=2, ensure_ascii=False)
        + "\n\n## Current Dockerfile (previous version)\n\n```dockerfile\n"
        + old_dockerfile.rstrip()
        + "\n```\n"
    )
    prompt += "\n\n" + upstream_evidence.render_prompt(evidence).strip() + "\n"
    if findings:
        prompt += (
            "\n## Validation report to resolve\n\n"
            "上一轮生成的 Dockerfile 未通过确定性校验，逐条修正后重新生成完整文件：\n"
            + json.dumps(findings, indent=2, ensure_ascii=False)
            + "\n"
        )
    prompt += (
        "\n## Final response contract\n\n"
        "最终响应必须恰好是一个 JSON 对象，包含以下键："
        "success(bool)、dockerfile(str，完整 Dockerfile 文本)、"
        "summary(str)、error(null 或 str)。"
        "不得修改工作区文件；只返回 JSON。\n"
    )
    return prompt


def _reset_workspace(repo_dir: Path) -> None:
    """清掉 Agent 可能写下的改动；Dockerfile 只通过 JSON 返回。"""
    _git(repo_dir, "checkout", "--", ".", check=False)
    _git(repo_dir, "clean", "-fd", check=False)


CPU_TORCH_RUN = (
    "RUN pip install --retries 10 --timeout 120 'torch<=2.9.1' "
    "torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu"
)


def _needs_cpu_torch(requirements: str) -> bool:
    text = requirements.lower()
    return "sentence-transformers" in text or re.search(
        r"(?m)^\s*torch\b", text
    ) is not None


def ensure_cpu_torch(dockerfile: str, requirements: str) -> str:
    """requirements 依赖 torch 时，在安装 requirements 前补一条 CPU 版 torch。

    默认 PyPI 的 torch 会拖入数 GB 的 CUDA/nvidia 依赖，自托管 Runner 常因
    磁盘或镜像站超时构建失败；上游官方 Dockerfile 也是先装 CPU 版。
    """
    if not _needs_cpu_torch(requirements):
        return dockerfile
    if "download.pytorch.org/whl/cpu" in dockerfile:
        return dockerfile
    lines = dockerfile.splitlines()
    for index, line in enumerate(lines):
        if not line.lstrip().startswith("RUN"):
            continue
        block_end = index
        while (
            block_end < len(lines)
            and lines[block_end].rstrip().endswith("\\")
        ):
            block_end += 1
        block = "\n".join(lines[index : block_end + 1])
        if "requirements" in block and "pip install" in block:
            lines[index:index] = [CPU_TORCH_RUN, ""]
            suffix = "\n" if dockerfile.endswith("\n") else ""
            return "\n".join(lines) + suffix
    return dockerfile


def fetch_upstream_requirements(item: dict) -> str:
    """读取上游 tag 的 backend/requirements.txt；失败只返回空串（不阻断）。"""
    source_url = str(item.get("source_url") or "")
    parsed = urlparse(source_url)
    if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
        return ""
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return ""
    owner, repo = parts[0], parts[1].removesuffix(".git")
    evidence = item.get("evidence") or {}
    refs = [
        str(evidence.get("tag") or "").strip(),
        f"v{item.get('version')}",
        str(item.get("version") or ""),
    ]
    for ref in dict.fromkeys(refs):
        if not ref:
            continue
        url = (
            f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}"
            "/backend/requirements.txt"
        )
        try:
            with urllib.request.urlopen(url, timeout=20) as response:
                return response.read().decode("utf-8", errors="replace")
        except OSError:
            continue
    return ""


def _generate_dockerfile(
    *,
    repo_dir: Path,
    app: str,
    domain: str,
    plan: version_upgrade.UpgradePlan,
    item: dict,
) -> str:
    """让 AI 结合证据包生成新版本 Dockerfile；失败即终止，不回落机械替换。"""
    api_key = ai_provider.api_key()
    executable = os.environ.get("OPENCODE_BIN") or shutil.which("opencode")
    if not api_key or not executable:
        raise version_upgrade.UpgradeError(
            f"{app}: 缺少 AI 凭证/opencode，无法生成 Dockerfile"
            "（场景二禁止机械替换版本串）"
        )

    old_dockerfile = (plan.src_dir / "Dockerfile").read_text(encoding="utf-8")
    findings: list[str] = []
    for round_no in range(MAX_DOCKERFILE_ROUNDS):
        prompt = build_dockerfile_prompt(
            app=app,
            domain=domain,
            plan=plan,
            item=item,
            old_dockerfile=old_dockerfile,
            findings=findings or None,
        )
        log_stage(
            "upgrade-apply",
            f"{app}: dockerfile agent round {round_no + 1}",
        )
        try:
            result = run_agent(
                executable=Path(executable),
                role=DOCKERFILE_AGENT_ROLE,
                prompt=prompt,
                workspace=repo_dir,
                api_key=api_key,
                required_keys=DOCKERFILE_REQUIRED_KEYS,
                timeout=DOCKERFILE_AGENT_TIMEOUT_SECONDS,
            )
        finally:
            _reset_workspace(repo_dir)

        payload = result.payload
        if not bool(payload.get("success")):
            findings = [str(payload.get("error") or "Agent 报告生成失败")]
        else:
            candidate = payload.get("dockerfile")
            if not isinstance(candidate, str) or not candidate.strip():
                findings = ["Agent 未返回非空的 dockerfile 字符串"]
            else:
                findings = version_upgrade.check_dockerfile(
                    candidate, str(item["version"])
                )
                if not findings:
                    guarded = candidate
                    if "requirements" in candidate and "pip install" in candidate:
                        guarded = ensure_cpu_torch(
                            candidate, fetch_upstream_requirements(item)
                        )
                    if guarded != candidate:
                        log_stage(
                            "upgrade-apply",
                            f"{app}: 已补充 CPU 版 torch 安装（避免 CUDA 依赖）",
                        )
                    return guarded
        log_stage("upgrade-apply", f"{app}: dockerfile findings={findings}")

    raise version_upgrade.UpgradeError(
        f"{app}: AI 生成的 Dockerfile 未通过校验：{'；'.join(findings)}"
    )


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
    dockerfile_text = _generate_dockerfile(
        repo_dir=repo_dir, app=app, domain=domain, plan=plan, item=item
    )
    test_status = _ensure_test_script(
        repo_dir=repo_dir, app=app, domain=domain, plan=plan, item=item
    )
    changed = version_upgrade.apply_upgrade(
        app_dir, plan, new_version, dockerfile_text
    )

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
