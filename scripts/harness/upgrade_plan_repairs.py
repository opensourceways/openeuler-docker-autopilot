#!/usr/bin/env python3
"""为一次失败的升级运行生成自动 repair 矩阵（场景二）。

只挑「双架构原生验证」失败的应用：``_upgrade_app.yml`` 的 job 名形如
``Upgrade <app> / Validate x86_64``；prepare 失败（分支没推上去）不自动
repair，避免在没有分支时白跑一轮。

jobs 来源二选一：

- ``--repo`` + ``--run-id`` + ``GITHUB_TOKEN``：直接查 Actions jobs API；
- ``--jobs``：读取已有的 jobs JSON（离线单测）。

输出写入 ``GITHUB_OUTPUT``：``count`` / ``apps`` / ``matrix``，
``matrix`` 可直接喂给 ``_upgrade_app.yml`` 的 repair 模式。
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterable, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib import app_notes  # noqa: E402

_JOB_NAME = re.compile(r"^Upgrade (?P<app>[^/]+?) / (?P<step>.+)$")
# 目标仓目录名：不允许空格与斜杠，避免拼进 artifact 名称/路径时产生歧义。
_APP_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_VALIDATION_JOB_PREFIX = "Validate "
_API = "https://api.github.com"


def select_failed_apps(jobs: Iterable[Mapping[str, object]]) -> list[str]:
    """返回 validation job 失败的 app（去重排序）。"""
    apps: set[str] = set()
    for job in jobs:
        match = _JOB_NAME.match(str(job.get("name") or ""))
        if match is None:
            continue
        if not match.group("step").startswith(_VALIDATION_JOB_PREFIX):
            continue
        if job.get("conclusion") != "failure":
            continue
        app = match.group("app")
        if _APP_NAME.fullmatch(app):
            apps.add(app)
    return sorted(apps)


def build_matrix(apps: Iterable[str], instructions: str) -> dict[str, list[dict[str, object]]]:
    include: list[dict[str, object]] = []
    for app in sorted(apps):
        entry: dict[str, object] = {"app": app, "instructions": instructions}
        notes = app_notes.load(app)
        if notes is not None:
            if notes.build_timeout_minutes:
                entry["build_timeout_minutes"] = notes.build_timeout_minutes
            if notes.prepare_timeout_minutes:
                entry["prepare_timeout_minutes"] = notes.prepare_timeout_minutes
        include.append(entry)
    return {"include": include}


def fetch_jobs(*, repo: str, run_id: str, token: str) -> list[dict[str, object]]:
    """分页读取一次运行的 jobs。"""
    jobs: list[dict[str, object]] = []
    page = 1
    while True:
        request = urllib.request.Request(
            f"{_API}/repos/{repo}/actions/runs/{run_id}/jobs"
            f"?per_page=100&page={page}",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as error:
            raise SystemExit(
                f"jobs API failed: {error.code} {error.reason} ({repo} run {run_id})"
            )
        batch = payload.get("jobs") or []
        jobs.extend(batch)
        if len(batch) < 100:
            return jobs
        page += 1


def _emit_output(**values: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT", "")
    if not path:
        for key, value in values.items():
            print(f"{key}={value}")
        return
    with open(path, "a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", default="", help="jobs JSON 文件（离线用）")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", ""))
    parser.add_argument(
        "--instructions",
        default=os.environ.get("REPAIR_INSTRUCTIONS", ""),
        help="自动 repair 的默认说明",
    )
    args = parser.parse_args()

    if args.jobs:
        payload = json.loads(Path(args.jobs).read_text(encoding="utf-8"))
        jobs = payload.get("jobs") if isinstance(payload, dict) else payload
    else:
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
        if not args.repo or not args.run_id or not token:
            raise SystemExit(
                "--repo/--run-id and GITHUB_TOKEN are required without --jobs"
            )
        jobs = fetch_jobs(repo=args.repo, run_id=args.run_id, token=token)

    apps = select_failed_apps(jobs or [])
    matrix = build_matrix(apps, args.instructions)
    _emit_output(
        count=str(len(apps)),
        apps=json.dumps(apps, ensure_ascii=False, separators=(",", ":")),
        matrix=json.dumps(matrix, ensure_ascii=False, separators=(",", ":")),
    )
    print(f"failed validation apps: {apps}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
