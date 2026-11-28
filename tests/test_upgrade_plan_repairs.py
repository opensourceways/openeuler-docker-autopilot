"""自动 repair 矩阵的单测（不联网）。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.harness import upgrade_plan_repairs  # noqa: E402


class SelectFailedAppsTest(unittest.TestCase):
    def test_only_validation_failures_are_repaired(self) -> None:
        jobs = [
            {"name": "Discover upgradable apps", "conclusion": "success"},
            {
                "name": "Upgrade open-webui / Prepare open-webui -> 0.13.3",
                "conclusion": "success",
            },
            {"name": "Upgrade open-webui / Validate x86_64", "conclusion": "success"},
            {"name": "Upgrade open-webui / Validate aarch64", "conclusion": "failure"},
            {"name": "Upgrade kvrocks / Validate x86_64", "conclusion": "failure"},
            # prepare 失败没有分支，不自动 repair
            {
                "name": "Upgrade redis / Prepare redis -> 7.4.0",
                "conclusion": "failure",
            },
            {"name": "Audit and fix ${{ matrix.item.app }}", "conclusion": "failure"},
        ]

        apps = upgrade_plan_repairs.select_failed_apps(jobs)

        self.assertEqual(apps, ["kvrocks", "open-webui"])

    def test_invalid_app_names_are_dropped(self) -> None:
        jobs = [
            {"name": "Upgrade bad app / Validate x86_64", "conclusion": "failure"},
            {"name": "Upgrade ok-app / Validate x86_64", "conclusion": "failure"},
        ]

        apps = upgrade_plan_repairs.select_failed_apps(jobs)

        self.assertEqual(apps, ["ok-app"])

    def test_failed_job_apps_include_non_validation_stages(self) -> None:
        jobs = [
            {"name": "Discover upgradable apps", "conclusion": "failure"},
            {
                "name": "Upgrade redis / Prepare redis -> 7.4.0",
                "conclusion": "failure",
            },
            {"name": "Upgrade kvrocks / Validate x86_64", "conclusion": "failure"},
            {"name": "Upgrade ndpi / Replay aarch64", "conclusion": "cancelled"},
            {"name": "Upgrade ok-app / Validate x86_64", "conclusion": "success"},
        ]

        apps = upgrade_plan_repairs.select_failed_job_apps(jobs)

        self.assertEqual(apps, ["kvrocks", "ndpi", "redis"])

    def test_matrix_carries_repository_instructions(self) -> None:
        matrix = upgrade_plan_repairs.build_matrix(
            ["open-webui"], "优先把预热放到构建期"
        )

        self.assertEqual(
            matrix,
            {
                "include": [
                    {"app": "open-webui", "instructions": "优先把预热放到构建期"}
                ]
            },
        )


class MainTest(unittest.TestCase):
    def test_jobs_file_produces_github_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs_file = root / "jobs.json"
            jobs_file.write_text(
                json.dumps(
                    {
                        "jobs": [
                            {
                                "name": "Upgrade open-webui / Validate aarch64",
                                "conclusion": "failure",
                            },
                            {
                                "name": "Upgrade open-webui / Validate x86_64",
                                "conclusion": "success",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            output_file = root / "output"
            previous = sys.argv
            sys.argv = [
                "upgrade_plan_repairs.py",
                "--jobs",
                str(jobs_file),
                "--instructions",
                "放宽启动等待",
            ]
            try:
                with mock.patch.dict(
                    "os.environ", {"GITHUB_OUTPUT": str(output_file)}
                ):
                    self.assertEqual(upgrade_plan_repairs.main(), 0)
            finally:
                sys.argv = previous
            values = output_file.read_text(encoding="utf-8").splitlines()

        written = dict(line.split("=", 1) for line in values)
        self.assertEqual(written["count"], "1")
        self.assertEqual(written["apps"], '["open-webui"]')
        self.assertEqual(written["unrepairable_count"], "0")
        self.assertEqual(written["unrepairable"], "[]")
        self.assertEqual(
            json.loads(written["matrix"]),
            {
                "include": [
                    {"app": "open-webui", "instructions": "放宽启动等待"}
                ]
            },
        )

    def test_unrepairable_apps_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs_file = root / "jobs.json"
            jobs_file.write_text(
                json.dumps(
                    {
                        "jobs": [
                            {
                                "name": "Upgrade redis / Prepare redis -> 7.4.0",
                                "conclusion": "failure",
                            },
                            {
                                "name": "Upgrade open-webui / Validate x86_64",
                                "conclusion": "failure",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            output_file = root / "output"
            previous = sys.argv
            sys.argv = [
                "upgrade_plan_repairs.py",
                "--jobs",
                str(jobs_file),
            ]
            try:
                with mock.patch.dict(
                    "os.environ", {"GITHUB_OUTPUT": str(output_file)}
                ):
                    self.assertEqual(upgrade_plan_repairs.main(), 0)
            finally:
                sys.argv = previous
            values = output_file.read_text(encoding="utf-8").splitlines()

        written = dict(line.split("=", 1) for line in values)
        self.assertEqual(written["count"], "1")
        self.assertEqual(written["apps"], '["open-webui"]')
        self.assertEqual(written["unrepairable_count"], "1")
        self.assertEqual(written["unrepairable"], '["redis"]')


if __name__ == "__main__":
    unittest.main()
