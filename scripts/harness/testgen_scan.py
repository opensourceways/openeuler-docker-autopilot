#!/usr/bin/env python3
"""
Stage: 场景四 —— 指定软件的目标镜像解析（testgen_resolve）

手动触发场景：给定一个软件名，在目标仓克隆里定位它的最新镜像目录
`{domain}/{app}/{version}/{os_version}/Dockerfile`，产出 testgen_generate
需要的一条 item。本阶段只读本地克隆，不发任何网络请求。

输入: --app <应用名>（必填）、--domain <域目录>（可选，同名跨域时消歧）、
      --source-url <上游仓库链接>（可选，仅作为生成提示）、
      --repo <目标仓克隆目录>（默认 env SOURCE_REPO_DIR / PROJECT_ROOT/source-repo）
输出: --format github-output → GITHUB_OUTPUT 写 item=<json>；--format json → stdout
退出码: 应用不存在 / 同名有歧义 / 缺 Dockerfile / 已有 test.sh → 非 0
        （人工触发应当直接报错，不静默跳过）
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

from scripts.lib.stage_common import log_stage  # noqa: E402
from scripts.lib.task_spec import _DOMAINS  # noqa: E402

DOMAIN_DIRECTORIES = tuple(sorted(_DOMAINS.values()))

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


def version_dockerfile(app_dir: Path, version: str) -> Path | None:
    """目标版本目录自己的 Dockerfile；同版本多条 OS 线时取最高 OS。

    审计必须锁定清单给出的版本目录，不能沿用 ``latest_dockerfile``：
    应用同时存在 ``master`` 这类浮动目录时，它按字典序排在固定哈希目录前面，
    会被误当成“最新版本”，导致修复改错目录、tag/meta 全部对不上。
    """
    target = version.strip().lstrip("vV").lower()
    candidates = [
        dockerfile
        for dockerfile in app_dir.glob("*/*/Dockerfile")
        if dockerfile.parts[-3].strip().lstrip("vV").lower() == target
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda dockerfile: _version_key(dockerfile.parts[-2]),
    )


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


def resolve_item(
    *,
    repo_dir: Path,
    app: str,
    domain: str = "",
    source_url: str = "",
) -> dict:
    """Locate ``app`` in the clone and build the testgen item for it."""
    matches = index_target_apps(repo_dir).get(normalize_name(app), [])
    if domain:
        wanted = domain.strip().lower()
        matches = [m for m in matches if m[0].lower() == wanted]
    if not matches:
        raise SystemExit(
            f"{app}: 在目标仓里找不到应用目录"
            + (f"（domain={domain}）" if domain else "")
        )
    if len(matches) > 1:
        raise SystemExit(
            f"{app}: 命中多个同名目录 {matches}，请用 --domain 指定"
        )

    app_domain, app_name = matches[0]
    app_dir = repo_dir / app_domain / app_name
    if has_any_test_script(app_dir):
        raise SystemExit(
            f"{app}: 已有功能测试脚本（tests/test.sh 等），本次不覆盖"
        )
    dockerfile = latest_dockerfile(app_dir)
    if dockerfile is None:
        raise SystemExit(f"{app}: 目录 {app_domain}/{app_name} 下没有 */*/Dockerfile")

    return {
        "app": app_name,
        "domain": app_domain,
        "version": dockerfile.parts[-3],
        "os_version": dockerfile.parts[-2],
        "source_url": source_url.strip(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("SOURCE_REPO_DIR", ""))
    parser.add_argument("--app", required=True, help="应用名（目标仓目录名）")
    parser.add_argument("--domain", default="", help="域目录，同名跨域时用来消歧")
    parser.add_argument("--source-url", default="", help="上游仓库链接（可选）")
    parser.add_argument(
        "--format",
        choices=("json", "github-output"),
        default="json",
    )
    args = parser.parse_args()

    repo_dir = Path(args.repo or os.path.join(PROJECT_ROOT, "source-repo"))
    if not repo_dir.is_dir():
        raise SystemExit(f"target repo clone not found: {repo_dir}")

    item = resolve_item(
        repo_dir=repo_dir,
        app=args.app,
        domain=args.domain,
        source_url=args.source_url,
    )
    log_stage(
        "testgen",
        f"resolved {item['app']} -> {item['domain']}/{item['app']}/"
        f"{item['version']}/{item['os_version']}",
    )

    if args.format == "github-output":
        github_output = os.environ.get("GITHUB_OUTPUT", "")
        if not github_output:
            raise SystemExit("GITHUB_OUTPUT is not set (not running in Actions)")
        with open(github_output, "a", encoding="utf-8") as handle:
            handle.write(f"item={json.dumps(item, ensure_ascii=False)}\n")
    else:
        print(json.dumps(item, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
