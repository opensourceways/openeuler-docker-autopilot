"""场景二升级候选发现单测（不联网、不查询看板）。"""

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


def _entry(version: str = "2.17.0", **overrides) -> dict:
    entry = {
        "name": "kvrocks",
        "app": "kvrocks",
        "domain": "Database",
        "version": version,
        "source_url": "https://github.com/apache/kvrocks",
    }
    entry.update(overrides)
    return entry


class FindUpdatesTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name) / "target-repo"
        self.repo.mkdir()
        _make_app(self.repo, "Database", "kvrocks")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _scan(self, version: str = "2.17.0", **overrides):
        overrides.setdefault("apps", [_entry(version)])
        return upgrade_scan.find_updates(repo_dir=self.repo, **overrides)

    def test_list_version_becomes_an_upgrade_item(self) -> None:
        result = self._scan()
        self.assertEqual(len(result["updates"]), 1)
        item = result["updates"][0]
        self.assertEqual(item["app"], "kvrocks")
        self.assertEqual(item["domain"], "Database")
        self.assertEqual(item["version"], "2.17.0")
        self.assertEqual(item["os_version"], "24.03-lts-sp4")
        self.assertEqual(item["source_url"], "https://github.com/apache/kvrocks")
        self.assertEqual(result["skipped"], [])

    def test_manual_evidence_does_not_claim_dashboard_crawl(self) -> None:
        item = self._scan()["updates"][0]
        self.assertEqual(item["evidence"]["source"], "manual")
        self.assertEqual(item["evidence"]["collector"], [])
        self.assertEqual(item["evidence"]["probe"]["status"], "skipped")

    def test_missing_version_is_skipped(self) -> None:
        apps = [
            {
                "name": "kvrocks",
                "app": "kvrocks",
                "domain": "Database",
                "source_url": "https://github.com/apache/kvrocks",
            }
        ]
        result = self._scan(apps=apps)
        self.assertEqual(result["updates"], [])
        self.assertIn("未提供 version", result["skipped"][0]["reason"])

    def test_missing_source_url_is_skipped(self) -> None:
        apps = [
            {"name": "kvrocks", "app": "kvrocks", "domain": "Database", "version": "2.17.0"}
        ]
        result = self._scan(apps=apps)
        self.assertEqual(result["updates"], [])
        self.assertIn("未提供 source_url", result["skipped"][0]["reason"])

    def test_only_configured_apps_are_scanned(self) -> None:
        _make_app(self.repo, "Database", "unlisted")
        result = self._scan()
        self.assertEqual([item["app"] for item in result["updates"]], ["kvrocks"])

    def test_configured_app_missing_from_repo_is_skipped(self) -> None:
        result = self._scan(apps=[_entry("2.17.0", app="gone", name="gone")])
        self.assertEqual(result["updates"], [])
        self.assertIn("目标仓没有", result["skipped"][0]["reason"])

    def test_filter_matches_the_list_name(self) -> None:
        result = self._scan(
            app_filter="Kvrocks",
            apps=[_entry("2.17.0", name="Kvrocks")],
        )
        self.assertEqual(len(result["updates"]), 1)

    def test_existing_version_becomes_an_audit(self) -> None:
        result = self._scan("v2.16.0")
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
            "v2.16.0",
            apps=[
                _entry("v2.16.0"),
                _entry("v2.16.0", name="Redis", app="redis"),
            ],
            audit_limit=1,
        )
        self.assertEqual(len(result["audits"]), 1)
        self.assertTrue(
            any("审计数量达到上限" in item["reason"] for item in result["skipped"])
        )

    def test_lower_version_than_repo_is_skipped(self) -> None:
        result = self._scan("2.15.0")
        self.assertEqual(result["updates"], [])
        self.assertEqual(result["audits"], [])
        self.assertIn("低于仓库现有版本", result["skipped"][0]["reason"])

    def test_allow_downgrade_overrides_the_guard(self) -> None:
        result = self._scan(
            "2.15.0", apps=[_entry("2.15.0", allow_downgrade=True)]
        )
        self.assertEqual(len(result["updates"]), 1)
        self.assertEqual(result["updates"][0]["version"], "2.15.0")
        self.assertEqual(result["skipped"], [])

    def test_placeholder_version_is_skipped(self) -> None:
        result = self._scan("Undefined")
        self.assertEqual(result["updates"], [])
        self.assertEqual(result["audits"], [])
        self.assertIn("版本号无效", result["skipped"][0]["reason"])

    def test_non_numeric_versions_keep_the_existing_behavior(self) -> None:
        _make_app(self.repo, "Database", "kvrocks-rc", versions=("2.16.0-rc1",))
        result = self._scan(
            "2.17.0-rc1",
            apps=[_entry("2.17.0-rc1", app="kvrocks-rc")],
        )
        self.assertEqual(len(result["updates"]), 1)

    def test_open_pr_is_skipped(self) -> None:
        calls = []

        def pr_exists(repo, branch, token):
            calls.append(branch)
            return {"number": 7}

        result = self._scan(
            pr_exists=pr_exists,
            target_repo="openeuler/openeuler-docker-images",
            token="t",
        )
        self.assertEqual(result["updates"], [])
        self.assertIn("open PR", result["skipped"][0]["reason"])
        self.assertEqual(
            calls, ["auto/version-update/kvrocks/2.17.0-oe2403sp4"]
        )

    def test_forced_version_uses_cli_inputs(self) -> None:
        result = upgrade_scan.find_updates(
            repo_dir=self.repo,
            app_filter="kvrocks",
            forced_version="2.18.0",
            source_url="https://github.com/apache/kvrocks",
            apps=[{"name": "kvrocks", "app": "kvrocks", "domain": "Database"}],
        )
        self.assertEqual(result["updates"][0]["version"], "2.18.0")
        self.assertEqual(
            result["updates"][0]["source_url"], "https://github.com/apache/kvrocks"
        )
        # 版本号不能冒充上游 tag，否则审计/修复会误判 tag.mismatch
        self.assertEqual(result["updates"][0]["evidence"]["tag"], "")

    def test_forced_tag_is_carried_into_evidence(self) -> None:
        result = upgrade_scan.find_updates(
            repo_dir=self.repo,
            app_filter="kvrocks",
            forced_version="2.18.0",
            forced_tag="v2.18.0",
            source_url="https://github.com/apache/kvrocks",
            apps=[{"name": "kvrocks", "app": "kvrocks", "domain": "Database"}],
        )
        self.assertEqual(result["updates"][0]["evidence"]["tag"], "v2.18.0")

    def test_forced_version_requires_source_url(self) -> None:
        with self.assertRaises(SystemExit):
            upgrade_scan.find_updates(
                repo_dir=self.repo,
                app_filter="kvrocks",
                forced_version="2.18.0",
                apps=[{"name": "kvrocks", "app": "kvrocks", "domain": "Database"}],
            )

    def test_unlisted_app_in_repo_can_be_upgraded_with_forced_version(self) -> None:
        _make_app(self.repo, "AI", "open-webui", versions=("0.1.108",))
        result = upgrade_scan.find_updates(
            repo_dir=self.repo,
            app_filter="open-webui",
            forced_version="0.13.3",
            source_url="https://github.com/open-webui/open-webui",
            apps=[{"name": "kvrocks", "app": "kvrocks", "domain": "Database"}],
        )
        self.assertEqual(len(result["updates"]), 1)
        item = result["updates"][0]
        self.assertEqual(item["app"], "open-webui")
        self.assertEqual(item["domain"], "AI")
        self.assertEqual(item["version"], "0.13.3")
        self.assertEqual(
            item["source_url"], "https://github.com/open-webui/open-webui"
        )

    def test_unlisted_app_requires_forced_version(self) -> None:
        _make_app(self.repo, "AI", "open-webui", versions=("0.1.108",))
        with self.assertRaises(SystemExit):
            upgrade_scan.find_updates(
                repo_dir=self.repo,
                app_filter="open-webui",
                apps=[{"name": "kvrocks", "app": "kvrocks", "domain": "Database"}],
            )

    def test_unknown_app_raises(self) -> None:
        with self.assertRaises(SystemExit):
            upgrade_scan.find_updates(repo_dir=self.repo, app_filter="nope")

    def test_limit_stops_after_n_updates(self) -> None:
        _make_app(self.repo, "Database", "redis", versions=("1.0.0",))
        result = self._scan(
            apps=[
                _entry("2.17.0"),
                _entry("2.0.0", name="Redis", app="redis"),
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

    def test_manual_version_fields_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "apps.yml"
            path.write_text(
                "apps:\n"
                "- name: Ceph\n"
                "  app: ceph\n"
                "  domain: Storage\n"
                "  version: '22.0.0'\n"
                "  tag: v22.0.0\n"
                "  source_url: https://github.com/ceph/ceph\n"
                "  allow_downgrade: true\n",
                encoding="utf-8",
            )
            apps = upgrade_scan.load_apps(path)
        self.assertEqual(
            apps[0],
            {
                "name": "Ceph",
                "app": "ceph",
                "domain": "Storage",
                "version": "22.0.0",
                "tag": "v22.0.0",
                "source_url": "https://github.com/ceph/ceph",
                "allow_downgrade": True,
            },
        )

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


if __name__ == "__main__":
    unittest.main()
