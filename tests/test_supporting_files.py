"""辅助脚本审计单测（不联网、不调用 Agent）。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.lib import supporting_files  # noqa: E402

_DOCKERFILE = (
    "FROM openeuler/openeuler:24.03-lts-sp4\n"
    "COPY build.sh /opt/\n"
    "COPY patch.diff /opt/\n"
    "RUN ./build.sh\n"
)


def _version_dir(root: Path) -> Path:
    version = root / "4.4" / "24.03-lts-sp4"
    version.mkdir(parents=True)
    (version / "Dockerfile").write_text(_DOCKERFILE, encoding="utf-8")
    (version / "build.sh").write_text(
        "#!/bin/bash\ncmake -S . -B build -DWITH_GUI=ON\n", encoding="utf-8"
    )
    (version / "patch.diff").write_text("--- a\n+++ b\n", encoding="utf-8")
    (version / "unrelated.txt").write_text("not referenced\n", encoding="utf-8")
    return version


class CollectTest(unittest.TestCase):
    def test_only_files_referenced_by_the_dockerfile_are_collected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            version = _version_dir(Path(tmp))
            files = supporting_files.collect(version, _DOCKERFILE)

        self.assertEqual([item.path for item in files], ["build.sh", "patch.diff"])

    def test_copy_of_the_whole_directory_includes_everything(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            version = _version_dir(Path(tmp))
            files = supporting_files.collect(version, "FROM x\nCOPY . /opt\n")

        self.assertIn("unrelated.txt", [item.path for item in files])


class ValidateTest(unittest.TestCase):
    def test_missing_conclusion_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            files = supporting_files.collect(_version_dir(Path(tmp)), _DOCKERFILE)

        findings, updates = supporting_files.validate(
            files,
            {
                "supporting_files": [
                    {"path": "build.sh", "verdict": "unchanged", "reason": "ok"}
                ]
            },
        )

        self.assertEqual(updates, {})
        self.assertTrue(any("patch.diff" in finding for finding in findings))

    def test_updated_file_must_carry_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            files = supporting_files.collect(_version_dir(Path(tmp)), _DOCKERFILE)

        findings, _ = supporting_files.validate(
            files,
            {
                "supporting_files": [
                    {"path": "build.sh", "verdict": "updated", "content": ""},
                    {"path": "patch.diff", "verdict": "unchanged", "reason": "ok"},
                ]
            },
        )

        self.assertTrue(any("完整 content" in finding for finding in findings))

    def test_updated_script_is_returned_for_write_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            files = supporting_files.collect(_version_dir(Path(tmp)), _DOCKERFILE)
            new_content = (
                "#!/bin/bash\ncmake -S . -B build -DWITH_GUI=ON -DBUILD_TESTING=OFF\n"
            )
            findings, updates = supporting_files.validate(
                files,
                {
                    "supporting_files": [
                        {
                            "path": "build.sh",
                            "verdict": "updated",
                            "content": new_content,
                            "reason": "tests need GEOS 3.12",
                        },
                        {"path": "patch.diff", "verdict": "unchanged", "reason": "ok"},
                    ]
                },
            )

        self.assertEqual(findings, [])
        self.assertEqual(updates, {"build.sh": new_content})

    def test_paths_outside_the_collected_list_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            files = supporting_files.collect(_version_dir(Path(tmp)), _DOCKERFILE)

        findings, updates = supporting_files.validate(
            files,
            {
                "supporting_files": [
                    {"path": "build.sh", "verdict": "unchanged", "reason": "ok"},
                    {"path": "patch.diff", "verdict": "unchanged", "reason": "ok"},
                    {"path": "../escape.sh", "verdict": "unchanged", "reason": "no"},
                ]
            },
        )

        self.assertEqual(updates, {})
        self.assertTrue(any("清单外" in finding for finding in findings))


class DeterministicFindingsTest(unittest.TestCase):
    def test_stale_version_literal_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            version = _version_dir(Path(tmp))
            (version / "build.sh").write_text(
                "#!/bin/bash\nwget https://example.com/demo-4.2.3.tar.gz\n",
                encoding="utf-8",
            )
            files = supporting_files.collect(version, _DOCKERFILE)

        findings = supporting_files.deterministic_findings(
            files, old_version="4.2.3", new_version="4.4"
        )

        self.assertTrue(any("4.2.3" in finding for finding in findings))

    def test_broken_bash_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            version = _version_dir(Path(tmp))
            (version / "build.sh").write_text("if [ 1; then\n", encoding="utf-8")
            files = supporting_files.collect(version, _DOCKERFILE)

        findings = supporting_files.deterministic_findings(files)

        self.assertTrue(findings)


if __name__ == "__main__":
    unittest.main()
