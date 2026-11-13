#!/usr/bin/env python3
"""
Stage: 场景二 —— 应用升级候选发现（upgrade_scan）

每天（或手动）在目标仓克隆里枚举应用，用 upstream-dashboard 的
``/api/v1/version/resolve`` 解析每个软件的最新上游版本，与本地已有版本目录
对比，产出需要升级的应用矩阵：

    [{app, domain, version, os_version, source_url, evidence}]

规则：
- 软件清单来自 ``config/upgrade-apps.yml``（人工维护，初始由
  ``scripts/utils/scrape_upgrade_apps.py`` 从看板生成），**不遍历目标仓**；
- 每个软件按 ``{domain}/{app}/{version}/{os}/Dockerfile`` 定位（复用
  testgen_scan 的排序）；
- ``blocked_reason`` 非 null → 跳过（记录原因；看板未解析出可用版本）；
- 最新版本已存在同名目录（去 ``v`` 前缀、忽略大小写）→ 跳过；
- 目标分支已有 open PR → 跳过；
- os 目录沿用该应用最新的一个（不补齐所有 os 版本）；
- 证据：``upstream_evidence.normalize`` + ``probe``（自探兜底），只作参考。

输入: --repo <目标仓克隆>，可选 --app / --version / --apps-file / --limit
输出: --format github-output → GITHUB_OUTPUT 写 updates=<json>；--format json → stdout
"""

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

import yaml

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

from scripts.harness import testgen_scan  # noqa: E402
from scripts.lib import upstream_dashboard, upstream_evidence  # noqa: E402
from scripts.lib.stage_common import log_stage  # noqa: E402
from scripts.lib.task_spec import _os_tag  # noqa: E402

DEFAULT_TARGET_REPO = "openeuler/openeuler-docker-images"
DEFAULT_APPS_FILE = os.path.join(PROJECT_ROOT, "config", "upgrade-apps.yml")
MAX_WORKERS = 8
# 矩阵 payload 走 workflow output，证据只保留参考价值最高的部分，避免超长。
_MAX_RAW_CHARS = 400
_MAX_COLLECTOR_ITEMS = 20


def _normalize_version(value: str) -> str:
    """`v1.2.3` / `V1.2.3` / `1.2.3` 视为同一版本。"""
    return str(value or "").strip().lstrip("vV").lower()


def existing_versions(app_dir: Path) -> set[str]:
    return {
        _normalize_version(entry.name)
        for entry in app_dir.iterdir()
        if entry.is_dir()
    }


def _trim_evidence(evidence: dict) -> dict:
    trimmed = dict(evidence)
    collector = trimmed.get("collector") or []
    trimmed["collector"] = collector[:_MAX_COLLECTOR_ITEMS]
    raw = trimmed.get("raw") or {}
    trimmed["raw"] = {
        key: (value if len(str(value)) <= _MAX_RAW_CHARS else str(value)[:_MAX_RAW_CHARS] + "…")
        for key, value in raw.items()
    }
    return trimmed


def load_apps(path: str | Path | None = None) -> list[dict]:
    """读取人工维护的软件清单；格式错误直接失败，避免静默少扫。"""
    apps_file = Path(path or DEFAULT_APPS_FILE)
    if not apps_file.is_file():
        raise SystemExit(f"apps file not found: {apps_file}")
    data = yaml.safe_load(apps_file.read_text(encoding="utf-8")) or {}
    entries = data.get("apps") if isinstance(data, dict) else data
    if not isinstance(entries, list) or not entries:
        raise SystemExit(f"{apps_file}: 需要非空的 apps 列表")

    apps: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise SystemExit(f"{apps_file}: apps 里的每一项必须是对象")
        name = str(entry.get("name") or entry.get("app") or "").strip()
        app = str(entry.get("app") or "").strip()
        domain = str(entry.get("domain") or "").strip()
        if not app or not domain:
            raise SystemExit(f"{apps_file}: app / domain 不能为空（{entry!r}）")
        key = (domain, app)
        if key in seen:
            continue
        seen.add(key)
        apps.append({"name": name or app, "app": app, "domain": domain})
    return apps


def _select_apps(apps: list[dict], app_filter: str) -> list[dict]:
    if not app_filter:
        return apps
    key = testgen_scan.normalize_name(app_filter)
    matches = [
        entry
        for entry in apps
        if key
        in {
            testgen_scan.normalize_name(entry["app"]),
            testgen_scan.normalize_name(entry["name"]),
        }
    ]
    if not matches:
        raise SystemExit(
            f"{app_filter}: 不在软件清单里（app=config/upgrade-apps.yml）"
        )
    if len(matches) > 1:
        raise SystemExit(
            f"{app_filter}: 软件清单命中多个条目 "
            f"{[(m['domain'], m['app']) for m in matches]}"
        )
    return matches


def _resolve_one(
    name: str,
    *,
    resolve: Callable[..., dict | None],
    probe: Callable[[dict | None], dict],
) -> tuple[dict | None, dict]:
    payload = resolve(name)
    return payload, probe(payload)


def find_updates(
    *,
    repo_dir: Path,
    app_filter: str = "",
    forced_version: str = "",
    limit: int = 0,
    apps: list[dict] | None = None,
    apps_file: str | Path | None = None,
    resolve: Callable[..., dict | None] = upstream_dashboard.resolve_version,
    probe: Callable[[dict | None], dict] = upstream_evidence.probe,
    pr_exists: Callable[[str, str, str], dict | None] | None = None,
    target_repo: str = DEFAULT_TARGET_REPO,
    token: str = "",
) -> dict:
    entries = _select_apps(apps if apps is not None else load_apps(apps_file), app_filter.strip())

    skipped: list[dict] = []
    pairs: list[tuple[dict, Path]] = []
    for entry in entries:
        app_dir = repo_dir / entry["domain"] / entry["app"]
        if not app_dir.is_dir():
            skipped.append(
                {
                    "app": entry["app"],
                    "reason": (
                        f"目标仓没有 {entry['domain']}/{entry['app']}"
                        "（软件清单配置过期）"
                    ),
                }
            )
            continue
        pairs.append((entry, app_dir))
    if not pairs:
        return {"updates": [], "skipped": skipped}

    if forced_version:
        # 手动指定版本：不查看板，其余照常对比本地目录。
        payloads: list[tuple[dict | None, dict]] = [
            (
                {
                    "name": entry["name"],
                    "version": forced_version,
                    "tag": forced_version,
                    "source": "manual",
                },
                {
                    "source": "self-probe",
                    "status": "skipped",
                    "reason": "手动指定版本，未做自探",
                },
            )
            for entry, _ in pairs
        ]
    elif app_filter:
        payloads = [_resolve_one(pairs[0][0]["name"], resolve=resolve, probe=probe)]
    else:
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(pairs))) as pool:
            payloads = list(
                pool.map(
                    lambda pair: _resolve_one(pair[0]["name"], resolve=resolve, probe=probe),
                    pairs,
                )
            )

    updates: list[dict] = []
    for (entry, app_dir), (payload, probe_result) in zip(pairs, payloads):
        app = entry["app"]
        domain = entry["domain"]
        if payload is None:
            skipped.append({"app": app, "reason": "看板 400/404（软件不存在或入参非法）"})
            continue
        if not upstream_dashboard.is_usable(payload):
            skipped.append(
                {
                    "app": app,
                    "reason": f"blocked_reason={payload.get('blocked_reason')}",
                }
            )
            continue

        dockerfile = testgen_scan.latest_dockerfile(app_dir)
        if dockerfile is None:
            skipped.append({"app": app, "reason": "应用目录下没有 */*/Dockerfile"})
            continue

        new_version = str(forced_version or payload.get("version") or "").strip()
        if not new_version:
            skipped.append({"app": app, "reason": "看板未给出可用版本号"})
            continue
        if _normalize_version(new_version) in existing_versions(app_dir):
            skipped.append({"app": app, "reason": f"已有版本目录 {new_version}"})
            continue

        os_version = dockerfile.parts[-2]
        branch = f"auto/version-update/{app}/{new_version}-{_os_tag(os_version)}"
        if pr_exists is not None and token:
            if pr_exists(target_repo, branch, token):
                skipped.append({"app": app, "reason": f"已有 open PR（{branch}）"})
                continue

        evidence = upstream_evidence.normalize(payload)
        evidence["probe"] = probe_result
        updates.append(
            {
                "app": app,
                "domain": domain,
                "version": new_version,
                "os_version": os_version,
                "source_url": str(payload.get("repo_url") or ""),
                "evidence": _trim_evidence(evidence),
            }
        )
        if limit and len(updates) >= limit:
            break

    return {"updates": updates, "skipped": skipped}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("SOURCE_REPO_DIR", ""))
    parser.add_argument("--app", default="", help="只处理这一个应用")
    parser.add_argument("--version", default="", help="手动指定目标版本（跳过看板解析）")
    parser.add_argument(
        "--apps-file",
        default=os.environ.get("UPGRADE_APPS_FILE", ""),
        help=f"软件清单（默认 {DEFAULT_APPS_FILE}）",
    )
    parser.add_argument("--limit", type=int, default=0, help="最多产出几个升级（0=不限）")
    parser.add_argument("--format", choices=("json", "github-output"), default="json")
    args = parser.parse_args()

    repo_dir = Path(args.repo or os.path.join(PROJECT_ROOT, "source-repo"))
    if not repo_dir.is_dir():
        raise SystemExit(f"target repo clone not found: {repo_dir}")

    from scripts.lib.ci_gitcode_api import find_any_pr_by_head_branch

    result = find_updates(
        repo_dir=repo_dir,
        app_filter=args.app,
        forced_version=args.version,
        limit=args.limit,
        apps_file=args.apps_file or None,
        pr_exists=find_any_pr_by_head_branch,
        target_repo=os.environ.get("TARGET_REPO", DEFAULT_TARGET_REPO),
        token=os.environ.get("GITCODE_TOKEN", "").strip(),
    )
    log_stage(
        "upgrade-scan",
        f"updates={len(result['updates'])} skipped={len(result['skipped'])}",
    )

    if args.format == "github-output":
        github_output = os.environ.get("GITHUB_OUTPUT", "")
        if not github_output:
            raise SystemExit("GITHUB_OUTPUT is not set (not running in Actions)")
        with open(github_output, "a", encoding="utf-8") as handle:
            handle.write(f"updates={json.dumps(result['updates'], ensure_ascii=False)}\n")
        print(json.dumps(result["skipped"], ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
