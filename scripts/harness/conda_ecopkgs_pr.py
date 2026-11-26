#!/usr/bin/env python3
"""给 openEuler conda-ecopkgs 仓提交「新增版本支持」PR。

对每个升级项，在 ``packages/<pkg>/supported-versions.yml`` 里登记
``<os_version>`` 下新增的 conda 包版本与架构：

- 已有该 openEuler 版本段：追加到段尾；
- 没有该段：在文件末尾新建；
- 版本已存在则跳过（分支为空时不提交、不建 PR）。

登记前先查 ``package.yml`` 声明的上游渠道：``linux-64`` / ``linux-aarch64``
必须有该版本产物，缺任何一个就跳过该包，不登记、不建 PR。包目录缺
``tests/cases.yml`` 时按统一模板补齐（安装版本核对 + 包文件完整性），
随版本登记一起提交，让目标仓 CI 真的能跑到功能用例。

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

import requests
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


ANACONDA_API = "https://api.anaconda.org/package/{channel}/{package}"
ARCH_SUBDIRS = {"x86_64": "linux-64", "aarch64": "linux-aarch64"}
# 包目录缺少 cases.yml 时补的通用功能用例超时（秒）。
_GENERIC_CASE_TIMEOUT = {"installed-version": 60, "package-integrity": 120}


class UpstreamIndexError(RuntimeError):
    """上游 conda 渠道索引不可用时抛出，调用方不应放行 PR。"""


def _file_subdir(entry: dict) -> str:
    subdir = str((entry.get("attrs") or {}).get("subdir") or "").strip()
    if subdir:
        return subdir
    basename = str(entry.get("basename") or "")
    return basename.split("/", 1)[0] if "/" in basename else ""


def missing_artifacts(index: dict, *, version: str, arches: list[str]) -> list[str]:
    """返回上游索引里缺少 ``version`` 产物的架构列表（空表示齐全）。"""
    available = {
        (str(entry.get("version") or ""), _file_subdir(entry))
        for entry in index.get("files") or []
    }
    missing: list[str] = []
    for arch in arches:
        subdir = ARCH_SUBDIRS.get(arch)
        if subdir is None or (version, subdir) not in available:
            missing.append(arch)
    return missing


def fetch_package_index(channel: str, package: str, *, timeout: int = 30) -> dict:
    """读取 anaconda.org 的包索引（conda-forge / bioconda / main 均适用）。"""
    url = ANACONDA_API.format(channel=channel, package=package)
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as error:
        raise UpstreamIndexError(f"{channel}/{package} 上游索引查询失败：{error}") from error
    if not isinstance(payload, dict):
        raise UpstreamIndexError(f"{channel}/{package} 上游索引返回格式异常")
    return payload


def verify_upstream(
    *, channel: str, package: str, version: str, arches: list[str]
) -> list[str]:
    """校验上游渠道有 ``version`` 的对应架构产物，返回缺失的架构。"""
    index = fetch_package_index(channel, package)
    return missing_artifacts(index, version=version, arches=arches)


def _load_channel(repo_dir: Path, package: str) -> str:
    package_yml = repo_dir / "packages" / package / "package.yml"
    if not package_yml.is_file():
        raise SystemExit(f"conda-ecopkgs 里没有 packages/{package}/package.yml")
    meta = yaml.safe_load(package_yml.read_text(encoding="utf-8")) or {}
    channel = str(meta.get("channel") or "").strip()
    if not channel:
        raise SystemExit(f"packages/{package}/package.yml 缺少 channel，无法校验上游产物")
    return channel


def cases_yaml(package: str) -> str:
    """生成 packages/<pkg>/tests/cases.yml 的内容。

    只放不依赖具体软件的命令：安装版本核对 + 包文件完整性，对所有包都成立。
    """
    cases = [
        {
            "name": "installed-version",
            "description": f"已安装的 {package} 版本必须等于申报版本",
            "category": "functional",
            "cmd": f'ls "$CONDA_PREFIX/conda-meta/{package}-${{PKG_VERSION}}-"*.json',
            "timeout": _GENERIC_CASE_TIMEOUT["installed-version"],
        },
        {
            "name": "package-integrity",
            "description": "conda 元数据登记的包内文件必须完整落盘",
            "category": "functional",
            "cmd": (
                'python -c "import glob,json,os,sys; '
                "p=os.environ['CONDA_PREFIX']; "
                f"m=glob.glob(os.path.join(p,'conda-meta','{package}-'"
                "+os.environ['PKG_VERSION']+'-*.json')); "
                "f=json.load(open(m[0]))['files']; "
                "missing=[x for x in f if not os.path.lexists(os.path.join(p,x))]; "
                "print('checked',len(f),'files; missing',len(missing)); "
                "[print('missing',x) for x in missing[:20]]; "
                'sys.exit(1 if missing else 0)"'
            ),
            "timeout": _GENERIC_CASE_TIMEOUT["package-integrity"],
        },
    ]
    body = yaml.safe_dump(
        {"cases": cases},
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        width=10000,
    )
    return "# 由 openEuler Docker 自动升级流水线生成\n" + body


def _yaml_version_key(version: str) -> str:
    """版本号可能被 YAML 解析成数字（如 4.4 -> float），这类键必须加引号。"""
    parsed = yaml.safe_load(f"key: {version}")
    if isinstance(parsed, dict) and isinstance(parsed.get("key"), str):
        return version
    return f'"{version}"'


def upsert_version(
    text: str, *, os_version: str, version: str, arches: list[str]
) -> tuple[str, bool]:
    """返回 (新文本, 是否有改动)；段内已有同版本时原样返回。"""
    lines = text.splitlines()
    header = f"{os_version}:"
    block = [f"{VERSION_INDENT}{_yaml_version_key(version)}:"] + [
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

    existing_keys = {f"{version}:", f'"{version}":', f"'{version}':"}
    if any(line.strip() in existing_keys for line in lines[start:end]):
        return text, False

    insert_at = end
    while insert_at > start + 1 and not lines[insert_at - 1].strip():
        insert_at -= 1
    out = lines[:insert_at] + block + lines[insert_at:]
    return "\n".join(out) + ("\n" if text.endswith("\n") else ""), True


def pr_body(item: dict, *, channel: str, with_cases: bool) -> str:
    arches = "、".join(item["arches"])
    lines = [
        f"新增 **{item['package']}** {item['version']} 在 openEuler "
        f"`{item['os_version']}` 上的 {arches} 验证记录。",
        "",
    ]
    if channel:
        lines.append(f"- 已在 `{channel}` 渠道确认该版本存在 {arches} 产物；")
    lines.append("- 仅新增版本记录，不删除任何已有版本信息。")
    if with_cases:
        lines.append(
            "- 同时补充 `tests/cases.yml`：核对安装版本并校验包文件完整性。"
        )
    lines += ["", "> 本 PR 由 openEuler Docker 自动升级流水线生成。", ""]
    return "\n".join(lines)


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
    cases_path = repo_dir / "packages" / package / "tests" / "cases.yml"
    needs_cases = not cases_path.is_file()
    branch = branch_name(item)
    if not changed and not needs_cases:
        log_stage("conda-pr", f"{package} {version}@{os_version} 已登记，跳过")
        return ""

    channel = _load_channel(repo_dir, package) if changed else ""
    if changed:
        missing = verify_upstream(
            channel=channel, package=package, version=version, arches=arches
        )
        if missing:
            detail = "、".join(
                f"{arch}({ARCH_SUBDIRS.get(arch, '未知架构')})" for arch in missing
            )
            log_stage(
                "conda-pr",
                f"{package} {version}@{os_version}: {channel} 渠道缺 {detail} 产物，"
                "跳过登记与建 PR",
            )
            return ""

    if changed:
        parsed = yaml.safe_load(updated) or {}
        if version not in (parsed.get(os_version) or {}):
            raise SystemExit(f"{package}: 写入后 YAML 校验失败（{os_version}/{version}）")

    if dry_run:
        targets = []
        if changed:
            targets.append("supported-versions.yml")
        if needs_cases:
            targets.append("tests/cases.yml")
        log_stage(
            "conda-pr",
            f"{package}: dry-run，跳过推送（branch={branch}，改动={','.join(targets)}）",
        )
        if changed:
            print(updated)
        if needs_cases:
            print(cases_yaml(package))
        return ""

    _git(repo_dir, "fetch", "origin", base_branch)
    _git(repo_dir, "checkout", "-B", branch, f"origin/{base_branch}")
    if changed:
        yml_path.write_text(updated, encoding="utf-8")
        _git(repo_dir, "add", str(yml_path.relative_to(repo_dir)))
    if needs_cases:
        cases_path.parent.mkdir(parents=True, exist_ok=True)
        cases_path.write_text(cases_yaml(package), encoding="utf-8")
        _git(repo_dir, "add", str(cases_path.relative_to(repo_dir)))
    subject = (
        f"feat({package}): add {version} support for {os_version}"
        if changed
        else f"test({package}): add functional test cases"
    )
    if changed and needs_cases:
        subject += " with tests"
    _git(
        repo_dir,
        "-c", f"user.name={_env('GIT_COMMIT_NAME', 'openeuler-bot')}",
        "-c", f"user.email={_env('GIT_COMMIT_EMAIL', 'bot@openeuler.org')}",
        "commit",
        "-m", subject,
    )
    _git(repo_dir, "push", push_url, f"+refs/heads/{branch}:refs/heads/{branch}")
    log_stage("conda-pr", f"{package}: pushed {branch} -> {fork_repo}")

    existing = find_any_pr_by_head_branch(target_repo, branch, token, open_only=True)
    if existing:
        url = str(existing.get("web_url") or existing.get("html_url") or "")
        log_stage("conda-pr", f"{package}: PR 已存在 {url}")
        return url

    head = f"{fork_repo.split('/')[0]}:{branch}" if fork_repo != target_repo else branch
    if changed:
        title = (
            f"feat({package}): 新增 {version} 支持（{os_version}，"
            f"{'/'.join(arches)}）"
        )
    else:
        title = f"test({package}): 补充功能测试用例"
    pr = None
    for attempt in range(3):
        try:
            pr = create_pull_request(
                target_repo,
                head,
                base_branch,
                title,
                pr_body(item, channel=channel, with_cases=needs_cases),
                token,
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
