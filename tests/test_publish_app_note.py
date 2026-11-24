"""把 Agent 总结的 app note 发布成本仓 PR 的单测（不联网、不真实 git）。"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.harness import publish_app_note  # noqa: E402


class PublishAppNoteTest(unittest.TestCase):
    def _publish(self, workspace: Path, note: str) -> tuple[str, list, dict]:
        calls: list = []
        opened: dict = {}

        def fake_git(_workspace, *args, check=True):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, "", "")

        def fake_open_pr(**kwargs):
            opened.update(kwargs)
            return "https://github.com/example/repo/pull/7"

        with (
            mock.patch.object(publish_app_note, "_git", fake_git),
            mock.patch.object(publish_app_note, "_open_pr", fake_open_pr),
        ):
            url = publish_app_note.publish(
                app="demo",
                version="2.17.0",
                os_version="24.03-lts-sp4",
                note=note,
                workspace=workspace,
                repo="example/repo",
                token="token",
                base="main",
                branch="auto/app-note/demo",
            )
        return url, calls, opened

    def test_note_is_merged_into_an_existing_file_and_pr_opened(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            notes_dir = workspace / "config" / "app-notes"
            notes_dir.mkdir(parents=True)
            (notes_dir / "demo.md").write_text(
                "# demo\n\n人工经验：先确认下载 URL。\n", encoding="utf-8"
            )

            url, calls, opened = self._publish(
                workspace, "构建约 40 分钟；保留 boost。"
            )

            content = (notes_dir / "demo.md").read_text(encoding="utf-8")
            self.assertIn("人工经验：先确认下载 URL", content)
            self.assertIn("## 自动沉淀：2.17.0 / 24.03-lts-sp4", content)
            self.assertIn("构建约 40 分钟", content)
            self.assertTrue(any("commit" in call for call in calls))
            self.assertTrue(
                any("push" in call for call in calls)
            )
            self.assertEqual(
                opened["branch"], "auto/app-note/demo"
            )
            self.assertEqual(url, "https://github.com/example/repo/pull/7")

    def test_unchanged_note_does_not_open_a_pr(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            notes_dir = workspace / "config" / "app-notes"
            notes_dir.mkdir(parents=True)
            existing = (
                "# demo\n\n"
                "<!-- oe-app-note:auto:2.17.0/24.03-lts-sp4 -->\n"
                "## 自动沉淀：2.17.0 / 24.03-lts-sp4\n\n"
                "构建约 40 分钟。\n"
                "<!-- /oe-app-note:auto -->\n"
            )
            (notes_dir / "demo.md").write_text(existing, encoding="utf-8")

            url, calls, opened = self._publish(workspace, "构建约 40 分钟。")

            self.assertEqual(url, "")
            self.assertEqual(opened, {})
            self.assertFalse(any("commit" in call for call in calls))


class PublishAppNoteGitTest(unittest.TestCase):
    """用本地 bare 仓库验证 fetch / commit / push 分支的真实行为。"""

    def _run(self, *args, cwd: Path) -> None:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if completed.returncode != 0:
            self.fail(f"git {' '.join(args)} failed: {completed.stderr}")

    def test_publish_pushes_a_branch_that_accumulates_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            origin = root / "origin.git"
            self._run("init", "--bare", str(origin), cwd=root)

            seed = root / "seed"
            self._run("clone", f"file://{origin}", str(seed), cwd=root)
            self._run("checkout", "-b", "main", cwd=seed)
            self._run("config", "user.name", "t", cwd=seed)
            self._run("config", "user.email", "t@example.com", cwd=seed)
            notes = seed / "config" / "app-notes"
            notes.mkdir(parents=True)
            (notes / "demo.md").write_text(
                "# demo\n\n人工经验：先确认下载 URL。\n", encoding="utf-8"
            )
            self._run("add", "-A", cwd=seed)
            self._run("commit", "-m", "seed", cwd=seed)
            self._run("push", "origin", "main", cwd=seed)

            workspace = root / "workspace"
            self._run("clone", f"file://{origin}", str(workspace), cwd=root)
            self._run("config", "user.name", "t", cwd=workspace)
            self._run("config", "user.email", "t@example.com", cwd=workspace)

            opened: list[dict] = []

            def fake_open_pr(**kwargs):
                opened.append(kwargs)
                return "https://github.com/example/repo/pull/9"

            def publish(note: str) -> str:
                with mock.patch.object(publish_app_note, "_open_pr", fake_open_pr):
                    return publish_app_note.publish(
                        app="demo",
                        version="2.17.0",
                        os_version="24.03-lts-sp4",
                        note=note,
                        workspace=workspace,
                        repo="example/repo",
                        token="token",
                        base="main",
                        branch="auto/app-note/demo",
                    )

            first = publish("构建约 40 分钟。")
            second = publish("构建约 45 分钟；保留 boost。")

            self.assertEqual(first, "https://github.com/example/repo/pull/9")
            self.assertEqual(second, "https://github.com/example/repo/pull/9")
            self.assertEqual(len(opened), 2)

            check = root / "check"
            self._run(
                "clone", "--branch", "auto/app-note/demo",
                f"file://{origin}", str(check), cwd=root,
            )
            content = (check / "config" / "app-notes" / "demo.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("人工经验：先确认下载 URL", content)
            self.assertIn("构建约 45 分钟；保留 boost。", content)
            self.assertNotIn("构建约 40 分钟。", content)
            self.assertEqual(content.count("## 自动沉淀"), 1)


if __name__ == "__main__":
    unittest.main()
