#!/usr/bin/env python3
"""一次性脚本：从 upstream-dashboard 拉软件列表，生成场景二的升级清单。

运行时不再遍历目标仓：`upgrade_scan.py` 只读 ``config/upgrade-apps.yml``。
本脚本只负责把看板软件名与目标仓的 ``{domain}/{app}`` 目录对上，产出初始
清单；之后新增/删除软件直接改 YAML 即可。

用法::

    python scripts/utils/scrape_upgrade_apps.py --repo /path/to/oe-images \\
        --out config/upgrade-apps.yml

``--repo`` 可以是完整克隆，也可以是 ``--filter=blob:none --no-checkout`` 的
浅克隆（脚本用 ``git ls-tree`` 取目录名，不读文件内容）。
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

import requests
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.lib.task_spec import _DOMAINS  # noqa: E402

DEFAULT_OUT = PROJECT_ROOT / "config" / "upgrade-apps.yml"
DOMAIN_DIRECTORIES = set(_DOMAINS.values())
DEFAULT_BASE = "https://upstream-dashboard.test.osinfra.cn"
PAGE_SIZE = 100
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json",
}
_SPLIT_RE = re.compile(r"[-_.\s]+")


def normalize(name: str) -> str:
    """ClickHouse / click-house / click_house 统一成 clickhouse。"""
    return _SPLIT_RE.sub("-", str(name or "").strip().lower()).strip("-")


def fetch_software(base: str) -> list[dict]:
    items: list[dict] = []
    page = 1
    total = None
    while total is None or len(items) < total:
        response = requests.get(
            f"{base.rstrip('/')}/api/v1/software",
            params={"page": page, "page_size": PAGE_SIZE},
            headers=_HEADERS,
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        total = int(payload.get("total") or 0)
        batch = payload.get("items") or []
        if not batch:
            break
        items.extend(batch)
        page += 1
    return items


def index_target_repo(repo: Path) -> dict[str, list[tuple[str, str]]]:
    """normalized app -> [(domain, app)]；只依赖 git tree，不读文件。"""
    completed = subprocess.run(
        ["git", "-C", str(repo), "ls-tree", "-r", "--name-only", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(f"git ls-tree 失败: {completed.stderr.strip()[:500]}")

    index: dict[str, list[tuple[str, str]]] = {}
    seen: set[tuple[str, str]] = set()
    for line in completed.stdout.splitlines():
        parts = line.split("/")
        if len(parts) < 2 or parts[0] not in DOMAIN_DIRECTORIES:
            continue
        pair = (parts[0], parts[1])
        if pair in seen:
            continue
        seen.add(pair)
        index.setdefault(normalize(parts[1]), []).append(pair)
    return index


def _lookup(record: dict, index: dict[str, list[tuple[str, str]]]) -> list[tuple[str, str]]:
    for key in (record.get("name"), record.get("display_name")):
        if not key:
            continue
        exact = [pair for pair in index.get(normalize(key), [])]
        if len(exact) == 1:
            return exact
        if len(exact) > 1:
            return exact
    for alias in record.get("aliases") or []:
        matches = index.get(normalize(alias), [])
        if len(matches) == 1:
            return matches
    return []


def build_entries(records: list[dict], repo: Path) -> tuple[list[dict], list[str], list[str]]:
    index = index_target_repo(repo)
    entries: list[dict] = []
    missing: list[str] = []
    ambiguous: list[str] = []
    used: set[tuple[str, str]] = set()

    for record in sorted(records, key=lambda item: str(item.get("name") or "").casefold()):
        if not record.get("is_active", True):
            continue
        matches = _lookup(record, index)
        if not matches:
            missing.append(str(record.get("name") or "?"))
            continue
        if len(matches) > 1:
            ambiguous.append(
                f"{record.get('name')} -> {', '.join(f'{d}/{a}' for d, a in matches)}"
            )
            continue
        domain, app = matches[0]
        if (domain, app) in used:
            continue
        used.add((domain, app))
        entries.append(
            {"name": str(record.get("name") or app), "app": app, "domain": domain}
        )

    entries.sort(key=lambda entry: (entry["domain"].casefold(), entry["app"].casefold()))
    return entries, missing, ambiguous


def write_yaml(entries: list[dict], out: Path) -> None:
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
        "# 场景二（应用自动升级）的软件清单，人工维护。\n"
        "# name: 看板软件名（传给 /api/v1/version/resolve）\n"
        "# app:  目标仓应用目录名；domain: 目标仓一级目录\n"
        "# 新增/删除软件直接改本文件，workflow 不再遍历目标仓。\n"
        "# 初始内容由 scripts/utils/scrape_upgrade_apps.py 生成。\n"
    )
    out.write_text(header + body, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="目标仓克隆目录")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument(
        "--base",
        default=os.environ.get("UPSTREAM_DASHBOARD_BASE", DEFAULT_BASE),
        help="看板地址",
    )
    args = parser.parse_args()

    repo = Path(args.repo)
    if not repo.is_dir():
        raise SystemExit(f"repo not found: {repo}")

    records = fetch_software(args.base)
    entries, missing, ambiguous = build_entries(records, repo)
    write_yaml(entries, Path(args.out))

    print(f"看板软件 {len(records)} 个；写入 {len(entries)} 条 -> {args.out}")
    print(f"未在目标仓找到：{len(missing)} 个")
    if missing:
        print("  " + ", ".join(missing[:30]) + (" ..." if len(missing) > 30 else ""))
    if ambiguous:
        print(f"归一化后命中多个目录，已跳过 {len(ambiguous)} 个：")
        for line in ambiguous[:10]:
            print(f"  {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
