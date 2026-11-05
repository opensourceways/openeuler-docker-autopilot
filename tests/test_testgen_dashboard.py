"""Tests for the upstream-dashboard catalogue client."""

from __future__ import annotations

import unittest
from unittest import mock

import requests

from scripts.lib import testgen_dashboard
from scripts.lib.testgen_dashboard import DashboardSoftware, fetch_dashboard_software


def _page(items: list[dict]) -> dict:
    return {"items": items}


_ITEM = {
    "name": "ClickHouse",
    "repo_url": "https://github.com/ClickHouse/ClickHouse",
    "latest_version": "26.10.2.103",
    "is_active": True,
}


class FetchDashboardSoftwareTest(unittest.TestCase):
    def _patch_get(self, responses):
        return mock.patch(
            "scripts.lib.testgen_dashboard.requests.get",
            side_effect=responses,
        )

    def test_paginates_until_empty_items(self) -> None:
        first = mock.Mock(ok=True)
        first.raise_for_status.return_value = None
        first.json.return_value = _page([_ITEM, dict(_ITEM, name="Python")])
        second = mock.Mock(ok=True)
        second.raise_for_status.return_value = None
        second.json.return_value = _page([])
        with self._patch_get([first, second]):
            software = fetch_dashboard_software()
        self.assertEqual(
            software,
            [
                DashboardSoftware(
                    name="ClickHouse",
                    repo_url="https://github.com/ClickHouse/ClickHouse",
                    latest_version="26.10.2.103",
                    is_active=True,
                ),
                DashboardSoftware(
                    name="Python",
                    repo_url="https://github.com/ClickHouse/ClickHouse",
                    latest_version="26.10.2.103",
                    is_active=True,
                ),
            ],
        )

    def test_missing_optional_fields_get_defaults(self) -> None:
        page = mock.Mock(ok=True)
        page.raise_for_status.return_value = None
        page.json.return_value = _page([{"name": "gulp"}])
        empty = mock.Mock(ok=True)
        empty.raise_for_status.return_value = None
        empty.json.return_value = _page([])
        with self._patch_get([page, empty]):
            result = fetch_dashboard_software()
        self.assertEqual(
            result,
            [DashboardSoftware(name="gulp", repo_url="", latest_version="", is_active=True)],
        )

    def test_skips_items_without_a_name(self) -> None:
        page = mock.Mock(ok=True)
        page.raise_for_status.return_value = None
        page.json.return_value = _page([{"repo_url": "https://x"}, {"name": "  "}])
        empty = mock.Mock(ok=True)
        empty.raise_for_status.return_value = None
        empty.json.return_value = _page([])
        with self._patch_get([page, empty]):
            result = fetch_dashboard_software()
        self.assertEqual(result, [])

    def test_retries_once_then_raises(self) -> None:
        error = requests.ConnectionError("boom")
        with self._patch_get([error, error]):
            with self.assertRaises(RuntimeError):
                fetch_dashboard_software()

    def test_recovers_on_second_attempt(self) -> None:
        error = requests.ConnectionError("boom")
        page = mock.Mock(ok=True)
        page.raise_for_status.return_value = None
        page.json.return_value = _page([])
        with self._patch_get([error, page]):
            result = fetch_dashboard_software()
        self.assertEqual(result, [])

    def test_malformed_payload_returns_none(self) -> None:
        page = mock.Mock(ok=True)
        page.raise_for_status.return_value = None
        page.json.return_value = {"unexpected": []}
        with self._patch_get([page]):
            self.assertIsNone(fetch_dashboard_software())

    def test_non_dict_payload_returns_none(self) -> None:
        page = mock.Mock(ok=True)
        page.raise_for_status.return_value = None
        page.json.return_value = [1, 2]
        with self._patch_get([page]):
            self.assertIsNone(fetch_dashboard_software())

    def test_http_error_retries_then_raises(self) -> None:
        response = mock.Mock(ok=False)
        response.raise_for_status.side_effect = requests.HTTPError("500")
        with self._patch_get([response, response]):
            with self.assertRaises(RuntimeError):
                fetch_dashboard_software()

    def test_request_url_and_params(self) -> None:
        page = mock.Mock(ok=True)
        page.raise_for_status.return_value = None
        page.json.return_value = _page([])
        with self._patch_get([page]) as get:
            fetch_dashboard_software(domain="ascend")
        call = get.call_args
        self.assertEqual(call.args[0], f"{testgen_dashboard.DASHBOARD_BASE}/api/v1/software")
        self.assertEqual(
            call.kwargs["params"],
            {"domain": "ascend", "page": 1, "page_size": testgen_dashboard._PAGE_SIZE},
        )


if __name__ == "__main__":
    unittest.main()
