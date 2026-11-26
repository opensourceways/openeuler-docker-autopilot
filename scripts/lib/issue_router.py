"""Route one GitCode image Issue to its scenario.

统一后的标题只保留 ``【镜像任务】`` 标记，不再承载参数；场景由正文的
``**任务类型（Type）：**`` 字段决定。旧标题（``【new-image】`` /
``【new-version】`` / ``【oe-upgrade】``）继续按前缀识别，永久兼容。
"""

from __future__ import annotations

import re

SCENARIO_NEW_IMAGE = "new-image"
SCENARIO_UPGRADE = "upgrade-version"
SCENARIO_OE_UPGRADE = "oe-upgrade"

UNIFIED_TITLE_PREFIX = "【镜像任务】"

LEGACY_TITLE_PREFIXES = {
    SCENARIO_NEW_IMAGE: "【new-image】",
    SCENARIO_UPGRADE: "【new-version】",
    SCENARIO_OE_UPGRADE: "【oe-upgrade】",
}


class IssueRoutingError(ValueError):
    """Raised when an Issue cannot be routed to exactly one scenario."""


_TYPE_LABEL = r"(?:任务类型\s*[（(]\s*Type\s*[）)]|Task\s*Type|Type)"
_TYPE_PATTERN = re.compile(
    rf"^\s*\*\*{_TYPE_LABEL}\s*[：:]?\*\*\s*[：:]?\s*(?P<value>.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

_TYPE_ALIASES = {
    SCENARIO_NEW_IMAGE: frozenset(
        {
            "new-image",
            "newimage",
            "new-mirror",
            "新建镜像",
            "新增镜像",
            "新增镜像需求",
        }
    ),
    SCENARIO_UPGRADE: frozenset(
        {
            "upgrade-version",
            "upgrade",
            "version-upgrade",
            "app-upgrade",
            "版本升级",
            "应用升级",
            "升级应用版本",
        }
    ),
    SCENARIO_OE_UPGRADE: frozenset(
        {
            "oe-upgrade",
            "os-upgrade",
            "openeuler-upgrade",
            "oe升级",
            "系统升级",
            "操作系统升级",
            "openeuler版本升级",
        }
    ),
}


def _normalize_type(value: str) -> str:
    # "new image" / "new_image" / "New-Image" 都收敛到同一个键。
    return re.sub(r"[\s_]+", "-", value.strip().lower())


def parse_issue_type(body: str) -> str | None:
    """Return the declared scenario, or None when the body has no Type field."""

    values = [match.group("value") for match in _TYPE_PATTERN.finditer(body)]
    if not values:
        return None
    if len(values) > 1:
        raise IssueRoutingError("duplicate 任务类型（Type） field")
    key = _normalize_type(values[0])
    for scenario, aliases in _TYPE_ALIASES.items():
        if key in aliases:
            return scenario
    raise IssueRoutingError(
        "unsupported 任务类型（Type）: "
        f"{values[0]!r}; expected new-image / upgrade-version / oe-upgrade"
    )


def is_unified_title(title: str) -> bool:
    return title.strip().startswith(UNIFIED_TITLE_PREFIX)


def route_issue(title: str, body: str) -> str:
    """Decide the scenario for one Issue.

    正文声明优先；没有声明时按旧标题前缀兜底；两者都没有则拒绝。
    """

    declared = parse_issue_type(body)
    stripped = title.strip()
    if declared is not None:
        for scenario, prefix in LEGACY_TITLE_PREFIXES.items():
            if stripped.startswith(prefix) and scenario != declared:
                raise IssueRoutingError(
                    "标题前缀与正文 Type 不一致："
                    f"{prefix.strip('【】')} vs {declared}"
                )
        return declared
    for scenario, prefix in LEGACY_TITLE_PREFIXES.items():
        if stripped.startswith(prefix):
            return scenario
    raise IssueRoutingError(
        "无法判断场景：正文缺少「任务类型（Type）」字段，标题也不是旧格式"
    )
