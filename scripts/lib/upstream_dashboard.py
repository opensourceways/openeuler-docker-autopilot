#!/usr/bin/env python3
"""upstream-dashboard 版本解析客户端（场景二自动升级的版本源）。

对外接口见 https://github.com/opensourceways/upstream-dashboard/blob/main/docs/external-api.md：

    GET {base}/api/v1/version/resolve?name=<软件名>[&version=<指定版本>]

返回值**原样透传**——除版本号外，看板后续还会补充上游证据字段，这里不做字段裁剪，
证据的归纳交给 :mod:`scripts.lib.upstream_evidence`。

错误语义按文档：
- 400（入参非法）/ 404（软件不存在）是确定性结果 → 返回 None，调用方跳过该软件；
- 502（看板调 GitHub 失败）→ 有限重试；
- 503（看板侧未配置 token / 迁移未完成）及其它异常 → 抛 :class:`DashboardError`，
  让运行失败而不是静默产出一批错误的升级。
"""

from __future__ import annotations

import os
import time
from typing import Any

import requests

DEFAULT_BASE = "https://upstream-dashboard.test.osinfra.cn"
DEFAULT_TIMEOUT_SECONDS = 30
_EVIDENCE_PAGE_SIZE = 50
# 场景二的证据包固定取 L1 的 3 条：上游 ARM CI、文档声明、release 产物。
_EVIDENCE_LEVEL = "L1"

# 看板测试环境前面有 WAF：默认 python-requests UA 会被拒绝（HTTP 418），
# 与 scripts/harness/testgen_scan.py 的看板访问口径保持一致。
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

_RETRYABLE_STATUS = {502}
_MAX_ATTEMPTS = 3


class DashboardError(RuntimeError):
    """看板返回了无法通过重试恢复的错误。"""


def base_url() -> str:
    """看板地址：环境变量 / 仓库 Variable 覆盖，默认测试环境。"""
    return (os.environ.get("UPSTREAM_DASHBOARD_BASE") or DEFAULT_BASE).rstrip("/")


def resolve_version(
    name: str,
    version: str | None = None,
    *,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any] | None:
    """解析软件的上游版本信息；确定性失败（400/404）返回 None。

    返回原始 JSON（含 `version` / `tag` / `tag_url` / `commit_sha` / `source` /
    `blocked_reason` / `fetched_at`，以及接口后续新增的任意字段）。
    """
    params: dict[str, str] = {"name": name}
    if version:
        params["version"] = version
    url = f"{base_url()}/api/v1/version/resolve"

    last_error: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            response = requests.get(
                url, params=params, headers=_HEADERS, timeout=timeout
            )
        except requests.RequestException as error:
            last_error = error
            if attempt < _MAX_ATTEMPTS - 1:
                time.sleep(1.5 * (2 ** attempt))
                continue
            raise DashboardError(f"{name}: 请求看板失败: {error}") from error

        if response.status_code in (400, 404):
            return None
        if response.status_code in _RETRYABLE_STATUS:
            last_error = requests.HTTPError(
                f"HTTP {response.status_code} from {url}", response=response
            )
            if attempt < _MAX_ATTEMPTS - 1:
                time.sleep(1.5 * (2 ** attempt))
                continue
            raise DashboardError(f"{name}: 看板持续返回 {response.status_code}") from last_error
        if response.status_code >= 400:
            detail = ""
            try:
                detail = str(response.json().get("detail") or "")
            except ValueError:
                detail = (response.text or "")[:200]
            raise DashboardError(
                f"{name}: 看板返回 {response.status_code}"
                + (f"（{detail}）" if detail else "")
            )

        payload = response.json()
        if not isinstance(payload, dict):
            raise DashboardError(f"{name}: 看板返回的不是 JSON 对象")
        return payload

    raise DashboardError(f"{name}: 看板请求失败: {last_error}")


def is_usable(payload: dict[str, Any] | None) -> bool:
    """`blocked_reason` 为 null 才能直接使用解析结果。"""
    return bool(payload) and payload.get("blocked_reason") is None


def _normalize(value: Any) -> str:
    return str(value or "").strip().lstrip("vV").casefold()


def fetch_evidence(
    name: str,
    version: str = "",
    *,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> list[dict[str, Any]]:
    """取看板采集到的上游证据包（固定 L1 的 3 条 check）。

    ``version/resolve`` 只返回版本号，证据在 ``/api/v1/software`` 的
    ``versions[].levels[].evidence`` 里；场景二只取 L1：
    ``kp.l1.arm_ci`` / ``kp.l1.doc_declared`` / ``kp.l1.release_artifact``。
    证据只作 AI 参考与 PR 留痕，因此这里任何失败都返回空列表，绝不阻断升级主流程。
    """
    url = f"{base_url()}/api/v1/software"
    try:
        response = requests.get(
            url,
            params={"name": name, "page_size": _EVIDENCE_PAGE_SIZE},
            headers=_HEADERS,
            timeout=timeout,
        )
    except requests.RequestException:
        return []
    if response.status_code != 200:
        return []
    try:
        payload = response.json()
    except ValueError:
        return []
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return []

    software = _pick_software(items, name)
    if software is None:
        return []
    return _evidence_entries(software, version)


def _pick_software(
    items: list[Any], name: str
) -> dict[str, Any] | None:
    """按名字精确命中优先；模糊查询只返回一条时接受该条。"""
    wanted = str(name or "").strip().casefold()
    exact = [
        item
        for item in items
        if isinstance(item, dict)
        and str(item.get("name") or "").strip().casefold() == wanted
    ]
    if len(exact) == 1:
        return exact[0]
    if len(items) == 1 and isinstance(items[0], dict):
        return items[0]
    return exact[0] if exact else None


def _evidence_entries(
    software: dict[str, Any], version: str
) -> list[dict[str, Any]]:
    versions = software.get("versions")
    if not isinstance(versions, list):
        return []
    entry = _pick_version(versions, version, software.get("latest_version"))
    if entry is None:
        return []
    return _level_evidence(entry, _EVIDENCE_LEVEL)


def _level_evidence(
    entry: dict[str, Any], support_level: str
) -> list[dict[str, Any]]:
    """只取指定等级的 check；场景二的证据包固定用 L1 的 3 条。"""
    for level in entry.get("levels") or []:
        if not isinstance(level, dict):
            continue
        if str(level.get("support_level") or "").upper() != support_level:
            continue
        evidence: list[dict[str, Any]] = []
        for item in level.get("evidence") or []:
            if not isinstance(item, dict):
                continue
            enriched = dict(item)
            enriched.setdefault("support_level", level.get("support_level"))
            evidence.append(enriched)
        return evidence
    return []


def _pick_version(
    versions: list[Any], version: str, latest_version: Any
) -> dict[str, Any] | None:
    """优先精确版本，其次 latest_version，最后取有证据的最新发布版本。"""
    wanted = _normalize(version)
    if wanted:
        for entry in versions:
            if isinstance(entry, dict) and _normalize(entry.get("version")) == wanted:
                return entry

    latest = _normalize(latest_version)
    if latest:
        for entry in versions:
            if isinstance(entry, dict) and _normalize(entry.get("version")) == latest:
                return entry

    for version_type in ("latest_release", ""):
        for entry in versions:
            if not isinstance(entry, dict):
                continue
            if version_type and entry.get("version_type") != version_type:
                continue
            if _has_evidence(entry):
                return entry
    return None


def _has_evidence(entry: dict[str, Any]) -> bool:
    return bool(_level_evidence(entry, _EVIDENCE_LEVEL))
