"""Render GitCode Issue result comments in one consistent layout.

三个场景（新增镜像 / 应用升级 / openEuler 升级）的结果评论共用这一套结构：

    ## <结论>

    - **场景**：...
    - **状态**：...
    - **Workflow**：...
    - **Pull request**：...      # 有 PR 时才有

    ### 摘要
    ### 失败摘要
    ### 证据
    ### <自定义小节>
"""

from __future__ import annotations

from collections.abc import Sequence

SCENARIO_NEW_IMAGE = "new-image"
SCENARIO_UPGRADE = "upgrade-version"
SCENARIO_OE_UPGRADE = "oe-upgrade"

SCENARIO_LABELS = {
    SCENARIO_NEW_IMAGE: "① 新增镜像",
    SCENARIO_UPGRADE: "② 应用自动升级",
    SCENARIO_OE_UPGRADE: "③ openEuler 版本升级",
}


def render_result_comment(
    *,
    scenario: str,
    headline: str,
    status: str,
    run_url: str = "",
    pr_url: str = "",
    summary_lines: Sequence[str] = (),
    extra_sections: Sequence[tuple[str, Sequence[str]]] = (),
    failure_summary: str = "",
    evidence: str = "",
    footer_lines: Sequence[str] = (),
) -> str:
    """Render one Issue result comment with the shared three-scenario layout."""

    lines = [
        f"## {headline.strip()}",
        "",
        f"- **场景**：{SCENARIO_LABELS.get(scenario, scenario)}",
        f"- **状态**：{status}",
    ]
    if run_url:
        lines.append(f"- **Workflow**：{run_url}")
    if pr_url:
        lines.append(f"- **Pull request**：{pr_url}")

    if summary_lines:
        lines.extend(("", "### 摘要", ""))
        lines.extend(summary_lines)

    for title, section_lines in extra_sections:
        lines.extend(("", f"### {title}", ""))
        lines.extend(section_lines or ["- 无"])

    if failure_summary.strip():
        lines.extend(("", "### 失败摘要", "", failure_summary.strip()))

    if evidence.strip():
        lines.extend(("", "### 证据", "", evidence.strip()))

    if footer_lines:
        lines.extend(("", *footer_lines))

    return "\n".join(lines)
