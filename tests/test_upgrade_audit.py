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

    def test_fix_prompt_states_the_image_info_command_requirement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(Path(tmp))
            context = upgrade_audit.collect_context(repo, _ITEM)
            findings = upgrade_audit.deterministic_findings(context)
            prompt = upgrade_audit.build_fix_prompt(
                context,
                findings,
                {"verdict": "issues", "summary": "doc 与测试脚本不一致"},
                problems=["doc/image-info.yml 仍未包含测试脚本命令 ['srun']"],
            )

        self.assertIn('"test_script_commands"', prompt)
        self.assertIn("Hard requirement: image-info usage", prompt)
        self.assertIn("srun", prompt)
        self.assertIn("Previous attempt was rejected", prompt)
        self.assertIn("仍未包含测试脚本命令", prompt)

    def test_fix_retries_with_the_rejected_problems_when_validation_fails(
        self,
    ) -> None:
        rejected = self._corrected_payload()
        rejected["image_info"] = (
            "name: slurm\ntags: 26.05.6.1\nusage: |\n  docker run it\n"
        )
        corrected = self._corrected_payload()
        prompts: list[str] = []

        def fake_agent(**kwargs: object) -> mock.Mock:
            prompts.append(str(kwargs["prompt"]))
            return mock.Mock(payload=rejected if len(prompts) == 1 else corrected)

        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(Path(tmp))
            context = upgrade_audit.collect_context(repo, _ITEM)
            with (
                mock.patch.dict("os.environ", {"OPENCODE_BIN": "/bin/true"}),
                mock.patch.object(
                    upgrade_audit.ai_provider, "api_key", return_value="k"
                ),
                mock.patch.object(
                    upgrade_audit, "run_agent", side_effect=fake_agent
                ),
                mock.patch.object(upgrade_audit, "_reset_workspace"),
            ):
                payload = upgrade_audit.run_agent_fix(context, [], {}, repo)

        self.assertEqual(payload, corrected)
        self.assertEqual(len(prompts), 2)
        self.assertNotIn("Previous attempt was rejected", prompts[0])
        self.assertIn("Previous attempt was rejected", prompts[1])
        self.assertIn("测试脚本命令", prompts[1])

    def test_fix_gives_up_after_the_final_rejected_attempt(self) -> None:
        rejected = self._corrected_payload()
        rejected["image_info"] = "name: slurm\ntags: 26.05.6.1\n"

        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(Path(tmp))
            context = upgrade_audit.collect_context(repo, _ITEM)
            with (
                mock.patch.dict("os.environ", {"OPENCODE_BIN": "/bin/true"}),
                mock.patch.object(
                    upgrade_audit.ai_provider, "api_key", return_value="k"
                ),
                mock.patch.object(
                    upgrade_audit,
                    "run_agent",
                    return_value=mock.Mock(payload=rejected),
                ) as agent,
                mock.patch.object(upgrade_audit, "_reset_workspace"),
            ):
                with self.assertRaises(SystemExit) as raised:
                    upgrade_audit.run_agent_fix(context, [], {}, repo)

        message = str(raised.exception)
        self.assertIn("AI fix failed validation", message)
        self.assertIn("测试脚本命令", message)
        self.assertEqual(agent.call_count, 2)

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

    def test_apply_fix_registers_missing_version_in_meta_and_docs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(Path(tmp))
            app = repo / "Others" / "slurm"
            (app / "meta.yml").write_text("", encoding="utf-8")
            old_image = app / "26.05.5.1" / "24.03-lts-sp4"
            old_image.mkdir(parents=True)
            (old_image / "Dockerfile").write_text("FROM x\n", encoding="utf-8")
            old_row = (
                "|[26.05.5.1-oe2403sp4](https://gitcode.com/x/blob/master/"
                "Others/slurm/26.05.5.1/24.03-lts-sp4/Dockerfile) | "
                "slurm 26.05.5.1 on openEuler 24.03-LTS-SP4 | amd64, arm64 |\n"
            )
            (app / "README.md").write_text(
                "| Tags | Currently |  Architectures|\n|--|--|--|\n" + old_row,
                encoding="utf-8",
            )
            doc = app / "doc"
            doc.mkdir(exist_ok=True)
            (doc / "image-info.yml").write_text(
                "name: slurm\ntags: |\n  " + old_row + "usage: |\n  srun --version\n",
                encoding="utf-8",
            )

            context = upgrade_audit.collect_context(repo, _ITEM)
            payload = self._corrected_payload()
            # AI 修复只返回修好的 Dockerfile 与旧 image-info，漏登记新版本
            payload["image_info"] = (
                "name: slurm\ntags: |\n  " + old_row + "usage: |\n  srun --version\n"
            )

            changed = upgrade_audit.apply_fix(repo, context, payload)

            relative = {path.relative_to(repo).as_posix() for path in changed}
            self.assertIn("Others/slurm/meta.yml", relative)
            self.assertIn("Others/slurm/README.md", relative)
            self.assertIn("Others/slurm/doc/image-info.yml", relative)
            meta = (app / "meta.yml").read_text(encoding="utf-8")
            self.assertIn("26.05.6.1-oe2403sp4", meta)
            self.assertIn("26.05.6.1/24.03-lts-sp4/Dockerfile", meta)
            readme = (app / "README.md").read_text(encoding="utf-8")
            self.assertIn("26.05.6.1-oe2403sp4", readme)
            self.assertIn("26.05.6.1/24.03-lts-sp4/Dockerfile", readme)
            # 旧版本行保留，只追加新版本
            self.assertIn("26.05.5.1-oe2403sp4", readme)
            image_info = (doc / "image-info.yml").read_text(encoding="utf-8")
            self.assertIn("26.05.6.1-oe2403sp4", image_info)

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

    def test_prepare_pushes_branch_and_writes_handoff_artifacts(self) -> None:
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
        branch = "auto/image-audit/slurm/26.05.6.1"
        changed = ["Others/slurm/26.05.6.1/24.03-lts-sp4/Dockerfile"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            out = root / "audit-out"
            output_file = root / "github-output"
            output_file.touch()
            with (
                mock.patch.object(
                    upgrade_audit, "run_agent_audit", return_value=audit_payload
                ),
                mock.patch.object(
                    upgrade_audit, "run_agent_fix", return_value=fix_payload
                ),
                mock.patch.object(
                    upgrade_audit,
                    "push_fix",
                    return_value=(branch, "fork/openeuler-docker-images", changed),
                ) as push,
                mock.patch.dict(
                    "os.environ", {"GITHUB_OUTPUT": str(output_file)}
                ),
            ):
                code = upgrade_audit.run(
                    _ITEM,
                    repo_dir=repo,
                    out_dir=out,
                    dry_run=False,
                    prepare=True,
                )

            self.assertEqual(code, 0)
            push.assert_called_once()
            delivery = json.loads(
                (out / "delivery.json").read_text(encoding="utf-8")
            )
            self.assertEqual(delivery["branch"], branch)
            self.assertEqual(delivery["push_repo"], "fork/openeuler-docker-images")
            self.assertEqual(delivery["changed"], changed)
            task = json.loads((out / "task-spec.json").read_text(encoding="utf-8"))
            self.assertEqual(task["version"], "26.05.6.1")
            self.assertEqual(task["domain"], "Others")
            self.assertEqual(task["scenario"], "version-update")
            emitted = output_file.read_text(encoding="utf-8")
            self.assertIn("has_changes=true", emitted)
            self.assertIn(f"branch={branch}", emitted)
            report = (out / "audit.md").read_text(encoding="utf-8")
            self.assertIn("通过双架构原生校验后开 PR", report)

    def test_open_pr_from_delivery_creates_pr_for_pushed_branch(self) -> None:
        context = {
            "app": "slurm",
            "domain": "Others",
            "version": "26.05.6.1",
            "os_version": "24.03-lts-sp4",
            "dockerfile_path": "Others/slurm/26.05.6.1/24.03-lts-sp4/Dockerfile",
            "test_scripts": [{"path": "Others/slurm/tests/test.sh", "content": "srun --version\n"}],
            "evidence": {"tag": "slurm-26-05-6-1"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            delivery = Path(tmp) / "delivery.json"
            delivery.write_text(
                json.dumps(
                    {
                        "context": context,
                        "findings": [],
                        "audit": {"verdict": "critical", "summary": "bad tag"},
                        "fix": {"changes": ["fix tag"], "summary": "fixed"},
                        "branch": "auto/image-audit/slurm/26.05.6.1",
                        "push_repo": "fork/openeuler-docker-images",
                        "changed": ["Others/slurm/26.05.6.1/24.03-lts-sp4/Dockerfile"],
                    }
                ),
                encoding="utf-8",
            )
            with (
                mock.patch.object(
                    upgrade_audit, "find_any_pr_by_head_branch", return_value=None
                ),
                mock.patch.object(
                    upgrade_audit,
                    "create_pull_request",
                    return_value={"web_url": "https://gitcode.com/pr/9"},
                ) as create,
                mock.patch.dict(
                    "os.environ",
                    {
                        "GITCODE_TOKEN": "t",
                        "TARGET_REPO": "openeuler/openeuler-docker-images",
                        "TARGET_BRANCH": "master",
                    },
                ),
            ):
                url = upgrade_audit.open_pr_from_delivery(delivery)

            self.assertEqual(url, "https://gitcode.com/pr/9")
            self.assertEqual(
                create.call_args.args[1], "fork:auto/image-audit/slurm/26.05.6.1"
            )

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


class EnsureTestScriptTest(unittest.TestCase):
    """审计链路为缺 test.sh 的应用补测试。"""

    def test_existing_test_is_left_alone(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(Path(tmp))
            context = upgrade_audit.collect_context(repo, _ITEM)
            with mock.patch(
                "scripts.harness.testgen_generate.generate_test_script"
            ) as generate:
                paths = upgrade_audit.ensure_test_script(repo, context)

        self.assertEqual(paths, [])
        generate.assert_not_called()

    def test_generated_test_is_recorded_in_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(Path(tmp), with_test=False)
            context = upgrade_audit.collect_context(repo, _ITEM)
            test_path = repo / "Others" / "slurm" / "tests" / "test.sh"

            def fake_generate(**kwargs):
                self.assertEqual(
                    kwargs["dockerfile_rel"], _ITEM["dockerfile_path"]
                )
                self.assertEqual(kwargs["latest_version"], "26.05.6.1")
                test_path.parent.mkdir(parents=True, exist_ok=True)
                test_path.write_text(
                    '#!/bin/bash\n: "${EXPECTED_VERSION:?}"\nsrun --version\n',
                    encoding="utf-8",
                )
                return []

            with (
                mock.patch.dict("os.environ", {"OPENCODE_BIN": "/bin/true"}),
                mock.patch.object(
                    upgrade_audit.ai_provider, "api_key", return_value="key"
                ),
                mock.patch(
                    "scripts.harness.testgen_generate.generate_test_script",
                    side_effect=fake_generate,
                ),
            ):
                paths = upgrade_audit.ensure_test_script(repo, context)

            self.assertEqual(paths, [test_path])
            self.assertEqual(
                context["test_scripts"][0]["path"], "Others/slurm/tests/test.sh"
            )
            if sys.platform != "win32":
                self.assertTrue(test_path.stat().st_mode & 0o111)

    def test_failed_generation_is_not_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(Path(tmp), with_test=False)
            context = upgrade_audit.collect_context(repo, _ITEM)
            findings = [
                {
                    "code": "kunpeng.not_executable",
                    "level": "retry",
                    "owner": "testgen_creator",
                    "message": "test.sh must have the executable bit set",
                }
            ]
            with (
                mock.patch.dict("os.environ", {"OPENCODE_BIN": "/bin/true"}),
                mock.patch.object(
                    upgrade_audit.ai_provider, "api_key", return_value="key"
                ),
                mock.patch(
                    "scripts.harness.testgen_generate.generate_test_script",
                    return_value=findings,
                ),
            ):
                paths = upgrade_audit.ensure_test_script(repo, context)

        self.assertEqual(paths, [])
        self.assertEqual(context["test_scripts"], [])

    def test_prepare_commits_generated_test_with_the_fix(self) -> None:
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
        branch = "auto/image-audit/slurm/26.05.6.1"
        changed = [
            "Others/slurm/tests/test.sh",
            "Others/slurm/26.05.6.1/24.03-lts-sp4/Dockerfile",
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root, with_test=False)
            out = root / "audit-out"
            test_path = repo / "Others" / "slurm" / "tests" / "test.sh"
            with (
                mock.patch.object(
                    upgrade_audit, "run_agent_audit", return_value=audit_payload
                ),
                mock.patch.object(
                    upgrade_audit, "run_agent_fix", return_value=fix_payload
                ),
                mock.patch.object(
                    upgrade_audit, "ensure_test_script", return_value=[test_path]
                ),
                mock.patch.object(
                    upgrade_audit,
                    "push_fix",
                    return_value=(branch, "fork/openeuler-docker-images", changed),
                ) as push,
            ):
                code = upgrade_audit.run(
                    _ITEM,
                    repo_dir=repo,
                    out_dir=out,
                    dry_run=False,
                    prepare=True,
                )

            self.assertEqual(code, 0)
            self.assertEqual(push.call_args.kwargs["extra_paths"], [test_path])
            delivery = json.loads(
                (out / "delivery.json").read_text(encoding="utf-8")
            )
            self.assertTrue(
                all(
                    finding["component"] != "tests"
                    for finding in delivery["findings"]
                )
            )


if __name__ == "__main__":
    unittest.main()
