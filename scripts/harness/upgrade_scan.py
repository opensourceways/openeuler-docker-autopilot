#!/usr/bin/env python3
"""
Stage: 场景二 —— 应用升级候选发现（upgrade_scan）

每天（或手动）在目标仓克隆里枚举应用，用 upstream-dashboard 的
``/api/v1/version/resolve`` 解析每个软件的最新上游版本，与本地已有版本目录
对比，产出：

- ``updates``：需要升级的应用矩阵
  ``[{app, domain, version, os_version, source_url, evidence}]``；
- ``audits``：已是最新版本、不能直接跳过的应用
  ``[{app, domain, version, os_version, dockerfile_path, source_url, evidence,
  has_test_script}]``，交给 ``upgrade_audit.py`` 做 AI 审计。

规则：
- 软件清单来自 ``config/upgrade-apps.yml``（人工维护，初始由
  ``scripts/utils/scrape_upgrade_apps.py`` 从看板生成），批量扫描**不遍历目标仓**；
  手动 ``--app`` 指定的应用可以不在清单里：按目标仓目录反查 domain，不看看板，
  必须同时用 ``--version`` 指定目标版本；
- 每个软件按 ``{domain}/{app}/{version}/{os}/Dockerfile`` 定位（复用
  testgen_scan 的排序）；
- ``blocked_reason`` 非 null → 跳过（记录原因；看板未解析出可用版本）；
- 最新版本已存在同名目录（去 ``v`` 前缀、忽略大小写）→ **不跳过**，产出 audit；
- 目标分支已有 open PR → 跳过（已有升级在途）；
- os 目录沿用该应用最新的一个（不补齐所有 os 版本）；
- 证据：``upstream_evidence.normalize`` + ``upstream_dashboard.fetch_evidence``
  （看板 ``/api/v1/software`` 采集证据，固定 L1 的 3 条）+ ``probe``（自探兜底），
  只作参考，抓取失败不阻断升级。

输入: --repo <目标仓克隆>，可选 --app / --version / --tag / --source-url /
      --apps-file / --limit / --audit-limit
输出: --format github-output → GITHUB_OUTPUT 写 updates/audits/skipped；--format json → stdout
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
    trimmed["collector"] = [
        _trim_mapping(item) for item in collector[:_MAX_COLLECTOR_ITEMS]
    ]
    raw = trimmed.get("raw") or {}
    trimmed["raw"] = _trim_mapping(raw)
    return trimmed


def _trim_mapping(value: dict) -> dict:
    if not isinstance(value, dict):
        return value
    return {
        key: (item if len(str(item)) <= _MAX_RAW_CHARS else str(item)[:_MAX_RAW_CHARS] + "…")
        for key, item in value.items()
    }


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
    return [
        entry
        for entry in apps
        if key
        in {
            testgen_scan.normalize_name(entry["app"]),
            testgen_scan.normalize_name(entry["name"]),
        }
    ]


def _find_repo_app(repo_dir: Path, app_filter: str) -> dict:
    """清单外的应用：只在目标仓里反查 domain，不看看板。"""
    key = testgen_scan.normalize_name(app_filter)
    matches = [
        {"name": app_filter, "app": child.name, "domain": parent.name}
        for parent in sorted(repo_dir.iterdir())
        if parent.is_dir()
        for child in sorted(parent.iterdir())
        if child.is_dir() and testgen_scan.normalize_name(child.name) == key
    ]
    if not matches:
        raise SystemExit(
            f"{app_filter}: 不在软件清单里，目标仓也没有这个应用目录"
        )
    if len(matches) > 1:
        raise SystemExit(
            f"{app_filter}: 软件清单里没有，且目标仓命中多个目录 "
            f"{[(m['domain'], m['app']) for m in matches]}"
        )
    return matches[0]


def _resolve_one(
    name: str,
    *,
    resolve: Callable[..., dict | None],
    probe: Callable[[dict | None], dict],
) -> tuple[dict | None, dict]:
    payload = resolve(name)
    return payload, probe(payload)


def _build_evidence(
    name: str,
    new_version: str,
    payload: dict,
    probe_result: dict,
    fetch_evidence: Callable[[str, str], list[dict]] | None,
) -> dict:
    evidence = upstream_evidence.normalize(payload)
    evidence["probe"] = probe_result
    collector = list(evidence.get("collector") or [])
    if fetch_evidence is not None:
        try:
            collector.extend(fetch_evidence(name, new_version))
        except Exception as error:  # 证据只作参考，抓取失败不能阻断升级
            log_stage(
                "upgrade-scan",
                f"{name}: 证据包抓取失败（非阻断）: {error}",
            )
    evidence["collector"] = collector
    return _trim_evidence(evidence)


def find_updates(
    *,
    repo_dir: Path,
    app_filter: str = "",
    forced_version: str = "",
    forced_tag: str = "",
    source_url: str = "",
    limit: int = 0,
    audit_limit: int = 0,
    apps: list[dict] | None = None,
    apps_file: str | Path | None = None,
    resolve: Callable[..., dict | None] = upstream_dashboard.resolve_version,
    probe: Callable[[dict | None], dict] = upstream_evidence.probe,
    fetch_evidence: Callable[[str, str], list[dict]] | None = (
        upstream_dashboard.fetch_evidence
    ),
    pr_exists: Callable[[str, str, str], dict | None] | None = None,
    target_repo: str = DEFAULT_TARGET_REPO,
    token: str = "",
) -> dict:
    app_filter = app_filter.strip()
    entries = _select_apps(apps if apps is not None else load_apps(apps_file), app_filter)

    # 手动指定但不在清单里的应用：只按目标仓定位，不看看板。
    ad_hoc = bool(app_filter) and not entries
    if ad_hoc:
        if not forced_version:
            raise SystemExit(
                f"{app_filter}: 不在软件清单里，手动升级必须同时指定 --version"
                "（清单外应用不查看看板）"
            )
        entries = [_find_repo_app(repo_dir, app_filter)]
        evidence_fetch = None
    else:
        evidence_fetch = fetch_evidence

    # task-spec 的 source_url 是必填项：手动升级跳过了看板，必须由调用方给出。
    source_url = source_url.strip()
    if forced_version and not source_url:
        raise SystemExit(
            "手动指定 --version 时必须同时提供 --source-url"
            "（上游仓库 HTTPS 地址，用于 task spec）"
        )

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
                        "（尚未入库，待场景一新建镜像）"
                    ),
                }
            )
            continue
        pairs.append((entry, app_dir))
    if not pairs:
        return {"updates": [], "skipped": skipped}
    if forced_version:
        # 手动指定版本：不查看板，其余照常对比本地目录。
        # tag 不能拿版本号冒充（slurm 的版本是 26.05.6.1，上游 tag 却是
        # slurm-26-05-6-1）；没给 tag 就留空，后续审计/修复会跳过 tag 校验。
        forced_tag = forced_tag.strip()
        if not forced_tag:
            log_stage(
                "upgrade-scan",
                "手动指定版本但未给 tag，本次跳过 tag 校验（需要时请同时填 tag）",
            )
        payloads: list[tuple[dict | None, dict]] = [
            (
                {
                    "name": entry["name"],
                    "version": forced_version,
                    "tag": forced_tag,
                    "repo_url": source_url,
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
    audits: list[dict] = []
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
            if audit_limit and len(audits) >= audit_limit:
                skipped.append(
                    {
                        "app": app,
                        "reason": (
                            f"已有版本目录 {new_version}；"
                            f"审计数量达到上限 {audit_limit}"
                        ),
                    }
                )
                continue
            audits.append(
                {
                    "app": app,
                    "domain": domain,
                    "version": new_version,
                    "os_version": dockerfile.parts[-2],
                    "dockerfile_path": dockerfile.relative_to(repo_dir).as_posix(),
                    "source_url": str(payload.get("repo_url") or ""),
                    "evidence": _build_evidence(
                        entry["name"],
                        new_version,
                        payload,
                        probe_result,
                        evidence_fetch,
                    ),
                    "has_test_script": testgen_scan.has_any_test_script(app_dir),
                    "reason": f"已有版本目录 {new_version}，无需升级，转入 AI 审计",
                }
            )
            continue

        os_version = dockerfile.parts[-2]
        branch = f"auto/version-update/{app}/{new_version}-{_os_tag(os_version)}"
        if pr_exists is not None and token:
            if pr_exists(target_repo, branch, token):
                skipped.append({"app": app, "reason": f"已有 open PR（{branch}）"})
                continue

        updates.append(
            {
                "app": app,
                "domain": domain,
                "version": new_version,
                "os_version": os_version,
                "source_url": str(payload.get("repo_url") or ""),
                "evidence": _build_evidence(
                    entry["name"],
                    new_version,
                    payload,
                    probe_result,
                    evidence_fetch,
                ),
            }
        )
        if limit and len(updates) >= limit:
            break

    return {"updates": updates, "audits": audits, "skipped": skipped}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("SOURCE_REPO_DIR", ""))
    parser.add_argument(
        "--app",
        default="",
        help="只处理这一个应用（可不在软件清单里，此时需配合 --version）",
    )
    parser.add_argument("--version", default="", help="手动指定目标版本（跳过看板解析）")
    parser.add_argument(
        "--tag",
        default="",
        help="手动指定版本对应的上游 tag（如 slurm-26-05-6-1；留空则跳过 tag 校验）",
    )
    parser.add_argument(
        "--source-url",
        default="",
        help="手动升级时的上游仓库 HTTPS 地址（配合 --version，写入 task spec）",
    )
    parser.add_argument(
        "--apps-file",
        default=os.environ.get("UPGRADE_APPS_FILE", ""),
        help=f"软件清单（默认 {DEFAULT_APPS_FILE}）",
    )
    parser.add_argument("--limit", type=int, default=0, help="最多产出几个升级（0=不限）")
    parser.add_argument(
        "--audit-limit",
        type=int,
        default=0,
        help="最多产出几个「已是最新版本」的 AI 审计（0=不限）",
    )
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
        forced_tag=args.tag,
        source_url=args.source_url,
        limit=args.limit,
        audit_limit=args.audit_limit,
        apps_file=args.apps_file or None,
        pr_exists=find_any_pr_by_head_branch,
        target_repo=os.environ.get("TARGET_REPO", DEFAULT_TARGET_REPO),
        token=os.environ.get("GITCODE_TOKEN", "").strip(),
    )
    log_stage(
        "upgrade-scan",
        "updates={} audits={} skipped={}".format(
            len(result["updates"]), len(result["audits"]), len(result["skipped"])
        ),
    )

    if args.format == "github-output":
        github_output = os.environ.get("GITHUB_OUTPUT", "")
        if not github_output:
            raise SystemExit("GITHUB_OUTPUT is not set (not running in Actions)")
        with open(github_output, "a", encoding="utf-8") as handle:
            handle.write(f"updates={json.dumps(result['updates'], ensure_ascii=False)}\n")
            handle.write(f"audits={json.dumps(result['audits'], ensure_ascii=False)}\n")
            handle.write(f"skipped={json.dumps(result['skipped'], ensure_ascii=False)}\n")
        print(json.dumps(result["skipped"], ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
