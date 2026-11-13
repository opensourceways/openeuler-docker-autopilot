#!/usr/bin/env python3
"""场景二交付：为一个已通过双架构验证的升级分支创建跨仓 PR。"""

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

from scripts.lib import upstream_evidence  # noqa: E402
from scripts.lib.ci_gitcode_api import create_pull_request  # noqa: E402
from scripts.lib.stage_common import log_stage, normalize_repo  # noqa: E402

DEFAULT_TARGET_REPO = "openeuler/openeuler-docker-images"
DEFAULT_TARGET_BRANCH = "master"

_TEST_STATUS_TEXT = {
    "added": "本次 PR 新增 `tests/test.sh`（AI 生成 + 静态校验通过）",
    "existing": "该应用已有 `tests/test.sh`，本次未改动",
    "pending": "该应用缺 `tests/test.sh`，本次生成未通过（非阻断，可手动触发 Generate Test Scripts 补）",
}


def build_body(item: dict, test_status: str) -> str:
    app = item["app"]
    version = item["version"]
    domain = item["domain"]
    os_version = item["os_version"]
    lines = [
        f"本 PR 把 **{app}** 升级到上游 **{version}**（openEuler `{os_version}`）。",
        "",
        "## 变更",
        "",
        f"- 新增镜像目录：`{domain}/{app}/{version}/{os_version}/`",
        f"- 复用上一版本目录结构，确定性替换版本号：`{domain}/{app}/<旧版本>/{os_version}` → 新版本",
        f"- `meta.yml` 追加 `{version}` 条目",
        "",
        f"## 功能测试",
        "",
        f"- {_TEST_STATUS_TEXT.get(test_status, test_status or 'unknown')}",
        "",
        upstream_evidence.render_markdown(item.get("evidence")),
        "",
        "> 本 PR 由场景二（应用自动升级）生成；双架构原生构建 + 功能测试已在自托管 Runner 上通过。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--item", required=True, help="升级 item JSON")
    parser.add_argument("--branch", required=True)
    parser.add_argument("--push-repo", default="")
    parser.add_argument("--test-status", default="pending")
    parser.add_argument("--target-repo", default=os.environ.get("TARGET_REPO", DEFAULT_TARGET_REPO))
    parser.add_argument("--base", default=os.environ.get("TARGET_BRANCH", DEFAULT_TARGET_BRANCH))
    args = parser.parse_args()

    import json

    item = json.loads(args.item)
    token = (os.environ.get("GITCODE_TOKEN") or "").strip()
    if not token:
        raise SystemExit("GITCODE_TOKEN is required to open the upgrade PR")

    target_repo = normalize_repo(args.target_repo) or DEFAULT_TARGET_REPO
    push_repo = normalize_repo(args.push_repo) or target_repo
    head = (
        f"{push_repo.split('/')[0]}:{args.branch}"
        if push_repo != target_repo
        else args.branch
    )

    pr = create_pull_request(
        target_repo,
        head,
        args.base,
        f"feat: upgrade {item['app']} to {item['version']}",
        build_body(item, args.test_status),
        token,
    )
    url = str(pr.get("web_url") or pr.get("html_url") or "")
    log_stage("upgrade-pr", f"{item['app']}: PR created {url}")

    github_output = os.environ.get("GITHUB_OUTPUT", "")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as handle:
            handle.write(f"pr_url={url}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
