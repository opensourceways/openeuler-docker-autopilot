#!/usr/bin/env python3
"""
Stage: 场景二「已是最新版本」的 AI 审计（upgrade_audit）

当看板解析出的最新版本在目标仓已经存在时，不再直接跳过，而是审计现有镜像：

1. Dockerfile 是否有问题（版本/构建源/依赖/运行入口等）；
2. Dockerfile 是否按上游证据构建（tag / commit / L1 证据包 / 自探结果）；
3. 构建出的镜像版本是否正确（Dockerfile ARG、clone tag、meta.yml 是否一致）；
4. 是否有功能测试脚本，脚本质量是否足够。

先跑确定性检查（版本、tag、meta、测试脚本存在性），再把 Dockerfile、meta.yml、
测试脚本和上游证据一起交给 ``upgrade_auditor`` Agent 做语义审计。
``--dry-run`` 只输出确定性检查与将发送给 Agent 的上下文，不调用 AI。

输入: --item '<json>'（upgrade_scan 的 audits 条目）
环境: SOURCE_REPO_DIR（默认 PROJECT_ROOT/source-repo）、AI_API_KEY、OPENCODE_BIN
输出: --out <dir> 下的 audit.json / audit.md；同时写入 GITHUB_STEP_SUMMARY
退出码: 0 审计完成（无论是否发现问题）；AI 调用/契约失败 → 1
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

from scripts.lib import ai_provider, upstream_evidence  # noqa: E402
from scripts.lib.agent_runtime import run_agent  # noqa: E402
from scripts.lib.stage_common import (  # noqa: E402
    agent_prompt_file,
    log_stage,
)
from scripts.lib.task_spec import _os_tag  # noqa: E402

DEFAULT_SOURCE_REPO_DIR = os.path.join(PROJECT_ROOT, "source-repo")
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
    info = _read(app_dir / "doc" / "image-info.yml")
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
        "image_info": _truncate(info[:4000]),
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
        tags = [value for value in args["TAG"] if not value.startswith("$")]
        clone_refs = [
            value
            for value in _CLONE_BRANCH_RE.findall(dockerfile)
            if not value.startswith("$")
        ]
        observed = tags or clone_refs
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
    parts.append(
        "\n\n## Final response contract\n\n"
        "最终响应必须恰好是一个 JSON 对象，包含以下键："
        "success(bool)、verdict(ok|issues|critical)、"
        "dockerfile_issues(list)、evidence_alignment(object)、"
        "version_check(object)、test_script(object)、summary(str)、"
        "error(null 或 str)。不得修改工作区文件；只返回 JSON。\n"
    )
    return "".join(parts)


def _git(repo_dir: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo_dir), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _reset_workspace(repo_dir: Path) -> None:
    _git(repo_dir, "checkout", "--", ".")
    _git(repo_dir, "clean", "-fd")


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


def render_markdown(
    context: dict, findings: list[dict], summary: dict, payload: dict | None
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
        "> 审计只读，不修改目标仓；AI 结论用于人工判断，不自动开 PR。",
        "",
    ]
    return "\n".join(lines)


def run(item: dict, *, repo_dir: Path, out_dir: Path, dry_run: bool) -> int:
    context = collect_context(repo_dir, item)
    findings = deterministic_findings(context)
    summary = deterministic_summary(context, findings)
    payload = None if dry_run else run_agent_audit(context, findings, repo_dir)

    report = render_markdown(context, findings, summary, payload)
    out_dir.mkdir(parents=True, exist_ok=True)
    document = {
        "item": item,
        "context": {key: value for key, value in context.items() if key != "test_scripts"},
        "test_scripts": [script["path"] for script in context["test_scripts"]],
        "deterministic_findings": findings,
        "deterministic_summary": summary,
        "ai": payload,
        "markdown": report,
    }
    (out_dir / "audit.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "audit.md").write_text(report, encoding="utf-8")
    print(report)

    summary = os.environ.get("GITHUB_STEP_SUMMARY", "")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(report + "\n")
    log_stage(
        "upgrade-audit",
        f"{context['app']}: done dry_run={dry_run} "
        f"findings={len(findings)} verdict={(payload or {}).get('verdict')}",
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--item", required=True, help="upgrade_scan audits 条目 JSON")
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
    args = parser.parse_args()

    repo_dir = Path(args.repo)
    if not repo_dir.is_dir():
        raise SystemExit(f"target repo clone not found: {repo_dir}")
    return run(
        json.loads(args.item),
        repo_dir=repo_dir,
        out_dir=Path(args.out),
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())
