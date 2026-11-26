"""conda-ecopkgs 升级 PR 的确定性文件改写单测。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.harness import conda_ecopkgs_pr  # noqa: E402


SAMPLE = """24.03-LTS-SP2:
    1.9.4:
        - aarch64
        - x86_64
"""


def _index(*entries: tuple[str, str]) -> dict:
    return {
        "files": [
            {"version": version, "attrs": {"subdir": subdir}, "basename": f"{subdir}/x"}
            for version, subdir in entries
        ]
    }


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

    def test_numeric_looking_version_is_quoted(self) -> None:
        updated, changed = conda_ecopkgs_pr.upsert_version(
            SAMPLE,
            os_version="24.03-LTS-SP4",
            version="4.4",
            arches=["aarch64", "x86_64"],
        )
        self.assertTrue(changed)
        self.assertIn('"4.4":', updated)
        parsed = yaml.safe_load(updated)
        self.assertIn("4.4", parsed["24.03-LTS-SP4"])
        self.assertEqual(
            parsed["24.03-LTS-SP4"]["4.4"], ["aarch64", "x86_64"]
        )

    def test_quoted_existing_version_is_untouched(self) -> None:
        text = '24.03-LTS-SP4:\n    "4.4":\n        - aarch64\n'
        updated, changed = conda_ecopkgs_pr.upsert_version(
            text,
            os_version="24.03-LTS-SP4",
            version="4.4",
            arches=["aarch64"],
        )
        self.assertFalse(changed)
        self.assertEqual(updated, text)

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


class MissingArtifactsTest(unittest.TestCase):
    def test_version_missing_on_all_arches(self) -> None:
        index = _index(("1.5.4", "linux-64"), ("1.5.4", "linux-aarch64"))
        self.assertEqual(
            conda_ecopkgs_pr.missing_artifacts(
                index, version="1.5.5", arches=["x86_64", "aarch64"]
            ),
            ["x86_64", "aarch64"],
        )

    def test_version_present_on_all_arches(self) -> None:
        index = _index(("1.5.4", "linux-64"), ("1.5.4", "linux-aarch64"))
        self.assertEqual(
            conda_ecopkgs_pr.missing_artifacts(
                index, version="1.5.4", arches=["x86_64", "aarch64"]
            ),
            [],
        )

    def test_partial_arch_is_reported(self) -> None:
        index = _index(("65936", "linux-64"))
        self.assertEqual(
            conda_ecopkgs_pr.missing_artifacts(
                index, version="65936", arches=["x86_64", "aarch64"]
            ),
            ["aarch64"],
        )

    def test_unknown_arch_is_treated_as_missing(self) -> None:
        index = _index(("1.5.4", "linux-64"))
        self.assertEqual(
            conda_ecopkgs_pr.missing_artifacts(
                index, version="1.5.4", arches=["x86_64", "ppc64le"]
            ),
            ["ppc64le"],
        )

    def test_subdir_falls_back_to_basename(self) -> None:
        index = {
            "files": [{"version": "1.5.4", "basename": "linux-aarch64/apptainer.conda"}]
        }
        self.assertEqual(
            conda_ecopkgs_pr.missing_artifacts(
                index, version="1.5.4", arches=["aarch64"]
            ),
            [],
        )


class CasesYamlTest(unittest.TestCase):
    def test_generic_cases_are_valid_yaml(self) -> None:
        parsed = yaml.safe_load(conda_ecopkgs_pr.cases_yaml("unknown-pkg"))
        names = [case["name"] for case in parsed["cases"]]
        self.assertEqual(names, ["installed-version", "package-integrity"])
        for case in parsed["cases"]:
            self.assertTrue(case["cmd"])
            self.assertEqual(case["category"], "functional")
            self.assertIsInstance(case["timeout"], int)

    def test_known_package_gets_curated_case(self) -> None:
        parsed = yaml.safe_load(conda_ecopkgs_pr.cases_yaml("bioconductor-batchelor"))
        names = [case["name"] for case in parsed["cases"]]
        self.assertIn("r-library-load", names)

    def test_generated_cmd_uses_declared_package_name(self) -> None:
        parsed = yaml.safe_load(conda_ecopkgs_pr.cases_yaml("expat"))
        self.assertIn("conda-meta/expat-", parsed["cases"][0]["cmd"])


class WritePrTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        package_dir = self.repo / "packages" / "demo"
        package_dir.mkdir(parents=True)
        (package_dir / "package.yml").write_text(
            "name: demo\nchannel: conda-forge\n", encoding="utf-8"
        )
        (package_dir / "supported-versions.yml").write_text("", encoding="utf-8")
        self.cases_path = package_dir / "tests" / "cases.yml"
        self.item = {
            "package": "demo",
            "version": "1.5.4",
            "os_version": "24.03-LTS-SP4",
            "arches": ["x86_64", "aarch64"],
        }

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, *, verify_result: list[str] | None = None) -> str:
        with (
            mock.patch.object(conda_ecopkgs_pr, "_git") as git,
            mock.patch.object(
                conda_ecopkgs_pr, "verify_upstream", return_value=verify_result or []
            ) as verify,
            mock.patch.object(
                conda_ecopkgs_pr, "find_any_pr_by_head_branch", return_value=None
            ),
            mock.patch.object(
                conda_ecopkgs_pr,
                "create_pull_request",
                return_value={"web_url": "https://example/pr/1"},
            ) as create,
        ):
            url = conda_ecopkgs_pr._write_pr(
                repo_dir=self.repo,
                item=self.item,
                target_repo="openeuler/conda-ecopkgs",
                base_branch="master",
                fork_repo="fork/conda-ecopkgs",
                push_url="https://token@gitcode.com/fork/conda-ecopkgs.git",
                token="token",
                dry_run=False,
            )
        self.git = git
        self.verify = verify
        self.create = create
        return url

    def test_verifies_upstream_and_adds_missing_cases(self) -> None:
        url = self._write()
        self.assertEqual(url, "https://example/pr/1")
        self.verify.assert_called_once_with(
            channel="conda-forge",
            package="demo",
            version="1.5.4",
            arches=["x86_64", "aarch64"],
        )
        parsed = yaml.safe_load(self.cases_path.read_text(encoding="utf-8"))
        self.assertEqual(parsed["cases"][0]["name"], "installed-version")
        body = self.create.call_args.args[4]
        self.assertIn("`conda-forge` 渠道确认", body)
        self.assertIn("tests/cases.yml", body)

    def test_skips_package_when_upstream_artifact_missing(self) -> None:
        url = self._write(verify_result=["aarch64"])
        self.assertEqual(url, "")
        self.assertFalse(self.cases_path.exists())
        self.git.assert_not_called()
        self.create.assert_not_called()

    def test_adds_tests_only_when_version_already_registered(self) -> None:
        yml_path = self.repo / "packages" / "demo" / "supported-versions.yml"
        yml_path.write_text(
            "24.03-LTS-SP4:\n    1.5.4:\n        - x86_64\n        - aarch64\n",
            encoding="utf-8",
        )
        url = self._write()
        self.assertEqual(url, "https://example/pr/1")
        self.verify.assert_not_called()
        self.assertTrue(self.cases_path.is_file())
        title = self.create.call_args.args[3]
        self.assertEqual(title, "test(demo): 补充功能测试用例")


if __name__ == "__main__":
    unittest.main()
