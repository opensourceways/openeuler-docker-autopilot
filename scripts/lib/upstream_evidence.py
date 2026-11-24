#!/usr/bin/env python3
"""上游证据适配层（场景二自动升级）。

看板 ``version/resolve`` 目前只返回版本号，后续会补充它采集到的上游证据。
本模块因此做两件事：

1. **适配**：已知字段归纳成结构化 evidence，**未知字段原样保留**——接口后续加
   字段不用改 workflow。
2. **自探兜底**：证据缺失时自己探测上游是否真的存在该版本（tag / release /
   源码归档是否可下载），把结果一并写进 PR。

证据只作 AI 参考与 PR 留痕，**不参与门禁判定**：能不能升级仍以双架构原生构建 +
功能测试的结果为准。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.parse import urlparse

import requests

_HEADERS = {
    "User-Agent": "openeuler-autopilot/1.0 (+https://github.com/opensourceways)",
    "Accept": "application/vnd.github+json",
}
_PROBE_TIMEOUT_SECONDS = 10

_KNOWN_FIELDS = (
    "tag",
    "tag_url",
    "commit_sha",
    "source",
    "fetched_at",
    "repo_url",
    "owner",
    "repo",
    "version",
    "display_version",
    "name",
)
# 看板侧可能用这些键承载「采集到的上游证据」；命中即提升为 collector 列表。
_COLLECTOR_KEYS = ("evidence", "upstream_evidence", "checks", "items")

_OWNER_REPO_RE = re.compile(r"github\.com/([^/]+)/([^/#?]+)", re.IGNORECASE)


def normalize(payload: dict[str, Any] | None) -> dict[str, Any]:
    """把看板返回归纳成 evidence；未知字段原样透传在 ``raw``。"""
    payload = payload or {}
    evidence: dict[str, Any] = {field: payload.get(field) for field in _KNOWN_FIELDS}
    evidence["version"] = payload.get("version")
    evidence["collector"] = _collector_entries(payload)
    evidence["raw"] = {
        key: value
        for key, value in payload.items()
        if key not in _KNOWN_FIELDS and key not in _COLLECTOR_KEYS
    }
    return evidence


def from_issue_payload(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """把 Issue 正文里的完整上游证据 JSON 归一化成内部 evidence。

    保留结构化字段供 Agent / PR 渲染，同时把原始对象放进 ``raw``，接口后续
    新增字段无需改解析。
    """
    payload = payload or {}
    software = payload.get("software")
    upstream = payload.get("upstream_evidence")
    software = software if isinstance(software, Mapping) else {}
    upstream = upstream if isinstance(upstream, Mapping) else {}
    entry = upstream.get("evidence")
    return {
        "source": "gitcode-issue",
        "name": software.get("name"),
        "repo_url": software.get("repo_url"),
        "version": software.get("version"),
        "support_level": upstream.get("support_level"),
        "collector": [dict(entry)] if isinstance(entry, Mapping) else [],
        "l3_evidence": payload.get("l3_evidence"),
        "install_candidates": list(payload.get("install_candidates") or []),
        "raw": {
            "software": dict(software),
            "upstream_evidence": {
                key: value
                for key, value in upstream.items()
                if key != "evidence"
            },
        },
    }


_INSTALL_MODES = {"source", "binary"}


def install_mode(evidence: Mapping[str, Any] | None) -> str:
    """从 ``install_candidates`` 推导候选安装方式（仅作兜底）。

    只要候选里出现 ``type=binary``，就按二进制候选处理；否则按源码候选。
    最终采用哪种方式由 Agent 根据实际 Dockerfile 决定。
    """
    candidates = (evidence or {}).get("install_candidates") or []
    if isinstance(candidates, list):
        for candidate in candidates:
            if (
                isinstance(candidate, Mapping)
                and str(candidate.get("type") or "").strip().lower()
                == "binary"
            ):
                return "binary"
    return "source"


def normalize_install_mode(value: object) -> str:
    """把 Agent 返回的安装方式归一化；非法值返回空串。"""
    mode = str(value or "").strip().lower()
    return mode if mode in _INSTALL_MODES else ""


def resolved_install_mode(item: Mapping[str, Any] | None) -> str:
    """PR 元数据使用的安装方式：优先 Agent 根据最终 Dockerfile 返回的值。"""
    item = item or {}
    mode = normalize_install_mode(item.get("install_mode"))
    if mode:
        return mode
    return install_mode(item.get("evidence"))


def render_install_section(evidence: Mapping[str, Any] | None) -> str:
    """Dockerfile 生成/修复提示：候选安装方式（Agent 最终决定）。

    只给 Dockerfile 使用；测试生成等其它提示仍走 :func:`render_prompt`，不受影响。
    """
    evidence = evidence or {}
    candidates = evidence.get("install_candidates") or []
    lines = [
        "",
        "## Install candidates (reference for the Dockerfile)",
        "",
        "- install_candidates 是候选安装方式，仅供参考；"
        "最终由你根据该版本实际可用的产物与构建结果决定：",
    ]
    if isinstance(candidates, list) and candidates:
        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                continue
            lines.append(
                f"  - type=`{candidate.get('type')}` "
                f"url={candidate.get('url')} "
                f"artifact=`{candidate.get('artifact')}`"
            )
    else:
        lines.append("  - （未提供候选，按上游源码仓库的默认构建方式处理）")
    lines += [
        "- 若最终采用 binary：直接下载/解压/安装该制品，**不要从源码编译**；",
        "- 若最终采用 source：按源码候选或上游源码仓库编译安装。",
        "- 该选择只约束 Dockerfile；不要为它改动测试脚本、README 或元数据。",
        '- 在最终 JSON 返回 `install_mode`（`"source"` 或 `"binary"`），'
        "必须与最终 Dockerfile 的实际做法一致。",
    ]
    return "\n".join(lines) + "\n"


def for_non_dockerfile(evidence: Mapping[str, Any] | None) -> dict[str, Any]:
    """去掉安装候选的证据副本：安装方式只作用于 Dockerfile。

    测试生成等场景不需要、也不应该被 ``install_candidates`` 影响。
    """
    copy = dict(evidence or {})
    copy.pop("install_candidates", None)
    return copy


def _collector_entries(payload: dict[str, Any]) -> list[Any]:
    for key in _COLLECTOR_KEYS:
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            return [value]
    return []


def _owner_repo(payload: dict[str, Any]) -> tuple[str, str] | None:
    owner = str(payload.get("owner") or "").strip()
    repo = str(payload.get("repo") or "").strip()
    if owner and repo:
        return owner, repo
    repo_url = str(payload.get("repo_url") or "")
    match = _OWNER_REPO_RE.search(repo_url)
    if match:
        return match.group(1), match.group(2).removesuffix(".git")
    return None


def _github_get(url: str) -> int | None:
    try:
        response = requests.get(url, headers=_HEADERS, timeout=_PROBE_TIMEOUT_SECONDS)
    except requests.RequestException:
        return None
    return response.status_code


def _github_head(url: str) -> int | None:
    try:
        response = requests.head(
            url, headers=_HEADERS, timeout=_PROBE_TIMEOUT_SECONDS, allow_redirects=True
        )
    except requests.RequestException:
        return None
    return response.status_code


def probe(payload: dict[str, Any] | None) -> dict[str, Any]:
    """自探上游是否真的存在该版本；探测失败只记录，不影响升级主流程。"""
    payload = payload or {}
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    tag = str(payload.get("tag") or "").strip()

    location = _owner_repo(payload)
    if not location:
        return {
            "source": "self-probe",
            "status": "skipped",
            "reason": "上游不是可解析的 GitHub 仓库（无 owner/repo）",
            "checked_at": checked_at,
        }
    if not tag:
        return {
            "source": "self-probe",
            "status": "skipped",
            "reason": "看板未返回 tag",
            "checked_at": checked_at,
        }

    owner, repo = location
    tag_exists = _github_get(f"https://api.github.com/repos/{owner}/{repo}/git/ref/tags/{tag}")
    release_exists = _github_get(f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{tag}")
    archive_url = f"https://github.com/{owner}/{repo}/archive/refs/tags/{tag}.tar.gz"
    archive_status = _github_head(archive_url)

    tag_ok = tag_exists == 200
    archive_ok = archive_status in (200, 302)
    if tag_ok and archive_ok:
        status = "ok"
    elif tag_ok or archive_ok:
        status = "partial"
    else:
        status = "missing"

    return {
        "source": "self-probe",
        "status": status,
        "tag": tag,
        "tag_exists": tag_ok,
        "release_exists": release_exists == 200,
        "archive_url": archive_url,
        "archive_status": archive_status,
        "checked_at": checked_at,
    }


def render_markdown(evidence: dict[str, Any] | None) -> str:
    """PR 正文里的「上游证据」段。"""
    evidence = evidence or {}
    if evidence.get("source") == "gitcode-issue":
        return _render_issue_markdown(evidence)
    if evidence.get("source") == "manual":
        return _render_manual_markdown(evidence)
    probe_result = evidence.get("probe") or {}
    collector = evidence.get("collector") or []
    raw = evidence.get("raw") or {}

    lines = ["## 上游证据", ""]
    lines.append(f"- 版本来源：`{evidence.get('source') or 'unknown'}`")
    if evidence.get("tag"):
        lines.append(f"- 上游 tag：`{evidence['tag']}`")
    if evidence.get("tag_url"):
        lines.append(f"- 版本落地页：{evidence['tag_url']}")
    if evidence.get("commit_sha"):
        lines.append(f"- commit：`{evidence['commit_sha']}`")
    if evidence.get("fetched_at"):
        lines.append(f"- 看板获取时间：{evidence['fetched_at']}")
    lines.append(
        "- 看板采集证据："
        + (f"{len(collector)} 条（见下）" if collector else "本次未返回（看板未提供或抓取失败）")
    )

    if probe_result:
        lines += ["", "### 自探结果", ""]
        lines.append(f"- 状态：`{probe_result.get('status')}`")
        for key, label in (
            ("tag_exists", "tag 存在"),
            ("release_exists", "release 存在"),
            ("archive_status", "源码归档 HTTP 状态"),
        ):
            if key in probe_result:
                value = probe_result.get(key)
                lines.append(f"- {label}：`{value}`")
        if probe_result.get("archive_url"):
            lines.append(f"- 源码归档：{probe_result['archive_url']}")
        if probe_result.get("reason"):
            lines.append(f"- 跳过原因：{probe_result['reason']}")

    if collector:
        lines += ["", "### 看板采集明细", "", "```json"]
        lines.append(_json_block(collector))
        lines.append("```")

    if raw:
        lines += ["", "### 其它字段（接口新增字段透传）", "", "```json"]
        lines.append(_json_block(raw))
        lines.append("```")

    lines += ["", "> 证据仅作参考，是否可用以双架构原生构建 + 功能测试结果为准。", ""]
    return "\n".join(lines)


def _render_manual_markdown(evidence: dict[str, Any]) -> str:
    """手动提供版本时的 PR 证据段：只列输入，不冒充看板采集结果。"""
    lines = ["## 升级来源", ""]
    lines.append(f"- 版本：`{evidence.get('version') or 'unknown'}`")
    if evidence.get("tag"):
        lines.append(f"- 上游 tag：`{evidence['tag']}`")
    if evidence.get("repo_url"):
        lines.append(f"- 上游仓库：{evidence['repo_url']}")
    lines.append("- 来源：清单手动提供（未查询看板）")
    lines += [
        "",
        "> 版本由人工提供，是否可用以双架构原生构建 + 功能测试结果为准。",
        "",
    ]
    return "\n".join(lines)


def _render_manual_prompt(evidence: dict[str, Any]) -> str:
    parts = [
        "## Upgrade input (provided manually; reference only)",
        "- source: manual",
        f"- version: {evidence.get('version') or 'unknown'}",
        f"- tag: {evidence.get('tag') or 'unknown'}",
        f"- repo_url: {evidence.get('repo_url') or 'unknown'}",
        "- 版本由人工提供，未查询看板；最终以上游仓库与构建结果为准。",
    ]
    return "\n".join(parts)


def render_prompt(evidence: dict[str, Any] | None) -> str:
    """注入生成提示的紧凑版证据（给 AI 参考）。"""
    evidence = evidence or {}
    if evidence.get("source") == "gitcode-issue":
        return _render_issue_prompt(evidence)
    if evidence.get("source") == "manual":
        return _render_manual_prompt(evidence)
    probe_result = evidence.get("probe") or {}
    collector = evidence.get("collector") or []
    parts = [
        "## Upstream evidence (reference only)",
        f"- source: {evidence.get('source') or 'unknown'}",
        f"- tag: {evidence.get('tag') or 'unknown'}",
        f"- tag_url: {evidence.get('tag_url') or 'unknown'}",
        f"- commit_sha: {evidence.get('commit_sha') or 'unknown'}",
    ]
    if probe_result:
        parts.append(f"- self-probe status: {probe_result.get('status')}")
        if "tag_exists" in probe_result:
            parts.append(f"- tag exists: {probe_result.get('tag_exists')}")
        if "archive_status" in probe_result:
            parts.append(f"- archive HTTP status: {probe_result.get('archive_status')}")
    if collector:
        parts.append("")
        parts.append(
            f"### Dashboard checks ({len(collector)} entries; each entry is one "
            "collected fact, not a gate)"
        )
        parts.extend(_render_collector(collector))
    raw = evidence.get("raw") or {}
    if raw:
        parts += ["", "### Other dashboard fields (pass-through)", "", "```json"]
        parts.append(_json_block(raw))
        parts.append("```")
    parts.append(
        "- 该证据只作参考，最终是否需要特殊构建参数以上游仓库与构建结果为准。"
    )
    return "\n".join(parts)


def _render_issue_prompt(evidence: dict[str, Any]) -> str:
    parts = [
        "## Upstream evidence (from the triggering Issue; reference only)",
        *_issue_evidence_lines(evidence),
        "",
        "### Evidence entries",
        *(_render_collector(evidence.get("collector") or []) or ["- (empty)"]),
        *_issue_candidate_lines(evidence),
        *_issue_l3_lines(evidence),
        "",
        "- 证据来自触发 Issue，只作参考；最终以上游源码、安装候选与双架构构建结果为准。",
    ]
    return "\n".join(parts)


def _render_issue_markdown(evidence: dict[str, Any]) -> str:
    lines = ["## 上游证据（来自触发 Issue）", ""]
    lines.extend(_issue_evidence_lines(evidence))
    lines += ["", "### 采集证据", ""]
    lines.extend(_render_collector(evidence.get("collector") or []) or ["- 无"])
    lines.extend(_issue_candidate_lines(evidence))
    lines.extend(_issue_l3_lines(evidence))
    lines += ["", "> 证据只作参考，是否可用以双架构原生构建 + 功能测试结果为准。", ""]
    return "\n".join(lines)


def _issue_evidence_lines(evidence: dict[str, Any]) -> list[str]:
    return [
        "- 证据来源：触发 Issue",
        f"- 上游仓库：{evidence.get('repo_url') or 'unknown'}",
        f"- 版本：`{evidence.get('version') or 'unknown'}`",
        f"- 证据等级：`{evidence.get('support_level') or 'unknown'}`",
    ]


def _issue_candidate_lines(evidence: dict[str, Any]) -> list[str]:
    candidates = evidence.get("install_candidates") or []
    if not candidates:
        return []
    lines = ["", f"### 安装候选（{len(candidates)} 条）", ""]
    for candidate in candidates[:10]:
        if not isinstance(candidate, Mapping):
            continue
        lines.append(
            f"- `{candidate.get('type')}` {candidate.get('url')} "
            f"artifact=`{candidate.get('artifact')}`"
        )
    return lines


def _issue_l3_lines(evidence: dict[str, Any]) -> list[str]:
    l3 = evidence.get("l3_evidence")
    if not l3:
        return ["", "### L3 openEuler 镜像证据", "", "- 本次未提供"]
    return ["", "### L3 openEuler 镜像证据", "", "```json", _json_block(l3), "```"]


def _render_collector(entries: list[Any]) -> list[str]:
    """把看板证据渲染成可读条目；excerpt 截断，避免撑爆提示。"""
    lines: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        check = entry.get("check_id") or entry.get("check") or "unknown"
        result = entry.get("result") or entry.get("status") or "unknown"
        fields = [f"- `{check}`: result=`{result}`"]
        for key, label in (
            ("support_level", "level"),
            ("artifact", "artifact"),
            ("test_depth", "test_depth"),
            ("nearest_version", "nearest_version"),
            ("matched_version", "matched_version"),
            ("checked_at", "checked_at"),
            ("assessment_id", "assessment"),
        ):
            value = entry.get(key)
            if value:
                fields.append(f"{label}=`{value}`")
        line = " ".join(fields)
        excerpt = str(entry.get("excerpt") or "").strip()
        if excerpt:
            line += f"\n  excerpt: {excerpt[:600]}"
        source_url = str(entry.get("source_url") or "").strip()
        if source_url:
            line += f"\n  source: {source_url}"
        workflows = entry.get("ci_workflows")
        if isinstance(workflows, list):
            for workflow in workflows[:5]:
                if not isinstance(workflow, dict):
                    continue
                path = workflow.get("workflow_path") or "unknown"
                depth = workflow.get("test_depth") or "unknown"
                url = workflow.get("workflow_url") or ""
                run_url = workflow.get("workflow_run_url") or ""
                line += f"\n  ci: `{path}` (test_depth=`{depth}`) {url}".rstrip()
                if run_url:
                    line += f"\n  ci run: {run_url}"
        lines.append(line)
    return lines


def _json_block(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, indent=2)[:4000]
