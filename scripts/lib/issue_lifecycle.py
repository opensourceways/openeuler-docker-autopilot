"""Policies for GitCode Issue lifecycle: claim, dispatch and finalize."""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from scripts.lib.gitcode_client import GitCodeResource
from scripts.lib.issue_router import (
    AUTO_UPGRADE_TITLE_PREFIX,
    LEGACY_TITLE_PREFIXES,
    SCENARIO_UPGRADE,
)
from scripts.lib.task_spec import TaskSpec


class IssueLifecycleError(RuntimeError):
    """Raised when an Issue cannot be selected or updated safely."""


class IssueOperationForbiddenError(IssueLifecycleError):
    """Raised when the controlled E2E operation is invoked out of scope."""


_SAFE_DYNAMIC_VALUE = re.compile(r"^[A-Za-z0-9._-]+$")
_NEW_IMAGE_TITLE = "【new-image】"
_UPGRADE_TITLE = "【new-version】"
# GitCode 的默认状态名是「待办的」；旧数据 / 自定义流程里也出现过「新建」。
_CLAIMABLE_ISSUE_STATUSES = frozenset({"新建", "待办的"})
# 已认领后可能停留的状态：需求类型用「已接纳」，任务类型没有该状态，用「进行中」。
_CLAIMED_ISSUE_STATUSES = frozenset({"已接纳", "进行中"})
_TASK_ISSUE_TYPE = "任务"
_UPGRADE_APP_RE = re.compile(
    r"^\s*【new-version】\s*upgrade\s+(?P<app>\S+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ClaimedIssue:
    number: int
    url: str
    task: TaskSpec


@dataclass(frozen=True)
class UpgradeRequest:
    """Scenario-two request parsed from one 【new-version】 Issue."""

    app: str
    version: str
    os_version: str
    source_url: str
    evidence: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class ClaimedUpgradeIssue:
    number: int
    url: str
    request: UpgradeRequest


@dataclass(frozen=True)
class ClaimedRoutedIssue:
    """One claimed auto-upgrade Issue and the scenario chosen for it."""

    number: int
    url: str
    scenario: str
    payload: Any


@dataclass(frozen=True)
class FailureIssueReport:
    task: TaskSpec
    failure_stage: str
    attempt_count: int
    terminal_delivery_error: bool
    architecture_status: Mapping[str, str]
    repair_summaries: tuple[str, ...]
    run_url: str
    artifact_url: str
    suggested_action: str

    def __post_init__(self) -> None:
        if not 0 <= self.attempt_count <= 3:
            raise ValueError("attempt_count must be between 0 and 3")
        if not self.failure_stage.strip():
            raise ValueError("failure_stage is required")
        if set(self.architecture_status) != {"x86_64", "aarch64"}:
            raise ValueError("architecture_status must cover x86_64 and aarch64")
        for field_name in ("run_url", "artifact_url"):
            value = getattr(self, field_name)
            if not value.startswith("https://"):
                raise ValueError(f"{field_name} must be an HTTPS URL")


def _marker(idempotency_key: str) -> str:
    return f"<!-- oe-autopilot-task:{idempotency_key} -->"


def _issue_number(issue: Mapping[str, object]) -> int:
    raw_number = issue.get("number", issue.get("iid"))
    try:
        number = int(raw_number)
    except (TypeError, ValueError) as error:
        raise IssueLifecycleError("Issue has no valid number") from error
    if number <= 0:
        raise IssueLifecycleError("Issue number must be positive")
    return number


def _issue_status(issue: Mapping[str, object]) -> str:
    detail = issue.get("issue_state_detail")
    if isinstance(detail, Mapping):
        title = str(detail.get("title", "")).strip()
        if title:
            return title
    return str(issue.get("issue_state", "")).strip()


def _is_claimable(issue: Mapping[str, object]) -> bool:
    return _issue_status(issue) in _CLAIMABLE_ISSUE_STATUSES


def _issue_type(issue: Mapping[str, object]) -> str:
    detail = issue.get("issue_type_detail")
    if isinstance(detail, Mapping):
        title = str(detail.get("title", "")).strip()
        if title:
            return title
    return str(issue.get("issue_type", "")).strip()


def _claimed_status(issue: Mapping[str, object]) -> str:
    # 任务类型的 Issue 状态机没有「已接纳」，认领后停在「进行中」。
    if _issue_type(issue) == _TASK_ISSUE_TYPE:
        return "进行中"
    return "已接纳"


def _issue_url(issue: Mapping[str, object]) -> str:
    return str(
        issue.get("html_url")
        or issue.get("web_url")
        or issue.get("url")
        or ""
    )


def _update_source_issue(
    *,
    client: Any,
    target_repo: str,
    issue: Mapping[str, object],
    issue_status: str,
    state: str,
) -> Any:
    return client.update_issue(
        target_repo=target_repo,
        number=_issue_number(issue),
        title=str(issue.get("title", "")),
        body=str(issue.get("body", "") or ""),
        state=state,
        issue_status=issue_status,
    )


def _load_evidence(path: Path, label: str) -> Mapping[str, object]:
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise IssueLifecycleError(f"{label} evidence is invalid") from error
    if not isinstance(payload, Mapping):
        raise IssueLifecycleError(f"{label} evidence must be an object")
    return payload


def _brief(value: object, *, limit: int = 500) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return "No summary recorded."
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _agent_stage_lines(generation_dir: Path) -> list[str]:
    stage_files = (
        ("image-creator.json", "Image Creator"),
        ("image-creator-precheck-repair.json", "Image Creator precheck repair"),
        ("testcase-creator.json", "Testcase Creator"),
        (
            "testcase-creator-precheck-repair.json",
            "Testcase Creator precheck repair",
        ),
        ("testcase-qa-round1.json", "Testcase QA round 1"),
        ("testcase-creator-round2.json", "Testcase Creator QA repair"),
        ("testcase-qa-round2.json", "Testcase QA round 2"),
    )
    lines: list[str] = []
    for filename, label in stage_files:
        path = generation_dir / filename
        if not path.is_file():
            continue
        report = _load_evidence(path, label)
        if "status" in report:
            status = _brief(report.get("status"), limit=40)
        else:
            status = "completed" if report.get("success") is True else "failed"
        lines.append(
            f"- {label}: `{status}` — {_brief(report.get('summary'))}"
        )
        issues = report.get("issues")
        if not isinstance(issues, list):
            continue
        for issue in issues[:3]:
            if not isinstance(issue, Mapping):
                continue
            severity = _brief(issue.get("severity", "unknown"), limit=30)
            file = _brief(issue.get("file"), limit=180) if issue.get("file") else ""
            location = f"`{file}`: " if file else ""
            lines.append(
                f"  - `{severity}` — {location}"
                f"{_brief(issue.get('description'))}"
            )
        if len(issues) > 3:
            lines.append(f"  - {len(issues) - 3} more issues are in the Artifact.")
    return lines


def _native_stage_lines(terminal: Mapping[str, object]) -> list[str]:
    architectures = terminal.get("architectures")
    if not isinstance(architectures, Mapping):
        raise IssueLifecycleError("terminal evidence has no architecture reports")
    lines: list[str] = []
    for architecture in ("x86_64", "aarch64"):
        report = architectures.get(architecture)
        if not isinstance(report, Mapping):
            raise IssueLifecycleError(
                f"terminal evidence is missing {architecture} report"
            )
        status = _brief(report.get("status", "unknown"), limit=40)
        failed_stage = _brief(report.get("failed_stage"), limit=80)
        failure = _brief(report.get("failure"))
        if status == "passed":
            lines.append(f"- Native {architecture}: `passed`.")
        else:
            lines.append(
                f"- Native {architecture}: `{status}` at `{failed_stage}` — "
                f"{failure}"
            )
    return lines


def _fixer_stage_lines(evidence_dir: Path) -> list[str]:
    pattern = re.compile(
        r"^fixer-native-[A-Za-z0-9_]+-round(?P<round>[0-9]+)"
        r"(?:-attempt(?P<attempt>[0-9]+))?\.json$"
    )
    def order(path: Path) -> tuple[int, int, str]:
        match = pattern.fullmatch(path.name)
        if match is None:
            return (10_000, 10_000, str(path))
        return (
            int(match.group("round")),
            int(match.group("attempt") or 1),
            str(path),
        )

    paths = sorted(evidence_dir.rglob("fixer-native-*.json"), key=order)
    lines: list[str] = []
    for path in paths:
        match = pattern.fullmatch(path.name)
        if match is None:
            continue
        report = _load_evidence(path, "Native Fixer")
        round_number = int(match.group("round"))
        attempt = int(match.group("attempt") or 1)
        status = _brief(
            report.get("status", "fixed" if report.get("success") else "failed"),
            limit=40,
        )
        lines.append(
            f"- Fixer round {round_number}, attempt {attempt}: `{status}` — "
            f"{_brief(report.get('summary'))}"
        )
        changes = report.get("changes")
        if not isinstance(changes, list):
            continue
        for change in changes[:3]:
            if isinstance(change, Mapping):
                file = _brief(change.get("file"), limit=180) if change.get("file") else ""
                location = f"`{file}` — " if file else ""
                lines.append(
                    f"  - Change: {location}{_brief(change.get('change'))}"
                )
            else:
                lines.append(f"  - Change: {_brief(change)}")
    return lines


def _render_prepare_failure_summary(evidence_dir: Path) -> str:
    generation_dir = evidence_dir / "generation-reports"
    failure = _load_evidence(
        generation_dir / "generation-failure.json",
        "generation failure",
    )
    if failure.get("status") != "failed":
        raise IssueLifecycleError("generation failure evidence is not failed")

    stage_lines = _agent_stage_lines(generation_dir)
    blockers = (
        f"- Failed role: `{_brief(failure.get('role'), limit=80)}`.",
        f"- Failed stage: `{_brief(failure.get('stage'), limit=80)}`.",
        f"- Error: {_brief(failure.get('error'))}",
    )
    return "\n".join(
        (
            "## Stage summary",
            "",
            *(stage_lines or ["- No completed agent reports were recorded."]),
            "",
            "## Blocking error",
            "",
            *blockers,
        )
    )


def render_needs_human_summary(evidence_dir: Path) -> str:
    """Render one concise, auditable terminal report from sealed evidence."""

    evidence_dir = Path(evidence_dir)
    if (evidence_dir / "generation-reports" / "generation-failure.json").is_file():
        return _render_prepare_failure_summary(evidence_dir)

    decision_dir = evidence_dir / "decision" / "agents"
    terminal = _load_evidence(
        decision_dir / "convergence-report.json",
        "convergence report",
    )
    if terminal.get("status") != "needs-human-review":
        raise IssueLifecycleError(
            "convergence report is not a needs-human-review terminal"
        )

    stage_lines = _agent_stage_lines(evidence_dir / "generation")
    stage_lines.extend(_native_stage_lines(terminal))
    stage_lines.extend(_fixer_stage_lines(evidence_dir))

    blockers: list[str] = [
        f"- Terminal reason: `{_brief(terminal.get('reason'), limit=100)}`.",
        f"- Repair attempts: `{terminal.get('repair_attempts', 'unknown')}`.",
    ]
    architectures = terminal["architectures"]
    for architecture in ("x86_64", "aarch64"):
        report = architectures[architecture]
        if isinstance(report, Mapping) and report.get("status") != "passed":
            blockers.append(
                f"- **{architecture} `{_brief(report.get('failed_stage'), limit=80)}`**: "
                f"{_brief(report.get('failure'))}"
            )
    gate = terminal.get("gate")
    if isinstance(gate, Mapping):
        findings = gate.get("findings")
        if isinstance(findings, list):
            for finding in findings[:3]:
                if isinstance(finding, Mapping):
                    blockers.append(
                        f"- **Gate `{_brief(finding.get('code'), limit=100)}`**: "
                        f"{_brief(finding.get('message'))}"
                    )

    return "\n".join(
        (
            "## Stage summary",
            "",
            *(stage_lines or ["- No stage reports were recorded."]),
            "",
            "## Blocking error",
            "",
            *blockers,
        )
    )


def scenario_one_workflow_inputs(
    task: TaskSpec,
    issue_number: int,
) -> dict[str, str]:
    return {
        "operation": "scenario_one",
        "app": task.app,
        "version": task.version,
        "os_version": task.os_version,
        "domain": task.domain,
        "source_url": task.source_url,
        "source_run_id": f"issue:{issue_number}",
    }


def upgrade_workflow_inputs(
    request: UpgradeRequest,
    issue_number: int,
) -> dict[str, str]:
    # source_url may be empty: upgrade_scan.py falls back to config/upgrade-apps.yml.
    # os_version is used by the conda scan, while docker derives it from the
    # target repository layout. evidence carries the Issue-provided upstream
    # evidence payload for the scan and the generation prompt.
    inputs = {
        "app": request.app,
        "version": request.version,
        "os_version": request.os_version,
        "source_url": request.source_url,
        "source_issue": str(issue_number),
    }
    if request.evidence:
        inputs["evidence"] = json.dumps(
            request.evidence,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    return inputs


def _title_has_prefix(issue: Mapping[str, object], prefix: str) -> bool:
    return str(issue.get("title", "")).strip().startswith(prefix)


def _upgrade_app(issue: Mapping[str, object]) -> str | None:
    match = _UPGRADE_APP_RE.match(str(issue.get("title", "")))
    if match is None:
        return None
    return match.group("app").strip() or None


def _select_new_issue(
    issues: list[Mapping[str, object]],
    title_prefix: str,
) -> Mapping[str, object] | None:
    return next(
        (
            candidate
            for candidate in issues
            if _title_has_prefix(candidate, title_prefix)
            and _is_claimable(candidate)
        ),
        None,
    )


def _select_queued_upgrade_issue(
    issues: list[Mapping[str, object]],
) -> Mapping[str, object] | None:
    # Same-app requests queue: a new request for an app whose previous request
    # is still 已接纳 is skipped so the next poll picks it up after that run
    # finishes. Other apps keep flowing in the same scan.
    accepted_apps = {
        app
        for issue in issues
        if _issue_status(issue) in _CLAIMED_ISSUE_STATUSES
        for app in (_upgrade_app(issue),)
        if app
    }
    return next(
        (
            candidate
            for candidate in issues
            if _title_has_prefix(candidate, _UPGRADE_TITLE)
            and _is_claimable(candidate)
            and _upgrade_app(candidate) not in accepted_apps
        ),
        None,
    )


def _reject_issue(
    *,
    client: Any,
    target_repo: str,
    issue: Mapping[str, object],
    reason: str,
) -> None:
    client.create_issue_comment(
        target_repo=target_repo,
        number=_issue_number(issue),
        body=f"自动处理未启动：{reason}",
    )
    _update_source_issue(
        client=client,
        target_repo=target_repo,
        issue=issue,
        issue_status="已拒绝",
        state="open",
    )


def _claim_new_issue(
    *,
    client: Any,
    target_repo: str,
    issue_number: int | None,
    title_prefix: str,
    select_issue: Callable[
        [list[Mapping[str, object]]],
        Mapping[str, object] | None,
    ],
    parse_task: Callable[[Mapping[str, object]], Any],
    build_inputs: Callable[[Any, int], Mapping[str, str]],
    dispatch: Callable[[Mapping[str, str]], None],
    accepted_comment: str,
) -> tuple[int, str, Any] | None:
    """Claim one 新建 Issue by status, then dispatch its workflow."""

    if issue_number is None:
        issues = client.list_issues(
            target_repo=target_repo,
            state="open",
            search=title_prefix,
        )
        issue = select_issue(issues)
        if issue is None:
            return None
    else:
        issue = client.get_issue(
            target_repo=target_repo,
            number=issue_number,
        )
    if str(issue.get("state", "")).lower() not in {"open", "opened"}:
        return None
    if not _is_claimable(issue):
        return None

    number = _issue_number(issue)
    original_status = _issue_status(issue)
    try:
        task = parse_task(issue)
    except ValueError as error:
        _reject_issue(
            client=client,
            target_repo=target_repo,
            issue=issue,
            reason=str(error),
        )
        return None

    _update_source_issue(
        client=client,
        target_repo=target_repo,
        issue=issue,
        issue_status=_claimed_status(issue),
        state="open",
    )
    try:
        dispatch(build_inputs(task, number))
    except Exception as error:
        try:
            _update_source_issue(
                client=client,
                target_repo=target_repo,
                issue=issue,
                issue_status=original_status,
                state="open",
            )
        except Exception as rollback_error:
            raise IssueLifecycleError(
                "workflow dispatch and Issue claim rollback both failed"
            ) from rollback_error
        raise IssueLifecycleError(f"workflow dispatch failed: {error}") from error

    client.create_issue_comment(
        target_repo=target_repo,
        number=number,
        body=accepted_comment,
    )
    return number, _issue_url(issue), task


def claim_new_image_issue(
    *,
    client: Any,
    target_repo: str,
    issue_number: int | None,
    dispatch: Callable[[Mapping[str, str]], None],
    parse_task: Callable[[Mapping[str, object]], TaskSpec],
) -> ClaimedIssue | None:
    """Claim one new-image Issue by status, then dispatch scenario one."""

    result = _claim_new_issue(
        client=client,
        target_repo=target_repo,
        issue_number=issue_number,
        title_prefix=_NEW_IMAGE_TITLE,
        select_issue=lambda issues: _select_new_issue(issues, _NEW_IMAGE_TITLE),
        parse_task=parse_task,
        build_inputs=scenario_one_workflow_inputs,
        dispatch=dispatch,
        accepted_comment="该请求已接纳，自动镜像流水线已经触发。",
    )
    if result is None:
        return None
    number, url, task = result
    return ClaimedIssue(number=number, url=url, task=task)


def claim_upgrade_issue(
    *,
    client: Any,
    target_repo: str,
    issue_number: int | None,
    dispatch: Callable[[Mapping[str, str]], None],
    parse_task: Callable[[Mapping[str, object]], UpgradeRequest],
) -> ClaimedUpgradeIssue | None:
    """Claim one 【new-version】 Issue, queueing requests for a busy app."""

    result = _claim_new_issue(
        client=client,
        target_repo=target_repo,
        issue_number=issue_number,
        title_prefix=_UPGRADE_TITLE,
        select_issue=_select_queued_upgrade_issue,
        parse_task=parse_task,
        build_inputs=upgrade_workflow_inputs,
        dispatch=dispatch,
        accepted_comment="该升级请求已接纳，自动升级流水线已经触发。",
    )
    if result is None:
        return None
    number, url, request = result
    return ClaimedUpgradeIssue(number=number, url=url, request=request)


def _select_routed_issue(
    issues: list[Mapping[str, object]],
    route: Callable[[Mapping[str, object]], tuple[str, Any]],
) -> Mapping[str, object] | None:
    """Pick the first claimable routed Issue, honouring same-app upgrade queueing."""

    busy_apps = set()
    for issue in issues:
        if _issue_status(issue) not in _CLAIMED_ISSUE_STATUSES:
            continue
        try:
            scenario, payload = route(issue)
        except ValueError:
            continue
        app = getattr(payload, "app", None)
        if scenario == SCENARIO_UPGRADE and app:
            busy_apps.add(app)
    for issue in issues:
        if not _is_claimable(issue):
            continue
        # 旧标题由各自的 monitor 认领，避免同一 Issue 被两条路径同时认领。
        if any(
            _title_has_prefix(issue, prefix)
            for prefix in LEGACY_TITLE_PREFIXES
        ):
            continue
        try:
            scenario, payload = route(issue)
        except ValueError:
            # 无法路由的 Issue 也要认领，交给认领流程回帖说明原因。
            return issue
        if (
            scenario == SCENARIO_UPGRADE
            and getattr(payload, "app", None) in busy_apps
        ):
            continue
        return issue
    return None


def claim_routed_issue(
    *,
    client: Any,
    target_repo: str,
    issue_number: int | None,
    route: Callable[[Mapping[str, object]], tuple[str, Any]],
    dispatch: Callable[[str, Any, int], None],
    accepted_comments: Mapping[str, str],
) -> ClaimedRoutedIssue | None:
    """Claim one ``【自动升级需求】`` Issue and dispatch its scenario."""

    if issue_number is None:
        issues = client.list_issues(
            target_repo=target_repo,
            state="open",
            search=AUTO_UPGRADE_TITLE_PREFIX,
        )
        issue = _select_routed_issue(issues, route)
        if issue is None:
            return None
    else:
        issue = client.get_issue(
            target_repo=target_repo,
            number=issue_number,
        )
    if str(issue.get("state", "")).lower() not in {"open", "opened"}:
        return None
    if not _is_claimable(issue):
        return None

    number = _issue_number(issue)
    original_status = _issue_status(issue)
    try:
        scenario, payload = route(issue)
    except ValueError as error:
        _reject_issue(
            client=client,
            target_repo=target_repo,
            issue=issue,
            reason=str(error),
        )
        return None

    _update_source_issue(
        client=client,
        target_repo=target_repo,
        issue=issue,
        issue_status=_claimed_status(issue),
        state="open",
    )
    try:
        dispatch(scenario, payload, number)
    except Exception as error:
        try:
            _update_source_issue(
                client=client,
                target_repo=target_repo,
                issue=issue,
                issue_status=original_status,
                state="open",
            )
        except Exception as rollback_error:
            raise IssueLifecycleError(
                "workflow dispatch and Issue claim rollback both failed"
            ) from rollback_error
        raise IssueLifecycleError(f"workflow dispatch failed: {error}") from error

    client.create_issue_comment(
        target_repo=target_repo,
        number=number,
        body=accepted_comments[scenario],
    )
    return ClaimedRoutedIssue(
        number=number,
        url=_issue_url(issue),
        scenario=scenario,
        payload=payload,
    )


def _finalize_issue(
    *,
    client: Any,
    target_repo: str,
    issue_number: int,
    outcome: str,
    run_url: str,
    pr_url: str = "",
    failure_summary: str = "",
    failure_evidence_dir: Path | None = None,
    pipeline_label: str = "自动镜像流水线",
    require_pr_on_success: bool = True,
) -> Any | None:
    """Write one terminal pipeline result back to its source Issue."""

    if outcome not in {"success", "failure", "needs-human-review"}:
        raise ValueError(
            "outcome must be success, failure or needs-human-review"
        )
    if not run_url.startswith("https://"):
        raise ValueError("run_url must be an HTTPS URL")
    if (
        outcome == "success"
        and require_pr_on_success
        and not pr_url.startswith("https://")
    ):
        raise ValueError("successful outcome requires an HTTPS PR URL")

    issue = client.get_issue(
        target_repo=target_repo,
        number=issue_number,
    )
    claimed_status = _claimed_status(issue)
    current_status = _issue_status(issue)
    # GitCode couples 已完成 to a closed Issue. A created PR completes the
    # generation request; unsuccessful outcomes stay open for human handling.
    if outcome == "success":
        target_status = "已完成"
        target_state = "closed"
    elif _issue_type(issue) == _TASK_ISSUE_TYPE:
        # 任务类型的状态机没有「已挂起」：失败时保持「进行中」并补说明，
        # 既不会被轮询重新认领，也保持 Issue 打开等待人工。
        target_status = claimed_status
        target_state = "open"
    else:
        target_status = "已挂起"
        target_state = "open"
    if current_status == target_status and current_status != claimed_status:
        return None
    # 手动重跑一个已挂起的 Issue 也可能这次成功：GitCode 允许
    # 「已挂起」→「已完成」+ close，此时应正常收口而不是拒绝。
    finalizable = {claimed_status}
    if current_status == "已挂起" and outcome == "success":
        finalizable.add("已挂起")
    if current_status not in finalizable:
        raise IssueLifecycleError(
            f"cannot finalize Issue in {current_status!r} status"
        )

    if outcome == "success":
        headline = (
            f"{pipeline_label}已生成 PR，Issue 已完成。"
            if pr_url
            else f"{pipeline_label}已完成，Issue 已关闭。"
        )
        lines = [headline, "", f"- Workflow: {run_url}"]
        if pr_url:
            lines.append(f"- Pull request: {pr_url}")
        comment = "\n".join(lines)
    elif outcome == "needs-human-review":
        if failure_evidence_dir is not None:
            try:
                failure_summary = render_needs_human_summary(failure_evidence_dir)
            except IssueLifecycleError:
                if not failure_summary.strip():
                    raise
        if not failure_summary.strip():
            raise IssueLifecycleError(
                "needs-human-review requires terminal failure evidence"
            )
        comment = "\n".join(
            (
                f"needs-human-review: {pipeline_label}未收敛，需要人工处理。",
                "",
                failure_summary,
                "",
                "## Evidence",
                "",
                f"- Workflow: {run_url}",
            )
        )
    else:
        headline = (
            f"{pipeline_label}未完成，Issue 已挂起等待人工处理。"
            if target_status == "已挂起"
            else f"{pipeline_label}未完成，需要人工处理"
            f"（Issue 状态保持「{target_status}」）。"
        )
        lines = [headline, "", f"- Workflow: {run_url}"]
        summary = failure_summary.strip()
        if summary:
            # 失败摘要可能是多行的日志摘录，单独成段，不要塞进列表项。
            lines.extend(["", summary])
        else:
            lines.append("- Failure summary: see workflow run")
        comment = "\n".join(lines)
    client.create_issue_comment(
        target_repo=target_repo,
        number=issue_number,
        body=comment,
    )
    if target_status == current_status:
        return None
    return _update_source_issue(
        client=client,
        target_repo=target_repo,
        issue=issue,
        issue_status=target_status,
        state=target_state,
    )


def finalize_new_image_issue(
    *,
    client: Any,
    target_repo: str,
    issue_number: int,
    outcome: str,
    run_url: str,
    pr_url: str = "",
    failure_summary: str = "",
    failure_evidence_dir: Path | None = None,
) -> Any | None:
    """Write the terminal scenario-one result back to its source Issue."""

    return _finalize_issue(
        client=client,
        target_repo=target_repo,
        issue_number=issue_number,
        outcome=outcome,
        run_url=run_url,
        pr_url=pr_url,
        failure_summary=failure_summary,
        failure_evidence_dir=failure_evidence_dir,
    )


def finalize_upgrade_issue(
    *,
    client: Any,
    target_repo: str,
    issue_number: int,
    outcome: str,
    run_url: str,
    pr_url: str = "",
    failure_summary: str = "",
) -> Any | None:
    """Write the terminal scenario-two result back to its source Issue.

    Upgrade runs may legitimately end without a PR (for example an audit-only
    round), so a successful outcome does not require a PR URL.
    """

    return _finalize_issue(
        client=client,
        target_repo=target_repo,
        issue_number=issue_number,
        outcome=outcome,
        run_url=run_url,
        pr_url=pr_url,
        failure_summary=failure_summary,
        pipeline_label="自动升级流水线",
        require_pr_on_success=False,
    )


def dispatch_github_workflow(
    *,
    github_token: str,
    github_repository: str,
    workflow: str,
    ref: str,
    inputs: Mapping[str, str],
    run: Callable[..., Any] = subprocess.run,
) -> None:
    """Dispatch a workflow through GitHub CLI without exposing its token."""

    if not github_token:
        raise IssueLifecycleError("GITHUB_TOKEN is required")
    command = [
        "gh",
        "workflow",
        "run",
        workflow,
        "--repo",
        github_repository,
        "--ref",
        ref,
    ]
    for key, value in sorted(inputs.items()):
        command.extend(("-f", f"{key}={value}"))
    environment = os.environ.copy()
    environment["GH_TOKEN"] = github_token
    run(
        command,
        check=True,
        env=environment,
    )


def _default_title(report: FailureIssueReport) -> str:
    return (
        f"[Autopilot Failure] {report.task.app.capitalize()} "
        f"{report.task.version} on openEuler {report.task.os_version}"
    )


def _render_body(report: FailureIssueReport, idempotency_key: str) -> str:
    architecture_lines = "\n".join(
        f"- {arch}: {report.architecture_status[arch]}"
        for arch in ("x86_64", "aarch64")
    )
    repair_lines = "\n".join(
        f"- {summary}" for summary in report.repair_summaries
    )
    if not repair_lines:
        repair_lines = "- No automated repair was applicable."
    return "\n".join(
        (
            _marker(idempotency_key),
            "",
            "## Terminal automation failure",
            "",
            f"- Failure stage: {report.failure_stage}",
            f"- Repair attempts: {report.attempt_count}/3",
            f"- Workflow run: {report.run_url}",
            f"- Diagnostic artifact: {report.artifact_url}",
            "",
            "## TaskSpec",
            "",
            "```json",
            report.task.to_json(),
            "```",
            "",
            "## Native architecture status",
            "",
            architecture_lines,
            "",
            "## Automated repair summary",
            "",
            repair_lines,
            "",
            "## Suggested human action",
            "",
            report.suggested_action,
        )
    )


def _existing_issue(
    client: Any,
    *,
    target_repo: str,
    idempotency_key: str,
) -> Mapping[str, object] | None:
    marker = _marker(idempotency_key)
    issues = client.list_issues(
        target_repo=target_repo,
        state="all",
        search=idempotency_key,
    )
    matches = [
        issue
        for issue in issues
        if marker in str(issue.get("body", ""))
    ]
    if len(matches) > 1:
        raise IssueLifecycleError(
            f"multiple Issues contain idempotency marker {idempotency_key}"
        )
    return matches[0] if matches else None


def report_terminal_failure(
    *,
    client: Any,
    target_repo: str,
    report: FailureIssueReport,
    successful: bool,
    idempotency_key: str | None = None,
    title: str | None = None,
    create_if_missing: bool = True,
) -> GitCodeResource | Any | None:
    """Create or update one terminal failure Issue.

    Ordinary failures are silent until all three repair attempts have failed.
    A non-recoverable delivery error can report earlier.
    """

    if successful:
        return None
    if report.attempt_count < 3 and not report.terminal_delivery_error:
        return None

    key = idempotency_key or report.task.task_id
    issue_title = title or _default_title(report)
    body = _render_body(report, key)
    existing = _existing_issue(
        client,
        target_repo=target_repo,
        idempotency_key=key,
    )
    if existing is None:
        if not create_if_missing:
            raise IssueLifecycleError(
                "new Issue is not visible for the idempotent update; "
                "refusing to create a duplicate"
            )
        return client.create_issue(
            target_repo=target_repo,
            title=issue_title,
            body=body,
            labels="needs-human-review",
        )

    raw_number = existing.get("number")
    if raw_number is None:
        raw_number = existing.get("iid")
    try:
        number = int(raw_number)
    except (TypeError, ValueError) as error:
        raise IssueLifecycleError("existing Issue has no valid number") from error
    return client.update_issue(
        target_repo=target_repo,
        number=number,
        title=issue_title,
        body=body,
        state="open",
        labels="needs-human-review",
    )


def run_controlled_issue_probe(
    *,
    client: Any,
    target_repo: str,
    task: TaskSpec,
    environment: str,
    operation: str,
    github_run_id: str,
    github_run_url: str,
    failure_stage: str,
) -> GitCodeResource | Any:
    """Run the explicit test-only create/update/comment/close contract probe."""

    if environment != "test" or operation != "failure_issue_contract_test":
        raise IssueOperationForbiddenError(
            "controlled Issue probe requires the explicit test operation"
        )
    if not _SAFE_DYNAMIC_VALUE.fullmatch(github_run_id):
        raise ValueError("github_run_id contains unsafe characters")
    if not _SAFE_DYNAMIC_VALUE.fullmatch(failure_stage):
        raise ValueError("failure_stage contains unsafe characters")

    key = f"e2e-{task.task_id}-run-{github_run_id}"
    title = (
        f"[E2E TEST] {task.app.capitalize()} {task.version} "
        f"{failure_stage} final failure - run {github_run_id}"
    )
    report = FailureIssueReport(
        task=task,
        failure_stage=failure_stage,
        attempt_count=3,
        terminal_delivery_error=False,
        architecture_status={
            "x86_64": "passed (controlled probe)",
            "aarch64": "failed (controlled probe)",
        },
        repair_summaries=(
            "round 1: controlled retry recorded",
            "round 2: controlled retry recorded",
            "round 3: controlled terminal failure recorded",
        ),
        run_url=github_run_url,
        artifact_url=github_run_url,
        suggested_action="No human action is required for this E2E probe.",
    )

    created = report_terminal_failure(
        client=client,
        target_repo=target_repo,
        report=report,
        successful=False,
        idempotency_key=key,
        title=title,
    )
    updated = report_terminal_failure(
        client=client,
        target_repo=target_repo,
        report=report,
        successful=False,
        idempotency_key=key,
        title=title,
        create_if_missing=False,
    )
    if created is None or updated is None:
        raise IssueLifecycleError("controlled Issue probe did not create an Issue")

    client.create_issue_comment(
        target_repo=target_repo,
        number=updated.number,
        body=(
            "E2E contract verified: creation and idempotent update both "
            "succeeded. Closing this controlled probe."
        ),
    )
    closed_body = (
        f"{_render_body(report, key)}\n\n"
        "## E2E contract result\n\n"
        "The controlled Issue was closed automatically after create, update, "
        "comment and idempotency checks passed."
    )
    return client.update_issue(
        target_repo=target_repo,
        number=updated.number,
        title=title,
        body=closed_body,
        state="closed",
        labels="needs-human-review",
    )
