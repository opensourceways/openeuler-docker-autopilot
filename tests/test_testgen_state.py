"""Tests for the scenario-four cross-round state markers."""

from __future__ import annotations

import unittest
from unittest import mock

from scripts.lib import testgen_state


class TestgenStateTest(unittest.TestCase):
    def test_done_roundtrip(self) -> None:
        with (
            mock.patch.object(testgen_state.ci_data, "read_file") as read,
            mock.patch.object(testgen_state.ci_data, "write_file") as write,
        ):
            read.return_value = "https://gitcode.com/openeuler/openeuler-docker-images/pulls/12"
            self.assertTrue(testgen_state.is_done("kvrocks"))
            self.assertEqual(
                testgen_state.done_pr_url("kvrocks"),
                "https://gitcode.com/openeuler/openeuler-docker-images/pulls/12",
            )
            testgen_state.mark_done("kvrocks", "https://example.com/pr/12")
            write.assert_called_once_with(
                "testgen-log/kvrocks/done",
                "https://example.com/pr/12",
                "testgen: mark kvrocks done (https://example.com/pr/12)",
                branch=testgen_state.TESTGEN_BRANCH,
            )

    def test_empty_marker_means_not_done(self) -> None:
        with mock.patch.object(testgen_state.ci_data, "read_file") as read:
            read.return_value = ""
            self.assertFalse(testgen_state.is_done("kvrocks"))
            self.assertFalse(testgen_state.is_exhausted("kvrocks"))

    def test_exhausted_roundtrip(self) -> None:
        with (
            mock.patch.object(testgen_state.ci_data, "read_file") as read,
            mock.patch.object(testgen_state.ci_data, "write_file") as write,
        ):
            read.return_value = "kunpeng.set_e: set -e is forbidden"
            self.assertTrue(testgen_state.is_exhausted("gulp"))
            testgen_state.mark_exhausted("gulp", "kunpeng.set_e: set -e is forbidden")
            write.assert_called_once_with(
                "testgen-log/gulp/exhausted",
                "kunpeng.set_e: set -e is forbidden",
                "testgen: mark gulp exhausted",
                branch=testgen_state.TESTGEN_BRANCH,
            )

    def test_reads_use_testgen_branch(self) -> None:
        with mock.patch.object(testgen_state.ci_data, "read_file") as read:
            read.return_value = ""
            testgen_state.is_done("kvrocks")
            testgen_state.is_exhausted("kvrocks")
            for call in read.call_args_list:
                self.assertEqual(call.kwargs.get("branch"), testgen_state.TESTGEN_BRANCH)
                self.assertTrue(call.args[0].startswith("testgen-log/kvrocks/"))

    def test_invalid_app_name_rejected(self) -> None:
        with self.assertRaises(ValueError):
            testgen_state.is_done("../escape")
        with self.assertRaises(ValueError):
            testgen_state.mark_done("with space", "url")


if __name__ == "__main__":
    unittest.main()
