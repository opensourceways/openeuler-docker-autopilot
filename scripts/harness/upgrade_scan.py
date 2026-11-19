#!/usr/bin/env python3
"""
Stage: 场景二 —— 应用升级候选发现（upgrade_scan）

**不查询 upstream-dashboard**：目标版本由软件清单（或 ``--version``）手动提供。
在目标仓克隆里按 ``{domain}/{app}/{version}/{os}/Dockerfile`` 定位，与本地已有
版本目录对比，产出：

- ``updates``：需要升级的应用矩阵
  ``[{app, domain, version, os_version, source_url, evidence}]``；
- ``audits``：目标版本的目录已存在、不能直接跳过的应用
  ``[{app, domain, version, os_version, dockerfile_path, source_url, evidence,
  has_test_script}]``，交给 ``upgrade_audit.py`` 做 AI 审计。

规则：
- 软件清单来自 ``config/upgrade-apps.yml``（人工维护，可用 ``--apps-file``
  指向子集），批量扫描**不遍历目标仓**；
- 每项必须有 ``app`` / ``domain``；自动升级还要求 ``version``（目标版本）与
  ``source_url``（上游仓库 HTTPS 地址，写入 task spec），缺失则跳过并记录原因；
- 清单项可选 ``tag``（上游 tag，如 ``slurm-26-05-6-1``）；不填则跳过 tag 校验；
- 手动 ``--app`` 可不在清单里：按目标仓目录反查 domain，必须同时给
  ``--version`` 与 ``--source-url``；
- 目标版本低于仓库现有版本（仅纯数字版本比较）或为 ``Undefined`` / ``latest``
  等占位值 → 跳过，避免降级 PR；
- 最新版本目录已存在 → **不跳过**，产出 audit；
- 目标分支已有 open PR → 跳过（已有升级在途）；
- os 目录沿用该应用最新的一个（不补齐所有 os 版本）；
- 证据只保留手动提供的信息（``source=manual``），不再抓看板采集项。

输入: --repo <目标仓克隆>，可选 --app / --version / --tag / --source-url /
      --apps-file / --limit / --audit-limit
输出: --format github-output → GITHUB_OUTPUT 写 updates/audits/skipped；--format json → stdout
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Callable

import yaml

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

from scripts.harness import testgen_scan  # noqa: E402
from scripts.lib.stage_common import log_stage  # noqa: E402
from scripts.lib.task_spec import _os_tag  # noqa: E402

DEFAULT_TARGET_REPO = "openeuler/openeuler-docker-images"
DEFAULT_APPS_FILE = os.path.join(PROJECT_ROOT, "config", "upgrade-apps.yml")


def _normalize_version(value: str) -> str:
    """`v1.2.3` / `V1.2.3` / `1.2.3` 视为同一版本。"""
    return str(value or "").strip().lstrip("vV").lower()


# 手写版本里也可能误填占位值；它们不能当目录名。
_PLACEHOLDER_VERSIONS = {"undefined", "latest", "null", "none", "unknown"}


def _numeric_version_key(value: str) -> tuple[int, ...] | None:
    """纯数字版本转成可比较的 key；含字母或占位值时返回 None。

    只用于拦截「目标版本低于仓库现有版本」的降级：跨项目的 rc/beta/commit
    等版本号没有统一排序，遇到就不做大小判断。
    """
    tokens = [
        token
        for token in re.split(
            r"[^0-9A-Za-z]+", str(value or "").strip().lstrip("vV")
        )
        if token
    ]
    if not tokens or not all(token.isdigit() for token in tokens):
        return None
    return tuple(int(token) for token in tokens)


def existing_versions(app_dir: Path) -> set[str]:
    return {
        _normalize_version(entry.name)
        for entry in app_dir.iterdir()
        if entry.is_dir()
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
        record = {"name": name or app, "app": app, "domain": domain}
        for field in ("version", "tag", "source_url"):
            value = str(entry.get(field) or "").strip()
            if value:
                record[field] = value
        apps.append(record)
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
    """清单外的应用：只在目标仓里反查 domain。"""
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


def _manual_evidence(
    *, name: str, version: str, tag: str, source_url: str
) -> dict:
    """版本由人工提供，证据只记录这次升级的输入，不抓看板。"""
    return {
        "source": "manual",
        "name": name,
        "version": version,
        "tag": tag,
        "tag_url": "",
        "commit_sha": "",
        "repo_url": source_url,
        "collector": [],
        "probe": {
            "source": "manual",
            "status": "skipped",
            "reason": "版本由清单手动提供，未查询看板/上游",
        },
    }


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
    pr_exists: Callable[[str, str, str], dict | None] | None = None,
    target_repo: str = DEFAULT_TARGET_REPO,
    token: str = "",
) -> dict:
    app_filter = app_filter.strip()
    entries = _select_apps(
        apps if apps is not None else load_apps(apps_file), app_filter
    )

    # 手动指定但不在清单里的应用：只按目标仓定位。
    ad_hoc = bool(app_filter) and not entries
    if ad_hoc:
        if not forced_version:
            raise SystemExit(
                f"{app_filter}: 不在软件清单里，手动升级必须同时指定 --version"
            )
        entries = [_find_repo_app(repo_dir, app_filter)]

    # task-spec 的 source_url 是必填项：版本已经手动提供，仓库地址也必须给。
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
        return {"updates": [], "audits": [], "skipped": skipped}

    updates: list[dict] = []
    audits: list[dict] = []
    for entry, app_dir in pairs:
        app = entry["app"]
        domain = entry["domain"]
        version = (forced_version or str(entry.get("version") or "")).strip()
        if not version:
            skipped.append(
                {
                    "app": app,
                    "reason": (
                        "清单未提供 version（自动升级只用手动提供的版本，"
                        "不查询看板）"
                    ),
                }
            )
            continue
        if version.lower() in _PLACEHOLDER_VERSIONS:
            skipped.append({"app": app, "reason": f"版本号无效（{version}）"})
            continue

        entry_source = source_url or str(entry.get("source_url") or "").strip()
        if not entry_source:
            skipped.append(
                {
                    "app": app,
                    "reason": (
                        "清单未提供 source_url（task spec 需要上游仓库 HTTPS 地址）"
                    ),
                }
            )
            continue
        tag = (
            forced_tag.strip()
            if forced_version
            else str(entry.get("tag") or "").strip()
        )

        dockerfile = testgen_scan.latest_dockerfile(app_dir)
        if dockerfile is None:
            skipped.append({"app": app, "reason": "应用目录下没有 */*/Dockerfile"})
            continue

        # 清单由人工维护时也可能填错方向；只判断「版本目录是否存在」会把降级
        # 当成升级，纯数字版本先做一次大小保护。
        current_version = dockerfile.parts[-3]
        new_key = _numeric_version_key(version)
        current_key = _numeric_version_key(current_version)
        if (
            not forced_version
            and new_key is not None
            and current_key is not None
            and new_key < current_key
        ):
            skipped.append(
                {
                    "app": app,
                    "reason": (
                        f"目标版本 {version} 低于仓库现有版本 "
                        f"{current_version}，跳过"
                    ),
                }
            )
            continue

        evidence = _manual_evidence(
            name=entry["name"], version=version, tag=tag, source_url=entry_source
        )

        if _normalize_version(version) in existing_versions(app_dir):
            if audit_limit and len(audits) >= audit_limit:
                skipped.append(
                    {
                        "app": app,
                        "reason": (
                            f"已有版本目录 {version}；"
                            f"审计数量达到上限 {audit_limit}"
                        ),
                    }
                )
                continue
            audits.append(
                {
                    "app": app,
                    "domain": domain,
                    "version": version,
                    "os_version": dockerfile.parts[-2],
                    "dockerfile_path": dockerfile.relative_to(repo_dir).as_posix(),
                    "source_url": entry_source,
                    "evidence": evidence,
                    "has_test_script": testgen_scan.has_any_test_script(app_dir),
                    "reason": f"已有版本目录 {version}，无需升级，转入 AI 审计",
                }
            )
            continue

        os_version = dockerfile.parts[-2]
        branch = f"auto/version-update/{app}/{version}-{_os_tag(os_version)}"
        if pr_exists is not None and token:
            if pr_exists(target_repo, branch, token):
                skipped.append({"app": app, "reason": f"已有 open PR（{branch}）"})
                continue

        updates.append(
            {
                "app": app,
                "domain": domain,
                "version": version,
                "os_version": os_version,
                "source_url": entry_source,
                "evidence": evidence,
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
    parser.add_argument("--version", default="", help="手动指定目标版本（配合 --app）")
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
        help="最多产出几个「已存在版本目录」的 AI 审计（0=不限）",
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
