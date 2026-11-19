#!/usr/bin/env python3
"""一次性脚本：爬看板鲲鹏域 ``level_auto=L5`` 的软件，映射到目标仓应用。

L5 的定义见 upstream-dashboard ``docs/support-judgment-criteria.md``：
上游原生（L1）/ 中游（L2）/ 下游（L4）三个支持等级均不成立时判最低档 L5。
L5 只表示鲲鹏支持度为最低，并**不阻断版本解析**——``/api/v1/version/resolve``
仍能给出最新版本与 ``repo_url``，所以这些应用可以直接用于自动升级。

用法::

    python scripts/utils/fetch_l5_apps.py --repo source-repo \\
        --out config/upgrade-apps-l5.yml

看板前置 WAF，脚本会先访问首页取 Cookie 并分页抓取；可用 ``--cache-dir``
缓存原始分页，网络抖动时重跑不用从头再来。
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
    normalize,
)

DEFAULT_OUT = PROJECT_ROOT / "config" / "upgrade-apps-l5.yml"
PAGE_SIZE = 50
TARGET_LEVEL = "L5"
# 看板软件名与目标仓目录名不一致的少数情况（按归一化名映射）。
NAME_ALIASES = {
    "golang": "go",
}
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def repo_apps(repo: Path, rev: str) -> dict[str, list[tuple[str, str]]]:
    """normalized app -> [(domain, app)]；只统计带 Dockerfile 的应用目录。"""
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
    index: dict[str, set[tuple[str, str]]] = {}
    for line in completed.stdout.splitlines():
        parts = line.split("/")
        if (
            len(parts) == 5
            and parts[0] in DOMAIN_DIRECTORIES
            and parts[4] == "Dockerfile"
        ):
            index.setdefault(normalize(parts[1]), set()).add((parts[0], parts[1]))
    return {key: sorted(value) for key, value in index.items()}


def _cache_path(cache_dir: Path | None, page: int) -> Path | None:
    return cache_dir / f"page-{page}.json" if cache_dir else None


def _fetch_json(
    session: requests.Session, base: str, params: dict[str, object], attempts: int = 6
) -> dict:
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            response = session.get(
                f"{base}/api/v1/software",
                params=params,
                headers={**_HEADERS, "Referer": f"{base}/"},
                timeout=45,
            )
            if response.status_code == 418:
                session.get(
                    f"{base}/",
                    headers={**_HEADERS, "Accept": "text/html"},
                    timeout=20,
                )
                response = session.get(
                    f"{base}/api/v1/software",
                    params=params,
                    headers={**_HEADERS, "Referer": f"{base}/"},
                    timeout=45,
                )
            if response.status_code == 200:
                return response.json()
            last = RuntimeError(f"HTTP {response.status_code}")
        except Exception as error:  # 看板前置 WAF，连接/RST 都可能
            last = error
        if attempt + 1 < attempts:
            time.sleep(3)
    raise SystemExit(f"看板请求失败: {last}")


def fetch_software(base: str, cache_dir: Path | None = None) -> list[dict]:
    session = requests.Session()
    try:
        session.get(f"{base}/", headers={**_HEADERS, "Accept": "text/html"}, timeout=20)
    except Exception:
        pass

    items: list[dict] = []
    page = 1
    total = None
    while total is None or len(items) < total:
        cached = _cache_path(cache_dir, page)
        if cached and cached.is_file():
            payload = yaml.safe_load(cached.read_text(encoding="utf-8"))
        else:
            payload = _fetch_json(
                session, base, {"page": page, "page_size": PAGE_SIZE}
            )
            if cached:
                cached.parent.mkdir(parents=True, exist_ok=True)
                cached.write_text(
                    yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
                    encoding="utf-8",
                )
        total = int(payload.get("total") or 0)
        batch = payload.get("items") or []
        if not batch:
            break
        items.extend(batch)
        page += 1
    return items


def select_l5(records: list[dict]) -> list[dict]:
    l5: list[dict] = []
    for record in records:
        if record.get("domain") != "kunpeng":
            continue
        raw_levels = record.get("level_auto") or []
        if isinstance(raw_levels, str):
            raw_levels = [part.strip() for part in raw_levels.split(",")]
        levels = [str(level).upper() for level in raw_levels]
        if levels == [TARGET_LEVEL]:
            l5.append(record)
    return sorted(l5, key=lambda item: str(item.get("name") or "").casefold())


def lookup(
    record: dict, index: dict[str, list[tuple[str, str]]]
) -> tuple[tuple[str, str] | None, list[tuple[str, str]]]:
    """返回 (唯一命中, 全部候选)；优先精确名，其次别名。"""
    for key in (record.get("name"), record.get("display_name")):
        if not key:
            continue
        normalized = normalize(key)
        exact = index.get(NAME_ALIASES.get(normalized, normalized), [])
        if len(exact) == 1:
            return exact[0], exact
    candidates: set[tuple[str, str]] = set()
    for key in [record.get("name"), record.get("display_name")] + list(
        record.get("aliases") or []
    ):
        if key:
            normalized = normalize(key)
            candidates.update(
                index.get(NAME_ALIASES.get(normalized, normalized), [])
            )
    if len(candidates) == 1:
        return next(iter(candidates)), sorted(candidates)
    return None, sorted(candidates)


def write_yaml(entries: list[dict[str, str]], out: Path) -> None:
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
        "# 看板鲲鹏域 level_auto=L5 的软件（上游原生/中游/下游支持等级均不成立）。\n"
        "# L5 只影响鲲鹏支持度，不影响版本解析：version/resolve 仍会给出\n"
        "# 最新版本与 repo_url，因此可以直接用于自动升级。\n"
        "# 生成：python scripts/utils/fetch_l5_apps.py\n"
    )
    out.write_text(header + body, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="目标仓克隆目录")
    parser.add_argument("--rev", default="origin/master", help="目标仓 revision")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--base", default=os.environ.get("UPSTREAM_DASHBOARD_BASE", DEFAULT_BASE))
    parser.add_argument("--cache-dir", default="", help="分页 JSON 缓存目录（可选）")
    args = parser.parse_args()

    repo = Path(args.repo)
    if not repo.is_dir():
        raise SystemExit(f"repo not found: {repo}")

    records = fetch_software(
        args.base, Path(args.cache_dir) if args.cache_dir else None
    )
    l5 = select_l5(records)
    index = repo_apps(repo, args.rev)

    entries: list[dict[str, str]] = []
    unmatched: list[str] = []
    ambiguous: list[str] = []
    for record in l5:
        match, candidates = lookup(record, index)
        name = str(record.get("name") or "")
        if match is None:
            if candidates:
                ambiguous.append(f"{name} -> {candidates}")
            else:
                unmatched.append(name)
            continue
        domain, app = match
        entries.append({"name": name, "app": app, "domain": domain})

    write_yaml(entries, Path(args.out))

    print(f"看板软件 {len(records)} 个；鲲鹏域 L5 {len(l5)} 个")
    print(f"目标仓可对上 {len(entries)} 个 -> {args.out}")
    print(f"目标仓没有对应目录 {len(unmatched)} 个：{', '.join(unmatched)}")
    if ambiguous:
        print(f"命中多个目录，已跳过 {len(ambiguous)} 个：")
        for line in ambiguous:
            print(f"  {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
