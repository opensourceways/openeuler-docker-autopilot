"""场景二「已是最新版本」审计单测（不联网、不调用真实 Agent）。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.harness import upgrade_audit  # noqa: E402

_ITEM = {
    "app": "slurm",
    "domain": "Others",
    "version": "26.05.6.1",
    "os_version": "24.03-lts-sp4",
    "dockerfile_path": "Others/slurm/26.05.6.1/24.03-lts-sp4/Dockerfile",
    "source_url": "https://github.com/SchedMD/slurm",
    "has_test_script": True,
    "evidence": {
        "tag": "slurm-26-05-6-1",
        "tag_url": "https://github.com/SchedMD/slurm/releases/tag/slurm-26-05-6-1",
        "commit_sha": "599e8ac50eaff5547946f3f0687d9fe3bf44347f",
        "collector": [
            {"check_id": "kp.l1.arm_ci", "result": "supported"},
            {"check_id": "kp.l1.doc_declared", "result": "not_found"},
            {"check_id": "kp.l1.release_artifact", "result": "not_found"},
        ],
    },
}


def _make_repo(root: Path, *, tag: str = "slurm-26-05-4-1", with_test: bool = True) -> Path:
    repo = root / "target"
    image = repo / "Others" / "slurm" / "26.05.6.1" / "24.03-lts-sp4"
    image.mkdir(parents=True)
    (image / "Dockerfile").write_text(
        "ARG BASE=openeuler/openeuler:24.03-lts-sp4\n"
        "FROM $BASE\n"
        "ARG VERSION=26.05.6.1\n"
        f"ARG TAG={tag}\n"
        "RUN git clone -b ${TAG} https://github.com/SchedMD/slurm.git /slurm\n",
        encoding="utf-8",
    )
    (repo / "Others" / "slurm" / "meta.yml").write_text(
        "26.05.6.1-oe2403sp4:\n"
        "  path: 26.05.6.1/24.03-lts-sp4/Dockerfile\n",
        encoding="utf-8",
    )
    if with_test:
        tests = repo / "Others" / "slurm" / "tests"
        tests.mkdir()
        (tests / "test.sh").write_text(
            "#!/bin/bash\n"
            ': "${EXPECTED_VERSION:?EXPECTED_VERSION is required}"\n'
            "srun --version\n",
            encoding="utf-8",
        )
    return repo


class DeterministicAuditTest(unittest.TestCase):
    def test_mismatched_upstream_tag_is_a_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(Path(tmp))
            context = upgrade_audit.collect_context(repo, _ITEM)
            findings = upgrade_audit.deterministic_findings(context)
            summary = upgrade_audit.deterministic_summary(context, findings)

        codes = {finding["code"] for finding in findings}
        self.assertIn("tag.mismatch", codes)
        tag_finding = next(f for f in findings if f["code"] == "tag.mismatch")
        self.assertEqual(tag_finding["severity"], "blocker")
        self.assertIn("slurm-26-05-6-1", tag_finding["message"])
        self.assertNotIn("test.missing", codes)
        self.assertFalse(summary["version"]["ok"])
        self.assertTrue(summary["test_script"]["present"])
        self.assertTrue(summary["test_script"]["expects_version"])
        self.assertEqual(
            [check["check_id"] for check in summary["evidence"]["l1_checks"]],
            ["kp.l1.arm_ci", "kp.l1.doc_declared", "kp.l1.release_artifact"],
        )

    def test_missing_test_script_and_meta_entry_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(Path(tmp), with_test=False)
            (repo / "Others" / "slurm" / "meta.yml").write_text("", encoding="utf-8")
            context = upgrade_audit.collect_context(repo, _ITEM)
            findings = upgrade_audit.deterministic_findings(context)

        codes = {finding["code"] for finding in findings}
        self.assertIn("test.missing", codes)
        self.assertIn("meta.mismatch", codes)

    def test_prompt_contains_dockerfile_evidence_and_findings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(Path(tmp))
            context = upgrade_audit.collect_context(repo, _ITEM)
            findings = upgrade_audit.deterministic_findings(context)
            prompt = upgrade_audit.build_prompt(context, findings)

        self.assertIn("ARG TAG=slurm-26-05-4-1", prompt)
        self.assertIn("kp.l1.arm_ci", prompt)
        self.assertIn("tag.mismatch", prompt)
        self.assertIn("Deterministic findings", prompt)

    def test_image_info_is_checked_against_test_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(Path(tmp))
            doc = repo / "Others" / "slurm" / "doc"
            doc.mkdir()
            (doc / "image-info.yml").write_text(
                "name: slurm\n"
                "tags: slurm 26.05.6.1\n"
                "usage: |\n"
                "  docker run -it openeuler/slurm:{Tag}\n"
                "  slurm --version\n",
                encoding="utf-8",
            )
            context = upgrade_audit.collect_context(repo, _ITEM)
            findings = upgrade_audit.deterministic_findings(context)

        codes = {finding["code"] for finding in findings}
        self.assertIn("image_info.test_commands_missing", codes)
        self.assertNotIn("image_info.version_missing", codes)


class FixValidationTest(unittest.TestCase):
    def _corrected_payload(self) -> dict:
        return {
            "success": True,
            "dockerfile": (
                "FROM openeuler/openeuler:24.03-lts-sp4\n"
                "ARG VERSION=26.05.6.1\n"
                "ARG TAG=slurm-26-05-6-1\n"
                "RUN git clone -b ${TAG} https://github.com/SchedMD/slurm.git /slurm\n"
            ),
            "image_info": (
                "name: slurm\n"
                "tags: |\n"
                "  |26.05.6.1-oe2403sp4| slurm 26.05.6.1 on openEuler 24.03-LTS-SP4 |\n"
                "usage: |\n"
                "  docker run -it openeuler/slurm:{Tag}\n"
                "  srun --version\n"
                "  scontrol show hostnames 'node[1-4]'\n"
            ),
            "changes": ["fix tag", "align image-info usage"],
            "summary": "fix",
        }

    def test_corrected_payload_passes_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(Path(tmp))
            context = upgrade_audit.collect_context(repo, _ITEM)
            payload = self._corrected_payload()

        self.assertEqual(upgrade_audit.validate_fix(context, payload), [])

    def test_wrong_tag_and_missing_commands_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(Path(tmp))
            context = upgrade_audit.collect_context(repo, _ITEM)
            payload = self._corrected_payload()
            payload["dockerfile"] = payload["dockerfile"].replace(
                "slurm-26-05-6-1", "slurm-26-05-4-1"
            )
            payload["image_info"] = "name: slurm\nusage: |\n  slurm --version\n"

            problems = upgrade_audit.validate_fix(context, payload)

        self.assertTrue(any("tag" in problem for problem in problems))
        self.assertTrue(
            any("测试脚本命令" in problem for problem in problems), problems
        )
        self.assertTrue(any("目标版本" in problem for problem in problems))

    def test_apply_fix_writes_dockerfile_and_image_info(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(Path(tmp))
            context = upgrade_audit.collect_context(repo, _ITEM)
            payload = self._corrected_payload()

            changed = upgrade_audit.apply_fix(repo, context, payload)

            relative = {path.relative_to(repo).as_posix() for path in changed}
            self.assertIn(
                "Others/slurm/26.05.6.1/24.03-lts-sp4/Dockerfile", relative
            )
            self.assertIn("Others/slurm/doc/image-info.yml", relative)
            dockerfile = (
                repo / "Others/slurm/26.05.6.1/24.03-lts-sp4/Dockerfile"
            ).read_text(encoding="utf-8")
            self.assertIn("slurm-26-05-6-1", dockerfile)
            image_info = (repo / "Others/slurm/doc/image-info.yml").read_text(
                encoding="utf-8"
            )
            self.assertIn("srun --version", image_info)

    def test_pr_body_mentions_audit_and_test_alignment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(Path(tmp))
            context = upgrade_audit.collect_context(repo, _ITEM)
            findings = upgrade_audit.deterministic_findings(context)
            audit_payload = {"verdict": "critical", "summary": "bad tag", "dockerfile_issues": []}
            fix_payload = self._corrected_payload()
            body = upgrade_audit.build_fix_pr_body(
                context, findings, audit_payload, fix_payload
            )

        self.assertIn("审计结论", body)
        self.assertIn("doc/image-info.yml", body)
        self.assertIn("srun", body)


class DryRunTest(unittest.TestCase):
    def test_dry_run_writes_report_without_ai(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            out = root / "audit-out"
            code = upgrade_audit.run(
                _ITEM, repo_dir=repo, out_dir=out, dry_run=True
            )

            self.assertEqual(code, 0)
            document = json.loads((out / "audit.json").read_text(encoding="utf-8"))
            self.assertIsNone(document["ai"])
            self.assertTrue(
                any(
                    finding["code"] == "tag.mismatch"
                    for finding in document["deterministic_findings"]
                )
            )
            report = (out / "audit.md").read_text(encoding="utf-8")
            self.assertIn("dry-run", report)
            self.assertIn("确定性结论", report)
            self.assertIn("tag.mismatch", report)

    def test_deliver_runs_fix_and_records_the_pr(self) -> None:
        audit_payload = {
            "success": True,
            "verdict": "critical",
            "dockerfile_issues": [],
            "evidence_alignment": {},
            "version_check": {},
            "test_script": {},
            "summary": "bad tag",
        }
        fix_payload = {
            "success": True,
            "dockerfile": "FROM x\nARG VERSION=26.05.6.1\nARG TAG=slurm-26-05-6-1\n",
            "image_info": "name: slurm\n",
            "changes": ["fix tag"],
            "summary": "fixed",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            out = root / "audit-out"
            with (
                mock.patch.object(
                    upgrade_audit, "run_agent_audit", return_value=audit_payload
                ),
                mock.patch.object(
                    upgrade_audit, "run_agent_fix", return_value=fix_payload
                ),
                mock.patch.object(
                    upgrade_audit,
                    "deliver_fix",
                    return_value="https://gitcode.com/pr/1",
                ),
            ):
                code = upgrade_audit.run(
                    _ITEM,
                    repo_dir=repo,
                    out_dir=out,
                    dry_run=False,
                    deliver=True,
                )

            self.assertEqual(code, 0)
            document = json.loads((out / "audit.json").read_text(encoding="utf-8"))
            self.assertEqual(document["fix"], fix_payload)
            self.assertEqual(document["pr_url"], "https://gitcode.com/pr/1")
            report = (out / "audit.md").read_text(encoding="utf-8")
            self.assertIn("修复（AI）", report)
            self.assertIn("https://gitcode.com/pr/1", report)

    def test_ai_payload_is_rendered_into_the_report(self) -> None:
        payload = {
            "success": True,
            "verdict": "critical",
            "dockerfile_issues": [
                {
                    "severity": "blocker",
                    "message": "clone tag does not match the target version",
                    "evidence": "ARG TAG=slurm-26-05-4-1",
                }
            ],
            "evidence_alignment": {
                "aligned": False,
                "checks": [
                    {
                        "check_id": "kp.l1.arm_ci",
                        "result": "supported",
                        "applied": True,
                        "comment": "ARM CI passes",
                    }
                ],
            },
            "version_check": {
                "expected": "26.05.6.1",
                "found": ["slurm-26-05-4-1"],
                "ok": False,
            },
            "test_script": {
                "present": True,
                "path": "Others/slurm/tests/test.sh",
                "adequate": True,
                "issues": [],
            },
            "summary": "image would build the wrong upstream tag",
            "error": None,
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            out = root / "audit-out"
            with mock.patch.object(
                upgrade_audit, "run_agent_audit", return_value=payload
            ):
                code = upgrade_audit.run(
                    _ITEM, repo_dir=repo, out_dir=out, dry_run=False
                )

            self.assertEqual(code, 0)
            report = (out / "audit.md").read_text(encoding="utf-8")
            self.assertIn("critical", report)
            self.assertIn("Dockerfile 问题（AI）", report)
            self.assertIn("clone tag does not match", report)
            document = json.loads((out / "audit.json").read_text(encoding="utf-8"))
            self.assertEqual(document["ai"]["verdict"], "critical")


if __name__ == "__main__":
    unittest.main()
