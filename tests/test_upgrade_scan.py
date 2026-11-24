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

    def test_comma_separated_filter_selects_multiple_apps(self) -> None:
        _make_app(self.repo, "Database", "redis", versions=("2.16.0",))
        apps = [
            _entry("2.17.0"),
            _entry("2.17.0", name="redis", app="redis"),
            _entry("2.17.0", name="other", app="other"),
        ]
        result = self._scan(app_filter="kvrocks, redis", apps=apps)

        self.assertEqual(
            sorted(item["app"] for item in result["updates"]),
            ["kvrocks", "redis"],
        )

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

    def test_audit_item_carries_the_app_build_budget(self) -> None:
        from unittest import mock

        from scripts.lib import app_notes

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "kvrocks.md").write_text(
                "---\napp: kvrocks\nbuild_timeout_minutes: 300\n"
                "generate_timeout_minutes: 120\n---\n# kvrocks\n",
                encoding="utf-8",
            )
            with mock.patch.object(app_notes, "NOTES_DIR", Path(tmp)):
                result = self._scan("v2.16.0")

        audit = result["audits"][0]
        self.assertEqual(audit["build_timeout_minutes"], 300)
        self.assertEqual(audit["prepare_timeout_minutes"], 360)

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

    def test_build_notes_are_carried_into_the_update_item(self) -> None:
        result = self._scan(
            "2.17.0", apps=[_entry("2.17.0", build_notes="build from source")]
        )
        self.assertEqual(
            result["updates"][0]["build_notes"], "build from source"
        )
        # 没填时不写空字段，避免污染 prepare 的任务契约
        self.assertNotIn("build_notes", self._scan()["updates"][0])

    def test_app_notes_timeouts_are_carried_into_the_update_item(self) -> None:
        from unittest import mock

        from scripts.lib import app_notes

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "kvrocks.md").write_text(
                "---\napp: kvrocks\nbuild_timeout_minutes: 300\n"
                "generate_timeout_minutes: 120\n---\n# kvrocks\n",
                encoding="utf-8",
            )
            with mock.patch.object(app_notes, "NOTES_DIR", Path(tmp)):
                result = self._scan()

        item = result["updates"][0]
        self.assertEqual(item["build_timeout_minutes"], 300)
        # prepare = build + 60（或 generate + 60 的较大值）
        self.assertEqual(item["prepare_timeout_minutes"], 360)

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

    def test_forced_version_without_source_url_is_skipped(self) -> None:
        result = upgrade_scan.find_updates(
            repo_dir=self.repo,
            app_filter="kvrocks",
            forced_version="2.18.0",
            apps=[{"name": "kvrocks", "app": "kvrocks", "domain": "Database"}],
        )
        self.assertEqual(result["updates"], [])
        self.assertIn("source_url", result["skipped"][0]["reason"])

    def test_source_url_falls_back_to_doc_image_info(self) -> None:
        doc = self.repo / "Database" / "kvrocks" / "doc"
        doc.mkdir()
        (doc / "image-info.yml").write_text(
            "homepage: https://github.com/apache/kvrocks\n",
            encoding="utf-8",
        )

        result = self._scan(apps=[_entry("2.17.0", source_url="")])

        self.assertEqual(
            result["updates"][0]["source_url"],
            "https://github.com/apache/kvrocks",
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


class CondaScanTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.repo = root / "target-repo"
        self.repo.mkdir()
        _make_app(self.repo, "AI", "benchmark", versions=("1.9.2",))
        self.conda = root / "conda-repo"
        package = self.conda / "packages" / "benchmark"
        package.mkdir(parents=True)
        (package / "supported-versions.yml").write_text(
            "24.03-LTS:\n"
            "    1.9.2:\n"
            "        - x86_64\n"
            "        - aarch64\n"
            "24.03-LTS-SP4:\n"
            "    1.10.0:\n"
            "        - noarch\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    @staticmethod
    def _entry(**overrides) -> dict:
        entry = {
            "name": "benchmark",
            "docker": {"app": "benchmark", "domain": "AI"},
            "conda": {"package": "benchmark"},
        }
        entry.update(overrides)
        return entry

    def test_both_targets_produce_a_docker_update_and_a_conda_update(self) -> None:
        result = upgrade_scan.find_updates(
            repo_dir=self.repo,
            forced_version="1.11.0",
            source_url="https://github.com/google/benchmark",
            apps=[self._entry()],
            conda_repo=self.conda,
        )

        self.assertEqual([item["app"] for item in result["updates"]], ["benchmark"])
        self.assertEqual(
            result["conda_updates"],
            [
                {
                    "name": "benchmark",
                    "package": "benchmark",
                    "version": "1.11.0",
                    "os_version": "24.03-LTS-SP4",
                    "arches": ["noarch"],
                }
            ],
        )

    def test_registered_conda_version_is_skipped(self) -> None:
        result = upgrade_scan.find_updates(
            repo_dir=self.repo,
            forced_version="1.10.0",
            forced_os="24.03-lts-sp4",
            source_url="https://github.com/google/benchmark",
            apps=[self._entry()],
            conda_repo=self.conda,
        )

        self.assertEqual(result["conda_updates"], [])
        conda_skips = [
            item for item in result["skipped"] if item.get("target") == "conda"
        ]
        self.assertEqual(len(conda_skips), 1)
        self.assertIn("已登记", conda_skips[0]["reason"])

    def test_forced_os_matches_existing_section_case_insensitively(self) -> None:
        result = upgrade_scan.find_updates(
            repo_dir=self.repo,
            forced_version="1.11.0",
            forced_os="24.03-lts",
            source_url="https://github.com/google/benchmark",
            apps=[self._entry()],
            conda_repo=self.conda,
        )

        self.assertEqual(
            result["conda_updates"][0]["os_version"], "24.03-LTS"
        )
        self.assertEqual(
            result["conda_updates"][0]["arches"], ["x86_64", "aarch64"]
        )

    def test_new_os_section_is_canonicalized(self) -> None:
        result = upgrade_scan.find_updates(
            repo_dir=self.repo,
            forced_version="1.11.0",
            forced_os="24.03-lts-sp5",
            source_url="https://github.com/google/benchmark",
            apps=[self._entry()],
            conda_repo=self.conda,
        )

        self.assertEqual(
            result["conda_updates"][0]["os_version"], "24.03-LTS-SP5"
        )

    def test_conda_only_app_is_scanned_without_docker(self) -> None:
        result = upgrade_scan.find_updates(
            repo_dir=self.repo,
            forced_version="1.11.0",
            apps=[{"name": "benchmark", "conda": {"package": "benchmark"}}],
            conda_repo=self.conda,
        )

        self.assertEqual(result["updates"], [])
        self.assertEqual(len(result["conda_updates"]), 1)

    def test_missing_conda_version_is_skipped(self) -> None:
        result = upgrade_scan.find_updates(
            repo_dir=self.repo,
            apps=[{"name": "benchmark", "conda": {"package": "benchmark"}}],
            conda_repo=self.conda,
        )

        self.assertEqual(result["conda_updates"], [])
        self.assertIn("未提供 version", result["skipped"][0]["reason"])


    def test_single_app_filter_fills_a_missing_conda_target(self) -> None:
        result = upgrade_scan.find_updates(
            repo_dir=self.repo,
            app_filter="benchmark",
            forced_version="1.11.0",
            source_url="https://github.com/google/benchmark",
            apps=[{"name": "benchmark", "docker": {"app": "benchmark", "domain": "AI"}}],
            conda_repo=self.conda,
        )

        self.assertEqual(len(result["updates"]), 1)
        self.assertEqual(len(result["conda_updates"]), 1)

    def test_single_app_filter_fills_a_missing_docker_target(self) -> None:
        result = upgrade_scan.find_updates(
            repo_dir=self.repo,
            app_filter="benchmark",
            forced_version="1.11.0",
            source_url="https://github.com/google/benchmark",
            apps=[{"name": "benchmark", "conda": {"package": "benchmark"}}],
            conda_repo=self.conda,
        )

        self.assertEqual(len(result["updates"]), 1)
        self.assertEqual(len(result["conda_updates"]), 1)


class NewImageTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        self.apps = [
            {
                "name": "grpc-java",
                "create": {"app": "grpc-java", "domain": "Others"},
                "source_url": "https://github.com/grpc/grpc-java",
            }
        ]

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_create_target_becomes_a_new_image_item(self) -> None:
        result = upgrade_scan.find_updates(
            repo_dir=self.repo,
            app_filter="grpc-java",
            forced_version="1.85.4",
            forced_os="24.03-lts-sp4",
            apps=self.apps,
        )

        self.assertEqual(result["updates"], [])
        self.assertEqual(
            result["new_images"],
            [
                {
                    "name": "grpc-java",
                    "app": "grpc-java",
                    "domain": "Others",
                    "version": "1.85.4",
                    "os_version": "24.03-lts-sp4",
                    "source_url": "https://github.com/grpc/grpc-java",
                }
            ],
        )

    def test_create_target_needs_an_os_version(self) -> None:
        result = upgrade_scan.find_updates(
            repo_dir=self.repo,
            app_filter="grpc-java",
            forced_version="1.85.4",
            apps=self.apps,
        )

        self.assertEqual(result["new_images"], [])
        self.assertIn("--os-version", result["skipped"][0]["reason"])

    def test_load_apps_accepts_a_create_only_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "apps.yml"
            path.write_text(
                "apps:\n"
                "- name: grpc-java\n"
                "  create:\n"
                "    app: grpc-java\n"
                "    domain: Others\n"
                "  source_url: https://github.com/grpc/grpc-java\n",
                encoding="utf-8",
            )
            apps = upgrade_scan.load_apps(path)

        self.assertEqual(
            apps[0],
            {
                "name": "grpc-java",
                "create": {"app": "grpc-java", "domain": "Others"},
                "source_url": "https://github.com/grpc/grpc-java",
            },
        )


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
        self.assertEqual(
            apps[0],
            {
                "name": "ClickHouse",
                "docker": {"app": "clickhouse", "domain": "Database"},
            },
        )
        self.assertEqual(
            apps[1],
            {"name": "nginx", "docker": {"app": "nginx", "domain": "Cloud"}},
        )

    def test_new_schema_records_both_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "apps.yml"
            path.write_text(
                "apps:\n"
                "- name: benchmark\n"
                "  docker:\n"
                "    app: benchmark\n"
                "    domain: AI\n"
                "  conda:\n"
                "    package: benchmark\n",
                encoding="utf-8",
            )
            apps = upgrade_scan.load_apps(path)
        self.assertEqual(
            apps[0],
            {
                "name": "benchmark",
                "docker": {"app": "benchmark", "domain": "AI"},
                "conda": {"package": "benchmark"},
            },
        )

    def test_conda_only_entry_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "apps.yml"
            path.write_text(
                "apps:\n- name: abyss\n  conda:\n    package: abyss\n",
                encoding="utf-8",
            )
            apps = upgrade_scan.load_apps(path)
        self.assertEqual(
            apps[0], {"name": "abyss", "conda": {"package": "abyss"}}
        )

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
                "  allow_downgrade: true\n"
                "  build_notes: build the kernel module\n",
                encoding="utf-8",
            )
            apps = upgrade_scan.load_apps(path)
        self.assertEqual(
            apps[0],
            {
                "name": "Ceph",
                "docker": {"app": "ceph", "domain": "Storage"},
                "version": "22.0.0",
                "tag": "v22.0.0",
                "source_url": "https://github.com/ceph/ceph",
                "allow_downgrade": True,
                "build_notes": "build the kernel module",
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
