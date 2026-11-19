"""conda-ecopkgs 升级 PR 的确定性文件改写单测。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.harness import conda_ecopkgs_pr  # noqa: E402


SAMPLE = """24.03-LTS-SP2:
    1.9.4:
        - aarch64
        - x86_64
"""


class UpsertVersionTest(unittest.TestCase):
    def test_appends_missing_os_section(self) -> None:
        updated, changed = conda_ecopkgs_pr.upsert_version(
            SAMPLE,
            os_version="24.03-LTS-SP4",
            version="1.10.0",
            arches=["aarch64", "x86_64"],
        )
        self.assertTrue(changed)
        parsed = yaml.safe_load(updated)
        self.assertEqual(
            parsed["24.03-LTS-SP4"]["1.10.0"], ["aarch64", "x86_64"]
        )
        # 旧段保持原样
        self.assertEqual(parsed["24.03-LTS-SP2"]["1.9.4"], ["aarch64", "x86_64"])

    def test_inserts_before_the_next_section(self) -> None:
        text = (
            "24.03-LTS-SP4:\n"
            "    5.5.3:\n"
            "        - aarch64\n"
            "        - x86_64\n"
            "24.03-LTS-SP1:\n"
            "    5.5.0:\n"
            "        - x86_64\n"
        )
        updated, changed = conda_ecopkgs_pr.upsert_version(
            text,
            os_version="24.03-LTS-SP4",
            version="5.5.4",
            arches=["aarch64", "x86_64"],
        )
        self.assertTrue(changed)
        parsed = yaml.safe_load(updated)
        self.assertEqual(
            list(parsed["24.03-LTS-SP4"]), ["5.5.3", "5.5.4"]
        )
        self.assertEqual(parsed["24.03-LTS-SP1"]["5.5.0"], ["x86_64"])

    def test_existing_version_is_untouched(self) -> None:
        updated, changed = conda_ecopkgs_pr.upsert_version(
            SAMPLE,
            os_version="24.03-LTS-SP2",
            version="1.9.4",
            arches=["aarch64", "x86_64"],
        )
        self.assertFalse(changed)
        self.assertEqual(updated, SAMPLE)

    def test_branch_name_slugifies_the_os(self) -> None:
        branch = conda_ecopkgs_pr.branch_name(
            {
                "package": "benchmark",
                "version": "1.10.0",
                "os_version": "24.03-LTS-SP4",
            }
        )
        self.assertEqual(branch, "auto/upgrade/benchmark-1.10.0-2403ltssp4")


if __name__ == "__main__":
    unittest.main()
