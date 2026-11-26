"""Map a GitCode Issue title to its scenario.

场景二使用 ``【自动升级需求】upgrade <app> to <version> on openEuler <os>``，
场景一 / 三沿用 ``【new-image】`` / ``【oe-upgrade】``；旧标题
``【new-version】upgrade ...`` 继续按场景二处理。
"""

from __future__ import annotations

SCENARIO_NEW_IMAGE = "new-image"
SCENARIO_UPGRADE = "upgrade-version"
SCENARIO_OE_UPGRADE = "oe-upgrade"

AUTO_UPGRADE_TITLE_PREFIX = "【自动升级需求】"

TITLE_PREFIXES = {
    SCENARIO_UPGRADE: (AUTO_UPGRADE_TITLE_PREFIX, "【new-version】"),
    SCENARIO_NEW_IMAGE: ("【new-image】",),
    SCENARIO_OE_UPGRADE: ("【oe-upgrade】",),
}

# 这些标题由各自的旧 monitor 认领，统一入口必须跳过，避免同一 Issue 被两条路径
# 同时认领。``【自动升级需求】`` 只有统一入口处理，不在其中。
LEGACY_TITLE_PREFIXES = (
    "【new-image】",
    "【new-version】",
    "【oe-upgrade】",
)


class IssueRoutingError(ValueError):
    """Raised when an Issue title does not name exactly one scenario."""


def route_issue(title: str) -> str:
    """Return the scenario encoded in the Issue title prefix."""

    stripped = title.strip()
    for scenario, prefixes in TITLE_PREFIXES.items():
        if stripped.startswith(prefixes):
            return scenario
    raise IssueRoutingError(
        "无法判断场景：标题必须以 "
        "`【自动升级需求】upgrade <app> to <version> on openEuler <version>`、"
        "`【new-image】...` 或 `【oe-upgrade】...` 开头"
    )
