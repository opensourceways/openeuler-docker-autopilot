"""Tests for parse_issue.py."""

import json
import sys
import urllib.error
import urllib.request
from io import BytesIO

sys.path.insert(0, "scripts/harness")

import pytest

from parse_issue import (
    IssueParseError,
    parse_issue_body,
    parse_issue_request,
    parse_upgrade_issue_request,
    validate,
)


SAMPLE_ISSUE = """**Package Name**: nginx
**Upstream Repository**: https://github.com/nginx/nginx
**Domain**: Cloud
**openEuler Version**: 24.03-lts
**App Version**: 1.27.2

## Description
Nginx is a high-performance HTTP server and reverse proxy.
"""


def test_parse_all_fields():
    fields = parse_issue_body(SAMPLE_ISSUE)
    assert fields["package_name"] == "nginx"
    assert fields["source_repo_url"] == "https://github.com/nginx/nginx"
    assert fields["domain"] == "Cloud"
    assert fields["os_version"] == "24.03-lts"
    assert fields["app_version"] == "1.27.2"


def test_validate_complete():
    fields = parse_issue_body(SAMPLE_ISSUE)
    missing = validate(fields)
    assert missing == []


def test_validate_missing():
    missing = validate({"package_name": "nginx"})
    assert "source_repo_url" in missing
    assert "domain" in missing


def test_derived_os_tag():
    fields = parse_issue_body(SAMPLE_ISSUE)
    assert fields["os_tag"] == "oe2403lts"


def test_domain_normalization():
    body = SAMPLE_ISSUE.replace("Cloud", "database")
    fields = parse_issue_body(body)
    assert fields["domain"] == "Database"


def test_target_repository_virtualization_domain_maps_to_cloud():
    body = (
        "**软件包名称（Package Name）：** kubeflow\n"
        "**源码仓库（Source Repository）：** "
        "https://github.com/kubeflow/kubeflow\n"
        "**所属领域（Domain）：** 虚拟化\n"
    )

    assert parse_issue_body(body)["domain"] == "Cloud"


MINIMAL_TARGET_ISSUE = """**软件包名称（Package Name）：** kvrocks
**源码仓库（Source Repository）：** https://github.com/apache/kvrocks/tree/v2.16.0
**所属领域（Domain）：** 数据库
"""


def test_parse_target_repository_minimal_bilingual_issue():
    fields = parse_issue_request(
        "【new-image】add kvrocks 2.16.0 docker image on openEuler 24.03-LTS-SP4",
        MINIMAL_TARGET_ISSUE,
    )

    assert fields == {
        "package_name": "kvrocks",
        "source_repo_url": (
            "https://github.com/apache/kvrocks/tree/v2.16.0"
        ),
        "domain": "Database",
        "os_version": "24.03-LTS-SP4",
        "app_version": "2.16.0",
    }


def test_parse_minimal_issue_can_take_version_from_pinned_source_url():
    fields = parse_issue_request(
        "【new-image】add kvrocks docker image on openEuler 24.03-LTS-SP4",
        MINIMAL_TARGET_ISSUE,
    )

    assert fields["app_version"] == "2.16.0"


def test_parse_pinned_source_url_keeps_a_compound_upstream_version():
    body = MINIMAL_TARGET_ISSUE.replace(
        "https://github.com/apache/kvrocks/tree/v2.16.0",
        (
            "https://github.com/percona/percona-server/tree/"
            "Percona-Server-5.5.25a-27.1"
        ),
    ).replace("kvrocks", "percona-server")

    fields = parse_issue_request(
        "【new-image】add percona-server docker image on openEuler 24.03-LTS-SP4",
        body,
    )

    assert fields["app_version"] == "5.5.25a-27.1"


def test_title_version_takes_precedence_over_a_different_source_ref(monkeypatch):
    def unexpected_urlopen(request, timeout):
        pytest.fail(f"latest release lookup was not expected: {request.full_url}")

    monkeypatch.setattr(urllib.request, "urlopen", unexpected_urlopen)

    fields = parse_issue_request(
        "【new-image】add kvrocks 3.0.0 docker image on openEuler 24.03-LTS-SP4",
        MINIMAL_TARGET_ISSUE,
    )

    assert fields["app_version"] == "3.0.0"
    assert fields["source_repo_url"].endswith("/tree/v2.16.0")


def test_parse_minimal_issue_uses_latest_github_release_or_tag_when_version_is_omitted(
    monkeypatch,
):
    requested_urls = []

    def fake_urlopen(request, timeout):
        requested_urls.append((request.full_url, timeout))
        if request.full_url.endswith("/releases/latest"):
            payload = {
                "tag_name": "Percona-Server-5.5.55-38.8",
                "published_at": "2017-07-05T20:27:17Z",
            }
        elif request.full_url.endswith("/graphql"):
            payload = {
                "data": {
                    "repository": {
                        "refs": {
                            "nodes": [
                                {
                                    "name": "Percona-Server-9.7.1-1",
                                    "target": {
                                        "tagger": {
                                            "date": "2026-08-05T09:22:28Z",
                                        },
                                        "target": {
                                            "committedDate": (
                                                "2026-07-26T15:44:44Z"
                                            ),
                                        },
                                    },
                                }
                            ]
                        }
                    }
                }
            }
        else:
            payload = [
                {"ref": "refs/tags/12.4"},
                {"ref": "refs/tags/mysqlsummit-0.2.1"},
                {"ref": "refs/tags/Percona-Server-5.5.25a-27.1"},
                {"ref": "refs/tags/Percona-Server-8.4.10-10"},
                {"ref": "refs/tags/Percona-Server-9.7.1-1"},
                {"ref": "refs/tags/version_where_test_case_for_bug_31581_works"},
            ]
        return BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    body = MINIMAL_TARGET_ISSUE.replace(
        "https://github.com/apache/kvrocks/tree/v2.16.0",
        "https://github.com/percona/percona-server",
    ).replace("kvrocks", "percona-server")

    fields = parse_issue_request(
        "【new-image】add percona-server docker image on openEuler 24.03-LTS-SP4",
        body,
    )

    assert fields["app_version"] == "9.7.1-1"
    assert fields["source_repo_url"] == (
        "https://github.com/percona/percona-server/tree/Percona-Server-9.7.1-1"
    )
    assert requested_urls == [
        (
            "https://api.github.com/repos/percona/percona-server/releases/latest",
            30,
        ),
        (
            "https://api.github.com/graphql",
            30,
        ),
    ]


def test_parse_minimal_issue_falls_back_to_latest_github_tag(monkeypatch):
    requested_urls = []

    def fake_urlopen(request, timeout):
        requested_urls.append(request.full_url)
        if request.full_url.endswith("/releases/latest"):
            raise urllib.error.HTTPError(
                request.full_url,
                404,
                "Not Found",
                {},
                None,
            )
        payload = {
            "data": {
                "repository": {
                    "refs": {
                        "nodes": [
                            {
                                "name": "v9.1.0",
                                "target": {
                                    "committedDate": "2026-07-01T00:00:00Z",
                                },
                            }
                        ]
                    }
                }
            }
        }
        return BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    body = MINIMAL_TARGET_ISSUE.replace(
        "https://github.com/apache/kvrocks/tree/v2.16.0",
        "https://github.com/example/no-releases",
    ).replace("kvrocks", "example-app")

    fields = parse_issue_request(
        "【new-image】add example-app docker image on openEuler 24.03-LTS-SP4",
        body,
    )

    assert fields["app_version"] == "9.1.0"
    assert fields["source_repo_url"] == (
        "https://github.com/example/no-releases/tree/v9.1.0"
    )
    assert requested_urls == [
        "https://api.github.com/repos/example/no-releases/releases/latest",
        "https://api.github.com/graphql",
    ]


def test_parse_minimal_issue_rejects_title_and_body_package_mismatch():
    with pytest.raises(IssueParseError, match="package"):
        parse_issue_request(
            "【new-image】add nginx 1.27.2 docker image on openEuler 24.03-LTS-SP4",
            MINIMAL_TARGET_ISSUE,
        )


def test_validate_accepts_the_target_repository_three_field_body():
    assert validate(parse_issue_body(MINIMAL_TARGET_ISSUE)) == []


UPGRADE_ISSUE_TITLE = (
    "【new-version】upgrade grpc to 1.85.4 on openEuler 24.03-lts-sp4"
)


def _upgrade_body(**overrides) -> str:
    payload = {
        "software": {
            "name": "grpc",
            "repo_url": "https://github.com/grpc/grpc",
            "version": "1.85.4",
            "raw_category": "rpc",
        },
        "upstream_evidence": {
            "support_level": "L1",
            "evidence": {
                "check_id": "kp.l1.arm_ci",
                "source_url": "https://ci.example.com/jobs/1",
                "ci_workflows": [],
            },
        },
        "l3_evidence": {
            "check_id": "kp.l3.openeuler_image",
            "artifact": "1.85.4-oe2403sp4",
            "source_url": (
                "https://gitcode.com/openeuler/openeuler-docker-images/"
                "tree/master/Others/grpc"
            ),
        },
        "install_candidates": [
            {
                "type": "source",
                "url": "https://github.com/grpc/grpc/archive/v1.85.4.tar.gz",
                "artifact": "grpc-1.85.4.tar.gz",
            }
        ],
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


def test_parse_upgrade_issue_returns_the_full_evidence_payload():
    fields = parse_upgrade_issue_request(
        UPGRADE_ISSUE_TITLE, _upgrade_body()
    )

    assert fields["app"] == "grpc"
    assert fields["version"] == "1.85.4"
    assert fields["os_version"] == "24.03-lts-sp4"
    assert fields["source_url"] == "https://github.com/grpc/grpc"
    assert fields["evidence"]["software"]["version"] == "1.85.4"
    assert (
        fields["evidence"]["upstream_evidence"]["evidence"]["check_id"]
        == "kp.l1.arm_ci"
    )


def test_parse_upgrade_issue_accepts_a_fenced_json_body():
    body = "升级说明：\n\n```json\n" + _upgrade_body() + "\n```\n"

    fields = parse_upgrade_issue_request(UPGRADE_ISSUE_TITLE, body)

    assert fields["source_url"] == "https://github.com/grpc/grpc"
    assert fields["evidence"]["software"]["name"] == "grpc"


def test_parse_upgrade_issue_requires_the_evidence_body():
    with pytest.raises(IssueParseError, match="evidence JSON object"):
        parse_upgrade_issue_request(UPGRADE_ISSUE_TITLE, "")


def test_parse_upgrade_issue_only_requires_software():
    payload = json.loads(_upgrade_body())
    payload.pop("upstream_evidence")
    payload.pop("l3_evidence")
    payload.pop("install_candidates")

    fields = parse_upgrade_issue_request(
        UPGRADE_ISSUE_TITLE, json.dumps(payload, ensure_ascii=False)
    )

    assert fields["version"] == "1.85.4"


@pytest.mark.parametrize("field", ("software",))
def test_parse_upgrade_issue_requires_every_schema_field(field):
    payload = json.loads(_upgrade_body())
    payload.pop(field)

    with pytest.raises(IssueParseError, match=f"missing required field: {field}"):
        parse_upgrade_issue_request(
            UPGRADE_ISSUE_TITLE, json.dumps(payload, ensure_ascii=False)
        )


def test_parse_upgrade_issue_rejects_a_mismatched_software_name():
    payload = json.loads(_upgrade_body())
    payload["software"]["name"] = "slurm"

    with pytest.raises(IssueParseError, match="software.name"):
        parse_upgrade_issue_request(
            UPGRADE_ISSUE_TITLE, json.dumps(payload, ensure_ascii=False)
        )


def test_parse_upgrade_issue_rejects_a_mismatched_version():
    payload = json.loads(_upgrade_body())
    payload["software"]["version"] = "1.86.0"

    with pytest.raises(IssueParseError, match="software.version"):
        parse_upgrade_issue_request(
            UPGRADE_ISSUE_TITLE, json.dumps(payload, ensure_ascii=False)
        )


def test_parse_upgrade_issue_accepts_a_v_prefixed_version_value():
    payload = json.loads(_upgrade_body())
    payload["software"]["version"] = "v1.85.4"

    fields = parse_upgrade_issue_request(
        UPGRADE_ISSUE_TITLE, json.dumps(payload, ensure_ascii=False)
    )

    assert fields["version"] == "1.85.4"


def test_parse_upgrade_issue_requires_an_https_repo_url():
    payload = json.loads(_upgrade_body())
    payload["software"]["repo_url"] = "http://github.com/grpc/grpc"

    with pytest.raises(IssueParseError, match="HTTPS"):
        parse_upgrade_issue_request(
            UPGRADE_ISSUE_TITLE, json.dumps(payload, ensure_ascii=False)
        )


def test_parse_upgrade_issue_rejects_an_unknown_candidate_type():
    payload = json.loads(_upgrade_body())
    payload["install_candidates"][0]["type"] = "source/binary"

    with pytest.raises(IssueParseError, match="source or binary"):
        parse_upgrade_issue_request(
            UPGRADE_ISSUE_TITLE, json.dumps(payload, ensure_ascii=False)
        )


def test_parse_upgrade_issue_rejects_an_unsafe_app_name():
    with pytest.raises(IssueParseError, match="app name"):
        parse_upgrade_issue_request(
            "【new-version】upgrade grpc;rm to 1.85.4 on openEuler 24.03-lts",
            "",
        )


def test_parse_upgrade_issue_rejects_a_non_matching_title():
    with pytest.raises(IssueParseError, match="title must match"):
        parse_upgrade_issue_request(
            "【new-image】add grpc 1.85.4 docker image on openEuler 24.03-lts",
            "",
        )
