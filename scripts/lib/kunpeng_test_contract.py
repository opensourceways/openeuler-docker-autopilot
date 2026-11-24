"""KunpengTest functional-test script contract (scenario four).

Validates a generated ``test.sh`` against the KunpengTest rules documented at
https://github.com/opensourceways/upstream-dashboard/blob/KunpengTest/README.md
(the CI there runs the script via ``docker run --entrypoint bash`` with the
script directory mounted read-only at /tmp/eptest and five injected
environment variables).  All checks are static; the workflow never builds or
runs the image in scenario four.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

_LINT_TIMEOUT_SECONDS = 30

_REQUIRED_SHEBANG = "#!/bin/bash"

# `set -e` (and its -o errexit spelling) aborts the script on the first
# failed assertion, which distorts per-case PASS/FAIL output and the exit
# code.  KunpengTest 4.7 forbids it.  The option block is captured first
# and inspected separately so `set -o pipefail` (allowed) never matches.
_SET_OPTIONS_RE = re.compile(r"^\s*set\s+(-[A-Za-z]+)\b", re.MULTILINE)
_SET_ERREXIT_RE = re.compile(r"^\s*set\s+-o\s+errexit\b", re.MULTILINE)

# Function definitions: any name starting with `test` is parsed by the CI as a
# test case and must match test[A-Za-z0-9_]+ (KunpengTest 4.7).
_FUNC_DEF_RE = re.compile(
    r"^\s*(?:function\s+)?([A-Za-z_][A-Za-z0-9_-]*)\s*\(\)",
    re.MULTILINE,
)
_VALID_TEST_FUNC_RE = re.compile(r"^test[A-Za-z0-9_]+$")

# A manual `exit 0` bypasses the failure tally (convention A) or shUnit2's
# exit-code takeover (convention B).  The prompt requires plain `return`.
_EXIT_ZERO_RE = re.compile(r"^\s*exit\s+0\b", re.MULTILINE)

# The script must fail fast when the CI forgot EXPECTED_VERSION.
_VERSION_GUARD_RES = (
    re.compile(r"EXPECTED_VERSION:\?"),
    re.compile(r"-\s*z\s+\"?\$\{?EXPECTED_VERSION\b"),
    re.compile(r"-\s*n\s+\"?\$\{?EXPECTED_VERSION\b"),
)
_EXPECTED_VERSION_RE = re.compile(r"\bEXPECTED_VERSION\b")

# Convention A output: one PASS:/FAIL: line per case.
_PASS_LINE_RE = re.compile(r"\bPASS:\s")
_FAIL_LINE_RE = re.compile(r"\bFAIL:\s")

# The script runs *inside* the image under test; container lifecycle
# operations are forbidden (and pointless) there.
_DOCKER_RE = re.compile(
    r"\bdocker\s+(?:build|run|exec|stop|rm|pull|logs|start|restart|kill|create|ps)\b"
)

_MKTEMP_RE = re.compile(r"\bmktemp\b")
_TRAP_RE = re.compile(r"\btrap\b")

# 一个用例必须能失败：至少出现比较、grep/diff、case 或命令退出码判断。
# 只有 echo "PASS: ..." 的"测试"什么也证明不了，必须拦下。
_ASSERTION_RE = re.compile(
    r"(?m)(?:\[\[?[^\n]*\]\]?"
    r"|\btest\s+-?[A-Za-z0-9_$]"
    r"|\b(?:grep|egrep|fgrep|diff|cmp)\b"
    r"|\bcase\s+[^\n]+\s+in\b"
    r"|\bif\s+"
    r"|\|\|)"
)
# 只把 EXPECTED_VERSION 当必填守卫不算断言；它必须真的和软件输出比较。
_VERSION_GUARD_SUB_RE = re.compile(r"\$\{EXPECTED_VERSION:[^}]*\}")
_VERSION_COMPARISON_RE = re.compile(
    r"(?:==|!=|=~|-eq|-ne|-lt|-gt|-le|-ge|\bgrep\b|\bcase\b"
    r"|\[\[?[^\n]*\]\]?|\btest\s)"
)


class KunpengContractError(ValueError):
    """Raised when a generated test script violates the KunpengTest rules."""

    def __init__(
        self,
        message: str,
        *,
        findings: list[dict[str, str]] | None = None,
    ) -> None:
        super().__init__(message)
        self.findings = list(findings or ())


def _finding(code: str, message: str) -> dict[str, str]:
    return {
        "code": code,
        "level": "delivery_stop",
        "owner": "testgen_creator",
        "source": "kunpeng_test_protocol",
        "message": message,
        "check": "kunpeng_contract",
    }


_BASH_LINTER: str | None = None
_BASH_LINTER_CHECKED = False


def _bash_linter() -> str | None:
    """返回可用的 bash；WSL 等"存在但跑不动"的 bash 直接视为不可用。"""
    global _BASH_LINTER, _BASH_LINTER_CHECKED
    if _BASH_LINTER_CHECKED:
        return _BASH_LINTER
    _BASH_LINTER_CHECKED = True
    bash = shutil.which("bash")
    if bash is None:
        return None
    try:
        probe = subprocess.run(
            [bash, "-n", "-s"],
            input="if [ 1 = 1 ]; then :; fi\n",
            capture_output=True,
            text=True,
            timeout=_LINT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if probe.returncode != 0:
        return None
    _BASH_LINTER = bash
    return bash


def _lint_syntax(path: Path) -> str | None:
    """Return Bash's complaint about the script, or None when it parses."""
    bash = _bash_linter()
    if bash is None:
        return None
    try:
        # 走 stdin 而不是文件路径：Windows 上的 WSL bash 读不到 D:\... 路径，
        # 会误报 exit code 127。
        completed = subprocess.run(
            [bash, "-n", "-s"],
            input=path.read_text(encoding="utf-8", errors="replace"),
            capture_output=True,
            text=True,
            timeout=_LINT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode == 0:
        return None
    if completed.returncode == 127:
        # `bash` was found but could not be started (e.g. a WSL shim on
        # Windows); that says nothing about the script's syntax.
        return None
    detail = " ".join((completed.stderr or completed.stdout or "").split())
    return detail[:300] or f"exit code {completed.returncode}"


def _case_bodies(text: str) -> dict[str, str]:
    """按函数定义切出每个 test_* 的函数体（到下一个函数或 ^} 为止）。"""
    matches = list(_FUNC_DEF_RE.finditer(text))
    bodies: dict[str, str] = {}
    for index, match in enumerate(matches):
        name = match.group(1)
        if not _VALID_TEST_FUNC_RE.match(name):
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end():end]
        close = re.search(r"^\}", body, re.MULTILINE)
        if close:
            body = body[: close.start()]
        bodies[name] = body
    return bodies


def _asserts_expected_version(lines: list[str]) -> bool:
    """EXPECTED_VERSION 是否参与比较，而不只是必填守卫/赋值。"""
    for line in lines:
        if "EXPECTED_VERSION" not in line:
            continue
        stripped = _VERSION_GUARD_SUB_RE.sub("", line)
        if "EXPECTED_VERSION" not in stripped:
            continue
        if _VERSION_COMPARISON_RE.search(stripped):
            return True
    return False


def check_test_script(path: Path) -> list[dict[str, str]]:
    """Return delivery-stop findings for a KunpengTest ``test.sh``.

    An empty list means the script satisfies every statically checkable
    KunpengTest rule.
    """
    path = Path(path)
    findings: list[dict[str, str]] = []

    if not path.is_file():
        findings.append(_finding("kunpeng.missing", f"test script not found: {path}"))
        return findings
    if path.stat().st_size == 0:
        findings.append(_finding("kunpeng.empty", f"test script is empty: {path}"))
        return findings

    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    first_line = lines[0].strip() if lines else ""
    if first_line != _REQUIRED_SHEBANG:
        findings.append(
            _finding(
                "kunpeng.shebang",
                f"first line must be exactly {_REQUIRED_SHEBANG}, got: {first_line!r}",
            )
        )

    syntax_detail = _lint_syntax(path)
    if syntax_detail:
        findings.append(
            _finding("kunpeng.shell_syntax", f"not valid Bash: {syntax_detail}")
        )

    set_e_used = _SET_ERREXIT_RE.search(text) is not None
    for match in _SET_OPTIONS_RE.finditer(text):
        if "e" in match.group(1)[1:]:
            set_e_used = True
    if set_e_used:
        findings.append(
            _finding(
                "kunpeng.set_e",
                "set -e / set -o errexit is forbidden: it aborts on the first "
                "failed assertion and distorts PASS/FAIL output and the exit "
                "code (KunpengTest 4.7)",
            )
        )

    case_names: list[str] = []
    for match in _FUNC_DEF_RE.finditer(text):
        name = match.group(1)
        if not name.startswith("test"):
            continue
        if _VALID_TEST_FUNC_RE.match(name):
            case_names.append(name)
        else:
            findings.append(
                _finding(
                    "kunpeng.test_func_name",
                    f"function {name}() starts with 'test' but the CI only "
                    "recognises test[A-Za-z0-9_]+ names (KunpengTest 4.7)",
                )
            )
    if not case_names:
        findings.append(
            _finding(
                "kunpeng.no_test_case",
                "no test case function found: at least one "
                "test[A-Za-z0-9_]+ function is required so the report has "
                "test_cases",
            )
        )

    if not _EXPECTED_VERSION_RE.search(text):
        findings.append(
            _finding(
                "kunpeng.expected_version_missing",
                "EXPECTED_VERSION is never referenced: the CI injects it and "
                "the script must assert the exact version",
            )
        )
    elif not any(guard.search(text) for guard in _VERSION_GUARD_RES):
        findings.append(
            _finding(
                "kunpeng.expected_version_guard",
                "EXPECTED_VERSION must be guarded as required, e.g. "
                "\": ${EXPECTED_VERSION:?EXPECTED_VERSION is required}\" "
                "or a -z/-n check",
            )
        )
    if _EXPECTED_VERSION_RE.search(text) and not _asserts_expected_version(lines):
        findings.append(
            _finding(
                "kunpeng.expected_version_not_asserted",
                "EXPECTED_VERSION is only guarded, never compared with the "
                "actual software output: the test must assert the exact "
                "version, e.g. [ \"${out}\" = \"${EXPECTED_VERSION}\" ]",
            )
        )

    for name, body in _case_bodies(text).items():
        if not _ASSERTION_RE.search(body):
            findings.append(
                _finding(
                    "kunpeng.no_assertion",
                    f"{name}: no assertion that can fail (comparison, "
                    "grep/diff, case or command exit status); a case that "
                    "only echoes PASS does not prove functionality",
                )
            )

    if not _PASS_LINE_RE.search(text):
        findings.append(
            _finding(
                "kunpeng.pass_output_missing",
                "no 'PASS: ' line found: every test_xxx must output exactly "
                "one PASS: line on success (convention A)",
            )
        )
    if not _FAIL_LINE_RE.search(text):
        findings.append(
            _finding(
                "kunpeng.fail_output_missing",
                "no 'FAIL: ' line found: every test_xxx must output exactly "
                "one FAIL: line on failure (convention A)",
            )
        )

    if _EXIT_ZERO_RE.search(text):
        findings.append(
            _finding(
                "kunpeng.manual_exit_zero",
                "manual 'exit 0' is forbidden: use plain return from "
                "main/cases and let the last command decide the exit code",
            )
        )

    if _DOCKER_RE.search(text):
        findings.append(
            _finding(
                "kunpeng.docker_operations",
                "docker container lifecycle commands are forbidden inside "
                "test.sh (the script already runs inside the image under "
                "test)",
            )
        )

    if _MKTEMP_RE.search(text) and not _TRAP_RE.search(text):
        findings.append(
            _finding(
                "kunpeng.mktemp_without_trap",
                "mktemp is used without a trap cleanup: clean up temporary "
                "files on exit (KunpengTest 4.2)",
            )
        )

    # The executable bit does not exist on Windows filesystems, so the check
    # is Linux-only (the workflow always runs on Linux).
    if os.name != "nt" and not path.stat().st_mode & 0o111:
        findings.append(
            _finding(
                "kunpeng.not_executable",
                f"{path.name} must have the executable bit set",
            )
        )

    return findings
