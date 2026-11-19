#!/usr/bin/env python3
"""给 openEuler conda-ecopkgs 仓提交「新增版本支持」PR。

对每个升级项，在 ``packages/<pkg>/supported-versions.yml`` 里登记
``<os_version>`` 下新增的 conda 包版本与架构：

- 已有该 openEuler 版本段：追加到段尾；
- 没有该段：在文件末尾新建；
- 版本已存在则跳过（分支为空时不提交、不建 PR）。

登记后按包切独立分支、推送到 fork，并调用 GitCode API 创建 PR；目标仓已有
同 head 的 open PR 时直接跳过，保证重跑幂等。

输入: --repo <conda-ecopkgs 克隆> --items '<json>' / --items-file
环境: GITCODE_TOKEN, GITCODE_FORK_REPO, GIT_COMMIT_NAME/EMAIL
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import yaml

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

from scripts.lib.ci_gitcode_api import (  # noqa: E402
    create_pull_request,
    find_any_pr_by_head_branch,
)
from scripts.lib.stage_common import log_stage  # noqa: E402

DEFAULT_TARGET_REPO = "openeuler/conda-ecopkgs"
DEFAULT_TARGET_BRANCH = "master"
VERSION_INDENT = " " * 4
ARCH_INDENT = " " * 8


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if check and completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {detail[:2000]}")
    return completed


def branch_name(item: dict) -> str:
    slug = re.sub(r"[^a-z0-9]+", "", str(item["os_version"]).lower())
    return f"auto/upgrade/{item['package']}-{item['version']}-{slug}"


def upsert_version(
    text: str, *, os_version: str, version: str, arches: list[str]
) -> tuple[str, bool]:
    """返回 (新文本, 是否有改动)；段内已有同版本时原样返回。"""
    lines = text.splitlines()
    header = f"{os_version}:"
    block = [f"{VERSION_INDENT}{version}:"] + [
        f"{ARCH_INDENT}- {arch}" for arch in arches
    ]

    start = next((i for i, line in enumerate(lines) if line.rstrip() == header), None)
    if start is None:
        body = list(lines)
        if body and body[-1].strip():
            body.append("")
        return "\n".join(body + [header] + block) + "\n", True

    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line.strip() and not line.startswith((" ", "\t")):
            end = index
            break

    if any(line.strip() == f"{version}:" for line in lines[start:end]):
        return text, False

    insert_at = end
    while insert_at > start + 1 and not lines[insert_at - 1].strip():
        insert_at -= 1
    out = lines[:insert_at] + block + lines[insert_at:]
    return "\n".join(out) + ("\n" if text.endswith("\n") else ""), True


def pr_body(item: dict) -> str:
    arches = "、".join(item["arches"])
    return "\n".join(
        [
            f"新增 **{item['package']}** {item['version']} 在 openEuler "
            f"`{item['os_version']}` 上的 {arches} 验证记录。",
            "",
            "- 上游 conda 渠道已提供对应架构构建；",
            "- 仅新增版本记录，不删除任何已有版本信息。",
            "",
            "> 本 PR 由 openEuler Docker 自动升级流水线生成。",
            "",
        ]
    )


def _write_pr(
    *,
    repo_dir: Path,
    item: dict,
    target_repo: str,
    base_branch: str,
    fork_repo: str,
    push_url: str,
    token: str,
    dry_run: bool,
) -> str:
    package = item["package"]
    version = item["version"]
    os_version = item["os_version"]
    arches = [str(arch) for arch in item["arches"]]

    yml_path = repo_dir / "packages" / package / "supported-versions.yml"
    if not yml_path.is_file():
        raise SystemExit(f"conda-ecopkgs 里没有 packages/{package}/supported-versions.yml")

    original = yml_path.read_text(encoding="utf-8")
    updated, changed = upsert_version(
        original, os_version=os_version, version=version, arches=arches
    )
    branch = branch_name(item)
    if not changed:
        log_stage("conda-pr", f"{package} {version}@{os_version} 已登记，跳过")
        return ""

    parsed = yaml.safe_load(updated) or {}
    if version not in (parsed.get(os_version) or {}):
        raise SystemExit(f"{package}: 写入后 YAML 校验失败（{os_version}/{version}）")

    if dry_run:
        log_stage("conda-pr", f"{package}: dry-run，跳过推送（branch={branch}）")
        print(updated)
        return ""

    _git(repo_dir, "fetch", "--depth", "1", "origin", base_branch)
    _git(repo_dir, "checkout", "-B", branch, f"origin/{base_branch}")
    yml_path.write_text(updated, encoding="utf-8")
    _git(repo_dir, "add", str(yml_path.relative_to(repo_dir)))
    _git(
        repo_dir,
        "-c", f"user.name={_env('GIT_COMMIT_NAME', 'openeuler-bot')}",
        "-c", f"user.email={_env('GIT_COMMIT_EMAIL', 'bot@openeuler.org')}",
        "commit",
        "-m", f"feat({package}): add {version} support for {os_version}",
    )
    _git(repo_dir, "push", push_url, f"+refs/heads/{branch}:refs/heads/{branch}")
    log_stage("conda-pr", f"{package}: pushed {branch} -> {fork_repo}")

    existing = find_any_pr_by_head_branch(target_repo, branch, token)
    if existing:
        url = str(existing.get("web_url") or existing.get("html_url") or "")
        log_stage("conda-pr", f"{package}: PR 已存在 {url}")
        return url

    head = f"{fork_repo.split('/')[0]}:{branch}" if fork_repo != target_repo else branch
    title = (
        f"feat({package}): 新增 {version} 支持（{os_version}，"
        f"{'/'.join(arches)}）"
    )
    pr = None
    for attempt in range(3):
        try:
            pr = create_pull_request(
                target_repo, head, base_branch, title, pr_body(item), token
            )
            break
        except Exception as error:  # fork 分支同步有延迟，重试
            if attempt == 2:
                raise
            log_stage("conda-pr", f"{package}: 建 PR 重试 {attempt + 1}（{error}）")
            time.sleep(10)
    url = str((pr or {}).get("web_url") or (pr or {}).get("html_url") or "")
    log_stage("conda-pr", f"{package}: PR created {url}")
    return url


def run(
    *,
    repo_dir: Path,
    items: list[dict],
    target_repo: str,
    base_branch: str,
    fork_repo: str,
    token: str,
    dry_run: bool = False,
) -> int:
    if not dry_run and not token:
        raise SystemExit("GITCODE_TOKEN is required to push and open PRs")
    push_url = f"https://oauth2:{token}@gitcode.com/{fork_repo}.git"
    failed = 0
    for item in items:
        for field in ("package", "version", "os_version", "arches"):
            if not item.get(field):
                raise SystemExit(f"升级项缺少 {field}: {item!r}")
        try:
            _write_pr(
                repo_dir=repo_dir,
                item=item,
                target_repo=target_repo,
                base_branch=base_branch,
                fork_repo=fork_repo,
                push_url=push_url,
                token=token,
                dry_run=dry_run,
            )
        except Exception as error:
            failed += 1
            log_stage("conda-pr", f"{item.get('package')}: 失败 {error}")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="conda-ecopkgs 克隆目录")
    parser.add_argument("--items", default="", help="升级项 JSON 数组")
    parser.add_argument("--items-file", default="", help="从文件读取升级项 JSON")
    parser.add_argument("--target-repo", default=DEFAULT_TARGET_REPO)
    parser.add_argument("--base", default=DEFAULT_TARGET_BRANCH)
    parser.add_argument("--fork-repo", required=True, help="推送用的 fork（owner/repo）")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.items_file:
        payload = Path(args.items_file).read_text(encoding="utf-8")
    else:
        payload = args.items
    items = json.loads(payload or "[]")
    if not isinstance(items, list) or not items:
        raise SystemExit("--items 需要非空 JSON 数组")

    return run(
        repo_dir=Path(args.repo),
        items=items,
        target_repo=args.target_repo,
        base_branch=args.base,
        fork_repo=args.fork_repo,
        token=_env("GITCODE_TOKEN"),
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())
