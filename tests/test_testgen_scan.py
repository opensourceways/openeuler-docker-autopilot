"""Tests for the scenario-four target-app resolver."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.harness import testgen_scan  # noqa: E402


def _make_app(repo: Path, domain: str, app: str, *, versions=("2.0.0",),
              os_versions=("24.03-lts-sp4",), test_script=None) -> None:
    app_dir = repo / domain / app
    for version in versions:
        for os_version in os_versions:
            image_dir = app_dir / version / os_version
            image_dir.mkdir(parents=True, exist_ok=True)
            (image_dir / "Dockerfile").write_text("FROM x\n", encoding="utf-8")
    if test_script:
        target = app_dir / test_script
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("#!/bin/bash\n", encoding="utf-8")


class NormalizeNameTest(unittest.TestCase):
    def test_case_and_separators_fold(self) -> None:
        self.assertEqual(testgen_scan.normalize_name("ClickHouse"), "clickhouse")
        self.assertEqual(testgen_scan.normalize_name("spring cloud"), "spring-cloud")
        self.assertEqual(testgen_scan.normalize_name("Spring_Cloud"), "spring-cloud")
        self.assertEqual(testgen_scan.normalize_name("  libavif "), "libavif")


class HasAnyTestScriptTest(unittest.TestCase):
    def test_shared_tests_location(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp)
            self.assertFalse(testgen_scan.has_any_test_script(app_dir))
            (app_dir / "tests").mkdir()
            (app_dir / "tests" / "test.sh").write_text("#!/bin/bash\n", encoding="utf-8")
            self.assertTrue(testgen_scan.has_any_test_script(app_dir))

    def test_legacy_app_level_location(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp)
            (app_dir / "test.sh").write_text("#!/bin/bash\n", encoding="utf-8")
            self.assertTrue(testgen_scan.has_any_test_script(app_dir))

    def test_version_colocated_location(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp)
            (app_dir / "1.0" / "oe2403").mkdir(parents=True)
            (app_dir / "1.0" / "oe2403" / "test.sh").write_text(
                "#!/bin/bash\n", encoding="utf-8"
            )
            self.assertTrue(testgen_scan.has_any_test_script(app_dir))


class LatestDockerfileTest(unittest.TestCase):
    def test_picks_highest_version_then_os(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp)
            for version, os_version in (
                ("1.9.0", "24.03-lts-sp4"),
                ("1.10.0", "22.03-lts-sp3"),
                ("1.10.0", "24.03-lts-sp4"),
            ):
                image = app_dir / version / os_version
                image.mkdir(parents=True)
                (image / "Dockerfile").write_text("FROM x\n", encoding="utf-8")
            best = testgen_scan.latest_dockerfile(app_dir)
            self.assertIsNotNone(best)
            self.assertEqual(best.parts[-3], "1.10.0")
            self.assertEqual(best.parts[-2], "24.03-lts-sp4")

    def test_no_dockerfile_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(testgen_scan.latest_dockerfile(Path(tmp)))

    def test_version_dockerfile_prefers_the_requested_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp)
            for version in ("df38c01", "master"):
                image = app_dir / version / "24.03-lts-sp4"
                image.mkdir(parents=True)
                (image / "Dockerfile").write_text("FROM x\n", encoding="utf-8")
            picked = testgen_scan.version_dockerfile(app_dir, "df38c01")
            self.assertIsNotNone(picked)
            self.assertEqual(picked.parts[-3], "df38c01")

    def test_version_dockerfile_missing_version_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(
                testgen_scan.version_dockerfile(Path(tmp), "1.0.0")
            )


class ResolveItemTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name) / "target-repo"
        self.repo.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_resolves_latest_image_of_the_named_app(self) -> None:
        _make_app(self.repo, "Database", "kvrocks",
                  versions=("2.15.0", "2.16.0"))
        item = testgen_scan.resolve_item(repo_dir=self.repo, app="Kvrocks")
        self.assertEqual(
            item,
            {
                "app": "kvrocks",
                "domain": "Database",
                "version": "2.16.0",
                "os_version": "24.03-lts-sp4",
                "source_url": "",
            },
        )

    def test_source_url_is_echoed(self) -> None:
        _make_app(self.repo, "Database", "kvrocks")
        item = testgen_scan.resolve_item(
            repo_dir=self.repo, app="kvrocks",
            source_url=" https://github.com/apache/kvrocks ",
        )
        self.assertEqual(item["source_url"], "https://github.com/apache/kvrocks")

    def test_domain_disambiguates_same_name(self) -> None:
        _make_app(self.repo, "Database", "salmon")
        _make_app(self.repo, "Others", "Salmon")
        with self.assertRaises(SystemExit) as ambiguous:
            testgen_scan.resolve_item(repo_dir=self.repo, app="salmon")
        self.assertIn("--domain", str(ambiguous.exception))

        item = testgen_scan.resolve_item(
            repo_dir=self.repo, app="salmon", domain="Others"
        )
        self.assertEqual(item["domain"], "Others")

    def test_missing_app_raises(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            testgen_scan.resolve_item(repo_dir=self.repo, app="nope")
        self.assertIn("找不到应用目录", str(ctx.exception))

    def test_existing_test_script_blocks_regeneration(self) -> None:
        _make_app(self.repo, "Database", "kvrocks", test_script="tests/test.sh")
        with self.assertRaises(SystemExit) as ctx:
            testgen_scan.resolve_item(repo_dir=self.repo, app="kvrocks")
        self.assertIn("已有功能测试脚本", str(ctx.exception))

    def test_app_without_dockerfile_raises(self) -> None:
        (self.repo / "Database" / "empty-app").mkdir(parents=True)
        with self.assertRaises(SystemExit) as ctx:
            testgen_scan.resolve_item(repo_dir=self.repo, app="empty-app")
        self.assertIn("没有", str(ctx.exception))


class MainTest(unittest.TestCase):
    def test_github_output_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "gh_output"
            repo = Path(tmp) / "target-repo"
            repo.mkdir()
            _make_app(repo, "Database", "kvrocks")
            with (
                mock.patch.dict(
                    "os.environ",
                    {"GITHUB_OUTPUT": str(out), "SOURCE_REPO_DIR": str(repo)},
                    clear=False,
                ),
                mock.patch.object(
                    sys, "argv",
                    ["testgen_scan", "--app", "kvrocks", "--format", "github-output"],
                ),
            ):
                self.assertEqual(testgen_scan.main(), 0)
            content = out.read_text(encoding="utf-8")
            self.assertIn("item=", content)
            payload = json.loads(content.split("item=", 1)[1].strip())
            self.assertEqual(payload["app"], "kvrocks")

    def test_missing_repo_dir_exits(self) -> None:
        with (
            mock.patch.dict("os.environ", {"SOURCE_REPO_DIR": ""}, clear=False),
            mock.patch.object(
                sys, "argv", ["testgen_scan", "--repo", "no-such-dir", "--app", "x"]
            ),
        ):
            with self.assertRaises(SystemExit):
                testgen_scan.main()


if __name__ == "__main__":
    unittest.main()
