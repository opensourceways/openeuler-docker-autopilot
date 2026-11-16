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
        overrides.setdefault(
            "apps",
            [{"name": "kvrocks", "app": "kvrocks", "domain": "Database"}],
        )
        overrides.setdefault("resolve", lambda name: payload)
        overrides.setdefault("probe", lambda p: {"source": "self-probe", "status": "ok"})
        overrides.setdefault("fetch_evidence", lambda name, version: [])
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

    def test_dashboard_evidence_is_attached_to_the_item(self) -> None:
        checks = [
            {"check_id": "kp.l1.arm_ci", "result": "supported"},
            {"check_id": "kp.l1.doc_declared", "result": "not_found"},
            {"check_id": "kp.l1.release_artifact", "result": "not_found"},
        ]
        result = self._scan(
            _payload("2.17.0"),
            fetch_evidence=lambda name, version: checks,
        )
        item = result["updates"][0]
        self.assertEqual(
            [entry["check_id"] for entry in item["evidence"]["collector"]],
            [
                "kp.l1.arm_ci",
                "kp.l1.doc_declared",
                "kp.l1.release_artifact",
            ],
        )

    def test_evidence_fetch_failure_does_not_block_the_upgrade(self) -> None:
        def boom(name, version):
            raise RuntimeError("dashboard offline")

        result = self._scan(_payload("2.17.0"), fetch_evidence=boom)
        self.assertEqual(len(result["updates"]), 1)
        self.assertEqual(result["updates"][0]["evidence"]["collector"], [])

    def test_only_configured_apps_are_scanned(self) -> None:
        _make_app(self.repo, "Database", "unlisted")
        result = self._scan(_payload("2.17.0"))
        self.assertEqual([item["app"] for item in result["updates"]], ["kvrocks"])

    def test_configured_app_missing_from_repo_is_skipped(self) -> None:
        result = self._scan(
            _payload("2.17.0"),
            apps=[{"name": "gone", "app": "gone", "domain": "Database"}],
        )
        self.assertEqual(result["updates"], [])
        self.assertIn("目标仓没有", result["skipped"][0]["reason"])

    def test_filter_matches_the_dashboard_name(self) -> None:
        result = self._scan(
            _payload("2.17.0"),
            app_filter="Kvrocks",
            apps=[{"name": "Kvrocks", "app": "kvrocks", "domain": "Database"}],
        )
        self.assertEqual(len(result["updates"]), 1)

    def test_existing_version_becomes_an_audit(self) -> None:
        result = self._scan(_payload("v2.16.0"))
        self.assertEqual(result["updates"], [])
        self.assertEqual(len(result["audits"]), 1)
        audit = result["audits"][0]
        self.assertEqual(audit["app"], "kvrocks")
        self.assertEqual(audit["version"], "v2.16.0")
        self.assertEqual(audit["os_version"], "24.03-lts-sp4")
        self.assertEqual(
            audit["dockerfile_path"],
            "Database/kvrocks/2.16.0/24.03-lts-sp4/Dockerfile",
        )
        self.assertFalse(audit["has_test_script"])
        self.assertIn("转入 AI 审计", audit["reason"])

    def test_audit_limit_caps_the_audit_matrix(self) -> None:
        _make_app(self.repo, "Database", "redis", versions=("2.16.0",))
        result = self._scan(
            _payload("v2.16.0"),
            apps=[
                {"name": "kvrocks", "app": "kvrocks", "domain": "Database"},
                {"name": "Redis", "app": "redis", "domain": "Database"},
            ],
            audit_limit=1,
        )
        self.assertEqual(len(result["audits"]), 1)
        self.assertTrue(
            any("审计数量达到上限" in item["reason"] for item in result["skipped"])
        )

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
            apps=[{"name": "kvrocks", "app": "kvrocks", "domain": "Database"}],
            resolve=fail,
            probe=lambda p: {},
            fetch_evidence=lambda name, version: [],
        )
        self.assertEqual(result["updates"][0]["version"], "2.18.0")
        # 版本号不能冒充上游 tag，否则审计/修复会误判 tag.mismatch
        self.assertEqual(result["updates"][0]["evidence"]["tag"], "")

    def test_forced_tag_is_carried_into_evidence(self) -> None:
        result = upgrade_scan.find_updates(
            repo_dir=self.repo,
            app_filter="kvrocks",
            forced_version="2.18.0",
            forced_tag="v2.18.0",
            apps=[{"name": "kvrocks", "app": "kvrocks", "domain": "Database"}],
            resolve=lambda name: (_ for _ in ()).throw(
                AssertionError("dashboard must not be called")
            ),
            probe=lambda p: {},
            fetch_evidence=lambda name, version: [],
        )
        self.assertEqual(result["updates"][0]["evidence"]["tag"], "v2.18.0")

    def test_unlisted_app_in_repo_can_be_upgraded_with_forced_version(self) -> None:
        _make_app(self.repo, "AI", "open-webui", versions=("0.1.108",))

        def boom(*args):
            raise AssertionError("dashboard must not be called")

        result = upgrade_scan.find_updates(
            repo_dir=self.repo,
            app_filter="open-webui",
            forced_version="0.13.3",
            apps=[{"name": "kvrocks", "app": "kvrocks", "domain": "Database"}],
            resolve=boom,
            probe=boom,
            fetch_evidence=boom,
        )
        self.assertEqual(len(result["updates"]), 1)
        item = result["updates"][0]
        self.assertEqual(item["app"], "open-webui")
        self.assertEqual(item["domain"], "AI")
        self.assertEqual(item["version"], "0.13.3")

    def test_unlisted_app_requires_forced_version(self) -> None:
        _make_app(self.repo, "AI", "open-webui", versions=("0.1.108",))
        with self.assertRaises(SystemExit):
            upgrade_scan.find_updates(
                repo_dir=self.repo,
                app_filter="open-webui",
                apps=[{"name": "kvrocks", "app": "kvrocks", "domain": "Database"}],
                resolve=lambda name: {},
                probe=lambda payload: {},
                fetch_evidence=lambda name, version: [],
            )

    def test_unknown_app_raises(self) -> None:
        with self.assertRaises(SystemExit):
            upgrade_scan.find_updates(repo_dir=self.repo, app_filter="nope")

    def test_limit_stops_after_n_updates(self) -> None:
        _make_app(self.repo, "Database", "redis", versions=("1.0.0",))
        result = self._scan(
            _payload("2.17.0"),
            apps=[
                {"name": "kvrocks", "app": "kvrocks", "domain": "Database"},
                {"name": "Redis", "app": "redis", "domain": "Database"},
            ],
            limit=1,
        )
        self.assertEqual(len(result["updates"]), 1)


class LoadAppsTest(unittest.TestCase):
    def test_parses_yaml_and_defaults_name_to_app(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "apps.yml"
            path.write_text(
                "apps:\n"
                "- name: ClickHouse\n"
                "  app: clickhouse\n"
                "  domain: Database\n"
                "- app: nginx\n"
                "  domain: Cloud\n",
                encoding="utf-8",
            )
            apps = upgrade_scan.load_apps(path)
        self.assertEqual(apps[0], {"name": "ClickHouse", "app": "clickhouse", "domain": "Database"})
        self.assertEqual(apps[1], {"name": "nginx", "app": "nginx", "domain": "Cloud"})

    def test_missing_app_or_domain_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "apps.yml"
            path.write_text("apps:\n- name: broken\n", encoding="utf-8")
            with self.assertRaises(SystemExit):
                upgrade_scan.load_apps(path)


class NormalizeVersionTest(unittest.TestCase):
    def test_v_prefix_and_case_are_ignored(self) -> None:
        self.assertEqual(upgrade_scan._normalize_version("v1.2.3"), "1.2.3")
        self.assertEqual(upgrade_scan._normalize_version("V1.2.3"), "1.2.3")
        self.assertEqual(upgrade_scan._normalize_version(" 1.2.3 "), "1.2.3")
