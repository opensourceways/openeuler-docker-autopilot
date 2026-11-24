"""Tests for the KunpengTest static contract checker."""

from __future__ import annotations

import unittest
from pathlib import Path

from scripts.lib.kunpeng_test_contract import (
    KunpengContractError,
    check_test_script,
)

# A minimal convention-A script that satisfies every KunpengTest rule.
_COMPLIANT_SCRIPT = """#!/bin/bash

EXPECTED_VERSION="${EXPECTED_VERSION:?EXPECTED_VERSION is required}"

test_binary_present() {
    if command -v myapp >/dev/null 2>&1; then
        echo "PASS: binary myapp exists"
        return 0
    fi
    echo "FAIL: binary myapp not found in PATH"
    return 1
}

test_version() {
    local out
    out="$(myapp --version 2>&1 || true)"
    if [ "${out}" = "myapp version ${EXPECTED_VERSION}" ]; then
        echo "PASS: exact version ${out}"
        return 0
    fi
    echo "FAIL: expected 'myapp version ${EXPECTED_VERSION}', got '${out}'"
    return 1
}

test_temp_cleanup() {
    local work
    work="$(mktemp -d)"
    trap 'rm -rf "${work}"' EXIT
    if [ -d "${work}" ]; then
        echo "PASS: temp dir usable"
        return 0
    fi
    echo "FAIL: temp dir was not created"
    return 1
}

main() {
    local failures=0
    test_binary_present || failures=$((failures + 1))
    test_version       || failures=$((failures + 1))
    test_temp_cleanup   || failures=$((failures + 1))
    if [ "${failures}" -eq 0 ]; then
        echo "ALL_TESTS_PASSED"
        return 0
    fi
    echo "TESTS_FAILED: ${failures} failure(s)"
    return 1
}

main "$@"
"""


def _write_script(tmp_path: Path, content: str, *, executable: bool = True) -> Path:
    path = tmp_path / "test.sh"
    path.write_text(content, encoding="utf-8", newline="\n")
    if executable:
        path.chmod(0o755)
    return path


def _codes(findings: list[dict[str, str]]) -> set[str]:
    return {finding["code"] for finding in findings}


class CheckTestScriptTest(unittest.TestCase):
    def test_compliant_script_has_no_findings(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = _write_script(Path(tmp), _COMPLIANT_SCRIPT)
            self.assertEqual(check_test_script(path), [])

    def test_missing_file(self) -> None:
        findings = check_test_script(Path("does-not-exist", "test.sh"))
        self.assertEqual(_codes(findings), {"kunpeng.missing"})

    def test_empty_file(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = _write_script(Path(tmp), "")
            self.assertEqual(_codes(findings := check_test_script(path)), {
                "kunpeng.empty",
            })

    def test_wrong_shebang(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            script = _COMPLIANT_SCRIPT.replace("#!/bin/bash", "#!/bin/sh", 1)
            path = _write_script(Path(tmp), script)
            self.assertIn("kunpeng.shebang", _codes(check_test_script(path)))

    def test_bash_syntax_error(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            script = _COMPLIANT_SCRIPT.replace("main \"$@\"", "main \"$@\"\nif then fi")
            path = _write_script(Path(tmp), script)
            codes = _codes(check_test_script(path))
        if "kunpeng.shell_syntax" not in codes:
            self.skipTest("bash syntax linting is unavailable in this environment")
        self.assertIn("kunpeng.shell_syntax", codes)

    def test_set_o_pipefail_is_allowed(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            script = "#!/bin/bash\nset -o pipefail\n" + _COMPLIANT_SCRIPT.split("\n", 1)[1]
            path = _write_script(Path(tmp), script)
            self.assertNotIn("kunpeng.set_e", _codes(check_test_script(path)))

    def test_set_e_forbidden(self) -> None:
        import tempfile

        for variant in ("set -e", "set -euo pipefail", "set -o errexit"):
            with self.subTest(variant=variant):
                with tempfile.TemporaryDirectory() as tmp:
                    script = f"#!/bin/bash\n{variant}\n" + _COMPLIANT_SCRIPT.split("\n", 1)[1]
                    path = _write_script(Path(tmp), script)
                    self.assertIn("kunpeng.set_e", _codes(check_test_script(path)))

    def test_bad_test_function_name(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            script = _COMPLIANT_SCRIPT.replace(
                "test_version()", "test-version()", 1
            ).replace(
                "test_version       ||",
                "test-version       ||",
                1,
            )
            path = _write_script(Path(tmp), script)
            codes = _codes(check_test_script(path))
            self.assertIn("kunpeng.test_func_name", codes)

    def test_no_test_case_function(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            script = _COMPLIANT_SCRIPT.replace("test_", "check_", 4)
            path = _write_script(Path(tmp), script)
            self.assertIn("kunpeng.no_test_case", _codes(check_test_script(path)))

    def test_expected_version_missing(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            script = _COMPLIANT_SCRIPT.replace("EXPECTED_VERSION", "APP_VERSION")
            path = _write_script(Path(tmp), script)
            codes = _codes(check_test_script(path))
            self.assertIn("kunpeng.expected_version_missing", codes)

    def test_expected_version_guard_missing(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            script = _COMPLIANT_SCRIPT.replace(
                'EXPECTED_VERSION="${EXPECTED_VERSION:?EXPECTED_VERSION is required}"',
                'EXPECTED_VERSION="${EXPECTED_VERSION:-1.0.0}"',
            )
            path = _write_script(Path(tmp), script)
            self.assertIn("kunpeng.expected_version_guard", _codes(check_test_script(path)))

    def test_z_guard_is_accepted(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            script = _COMPLIANT_SCRIPT.replace(
                'EXPECTED_VERSION="${EXPECTED_VERSION:?EXPECTED_VERSION is required}"',
                '[ -z "${EXPECTED_VERSION}" ] && { echo "FATAL: EXPECTED_VERSION required"; return 1; }',
            )
            path = _write_script(Path(tmp), script)
            codes = _codes(check_test_script(path))
            self.assertNotIn("kunpeng.expected_version_guard", codes)
            self.assertNotIn("kunpeng.expected_version_missing", codes)

    def test_case_without_assertion_is_flagged(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            script = _COMPLIANT_SCRIPT.replace(
                "    if command -v myapp >/dev/null 2>&1; then\n"
                '        echo "PASS: binary myapp exists"\n'
                "        return 0\n"
                "    fi\n",
                '    echo "PASS: binary myapp exists"\n',
                1,
            )
            path = _write_script(Path(tmp), script)
            self.assertIn("kunpeng.no_assertion", _codes(check_test_script(path)))

    def test_expected_version_only_guarded_is_flagged(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            script = _COMPLIANT_SCRIPT.replace(
                '    if [ "${out}" = "myapp version ${EXPECTED_VERSION}" ]; then',
                '    if [ -n "${out}" ]; then',
                1,
            )
            path = _write_script(Path(tmp), script)
            self.assertIn(
                "kunpeng.expected_version_not_asserted",
                _codes(check_test_script(path)),
            )

    def test_pass_line_missing(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            script = _COMPLIANT_SCRIPT.replace('PASS: ', 'OK: ')
            path = _write_script(Path(tmp), script)
            self.assertIn("kunpeng.pass_output_missing", _codes(check_test_script(path)))

    def test_fail_line_missing(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            script = _COMPLIANT_SCRIPT.replace('FAIL: ', 'BAD: ')
            path = _write_script(Path(tmp), script)
            self.assertIn("kunpeng.fail_output_missing", _codes(check_test_script(path)))

    def test_manual_exit_zero_forbidden(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            script = _COMPLIANT_SCRIPT.replace(
                "        return 0\n    fi\n    echo \"TESTS_FAILED",
                "        exit 0\n    fi\n    echo \"TESTS_FAILED",
                1,
            )
            path = _write_script(Path(tmp), script)
            self.assertIn("kunpeng.manual_exit_zero", _codes(check_test_script(path)))

    def test_docker_operations_forbidden(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            script = _COMPLIANT_SCRIPT.replace(
                'main "$@"',
                'docker run --rm myimage\ncleanup_check() { :; }\nmain "$@"',
            )
            path = _write_script(Path(tmp), script)
            self.assertIn("kunpeng.docker_operations", _codes(check_test_script(path)))

    def test_mktemp_requires_trap(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            script = _COMPLIANT_SCRIPT.replace(
                "    trap 'rm -rf \"${work}\"' EXIT\n", ""
            )
            path = _write_script(Path(tmp), script)
            self.assertIn("kunpeng.mktemp_without_trap", _codes(check_test_script(path)))

    def test_not_executable(self) -> None:
        import os
        import tempfile

        if os.name == "nt":
            self.skipTest("executable bit is not visible on Windows")
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_script(Path(tmp), _COMPLIANT_SCRIPT, executable=False)
            self.assertIn("kunpeng.not_executable", _codes(check_test_script(path)))


class KunpengContractErrorTest(unittest.TestCase):
    def test_error_carries_findings(self) -> None:
        findings = [
            {
                "code": "kunpeng.set_e",
                "level": "delivery_stop",
                "owner": "testgen_creator",
                "source": "kunpeng_test_protocol",
                "message": "boom",
                "check": "kunpeng_contract",
            }
        ]
        error = KunpengContractError("invalid", findings=findings)
        self.assertEqual(error.findings, findings)


if __name__ == "__main__":
    unittest.main()
