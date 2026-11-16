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
            ):
                dockerfile = upgrade_apply._generate_dockerfile(
                    repo_dir=app.parent.parent,
                    app="kvrocks",
                    domain="Database",
                    plan=plan,
                    item=item,
                )

        self.assertEqual(captured["role"], "upgrade_creator")
        self.assertIn("kp.l1.release_artifact", captured["prompt"])
        self.assertIn("ARG VERSION=2.17.0", dockerfile)


if __name__ == "__main__":
    unittest.main()
