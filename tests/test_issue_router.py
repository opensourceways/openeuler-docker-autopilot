import json

import pytest

from scripts.lib.issue_router import (
    SCENARIO_NEW_IMAGE,
    SCENARIO_OE_UPGRADE,
    SCENARIO_UPGRADE,
    IssueRoutingError,
    parse_issue_type,
    route_issue,
)

TARGET_REPO = "openeuler/openeuler-docker-images"


def _new_image_body(type_value="new-image"):
    return (
        f"**任务类型（Type）：** {type_value}\n"
        "**软件包名称（Package Name）：** kvrocks\n"
        "**源码仓库（Source Repository）：** "
        "https://github.com/apache/kvrocks/tree/v2.16.0\n"
        "**所属领域（Domain）：** Database\n"
        "**openEuler 版本（openEuler Version）：** 24.03-lts-sp4\n"
        "**应用版本（App Version）：** 2.16.0\n"
    )


def _upgrade_body(type_value="upgrade-version"):
    payload = {
        "software": {
            "name": "grpc",
            "repo_url": "https://github.com/grpc/grpc",
            "version": "1.85.4",
        }
    }
    return (
        f"**任务类型（Type）：** {type_value}\n"
        "**软件名（Software）：** grpc\n"
        "**目标版本（Target Version）：** 1.85.4\n"
        "**openEuler 版本（openEuler Version）：** 24.03-lts-sp4\n\n"
        "```json\n"
        f"{json.dumps(payload)}\n"
        "```\n"
    )


def _oe_body(type_value="oe-upgrade"):
    return (
        f"**任务类型（Type）：** {type_value}\n"
        "**openEuler 目标版本（Target openEuler Version）：** 24.03-lts-sp4\n"
        "**Scope：** HPC,Database\n"
    )


@pytest.mark.parametrize(
    ("declared", "expected"),
    [
        ("new-image", SCENARIO_NEW_IMAGE),
        ("NEW_IMAGE", SCENARIO_NEW_IMAGE),
        ("新建镜像", SCENARIO_NEW_IMAGE),
        ("upgrade-version", SCENARIO_UPGRADE),
        ("应用升级", SCENARIO_UPGRADE),
        ("Upgrade", SCENARIO_UPGRADE),
        ("oe-upgrade", SCENARIO_OE_UPGRADE),
        ("系统升级", SCENARIO_OE_UPGRADE),
    ],
)
def test_body_type_selects_scenario(declared, expected):
    assert route_issue("【镜像任务】任意描述", _new_image_body(declared)) == expected


def test_legacy_titles_still_route():
    assert (
        route_issue("【new-image】add kvrocks docker image on openEuler 24.03", "")
        == SCENARIO_NEW_IMAGE
    )
    assert (
        route_issue("【new-version】upgrade grpc to 1.85.4 on openEuler 24.03", "")
        == SCENARIO_UPGRADE
    )
    assert (
        route_issue("【oe-upgrade】补齐 openEuler 24.03-LTS-SP4 镜像", "")
        == SCENARIO_OE_UPGRADE
    )


def test_body_type_wins_over_legacy_title():
    body = _oe_body()
    assert route_issue("【镜像任务】补齐镜像", body) == SCENARIO_OE_UPGRADE


def test_missing_type_and_unknown_title_is_rejected():
    with pytest.raises(IssueRoutingError, match="无法判断场景"):
        route_issue("【镜像任务】没有类型", "只有一段描述")


def test_conflicting_type_and_legacy_title_is_rejected():
    with pytest.raises(IssueRoutingError, match="不一致"):
        route_issue("【new-image】add kvrocks docker image", _oe_body())


def test_unknown_type_is_rejected():
    with pytest.raises(IssueRoutingError, match="unsupported"):
        route_issue("【镜像任务】描述", _new_image_body("hotfix"))


def test_duplicate_type_is_rejected():
    body = _new_image_body() + "**任务类型（Type）：** oe-upgrade\n"
    with pytest.raises(IssueRoutingError, match="duplicate"):
        parse_issue_type(body)


def test_unified_new_image_reads_every_parameter_from_body():
    from scripts.harness.parse_issue import parse_new_image_request

    fields = parse_new_image_request("【镜像任务】新增 kvrocks 镜像", _new_image_body())

    assert fields == {
        "package_name": "kvrocks",
        "source_repo_url": "https://github.com/apache/kvrocks/tree/v2.16.0",
        "domain": "Database",
        "os_version": "24.03-lts-sp4",
        "app_version": "2.16.0",
    }


def test_unified_new_image_requires_openEuler_version_in_body():
    from scripts.harness.parse_issue import parse_new_image_request

    body = _new_image_body().replace(
        "**openEuler 版本（openEuler Version）：** 24.03-lts-sp4\n", ""
    )
    with pytest.raises(ValueError, match="os_version"):
        parse_new_image_request("【镜像任务】新增 kvrocks 镜像", body)


def test_unified_upgrade_reads_parameters_from_body():
    from scripts.harness.parse_issue import parse_upgrade_request

    fields = parse_upgrade_request("【镜像任务】升级 grpc", _upgrade_body())

    assert fields["app"] == "grpc"
    assert fields["version"] == "1.85.4"
    assert fields["os_version"] == "24.03-lts-sp4"
    assert fields["source_url"] == "https://github.com/grpc/grpc"
    assert fields["evidence"]["software"]["name"] == "grpc"


def test_unified_upgrade_rejects_evidence_version_mismatch():
    from scripts.harness.parse_issue import parse_upgrade_request

    body = _upgrade_body().replace('"version": "1.85.4"', '"version": "1.84.0"')
    with pytest.raises(ValueError, match="software.version"):
        parse_upgrade_request("【镜像任务】升级 grpc", body)


def test_unified_oe_upgrade_reads_version_from_body():
    from scripts.lib.oe_upgrade_contract import parse_upgrade_issue

    options = parse_upgrade_issue(
        321, "【镜像任务】补齐 openEuler 24.03-LTS-SP4 镜像", _oe_body(), mode="plan"
    )

    assert options.oe_version == "24.03-lts-sp4"
    assert options.scope == ("Database", "HPC")


def _route(issue):
    from scripts.harness.parse_issue import (
        parse_new_image_request,
        parse_upgrade_request,
    )

    title = issue["title"]
    body = issue["body"]
    scenario = route_issue(title, body)
    if scenario == SCENARIO_NEW_IMAGE:
        return scenario, parse_new_image_request(title, body)
    if scenario == SCENARIO_UPGRADE:
        return scenario, parse_upgrade_request(title, body)
    return scenario, {"body": body}


class _FakeClient:
    def __init__(self, issues):
        self.issues = [dict(issue) for issue in issues]
        self.calls = []

    def list_issues(self, **kwargs):
        self.calls.append(("list", kwargs))
        return [dict(issue) for issue in self.issues]

    def get_issue(self, **kwargs):
        self.calls.append(("get", kwargs))
        return next(
            issue for issue in self.issues if issue["number"] == kwargs["number"]
        )

    def update_issue(self, **kwargs):
        self.calls.append(("update", kwargs))
        for issue in self.issues:
            if issue["number"] == kwargs["number"]:
                issue["issue_state"] = kwargs["issue_status"]
                issue["state"] = kwargs["state"]
        return object()

    def create_issue_comment(self, **kwargs):
        self.calls.append(("comment", kwargs))
        return {}


def _issue(number, title, body):
    return {
        "number": number,
        "html_url": f"https://gitcode.com/example/issues/{number}",
        "title": title,
        "body": body,
        "state": "open",
        "issue_state": "新建",
    }


def _comments():
    return {
        SCENARIO_NEW_IMAGE: "新增镜像请求已接纳。",
        SCENARIO_UPGRADE: "升级请求已接纳。",
        SCENARIO_OE_UPGRADE: "版本升级请求已接纳。",
    }


def test_claim_routed_issue_dispatches_the_scenario_named_in_the_body():
    from scripts.lib.issue_lifecycle import claim_routed_issue

    client = _FakeClient([_issue(51, "【镜像任务】新增 kvrocks 镜像", _new_image_body())])
    dispatched = []

    claimed = claim_routed_issue(
        client=client,
        target_repo=TARGET_REPO,
        issue_number=None,
        route=_route,
        dispatch=lambda scenario, payload, number: dispatched.append(
            (scenario, payload, number)
        ),
        accepted_comments=_comments(),
    )

    assert claimed is not None
    assert claimed.scenario == SCENARIO_NEW_IMAGE
    assert claimed.number == 51
    scenario, payload, number = dispatched[0]
    assert scenario == SCENARIO_NEW_IMAGE
    assert payload["package_name"] == "kvrocks"
    assert payload["os_version"] == "24.03-lts-sp4"
    assert number == 51
    list_call = client.calls[0][1]
    assert list_call["search"] == "【镜像任务】"
    update_call = next(call for name, call in client.calls if name == "update")
    assert update_call["issue_status"] == "已接纳"
    comment = next(call for name, call in client.calls if name == "comment")
    assert comment["body"] == _comments()[SCENARIO_NEW_IMAGE]


def test_claim_routed_issue_skips_legacy_titled_issues():
    from scripts.lib.issue_lifecycle import claim_routed_issue

    legacy = _issue(
        53,
        "【new-version】upgrade grpc to 1.85.4 on openEuler 24.03-lts-sp4",
        _upgrade_body(),
    )
    unified = _issue(54, "【镜像任务】升级 grpc", _upgrade_body())
    client = _FakeClient([legacy, unified])
    dispatched = []

    claimed = claim_routed_issue(
        client=client,
        target_repo=TARGET_REPO,
        issue_number=None,
        route=_route,
        dispatch=lambda *args: dispatched.append(args),
        accepted_comments=_comments(),
    )

    assert claimed is not None
    assert claimed.number == 54
    assert claimed.scenario == SCENARIO_UPGRADE
    assert len(dispatched) == 1


def test_claim_routed_issue_rejects_issue_without_type():
    from scripts.lib.issue_lifecycle import claim_routed_issue

    client = _FakeClient([_issue(52, "【镜像任务】没有类型", "只有一段描述")])
    dispatched = []

    claimed = claim_routed_issue(
        client=client,
        target_repo=TARGET_REPO,
        issue_number=None,
        route=_route,
        dispatch=lambda *args: dispatched.append(args),
        accepted_comments=_comments(),
    )

    assert claimed is None
    assert dispatched == []
    update_call = next(call for name, call in client.calls if name == "update")
    assert update_call["issue_status"] == "已拒绝"
    comment = next(call for name, call in client.calls if name == "comment")
    assert "无法判断场景" in comment["body"]
