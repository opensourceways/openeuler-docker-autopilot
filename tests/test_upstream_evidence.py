"""上游证据适配层单测（不联网）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.lib import upstream_evidence  # noqa: E402

_PAYLOAD = {
    "name": "ClickHouse",
    "tag": "v26.8.2.7-lts",
    "version": "26.8.2.7-lts",
    "tag_url": "https://github.com/ClickHouse/ClickHouse/releases/tag/v26.8.2.7-lts",
    "commit_sha": "9e2a54b1c8d4",
    "source": "latest_release",
    "fetched_at": "2026-09-20T15:30:00",
    "repo_url": "https://github.com/ClickHouse/ClickHouse",
    "blocked_reason": None,
    "upstream_evidence": [{"check": "source_archive", "ok": True}],
    "future_field": {"anything": 1},
}


class NormalizeTest(unittest.TestCase):
    def test_known_fields_are_structured_and_unknown_fields_pass_through(self) -> None:
        evidence = upstream_evidence.normalize(_PAYLOAD)

        self.assertEqual(evidence["tag"], "v26.8.2.7-lts")
        self.assertEqual(evidence["source"], "latest_release")
        self.assertEqual(evidence["fetched_at"], "2026-09-20T15:30:00")
        # 接口后续新增的字段原样保留，不需要改 workflow
        self.assertEqual(evidence["raw"]["future_field"], {"anything": 1})
        self.assertNotIn("upstream_evidence", evidence["raw"])

    def test_collector_entries_are_lifted(self) -> None:
        evidence = upstream_evidence.normalize(_PAYLOAD)
        self.assertEqual(evidence["collector"], [{"check": "source_archive", "ok": True}])

    def test_missing_payload_is_empty_evidence(self) -> None:
        evidence = upstream_evidence.normalize(None)
        self.assertIsNone(evidence["tag"])
        self.assertEqual(evidence["collector"], [])
        self.assertEqual(evidence["raw"], {})


class ProbeTest(unittest.TestCase):
    def test_probe_reports_ok_when_tag_and_archive_exist(self) -> None:
        with (
            mock.patch.object(upstream_evidence, "_github_get", return_value=200),
            mock.patch.object(upstream_evidence, "_github_head", return_value=200),
        ):
            result = upstream_evidence.probe(_PAYLOAD)

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["tag_exists"])
        self.assertTrue(result["release_exists"])
        self.assertEqual(
            result["archive_url"],
            "https://github.com/ClickHouse/ClickHouse/archive/refs/tags/"
            "v26.8.2.7-lts.tar.gz",
        )

    def test_probe_reports_partial_and_missing(self) -> None:
        with (
            mock.patch.object(upstream_evidence, "_github_get", return_value=200),
            mock.patch.object(upstream_evidence, "_github_head", return_value=404),
        ):
            self.assertEqual(upstream_evidence.probe(_PAYLOAD)["status"], "partial")

        with (
            mock.patch.object(upstream_evidence, "_github_get", return_value=404),
            mock.patch.object(upstream_evidence, "_github_head", return_value=404),
        ):
            self.assertEqual(upstream_evidence.probe(_PAYLOAD)["status"], "missing")

    def test_probe_skips_non_github_or_missing_tag(self) -> None:
        skipped = upstream_evidence.probe({"repo_url": "https://gitcode.com/a/b", "tag": "1.0"})
        self.assertEqual(skipped["status"], "skipped")

        no_tag = upstream_evidence.probe({"repo_url": "https://github.com/a/b"})
        self.assertEqual(no_tag["status"], "skipped")

    def test_probe_prefers_owner_repo_fields(self) -> None:
        with (
            mock.patch.object(upstream_evidence, "_github_get", return_value=200),
            mock.patch.object(upstream_evidence, "_github_head", return_value=200),
        ):
            result = upstream_evidence.probe(
                {"owner": "o", "repo": "r", "tag": "v1", "repo_url": ""}
            )
        self.assertIn("github.com/o/r", result["archive_url"])


class RenderTest(unittest.TestCase):
    def test_markdown_contains_provenance_and_probe(self) -> None:
        evidence = upstream_evidence.normalize(_PAYLOAD)
        evidence["probe"] = {"source": "self-probe", "status": "ok", "tag_exists": True}
        text = upstream_evidence.render_markdown(evidence)

        self.assertIn("## 上游证据", text)
        self.assertIn("v26.8.2.7-lts", text)
        self.assertIn("自探结果", text)
        self.assertIn("看板采集明细", text)
        self.assertIn("仅作参考", text)

    def test_prompt_is_compact_and_marks_reference_only(self) -> None:
        evidence = upstream_evidence.normalize(_PAYLOAD)
        evidence["probe"] = {"status": "ok"}
        text = upstream_evidence.render_prompt(evidence)

        self.assertIn("reference only", text)
        self.assertIn("v26.8.2.7-lts", text)

    def test_manual_evidence_lists_inputs_without_dashboard(self) -> None:
        evidence = {
            "source": "manual",
            "version": "2.17.0",
            "tag": "v2.17.0",
            "repo_url": "https://github.com/apache/kvrocks",
        }
        markdown = upstream_evidence.render_markdown(evidence)
        prompt = upstream_evidence.render_prompt(evidence)

        self.assertIn("## 升级来源", markdown)
        self.assertIn("v2.17.0", markdown)
        self.assertIn("https://github.com/apache/kvrocks", markdown)
        self.assertNotIn("看板采集", markdown)
        self.assertIn("provided manually", prompt)
        self.assertIn("2.17.0", prompt)
        self.assertNotIn("Dashboard checks", prompt)

    def test_prompt_renders_each_dashboard_check(self) -> None:
        payload = dict(
            _PAYLOAD,
            upstream_evidence=[
                {
                    "check_id": "kp.l1.release_artifact",
                    "result": "not_found",
                    "excerpt": "release 只有源码包，无 arm64 资产",
                    "source_url": "https://github.com/nginx/nginx/releases/tag/release-1.31.8",
                }
            ],
        )
        text = upstream_evidence.render_prompt(upstream_evidence.normalize(payload))

        self.assertIn("Dashboard checks (1 entries", text)
        self.assertIn("kp.l1.release_artifact", text)
        self.assertIn("release 只有源码包，无 arm64 资产", text)
        self.assertIn("https://github.com/nginx/nginx/releases/tag/release-1.31.8", text)
