#!/usr/bin/env python3
"""
Stage: 场景二失败修复（upgrade_repair）

失败运行留下的分支不重新生成：本脚本只做

1. 从失败运行的 ``task-spec.json`` 还原任务契约（app/version/os_version/source_url/evidence）；
2. 拉取**已存在**的升级分支，读取分支上的 Dockerfile 与 ``tests/test.sh``；
3. 把双架构 evidence（失败项 + 诊断日志尾部）和人工 ``--instructions`` 交给
   ``upgrade_creator`` Agent，**在容器里复现失败指令并当场修复**，返回修复后的
   完整文件（与生成阶段共用同一套容器验证流程）；
4. 确定性校验后覆盖分支上的文件，提交并推回同一分支。

分支不存在时直接报错——repair 只修复已有分支，不重新生成。

输入: --task-spec（失败运行的 task-spec.json）
      --evidence-dir（可重复；失败运行上传的 evidence 目录，缺失时按空处理）
      --instructions（人工给 AI 的修复说明，可为空）
      --task-spec-out
环境: GITCODE_TOKEN, GITCODE_FORK_REPO(可选), SOURCE_REPO_DIR, TARGET_REPO,
      TARGET_BRANCH, GIT_COMMIT_NAME/EMAIL, AI_API_KEY, OPENCODE_BIN
输出: GITHUB_OUTPUT 写 branch/test_status/push_repo/item_json
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

from scripts.harness.upgrade_apply import (  # noqa: E402
    DOCKER_SHIM_DIR,
    _emit_output,
    _env,
    _git,
    _reset_workspace,
    container_name,
    container_verification_section,
    read_agent_file,
    session_dir,
)
from scripts.lib import ai_provider, build_runner, version_upgrade  # noqa: E402
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

REPAIR_AGENT_ROLE = "upgrade_creator"
REPAIR_REQUIRED_KEYS = ("success", "dockerfile", "summary")
# 修复通常只有一轮；留一轮用于消化确定性校验问题。
MAX_REPAIR_ROUNDS = 2
# 修复同样要在容器里复现并跑通失败指令，与生成阶段共用 90 分钟预算。
REPAIR_AGENT_TIMEOUT_SECONDS = 5400

_LOG_TAIL_LIMIT = 4000
_LOG_ENTRY_LIMIT = 12
_DETAIL_LIMIT = 2000


def _redact(text: str) -> str:
    return re.sub(r"oauth2:[^@]+@", "oauth2:***@", text)


def _tail(path: Path, limit: int = _LOG_TAIL_LIMIT) -> str:
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > limit:
                handle.seek(size - limit)
            return handle.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _trim_details(details: object) -> object:
    """失败详情可能带很长输出，截断后再放进提示。"""
    if not details:
        return {}
    try:
        text = json.dumps(details, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        text = str(details)
    if len(text) <= _DETAIL_LIMIT:
        return details
    return text[:_DETAIL_LIMIT] + "...[truncated]"


def collect_evidence(evidence_dirs: list[Path]) -> dict[str, object]:
    """把失败运行的 evidence 目录整理成提示可用的摘要。"""
    failures: list[dict[str, object]] = []
    reports: list[str] = []
    logs: list[dict[str, str]] = []
    for directory in evidence_dirs:
        root = Path(directory)
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix == ".json":
                try:
                    report = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if not isinstance(report, dict):
                    continue
                architecture = str(
                    report.get("architecture") or path.parent.name or "unknown"
                )
                status = str(report.get("status") or "missing")
                reports.append(
                    f"{path.name}: status={status} architecture={architecture}"
                )
                if status == "passed":
                    continue
                entries = report.get("failures")
                if not isinstance(entries, list) or not entries:
                    entries = [
                        {
                            "check": report.get("failed_stage") or "unknown",
                            "stage": report.get("failed_stage") or "unknown",
                            "failure": report.get("failure") or "validation failed",
                            "failure_details": report.get("failure_details") or {},
                        }
                    ]
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    failures.append(
                        {
                            "architecture": architecture,
                            "stage": str(entry.get("stage") or ""),
                            "check": str(entry.get("check") or ""),
                            "failure": str(entry.get("failure") or "")[:_DETAIL_LIMIT],
                            "details": _trim_details(entry.get("failure_details")),
                        }
                    )
            elif path.suffix == ".log":
                logs.append({"path": path.name, "tail": _tail(path)})

    if not failures:
        failures.append(
            {
                "architecture": "unknown",
                "stage": "unknown",
                "check": "unknown",
                "failure": (
                    "失败运行的 evidence 不可用或不含失败项；"
                    "请按人工修复说明与分支上的当前文件做最小修复。"
                ),
                "details": {},
            }
        )
    return {"reports": reports, "failures": failures, "logs": logs[:_LOG_ENTRY_LIMIT]}


def build_repair_prompt(
    *,
    task: TaskSpec,
    dockerfile_text: str,
    test_script_text: str,
    evidence: dict[str, object],
    instructions: str,
    findings: list[str] | None = None,
    session: dict | None = None,
) -> str:
    """组装修复提示：角色规则 + 分支现状 + 失败证据 + 人工说明。"""
    prompt = Path(agent_prompt_file("upgrade-creator")).read_text(encoding="utf-8")
    contract = {
        "mode": "repair",
        "app": task.app,
        "domain": task.domain,
        "version": task.version,
        "os_version": task.os_version,
        "dockerfile_path": (
            f"{task.domain}/{task.app}/{task.version}/{task.os_version}/Dockerfile"
        ),
        "test_script_path": f"{task.domain}/{task.app}/tests/test.sh",
        "source_url": task.source_url,
        "output_fields": ["dockerfile", "test_script"],
    }
    reports = evidence.get("reports") or ["（未找到 evidence 报告）"]
    prompt += (
        "\n\n## Repair mode\n\n"
        "这是对**已有升级分支**的失败修复，不是重新生成升级：禁止新建或切换分支，"
        "禁止改动与失败无关的文件。\n"
        "- `dockerfile` 必填，返回修复后的完整 Dockerfile 文本；\n"
        "- 需要调整功能测试时返回修复后的完整 `tests/test.sh` 文本，否则 `test_script` 为 `null`。\n"
        "\n## Immutable repair contract\n\n"
        + json.dumps(contract, indent=2, ensure_ascii=False)
        + "\n\n## Current Dockerfile on the upgrade branch\n\n```dockerfile\n"
        + dockerfile_text.rstrip()
        + "\n```\n"
    )
    if test_script_text.strip():
        prompt += (
            "\n## Current tests/test.sh on the upgrade branch\n\n```bash\n"
            + test_script_text.rstrip()
            + "\n```\n"
        )
    else:
        prompt += "\n## Current tests/test.sh on the upgrade branch\n\n（该分支没有 tests/test.sh）\n"
    prompt += (
        "\n## Validation evidence from the failed run\n\n"
        + json.dumps(
            {
                "reports": reports,
                "failures": evidence.get("failures") or [],
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )
    logs = evidence.get("logs") or []
    if logs:
        prompt += "\n## Diagnostic log tails\n"
        for log in logs:
            prompt += (
                f"\n### {log.get('path')}\n\n```text\n"
                + str(log.get("tail") or "").rstrip()
                + "\n```\n"
            )
    prompt += (
        "\n## Operator instructions\n\n"
        + (instructions.strip() or "（未提供；请按失败证据做最小修复）")
        + "\n"
    )
    if session:
        prompt += container_verification_section(
            staging=Path(session["staging"]),
            container=str(session["container"]),
            output_dockerfile=Path(session["output_dockerfile"]),
            build_log=Path(session["build_log"]),
            arch=str(session.get("arch") or "x86_64"),
            mode="repair",
        )
    if findings:
        prompt += (
            "\n## Findings to resolve\n\n"
            "上一轮修复未通过确定性校验，逐条修正后重新返回完整文件：\n"
            + json.dumps(findings, indent=2, ensure_ascii=False)
            + "\n"
        )
    prompt += (
        "\n## Final response contract\n\n"
        "最终响应必须恰好是一个 JSON 对象，包含以下键："
        "success(bool)、dockerfile(str，完整 Dockerfile 文本)、"
        "test_script(str 或 null)、summary(str)、error(null 或 str)。"
        "不得修改工作区文件；只返回 JSON。\n"
    )
    return prompt


def _validate_test_script(script: str) -> list[str]:
    """与目标仓测试契约保持一致的轻量校验。"""
    findings: list[str] = []
    stripped = script.strip()
    if not stripped:
        findings.append("test_script 为空")
        return findings
    if not stripped.startswith("#!"):
        findings.append("test_script 缺少 shebang")
    bash = shutil.which("bash")
    if bash:
        completed = subprocess.run(
            [bash, "-n"],
            input=script,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            findings.append(f"test_script 不是合法 Bash：{detail[:500]}")
    return findings


def _repair_files(
    *,
    repo_dir: Path,
    task: TaskSpec,
    dockerfile_text: str,
    test_script_text: str,
    evidence: dict[str, object],
    instructions: str,
    session: dict,
) -> tuple[str, str | None]:
    """让 Agent 在容器里复现并修复失败指令；失败即终止，不静默保留原文件。"""
    api_key = ai_provider.api_key()
    executable = os.environ.get("OPENCODE_BIN") or shutil.which("opencode")
    if not api_key or not executable:
        raise version_upgrade.UpgradeError(
            f"{task.app}: 缺少 AI 凭证/opencode，无法执行修复"
        )

    output_dockerfile = Path(session["output_dockerfile"])
    findings: list[str] = []
    for round_no in range(MAX_REPAIR_ROUNDS):
        prompt = build_repair_prompt(
            task=task,
            dockerfile_text=dockerfile_text,
            test_script_text=test_script_text,
            evidence=evidence,
            instructions=instructions,
            findings=findings or None,
            session=session,
        )
        log_stage("upgrade-repair", f"{task.app}: repair agent round {round_no + 1}")
        agent_error: Exception | None = None
        result = None
        try:
            result = run_agent(
                executable=Path(executable),
                role=REPAIR_AGENT_ROLE,
                prompt=prompt,
                workspace=repo_dir,
                api_key=api_key,
                required_keys=REPAIR_REQUIRED_KEYS,
                timeout=REPAIR_AGENT_TIMEOUT_SECONDS,
            )
        except Exception as error:  # noqa: BLE001 - 落盘产物优先于退出码
            agent_error = error
            log_stage(
                "upgrade-repair",
                f"{task.app}: agent 异常 {type(error).__name__}: {error}",
            )
        finally:
            written = read_agent_file(output_dockerfile)
            _reset_workspace(repo_dir)

        payload = result.payload if result is not None else {}
        candidate = written or payload.get("dockerfile")
        if not isinstance(candidate, str) or not candidate.strip():
            findings = [
                str(payload.get("error") or "")
                or (
                    f"Agent 异常且未落盘 Dockerfile："
                    f"{type(agent_error).__name__}: {agent_error}"
                    if agent_error is not None
                    else "Agent 未返回非空的 dockerfile 字符串"
                )
            ]
            log_stage("upgrade-repair", f"{task.app}: findings={findings}")
            continue
        if agent_error is not None:
            log_stage(
                "upgrade-repair",
                f"{task.app}: agent 未正常结束，但容器内已落盘 Dockerfile，继续采用",
            )
        findings = version_upgrade.check_dockerfile(candidate, task.version)
        script = payload.get("test_script")
        repaired_script: str | None = None
        if isinstance(script, str) and script.strip():
            findings += _validate_test_script(script)
            repaired_script = script
        if not findings:
            return candidate, repaired_script
        log_stage("upgrade-repair", f"{task.app}: findings={findings}")

    raise version_upgrade.UpgradeError(
        f"{task.app}: 修复未通过校验：{'；'.join(findings)}"
    )


def _test_status(repo_dir: Path, test_rel: str) -> str:
    """按分支相对目标分支的差异判定 PR 文案用的测试状态。"""
    if not (repo_dir / test_rel).is_file():
        return "pending"
    base = _env("TARGET_BRANCH", DEFAULT_TARGET_BRANCH)
    diff = _git(
        repo_dir,
        "diff",
        "--name-status",
        f"origin/{base}...HEAD",
        "--",
        test_rel,
        check=False,
    )
    if diff.returncode == 0 and re.search(r"^A\t", diff.stdout or "", re.MULTILINE):
        return "added"
    return "existing"


def run(
    *,
    task_spec_path: Path,
    evidence_dirs: list[Path],
    instructions: str,
    task_spec_out: Path,
    branch_override: str = "",
) -> int:
    raw = json.loads(Path(task_spec_path).read_text(encoding="utf-8"))
    task = TaskSpec.from_json(json.dumps(raw))
    evidence_payload = raw.get("evidence") or {}
    item = {
        "app": task.app,
        "domain": task.domain,
        "version": task.version,
        "os_version": task.os_version,
        "source_url": task.source_url,
        "evidence": evidence_payload,
    }

    repo_dir = Path(_env("SOURCE_REPO_DIR", DEFAULT_SOURCE_REPO_DIR))
    if not repo_dir.is_dir():
        raise SystemExit(f"source repo not found: {repo_dir}")

    token = _env("GITCODE_TOKEN")
    if not token:
        raise SystemExit("GITCODE_TOKEN is required to repair the upgrade branch")
    target_repo = _env("TARGET_REPO", DEFAULT_TARGET_REPO)
    push_repo = normalize_repo(_env("GITCODE_FORK_REPO")) or target_repo
    push_url = f"https://oauth2:{token}@gitcode.com/{push_repo}.git"

    branch = branch_override.strip() or (
        f"auto/version-update/{task.app}/{task.version}-{_os_tag(task.os_version)}"
    )
    fetched = _git(
        repo_dir,
        "fetch",
        push_url,
        f"+refs/heads/{branch}:refs/remotes/upgrade/{branch}",
        check=False,
    )
    if fetched.returncode != 0:
        detail = _redact((fetched.stderr or fetched.stdout or "").strip())
        raise SystemExit(
            f"{task.app}: 拉取已有升级分支 {branch} 失败（repair 不重新生成分支）："
            f"{detail[:1000]}"
        )
    _git(repo_dir, "checkout", "-B", branch, f"refs/remotes/upgrade/{branch}")

    app_rel = f"{task.domain}/{task.app}"
    dockerfile_rel = f"{app_rel}/{task.version}/{task.os_version}/Dockerfile"
    test_rel = f"{app_rel}/tests/test.sh"
    dockerfile_path = repo_dir / dockerfile_rel
    if not dockerfile_path.is_file():
        raise SystemExit(f"{task.app}: 分支 {branch} 上找不到 {dockerfile_rel}")
    dockerfile_text = dockerfile_path.read_text(encoding="utf-8")
    test_path = repo_dir / test_rel
    test_script_text = (
        test_path.read_text(encoding="utf-8") if test_path.is_file() else ""
    )

    evidence = collect_evidence(evidence_dirs)
    log_stage(
        "upgrade-repair",
        f"{task.app}: repair {branch} failures={len(evidence['failures'])} "
        f"logs={len(evidence['logs'])}",
    )

    # 修复也在容器里做：把版本目录复制成 staging 构建上下文，Agent 在其中
    # 复现失败指令并当场修，和 CI 失败修复链路同一套做法。
    root = session_dir(repo_dir, task.app, task.version, task.os_version, "repair")
    staging = root / "context"
    shutil.copytree(dockerfile_path.parent, staging)
    session = {
        "staging": staging,
        "container": container_name(f"{task.app}-repair"),
        "output_dockerfile": root / "final-Dockerfile",
        "build_log": root / "build-log.md",
        "arch": "x86_64",
    }
    label = build_runner.activate_docker_shim(DOCKER_SHIM_DIR)
    try:
        repaired_dockerfile, repaired_test = _repair_files(
            repo_dir=repo_dir,
            task=task,
            dockerfile_text=dockerfile_text,
            test_script_text=test_script_text,
            evidence=evidence,
            instructions=instructions,
            session=session,
        )
    finally:
        build_runner.docker_rm(str(session["container"]))
        build_runner.docker_rm_by_label(label)
        build_runner.docker_rm_images_by_label(label)

    repaired_dockerfile = version_upgrade.ensure_repo_cache_cleaned(
        repaired_dockerfile
    )
    dockerfile_path.write_text(repaired_dockerfile.rstrip() + "\n", encoding="utf-8")
    if repaired_test is not None:
        test_path.parent.mkdir(parents=True, exist_ok=True)
        test_path.write_text(repaired_test.rstrip() + "\n", encoding="utf-8")
        test_path.chmod(0o755)

    _git(repo_dir, "add", "-A", app_rel)
    if not _git(
        repo_dir, "status", "--porcelain", "--", app_rel, check=False
    ).stdout.strip():
        raise SystemExit(f"{task.app}: 修复没有产生任何文件改动，未提交")

    commit_name = _env("GIT_COMMIT_NAME", "github-actions[bot]")
    commit_email = _env(
        "GIT_COMMIT_EMAIL", "github-actions[bot]@users.noreply.github.com"
    )
    _git(
        repo_dir,
        "-c", f"user.name={commit_name}",
        "-c", f"user.email={commit_email}",
        "commit", "-m", f"fix: repair {task.app} {task.version} upgrade branch",
    )
    _git(repo_dir, "push", push_url, f"+refs/heads/{branch}:refs/heads/{branch}")
    log_stage("upgrade-repair", f"{task.app}: pushed {branch} -> {push_repo}")

    task_spec_out.parent.mkdir(parents=True, exist_ok=True)
    payload = json.loads(task.to_json())
    payload["evidence"] = evidence_payload
    task_spec_out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    _emit_output(
        branch=branch,
        test_status=_test_status(repo_dir, test_rel),
        push_repo=push_repo,
        item_json=json.dumps(item, ensure_ascii=False, separators=(",", ":")),
    )
    log_stage("upgrade-repair", f"{task.app}: done")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--task-spec", required=True, help="失败运行产出的 task-spec.json"
    )
    parser.add_argument(
        "--evidence-dir",
        action="append",
        default=[],
        help="失败运行的 evidence 目录，可重复",
    )
    parser.add_argument("--instructions", default="", help="人工给 AI 的修复说明")
    parser.add_argument(
        "--branch", default="", help="已有升级分支（留空按 task spec 推导）"
    )
    parser.add_argument(
        "--task-spec-out",
        default=os.path.join(
            os.environ.get("RUNNER_TEMP", PROJECT_ROOT), "task-spec.json"
        ),
    )
    args = parser.parse_args()
    return run(
        task_spec_path=Path(args.task_spec),
        evidence_dirs=[Path(path) for path in args.evidence_dir],
        instructions=args.instructions,
        task_spec_out=Path(args.task_spec_out),
        branch_override=args.branch,
    )


if __name__ == "__main__":
    sys.exit(main())
