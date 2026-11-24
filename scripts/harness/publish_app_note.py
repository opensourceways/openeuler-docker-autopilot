#!/usr/bin/env python3
"""把 Agent 总结的 app note 写回本仓 ``config/app-notes/<app>.md`` 并开 PR。

每次升级 / 审计 / 修复只更新该版本对应的自动沉淀章节，人工内容与 YAML
front matter 保持不变。分支按应用隔离（``auto/app-note/<app>``），避免并发
任务互相覆盖；branch 已存在时在其最新提交上继续追加。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from scripts.lib import app_notes  # noqa: E402

_API_ROOT = "https://api.github.com"
_REDACT_RE = re.compile(r"(https?://)[^@\s]+@", re.IGNORECASE)


def _redact(text: str) -> str:
    return _REDACT_RE.sub(r"\1***@", str(text))


def _git(workspace: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    completed = subprocess.run(
        ["git", "-C", str(workspace), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if check and completed.returncode != 0:
        detail = _redact((completed.stderr or completed.stdout or "").strip())
        raise SystemExit(f"git {' '.join(args[:2])} failed: {detail[:1000]}")
    return completed


def _api(method: str, url: str, token: str, payload: dict | None = None) -> tuple[int, object]:
    data = None
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "openeuler-autopilot/1.0",
    }
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode()
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(body) if body else {}
        except json.JSONDecodeError:
            parsed = {"message": body}
        return error.code, parsed
    except (OSError, urllib.error.URLError) as error:
        raise SystemExit(f"GitHub API request failed: {error}") from error


def _open_pr(
    *,
    repo: str,
    token: str,
    branch: str,
    base: str,
    title: str,
    body: str,
) -> str:
    owner = repo.split("/", 1)[0]
    query = (
        f"{_API_ROOT}/repos/{repo}/pulls?state=open"
        f"&head={quote(owner + ':' + branch, safe='')}"
    )
    status, payload = _api("GET", query, token)
    if status == 200 and isinstance(payload, list) and payload:
        return str(payload[0].get("html_url") or "")

    status, payload = _api(
        "POST",
        f"{_API_ROOT}/repos/{repo}/pulls",
        token,
        {"title": title, "head": branch, "base": base, "body": body},
    )
    if status in (200, 201) and isinstance(payload, dict):
        return str(payload.get("html_url") or "")
    message = payload.get("message") if isinstance(payload, dict) else payload
    raise SystemExit(f"failed to open notes PR ({status}): {message}")


def publish(
    *,
    app: str,
    version: str,
    os_version: str,
    note: str,
    workspace: Path,
    repo: str,
    token: str,
    base: str,
    branch: str,
) -> str:
    base_ref = f"refs/remotes/origin/{base}"
    _git(
        workspace,
        "fetch",
        "--no-tags",
        "--depth=1",
        "origin",
        f"+refs/heads/{base}:{base_ref}",
    )
    branch_ref = f"refs/remotes/origin/{branch}"
    _git(
        workspace,
        "fetch",
        "--no-tags",
        "--depth=1",
        "origin",
        f"+refs/heads/{branch}:{branch_ref}",
        check=False,
    )
    exists = _git(
        workspace, "rev-parse", "--verify", "--quiet", branch_ref, check=False
    ).returncode == 0
    start = branch_ref if exists else base_ref
    _git(workspace, "checkout", "-B", branch, start)

    relative = f"config/app-notes/{app}.md"
    try:
        written = app_notes.write_auto_note(
            app=app,
            version=version,
            os_version=os_version,
            note=note,
            notes_dir=workspace / "config" / "app-notes",
        )
    except ValueError as error:
        raise SystemExit(f"invalid app note for {app}: {error}") from error
    if written is None:
        return ""

    commit_name = os.environ.get("GIT_COMMIT_NAME", "github-actions[bot]")
    commit_email = os.environ.get(
        "GIT_COMMIT_EMAIL", "github-actions[bot]@users.noreply.github.com"
    )
    _git(workspace, "add", relative)
    _git(
        workspace,
        "-c",
        f"user.name={commit_name}",
        "-c",
        f"user.email={commit_email}",
        "commit",
        "-m",
        f"docs(app-notes): update {app} for {version}",
    )
    _git(workspace, "push", "origin", f"+refs/heads/{branch}:refs/heads/{branch}")

    run_url = os.environ.get("RUN_URL", "")
    body_lines = [
        f"## App notes: `{app}`",
        "",
        f"- 目标版本：`{version}` / openEuler `{os_version}`",
        f"- 文件：`{relative}`",
        "- 本次只更新该版本的自动沉淀章节，人工内容保持不变。",
    ]
    if run_url:
        body_lines.append(f"- 来源运行：{run_url}")
    return _open_pr(
        repo=repo,
        token=token,
        branch=branch,
        base=base,
        title=f"docs(app-notes): update {app} for {version}",
        body="\n".join(body_lines) + "\n",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", default="")
    parser.add_argument("--version", default="")
    parser.add_argument("--os-version", default="")
    parser.add_argument(
        "--task-spec",
        type=Path,
        help="apply/audit 产出的 task-spec.json；用它的 app/version/os_version 兜底",
    )
    parser.add_argument("--note-file", required=True, type=Path)
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path(os.environ.get("GITHUB_WORKSPACE", ".")),
        help="本仓 checkout 目录（默认 GITHUB_WORKSPACE）",
    )
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--base", default=os.environ.get("GITHUB_DEFAULT_BRANCH", "main"))
    parser.add_argument("--branch", default="")
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""))
    args = parser.parse_args()

    try:
        note = args.note_file.read_text(encoding="utf-8")
    except OSError:
        print(f"no app note at {args.note_file}; nothing to publish")
        return 0
    if not note.strip():
        print("empty app note; nothing to publish")
        return 0

    task: dict = {}
    if args.task_spec is not None and args.task_spec.is_file():
        try:
            task = json.loads(args.task_spec.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise SystemExit(f"cannot read task spec: {error}") from error
    app = (args.app or str(task.get("app") or "")).strip()
    version = (args.version or str(task.get("version") or "")).strip()
    os_version = (args.os_version or str(task.get("os_version") or "")).strip()
    if not (app and version and os_version):
        raise SystemExit("app, version and os_version are required")

    if not args.repo or not args.token:
        raise SystemExit("--repo and GITHUB_TOKEN are required to publish app notes")

    branch = args.branch.strip() or f"auto/app-note/{app}"
    pr_url = publish(
        app=app,
        version=version,
        os_version=os_version,
        note=note,
        workspace=args.workspace.resolve(),
        repo=args.repo,
        token=args.token,
        base=args.base,
        branch=branch,
    )
    print(pr_url or f"no note change for {app}")
    output = os.environ.get("GITHUB_OUTPUT", "")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"pr_url={pr_url}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
