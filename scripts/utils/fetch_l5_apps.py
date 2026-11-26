#!/usr/bin/env python3
"""一次性脚本：爬看板鲲鹏域 ``level_auto=L5`` 的软件，生成场景二的升级清单。

L5 的定义见 upstream-dashboard ``docs/support-judgment-criteria.md``：
上游原生（L1）/ 中游（L2）/ 下游（L4）三个支持等级均不成立时判最低档 L5。
L5 只表示鲲鹏支持度为最低，并**不阻断版本解析**——看板仍会给出
``latest_release`` 版本与 ``repo_url``，因此这些应用可以直接用于自动升级。

本脚本是**严格覆盖**：输出只包含当前看板 L5 的软件，旧清单里已不属于 L5 的
条目不会保留。每个软件同时尝试映射 docker（``{domain}/{app}``）与 conda
（``packages/{package}``）目标仓；两个仓都找不到的跳过并打印。

用法::

    python scripts/utils/fetch_l5_apps.py --repo source-repo \\
        --conda-repo conda-ecopkgs --out config/upgrade-apps-l5.yml

看板前置 WAF，脚本会先访问首页取 Cookie 并分页抓取；可用 ``--cache-dir``
缓存原始分页，网络抖动时重跑不用从头再来。
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

import requests
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.utils.scrape_upgrade_apps import (  # noqa: E402
    DEFAULT_BASE,
    build_entries,
    normalize,
)

DEFAULT_OUT = PROJECT_ROOT / "config" / "upgrade-apps-l5.yml"
PAGE_SIZE = 50
TARGET_LEVEL = "L5"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
_INVALID_VERSIONS = {"", "undefined", "latest", "unknown"}
# 看板版本与目标仓目录约定不一致时的前缀剥离。
_VERSION_PREFIXES = {
    "edk2": ("edk2-stable",),
}
_GITHUB_RE = re.compile(
    r"^https?://(?:www\.)?github\.com/([^/]+)/([^/#?]+)", re.IGNORECASE
)


def _github_repo(url: str) -> tuple[str, str] | None:
    match = _GITHUB_RE.match(str(url or "").strip())
    if not match:
        return None
    owner = match.group(1).lower()
    repo = re.sub(r"\.git$", "", match.group(2), flags=re.IGNORECASE).lower()
    return owner, repo


def _strip_version_prefix(name: str, version: str) -> str:
    for prefix in _VERSION_PREFIXES.get(normalize(name), ()):
        if version.lower().startswith(prefix.lower()):
            return version[len(prefix) :]
    return version


def _conda_homepage(conda_repo: Path | None, package: str) -> str:
    if conda_repo is None:
        return ""
    package_yml = conda_repo / "packages" / package / "package.yml"
    if not package_yml.is_file():
        return ""
    meta = yaml.safe_load(package_yml.read_text(encoding="utf-8")) or {}
    return str(meta.get("homepage") or "").strip()



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


def latest_version(record: dict) -> str:
    """取看板 latest_release 版本；没有就退回第一个有效版本。"""
    versions = record.get("versions") or []
    ordered = sorted(
        (item for item in versions if isinstance(item, dict)),
        key=lambda item: item.get("version_type") != "latest_release",
    )
    for item in ordered:
        version = str(item.get("version") or "").strip()
        if version.lower() not in _INVALID_VERSIONS:
            return version
    return ""


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
        "# 看板鲲鹏域当前 level_auto=L5 的软件（严格快照，重新生成会覆盖旧条目）。\n"
        "# docker 目标在 openeuler-docker-images 的 {app, domain} 目录；\n"
        "# conda 目标在 openeuler/conda-ecopkgs 的 packages/{package} 目录。\n"
        "# version 取看板 latest_release，source_url 取看板 repo_url。\n"
        "# 生成：python scripts/utils/fetch_l5_apps.py --repo ... --conda-repo ...\n"
    )
    out.write_text(header + body, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="docker 目标仓克隆目录")
    parser.add_argument(
        "--conda-repo",
        default="",
        help="conda-ecopkgs 克隆目录（留空 = 不映射 conda 目标）",
    )
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument(
        "--base",
        default=os.environ.get("UPSTREAM_DASHBOARD_BASE", DEFAULT_BASE),
        help="看板地址",
    )
    parser.add_argument("--cache-dir", default="", help="分页 JSON 缓存目录（可选）")
    args = parser.parse_args()

    repo = Path(args.repo)
    if not repo.is_dir():
        raise SystemExit(f"repo not found: {repo}")
    conda_repo = Path(args.conda_repo) if args.conda_repo else None
    if conda_repo is not None and not conda_repo.is_dir():
        raise SystemExit(f"conda repo not found: {conda_repo}")

    records = fetch_software(
        args.base, Path(args.cache_dir) if args.cache_dir else None
    )
    l5 = select_l5(records)
    entries, missing, ambiguous = build_entries(
        l5, repo, conda_repo=conda_repo, existing=[]
    )

    by_name = {normalize(str(record.get("name") or "")): record for record in l5}
    enriched: list[dict] = []
    no_version: list[str] = []
    conda_mismatch: list[str] = []
    for entry in entries:
        # 严格快照只保留目标仓里真实存在的软件；create 目标不属于本清单。
        if not entry.get("docker") and not entry.get("conda"):
            continue
        record = by_name.get(normalize(str(entry.get("name") or "")), {})
        name = str(entry.get("name") or "")
        version = _strip_version_prefix(name, latest_version(record))
        if not version:
            no_version.append(name)
            continue
        conda = entry.get("conda")
        if isinstance(conda, dict):
            package = str(conda.get("package") or "")
            dashboard_repo = _github_repo(str(record.get("repo_url") or ""))
            package_repo = _github_repo(
                _conda_homepage(conda_repo, package)
            )
            if (
                dashboard_repo
                and package_repo
                and dashboard_repo != package_repo
            ):
                conda_mismatch.append(
                    f"{name}: conda {package} 指向 {package_repo}，"
                    f"看板指向 {dashboard_repo}"
                )
                entry.pop("conda", None)
                if not entry.get("docker"):
                    continue
        entry["version"] = version
        repo_url = str(record.get("repo_url") or "").strip()
        if repo_url.startswith("https://"):
            entry["source_url"] = repo_url
        enriched.append(entry)

    write_yaml(enriched, Path(args.out))

    docker_count = sum(1 for entry in enriched if entry.get("docker"))
    conda_count = sum(1 for entry in enriched if entry.get("conda"))
    both_count = sum(
        1 for entry in enriched if entry.get("docker") and entry.get("conda")
    )
    print(f"看板软件 {len(records)} 个；鲲鹏域 L5 {len(l5)} 个")
    print(f"写入 {len(enriched)} 条 -> {args.out}")
    print(
        f"docker {docker_count} 个；conda {conda_count} 个；两者都有 {both_count} 个"
    )
    if no_version:
        print(f"缺有效版本、已跳过 {len(no_version)} 个：{', '.join(no_version)}")
    if conda_mismatch:
        print(f"conda 映射与看板上游不一致、已移除 {len(conda_mismatch)} 个：")
        for line in conda_mismatch:
            print(f"  {line}")
    if missing:
        print(
            f"目标仓没有对应目录、已跳过 {len(missing)} 个："
            + ", ".join(missing)
        )
    if ambiguous:
        print(f"命中多个目录（已按排序选择）{len(ambiguous)} 个：")
        for line in ambiguous:
            print(f"  {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
