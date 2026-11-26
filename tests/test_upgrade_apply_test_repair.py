import subprocess
from pathlib import Path

import pytest

from scripts.harness import upgrade_apply
from scripts.lib import version_upgrade
from test_kunpeng_test_contract import _COMPLIANT_SCRIPT

BROKEN_SCRIPT = """#!/bin/bash

EXPECTED_VERSION="${EXPECTED_VERSION:?EXPECTED_VERSION is required}"

test_binary_present() {
    if command -v echo >/dev/null 2>&1; then
        echo "PASS: binary present"
        return 0
    fi
    echo "FAIL: binary missing"
    return 1
}

main() {
    local failures=0
    test_binary_present || failures=$((failures + 1))
    if [ "${failures}" -eq 0 ]; then
        echo "ALL_TESTS_PASSED"
        return 0
    fi
    echo "TESTS_FAILED: ${failures} failure(s)"
    return 1
}

main "$@"
"""


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    test_path = repo / "Cloud" / "eino" / "tests" / "test.sh"
    test_path.parent.mkdir(parents=True)
    test_path.write_text(BROKEN_SCRIPT, encoding="utf-8", newline="\n")
    test_path.chmod(0o755)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fixture")
    return repo, test_path


def _plan(repo: Path) -> version_upgrade.UpgradePlan:
    return version_upgrade.UpgradePlan(
        old_version="0.9.22",
        os_version="24.03-lts-sp4",
        src_dir=repo,
    )


def _enable_agent(monkeypatch) -> None:
    monkeypatch.setattr(upgrade_apply.ai_provider, "api_key", lambda: "key")
    monkeypatch.setattr(
        upgrade_apply.shutil, "which", lambda name: "/usr/bin/opencode"
    )


def test_repairs_existing_test_script_with_agent(tmp_path: Path, monkeypatch) -> None:
    repo, test_path = _repo(tmp_path)
    _enable_agent(monkeypatch)
    calls: dict = {}

    def fake_run_agent(**kwargs):
        calls.update(kwargs)
        test_path.write_text(_COMPLIANT_SCRIPT, encoding="utf-8")
        test_path.chmod(0o755)
        # 越界改动必须被还原。
        (repo / "Cloud" / "eino" / "stray.txt").write_text("x", encoding="utf-8")

    monkeypatch.setattr(upgrade_apply, "run_agent", fake_run_agent)

    status = upgrade_apply._ensure_test_script(
        repo_dir=repo,
        app="eino",
        domain="Cloud",
        plan=_plan(repo),
        item={"version": "0.9.23"},
    )

    assert status == "existing-repaired"
    assert calls["role"] == "testgen_creator"
    assert "EXPECTED_VERSION" in calls["prompt"]
    assert not (repo / "Cloud" / "eino" / "stray.txt").exists()


def test_failed_repair_restores_original_script(tmp_path: Path, monkeypatch) -> None:
    repo, test_path = _repo(tmp_path)
    _enable_agent(monkeypatch)
    monkeypatch.setattr(upgrade_apply, "run_agent", lambda **kwargs: None)

    with pytest.raises(version_upgrade.UpgradeError):
        upgrade_apply._ensure_test_script(
            repo_dir=repo,
            app="eino",
            domain="Cloud",
            plan=_plan(repo),
            item={"version": "0.9.23"},
        )

    assert test_path.read_text(encoding="utf-8") == BROKEN_SCRIPT


def test_compliant_script_is_reused_without_agent(tmp_path: Path, monkeypatch) -> None:
    repo, test_path = _repo(tmp_path)
    test_path.write_text(_COMPLIANT_SCRIPT, encoding="utf-8")
    test_path.chmod(0o755)
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "compliant")

    def fail_run_agent(**kwargs):
        raise AssertionError("agent must not run for a compliant script")

    monkeypatch.setattr(upgrade_apply, "run_agent", fail_run_agent)

    status = upgrade_apply._ensure_test_script(
        repo_dir=repo,
        app="eino",
        domain="Cloud",
        plan=_plan(repo),
        item={"version": "0.9.23"},
    )
    assert status == "existing"
