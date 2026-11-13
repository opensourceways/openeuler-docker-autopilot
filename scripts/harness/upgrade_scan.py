#!/usr/bin/env python3
"""
Stage: 场景二 —— 应用升级候选发现（upgrade_scan）

每天（或手动）在目标仓克隆里枚举应用，用 upstream-dashboard 的
``/api/v1/version/resolve`` 解析每个软件的最新上游版本，与本地已有版本目录
对比，产出需要升级的应用矩阵：

    [{app, domain, version, os_version, source_url, evidence}]

规则：
- 只看 ``{domain}/{app}/{version}/{os}/Dockerfile``（复用 testgen_scan 的索引与排序）；
- ``blocked_reason`` 非 null → 跳过（记录原因；看板未解析出可用版本）；
- 最新版本已存在同名目录（去 ``v`` 前缀、忽略大小写）→ 跳过；
- 目标分支已有 open PR → 跳过；
- os 目录沿用该应用最新的一个（不补齐所有 os 版本）；
- 证据：``upstream_evidence.normalize`` + ``probe``（自探兜底），只作参考。

输入: --repo <目标仓克隆>，可选 --app / --version / --limit
输出: --format github-output → GITHUB_OUTPUT 写 updates=<json>；--format json → stdout
"""

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

from scripts.harness import testgen_scan  # noqa: E402
from scripts.lib import upstream_dashboard, upstream_evidence  # noqa: E402
from scripts.lib.stage_common import log_stage  # noqa: E402
from scripts.lib.task_spec import _os_tag  # noqa: E402

DEFAULT_TARGET_REPO = "openeuler/openeuler-docker-images"
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


def _candidate_apps(repo_dir: Path, app_filter: str) -> list[tuple[str, str]]:
    index = testgen_scan.index_target_apps(repo_dir)
    names = [app_filter] if app_filter else sorted(index)
    resolved: list[tuple[str, str]] = []
    for name in names:
        matches = index.get(testgen_scan.normalize_name(name), [])
        if len(matches) != 1:
            if app_filter:
                raise SystemExit(
                    f"{name}: 在目标仓里找不到唯一应用目录（命中 {matches}）"
                )
            continue
        resolved.append(matches[0])
    return resolved


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
    resolve: Callable[..., dict | None] = upstream_dashboard.resolve_version,
    probe: Callable[[dict | None], dict] = upstream_evidence.probe,
    pr_exists: Callable[[str, str, str], dict | None] | None = None,
    target_repo: str = DEFAULT_TARGET_REPO,
    token: str = "",
) -> dict:
    apps = _candidate_apps(repo_dir, app_filter.strip())
    if not apps:
        return {"updates": [], "skipped": []}

    skipped: list[dict] = []
    if forced_version:
        # 手动指定版本：不查看板，其余照常对比本地目录。
        payloads: list[tuple[dict | None, dict]] = [
            (
                {
                    "name": app,
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
            for _, app in apps
        ]
    elif app_filter:
        payloads = [_resolve_one(apps[0][1], resolve=resolve, probe=probe)]
    else:
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(apps))) as pool:
            payloads = list(
                pool.map(
                    lambda pair: _resolve_one(pair[1], resolve=resolve, probe=probe),
                    apps,
                )
            )

    updates: list[dict] = []
    for (domain, app), (payload, probe_result) in zip(apps, payloads):
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

        app_dir = repo_dir / domain / app
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
