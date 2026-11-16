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


class CpuTorchGuardTest(unittest.TestCase):
    def test_injects_cpu_torch_before_requirements_install(self) -> None:
        dockerfile = (
            "FROM openeuler/openeuler:24.03-lts-sp4\n"
            "RUN pip install --retries 5 -r backend/requirements.txt\n"
        )
        guarded = upgrade_apply.ensure_cpu_torch(
            dockerfile, "sentence-transformers==5.5.1\n"
        )
        self.assertIn(upgrade_apply.CPU_TORCH_RUN, guarded)
        self.assertLess(
            guarded.index(upgrade_apply.CPU_TORCH_RUN),
            guarded.index("pip install --retries 5 -r backend/requirements.txt"),
        )

    def test_skips_when_requirements_do_not_need_torch(self) -> None:
        dockerfile = "RUN pip install -r backend/requirements.txt\n"
        self.assertEqual(
            upgrade_apply.ensure_cpu_torch(dockerfile, "fastapi\n"), dockerfile
        )

    def test_keeps_existing_cpu_torch_install(self) -> None:
        dockerfile = (
            "RUN pip install torch --index-url https://download.pytorch.org/whl/cpu\n"
            "RUN pip install -r backend/requirements.txt\n"
        )
        self.assertEqual(
            upgrade_apply.ensure_cpu_torch(dockerfile, "torch==2.9.1\n"), dockerfile
        )

    def test_requirements_url_uses_the_pinned_tag(self) -> None:
        seen = []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b"sentence-transformers\n"

        def fake_urlopen(url, timeout):
            seen.append((url, timeout))
            return Response()

        with mock.patch.object(
            upgrade_apply.urllib.request, "urlopen", fake_urlopen
        ):
            text = upgrade_apply.fetch_upstream_requirements(
                {
                    "version": "0.13.3",
                    "source_url": "https://github.com/open-webui/open-webui",
                    "evidence": {"tag": "v0.13.3"},
                }
            )

        self.assertEqual(text, "sentence-transformers\n")
        self.assertEqual(
            seen[0][0],
            "https://raw.githubusercontent.com/open-webui/open-webui/"
            "v0.13.3/backend/requirements.txt",
        )


class ModelPrefetchGuardTest(unittest.TestCase):
    def test_prefetches_model_before_cmd_for_open_webui(self) -> None:
        dockerfile = (
            "ENV HF_ENDPOINT=https://hf-mirror.com\n"
            'CMD ["/bin/bash", "-c", "/root/open-webui/backend/start.sh"]\n'
        )
        guarded = upgrade_apply.ensure_model_prefetch(
            dockerfile, "sentence-transformers==5.5.1\n"
        )
        self.assertIn(upgrade_apply.MODEL_PREFETCH_RUN, guarded)
        self.assertLess(
            guarded.index(upgrade_apply.MODEL_PREFETCH_RUN),
            guarded.index("CMD"),
        )

    def test_skips_apps_that_do_not_need_the_model(self) -> None:
        dockerfile = 'FROM x\nCMD ["true"]\n'
        self.assertEqual(
            upgrade_apply.ensure_model_prefetch(
                dockerfile, "sentence-transformers==5.5.1\n"
            ),
            dockerfile,
        )

    def test_skips_when_model_is_already_prefetched(self) -> None:
        dockerfile = (
            'RUN python -c "from sentence_transformers import SentenceTransformer; '
            "SentenceTransformer('m')\"\n"
            'CMD ["true"]\n'
        )
        self.assertEqual(
            upgrade_apply.ensure_model_prefetch(dockerfile, "sentence-transformers\n"),
            dockerfile,
        )


if __name__ == "__main__":
    unittest.main()
