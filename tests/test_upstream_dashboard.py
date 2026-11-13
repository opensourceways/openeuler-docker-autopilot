"""upstream-dashboard 版本解析客户端单测（不联网）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.lib import upstream_dashboard  # noqa: E402

_PAYLOAD = {
    "name": "x265",
    "tag": "3.4",
    "version": "3.4",
    "display_version": "3.4",
    "tag_url": "https://github.com/Multicorewareinc/x265/releases/tag/3.4",
    "commit_sha": "abc123",
    "source": "latest_tag",
    "blocked_reason": None,
    "fetched_at": "2026-11-13T01:00:00",
    # 接口后续可能新增的字段必须原样保留
    "upstream_evidence": [{"check": "build_script", "ok": True}],
}


class _Response:
    def __init__(self, status_code: int, payload=None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class ResolveVersionTest(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.object(upstream_dashboard.time, "sleep")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_returns_payload_verbatim_including_unknown_fields(self) -> None:
        with mock.patch.object(
            upstream_dashboard.requests, "get", return_value=_Response(200, _PAYLOAD)
        ):
            payload = upstream_dashboard.resolve_version("x265")
        assert payload == _PAYLOAD
        assert upstream_dashboard.is_usable(payload) is True

    def test_blocked_reason_makes_payload_unusable(self) -> None:
        payload = dict(_PAYLOAD, blocked_reason="no_release")
        assert upstream_dashboard.is_usable(payload) is False

    def test_400_and_404_are_deterministic_misses(self) -> None:
        for status in (400, 404):
            with mock.patch.object(
                upstream_dashboard.requests, "get", return_value=_Response(status, {"detail": "x"})
            ):
                assert upstream_dashboard.resolve_version("nope") is None

    def test_502_is_retried_then_succeeds(self) -> None:
        responses = [_Response(502, {"detail": "bad gateway"}), _Response(200, _PAYLOAD)]
        with mock.patch.object(
            upstream_dashboard.requests, "get", side_effect=responses
        ) as getter:
            payload = upstream_dashboard.resolve_version("x265")
        assert payload == _PAYLOAD
        assert getter.call_count == 2

    def test_503_raises_immediately(self) -> None:
        with mock.patch.object(
            upstream_dashboard.requests, "get", return_value=_Response(503, {"detail": "no token"})
        ):
            with pytest.raises(upstream_dashboard.DashboardError, match="503"):
                upstream_dashboard.resolve_version("x265")

    def test_418_warms_up_waf_cookie_and_retries(self) -> None:
        responses = [
            _Response(418, None, "waf"),
            _Response(200, _PAYLOAD),
        ]
        with (
            mock.patch.object(
                upstream_dashboard.requests, "get", side_effect=responses
            ) as getter,
            mock.patch.object(
                upstream_dashboard, "_warm_up_cookies"
            ) as warm_up,
        ):
            payload = upstream_dashboard.resolve_version("x265")

        assert payload == _PAYLOAD
        warm_up.assert_called_once()
        assert getter.call_count == 2

    def test_base_url_can_be_overridden(self) -> None:
        with mock.patch.dict(
            "os.environ",
            {"UPSTREAM_DASHBOARD_BASE": "https://dashboard.internal:8000/"},
            clear=False,
        ):
            assert upstream_dashboard.base_url() == "https://dashboard.internal:8000"

    def test_version_parameter_is_forwarded(self) -> None:
        with mock.patch.object(
            upstream_dashboard.requests, "get", return_value=_Response(200, _PAYLOAD)
        ) as getter:
            upstream_dashboard.resolve_version("x265", "3.4")
        assert getter.call_args.kwargs["params"] == {"name": "x265", "version": "3.4"}


def _software_payload() -> dict:
    return {
        "items": [
            {
                "id": 453,
                "name": "Nginx",
                "latest_version": "1.31.8",
                "versions": [
                    {
                        "version": "1.31.7",
                        "version_type": "superseded",
                        "levels": [
                            {
                                "support_level": "L1",
                                "evidence": [
                                    {
                                        "check_id": "kp.l1.arm_ci",
                                        "result": "supported",
                                        "matched_version": "1.31.7",
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "version": "1.31.8",
                        "version_type": "latest_release",
                        "levels": [
                            {
                                "support_level": "L1",
                                "evidence": [
                                    {
                                        "check_id": "kp.l1.arm_ci",
                                        "result": "supported",
                                        "matched_version": "1.31.8",
                                    },
                                    {
                                        "check_id": "kp.l1.doc_declared",
                                        "result": "not_found",
                                    },
                                    {
                                        "check_id": "kp.l1.release_artifact",
                                        "result": "not_found",
                                    },
                                ],
                            },
                            {
                                "support_level": "L3",
                                "evidence": [
                                    {"check_id": "kp.l3.openeuler_conda", "result": "blocked"},
                                    {"check_id": "kp.l3.openeuler_image", "result": "supported"},
                                    {"check_id": "kp.l3.openeuler_rpm", "result": "not_found"},
                                ],
                            },
                        ],
                    },
                ],
            }
        ]
    }


class FetchEvidenceTest(unittest.TestCase):
    def test_returns_only_the_three_l1_checks(self) -> None:
        with mock.patch.object(
            upstream_dashboard.requests,
            "get",
            return_value=_Response(200, _software_payload()),
        ):
            evidence = upstream_dashboard.fetch_evidence("Nginx", "1.31.8")

        self.assertEqual(len(evidence), 3)
        self.assertEqual(
            [item["check_id"] for item in evidence],
            [
                "kp.l1.arm_ci",
                "kp.l1.doc_declared",
                "kp.l1.release_artifact",
            ],
        )
        # 每条证据都带上所属等级
        self.assertTrue(all(item["support_level"] == "L1" for item in evidence))

    def test_l3_only_software_falls_back_to_its_level(self) -> None:
        payload = _software_payload()
        payload["items"][0]["versions"][1]["levels"] = [
            payload["items"][0]["versions"][1]["levels"][1]
        ]
        with mock.patch.object(
            upstream_dashboard.requests, "get", return_value=_Response(200, payload)
        ):
            evidence = upstream_dashboard.fetch_evidence("Nginx", "1.31.8")

        self.assertEqual(
            [item["check_id"] for item in evidence],
            [
                "kp.l3.openeuler_conda",
                "kp.l3.openeuler_image",
                "kp.l3.openeuler_rpm",
            ],
        )
        self.assertTrue(all(item["support_level"] == "L3" for item in evidence))

    def test_empty_l1_level_falls_back_to_the_next_level(self) -> None:
        payload = _software_payload()
        levels = payload["items"][0]["versions"][1]["levels"]
        payload["items"][0]["versions"][1]["levels"] = [
            {"support_level": "L1", "evidence": []},
            levels[1],
        ]
        with mock.patch.object(
            upstream_dashboard.requests, "get", return_value=_Response(200, payload)
        ):
            evidence = upstream_dashboard.fetch_evidence("Nginx", "1.31.8")
        self.assertTrue(evidence)
        self.assertTrue(all(item["support_level"] == "L3" for item in evidence))

    def test_v_prefix_and_latest_version_fallback(self) -> None:
        with mock.patch.object(
            upstream_dashboard.requests,
            "get",
            return_value=_Response(200, _software_payload()),
        ):
            evidence = upstream_dashboard.fetch_evidence("Nginx", "v1.31.8")
        self.assertEqual(len(evidence), 3)

        with mock.patch.object(
            upstream_dashboard.requests,
            "get",
            return_value=_Response(200, _software_payload()),
        ):
            evidence = upstream_dashboard.fetch_evidence("Nginx")
        self.assertEqual(len(evidence), 3)

    def test_exact_name_wins_over_fuzzy_matches(self) -> None:
        payload = _software_payload()
        payload["items"].insert(
            0,
            {
                "id": 99,
                "name": "Nginx (old)",
                "versions": [
                    {
                        "version": "0.9.0",
                        "version_type": "latest_release",
                        "levels": [{"support_level": "L1", "evidence": [{"check_id": "wrong"}]}],
                    }
                ],
            },
        )
        with mock.patch.object(
            upstream_dashboard.requests, "get", return_value=_Response(200, payload)
        ):
            evidence = upstream_dashboard.fetch_evidence("Nginx", "1.31.8")
        self.assertEqual(len(evidence), 3)
        self.assertNotIn("wrong", [item["check_id"] for item in evidence])

    def test_evidence_failures_never_raise(self) -> None:
        for response in (
            _Response(500, {"detail": "boom"}),
            _Response(200, None),
        ):
            with mock.patch.object(
                upstream_dashboard.requests, "get", return_value=response
            ):
                self.assertEqual(upstream_dashboard.fetch_evidence("Nginx"), [])

        with mock.patch.object(
            upstream_dashboard.requests,
            "get",
            side_effect=upstream_dashboard.requests.RequestException("offline"),
        ):
            self.assertEqual(upstream_dashboard.fetch_evidence("Nginx"), [])
