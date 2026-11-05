"""Tests for the scenario-four scan stage."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.harness import testgen_scan  # noqa: E402
from scripts.lib.testgen_dashboard import DashboardSoftware  # noqa: E402


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


def _software(name: str, repo_url: str = "https://github.com/x/y") -> DashboardSoftware:
    return DashboardSoftware(
        name=name, repo_url=repo_url, latest_version="1.0", is_active=True
    )


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "target-repo"
    repo.mkdir()
    return repo


class NormalizeNameTest(unittest.TestCase):
    def test_case_and_separators_fold(self) -> None:
        self.assertEqual(testgen_scan.normalize_name("ClickHouse"), "clickhouse")
        self.assertEqual(testgen_scan.normalize_name("spring cloud"), "spring-cloud")
        self.assertEqual(testgen_scan.normalize_name("Spring_Cloud"), "spring-cloud")
        self.assertEqual(testgen_scan.normalize_name("trf"), "trf")
        self.assertEqual(testgen_scan.normalize_name("  libavif "), "libavif")


class HasAnyTestScriptTest(unittest.TestCase):
    def test_shared_tests_location(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp)
            self.assertFalse(testgen_scan.has_any_test_script(app_dir))
            (app_dir / "tests").mkdir()
            (app_dir / "tests" / "test.sh").write_text("#!/bin/bash\n", encoding="utf-8")
            self.assertTrue(testgen_scan.has_any_test_script(app_dir))

    def test_legacy_app_level_location(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp)
            (app_dir / "test.sh").write_text("#!/bin/bash\n", encoding="utf-8")
            self.assertTrue(testgen_scan.has_any_test_script(app_dir))

    def test_version_colocated_location(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp)
            (app_dir / "1.0" / "oe2403").mkdir(parents=True)
            (app_dir / "1.0" / "oe2403" / "test.sh").write_text(
                "#!/bin/bash\n", encoding="utf-8"
            )
            self.assertTrue(testgen_scan.has_any_test_script(app_dir))


class LatestDockerfileTest(unittest.TestCase):
    def test_picks_highest_version_then_os(self) -> None:
        import tempfile

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
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(testgen_scan.latest_dockerfile(Path(tmp)))


class FindCandidatesTest(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.repo = _repo(Path(self._tmp.name))
        # Default state patches; individual tests override as needed.
        for name, value in (("is_exhausted", False), ("is_done", False)):
            patcher = mock.patch.object(
                testgen_scan, name, return_value=value
            )
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _scan(self, software, **overrides):
        defaults = dict(
            repo_dir=self.repo,
            limit=10,
            app_filter=None,
            token="",
            target_repo="openeuler/openeuler-docker-images",
        )
        defaults.update(overrides)
        with mock.patch.object(
            testgen_scan, "fetch_dashboard_software", return_value=software
        ):
            return testgen_scan.find_candidates(**defaults)

    def test_missing_test_script_becomes_candidate(self) -> None:
        _make_app(self.repo, "Database", "kvrocks")
        result = self._scan([_software("Kvrocks")])
        self.assertEqual(
            result["candidates"],
            [
                {
                    "app": "kvrocks",
                    "domain": "Database",
                    "version": "2.0.0",
                    "os_version": "24.03-lts-sp4",
                    "source_url": "https://github.com/x/y",
                    "dashboard_name": "Kvrocks",
                }
            ],
        )
        self.assertEqual(result["skipped"], [])

    def test_existing_shared_test_script_is_skipped(self) -> None:
        _make_app(self.repo, "Database", "kvrocks", test_script="tests/test.sh")
        result = self._scan([_software("Kvrocks")])
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["skipped"][0]["reason"], "test.sh already present")

    def test_no_matching_directory_is_reported(self) -> None:
        result = self._scan([_software("Spring Cloud")])
        self.assertEqual(result["candidates"], [])
        self.assertEqual(
            result["skipped"][0]["reason"], "no target-repo directory matched"
        )

    def test_ambiguous_match_is_skipped(self) -> None:
        _make_app(self.repo, "Database", "salmon")
        _make_app(self.repo, "Others", "Salmon")
        result = self._scan([_software("salmon")])
        self.assertEqual(result["candidates"], [])
        self.assertIn("ambiguous match", result["skipped"][0]["reason"])

    def test_app_without_dockerfile_is_skipped(self) -> None:
        (self.repo / "Database" / "empty-app").mkdir(parents=True)
        result = self._scan([_software("Empty App")])
        self.assertEqual(result["candidates"], [])
        self.assertEqual(
            result["skipped"][0]["reason"], "app directory has no Dockerfile"
        )

    def test_exhausted_and_done_are_skipped(self) -> None:
        _make_app(self.repo, "Database", "kvrocks")
        with mock.patch.object(testgen_scan, "is_exhausted", return_value=True):
            result = self._scan([_software("kvrocks")])
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["skipped"][0]["reason"], "exhausted (needs human review)")

        with (
            mock.patch.object(testgen_scan, "is_exhausted", return_value=False),
            mock.patch.object(testgen_scan, "is_done", return_value=True),
        ):
            result = self._scan([_software("kvrocks")])
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["skipped"][0]["reason"], "already delivered")

    def test_open_pr_is_skipped_when_token_present(self) -> None:
        _make_app(self.repo, "Database", "kvrocks")
        with mock.patch.object(
            testgen_scan, "find_any_pr_by_head_branch", return_value={"number": 7}
        ) as finder:
            result = self._scan([_software("kvrocks")], token="t")
        finder.assert_called_once_with(
            "openeuler/openeuler-docker-images", "auto/test-script/kvrocks", "t",
            open_only=True,
        )
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["skipped"][0]["reason"], "open PR already exists")

    def test_no_token_skips_pr_check(self) -> None:
        _make_app(self.repo, "Database", "kvrocks")
        with mock.patch.object(
            testgen_scan, "find_any_pr_by_head_branch"
        ) as finder:
            self._scan([_software("kvrocks")], token="")
        finder.assert_not_called()

    def test_limit_truncates_in_dashboard_order(self) -> None:
        _make_app(self.repo, "Database", "kvrocks")
        _make_app(self.repo, "Database", "redis")
        result = self._scan(
            [_software("kvrocks"), _software("redis")], limit=1
        )
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(result["candidates"][0]["app"], "kvrocks")

    def test_app_filter_restricts_scan(self) -> None:
        _make_app(self.repo, "Database", "kvrocks")
        _make_app(self.repo, "Database", "redis")
        result = self._scan(
            [_software("kvrocks"), _software("redis")],
            app_filter="redis",
        )
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(result["candidates"][0]["app"], "redis")

    def test_dashboard_unreachable_returns_empty(self) -> None:
        with mock.patch.object(
            testgen_scan, "fetch_dashboard_software", return_value=None
        ):
            result = testgen_scan.find_candidates(
                repo_dir=self.repo, limit=5, token=""
            )
        self.assertEqual(result["candidates"], [])
        self.assertTrue(result["dashboard_unreachable"])


class MainTest(unittest.TestCase):
    def test_github_output_written(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "gh_output"
            repo = _repo(Path(tmp))
            _make_app(repo, "Database", "kvrocks")
            with (
                mock.patch.dict(
                    "os.environ",
                    {"GITHUB_OUTPUT": str(out), "SOURCE_REPO_DIR": str(repo)},
                    clear=False,
                ),
                mock.patch.object(
                    testgen_scan,
                    "fetch_dashboard_software",
                    return_value=[_software("kvrocks")],
                ),
                mock.patch.object(testgen_scan, "is_exhausted", return_value=False),
                mock.patch.object(testgen_scan, "is_done", return_value=False),
                mock.patch.object(sys, "argv", [
                    "testgen_scan", "--format", "github-output",
                ]),
            ):
                self.assertEqual(testgen_scan.main(), 0)
            content = out.read_text(encoding="utf-8")
            self.assertIn("candidates=", content)
            self.assertIn('"app": "kvrocks"', content)

    def test_missing_repo_dir_exits(self) -> None:
        with (
            mock.patch.dict("os.environ", {"SOURCE_REPO_DIR": ""}, clear=False),
            mock.patch.object(
                sys, "argv", ["testgen_scan", "--repo", "no-such-dir"]
            ),
        ):
            with self.assertRaises(SystemExit):
                testgen_scan.main()


if __name__ == "__main__":
    unittest.main()
