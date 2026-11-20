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


if __name__ == "__main__":
    unittest.main()
