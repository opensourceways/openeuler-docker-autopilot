import json
from dataclasses import dataclass

import pytest


TARGET_REPO = "openeuler/openeuler-docker-images"
GITHUB_RUN_URL = (
    "https://github.com/opensourceways/openeuler-docker-autopilot/"
    "actions/runs/123456"
)


def _task():
    from scripts.lib.task_spec import TaskSpec

    return TaskSpec.from_workflow_dispatch(
        {
            "app": "kvrocks",
            "version": "2.16.0",
            "os_version": "24.03-lts-sp4",
            "domain": "Database",
            "source_url": "https://github.com/apache/kvrocks/tree/v2.16.0",
        }
    )


@dataclass(frozen=True)
class Resource:
    number: int
    url: str


class StatefulIssueClient:
    def __init__(self, existing=None):
        self.issue = existing
        self.calls = []

    def list_issues(self, **kwargs):
        self.calls.append(("list", kwargs))
        return [self.issue] if self.issue else []

    def create_issue(self, **kwargs):
        self.calls.append(("create", kwargs))
        self.issue = {
            "number": 19,
            "html_url": "https://gitcode.com/example/issues/19",
            "title": kwargs["title"],
            "body": kwargs["body"],
            "state": "open",
        }
        return Resource(number=19, url=self.issue["html_url"])

    def update_issue(self, **kwargs):
        self.calls.append(("update", kwargs))
        self.issue = {
            "number": kwargs["number"],
            "html_url": "https://gitcode.com/example/issues/19",
            "title": kwargs["title"],
            "body": kwargs["body"],
            "state": kwargs["state"],
        }
        return Resource(number=kwargs["number"], url=self.issue["html_url"])

    def create_issue_comment(self, **kwargs):
        self.calls.append(("comment", kwargs))
        return {"id": 3, "body": kwargs["body"]}


def _report(*, attempts=3, terminal_delivery_error=False):
    from scripts.lib.issue_lifecycle import FailureIssueReport

    return FailureIssueReport(
        task=_task(),
        failure_stage="dual-arch-test",
        attempt_count=attempts,
        terminal_delivery_error=terminal_delivery_error,
        architecture_status={
            "x86_64": "passed",
            "aarch64": "failed: version assertion",
        },
        repair_summaries=(
            "round 1: corrected build dependency",
            "round 2: corrected ARM library path",
            "round 3: version assertion still fails",
        ),
        run_url="https://github.com/Meihan-chen/repo/actions/runs/123456",
        artifact_url="https://github.com/Meihan-chen/repo/actions/runs/123456",
        suggested_action="Inspect the aarch64 version output.",
    )


@pytest.mark.parametrize(
    ("successful", "attempts"),
    [(True, 3), (False, 1), (False, 2)],
)
def test_intermediate_failure_or_success_never_writes_issue(successful, attempts):
    from scripts.lib.issue_lifecycle import report_terminal_failure

    client = StatefulIssueClient()

    result = report_terminal_failure(
        client=client,
        target_repo=TARGET_REPO,
        report=_report(attempts=attempts),
        successful=successful,
    )

    assert result is None
    assert client.calls == []


def test_terminal_failure_creates_structured_needs_human_review_issue():
    from scripts.lib.issue_lifecycle import report_terminal_failure

    client = StatefulIssueClient()

    result = report_terminal_failure(
        client=client,
        target_repo=TARGET_REPO,
        report=_report(),
        successful=False,
    )

    assert result.number == 19
    assert [name for name, _ in client.calls] == ["list", "create"]
    list_call = client.calls[0][1]
    assert list_call == {
        "target_repo": TARGET_REPO,
        "state": "all",
        "search": _task().task_id,
    }
    create_call = client.calls[1][1]
    assert create_call["labels"] == "needs-human-review"
    assert not create_call["title"].startswith("[E2E TEST]")
    body = create_call["body"]
    assert f"<!-- oe-autopilot-task:{_task().task_id} -->" in body
    assert _task().to_json() in body
    assert "dual-arch-test" in body
    assert "x86_64: passed" in body
    assert "aarch64: failed: version assertion" in body
    assert "round 3: version assertion still fails" in body
    assert "Inspect the aarch64 version output." in body


def test_terminal_delivery_error_can_report_before_third_repair_round():
    from scripts.lib.issue_lifecycle import report_terminal_failure

    client = StatefulIssueClient()

    result = report_terminal_failure(
        client=client,
        target_repo=TARGET_REPO,
        report=_report(attempts=1, terminal_delivery_error=True),
        successful=False,
    )

    assert result.number == 19
    assert [name for name, _ in client.calls] == ["list", "create"]


def test_existing_issue_with_exact_marker_is_updated_not_duplicated():
    from scripts.lib.issue_lifecycle import report_terminal_failure

    marker = f"<!-- oe-autopilot-task:{_task().task_id} -->"
    client = StatefulIssueClient(
        existing={
            "number": "27",
            "html_url": "https://gitcode.com/example/issues/27",
            "title": "old",
            "body": f"{marker}\nold failure",
            "state": "closed",
        }
    )

    result = report_terminal_failure(
        client=client,
        target_repo=TARGET_REPO,
        report=_report(),
        successful=False,
    )

    assert result.number == 27
    assert [name for name, _ in client.calls] == ["list", "update"]
    update_call = client.calls[1][1]
    assert update_call["number"] == 27
    assert update_call["state"] == "open"
    assert update_call["labels"] == "needs-human-review"


def test_controlled_probe_is_explicit_idempotent_commented_and_closed():
    from scripts.lib.issue_lifecycle import run_controlled_issue_probe

    client = StatefulIssueClient()

    result = run_controlled_issue_probe(
        client=client,
        target_repo=TARGET_REPO,
        task=_task(),
        environment="test",
        operation="failure_issue_contract_test",
        github_run_id="123456",
        github_run_url=GITHUB_RUN_URL,
        failure_stage="aarch64-build",
    )

    assert result.number == 19
    assert result.url.endswith("/issues/19")
    assert [name for name, _ in client.calls] == [
        "list",
        "create",
        "list",
        "update",
        "comment",
        "update",
    ]
    create_call = client.calls[1][1]
    assert create_call["title"].startswith("[E2E TEST]")
    assert "Kvrocks 2.16.0" in create_call["title"]
    assert "aarch64-build" in create_call["title"]
    assert "run 123456" in create_call["title"]
    assert "e2e-" in create_call["body"]
    assert GITHUB_RUN_URL in create_call["body"]
    assert "Meihan-chen/openeuler-docker-images-workflow" not in (
        create_call["body"]
    )
    assert client.calls[-1][1]["state"] == "closed"
    assert "closed automatically" in client.calls[-1][1]["body"]


def test_controlled_probe_never_creates_twice_when_new_issue_is_not_yet_listed():
    from scripts.lib.issue_lifecycle import (
        IssueLifecycleError,
        run_controlled_issue_probe,
    )

    class DelayedIndexClient(StatefulIssueClient):
        def list_issues(self, **kwargs):
            self.calls.append(("list", kwargs))
            return []

    client = DelayedIndexClient()

    with pytest.raises(IssueLifecycleError, match="not visible"):
        run_controlled_issue_probe(
            client=client,
            target_repo=TARGET_REPO,
            task=_task(),
            environment="test",
            operation="failure_issue_contract_test",
            github_run_id="123456",
            github_run_url=GITHUB_RUN_URL,
            failure_stage="aarch64-build",
        )

    assert [name for name, _ in client.calls] == [
        "list",
        "create",
        "list",
    ]


@pytest.mark.parametrize(
    ("environment", "operation"),
    [
        ("production", "failure_issue_contract_test"),
        ("test", "validate_only"),
        ("test", "fork_pr"),
    ],
)
def test_controlled_probe_rejects_non_explicit_or_non_test_invocation(
    environment, operation
):
    from scripts.lib.issue_lifecycle import (
        IssueOperationForbiddenError,
        run_controlled_issue_probe,
    )

    client = StatefulIssueClient()

    with pytest.raises(IssueOperationForbiddenError):
        run_controlled_issue_probe(
            client=client,
            target_repo=TARGET_REPO,
            task=_task(),
            environment=environment,
            operation=operation,
            github_run_id="123456",
            github_run_url=GITHUB_RUN_URL,
            failure_stage="aarch64-build",
        )

    assert client.calls == []


MINIMAL_ISSUE_TITLE = (
    "【自动升级需求】add kvrocks 2.16.0 docker image on "
    "openEuler 24.03-LTS-SP4"
)
MINIMAL_ISSUE_BODY = """**软件包名称（Package Name）：** kvrocks
**源码仓库（Source Repository）：** https://github.com/apache/kvrocks/tree/v2.16.0
**所属领域（Domain）：** 数据库
"""


class TriggerIssueClient:
    def __init__(self, issue):
        self.issue = dict(issue)
        self.calls = []

    def get_issue(self, **kwargs):
        self.calls.append(("get", kwargs))
        return dict(self.issue)

    def update_issue(self, **kwargs):
        self.calls.append(("update", kwargs))
        self.issue.update(
            {
                "title": kwargs["title"],
                "body": kwargs["body"],
                "state": kwargs["state"],
                "issue_state": kwargs.get("issue_status"),
                "issue_state_detail": {
                    "title": kwargs.get("issue_status"),
                },
            }
        )
        return Resource(
            number=kwargs["number"],
            url=f"https://gitcode.com/example/issues/{kwargs['number']}",
        )

    def create_issue_comment(self, **kwargs):
        self.calls.append(("comment", kwargs))
        return {"id": 3, "body": kwargs["body"]}


def _new_trigger_issue(**overrides):
    issue = {
        "number": 64,
        "html_url": "https://gitcode.com/example/issues/64",
        "title": MINIMAL_ISSUE_TITLE,
        "body": MINIMAL_ISSUE_BODY,
        "state": "open",
        "issue_state": "新建",
        "issue_state_detail": {"title": "新建"},
    }
    issue.update(overrides)
    return issue


@pytest.mark.parametrize(
    ("outcome", "pr_url", "expected_status", "expected_state"),
    [
        (
            "success",
            "https://gitcode.com/openeuler/openeuler-docker-images/pull/4000",
            "已完成",
            "closed",
        ),
        ("failure", "", "已挂起", "open"),
        ("needs-human-review", "", "已挂起", "open"),
    ],
)
def test_trigger_issue_is_finalized_from_scenario_one_result(
    outcome, pr_url, expected_status, expected_state
):
    from scripts.lib.issue_lifecycle import finalize_new_image_issue

    client = TriggerIssueClient(
        _new_trigger_issue(
            issue_state="已接纳",
            issue_state_detail={"title": "已接纳"},
        )
    )

    finalize_new_image_issue(
        client=client,
        target_repo=TARGET_REPO,
        issue_number=64,
        outcome=outcome,
        run_url="https://github.com/Meihan-chen/repo/actions/runs/123",
        pr_url=pr_url,
        failure_summary="package_candidate=failure",
    )

    assert [name for name, _ in client.calls] == ["get", "comment", "update"]
    comment = client.calls[1][1]["body"]
    assert "actions/runs/123" in comment
    if outcome == "success":
        assert pr_url in comment
        assert "Issue 已完成" in comment
        assert "保持打开" not in comment
    else:
        assert "package_candidate=failure" in comment
        if outcome == "needs-human-review":
            assert "needs-human-review" in comment
    update = client.calls[2][1]
    assert update["issue_status"] == expected_status
    assert update["state"] == expected_state


def test_needs_human_comment_summarizes_stages_fixer_and_blocker(tmp_path):
    from scripts.lib.issue_lifecycle import (
        finalize_new_image_issue,
        render_needs_human_summary,
    )

    generation = tmp_path / "generation"
    decision = tmp_path / "decision" / "agents"
    previous_decision = tmp_path / "decisions" / "round1" / "agents"
    generation.mkdir()
    decision.mkdir(parents=True)
    previous_decision.mkdir(parents=True)
    (generation / "image-creator.json").write_text(
        json.dumps({"success": True, "summary": "Created the image files."})
    )
    (generation / "testcase-qa-round1.json").write_text(
        json.dumps(
            {
                "status": "needs_fix",
                "summary": "Runtime command assertion was inconsistent.",
                "issues": [
                    {
                        "severity": "major",
                        "file": "Database/example/tests/test.sh",
                        "description": "Expected UID differs from Dockerfile.",
                    }
                ],
            }
        )
    )
    (generation / "image-qa-round1.json").write_text(
        json.dumps(
            {
                "status": "needs_fix",
                "summary": "Legacy image review must be ignored.",
            }
        )
    )
    (decision / "fixer-native-dual-round3-attempt1.json").write_text(
        json.dumps(
            {
                "success": True,
                "status": "fixed",
                "summary": "Added the missing ARM runtime library.",
                "changes": [
                    {
                        "file": "Database/example/1.0/oe/Dockerfile",
                        "change": "Install libatomic on aarch64.",
                    }
                ],
                "_input_review": {"kind": "native_validation_failure"},
            }
        )
    )
    (previous_decision / "fixer-native-dual-round1-attempt1.json").write_text(
        json.dumps(
            {
                "success": True,
                "status": "fixed",
                "summary": "Pinned the missing build dependency.",
                "changes": ["Install the compiler package."],
                "_input_review": {"kind": "native_validation_failure"},
            }
        )
    )
    (decision / "convergence-report.json").write_text(
        json.dumps(
            {
                "status": "needs-human-review",
                "reason": "native-repair-budget-exhausted",
                "round": 4,
                "repair_attempts": 3,
                "architectures": {
                    "x86_64": {
                        "status": "passed",
                        "checks": {
                            "native_build": True,
                            "runtime_test": True,
                        },
                    },
                    "aarch64": {
                        "status": "failed",
                        "failed_stage": "native_build",
                        "failure": "libatomic.so.1: cannot open shared object file",
                        "classification": {"category": "build-error"},
                    },
                },
            }
        )
    )

    summary = render_needs_human_summary(tmp_path)

    assert "## Stage summary" in summary
    assert "Image Creator" in summary
    assert "Created the image files" in summary
    assert "Image QA" not in summary
    assert "Testcase QA round 1" in summary
    assert "Expected UID differs from Dockerfile" in summary
    assert "Native x86_64" in summary and "passed" in summary
    assert "Native aarch64" in summary and "native_build" in summary
    assert "Fixer round 3, attempt 1" in summary
    assert "Fixer round 1, attempt 1" in summary
    assert "Pinned the missing build dependency" in summary
    assert "Install libatomic on aarch64" in summary
    assert "## Blocking error" in summary
    assert "libatomic.so.1" in summary

    client = TriggerIssueClient(
        _new_trigger_issue(
            issue_state="已接纳",
            issue_state_detail={"title": "已接纳"},
        )
    )
    finalize_new_image_issue(
        client=client,
        target_repo=TARGET_REPO,
        issue_number=64,
        outcome="needs-human-review",
        run_url="https://github.com/Meihan-chen/repo/actions/runs/123",
        failure_evidence_dir=tmp_path,
    )

    comment = client.calls[1][1]["body"]
    assert "## Stage summary" in comment
    assert "## Blocking error" in comment
    assert "libatomic.so.1" in comment


def test_prepare_failure_comment_summarizes_completed_agents_and_blocker(tmp_path):
    from scripts.lib.issue_lifecycle import (
        finalize_new_image_issue,
        render_needs_human_summary,
    )

    generation = tmp_path / "generation-reports"
    generation.mkdir()
    (generation / "image-creator.json").write_text(
        json.dumps({"success": True, "summary": "Created the image files."})
    )
    (generation / "testcase-creator.json").write_text(
        json.dumps({"success": True, "summary": "Created the smoke test."})
    )
    (generation / "generation-failure.json").write_text(
        json.dumps(
            {
                "status": "failed",
                "stage": "agent",
                "role": "testcase_qa",
                "error": (
                    "OpenCode completed without the required JSON contract: "
                    "issues, summary"
                ),
            }
        )
    )

    summary = render_needs_human_summary(tmp_path)

    assert "## Stage summary" in summary
    assert "Image Creator" in summary
    assert "Created the image files" in summary
    assert "Testcase Creator" in summary
    assert "Created the smoke test" in summary
    assert "## Blocking error" in summary
    assert "testcase_qa" in summary
    assert "agent" in summary
    assert "required JSON contract: issues, summary" in summary

    client = TriggerIssueClient(
        _new_trigger_issue(
            issue_state="已接纳",
            issue_state_detail={"title": "已接纳"},
        )
    )
    finalize_new_image_issue(
        client=client,
        target_repo=TARGET_REPO,
        issue_number=64,
        outcome="needs-human-review",
        run_url="https://github.com/Meihan-chen/repo/actions/runs/123",
        failure_evidence_dir=tmp_path,
    )

    comment = client.calls[1][1]["body"]
    assert "needs-human-review" in comment
    assert "三轮自动修复" not in comment
    assert "testcase_qa" in comment
    assert "required JSON contract: issues, summary" in comment


def test_github_workflow_dispatch_uses_token_only_in_environment():
    from scripts.lib.issue_lifecycle import dispatch_github_workflow

    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))

    dispatch_github_workflow(
        github_token="github-secret",
        github_repository="Meihan-chen/openeuler-docker-images-workflow",
        workflow="create_new_images.yml",
        ref="main",
        inputs={"operation": "scenario_one", "source_run_id": "64"},
        run=run,
    )

    command, kwargs = calls[0]
    assert command[:7] == [
        "gh",
        "workflow",
        "run",
        "create_new_images.yml",
        "--repo",
        "Meihan-chen/openeuler-docker-images-workflow",
        "--ref",
    ]
    assert "github-secret" not in command
    assert kwargs["env"]["GH_TOKEN"] == "github-secret"
    assert kwargs["check"] is True


UPGRADE_ISSUE_TITLE = (
    "【自动升级需求】upgrade grpc to 1.85.4 on openEuler 24.03-lts-sp4"
)


def _upgrade_trigger_issue(**overrides):
    issue = {
        "number": 81,
        "html_url": "https://gitcode.com/example/issues/81",
        "title": UPGRADE_ISSUE_TITLE,
        "body": "",
        "state": "open",
        "issue_state": "新建",
        "issue_state_detail": {"title": "新建"},
    }
    issue.update(overrides)
    return issue


def test_task_issue_failure_keeps_in_progress_and_comments():
    from scripts.lib.issue_lifecycle import finalize_upgrade_issue

    client = TriggerIssueClient(
        _upgrade_trigger_issue(
            issue_state="进行中",
            issue_state_detail={"title": "进行中"},
            issue_type="任务",
            issue_type_detail={"title": "任务", "id": 1884},
        )
    )

    finalize_upgrade_issue(
        client=client,
        target_repo=TARGET_REPO,
        issue_number=81,
        outcome="failure",
        run_url=GITHUB_RUN_URL,
        failure_summary="arm64 replay rejected",
    )

    assert [name for name, _ in client.calls] == ["get", "comment"]
    comment = client.calls[1][1]["body"]
    assert "需要人工处理" in comment
    assert "arm64 replay rejected" in comment
    assert client.issue["issue_state"] == "进行中"


def test_suspended_issue_success_is_finalized_after_rerun():
    """手动重跑已挂起的 Issue 并成功时，应能正常收口而不是报状态错误。"""
    from scripts.lib.issue_lifecycle import finalize_upgrade_issue

    client = TriggerIssueClient(
        _upgrade_trigger_issue(
            issue_state="已挂起",
            issue_state_detail={"title": "已挂起"},
        )
    )

    finalize_upgrade_issue(
        client=client,
        target_repo=TARGET_REPO,
        issue_number=81,
        outcome="success",
        run_url=GITHUB_RUN_URL,
        pr_url=(
            "https://gitcode.com/openeuler/openeuler-docker-images/"
            "merge_requests/6755"
        ),
    )

    assert [name for name, _ in client.calls] == ["get", "comment", "update"]
    assert client.issue["state"] == "closed"
    assert client.issue["issue_state"] == "已完成"


@pytest.mark.parametrize(
    ("outcome", "pr_url", "expected_status", "expected_state"),
    [
        ("success", "", "已完成", "closed"),
        (
            "success",
            "https://gitcode.com/openeuler/openeuler-docker-images/pull/4100",
            "已完成",
            "closed",
        ),
        ("failure", "", "已挂起", "open"),
    ],
)
def test_upgrade_issue_is_finalized_from_scenario_two_result(
    outcome, pr_url, expected_status, expected_state
):
    from scripts.lib.issue_lifecycle import finalize_upgrade_issue

    client = TriggerIssueClient(
        _upgrade_trigger_issue(
            issue_state="已接纳",
            issue_state_detail={"title": "已接纳"},
        )
    )

    finalize_upgrade_issue(
        client=client,
        target_repo=TARGET_REPO,
        issue_number=81,
        outcome=outcome,
        run_url="https://github.com/Meihan-chen/repo/actions/runs/456",
        pr_url=pr_url,
        failure_summary="discover failed",
    )

    assert [name for name, _ in client.calls] == ["get", "comment", "update"]
    comment = client.calls[1][1]["body"]
    assert "actions/runs/456" in comment
    if outcome == "success":
        assert "自动升级流水线" in comment
        if pr_url:
            assert pr_url in comment
            assert "Issue 已完成" in comment
        else:
            assert "Issue 已关闭" in comment
            assert "Pull request" not in comment
    else:
        assert "自动升级流水线未完成" in comment
        assert "discover failed" in comment
    update = client.calls[2][1]
    assert update["issue_status"] == expected_status
    assert update["state"] == expected_state


def test_upgrade_comment_uses_the_shared_result_layout():
    from scripts.lib.issue_lifecycle import finalize_upgrade_issue

    client = TriggerIssueClient(
        _upgrade_trigger_issue(
            issue_state="已接纳",
            issue_state_detail={"title": "已接纳"},
        )
    )

    finalize_upgrade_issue(
        client=client,
        target_repo=TARGET_REPO,
        issue_number=81,
        outcome="failure",
        run_url="https://github.com/Meihan-chen/repo/actions/runs/456",
        summary="- 升级任务：`failure`",
        failure_summary="**Validate x86_64**\n\n```text\nerror: boom\n```",
    )

    body = client.calls[1][1]["body"]
    assert body.startswith("## 自动升级流水线未完成")
    assert "- **场景**：② 应用自动升级" in body
    assert "- **Workflow**：https://github.com/Meihan-chen/repo/actions/runs/456" in body
    assert "### 摘要" in body
    assert "- 升级任务：`failure`" in body
    assert "### 失败摘要" in body
    assert "**Validate x86_64**" in body
