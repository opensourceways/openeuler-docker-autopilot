#!/usr/bin/env python3
"""一次性脚本：找出目标仓里「看板不支持」的应用。

看板不支持的判定：目标仓 ``{domain}/{app}`` 目录在看板的 ``/api/v1/software``
软件清单里没有对应条目（按 name / display_name / aliases 归一化匹配）。这些
应用无法通过 ``upgrade_scan.py`` 的看板路径解析版本，需要其它版本源（上游
tag / release）才能自动升级。

用法::

    python scripts/utils/find_unsupported_apps.py --repo source-repo \\
        --out config/upgrade-apps-unsupported.yml

看板不可达时用 ``--fallback-config config/upgrade-apps.yml``（默认）兜底：
该文件是看板 kunpeng 域的可升级清单，等价于「流水线已支持」的集合。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import requests
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.utils.scrape_upgrade_apps import (  # noqa: E402
    DEFAULT_BASE,
    DOMAIN_DIRECTORIES,
    fetch_software,
    normalize,
)

DEFAULT_OUT = PROJECT_ROOT / "config" / "upgrade-apps-unsupported.yml"
DEFAULT_FALLBACK = PROJECT_ROOT / "config" / "upgrade-apps.yml"


def repo_apps(repo: Path, rev: str) -> list[tuple[str, str]]:
    """返回 [(domain, app)]；只统计带 ``{version}/{os}/Dockerfile`` 的应用目录。"""
    completed = subprocess.run(
        ["git", "-C", str(repo), "ls-tree", "-r", "--name-only", rev],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(
            f"git ls-tree {rev} 失败: {completed.stderr.strip()[:500]}"
        )
    pairs: set[tuple[str, str]] = set()
    for line in completed.stdout.splitlines():
        parts = line.split("/")
        # {domain}/{app}/{version}/{os}/Dockerfile：过滤 image-list.yml、
        # doc/config/reports 这类非应用目录。
        if (
            len(parts) == 5
            and parts[0] in DOMAIN_DIRECTORIES
            and parts[4] == "Dockerfile"
        ):
            pairs.add((parts[0], parts[1]))
    return sorted(pairs)


def dashboard_keys(base: str) -> set[str]:
    """看板软件清单的归一化键集合（name / display_name / aliases）。"""
    keys: set[str] = set()
    for record in fetch_software(base):
        if not record.get("is_active", True):
            continue
        for key in (record.get("name"), record.get("display_name")):
            if key:
                keys.add(normalize(key))
        for alias in record.get("aliases") or []:
            keys.add(normalize(alias))
    return keys


def dashboard_keys_with_retry(base: str, attempts: int = 3) -> set[str]:
    """看板偶发超时/限流，分页抓取整体重试。"""
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            return dashboard_keys(base)
        except Exception as error:  # 网络/WAF 都可能，交给调用方决定是否回退
            last = error
            if attempt + 1 < attempts:
                print(f"看板抓取失败（第 {attempt + 1} 次）: {error}")
                time.sleep(5)
    raise last  # type: ignore[misc]


def config_keys(path: Path) -> set[str]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = data.get("apps") if isinstance(data, dict) else data
    keys: set[str] = set()
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        keys.add(normalize(entry.get("app")))
        keys.add(normalize(entry.get("name")))
    keys.discard("")
    return keys


def select_unsupported(
    pairs: list[tuple[str, str]], covered: set[str]
) -> list[dict[str, str]]:
    return [
        {"name": app, "app": app, "domain": domain}
        for domain, app in pairs
        if normalize(app) not in covered
    ]


def _display(path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path)


def write_yaml(entries: list[dict[str, str]], out: Path, source: str) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump(
        {"apps": entries},
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        indent=2,
        width=200,
    )
    header = (
        "# 目标仓里已有、但看板软件清单没有对应条目的应用。\n"
        "# 这些应用无法通过 upgrade_scan.py 的看板路径解析版本；\n"
        "# 自动升级需要改用其它版本源（上游 tag / release）。\n"
        f"# 判定依据：{source}\n"
        f"# 生成：python scripts/utils/find_unsupported_apps.py\n"
    )
    out.write_text(header + body, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="目标仓克隆目录")
    parser.add_argument("--rev", default="origin/master", help="目标仓 revision")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--base", default=os.environ.get("UPSTREAM_DASHBOARD_BASE", DEFAULT_BASE))
    parser.add_argument(
        "--fallback-config",
        default=str(DEFAULT_FALLBACK),
        help="看板不可达时使用的已支持清单（留空 = 直接失败）",
    )
    parser.add_argument(
        "--source",
        choices=("dashboard", "config"),
        default="dashboard",
        help="判定依据：live 看板，或本地已支持清单",
    )
    args = parser.parse_args()

    repo = Path(args.repo)
    if not repo.is_dir():
        raise SystemExit(f"repo not found: {repo}")

    pairs = repo_apps(repo, args.rev)
    if args.source == "config":
        covered = config_keys(Path(args.fallback_config))
        source = f"{_display(Path(args.fallback_config))}（已支持清单）"
    else:
        try:
            covered = dashboard_keys_with_retry(args.base)
        except Exception as error:
            if not args.fallback_config:
                raise
            print(f"看板不可达（{error}），回退到 {args.fallback_config}")
            covered = config_keys(Path(args.fallback_config))
            source = f"{_display(Path(args.fallback_config))}（看板不可达回退）"
        else:
            source = f"dashboard {args.base}"

    unsupported = select_unsupported(pairs, covered)
    write_yaml(unsupported, Path(args.out), source)

    by_domain: dict[str, int] = {}
    for entry in unsupported:
        by_domain[entry["domain"]] = by_domain.get(entry["domain"], 0) + 1
    print(f"目标仓应用 {len(pairs)} 个；看板已支持 {len(pairs) - len(unsupported)} 个")
    print(f"看板不支持 {len(unsupported)} 个 -> {args.out}")
    for domain, count in sorted(by_domain.items(), key=lambda item: -item[1]):
        print(f"  {domain}: {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
