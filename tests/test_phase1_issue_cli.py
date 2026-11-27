import argparse
import json
from dataclasses import dataclass
from types import SimpleNamespace

import pytest


def _task_file(tmp_path):
    path = tmp_path / "task.json"
    path.write_text(
        json.dumps(
            {
                "app": "kvrocks",
                "version": "2.16.0",
                "os_version": "24.03-lts-sp4",
                "domain": "Database",
                "source_url": (
                    "https://github.com/apache/kvrocks/tree/v2.16.0"
                ),
                "scenario": "new-image",
            }
        )
    )
    return path


@dataclass(frozen=True)
class Resource:
    number: int = 19
    url: str = "https://gitcode.com/example/issues/19"


def test_issue_contract_handler_is_fixed_to_explicit_test_operation(
    tmp_path, monkeypatch, capsys
):
    from scripts.harness import flow

    calls = []
    client = object()
    monkeypatch.setenv("GITCODE_TOKEN", "secret")
    monkeypatch.setattr(
        flow,
        "GitCodeClient",
        lambda **kwargs: calls.append(("client", kwargs)) or client,
    )
    monkeypatch.setattr(
        flow,
        "run_controlled_issue_probe",
        lambda **kwargs: calls.append(("probe", kwargs)) or Resource(),
    )

    flow._issue_contract_test(
        argparse.Namespace(
            task_spec=_task_file(tmp_path),
            github_run_id="123456",
            github_run_url=(
                "https://github.com/opensourceways/"
                "openeuler-docker-autopilot/actions/runs/123456"
            ),
            failure_stage="aarch64-build",
        )
    )

    assert calls[0] == ("client", {"token": "secret"})
    probe = calls[1][1]
    assert probe["client"] is client
    assert probe["target_repo"] == "openeuler/openeuler-docker-images"
    assert probe["environment"] == "test"
    assert probe["operation"] == "failure_issue_contract_test"
    assert probe["github_run_id"] == "123456"
    assert probe["github_run_url"] == (
        "https://github.com/opensourceways/"
        "openeuler-docker-autopilot/actions/runs/123456"
    )
    assert json.loads(capsys.readouterr().out) == {
        "number": 19,
        "state": "closed",
        "url": "https://gitcode.com/example/issues/19",
    }


def test_issue_contract_handler_prefers_the_dedicated_issue_token(
    tmp_path, monkeypatch
):
    from scripts.harness import flow

    calls = []
    monkeypatch.setenv("GITCODE_TOKEN", "pr-secret")
    monkeypatch.setenv("GITCODE_ISSUE_TOKEN", "issue-secret")
    monkeypatch.setattr(
        flow,
        "GitCodeClient",
        lambda **kwargs: calls.append(kwargs) or object(),
    )
    monkeypatch.setattr(
        flow,
        "run_controlled_issue_probe",
        lambda **kwargs: Resource(),
    )

    flow._issue_contract_test(
        argparse.Namespace(
            task_spec=_task_file(tmp_path),
            github_run_id="123456",
            github_run_url="https://github.com/example/repo/actions/runs/123456",
            failure_stage="aarch64-build",
        )
    )

    assert calls == [{"token": "issue-secret"}]


def test_issue_contract_handler_requires_token_before_client_or_probe(
    tmp_path, monkeypatch
):
    from scripts.harness import flow
    from scripts.lib.issue_lifecycle import IssueLifecycleError

    calls = []
    monkeypatch.delenv("GITCODE_TOKEN", raising=False)
    monkeypatch.delenv("GITCODE_ISSUE_TOKEN", raising=False)
    monkeypatch.setattr(
        flow,
        "GitCodeClient",
        lambda **kwargs: calls.append("client"),
    )
    monkeypatch.setattr(
        flow,
        "run_controlled_issue_probe",
        lambda **kwargs: calls.append("probe"),
    )

    with pytest.raises(IssueLifecycleError, match="GITCODE_TOKEN"):
        flow._issue_contract_test(
            argparse.Namespace(
                task_spec=_task_file(tmp_path),
                github_run_id="123456",
                github_run_url="https://github.com/example/repo/actions/runs/123456",
                failure_stage="aarch64-build",
            )
        )

    assert calls == []


def test_issue_finalize_handler_updates_the_exact_source_issue(
    monkeypatch, capsys
):
    from scripts.harness import flow

    calls = []
    client = object()
    monkeypatch.setenv("GITCODE_TOKEN", "gitcode-secret")
    monkeypatch.setattr(
        flow,
        "GitCodeClient",
        lambda **kwargs: client,
    )
    monkeypatch.setattr(
        flow,
        "finalize_new_image_issue",
        lambda **kwargs: calls.append(kwargs),
    )

    flow._issue_finalize(
        argparse.Namespace(
            target_repo="openeuler/openeuler-docker-images",
            issue_number=64,
            outcome="success",
            run_url="https://github.com/example/repo/actions/runs/123",
            pr_url="https://gitcode.com/example/repo/pull/9",
            failure_summary="",
        )
    )

    assert calls == [
        {
            "client": client,
            "target_repo": "openeuler/openeuler-docker-images",
            "issue_number": 64,
            "outcome": "success",
            "run_url": "https://github.com/example/repo/actions/runs/123",
            "pr_url": "https://gitcode.com/example/repo/pull/9",
            "summary": "",
            "failure_summary": "",
        }
    ]
    assert json.loads(capsys.readouterr().out) == {
        "issue_number": 64,
        "outcome": "success",
    }


def test_issue_trigger_commands_exist_on_the_shared_flow_cli():
    from scripts.harness import flow

    dispatch = flow._parser().parse_args(
        [
            "issue-dispatch",
            "--target-repo",
            "openeuler/openeuler-docker-images",
            "--issue-number",
            "64",
            "--max-issues",
            "3",
            "--github-repository",
            "Meihan-chen/openeuler-docker-images-workflow",
            "--github-ref",
            "main",
        ]
    )
    finalize = flow._parser().parse_args(
        [
            "issue-finalize",
            "--target-repo",
            "openeuler/openeuler-docker-images",
            "--issue-number",
            "64",
            "--outcome",
            "failure",
            "--run-url",
            "https://github.com/example/repo/actions/runs/123",
        ]
    )

    assert dispatch.handler is flow._issue_dispatch
    assert dispatch.max_issues == 3
    assert finalize.handler is flow._issue_finalize


def test_issue_dispatch_number_filter_is_optional_for_production_selection():
    from scripts.harness import flow

    dispatch = flow._parser().parse_args(
        [
            "issue-dispatch",
            "--target-repo",
            "openeuler/openeuler-docker-images",
            "--github-repository",
            "opensourceways/openeuler-docker-autopilot",
            "--github-ref",
            "main",
        ]
    )

    assert dispatch.issue_number is None
    assert dispatch.max_issues == 1
