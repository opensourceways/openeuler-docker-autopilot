"""每个应用的升级注意点文档（config/app-notes）单测。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.lib import app_notes  # noqa: E402


class AppNotesTest(unittest.TestCase):
    def test_missing_document_is_not_an_error(self) -> None:
        self.assertIsNone(app_notes.load("no-such-app-xyz"))
        self.assertEqual(app_notes.render_prompt(None), "")

    def test_document_body_and_overrides_are_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            notes_dir = Path(tmp)
            (notes_dir / "demo.md").write_text(
                "---\n"
                "app: demo\n"
                "build_timeout_minutes: 300\n"
                "generate_timeout_minutes: 120\n"
                "---\n"
                "# demo\n\n"
                "构建很慢。\n",
                encoding="utf-8",
            )
            with mock.patch.object(app_notes, "NOTES_DIR", notes_dir):
                notes = app_notes.load("demo")
                rendered = app_notes.render_prompt(notes)

        self.assertIsNotNone(notes)
        assert notes is not None
        self.assertEqual(notes.build_timeout_minutes, 300)
        self.assertEqual(notes.generate_timeout_minutes, 120)
        self.assertEqual(notes.prepare_timeout_minutes, 360)
        self.assertNotIn("build_timeout_minutes", notes.body)
        self.assertIn("构建很慢", rendered)
        self.assertIn("config/app-notes/demo.md", rendered)
        self.assertEqual(app_notes.generate_timeout_seconds(notes), 7200)

    def test_document_without_front_matter_is_still_rendered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            notes_dir = Path(tmp)
            (notes_dir / "plain.md").write_text("# 标题\n正文\n", encoding="utf-8")
            with mock.patch.object(app_notes, "NOTES_DIR", notes_dir):
                notes = app_notes.load("plain")

        assert notes is not None
        self.assertIsNone(notes.build_timeout_minutes)
        self.assertIsNone(notes.prepare_timeout_minutes)
        self.assertIn("正文", app_notes.render_prompt(notes))

    def test_real_milvus_note_extends_the_build_budget(self) -> None:
        notes = app_notes.load("milvus")
        assert notes is not None
        self.assertEqual(notes.build_timeout_minutes, 300)
        self.assertEqual(notes.generate_timeout_minutes, 180)
        self.assertEqual(notes.prepare_timeout_minutes, 360)

    def test_merge_auto_note_preserves_human_content(self) -> None:
        existing = (
            "---\n"
            "build_timeout_minutes: 300\n"
            "---\n"
            "# demo\n\n"
            "人工经验：先确认下载 URL。\n"
        )

        merged = app_notes.merge_auto_note(
            existing,
            version="2.17.0",
            os_version="24.03-lts-sp4",
            note="构建约 40 分钟；保留 boost。",
        )

        self.assertIn("build_timeout_minutes: 300", merged)
        self.assertIn("人工经验：先确认下载 URL。", merged)
        self.assertIn("## 自动沉淀：2.17.0 / 24.03-lts-sp4", merged)
        self.assertIn("构建约 40 分钟；保留 boost。", merged)

    def test_merge_auto_note_replaces_the_same_version_without_duplicates(self) -> None:
        first = app_notes.merge_auto_note(
            "# demo\n",
            version="2.17.0",
            os_version="24.03-lts-sp4",
            note="第一版经验。",
        )
        second = app_notes.merge_auto_note(
            first,
            version="2.17.0",
            os_version="24.03-lts-sp4",
            note="修正后的经验。",
        )

        self.assertEqual(second.count("## 自动沉淀"), 1)
        self.assertNotIn("第一版经验", second)
        self.assertIn("修正后的经验", second)
        self.assertIn("# demo", second)

    def test_merge_auto_note_keeps_other_versions(self) -> None:
        first = app_notes.merge_auto_note(
            "# demo\n",
            version="2.17.0",
            os_version="24.03-lts-sp4",
            note="旧版本经验。",
        )
        second = app_notes.merge_auto_note(
            first,
            version="2.18.0",
            os_version="24.03-lts-sp4",
            note="新版本经验。",
        )

        self.assertEqual(second.count("## 自动沉淀"), 2)
        self.assertIn("旧版本经验", second)
        self.assertIn("新版本经验", second)

    def test_merge_auto_note_keeps_human_content_after_the_section(self) -> None:
        first = app_notes.merge_auto_note(
            "# demo\n",
            version="2.17.0",
            os_version="24.03-lts-sp4",
            note="第一版经验。",
        )
        with_human = first + "\n人工补充：构建机需要额外 20G 磁盘。\n"
        second = app_notes.merge_auto_note(
            with_human,
            version="2.17.0",
            os_version="24.03-lts-sp4",
            note="修正后的经验。",
        )

        self.assertIn("修正后的经验", second)
        self.assertNotIn("第一版经验", second)
        self.assertIn("人工补充：构建机需要额外 20G 磁盘。", second)

    def test_merge_auto_note_rejects_front_matter(self) -> None:
        with self.assertRaises(ValueError):
            app_notes.merge_auto_note(
                "# demo\n",
                version="2.17.0",
                os_version="24.03-lts-sp4",
                note="---\napp: demo\n---\n正文",
            )

    def test_write_auto_note_skips_unchanged_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            notes_dir = Path(tmp)
            path = app_notes.write_auto_note(
                app="demo",
                version="2.17.0",
                os_version="24.03-lts-sp4",
                note="构建约 40 分钟。",
                notes_dir=notes_dir,
            )
            self.assertIsNotNone(path)
            assert path is not None
            self.assertIn("构建约 40 分钟", path.read_text(encoding="utf-8"))

            again = app_notes.write_auto_note(
                app="demo",
                version="2.17.0",
                os_version="24.03-lts-sp4",
                note="构建约 40 分钟。",
                notes_dir=notes_dir,
            )
            self.assertIsNone(again)

    def test_save_note_text_ignores_empty_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "note.md"
            self.assertIsNone(app_notes.save_note_text(path, "  "))
            self.assertFalse(path.exists())
            self.assertIsNone(app_notes.save_note_text(None, "内容"))
            self.assertIsNotNone(app_notes.save_note_text(path, "内容"))
            self.assertEqual(path.read_text(encoding="utf-8"), "内容\n")


if __name__ == "__main__":
    unittest.main()
