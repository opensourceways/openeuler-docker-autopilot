"""场景二失败修复单测（不联网、不调用真实 Agent、不执行 git）。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.harness import upgrade_repair  # noqa: E402
from scripts.lib.task_spec import TaskSpec  # noqa: E402


class CollectEvidenceTest(unittest.TestCase):
    def test_failed_report_and_log_tail_are_collected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "x86_64.json").write_text(
                json.dumps({"status": "passed", "architecture": "x86_64"}),
                encoding="utf-8",
            )
            (root / "aarch64.json").write_text(
                json.dumps(
                    {
                        "status": "failed",
                        "architecture": "aarch64",
                        "failed_stage": "test_sh",
                        "failures": [
                            {
                                "check": "runtime_test",
                                "stage": "test_sh",
                                "failure": "FATAL: backend did not become ready",
                                "failure_details": {"readiness_mode": "default_start"},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            diagnostics = root / "diagnostics"
            diagnostics.mkdir()
            (diagnostics / "test-runtime.docker.log").write_text(
                "model download started\nmodel download took 159s\n",
                encoding="utf-8",
            )

            evidence = upgrade_repair.collect_evidence([root, root / "absent"])

        self.assertEqual(len(evidence["failures"]), 1)
        failure = evidence["failures"][0]
        self.assertEqual(failure["architecture"], "aarch64")
        self.assertEqual(failure["stage"], "test_sh")
        self.assertIn("did not become ready", failure["failure"])
        self.assertEqual(len(evidence["reports"]), 2)
        self.assertEqual(evidence["logs"][0]["path"], "test-runtime.docker.log")
        self.assertIn("159s", evidence["logs"][0]["tail"])

    def test_missing_evidence_still_yields_a_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evidence = upgrade_repair.collect_evidence([Path(tmp) / "absent"])

        self.assertEqual(len(evidence["failures"]), 1)
        self.assertEqual(evidence["failures"][0]["stage"], "unknown")
        self.assertEqual(evidence["logs"], [])


class RepairPromptTest(unittest.TestCase):
    def test_prompt_carries_branch_files_failures_and_instructions(self) -> None:
        task = TaskSpec(
            app="demo",
            version="1.2.3",
            os_version="24.03-lts-sp4",
            domain="Database",
            source_url="https://github.com/acme/demo",
            scenario="version-update",
        )
        prompt = upgrade_repair.build_repair_prompt(
            task=task,
            dockerfile_text=(
                "FROM openeuler/openeuler:24.03-lts-sp4\nARG VERSION=1.2.3\n"
            ),
            test_script_text="#!/bin/bash\nset -euo pipefail\ntest -f /app\n",
            evidence={
                "reports": ["aarch64.json: status=failed architecture=aarch64"],
                "failures": [
                    {
                        "architecture": "aarch64",
                        "stage": "test_sh",
                        "check": "runtime_test",
                        "failure": "backend did not become ready",
                        "details": {},
                    }
                ],
                "logs": [{"path": "test-runtime.docker.log", "tail": "159s"}],
            },
            instructions="把首次启动的模型预热放到构建期",
        )

        self.assertIn("Repair mode", prompt)
        self.assertIn("ARG VERSION=1.2.3", prompt)
        self.assertIn("test -f /app", prompt)
        self.assertIn("backend did not become ready", prompt)
        self.assertIn("test-runtime.docker.log", prompt)
        self.assertIn("把首次启动的模型预热放到构建期", prompt)
        self.assertIn('"test_script"', prompt)
        self.assertIn("Final response contract", prompt)


class TestScriptCheckTest(unittest.TestCase):
    def test_script_without_shebang_is_rejected(self) -> None:
        findings = upgrade_repair._validate_test_script("echo hi\n")

        self.assertTrue(findings)

    def test_empty_script_is_rejected(self) -> None:
        findings = upgrade_repair._validate_test_script("   \n")

        self.assertTrue(findings)


if __name__ == "__main__":
    unittest.main()
