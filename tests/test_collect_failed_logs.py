"""失败日志摘要收集单测（不联网）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.utils import collect_failed_logs as logs  # noqa: E402


def test_excerpt_strips_ansi_timestamps_and_keeps_error_lines():
    text = (
        "\x1b[36;1m2026-11-24T12:35:05.2773059Z \x1b[0mRunning build\n"
        "2026-11-24T12:35:05.2773059Z Traceback (most recent call last):\n"
        '2026-11-24T12:35:05.2773059Z   File "flow.py", line 18, in <module>\n'
        "2026-11-24T12:35:05.2773059Z ModuleNotFoundError: "
        "No module named 'requests'\n"
        "2026-11-24T12:35:05.2773059Z ##[error]Process completed with exit code 1.\n"
    )

    lines = logs.excerpt(text)

    assert lines[0] == "Traceback (most recent call last):"
    assert any("ModuleNotFoundError" in line for line in lines)
    assert any(line.startswith("##[error]") for line in lines)
    assert all("2026-11-24T" not in line for line in lines)


def test_excerpt_falls_back_to_the_log_tail_without_error_markers():
    lines = logs.excerpt("\n".join(f"line {index}" for index in range(50)))

    assert lines == [f"line {index}" for index in range(30, 50)]


def test_excerpt_caps_very_long_lines():
    lines = logs.excerpt("error: " + "x" * 1000)

    assert len(lines[0]) == logs._MAX_LINE_CHARS


def test_collect_renders_one_section_per_failed_job(monkeypatch):
    monkeypatch.setattr(
        logs,
        "list_failed_jobs",
        lambda repo, run_id, token: [
            {
                "id": 1,
                "name": "Upgrade folly / Validate x86_64",
                "html_url": "https://github.com/o/r/actions/runs/9/job/1",
            }
        ],
    )
    monkeypatch.setattr(
        logs,
        "download_job_log",
        lambda repo, job_id, token: "2026-11-24T00:00:00.0Z ##[error]boom\n",
    )

    text = logs.collect("o/r", "9", "token")

    assert text.startswith("**Upgrade folly / Validate x86_64**")
    assert "https://github.com/o/r/actions/runs/9/job/1" in text
    assert "##[error]boom" in text


def test_collect_survives_a_job_whose_log_cannot_be_downloaded(monkeypatch):
    monkeypatch.setattr(
        logs,
        "list_failed_jobs",
        lambda repo, run_id, token: [
            {"id": 1, "name": "broken", "html_url": "u1"},
            {"id": 2, "name": "ok", "html_url": "u2"},
        ],
    )

    def fake_download(repo, job_id, token):
        if job_id == 1:
            raise RuntimeError("404")
        return "error: real failure\n"

    monkeypatch.setattr(logs, "download_job_log", fake_download)

    text = logs.collect("o/r", "9", "token")

    assert "日志获取失败" in text
    assert "**ok**" in text
