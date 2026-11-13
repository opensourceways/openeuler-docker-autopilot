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
# 证据等级优先取 L1（上游 ARM CI、文档声明、release 产物）；看板对不同软件
# 给出的等级不同（kunpeng 域多为 L1，slurm 只有 L3，OpenCV 是 L4），没有 L1 时
# 回退到该版本实际存在的等级，否则这些软件永远拿不到证据。
_EVIDENCE_LEVEL = "L1"

# 看板测试环境前面有 WAF：默认 python-requests UA 会被拒绝（HTTP 418），
# 与 scripts/harness/testgen_scan.py 的看板访问口径保持一致。
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
_HTML_HEADERS = {
    "User-Agent": _HEADERS["User-Agent"],
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": _HEADERS["Accept-Language"],
    "Upgrade-Insecure-Requests": "1",
}
_SESSION = requests.Session()
_WARMED_BASE = ""

_RETRYABLE_STATUS = {502}
_MAX_ATTEMPTS = 3


class DashboardError(RuntimeError):
    """看板返回了无法通过重试恢复的错误。"""


def base_url() -> str:
    """看板地址：环境变量 / 仓库 Variable 覆盖，默认测试环境。"""
    return (os.environ.get("UPSTREAM_DASHBOARD_BASE") or DEFAULT_BASE).rstrip("/")


def _warm_up_cookies(timeout: int) -> None:
    """先访问首页拿 WAF 会话 Cookie；418 常见于缺少这一步。"""
    global _WARMED_BASE
    base = base_url()
    if _WARMED_BASE == base:
        return
    _WARMED_BASE = base
    try:
        _SESSION.get(f"{base}/", headers=_HTML_HEADERS, timeout=timeout)
    except requests.RequestException:
        pass


def _get(url: str, *, params: dict[str, str], timeout: int):
    """API 请求；遇到 WAF 418 时取一次首页 Cookie 后重试。"""
    headers = {**_HEADERS, "Referer": f"{base_url()}/"}
    cookies = _SESSION.cookies.get_dict() or None
    response = requests.get(
        url,
        params=params,
        headers=headers,
        cookies=cookies,
        timeout=timeout,
    )
    if response.status_code == 418:
        _warm_up_cookies(timeout)
        response = requests.get(
            url,
            params=params,
            headers=headers,
            cookies=_SESSION.cookies.get_dict() or None,
            timeout=timeout,
        )
    return response


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
            response = _get(url, params=params, timeout=timeout)
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
    """取看板采集到的上游证据包。

    ``version/resolve`` 只返回版本号，证据在 ``/api/v1/software`` 的
    ``versions[].levels[].evidence`` 里。优先取 L1（kunpeng 域通常是
    ``kp.l1.arm_ci`` / ``kp.l1.doc_declared`` / ``kp.l1.release_artifact``），
    该版本没有 L1 时回退到实际存在的等级（如 slurm 的 L3、OpenCV 的 L4）。
    证据只作 AI 参考与 PR 留痕，因此这里任何失败都返回空列表，绝不阻断升级主流程。
    """
    url = f"{base_url()}/api/v1/software"
    try:
        response = _get(
            url,
            params={"name": name, "page_size": _EVIDENCE_PAGE_SIZE},
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
    return _level_evidence(entry)


def _level_evidence(entry: dict[str, Any]) -> list[dict[str, Any]]:
    """取该版本的证据：优先 L1，没有 L1 时回退到实际存在的等级。"""
    levels = [
        level for level in entry.get("levels") or [] if isinstance(level, dict)
    ]
    preferred = [
        level
        for level in levels
        if str(level.get("support_level") or "").upper() == _EVIDENCE_LEVEL
    ]
    ordered = preferred + [level for level in levels if level not in preferred]
    for level in ordered:
        evidence: list[dict[str, Any]] = []
        for item in level.get("evidence") or []:
            if not isinstance(item, dict):
                continue
            enriched = dict(item)
            enriched.setdefault("support_level", level.get("support_level"))
            evidence.append(enriched)
        if evidence:
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
    return bool(_level_evidence(entry))
