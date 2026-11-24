"""场景二 AI Dockerfile 生成单测（不联网、不调用真实 Agent）。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.harness import upgrade_apply  # noqa: E402
from scripts.lib import version_upgrade  # noqa: E402

_EVIDENCE = {
    "tag": "v2.17.0",
    "tag_url": "https://github.com/apache/kvrocks/releases/tag/v2.17.0",
    "commit_sha": "abc123",
    "collector": [
        {
            "check_id": "kp.l1.arm_ci",
            "result": "supported",
            "excerpt": "ARM 原生 job 全 success",
            "test_depth": "build_only",
        },
        {
            "check_id": "kp.l1.doc_declared",
            "result": "not_found",
        },
        {
            "check_id": "kp.l1.release_artifact",
            "result": "not_found",
        },
    ],
}


def _make_app(root: Path) -> Path:
    app = root / "Database" / "kvrocks"
    image = app / "2.16.0" / "24.03-lts-sp4"
    image.mkdir(parents=True)
    (image / "Dockerfile").write_text(
        "FROM openeuler/openeuler:24.03-lts-sp4\n"
        "ARG VERSION=2.16.0\n"
        "RUN curl -o /tmp/kvrocks.tar.gz https://example.com/kvrocks-2.16.0.tar.gz\n",
        encoding="utf-8",
    )
    return app


class DockerfilePromptTest(unittest.TestCase):
    def test_prompt_carries_contract_old_file_and_dashboard_evidence(self) -> None:
        app = Path("/tmp/Database/kvrocks")
        plan = version_upgrade.UpgradePlan(
            old_version="2.16.0",
            os_version="24.03-lts-sp4",
            src_dir=app / "2.16.0" / "24.03-lts-sp4",
        )
        prompt = upgrade_apply.build_dockerfile_prompt(
            app="kvrocks",
            domain="Database",
            plan=plan,
            item={
                "version": "2.17.0",
                "source_url": "https://github.com/apache/kvrocks",
                "evidence": _EVIDENCE,
            },
            old_dockerfile="FROM openeuler/openeuler:24.03-lts-sp4\nARG VERSION=2.16.0\n",
        )

        self.assertIn("Immutable task contract", prompt)
        self.assertIn('"new_version": "2.17.0"', prompt)
        self.assertIn("ARG VERSION=2.16.0", prompt)
        self.assertIn("kp.l1.arm_ci", prompt)
        self.assertIn("ARM 原生 job 全 success", prompt)
        self.assertIn("dockerfile", prompt)

    def test_prompt_carries_manifest_build_notes(self) -> None:
        app = Path("/tmp/Storage/drbd")
        plan = version_upgrade.UpgradePlan(
            old_version="9.31.0",
            os_version="24.03-lts-sp4",
            src_dir=app / "9.31.0" / "24.03-lts-sp4",
        )
        prompt = upgrade_apply.build_dockerfile_prompt(
            app="drbd",
            domain="Storage",
            plan=plan,
            item={
                "version": "9.3.5",
                "source_url": "https://github.com/LINBIT/drbd",
                "build_notes": "build the kernel module",
            },
            old_dockerfile="FROM openeuler/openeuler:24.03-lts-sp4\n",
        )
        self.assertIn('"build_notes": "build the kernel module"', prompt)

    def test_prompt_carries_the_app_notes_document(self) -> None:
        from scripts.lib import app_notes

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "kvrocks.md").write_text(
                "---\napp: kvrocks\n---\n# kvrocks\n\n先确认下载 URL。\n",
                encoding="utf-8",
            )
            with mock.patch.object(app_notes, "NOTES_DIR", Path(tmp)):
                notes = app_notes.load("kvrocks")
        prompt = upgrade_apply.build_dockerfile_prompt(
            app="kvrocks",
            domain="Database",
            plan=version_upgrade.UpgradePlan(
                old_version="2.16.0",
                os_version="24.03-lts-sp4",
                src_dir=Path("/tmp/Database/kvrocks/2.16.0/24.03-lts-sp4"),
            ),
            item={"version": "2.17.0", "source_url": "https://example.com"},
            old_dockerfile="FROM openeuler/openeuler:24.03-lts-sp4\n",
            notes=notes,
        )

        self.assertIn("## App upgrade notes", prompt)
        self.assertIn("先确认下载 URL", prompt)

    def test_replay_section_targets_the_second_architecture(self) -> None:
        section = upgrade_apply.container_verification_section(
            staging=Path("/tmp/context"),
            container="oe-upgrade-demo-replay",
            output_dockerfile=Path("/tmp/final-Dockerfile"),
            build_log=Path("/tmp/build-log.md"),
            arch="aarch64",
            mode="replay",
        )

        self.assertIn("aarch64", section)
        self.assertIn("x86_64 的容器里逐条重放通过", section)
        self.assertIn("只修复与架构相关的问题", section)
        self.assertIn("docker exec", section)


class GenerateDockerfileTest(unittest.TestCase):
    def test_agent_gets_the_evidence_and_its_output_is_used(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = _make_app(Path(tmp))
            plan = version_upgrade.plan_upgrade(app)
            item = {
                "version": "2.17.0",
                "source_url": "https://github.com/apache/kvrocks",
                "evidence": _EVIDENCE,
            }
            captured: dict = {}

            def fake_run_agent(**kwargs):
                captured.update(kwargs)
                return SimpleNamespace(
                    payload={
                        "success": True,
                        "dockerfile": (
                            "FROM openeuler/openeuler:24.03-lts-sp4\n"
                            "ARG VERSION=2.17.0\n"
                        ),
                        "summary": "bump version and download URL",
                    }
                )

            with (
                mock.patch.object(upgrade_apply, "run_agent", fake_run_agent),
                mock.patch.object(upgrade_apply, "_reset_workspace"),
                mock.patch.object(upgrade_apply.ai_provider, "api_key", return_value="k"),
                mock.patch.object(
                    upgrade_apply.shutil, "which", return_value="/usr/bin/opencode"
                ),
                mock.patch.object(
                    upgrade_apply.build_runner, "activate_docker_shim", return_value=""
                ),
                mock.patch.object(upgrade_apply.build_runner, "docker_rm"),
                mock.patch.object(upgrade_apply.build_runner, "docker_rm_by_label"),
                mock.patch.object(
                    upgrade_apply.build_runner, "docker_rm_images_by_label"
                ),
            ):
                dockerfile, supporting = upgrade_apply._generate_dockerfile(
                    repo_dir=app.parent.parent,
                    app="kvrocks",
                    domain="Database",
                    plan=plan,
                    item=item,
                )

        self.assertEqual(supporting, {})
        self.assertEqual(captured["role"], "upgrade_creator")
        self.assertIn("kp.l1.release_artifact", captured["prompt"])
        self.assertIn("Container build verification", captured["prompt"])
        self.assertIn("docker exec", captured["prompt"])
        self.assertIn("ARG VERSION=2.17.0", dockerfile)

    def test_agent_must_audit_every_supporting_script(self) -> None:
        """Dockerfile 引用的辅助脚本少了审计结论就判失败，不允许静默沿用旧脚本。"""
        with tempfile.TemporaryDirectory() as tmp:
            app = _make_app(Path(tmp))
            src = app / "2.16.0" / "24.03-lts-sp4"
            (src / "build.sh").write_text("#!/bin/bash\nmake\n", encoding="utf-8")
            (src / "Dockerfile").write_text(
                "FROM openeuler/openeuler:24.03-lts-sp4\n"
                "ARG VERSION=2.16.0\n"
                "COPY build.sh /opt/\n",
                encoding="utf-8",
            )
            plan = version_upgrade.plan_upgrade(app)
            item = {"version": "2.17.0", "source_url": "https://example.com"}
            prompts: list[str] = []

            def fake_run_agent(**kwargs):
                prompts.append(kwargs["prompt"])
                return SimpleNamespace(
                    payload={
                        "success": True,
                        "dockerfile": (
                            "FROM openeuler/openeuler:24.03-lts-sp4\n"
                            "ARG VERSION=2.17.0\n"
                            "COPY build.sh /opt/\n"
                        ),
                        "summary": "bump",
                    }
                )

            with (
                mock.patch.object(upgrade_apply, "run_agent", fake_run_agent),
                mock.patch.object(upgrade_apply, "_reset_workspace"),
                mock.patch.object(upgrade_apply.ai_provider, "api_key", return_value="k"),
                mock.patch.object(
                    upgrade_apply.shutil, "which", return_value="/usr/bin/opencode"
                ),
                mock.patch.object(
                    upgrade_apply.build_runner, "activate_docker_shim", return_value=""
                ),
                mock.patch.object(upgrade_apply.build_runner, "docker_rm"),
                mock.patch.object(upgrade_apply.build_runner, "docker_rm_by_label"),
                mock.patch.object(
                    upgrade_apply.build_runner, "docker_rm_images_by_label"
                ),
            ):
                with self.assertRaises(version_upgrade.UpgradeError):
                    upgrade_apply._generate_dockerfile(
                        repo_dir=app.parent.parent,
                        app="kvrocks",
                        domain="Database",
                        plan=plan,
                        item=item,
                    )

        self.assertIn("Supporting build scripts (mandatory audit)", prompts[0])
        self.assertIn("build.sh", prompts[0])

    def test_dockerfile_written_by_agent_survives_a_timeout(self) -> None:
        """Agent 超时不等于零产出：容器里落盘的 Dockerfile 优先于退出码。"""
        with tempfile.TemporaryDirectory() as tmp:
            app = _make_app(Path(tmp))
            plan = version_upgrade.plan_upgrade(app)
            item = {"version": "2.17.0", "source_url": "https://example.com"}
            fixed = (
                "FROM openeuler/openeuler:24.03-lts-sp4\n"
                "ARG VERSION=2.17.0\n"
            )
            session_root = Path(tmp) / "session"

            def fake_session_dir(*args, **kwargs):
                session_root.mkdir(parents=True, exist_ok=True)
                return session_root

            def fake_run_agent(**kwargs):
                (session_root / "final-Dockerfile").write_text(
                    fixed, encoding="utf-8"
                )
                raise TimeoutError("agent budget exhausted")

            with (
                mock.patch.object(upgrade_apply, "run_agent", fake_run_agent),
                mock.patch.object(upgrade_apply, "session_dir", fake_session_dir),
                mock.patch.object(upgrade_apply, "_reset_workspace"),
                mock.patch.object(upgrade_apply.ai_provider, "api_key", return_value="k"),
                mock.patch.object(
                    upgrade_apply.shutil, "which", return_value="/usr/bin/opencode"
                ),
                mock.patch.object(
                    upgrade_apply.build_runner, "activate_docker_shim", return_value=""
                ),
                mock.patch.object(upgrade_apply.build_runner, "docker_rm"),
                mock.patch.object(upgrade_apply.build_runner, "docker_rm_by_label"),
                mock.patch.object(
                    upgrade_apply.build_runner, "docker_rm_images_by_label"
                ),
            ):
                dockerfile, _ = upgrade_apply._generate_dockerfile(
                    repo_dir=app.parent.parent,
                    app="kvrocks",
                    domain="Database",
                    plan=plan,
                    item=item,
                )

        self.assertEqual(dockerfile.strip(), fixed.strip())


if __name__ == "__main__":
    unittest.main()
