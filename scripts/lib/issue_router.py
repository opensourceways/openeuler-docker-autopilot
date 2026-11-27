"""Map a GitCode Issue title to its scenario.

三个场景的标题统一以 ``【自动升级需求】`` 开头，用紧随其后的关键字区分：

* 场景一（新增镜像）：``【自动升级需求】add <app> <version> docker image on openEuler <os>``
* 场景二（应用升级）：``【自动升级需求】upgrade <app> to <version> on openEuler <os>``
* 场景三（openEuler 升级）：``【自动升级需求】upgrade openEuler to <version>``

旧标题 ``【new-image】`` / ``【new-version】`` / ``【oe-upgrade】`` 继续按原场景处理。
"""

from __future__ import annotations

import re

SCENARIO_NEW_IMAGE = "new-image"
SCENARIO_UPGRADE = "upgrade-version"
SCENARIO_OE_UPGRADE = "oe-upgrade"

AUTO_UPGRADE_TITLE_PREFIX = "【自动升级需求】"

# 「upgrade openEuler to <版本>」必须先于通用的应用升级标题匹配，否则会被当成
# `upgrade <app> to <version>`。
_OE_UPGRADE_TITLE_RE = re.compile(
    r"^\s*【自动升级需求】\s*upgrade\s+openEuler\s+to\s+\S+\s*$",
    re.IGNORECASE,
)
_UPGRADE_TITLE_RE = re.compile(
    r"^\s*【自动升级需求】\s*upgrade\s+\S+\s+to\s+\S+\s+"
    r"on\s+openEuler\s+\S+\s*$",
    re.IGNORECASE,
)
_NEW_IMAGE_TITLE_RE = re.compile(
    r"^\s*【自动升级需求】\s*add\s+.+?\s+docker\s+image\s+"
    r"on\s+openEuler\s+\S+\s*$",
    re.IGNORECASE,
)

# 旧标题由各自的旧 monitor 认领，统一入口必须跳过，避免同一 Issue 被两条路径
# 同时认领。``【自动升级需求】`` 只有统一入口处理，不在其中。
LEGACY_TITLE_PREFIXES = (
    "【new-image】",
    "【new-version】",
    "【oe-upgrade】",
)
_LEGACY_ROUTES = {
    "【new-image】": SCENARIO_NEW_IMAGE,
    "【new-version】": SCENARIO_UPGRADE,
    "【oe-upgrade】": SCENARIO_OE_UPGRADE,
}


class IssueRoutingError(ValueError):
    """Raised when an Issue title does not name exactly one scenario."""


def route_issue(title: str) -> str:
    """Return the scenario encoded in the Issue title."""

    stripped = title.strip()
    if _OE_UPGRADE_TITLE_RE.fullmatch(stripped):
        return SCENARIO_OE_UPGRADE
    if _UPGRADE_TITLE_RE.fullmatch(stripped):
        return SCENARIO_UPGRADE
    if _NEW_IMAGE_TITLE_RE.fullmatch(stripped):
        return SCENARIO_NEW_IMAGE
    for prefix, scenario in _LEGACY_ROUTES.items():
        if stripped.startswith(prefix):
            return scenario
    raise IssueRoutingError(
        "无法判断场景：标题必须以 "
        "`【自动升级需求】add <app> <version> docker image on openEuler <version>`、"
        "`【自动升级需求】upgrade <app> to <version> on openEuler <version>` 或 "
        "`【自动升级需求】upgrade openEuler to <version>` 开头"
    )
