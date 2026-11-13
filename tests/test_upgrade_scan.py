"""场景二升级候选发现单测（不联网）。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.harness import upgrade_scan  # noqa: E402


def _make_app(repo: Path, domain: str, app: str, versions=("2.16.0",),
              os_version: str = "24.03-lts-sp4") -> None:
    for version in versions:
        image = repo / domain / app / version / os_version
        image.mkdir(parents=True, exist_ok=True)
        (image / "Dockerfile").write_text("FROM x\n", encoding="utf-8")


def _payload(version: str, **overrides):
    payload = {
        "name": "kvrocks",
        "version": version,
        "tag": f"v{version}",
        "repo_url": "https://github.com/apache/kvrocks",
        "source": "latest_release",
        "fetched_at": "2026-11-13T01:00:00",
        "blocked_reason": None,
    }
    payload.update(overrides)
    return payload


class FindUpdatesTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name) / "target-repo"
        self.repo.mkdir()
        _make_app(self.repo, "Database", "kvrocks")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _scan(self, payload, **overrides):
        overrides.setdefault("resolve", lambda name: payload)
        overrides.setdefault("probe", lambda p: {"source": "self-probe", "status": "ok"})
        return upgrade_scan.find_updates(repo_dir=self.repo, **overrides)

    def test_new_version_becomes_an_upgrade_item(self) -> None:
        result = self._scan(_payload("2.17.0"))
        self.assertEqual(len(result["updates"]), 1)
        item = result["updates"][0]
        self.assertEqual(item["app"], "kvrocks")
        self.assertEqual(item["domain"], "Database")
        self.assertEqual(item["version"], "2.17.0")
        self.assertEqual(item["os_version"], "24.03-lts-sp4")
        self.assertEqual(item["source_url"], "https://github.com/apache/kvrocks")
        self.assertEqual(item["evidence"]["probe"]["status"], "ok")
        self.assertEqual(result["skipped"], [])

    def test_existing_version_is_skipped(self) -> None:
        result = self._scan(_payload("v2.16.0"))
        self.assertEqual(result["updates"], [])
        self.assertIn("已有版本目录", result["skipped"][0]["reason"])

    def test_blocked_reason_is_skipped(self) -> None:
        result = self._scan(_payload("2.17.0", blocked_reason="no_release"))
        self.assertEqual(result["updates"], [])
        self.assertIn("blocked_reason", result["skipped"][0]["reason"])

    def test_missing_software_is_skipped(self) -> None:
        result = self._scan(None)
        self.assertEqual(result["updates"], [])
        self.assertIn("400/404", result["skipped"][0]["reason"])

    def test_open_pr_is_skipped(self) -> None:
        calls = []

        def pr_exists(repo, branch, token):
            calls.append(branch)
            return {"number": 7}

        result = self._scan(
            _payload("2.17.0"),
            pr_exists=pr_exists,
            target_repo="openeuler/openeuler-docker-images",
            token="t",
        )
        self.assertEqual(result["updates"], [])
        self.assertIn("open PR", result["skipped"][0]["reason"])
        self.assertEqual(
            calls, ["auto/version-update/kvrocks/2.17.0-oe2403sp4"]
        )

    def test_forced_version_skips_the_dashboard(self) -> None:
        def fail(name):
            raise AssertionError("dashboard must not be called")

        result = upgrade_scan.find_updates(
            repo_dir=self.repo,
            app_filter="kvrocks",
            forced_version="2.18.0",
            resolve=fail,
            probe=lambda p: {},
        )
        self.assertEqual(result["updates"][0]["version"], "2.18.0")

    def test_unknown_app_raises(self) -> None:
        with self.assertRaises(SystemExit):
            upgrade_scan.find_updates(repo_dir=self.repo, app_filter="nope")

    def test_limit_stops_after_n_updates(self) -> None:
        _make_app(self.repo, "Database", "redis", versions=("1.0.0",))
        result = self._scan(_payload("2.17.0"), limit=1)
        self.assertEqual(len(result["updates"]), 1)


class NormalizeVersionTest(unittest.TestCase):
    def test_v_prefix_and_case_are_ignored(self) -> None:
        self.assertEqual(upgrade_scan._normalize_version("v1.2.3"), "1.2.3")
        self.assertEqual(upgrade_scan._normalize_version("V1.2.3"), "1.2.3")
        self.assertEqual(upgrade_scan._normalize_version(" 1.2.3 "), "1.2.3")
