#!/usr/bin/env python3
"""
Stage: 场景二「已是最新版本」的 AI 审计（upgrade_audit）

当看板解析出的最新版本在目标仓已经存在时，不再直接跳过，而是审计现有镜像：

1. Dockerfile 是否有问题（版本/构建源/依赖/运行入口等）；
2. Dockerfile 是否按上游证据构建（tag / commit / L1 证据包 / 自探结果）；
3. 构建出的镜像版本是否正确（Dockerfile ARG、clone tag、meta.yml 是否一致）；
4. 是否有功能测试脚本，脚本质量是否足够。

先跑确定性检查（版本、tag、meta、测试脚本、image-info），再把 Dockerfile、meta.yml、
测试脚本和上游证据一起交给 ``upgrade_auditor`` Agent 做语义审计。修复有两种交付方式：

- ``--prepare``：调用 ``upgrade_fixer`` 修正 Dockerfile 与 ``doc/image-info.yml``；
  若该应用没有功能测试脚本，复用场景四的 ``generate_test_script`` 生成
  ``tests/test.sh`` 一并提交（生成失败不阻断修复）；过确定性校验后只推送修复
  分支，并写出 ``task-spec.json`` / ``delivery.json``，供双架构原生校验与后续
  开 PR 使用；
- ``--open-pr --delivery <delivery.json>``：校验通过后从交接文件创建 PR；
- ``--deliver``：本地一键跑完（审计 + 修复 + 推分支 + 开 PR）。

输入: --item '<json>'（upgrade_scan 的 audits 条目）
环境: SOURCE_REPO_DIR（默认 PROJECT_ROOT/source-repo）、AI_API_KEY、OPENCODE_BIN；
      --prepare/--deliver/--open-pr 还需要 GITCODE_TOKEN / GITCODE_FORK_REPO（可选）/ TARGET_*
输出: --out <dir> 下的 audit.json / audit.md（--prepare 另有 task-spec.json、delivery.json）
退出码: 0 审计/修复完成；AI 调用/契约/修复校验失败 → 1
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

from scripts.lib import (  # noqa: E402
    ai_provider,
    app_notes,
    upstream_evidence,
    version_upgrade,
)
from scripts.lib.agent_policy import build_policy  # noqa: E402
from scripts.lib.agent_runtime import run_agent  # noqa: E402
from scripts.lib.ci_gitcode_api import (  # noqa: E402
    create_pull_request,
    find_any_pr_by_head_branch,
)
from scripts.lib.stage_common import (  # noqa: E402
    agent_prompt_file,
    log_stage,
    normalize_repo,
)
from scripts.lib.task_spec import TaskSpec, _os_tag  # noqa: E402

DEFAULT_SOURCE_REPO_DIR = os.path.join(PROJECT_ROOT, "source-repo")
DEFAULT_TARGET_REPO = "openeuler/openeuler-docker-images"
DEFAULT_TARGET_BRANCH = "master"
AUDIT_AGENT_ROLE = "upgrade_auditor"
AUDIT_REQUIRED_KEYS = (
    "success",
    "verdict",
    "dockerfile_issues",
    "evidence_alignment",
    "version_check",
    "test_script",
    "summary",
)
FIX_AGENT_ROLE = "upgrade_fixer"
FIX_REQUIRED_KEYS = (
    "success",
    "dockerfile",
    "image_info",
    "changes",
    "summary",
)
AUDIT_AGENT_TIMEOUT_SECONDS = 1800
_MAX_TEXT_CHARS = 20000

_ARG_RE = re.compile(
    r"(?im)^\s*ARG\s+(VERSION|TAG)\s*=\s*[\"']?([^\s\"']+)"
)
_CLONE_BRANCH_RE = re.compile(r"git\s+clone[^\n]*?(?:-b|--branch)\s+([^\s;]+)")


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _norm(value: object) -> str:
    return str(value or "").strip().lstrip("vV").casefold()


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _truncate(text: str) -> str:
    if len(text) <= _MAX_TEXT_CHARS:
        return text
    return text[:_MAX_TEXT_CHARS] + "\n…（截断）\n"


def find_test_scripts(app_dir: Path) -> list[Path]:
    """Target repo's three test search locations, de-duplicated."""
    candidates = [app_dir / "tests" / "test.sh", app_dir / "test.sh"]
    candidates.extend(sorted(app_dir.glob("*/*/test.sh")))
    seen: set[Path] = set()
    scripts: list[Path] = []
    for path in candidates:
        if path.is_file() and path not in seen:
            seen.add(path)
            scripts.append(path)
    return scripts


def collect_context(repo_dir: Path, item: dict) -> dict:
    domain = str(item["domain"])
    app = str(item["app"])
    version = str(item["version"])
    os_version = str(item["os_version"])
    app_dir = repo_dir / domain / app

    dockerfile_rel = str(item.get("dockerfile_path") or "")
    if not dockerfile_rel:
        dockerfile_rel = f"{domain}/{app}/{version}/{os_version}/Dockerfile"
    dockerfile_path = repo_dir / dockerfile_rel
    if not dockerfile_path.is_file():
        raise SystemExit(f"Dockerfile not found: {dockerfile_path}")

    meta = _read(app_dir / "meta.yml")
    readme = _read(app_dir / "README.md")
    scripts = find_test_scripts(app_dir)

    return {
        "app": app,
        "domain": domain,
        "version": version,
        "os_version": os_version,
        "dockerfile_path": dockerfile_rel,
        "dockerfile": _truncate(_read(dockerfile_path)),
        "meta_yml": _truncate(meta),
        "readme": _truncate(readme[:4000]),
        "image_info": _read(app_dir / "doc" / "image-info.yml"),
        "test_scripts": [
            {
                "path": path.relative_to(repo_dir).as_posix(),
                "content": _truncate(_read(path)),
            }
            for path in scripts
        ],
        "evidence": item.get("evidence") or {},
        "source_url": str(item.get("source_url") or ""),
    }


def _test_commands(scripts: list[dict]) -> list[str]:
    """Commands the test script actually invokes; used to align image-info usage."""
    commands: set[str] = set()
    noise = {
        "if", "then", "else", "fi", "for", "while", "do", "done", "case",
        "esac", "function", "local", "return", "echo", "printf", "export",
        "readonly", "set", "shift", "exit", "source", "command", "test",
        "true", "false", "docker", "sudo",
    }
    for script in scripts:
        text = script["content"]
        commands.update(
            match.group(2)
            for match in re.finditer(
                r'(?m)^\s*([A-Z0-9_]+)_BIN="([^"\s]+)"', text
            )
        )
        commands.update(
            re.findall(r"command\s+-v\s+[\"']?([A-Za-z0-9._-]+)", text)
        )
        commands.update(
            match.group(1)
            for match in re.finditer(
                r"(?m)^\s*([a-zA-Z][a-zA-Z0-9._-]+)(?=\s)", text
            )
            if not match.group(1).endswith("_BIN")
            and match.group(1) not in noise
            and match.group(1) != "main"
        )
    return sorted(commands)


def _image_info_findings(context: dict) -> list[dict]:
    findings: list[dict] = []
    text = context["image_info"]
    if not text.strip():
        return findings

    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError as error:
        findings.append(
            {
                "code": "image_info.invalid_yaml",
                "severity": "major",
                "component": "image-info",
                "message": f"doc/image-info.yml 不是合法 YAML：{error}",
            }
        )
        parsed = None
    if parsed is not None and not isinstance(parsed, dict):
        findings.append(
            {
                "code": "image_info.invalid_root",
                "severity": "major",
                "component": "image-info",
                "message": "doc/image-info.yml 根节点不是对象",
            }
        )

    if str(context["version"]) not in text:
        findings.append(
            {
                "code": "image_info.version_missing",
                "severity": "major",
                "component": "image-info",
                "message": (
                    f"doc/image-info.yml 没有出现目标版本 {context['version']}"
                ),
            }
        )

    commands = _test_commands(context["test_scripts"])
    if commands and not any(command in text for command in commands):
        findings.append(
            {
                "code": "image_info.test_commands_missing",
                "severity": "major",
                "component": "image-info",
                "message": (
                    "doc/image-info.yml 的 usage 与测试脚本命令不一致；"
                    f"测试脚本使用 {commands}，但 image-info 中都没有出现"
                ),
            }
        )
    return findings


def deterministic_findings(context: dict) -> list[dict]:
    """Harness facts the Agent must incorporate; no semantic guessing."""
    findings: list[dict] = []
    dockerfile = context["dockerfile"]
    expected_version = str(context["version"])
    expected_tag = str((context["evidence"] or {}).get("tag") or "").strip()

    args: dict[str, list[str]] = {"VERSION": [], "TAG": []}
    for match in _ARG_RE.finditer(dockerfile):
        args[match.group(1).upper()].append(match.group(2))

    if not args["VERSION"] and _norm(expected_version) not in _norm(dockerfile):
        findings.append(
            {
                "code": "version.missing",
                "severity": "major",
                "component": "dockerfile",
                "message": (
                    f"Dockerfile 没有 ARG VERSION，也没有出现目标版本 {expected_version}"
                ),
            }
        )
    elif args["VERSION"] and all(
        _norm(value) != _norm(expected_version) for value in args["VERSION"]
    ):
        findings.append(
            {
                "code": "version.mismatch",
                "severity": "major",
                "component": "dockerfile",
                "message": (
                    f"ARG VERSION={args['VERSION']} 与看板目标版本 {expected_version} 不一致"
                ),
            }
        )

    if expected_tag:
        observed = _observed_tags(dockerfile)
        if observed and all(_norm(value) != _norm(expected_tag) for value in observed):
            findings.append(
                {
                    "code": "tag.mismatch",
                    "severity": "blocker",
                    "component": "dockerfile",
                    "message": (
                        f"Dockerfile 使用的上游 tag {observed} 与看板 tag "
                        f"{expected_tag} 不一致，构建出的镜像版本可能不是目标版本"
                    ),
                }
            )

    meta = context["meta_yml"]
    expected_key = f"{expected_version}-{_os_tag(str(context['os_version']))}"
    expected_path = f"{expected_version}/{context['os_version']}/Dockerfile"
    if expected_key not in meta or expected_path not in meta:
        findings.append(
            {
                "code": "meta.mismatch",
                "severity": "major",
                "component": "meta.yml",
                "message": (
                    f"meta.yml 缺少 {expected_key} -> {expected_path} 的登记"
                ),
            }
        )

    if not context["test_scripts"]:
        findings.append(
            {
                "code": "test.missing",
                "severity": "major",
                "component": "tests",
                "message": "没有 tests/test.sh、test.sh 或 */*/test.sh",
            }
        )
    else:
        contents = "\n".join(script["content"] for script in context["test_scripts"])
        if "EXPECTED_VERSION" not in contents:
            findings.append(
                {
                    "code": "test.no_version_assertion",
                    "severity": "minor",
                    "component": "tests",
                    "message": "测试脚本没有使用 EXPECTED_VERSION 校验镜像版本",
                }
            )

    collector = (context["evidence"] or {}).get("collector") or []
    if not collector:
        findings.append(
            {
                "code": "evidence.missing",
                "severity": "minor",
                "component": "evidence",
                "message": "看板未返回 L1 证据包，镜像构建只能以 tag/commit 与上游源码为准",
            }
        )
    findings.extend(_image_info_findings(context))
    return findings


def deterministic_summary(context: dict, findings: list[dict]) -> dict:
    """按用户关心的四个问题汇总 Harness 事实，dry-run 也能直接看。"""
    version_codes = {
        "version.missing",
        "version.mismatch",
        "tag.mismatch",
        "meta.mismatch",
    }
    evidence = context["evidence"] or {}
    collector = evidence.get("collector") or []
    probe = evidence.get("probe") or {}
    tests = context["test_scripts"]
    test_content = "\n".join(script["content"] for script in tests)

    return {
        "dockerfile": {
            "issue_count": len(
                [f for f in findings if f["component"] == "dockerfile"]
            ),
        },
        "evidence": {
            "l1_checks": [
                {
                    "check_id": check.get("check_id"),
                    "result": check.get("result"),
                }
                for check in collector
            ],
            "probe_status": probe.get("status"),
            "missing": not collector,
        },
        "version": {
            "expected": context["version"],
            "tag": evidence.get("tag"),
            "ok": not any(f["code"] in version_codes for f in findings),
        },
        "image_info": {
            "present": bool(context["image_info"]),
            "issue_count": len(
                [f for f in findings if f["component"] == "image-info"]
            ),
        },
        "test_script": {
            "present": bool(tests),
            "paths": [script["path"] for script in tests],
            "expects_version": "EXPECTED_VERSION" in test_content,
        },
    }


def build_prompt(context: dict, findings: list[dict]) -> str:
    prompt = Path(agent_prompt_file("upgrade-auditor")).read_text(encoding="utf-8")
    contract = {
        "app": context["app"],
        "domain": context["domain"],
        "expected_version": context["version"],
        "os_version": context["os_version"],
        "dockerfile_path": context["dockerfile_path"],
        "source_url": context["source_url"],
        "tag": (context["evidence"] or {}).get("tag"),
        "tag_url": (context["evidence"] or {}).get("tag_url"),
        "commit_sha": (context["evidence"] or {}).get("commit_sha"),
        "has_test_script": bool(context["test_scripts"]),
        "test_script_paths": [s["path"] for s in context["test_scripts"]],
    }
    parts = [
        prompt,
        "\n\n## Immutable audit contract\n\n"
        + json.dumps(contract, indent=2, ensure_ascii=False),
        "\n\n" + build_policy(),
        "\n\n## Deterministic findings (Harness facts)\n\n"
        + json.dumps(findings, indent=2, ensure_ascii=False),
        "\n\n## Dockerfile under audit\n\n```dockerfile\n"
        + context["dockerfile"].rstrip()
        + "\n```\n",
        "\n\n## meta.yml\n\n```yaml\n"
        + context["meta_yml"].rstrip()
        + "\n```\n",
    ]
    for script in context["test_scripts"]:
        parts.append(
            f"\n\n## Test script: {script['path']}\n\n```bash\n"
            + script["content"].rstrip()
            + "\n```\n"
        )
    if not context["test_scripts"]:
        parts.append("\n\n## Test script\n\n未找到任何功能测试脚本。\n")
    if context["image_info"]:
        parts.append(
            "\n\n## doc/image-info.yml\n\n```yaml\n"
            + context["image_info"].rstrip()
            + "\n```\n"
        )
    parts.append("\n\n" + upstream_evidence.render_prompt(context["evidence"]))
    parts.append(app_notes.render_prompt(app_notes.load(context["app"])))
    parts.append(
        "\n\n## Final response contract\n\n"
        "最终响应必须恰好是一个 JSON 对象，包含以下键："
        "success(bool)、verdict(ok|issues|critical)、"
        "dockerfile_issues(list)、evidence_alignment(object)、"
        "version_check(object)、test_script(object)、summary(str)、"
        "error(null 或 str)。不得修改工作区文件；只返回 JSON。\n"
    )
    return "".join(parts)


def _observed_tags(dockerfile: str) -> list[str]:
    arg_tags = [
        match.group(2)
        for match in _ARG_RE.finditer(dockerfile)
        if match.group(1).upper() == "TAG" and not match.group(2).startswith("$")
    ]
    clone_refs = [
        value
        for value in _CLONE_BRANCH_RE.findall(dockerfile)
        if not value.startswith("$")
    ]
    return arg_tags or clone_refs


def _git(repo_dir: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess:
    completed = subprocess.run(
        ["git", "-C", str(repo_dir), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if check and completed.returncode != 0:
        detail = re.sub(
            r"oauth2:[^@]+@", "oauth2:***@",
            (completed.stderr or completed.stdout or "").strip(),
        )
        raise RuntimeError(
            f"git {' '.join(args)} failed ({completed.returncode}): {detail[:2000]}"
        )
    return completed


def _reset_workspace(repo_dir: Path) -> None:
    _git(repo_dir, "checkout", "--", ".")
    _git(repo_dir, "clean", "-fd")


def ensure_test_script(repo_dir: Path, context: dict) -> list[Path]:
    """缺功能测试时按 KunpengTest 规范补一个 ``tests/test.sh``。

    复用场景四的生成器；生成失败只记日志、不阻断本次修复（双架构校验会给出
    最终结论）。调用前工作树必须是干净的——生成器每轮都会 reset workspace，
    因此这一步要放在 ``run_agent_fix`` 之后、写修复/Dockerfile 之前。

    返回新增的文件列表；已有测试或生成失败时为空。
    """
    from scripts.harness import testgen_scan
    from scripts.harness.testgen_generate import generate_test_script

    app_dir = repo_dir / str(context["domain"]) / str(context["app"])
    if testgen_scan.has_any_test_script(app_dir):
        return []

    api_key = ai_provider.api_key()
    executable = os.environ.get("OPENCODE_BIN") or shutil.which("opencode")
    if not api_key or not executable:
        log_stage(
            "upgrade-audit",
            f"{context['app']}: 缺少 AI 凭证/opencode，跳过补测试",
        )
        return []

    findings = generate_test_script(
        repo_dir=repo_dir,
        app=str(context["app"]),
        domain=str(context["domain"]),
        dockerfile_rel=str(context["dockerfile_path"]),
        source_url=str(context["source_url"]),
        latest_version=str(context["version"]),
        api_key=api_key,
        executable=Path(executable),
        extra_context=upstream_evidence.render_prompt(context["evidence"]),
        timeout=AUDIT_AGENT_TIMEOUT_SECONDS,
    )
    if findings:
        detail = "; ".join(f"{f['code']}: {f['message']}" for f in findings)
        log_stage(
            "upgrade-audit",
            f"{context['app']}: 补测试未通过（不阻断修复）: {detail}",
        )
        return []

    test_path = app_dir / "tests" / "test.sh"
    if not test_path.is_file():
        log_stage("upgrade-audit", f"{context['app']}: 生成器未落盘 tests/test.sh")
        return []

    # 校验契约要求可执行位；生成器只负责写内容，这里统一补齐。
    test_path.chmod(test_path.stat().st_mode | 0o111)
    relative = test_path.relative_to(repo_dir).as_posix()
    context["test_scripts"] = [
        {"path": relative, "content": _truncate(_read(test_path))}
    ]
    log_stage("upgrade-audit", f"{context['app']}: 已补功能测试 {relative}")
    return [test_path]


def run_agent_audit(context: dict, findings: list[dict], repo_dir: Path) -> dict:
    api_key = ai_provider.api_key()
    executable = os.environ.get("OPENCODE_BIN") or shutil.which("opencode")
    if not api_key or not executable:
        raise SystemExit(
            "AI_API_KEY (or DEEPSEEK_API_KEY) and opencode are required for audit"
        )

    prompt = build_prompt(context, findings)
    log_stage("upgrade-audit", f"{context['app']}: agent audit start")
    try:
        result = run_agent(
            executable=Path(executable),
            role=AUDIT_AGENT_ROLE,
            prompt=prompt,
            workspace=repo_dir,
            api_key=api_key,
            required_keys=AUDIT_REQUIRED_KEYS,
            timeout=AUDIT_AGENT_TIMEOUT_SECONDS,
        )
    finally:
        _reset_workspace(repo_dir)

    payload = result.payload
    if not bool(payload.get("success")):
        raise SystemExit(
            f"{context['app']}: audit agent failed: {payload.get('error')}"
        )
    if payload.get("verdict") not in {"ok", "issues", "critical"}:
        raise SystemExit(
            f"{context['app']}: audit agent returned invalid verdict "
            f"{payload.get('verdict')!r}"
        )
    return payload


def build_fix_prompt(
    context: dict, findings: list[dict], audit_payload: dict
) -> str:
    """组装修复提示：审计结论 + 现有文件 + 测试脚本 + 证据。"""
    prompt = Path(agent_prompt_file("upgrade-fixer")).read_text(encoding="utf-8")
    contract = {
        "app": context["app"],
        "domain": context["domain"],
        "expected_version": context["version"],
        "os_version": context["os_version"],
        "dockerfile_path": context["dockerfile_path"],
        "image_info_path": (
            f"{context['domain']}/{context['app']}/doc/image-info.yml"
        ),
        "source_url": context["source_url"],
        "tag": (context["evidence"] or {}).get("tag"),
        "tag_url": (context["evidence"] or {}).get("tag_url"),
        "commit_sha": (context["evidence"] or {}).get("commit_sha"),
        "test_script_paths": [s["path"] for s in context["test_scripts"]],
    }
    parts = [
        prompt,
        "\n\n## Immutable fix contract\n\n"
        + json.dumps(contract, indent=2, ensure_ascii=False),
        "\n\n" + build_policy(),
        "\n\n## Deterministic findings\n\n"
        + json.dumps(findings, indent=2, ensure_ascii=False),
        "\n\n## AI audit conclusion\n\n"
        + json.dumps(audit_payload, indent=2, ensure_ascii=False),
        "\n\n## Current Dockerfile\n\n```dockerfile\n"
        + context["dockerfile"].rstrip()
        + "\n```\n",
        "\n\n## Current meta.yml\n\n```yaml\n"
        + context["meta_yml"].rstrip()
        + "\n```\n",
    ]
    if context["image_info"]:
        parts.append(
            "\n\n## Current doc/image-info.yml\n\n```yaml\n"
            + _truncate(context["image_info"]).rstrip()
            + "\n```\n"
        )
    else:
        parts.append("\n\n## Current doc/image-info.yml\n\n不存在。\n")
    for script in context["test_scripts"]:
        parts.append(
            f"\n\n## Test script: {script['path']}\n\n```bash\n"
            + script["content"].rstrip()
            + "\n```\n"
        )
    parts.append("\n\n" + upstream_evidence.render_prompt(context["evidence"]))
    parts.append(app_notes.render_prompt(app_notes.load(context["app"])))
    parts.append(
        "\n\n## Final response contract\n\n"
        "最终响应必须恰好是一个 JSON 对象，包含以下键："
        "success(bool)、dockerfile(str，完整 Dockerfile)、"
        "image_info(str，完整 doc/image-info.yml；不需要修改时原样返回)、"
        "changes(list[str])、summary(str)、error(null 或 str)。"
        "不得修改工作区文件；只返回 JSON。\n"
    )
    return "".join(parts)


def validate_fix(context: dict, payload: dict) -> list[str]:
    """修复结果的确定性校验；不通过就不允许推送。"""
    problems: list[str] = []
    dockerfile = str(payload.get("dockerfile") or "")
    problems.extend(
        version_upgrade.check_dockerfile(dockerfile, str(context["version"]))
    )

    expected_tag = str((context["evidence"] or {}).get("tag") or "").strip()
    if expected_tag:
        observed = _observed_tags(dockerfile)
        if observed and all(_norm(value) != _norm(expected_tag) for value in observed):
            problems.append(
                f"Dockerfile 使用的 tag {observed} 与看板 tag {expected_tag} 不一致"
            )

    image_info = payload.get("image_info")
    if image_info is not None:
        text = str(image_info)
        if context["image_info"] and not text.strip():
            problems.append("doc/image-info.yml 被清空")
        else:
            try:
                parsed = yaml.safe_load(text)
            except yaml.YAMLError as error:
                problems.append(f"doc/image-info.yml 不是合法 YAML：{error}")
                parsed = None
            if parsed is not None and not isinstance(parsed, dict):
                problems.append("doc/image-info.yml 根节点不是对象")
            if str(context["version"]) not in text:
                problems.append(
                    f"doc/image-info.yml 没有出现目标版本 {context['version']}"
                )
            commands = _test_commands(context["test_scripts"])
            if commands and not any(command in text for command in commands):
                problems.append(
                    f"doc/image-info.yml 仍未包含测试脚本命令 {commands}"
                )
    return problems


def apply_fix(repo_dir: Path, context: dict, payload: dict) -> list[Path]:
    """把修复结果写入工作树，返回实际改动的文件。"""
    changed: list[Path] = []

    dockerfile_path = repo_dir / context["dockerfile_path"]
    original = _read(dockerfile_path)
    updated = version_upgrade.ensure_repo_cache_cleaned(
        str(payload["dockerfile"]).rstrip() + "\n"
    )
    if updated != original:
        dockerfile_path.write_text(updated, encoding="utf-8")
        changed.append(dockerfile_path)

    image_info = payload.get("image_info")
    if isinstance(image_info, str) and image_info.strip():
        image_info_path = (
            repo_dir / context["domain"] / context["app"] / "doc" / "image-info.yml"
        )
        updated_info = image_info.rstrip() + "\n"
        if not image_info_path.is_file() or _read(image_info_path) != updated_info:
            image_info_path.parent.mkdir(parents=True, exist_ok=True)
            image_info_path.write_text(updated_info, encoding="utf-8")
            changed.append(image_info_path)
    return changed


def _branch_name(app: str, version: str) -> str:
    return f"auto/image-audit/{app}/{version}"


def build_fix_pr_body(
    context: dict,
    findings: list[dict],
    audit_payload: dict,
    fix_payload: dict,
) -> str:
    lines = [
        f"本 PR 修复 **{context['app']} {context['version']}** 的审计问题，"
        f"并同步 `doc/image-info.yml`（openEuler `{context['os_version']}`）。",
        "",
        "## 审计结论",
        "",
        f"- AI verdict：`{audit_payload.get('verdict')}`",
        f"- 摘要：{audit_payload.get('summary')}",
        "",
    ]
    for issue in audit_payload.get("dockerfile_issues") or []:
        lines.append(
            f"- **{issue.get('severity', 'unknown')}** {issue.get('message', '')}"
        )
    for finding in findings:
        lines.append(
            f"- **{finding['severity']}** `{finding['code']}`：{finding['message']}"
        )
    lines += ["", "## 变更", ""]
    for change in fix_payload.get("changes") or []:
        lines.append(f"- {change}")
    if context["test_scripts"]:
        lines += ["", "## 测试脚本依据", ""]
        for script in context["test_scripts"]:
            lines.append(f"- `{script['path']}`")
        commands = _test_commands(context["test_scripts"])
        if commands:
            lines.append(f"- 测试实际使用命令：`{commands}`")
    lines += ["", upstream_evidence.render_markdown(context["evidence"]), ""]
    lines.append(
        "> 本 PR 由场景二审计链路生成；`doc/image-info.yml` 的 usage "
        "与功能测试脚本保持一致，Dockerfile 依据看板 tag/commit 与上游源码修复。"
    )
    return "\n".join(lines)


def push_fix(
    repo_dir: Path,
    context: dict,
    fix_payload: dict,
    extra_paths: list[Path] | None = None,
) -> tuple[str, str, list[str]]:
    """把修复写入工作树、提交并推送分支；返回 (branch, push_repo, changed)。

    ``extra_paths`` 是修复结果以外需要一起提交的文件（例如审计链路补出来的
    ``tests/test.sh``），它们已由调用方写进工作树。
    """
    token = (os.environ.get("GITCODE_TOKEN") or "").strip()
    if not token:
        raise SystemExit("GITCODE_TOKEN is required to deliver the audit fix")

    branch = _branch_name(str(context["app"]), str(context["version"]))
    base = (os.environ.get("TARGET_BRANCH") or DEFAULT_TARGET_BRANCH).strip()
    target_repo = (os.environ.get("TARGET_REPO") or DEFAULT_TARGET_REPO).strip()
    push_repo = normalize_repo(os.environ.get("GITCODE_FORK_REPO") or "") or target_repo

    checkout = _git(repo_dir, "checkout", "-B", branch, f"origin/{base}")
    if checkout.returncode != 0:
        _git(repo_dir, "checkout", "-B", branch, base, check=True)

    changed = apply_fix(repo_dir, context, fix_payload)
    for path in extra_paths or []:
        if path.is_file() and path not in changed:
            changed.append(path)
    if not changed:
        log_stage(
            "upgrade-audit",
            f"{context['app']}: no change after fix, skip PR",
        )
        return branch, push_repo, []

    relative = [path.relative_to(repo_dir).as_posix() for path in changed]
    _git(repo_dir, "add", *relative, check=True)
    commit_name = (os.environ.get("GIT_COMMIT_NAME") or "github-actions[bot]").strip()
    commit_email = (
        os.environ.get("GIT_COMMIT_EMAIL")
        or "github-actions[bot]@users.noreply.github.com"
    ).strip()
    _git(
        repo_dir,
        "-c", f"user.name={commit_name}",
        "-c", f"user.email={commit_email}",
        "commit", "-m",
        f"fix: audit {context['app']} {context['version']}",
        check=True,
    )

    push_url = f"https://oauth2:{token}@gitcode.com/{push_repo}.git"
    _git(
        repo_dir,
        "push", push_url,
        f"+refs/heads/{branch}:refs/heads/{branch}",
        check=True,
    )
    return branch, push_repo, relative


def open_fix_pr(
    context: dict,
    findings: list[dict],
    audit_payload: dict,
    fix_payload: dict,
    branch: str,
    push_repo: str,
) -> str:
    """在修复分支已推送的前提下创建 PR（已存在则复用）。"""
    token = (os.environ.get("GITCODE_TOKEN") or "").strip()
    if not token:
        raise SystemExit("GITCODE_TOKEN is required to deliver the audit fix")

    target_repo = (
        os.environ.get("TARGET_REPO") or DEFAULT_TARGET_REPO
    ).strip()
    base = (os.environ.get("TARGET_BRANCH") or DEFAULT_TARGET_BRANCH).strip()

    head = f"{push_repo.split('/')[0]}:{branch}" if push_repo != target_repo else branch
    existing = find_any_pr_by_head_branch(target_repo, branch, token, open_only=True)
    if existing:
        url = str(existing.get("web_url") or existing.get("html_url") or "")
        log_stage("upgrade-audit", f"{context['app']}: PR already exists {url}")
        return url

    pr = create_pull_request(
        target_repo,
        head,
        base,
        f"fix: audit {context['app']} {context['version']}",
        build_fix_pr_body(context, findings, audit_payload, fix_payload),
        token,
    )
    url = str(pr.get("web_url") or pr.get("html_url") or "")
    log_stage("upgrade-audit", f"{context['app']}: PR created {url}")
    return url


def deliver_fix(
    repo_dir: Path,
    context: dict,
    findings: list[dict],
    audit_payload: dict,
    fix_payload: dict,
    extra_paths: list[Path] | None = None,
) -> str:
    """提交修复、推送分支并创建 PR；没有实际改动时返回空串。"""
    branch, push_repo, changed = push_fix(
        repo_dir, context, fix_payload, extra_paths=extra_paths
    )
    if not changed:
        return ""
    return open_fix_pr(
        context, findings, audit_payload, fix_payload, branch, push_repo
    )


def _emit_output(**values: str) -> None:
    output = os.environ.get("GITHUB_OUTPUT", "")
    if not output:
        return
    with open(output, "a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def write_task_spec(out_dir: Path, context: dict, item: dict) -> Path:
    """给双架构原生校验用的 TaskSpec（复用 version-update 场景）。"""
    source_url = str(item.get("source_url") or "").strip()
    if not source_url.startswith("https://"):
        source_url = "https://gitcode.com/openeuler/openeuler-docker-images"
    task = TaskSpec(
        app=str(context["app"]),
        version=str(context["version"]),
        os_version=str(context["os_version"]),
        domain=str(context["domain"]),
        source_url=source_url,
        scenario="version-update",
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "task-spec.json"
    path.write_text(task.to_json(), encoding="utf-8")
    return path


def write_delivery(
    out_dir: Path,
    item: dict,
    context: dict,
    findings: list[dict],
    audit_payload: dict,
    fix_payload: dict,
    branch: str,
    push_repo: str,
    changed: list[str],
) -> Path:
    """校验通过后开 PR 需要的全部上下文（跨 job 交接）。"""
    document = {
        "item": item,
        "context": context,
        "findings": findings,
        "audit": audit_payload,
        "fix": fix_payload,
        "branch": branch,
        "push_repo": push_repo,
        "changed": changed,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "delivery.json"
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path


def open_pr_from_delivery(path: Path) -> str:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    return open_fix_pr(
        document["context"],
        document.get("findings") or [],
        document.get("audit") or {},
        document.get("fix") or {},
        str(document["branch"]),
        str(document["push_repo"]),
    )


def run_agent_fix(
    context: dict,
    findings: list[dict],
    audit_payload: dict,
    repo_dir: Path,
) -> dict:
    api_key = ai_provider.api_key()
    executable = os.environ.get("OPENCODE_BIN") or shutil.which("opencode")
    if not api_key or not executable:
        raise SystemExit(
            "AI_API_KEY (or DEEPSEEK_API_KEY) and opencode are required for fix"
        )

    prompt = build_fix_prompt(context, findings, audit_payload)
    log_stage("upgrade-audit", f"{context['app']}: agent fix start")
    try:
        result = run_agent(
            executable=Path(executable),
            role=FIX_AGENT_ROLE,
            prompt=prompt,
            workspace=repo_dir,
            api_key=api_key,
            required_keys=FIX_REQUIRED_KEYS,
            timeout=AUDIT_AGENT_TIMEOUT_SECONDS,
        )
    finally:
        _reset_workspace(repo_dir)

    payload = result.payload
    if not bool(payload.get("success")):
        raise SystemExit(
            f"{context['app']}: fix agent failed: {payload.get('error')}"
        )
    problems = validate_fix(context, payload)
    if problems:
        raise SystemExit(
            f"{context['app']}: AI fix failed validation: {'；'.join(problems)}"
        )
    return payload


def render_markdown(
    context: dict,
    findings: list[dict],
    summary: dict,
    payload: dict | None,
    fix_payload: dict | None = None,
    pr_url: str = "",
    branch: str = "",
) -> str:
    lines = [f"## AI audit: {context['app']}", ""]
    lines.append(f"- 目标版本：`{context['version']}`（openEuler `{context['os_version']}`）")
    lines.append(f"- Dockerfile：`{context['dockerfile_path']}`")
    lines.append(f"- 测试脚本：{'有' if context['test_scripts'] else '无'}")
    lines += ["", "### 确定性结论", ""]
    lines.append(
        f"- Dockerfile：{summary['dockerfile']['issue_count']} 个确定性问题"
    )
    checks = summary["evidence"]["l1_checks"]
    lines.append(
        "- 证据对齐：L1 "
        + (f"{len(checks)} 条（{', '.join(str(c['check_id']) for c in checks)}）" if checks else "证据缺失")
        + f"，自探状态 `{summary['evidence']['probe_status']}`"
    )
    lines.append(
        f"- 版本：expected=`{summary['version']['expected']}`，"
        f"tag=`{summary['version']['tag']}`，ok=`{summary['version']['ok']}`"
    )
    tests = summary["test_script"]
    lines.append(
        f"- 测试脚本：present=`{tests['present']}`，"
        f"expects_version=`{tests['expects_version']}`，"
        f"paths=`{tests['paths']}`"
    )
    image_info = summary["image_info"]
    lines.append(
        f"- doc/image-info.yml：present=`{image_info['present']}`，"
        f"确定性问题=`{image_info['issue_count']}`"
    )
    if payload:
        lines.append(f"- AI 结论：`{payload.get('verdict')}`")
        lines.append(f"- 摘要：{payload.get('summary')}")
        lines.append("")

        issues = payload.get("dockerfile_issues") or []
        lines += ["### Dockerfile 问题（AI）", ""]
        if issues:
            for issue in issues:
                lines.append(
                    f"- **{issue.get('severity', 'unknown')}** "
                    f"{issue.get('message', '')}"
                )
        else:
            lines.append("- 未发现 Dockerfile 问题")

        alignment = payload.get("evidence_alignment") or {}
        lines += ["", "### 证据对齐（AI）", ""]
        lines.append(f"- aligned：`{alignment.get('aligned')}`")
        for check in alignment.get("checks") or []:
            lines.append(
                f"- `{check.get('check_id')}`：result=`{check.get('result')}`，"
                f"applied=`{check.get('applied')}` {check.get('comment', '')}"
            )

        version = payload.get("version_check") or {}
        lines += ["", "### 版本校验（AI）", ""]
        lines.append(
            f"- expected=`{version.get('expected')}`，"
            f"found=`{version.get('found')}`，ok=`{version.get('ok')}`"
        )

        tests = payload.get("test_script") or {}
        lines += ["", "### 测试脚本（AI）", ""]
        lines.append(
            f"- present=`{tests.get('present')}`，adequate=`{tests.get('adequate')}`，"
            f"path=`{tests.get('path')}`"
        )
        for issue in tests.get("issues") or []:
            lines.append(f"- {issue}")
    else:
        lines += ["", "> dry-run：未调用 AI，以上为 Harness 确定性结论。"]

    if fix_payload:
        lines += ["", "### 修复（AI）", ""]
        if pr_url:
            lines.append(f"- PR：{pr_url}")
        elif branch:
            lines.append(
                f"- 分支：`{branch}`（已推送，通过双架构原生校验后开 PR）"
            )
        else:
            lines.append("- 修复结果与现状一致，未产生 PR")
        lines.append(f"- 摘要：{fix_payload.get('summary')}")
        for change in fix_payload.get("changes") or []:
            lines.append(f"- {change}")

    lines += ["", "### Harness 确定性发现", ""]
    if findings:
        for finding in findings:
            lines.append(
                f"- **{finding['severity']}** `{finding['code']}`：{finding['message']}"
            )
    else:
        lines.append("- 未发现确定性问题")

    lines += [
        "",
        "> 审计报告只读；修复通过独立分支与 PR 交付，不直接改主分支。",
        "",
    ]
    return "\n".join(lines)


def run(
    item: dict,
    *,
    repo_dir: Path,
    out_dir: Path,
    dry_run: bool,
    deliver: bool = False,
    prepare: bool = False,
) -> int:
    context = collect_context(repo_dir, item)
    findings = deterministic_findings(context)
    summary = deterministic_summary(context, findings)
    payload = None if dry_run else run_agent_audit(context, findings, repo_dir)

    fix_payload: dict | None = None
    pr_url = ""
    branch = ""
    if payload is not None and deliver:
        fix_payload = run_agent_fix(context, findings, payload, repo_dir)
        test_paths = ensure_test_script(repo_dir, context)
        if test_paths:
            # 测试已补上，PR 文案与交接文件不再保留 test.missing。
            findings = [f for f in findings if f["component"] != "tests"]
        pr_url = deliver_fix(
            repo_dir,
            context,
            findings,
            payload,
            fix_payload,
            extra_paths=test_paths,
        )
    elif payload is not None and prepare:
        # 只推到修复分支，PR 留给双架构原生校验通过后的 deliver job
        fix_payload = run_agent_fix(context, findings, payload, repo_dir)
        test_paths = ensure_test_script(repo_dir, context)
        if test_paths:
            findings = [f for f in findings if f["component"] != "tests"]
        branch, push_repo, changed = push_fix(
            repo_dir, context, fix_payload, extra_paths=test_paths
        )
        write_task_spec(out_dir, context, item)
        if changed:
            write_delivery(
                out_dir,
                item,
                context,
                findings,
                payload,
                fix_payload,
                branch,
                push_repo,
                changed,
            )
        _emit_output(
            has_changes="true" if changed else "false",
            branch=branch,
            push_repo=push_repo,
        )
        log_stage(
            "upgrade-audit",
            f"{context['app']}: pushed={branch} changed={changed}",
        )

    report = render_markdown(
        context, findings, summary, payload, fix_payload, pr_url, branch
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    document = {
        "item": item,
        "context": {key: value for key, value in context.items() if key != "test_scripts"},
        "test_scripts": [script["path"] for script in context["test_scripts"]],
        "deterministic_findings": findings,
        "deterministic_summary": summary,
        "ai": payload,
        "fix": fix_payload,
        "pr_url": pr_url,
        "markdown": report,
    }
    (out_dir / "audit.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "audit.md").write_text(report, encoding="utf-8")
    print(report)

    step_summary = os.environ.get("GITHUB_STEP_SUMMARY", "")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as handle:
            handle.write(report + "\n")
    log_stage(
        "upgrade-audit",
        f"{context['app']}: done dry_run={dry_run} deliver={deliver} "
        f"findings={len(findings)} verdict={(payload or {}).get('verdict')} "
        f"pr={pr_url or 'none'}",
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--item", default="", help="upgrade_scan audits 条目 JSON")
    parser.add_argument(
        "--repo", default=os.environ.get("SOURCE_REPO_DIR", DEFAULT_SOURCE_REPO_DIR)
    )
    parser.add_argument(
        "--out",
        default=os.path.join(os.environ.get("RUNNER_TEMP", PROJECT_ROOT), "audit"),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只输出确定性检查与提示上下文，不调用 AI",
    )
    parser.add_argument(
        "--prepare",
        action="store_true",
        help="审计+修复并推送分支，但不创建 PR（等双架构原生校验）",
    )
    parser.add_argument(
        "--deliver",
        action="store_true",
        help="审计后调用修复 Agent，推送分支并创建 PR",
    )
    parser.add_argument(
        "--open-pr",
        action="store_true",
        help="从 delivery.json 创建修复 PR（分支已由 --prepare 推送）",
    )
    parser.add_argument(
        "--delivery",
        default="",
        help="delivery.json 路径（默认 <out>/delivery.json）",
    )
    args = parser.parse_args()

    if args.open_pr:
        delivery = Path(args.delivery or (Path(args.out) / "delivery.json"))
        if not delivery.is_file():
            raise SystemExit(f"delivery.json not found: {delivery}")
        print(open_pr_from_delivery(delivery))
        return 0

    if not args.item:
        raise SystemExit("--item is required unless --open-pr is used")
    repo_dir = Path(args.repo)
    if not repo_dir.is_dir():
        raise SystemExit(f"target repo clone not found: {repo_dir}")
    return run(
        json.loads(args.item),
        repo_dir=repo_dir,
        out_dir=Path(args.out),
        dry_run=args.dry_run,
        deliver=args.deliver,
        prepare=args.prepare,
    )


if __name__ == "__main__":
    sys.exit(main())
