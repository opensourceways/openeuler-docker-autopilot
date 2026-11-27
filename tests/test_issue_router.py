import pytest

from scripts.lib.issue_router import (
    SCENARIO_NEW_IMAGE,
    SCENARIO_OE_UPGRADE,
    SCENARIO_UPGRADE,
    IssueRoutingError,
    route_issue,
)

TARGET_REPO = "openeuler/openeuler-docker-images"

UPGRADE_TITLE = (
    "【自动升级需求】upgrade grpc to 1.85.4 on openEuler 24.03-lts-sp4"
)
LEGACY_UPGRADE_TITLE = (
    "【new-version】upgrade grpc to 1.85.4 on openEuler 24.03-lts-sp4"
)
NEW_IMAGE_TITLE = (
    "【自动升级需求】add kvrocks 2.16.0 docker image on openEuler 24.03-LTS-SP4"
)
OE_UPGRADE_TITLE = (
    "【自动升级需求】upgrade openEuler to 24.03-LTS-SP4"
)
LEGACY_NEW_IMAGE_TITLE = (
    "【new-image】add kvrocks 2.16.0 docker image on openEuler 24.03-LTS-SP4"
)
LEGACY_OE_UPGRADE_TITLE = "【oe-upgrade】补齐 openEuler 24.03-LTS-SP4 镜像"


def _new_image_body():
    return (
        "**软件包名称（Package Name）：** kvrocks\n"
        "**源码仓库（Source Repository）：** "
        "https://github.com/apache/kvrocks/tree/v2.16.0\n"
        "**所属领域（Domain）：** Database\n"
    )


def _upgrade_body(name="grpc", version="1.85.4"):
    return (
        f"软件名: {name}\n"
        "源码仓库: https://github.com/grpc/grpc\n"
        f"软件版本: {version}\n"
        "门禁路径: .github/workflows/ci.yml\n"
        "测试深度: smoke\n"
    )


def _oe_body():
    return (
        "**openEuler 目标版本（Target openEuler Version）：** 24.03-lts-sp4\n"
        "**Scope：** HPC,Database\n"
    )


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        (UPGRADE_TITLE, SCENARIO_UPGRADE),
        (NEW_IMAGE_TITLE, SCENARIO_NEW_IMAGE),
        (OE_UPGRADE_TITLE, SCENARIO_OE_UPGRADE),
        (LEGACY_UPGRADE_TITLE, SCENARIO_UPGRADE),
        (LEGACY_NEW_IMAGE_TITLE, SCENARIO_NEW_IMAGE),
        (LEGACY_OE_UPGRADE_TITLE, SCENARIO_OE_UPGRADE),
    ],
)
def test_title_selects_scenario(title, expected):
    assert route_issue(title) == expected


def test_unknown_title_is_rejected():
    with pytest.raises(IssueRoutingError, match="无法判断场景"):
        route_issue("【镜像任务】没有类型")


def test_claim_routed_issue_dispatches_the_auto_upgrade_scenario():
    from scripts.lib.issue_lifecycle import claim_routed_issue

    client = _FakeClient([_issue(51, UPGRADE_TITLE, _upgrade_body())])
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
    assert claimed.scenario == SCENARIO_UPGRADE
    assert claimed.number == 51
    scenario, payload, number = dispatched[0]
    assert scenario == SCENARIO_UPGRADE
    assert payload["app"] == "grpc"
    assert payload["version"] == "1.85.4"
    assert number == 51
    list_call = client.calls[0][1]
    assert list_call["search"] == "【自动升级需求】"
    update_call = next(call for name, call in client.calls if name == "update")
    assert update_call["issue_status"] == "已接纳"
    comment = next(call for name, call in client.calls if name == "comment")
    assert comment["body"] == _comments()[SCENARIO_UPGRADE]


def test_claim_routed_issue_skips_legacy_titled_issues():
    from scripts.lib.issue_lifecycle import claim_routed_issue

    legacy = _issue(53, LEGACY_UPGRADE_TITLE, _upgrade_body())
    unified = _issue(54, UPGRADE_TITLE, _upgrade_body())
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


def test_claim_routed_issue_rejects_an_unroutable_title():
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


def test_explicit_new_image_issue_number_routes_to_scenario_one():
    from scripts.lib.issue_lifecycle import claim_routed_issue

    client = _FakeClient([_issue(61, NEW_IMAGE_TITLE, _new_image_body())])
    dispatched = []

    claimed = claim_routed_issue(
        client=client,
        target_repo=TARGET_REPO,
        issue_number=61,
        route=_route,
        dispatch=lambda scenario, payload, number: dispatched.append(
            (scenario, payload, number)
        ),
        accepted_comments=_comments(),
    )

    assert claimed is not None
    assert claimed.scenario == SCENARIO_NEW_IMAGE
    assert dispatched[0][1].app == "kvrocks"


def test_explicit_oe_upgrade_issue_number_routes_to_scenario_three():
    from scripts.lib.issue_lifecycle import claim_routed_issue

    client = _FakeClient([_issue(71, OE_UPGRADE_TITLE, _oe_body())])
    dispatched = []

    claimed = claim_routed_issue(
        client=client,
        target_repo=TARGET_REPO,
        issue_number=71,
        route=_route,
        dispatch=lambda scenario, payload, number: dispatched.append(
            (scenario, payload, number)
        ),
        accepted_comments=_comments(),
    )

    assert claimed is not None
    assert claimed.scenario == SCENARIO_OE_UPGRADE
    assert dispatched[0][1].oe_version == "24.03-lts-sp4"


def _route(issue):
    from scripts.harness.parse_issue import (
        parse_issue_request,
        parse_upgrade_issue_request,
    )
    from scripts.lib.oe_upgrade_contract import parse_upgrade_issue

    title = issue["title"]
    body = issue["body"]
    scenario = route_issue(title)
    if scenario == SCENARIO_NEW_IMAGE:
        fields = parse_issue_request(title, body)
        return scenario, _Task(fields)
    if scenario == SCENARIO_UPGRADE:
        return scenario, parse_upgrade_issue_request(title, body)
    number = int(issue.get("number", 0))
    return scenario, parse_upgrade_issue(number, title, body, mode="plan")


class _Task:
    def __init__(self, fields):
        self.app = fields["package_name"]


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
