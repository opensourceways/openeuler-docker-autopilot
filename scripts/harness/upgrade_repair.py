#!/usr/bin/env python3
"""
Stage: 场景二失败修复 / 双架构重放（upgrade_repair）

失败运行留下的分支不重新生成：本脚本只做

1. 从失败运行的 ``task-spec.json`` 还原任务契约（app/version/os_version/source_url/evidence）；
2. 拉取**已存在**的升级分支，读取分支上的 Dockerfile 与 ``tests/test.sh``；
3. 把双架构 evidence（失败项 + 诊断日志尾部）和人工 ``--instructions`` 交给
   ``upgrade_creator`` Agent，**在容器里复现失败指令并当场修复**，返回修复后的
   完整文件（与生成阶段共用同一套容器验证流程）；
4. 确定性校验后覆盖分支上的文件，提交并推回同一分支。

``--mode replay --arch aarch64`` 是生成阶段的双架构重放：不依赖失败 evidence，
只把分支上已有的 Dockerfile 在 arm64 容器里完整重放一遍，修掉架构相关问题；
没有改动时正常退出、不产生空提交。

分支不存在时直接报错——repair 只修复已有分支，不重新生成。

输入: --task-spec（生成/失败运行的 task-spec.json）
      --evidence-dir（可重复；失败运行上传的 evidence 目录，缺失时按空处理）
      --instructions（人工给 AI 的修复说明，可为空）
      --mode（repair=失败修复；replay=双架构重放，默认 repair）
      --arch（x86_64 / aarch64；留空按当前 runner 自动识别）
      --task-spec-out
环境: GITCODE_TOKEN, GITCODE_FORK_REPO(可选), SOURCE_REPO_DIR, TARGET_REPO,
      TARGET_BRANCH, GIT_COMMIT_NAME/EMAIL, AI_API_KEY, OPENCODE_BIN
输出: GITHUB_OUTPUT 写 branch/test_status/push_repo/item_json
"""

import argparse
import json
import os
import platform
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
from scripts.lib import (  # noqa: E402
    ai_provider,
    app_notes,
    build_runner,
    supporting_files,
    upstream_evidence,
    version_upgrade,
)
from scripts.lib.agent_policy import build_policy  # noqa: E402
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
# 修复同样要在容器里复现并跑通失败指令；默认 90 分钟，可按应用覆盖（app_notes）。

_LOG_TAIL_LIMIT = 4000
_LOG_ENTRY_LIMIT = 12
_DETAIL_LIMIT = 2000
_SUPPORTED_ARCHES = ("x86_64", "aarch64")


def _detect_arch() -> str:
    """按 runner 架构选择重放/修复的容器架构。"""
    machine = platform.machine().lower()
    return "aarch64" if machine in {"aarch64", "arm64"} else "x86_64"



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
    notes: app_notes.AppNotes | None = None,
    mode: str = "repair",
    arch: str = "x86_64",
    supporting: list[supporting_files.SupportingFile] | None = None,
    upstream_evidence_payload: dict | None = None,
) -> str:
    """组装修复/重放提示：角色规则 + 分支现状 + 失败证据 + 人工说明。"""
    mode = (mode or "repair").strip().lower()
    prompt = Path(agent_prompt_file("upgrade-creator")).read_text(encoding="utf-8")
    contract = {
        "mode": mode,
        "arch": arch,
        "app": task.app,
        "domain": task.domain,
        "version": task.version,
        "os_version": task.os_version,
        "dockerfile_path": (
            f"{task.domain}/{task.app}/{task.version}/{task.os_version}/Dockerfile"
        ),
        "test_script_path": f"{task.domain}/{task.app}/tests/test.sh",
        "source_url": task.source_url,
        "output_fields": ["dockerfile", "test_script"]
        + (["supporting_files"] if supporting else []),
        "supporting_files": [item.path for item in supporting or []],
    }
    if mode == "replay":
        prompt += (
            f"\n\n## Dual-arch replay mode ({arch})\n\n"
            "生成阶段已在 x86_64 的容器里把这份 Dockerfile 逐条重放通过；本次不是"
            "重新生成版本，也不是按失败证据修复，而是在当前架构上对同一份文件做"
            "完整重放校验。\n"
            "- 只修复架构相关问题（包名、产物名、下载地址的架构差异、编译守卫、"
            "依赖可用性）；\n"
            "- 不得改版本、下载源、ENTRYPOINT/CMD 语义，不得删功能来绕过失败；\n"
            "- x86_64 下已经验证通过的步骤保持原样；需要区分架构时，守卫只能用于"
            "包名、产物名、下载地址等实现差异，不能把编译、安装或测试整体跳过；\n"
            "- 两个架构都必须产出功能等价的可用产物，不允许用单架构守卫伪造通过；\n"
            "- 不需要改测试时 `test_script` 返回 `null`。\n"
            "\n## Immutable replay contract\n\n"
            + json.dumps(contract, indent=2, ensure_ascii=False)
            + "\n\n"
            + build_policy()
            + "\n\n## Current Dockerfile on the upgrade branch\n\n```dockerfile\n"
            + dockerfile_text.rstrip()
            + "\n```\n"
        )
    else:
        prompt += (
            "\n\n## Repair mode\n\n"
            "这是对**已有升级分支**的失败修复，不是重新生成升级：禁止新建或切换分支，"
            "禁止改动与失败无关的文件。\n"
            "- `dockerfile` 必填，返回修复后的完整 Dockerfile 文本；\n"
            "- 需要调整功能测试时返回修复后的完整 `tests/test.sh` 文本，否则 `test_script` 为 `null`。\n"
            "\n## Immutable repair contract\n\n"
            + json.dumps(contract, indent=2, ensure_ascii=False)
            + "\n\n"
            + build_policy()
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
    prompt += supporting_files.render_prompt(supporting or [])
    prompt += app_notes.render_prompt(notes)
    if mode != "replay" and upstream_evidence_payload:
        prompt += upstream_evidence.render_install_section(
            upstream_evidence_payload
        )
    if mode != "replay":
        reports = evidence.get("reports") or ["（未找到 evidence 报告）"]
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
        + (
            instructions.strip()
            or (
                "（未提供；只做当前架构的重放校验，不改版本与功能）"
                if mode == "replay"
                else "（未提供；请按失败证据做最小修复）"
            )
        )
        + "\n"
    )
    if session:
        prompt += container_verification_section(
            staging=Path(session["staging"]),
            container=str(session["container"]),
            output_dockerfile=Path(session["output_dockerfile"]),
            build_log=Path(session["build_log"]),
            arch=arch,
            mode="replay" if mode == "replay" else "repair",
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
        'install_mode(str，"source" 或 "binary"，必须与最终 Dockerfile 的实际做法一致)、'
        "test_script(str 或 null)、summary(str)、"
        "app_note(str 或 null，本次新增的可复用经验)、error(null 或 str)"
        + (
            "、supporting_files(list，逐个辅助文件的审计结论)"
            if supporting
            else ""
        )
        + "。不得修改工作区文件；只返回 JSON。\n"
    )
    return prompt


def _app_note(payload: dict) -> str:
    note = payload.get("app_note")
    return note.strip() if isinstance(note, str) and note.strip() else ""


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
    mode: str = "repair",
    arch: str = "x86_64",
    supporting: list[supporting_files.SupportingFile] | None = None,
    upstream_evidence_payload: dict | None = None,
) -> tuple[str, str | None, dict[str, str], str, str]:
    """让 Agent 在容器里复现并修复失败指令；失败即终止，不静默保留原文件。"""
    api_key = ai_provider.api_key()
    executable = os.environ.get("OPENCODE_BIN") or shutil.which("opencode")
    if not api_key or not executable:
        raise version_upgrade.UpgradeError(
            f"{task.app}: 缺少 AI 凭证/opencode，无法执行修复"
        )

    stage = "upgrade-replay" if mode == "replay" else "upgrade-repair"
    output_dockerfile = Path(session["output_dockerfile"])
    notes = app_notes.load(task.app)
    agent_timeout = app_notes.generate_timeout_seconds(notes)
    if notes is not None and notes.body:
        log_stage(
            stage,
            f"{task.app}: 已加载注意点文档 config/app-notes/{notes.app}.md "
            f"({len(notes.body)} chars)",
        )
    if notes is not None and notes.generate_timeout_minutes:
        log_stage(
            stage,
            f"{task.app}: 注意点文档覆盖修复预算 "
            f"{notes.generate_timeout_minutes} 分钟",
        )
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
            notes=notes,
            mode=mode,
            arch=arch,
            supporting=supporting,
            upstream_evidence_payload=upstream_evidence_payload,
        )
        log_stage(stage, f"{task.app}: {mode} agent round {round_no + 1}")
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
                timeout=agent_timeout,
            )
        except Exception as error:  # noqa: BLE001 - 落盘产物优先于退出码
            agent_error = error
            log_stage(
                stage,
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
            log_stage(stage, f"{task.app}: findings={findings}")
            continue
        if agent_error is not None:
            log_stage(
                stage,
                f"{task.app}: agent 未正常结束，但容器内已落盘 Dockerfile，继续采用",
            )
        findings = version_upgrade.check_dockerfile(candidate, task.version)
        findings += supporting_files.deterministic_findings(supporting or [])
        review_findings, updates = supporting_files.validate(
            supporting or [], payload
        )
        findings += review_findings
        script = payload.get("test_script")
        repaired_script: str | None = None
        if isinstance(script, str) and script.strip():
            findings += _validate_test_script(script)
            repaired_script = script
        if not findings:
            return candidate, repaired_script, updates, _app_note(payload), (
                upstream_evidence.resolved_install_mode(
                    {
                        "install_mode": payload.get("install_mode"),
                        "evidence": upstream_evidence_payload,
                    }
                )
            )
        log_stage(stage, f"{task.app}: findings={findings}")

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
    if diff.returncode == 0 and re.search(r"^M\t", diff.stdout or "", re.MULTILINE):
        return "existing-repaired"
    return "existing"


def run(
    *,
    task_spec_path: Path,
    evidence_dirs: list[Path],
    instructions: str,
    task_spec_out: Path,
    branch_override: str = "",
    mode: str = "repair",
    arch: str = "",
    app_note_out: Path | None = None,
) -> int:
    mode = (mode or "repair").strip().lower()
    if mode not in {"repair", "replay"}:
        raise SystemExit(f"unsupported mode: {mode}")
    arch = (arch or "").strip().lower() or _detect_arch()
    if arch not in _SUPPORTED_ARCHES:
        raise SystemExit(f"unsupported arch: {arch}")
    stage = "upgrade-replay" if mode == "replay" else "upgrade-repair"

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

    supporting = supporting_files.collect(dockerfile_path.parent, dockerfile_text)
    if supporting:
        log_stage(
            stage,
            f"{task.app}: 需要审计 {len(supporting)} 个辅助文件 "
            f"{[item.path for item in supporting]}",
        )

    evidence = collect_evidence(evidence_dirs)
    log_stage(
        stage,
        f"{task.app}: {mode} {branch} arch={arch} "
        f"failures={len(evidence['failures'])} logs={len(evidence['logs'])}",
    )

    # 修复/重放都在容器里做：把版本目录复制成 staging 构建上下文，Agent 在其中
    # 复现失败指令并当场修，和 CI 失败修复链路同一套做法。
    kind = "replay" if mode == "replay" else "repair"
    root = session_dir(repo_dir, task.app, task.version, task.os_version, kind)
    staging = root / "context"
    shutil.copytree(dockerfile_path.parent, staging)
    session = {
        "staging": staging,
        "container": container_name(f"{task.app}-{kind}"),
        "output_dockerfile": root / "final-Dockerfile",
        "build_log": root / "build-log.md",
        "arch": arch,
    }
    label = build_runner.activate_docker_shim(DOCKER_SHIM_DIR)
    try:
        repaired_dockerfile, repaired_test, repaired_supporting, app_note, install_mode = (
            _repair_files(
                repo_dir=repo_dir,
                task=task,
                dockerfile_text=dockerfile_text,
                test_script_text=test_script_text,
                evidence=evidence,
                instructions=instructions,
                session=session,
                mode=mode,
                arch=arch,
                supporting=supporting,
                upstream_evidence_payload=evidence_payload,
            )
        )
    finally:
        build_runner.docker_rm(str(session["container"]))
        build_runner.docker_rm_by_label(label)
        build_runner.docker_rm_images_by_label(label)

    if app_notes.save_note_text(app_note_out, app_note) is not None:
        log_stage(stage, f"{task.app}: app note 已暂存 -> {app_note_out}")

    repaired_dockerfile = version_upgrade.ensure_repo_cache_cleaned(
        repaired_dockerfile
    )
    dockerfile_path.write_text(repaired_dockerfile.rstrip() + "\n", encoding="utf-8")
    for changed_path in supporting_files.apply_updates(
        dockerfile_path.parent, repaired_supporting
    ):
        log_stage(stage, f"{task.app}: 已更新辅助文件 {changed_path.name}")
    if repaired_test is not None:
        test_path.parent.mkdir(parents=True, exist_ok=True)
        test_path.write_text(repaired_test.rstrip() + "\n", encoding="utf-8")
        test_path.chmod(0o755)

    _git(repo_dir, "add", "-A", app_rel)
    changed = bool(
        _git(
            repo_dir, "status", "--porcelain", "--", app_rel, check=False
        ).stdout.strip()
    )
    if not changed:
        if mode != "replay":
            raise SystemExit(f"{task.app}: 修复没有产生任何文件改动，未提交")
        log_stage(stage, f"{task.app}: {arch} 重放未发现架构差异，无改动")
    else:
        commit_name = _env("GIT_COMMIT_NAME", "github-actions[bot]")
        commit_email = _env(
            "GIT_COMMIT_EMAIL", "github-actions[bot]@users.noreply.github.com"
        )
        message = (
            f"fix: replay {task.app} {task.version} on {arch}"
            if mode == "replay"
            else f"fix: repair {task.app} {task.version} upgrade branch"
        )
        _git(
            repo_dir,
            "-c", f"user.name={commit_name}",
            "-c", f"user.email={commit_email}",
            "commit", "-m", message,
        )
        _git(repo_dir, "push", push_url, f"+refs/heads/{branch}:refs/heads/{branch}")
        log_stage(stage, f"{task.app}: pushed {branch} -> {push_repo}")

    task_spec_out.parent.mkdir(parents=True, exist_ok=True)
    payload = json.loads(task.to_json())
    payload["evidence"] = evidence_payload
    payload["install_mode"] = install_mode
    task_spec_out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    _emit_output(
        branch=branch,
        test_status=_test_status(repo_dir, test_rel),
        push_repo=push_repo,
        item_json=json.dumps(
            {**item, "install_mode": install_mode},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    )
    log_stage(stage, f"{task.app}: done mode={mode} arch={arch}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--task-spec", required=True, help="生成/失败运行产出的 task-spec.json"
    )
    parser.add_argument(
        "--evidence-dir",
        action="append",
        default=[],
        help="失败运行的 evidence 目录，可重复；replay 模式不需要",
    )
    parser.add_argument("--instructions", default="", help="人工给 AI 的修复说明")
    parser.add_argument(
        "--branch", default="", help="已有升级分支（留空按 task spec 推导）"
    )
    parser.add_argument(
        "--mode",
        choices=("repair", "replay"),
        default="repair",
        help="repair=失败修复；replay=生成后的双架构重放",
    )
    parser.add_argument(
        "--arch",
        choices=("", "x86_64", "aarch64"),
        default="",
        help="重放/修复使用的容器架构；留空按当前 runner 自动识别",
    )
    parser.add_argument(
        "--task-spec-out",
        default=os.path.join(
            os.environ.get("RUNNER_TEMP", PROJECT_ROOT), "task-spec.json"
        ),
    )
    parser.add_argument(
        "--app-note-out",
        type=Path,
        help="Agent 总结的 app note 暂存路径（留空则不暂存）",
    )
    args = parser.parse_args()
    return run(
        task_spec_path=Path(args.task_spec),
        evidence_dirs=[Path(path) for path in args.evidence_dir],
        instructions=args.instructions,
        task_spec_out=Path(args.task_spec_out),
        branch_override=args.branch,
        mode=args.mode,
        arch=args.arch,
        app_note_out=args.app_note_out,
    )


if __name__ == "__main__":
    sys.exit(main())
