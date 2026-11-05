#!/usr/bin/env python3
"""
Stage: 场景四扫描（testgen_scan）

爬 Kunpeng 上游看板获取软件目录 → 与克隆的目标仓库对比，宽松匹配出
「有镜像目录但缺功能测试脚本」的应用 → 跳过已 exhausted / 已 done /
已有 open PR 的 → 截取本轮限量，输出候选 JSON。

输入: --repo <目标仓克隆目录>（或 env SOURCE_REPO_DIR）
      env TESTGEN_LIMIT（默认 10）, GITCODE_TOKEN, TESTGEN_DASHBOARD_BASE,
      可选 --app <name> 只处理一个软件（单软件调试）
输出: --format github-output → GITHUB_OUTPUT 写 candidates=<json>；
      --format json → stdout 打印 {"candidates": [...], "skipped": [...]}
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

from scripts.lib.ci_gitcode_api import find_any_pr_by_head_branch  # noqa: E402
from scripts.lib.stage_common import log_stage, normalize_repo  # noqa: E402
from scripts.lib.task_spec import _DOMAINS  # noqa: E402
from scripts.lib.testgen_dashboard import fetch_dashboard_software  # noqa: E402
from scripts.lib.testgen_state import is_done, is_exhausted  # noqa: E402

DOMAIN_DIRECTORIES = tuple(sorted(_DOMAINS.values()))
DEFAULT_LIMIT = 10
DEFAULT_TARGET_REPO = "openeuler/openeuler-docker-images"

_NORMALIZE_SPLIT_RE = re.compile(r"[-_.\s]+")


def normalize_name(name: str) -> str:
    """Case/separator-insensitive key: ClickHouse == clickhouse == click_house."""
    return _NORMALIZE_SPLIT_RE.sub("-", name.strip().lower()).strip("-")


def branch_name(app: str) -> str:
    return f"auto/test-script/{app}"


def has_any_test_script(app_dir: Path) -> bool:
    """True when any of the three CI search locations already holds a test."""
    if (app_dir / "tests" / "test.sh").is_file():
        return True
    if (app_dir / "test.sh").is_file():
        return True
    return any(app_dir.glob(f"*/*/test.sh"))


def _version_key(name: str):
    """Numeric-aware sort key so 1.10.0 sorts above 1.9.0.

    Dot/dash-separated segments compare numerically when both are digits,
    lexically otherwise (24.03-lts-sp4 > 22.03-lts-sp3).  The trailing spN
    suffix stays lexical, which is fine: the os choice only decides which
    CI build this round triggers.
    """
    key: list[tuple[int, int, str]] = []
    for part in re.split(r"[.-]", name):
        if part.isdigit():
            key.append((1, int(part), ""))
        else:
            key.append((0, 0, part.lower()))
    return tuple(key)


def latest_dockerfile(app_dir: Path) -> Path | None:
    """The highest (version, os) Dockerfile under the app directory."""
    best: Path | None = None
    best_key: tuple | None = None
    for dockerfile in app_dir.glob("*/*/Dockerfile"):
        key = (_version_key(dockerfile.parts[-3]), _version_key(dockerfile.parts[-2]))
        if best is None or key > best_key:
            best = dockerfile
            best_key = key
    return best


def index_target_apps(repo_dir: Path) -> dict[str, list[tuple[str, str]]]:
    """normalized app name -> [(domain, app)] over every known domain."""
    index: dict[str, list[tuple[str, str]]] = {}
    for domain in DOMAIN_DIRECTORIES:
        domain_dir = repo_dir / domain
        if not domain_dir.is_dir():
            continue
        for entry in sorted(domain_dir.iterdir()):
            if not entry.is_dir():
                continue
            index.setdefault(normalize_name(entry.name), []).append(
                (domain, entry.name)
            )
    return index


def find_candidates(
    *,
    repo_dir: Path,
    limit: int,
    app_filter: str | None = None,
    token: str = "",
    target_repo: str = DEFAULT_TARGET_REPO,
) -> dict:
    """Match the dashboard catalogue against the clone, return candidates."""
    software = fetch_dashboard_software()
    if software is None:
        log_stage("testgen", "dashboard unreachable; skipping this round")
        return {"candidates": [], "skipped": [], "dashboard_unreachable": True}

    index = index_target_apps(repo_dir)
    candidates: list[dict] = []
    skipped: list[dict] = []

    for item in software:
        if app_filter and item.name != app_filter:
            continue
        matches = index.get(normalize_name(item.name), [])
        if not matches:
            skipped.append({"name": item.name, "reason": "no target-repo directory matched"})
            continue
        if len(matches) > 1:
            skipped.append(
                {"name": item.name, "reason": f"ambiguous match: {matches}"}
            )
            continue
        domain, app = matches[0]
        app_dir = repo_dir / domain / app

        if is_exhausted(app):
            skipped.append({"name": item.name, "reason": "exhausted (needs human review)"})
            continue
        if is_done(app):
            skipped.append({"name": item.name, "reason": "already delivered"})
            continue
        if has_any_test_script(app_dir):
            skipped.append({"name": item.name, "reason": "test.sh already present"})
            continue
        dockerfile = latest_dockerfile(app_dir)
        if dockerfile is None:
            skipped.append({"name": item.name, "reason": "app directory has no Dockerfile"})
            continue
        if token and find_any_pr_by_head_branch(
            target_repo, branch_name(app), token, open_only=True
        ):
            skipped.append({"name": item.name, "reason": "open PR already exists"})
            continue

        version = dockerfile.parts[-3]
        os_version = dockerfile.parts[-2]
        candidates.append(
            {
                "app": app,
                "domain": domain,
                "version": version,
                "os_version": os_version,
                "source_url": item.repo_url,
                "dashboard_name": item.name,
            }
        )
        if len(candidates) >= limit:
            break

    return {"candidates": candidates, "skipped": skipped, "total": len(software)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("SOURCE_REPO_DIR", ""))
    parser.add_argument(
        "--format",
        choices=("json", "github-output"),
        default="json",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=int(os.environ.get("TESTGEN_LIMIT", DEFAULT_LIMIT)),
    )
    parser.add_argument(
        "--app",
        default="",
        help="restrict the scan to one dashboard software name (debug mode)",
    )
    args = parser.parse_args()

    repo_dir = Path(args.repo or os.path.join(PROJECT_ROOT, "source-repo"))
    if not repo_dir.is_dir():
        raise SystemExit(f"target repo clone not found: {repo_dir}")

    token = os.environ.get("GITCODE_TOKEN", "").strip()
    target_repo = normalize_repo(
        os.environ.get("TARGET_REPO", DEFAULT_TARGET_REPO)
    ) or DEFAULT_TARGET_REPO

    result = find_candidates(
        repo_dir=repo_dir,
        limit=args.limit,
        app_filter=args.app or None,
        token=token,
        target_repo=target_repo,
    )
    log_stage(
        "testgen",
        f"scan done candidates={len(result['candidates'])} "
        f"skipped={len(result['skipped'])}",
    )

    if args.format == "github-output":
        github_output = os.environ.get("GITHUB_OUTPUT", "")
        if not github_output:
            raise SystemExit("GITHUB_OUTPUT is not set (not running in Actions)")
        with open(github_output, "a", encoding="utf-8") as handle:
            handle.write(f"candidates={json.dumps(result['candidates'])}\n")
        print(json.dumps(result["skipped"], ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
