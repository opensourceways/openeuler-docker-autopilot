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
