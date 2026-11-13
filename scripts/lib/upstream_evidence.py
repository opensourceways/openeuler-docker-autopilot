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
from typing import Any
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


def render_prompt(evidence: dict[str, Any] | None) -> str:
    """注入生成提示的紧凑版证据（给 AI 参考）。"""
    evidence = evidence or {}
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
            ("nearest_version", "nearest_version"),
            ("matched_version", "matched_version"),
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
        lines.append(line)
    return lines


def _json_block(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, indent=2)[:4000]
