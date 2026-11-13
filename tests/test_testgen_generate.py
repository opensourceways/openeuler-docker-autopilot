"""Tests for the scenario-four per-app generation stage."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.harness import testgen_generate  # noqa: E402
from scripts.lib.kunpeng_test_contract import check_test_script  # noqa: E402

_GOOD_SCRIPT = """#!/bin/bash

EXPECTED_VERSION="${EXPECTED_VERSION:?EXPECTED_VERSION is required}"

test_version() {
    local out
    out="$(myapp --version 2>&1 || true)"
    if [ "${out}" = "myapp version ${EXPECTED_VERSION}" ]; then
        echo "PASS: exact version ${out}"
        return 0
    fi
    echo "FAIL: version mismatch"
    return 1
}

main() {
    local failures=0
    test_version || failures=$((failures + 1))
    if [ "${failures}" -eq 0 ]; then
        echo "ALL_TESTS_PASSED"
        return 0
    fi
    echo "TESTS_FAILED: ${failures} failure(s)"
    return 1
}

main "$@"
"""

_BAD_SCRIPT = "#!/bin/bash\nset -e\n" + _GOOD_SCRIPT.split("\n", 1)[1]

_ITEM = {
    "app": "myapp",
    "domain": "Database",
    "version": "2.0.0",
    "os_version": "24.03-lts-sp4",
    "source_url": "https://github.com/example/myapp",
}


def _init_target_repo(tmp_path: Path) -> Path:
    """Create a git repo shaped like a tiny openeuler-docker-images clone."""
    repo = tmp_path / "source-repo"
    repo.mkdir()
    dockerfile = repo / "Database" / "myapp" / "2.0.0" / "24.03-lts-sp4" / "Dockerfile"
    dockerfile.parent.mkdir(parents=True)
    dockerfile.write_bytes(b"FROM openeuler/openeuler:24.03-lts-sp4\nRUN install myapp\n")
    subprocess.run(["git", "init", "-b", "master"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "t@example.com"],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "t"],
        capture_output=True, check=True,
    )
    subprocess.run(["git", "-C", str(repo), "add", "-A"], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "init"],
        capture_output=True, check=True,
    )
    return repo


def _script_writer(scripts: list[str]):
    """Fake run_agent that writes the next script into the workspace."""

    def fake_run_agent(*, repo_dir_holder=[], **kwargs):
        workspace = Path(kwargs["workspace"])
        (workspace / "Database" / "myapp" / "tests").mkdir(parents=True, exist_ok=True)
        (workspace / "Database" / "myapp" / "tests" / "test.sh").write_text(
            scripts.pop(0), encoding="utf-8"
        )
        return mock.Mock(payload={"success": True})

    return fake_run_agent


class AppendBlankLineTest(unittest.TestCase):
    def test_appends_single_blank_line(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Dockerfile"
            path.write_bytes(b"FROM x\nEXPOSE 80\n")
            self.assertTrue(testgen_generate.append_blank_line(path))
            self.assertEqual(path.read_bytes(), b"FROM x\nEXPOSE 80\n\n")

    def test_idempotent_when_blank_line_exists(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Dockerfile"
            path.write_bytes(b"FROM x\n\n")
            self.assertFalse(testgen_generate.append_blank_line(path))
            self.assertEqual(path.read_bytes(), b"FROM x\n\n")

    def test_normalizes_missing_trailing_newline(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Dockerfile"
            path.write_bytes(b"FROM x")
            self.assertTrue(testgen_generate.append_blank_line(path))
            self.assertEqual(path.read_bytes(), b"FROM x\n\n")

    def test_preserves_crlf(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Dockerfile"
            path.write_bytes(b"FROM x\r\nEXPOSE 80\r\n")
            self.assertTrue(testgen_generate.append_blank_line(path))
            self.assertEqual(path.read_bytes(), b"FROM x\r\nEXPOSE 80\r\n\r\n")


class BuildPromptTest(unittest.TestCase):
    def test_prompt_contains_contract_and_response_rules(self) -> None:
        prompt = testgen_generate.build_prompt(
            app="myapp",
            domain="Database",
            dockerfile_rel="Database/myapp/2.0.0/24.03-lts-sp4/Dockerfile",
            source_url="https://github.com/example/myapp",
            latest_version="2.0.0",
            sample_paths=["Database/kvrocks/tests/test.sh"],
        )
        self.assertIn("KunpengTest", prompt)
        self.assertIn('"package_name": "myapp"', prompt)
        self.assertIn("Final response contract", prompt)
        self.assertNotIn("Static contract report to resolve", prompt)

    def test_repair_round_includes_findings(self) -> None:
        findings = [{"code": "kunpeng.set_e", "message": "set -e is forbidden"}]
        prompt = testgen_generate.build_prompt(
            app="myapp",
            domain="Database",
            dockerfile_rel="Database/myapp/2.0.0/24.03-lts-sp4/Dockerfile",
            source_url="",
            latest_version="2.0.0",
            sample_paths=[],
            findings=findings,
        )
        self.assertIn("Static contract report to resolve", prompt)
        self.assertIn("kunpeng.set_e", prompt)


class ScopeFindingsTest(unittest.TestCase):
    def test_change_outside_tests_is_flagged(self) -> None:
        subprocess_run = subprocess.run  # keep reference
        with mock.patch.object(testgen_generate, "_git") as git:
            git.return_value = mock.Mock(
                stdout=' M Database/myapp/2.0.0/24.03-lts-sp4/Dockerfile\n'
                '?? Database/myapp/tests/test.sh\n'
            )
            findings = testgen_generate._scope_findings(
                Path("repo"), "Database/myapp/tests/"
            )
        codes = [f["message"] for f in findings]
        self.assertTrue(all("Dockerfile" in m for m in codes), codes)
        self.assertEqual(len(findings), 1)
        del subprocess_run


class GenerateTestScriptTest(unittest.TestCase):
    def test_passes_on_first_round(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            repo = _init_target_repo(Path(tmp))
            with mock.patch.object(
                testgen_generate,
                "run_agent",
                side_effect=_script_writer([_GOOD_SCRIPT]),
            ):
                findings = testgen_generate.generate_test_script(
                    repo_dir=repo,
                    app="myapp",
                    domain="Database",
                    dockerfile_rel="Database/myapp/2.0.0/24.03-lts-sp4/Dockerfile",
                    source_url="https://github.com/example/myapp",
                    latest_version="2.0.0",
                    api_key="key",
                    executable=Path("/fake/opencode"),
                )
            self.assertEqual(findings, [])
            self.assertEqual(
                check_test_script(repo / "Database" / "myapp" / "tests" / "test.sh"),
                [],
            )

    def test_repairs_then_passes(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            repo = _init_target_repo(Path(tmp))
            with mock.patch.object(
                testgen_generate,
                "run_agent",
                side_effect=_script_writer([_BAD_SCRIPT, _GOOD_SCRIPT]),
            ):
                findings = testgen_generate.generate_test_script(
                    repo_dir=repo,
                    app="myapp",
                    domain="Database",
                    dockerfile_rel="Database/myapp/2.0.0/24.03-lts-sp4/Dockerfile",
                    source_url="",
                    latest_version="2.0.0",
                    api_key="key",
                    executable=Path("/fake/opencode"),
                )
            self.assertEqual(findings, [])

    def test_exhausts_after_max_rounds(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            repo = _init_target_repo(Path(tmp))
            with mock.patch.object(
                testgen_generate,
                "run_agent",
                side_effect=_script_writer([_BAD_SCRIPT] * 3),
            ) as agent:
                findings = testgen_generate.generate_test_script(
                    repo_dir=repo,
                    app="myapp",
                    domain="Database",
                    dockerfile_rel="Database/myapp/2.0.0/24.03-lts-sp4/Dockerfile",
                    source_url="",
                    latest_version="2.0.0",
                    api_key="key",
                    executable=Path("/fake/opencode"),
                )
            self.assertEqual(agent.call_count, 3)
            self.assertTrue(any(f["code"] == "kunpeng.set_e" for f in findings))


class RunGenerateTest(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.repo = _init_target_repo(Path(self._tmp.name))
        self.env = {
            "SOURCE_REPO_DIR": str(self.repo),
            "DEEPSEEK_API_KEY": "key",
            "GITCODE_TOKEN": "token",
            "GITCODE_FORK_REPO": "m0_fork/openeuler-docker-images",
            "GIT_COMMIT_NAME": "bot",
            "GIT_COMMIT_EMAIL": "bot@example.com",
        }
        patcher = mock.patch.dict(os.environ, self.env, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _full_run(self, scripts, pr_existing=None):
        pushes: list[list[str]] = []

        def fake_push(repo_dir, *args, **kwargs):
            pushes.append(list(args))
            return mock.Mock(returncode=0)

        created: list[dict] = []

        def fake_create(repo, head, base, title, body, token):
            created.append(
                {"repo": repo, "head": head, "base": base, "title": title}
            )
            return {"web_url": "https://gitcode.com/pr/99"}

        with (
            mock.patch.object(testgen_generate, "run_agent",
                              side_effect=_script_writer(scripts)),
            mock.patch.object(testgen_generate, "_git",
                              side_effect=lambda repo_dir, *a, **k: (
                                  fake_push(repo_dir, *a, **k)
                                  if a and a[0] == "push"
                                  else mock.Mock(returncode=0, stdout="")
                              )),
            mock.patch.object(testgen_generate, "find_any_pr_by_head_branch",
                              return_value=pr_existing),
            mock.patch.object(testgen_generate, "create_pull_request",
                              side_effect=fake_create),
            mock.patch("shutil.which", return_value="/fake/opencode"),
        ):
            code = testgen_generate.run_generate(dict(_ITEM))
        return {
            "code": code,
            "created": created,
            "pushes": pushes,
        }

    def test_full_success_creates_pr(self) -> None:
        result = self._full_run([_GOOD_SCRIPT])
        self.assertEqual(result["code"], 0)
        self.assertEqual(len(result["created"]), 1)
        pr = result["created"][0]
        self.assertEqual(pr["repo"], "openeuler/openeuler-docker-images")
        self.assertEqual(pr["head"], "m0_fork:auto/test-script/myapp")
        self.assertEqual(pr["base"], "master")
        # Dockerfile got its blank line
        dockerfile = (
            self.repo / "Database" / "myapp" / "2.0.0" / "24.03-lts-sp4" / "Dockerfile"
        )
        self.assertTrue(dockerfile.read_bytes().endswith(b"\n\n"))

    def test_existing_open_pr_skips_creation(self) -> None:
        existing = {"web_url": "https://gitcode.com/pr/40"}
        result = self._full_run([_GOOD_SCRIPT], pr_existing=existing)
        self.assertEqual(result["created"], [])

    def test_repeated_failure_exits_non_zero(self) -> None:
        result = self._full_run([_BAD_SCRIPT] * 3)
        self.assertEqual(result["code"], 1)
        self.assertEqual(result["created"], [])


class MainTest(unittest.TestCase):
    def test_main_parses_item_json(self) -> None:
        with (
            mock.patch.object(
                testgen_generate, "run_generate", return_value=0
            ) as run,
            mock.patch.object(sys, "argv", ["prog", "--item", json.dumps(_ITEM)]),
        ):
            self.assertEqual(testgen_generate.main(), 0)
        run.assert_called_once_with(_ITEM)


if __name__ == "__main__":
    unittest.main()
