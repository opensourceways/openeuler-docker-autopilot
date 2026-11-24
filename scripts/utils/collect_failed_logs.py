#!/usr/bin/env python3
"""汇总本次运行里失败 job 的日志摘要，供 Issue 回写评论使用。

GitHub Actions 的失败细节只在网页日志里；把失败 job 的关键错误行摘出来
贴到 GitCode Issue 评论，处理人不必再翻整份运行日志。

只用标准库：finalize job 跑在 system python 上，不保证装了 requirements.txt。
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

_API_ROOT = "https://api.github.com"
_FAILED_CONCLUSIONS = {"failure", "cancelled", "timed_out"}
_MAX_JOBS = 6
_MAX_LINES_PER_JOB = 40
_MAX_CHARS_PER_JOB = 3000
_MAX_TOTAL_CHARS = 12000
_MAX_LINE_CHARS = 300
_TAIL_LINES = 20

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T[\d:.]+Z\s?")
# 明确的错误行优先；不够时再补 "failed/exit code" 之类的泛化行。
_STRONG_MARKERS = (
    "::error::",
    "##[error]",
    "traceback (most recent call last)",
    "modulenotfounderror",
    "importerror",
    "no such file or directory",
    "fatal:",
    "error:",
)
_WEAK_MARKERS = ("failed", "failure", "exit code")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _fetch(url: str, token: str, *, follow: bool = True, timeout: int = 60) -> bytes:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "openeuler-docker-autopilot",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    if follow:
        response = urllib.request.urlopen(request, timeout=timeout)
    else:
        response = urllib.request.build_opener(_NoRedirect).open(
            request, timeout=timeout
        )
    with response:
        data = response.read()
        if response.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
        return data


def list_failed_jobs(repo: str, run_id: str, token: str) -> list[dict]:
    failed: list[dict] = []
    page = 1
    while True:
        payload = json.loads(
            _fetch(
                f"{_API_ROOT}/repos/{repo}/actions/runs/{run_id}/jobs"
                f"?per_page=100&page={page}",
                token,
            )
        )
        jobs = payload.get("jobs") or []
        failed.extend(
            job for job in jobs if job.get("conclusion") in _FAILED_CONCLUSIONS
        )
        if len(jobs) < 100:
            return failed
        page += 1


def download_job_log(repo: str, job_id: int | str, token: str) -> str:
    """日志接口会 302 到签名地址；签名请求不能再带 Authorization。"""
    url = f"{_API_ROOT}/repos/{repo}/actions/jobs/{job_id}/logs"
    try:
        data = _fetch(url, token, follow=False)
    except urllib.error.HTTPError as error:
        location = error.headers.get("Location") if error.headers else None
        error.close()
        if error.code not in (301, 302, 303, 307, 308) or not location:
            raise
        data = _fetch(location, "", follow=True)
    return data.decode("utf-8", "replace")


def _clean(line: str) -> str:
    line = _ANSI_RE.sub("", line)
    line = _TIMESTAMP_RE.sub("", line)
    return line.rstrip()


def _matches(line: str, markers: tuple[str, ...]) -> bool:
    lowered = line.lower()
    return any(marker in lowered for marker in markers)


def excerpt(text: str) -> list[str]:
    """优先取明确错误行；一条都没有时退回日志末尾。"""
    lines = [line for line in (_clean(item) for item in text.splitlines()) if line]
    picked: list[str] = []
    seen: set[str] = set()
    for line in lines:
        if len(picked) >= _MAX_LINES_PER_JOB:
            break
        if line in seen or not _matches(line, _STRONG_MARKERS):
            continue
        seen.add(line)
        picked.append(line)
    if len(picked) < 15:
        for line in lines:
            if len(picked) >= _MAX_LINES_PER_JOB:
                break
            if line in seen or not _matches(line, _WEAK_MARKERS):
                continue
            seen.add(line)
            picked.append(line)
    if not picked:
        picked = lines[-_TAIL_LINES:]
    return [line[:_MAX_LINE_CHARS] for line in picked]


def _section(job: dict, lines: list[str], repo: str) -> str:
    name = job.get("name") or f"job {job.get('id')}"
    url = job.get("html_url") or f"https://github.com/{repo}"
    body = "\n".join(lines)
    if len(body) > _MAX_CHARS_PER_JOB:
        body = body[:_MAX_CHARS_PER_JOB] + "\n…（截断）"
    return f"### {name}\n\n{url}\n\n```text\n{body}\n```"


def collect(repo: str, run_id: str, token: str) -> str:
    sections: list[str] = []
    used = 0
    for job in list_failed_jobs(repo, run_id, token)[:_MAX_JOBS]:
        name = job.get("name") or f"job {job.get('id')}"
        try:
            lines = excerpt(download_job_log(repo, job["id"], token))
        except Exception as error:  # noqa: BLE001 - 单个 job 失败不影响其余摘要
            section = f"### {name}\n\n日志获取失败：{error}"
        else:
            section = _section(job, lines, repo)
        if used + len(section) > _MAX_TOTAL_CHARS:
            break
        sections.append(section)
        used += len(section)
    return "\n\n".join(sections)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", ""))
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""))
    parser.add_argument("--output", required=True, help="写入失败摘要的 markdown 文件")
    args = parser.parse_args(argv)

    if not args.repo or not args.run_id:
        raise SystemExit("repo and run-id are required")
    if not args.token:
        raise SystemExit("token is required")

    summary = collect(args.repo, args.run_id, args.token)
    Path(args.output).write_text(summary, encoding="utf-8")
    print(f"collected {len(summary)} chars into {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
