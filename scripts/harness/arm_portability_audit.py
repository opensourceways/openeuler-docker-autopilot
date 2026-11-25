#!/usr/bin/env python3
"""
Stage: ARM 可移植性静态审计（arm_portability_audit）

只做静态分析，不构建镜像、不推送分支、不开 PR。用于回答两个问题：

1. 目标仓里用**源码**构建镜像的软件，是否在上游项目里已经适配了 ARM；
2. 为了让镜像能在 ARM 上构建，本仓是否修改了上游源码（patch / sed / 覆盖文件），
   或者写了 aarch64 条件分支。

输入：目标仓克隆目录 + domain（可逗号分隔，或 all）。
输出：JSON 明细 + Markdown 汇总（由调用方写入 GitHub Actions Step Summary）。

子命令：
  scan    只枚举每个软件的最新版本目录，输出清单；
  audit   对单个清单条目做静态审计，输出 JSON；
  report  scan + audit + Markdown 汇总一次完成（工作流使用该入口）。
"""

import argparse
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

_MAX_FILE_CHARS = 20000
_SKIP_DIRS = {"doc", "tests", ".git"}
_VERSION_TOKEN_RE = re.compile(r"(\d+|[A-Za-z]+)")
# 形如 24.03-lts-sp4 的目录名是 openEuler 版本，不是应用版本。
_OS_LIKE_RE = re.compile(
    r"^\d{2}\.\d{2}(?:-lts)?(?:-sp\d+)?$", re.IGNORECASE
)

# 源码构建特征：出现在 Dockerfile 的 RUN 指令里，且不属于包管理安装命令。
_SOURCE_BUILD_MARKERS = (
    r"\./configure\b",
    r"\bcmake\b",
    r"\bninja\b",
    r"\bmeson\b",
    r"\bbazel\b",
    r"\bautoreconf\b",
    r"\bautogen\.sh\b",
    r"\bmake\b",
    r"\bcargo\s+(?:build|install)\b",
    r"\bgo\s+(?:build|install)\b",
    r"\bmvn\b",
    r"\bgradlew?\b",
    r"\bsetup\.py\s+(?:build|install)\b",
    r"\bpip3?\s+install\s+(?:-e\s+)?\.(?:\s|$)",
    r"\b(?:gcc|g\+\+|cc|clang)\b",
)
_PACKAGE_INSTALL_RE = re.compile(
    r"(?:dnf|yum|apt-get|apt|microdnf|zypper)\s+(?:-\S+\s+)*install\b[^\n&;|]*"
)
_ARM_REPO_MARKERS = (
    r"aarch64",
    r"arm64",
    r"armv8",
    r"TARGETARCH",
    r"uname\s+-m",
)
_SOURCE_PATCH_MARKERS = (
    r"\bpatch\s+-p\s*\d",
    r"\bgit\s+apply\b",
    r"\bsed\s+-i\b",
    r"\bperl\s+-[a-z]*\s*-i\b",
)
_UPSTREAM_ARM_RE = re.compile(r"aarch64|arm64|armv8|\barm\b", re.IGNORECASE)


def _read(path: Path, limit: int = _MAX_FILE_CHARS) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text[:limit]


def _version_key(value: str) -> tuple:
    key: list[tuple[int, int, str]] = []
    for part in _VERSION_TOKEN_RE.findall(value):
        if part.isdigit():
            key.append((0, int(part), ""))
        else:
            key.append((1, 0, part.lower()))
    return tuple(key)


def _os_key(value: str) -> tuple[int, int, int]:
    match = re.match(
        r"\s*(\d+)\.(\d+)(?:-lts)?(?:-sp(\d+))?", value, re.IGNORECASE
    )
    if match is None:
        return (0, 0, 0)
    return (int(match.group(1)), int(match.group(2)), int(match.group(3) or 0))


def _source_url_from_image_info(app_dir: Path) -> str:
    import yaml

    path = app_dir / "doc" / "image-info.yml"
    if not path.is_file():
        return ""
    try:
        info = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return ""
    if not isinstance(info, dict):
        return ""
    homepage = str(info.get("homepage") or "").strip()
    if homepage.startswith("https://"):
        return homepage
    upstream = info.get("upstream")
    if isinstance(upstream, dict):
        version_url = str(upstream.get("version_url") or "").strip()
        if version_url.startswith("https://"):
            return version_url
        if version_url:
            backend = str(upstream.get("backend") or "GitHub").casefold()
            host = "gitlab.com" if backend == "gitlab" else "github.com"
            return f"https://{host}/{version_url}"
    return ""


def _source_url_from_dockerfile(text: str) -> str:
    match = re.search(
        r"(?:git\s+clone|curl|wget)[^\n]*(https://github\.com/[^\s\"']+)", text
    )
    return match.group(1) if match else ""


def resolve_domains(repo_dir: Path, value: str) -> list[str]:
    requested = [part.strip() for part in str(value).split(",") if part.strip()]
    if not requested:
        raise SystemExit("domain 不能为空")
    available = [
        child.name
        for child in sorted(repo_dir.iterdir())
        if child.is_dir()
        and child.name not in {"config", "tests"}
        and any(item.is_dir() for item in child.iterdir())
    ]
    if len(requested) == 1 and requested[0].lower() == "all":
        return available
    unknown = [name for name in requested if name not in available]
    if unknown:
        raise SystemExit(
            "未知 domain: "
            + ", ".join(unknown)
            + "；可用: "
            + ", ".join(available)
        )
    return requested


def latest_mdu(app_dir: Path) -> tuple[str, str, Path] | None:
    """返回 (version, os_version, Dockerfile)，按版本次序选最新的一个。

    目录名形如 24.03-lts-sp4 的是 openEuler 版本目录（部分应用会把应用版本
    直接放在这一层），排序时优先选择非 openEuler 形式的真实应用版本。
    """
    candidates: list[tuple[str, str, Path]] = []
    for version_dir in app_dir.iterdir():
        if not version_dir.is_dir() or version_dir.name in _SKIP_DIRS:
            continue
        for os_dir in version_dir.iterdir():
            if not os_dir.is_dir():
                continue
            dockerfile = os_dir / "Dockerfile"
            if dockerfile.is_file():
                candidates.append((version_dir.name, os_dir.name, dockerfile))
    if not candidates:
        return None
    real_versions = [
        item for item in candidates if not _OS_LIKE_RE.match(item[0])
    ]
    pool = real_versions or candidates
    return max(pool, key=lambda item: (_version_key(item[0]), _os_key(item[1])))


def scan(repo_dir: Path, domains: list[str], apps: str = "") -> list[dict]:
    wanted = {
        part.strip().casefold() for part in str(apps).split(",") if part.strip()
    }
    items: list[dict] = []
    for domain in domains:
        domain_dir = repo_dir / domain
        if not domain_dir.is_dir():
            continue
        for app_dir in sorted(domain_dir.iterdir()):
            if not app_dir.is_dir():
                continue
            if wanted and app_dir.name.casefold() not in wanted:
                continue
            latest = latest_mdu(app_dir)
            if latest is None:
                items.append(
                    {
                        "domain": domain,
                        "app": app_dir.name,
                        "version": "",
                        "os_version": "",
                        "dockerfile_path": "",
                        "skipped": "no Dockerfile in any version directory",
                    }
                )
                continue
            version, os_version, dockerfile = latest
            items.append(
                {
                    "domain": domain,
                    "app": app_dir.name,
                    "version": version,
                    "os_version": os_version,
                    "dockerfile_path": dockerfile.relative_to(repo_dir).as_posix(),
                }
            )
    return items


def _strip_package_installs(text: str) -> str:
    return _PACKAGE_INSTALL_RE.sub(" ", text)


def _collect_evidence_lines(text: str, markers: tuple[str, ...]) -> list[str]:
    hits: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if any(re.search(marker, stripped, re.IGNORECASE) for marker in markers):
            hits.append(stripped[:160])
    return hits


def classify_build(dockerfile: str) -> dict:
    stripped = _strip_package_installs(dockerfile)
    source_hits = _collect_evidence_lines(stripped, _SOURCE_BUILD_MARKERS)
    if source_hits:
        return {"mode": "source", "evidence": source_hits[:8]}
    markers = _collect_evidence_lines(
        dockerfile,
        (r"\bcurl\b", r"\bwget\b", r"\b(?:dnf|yum|apt-get|microdnf)\b", r"\bpip3?\b"),
    )
    if markers:
        return {"mode": "binary", "evidence": markers[:8]}
    return {"mode": "unknown", "evidence": []}


def inspect_repo_adaptation(
    app_dir: Path, dockerfile: str, version: str = "", os_version: str = ""
) -> dict:
    """本仓是否为 ARM 做了适配 / 是否修改了上游源码。

    只检查被审计的 MDU 目录（{version}/{os_version}，以及应用根下的通用
    patches 目录），避免把历史版本/历史系统的补丁算进当前版本。
    """
    scope_dirs = []
    mdu_dir = app_dir / version / os_version if version and os_version else None
    if mdu_dir is not None and mdu_dir.is_dir():
        scope_dirs.append(mdu_dir)
    elif version and (app_dir / version).is_dir():
        scope_dirs.append(app_dir / version)
    patches_dir = app_dir / "patches"
    if patches_dir.is_dir():
        scope_dirs.append(patches_dir)
    build_scripts = sorted(
        path
        for scope in scope_dirs
        for path in scope.rglob("*.sh")
        if path.is_file()
    )[:20]
    patch_files = sorted(
        path
        for scope in scope_dirs
        for path in scope.rglob("*")
        if path.is_file() and path.suffix in {".patch", ".diff"}
    )[:20]
    texts = {"Dockerfile": dockerfile}
    for path in build_scripts:
        texts[path.relative_to(app_dir).as_posix()] = _read(path)
    arm_evidence: list[str] = []
    for name, text in texts.items():
        for line in _collect_evidence_lines(text, _ARM_REPO_MARKERS):
            arm_evidence.append(f"{name}: {line}")
    patch_evidence: list[str] = []
    for name, text in texts.items():
        for line in _collect_evidence_lines(text, _SOURCE_PATCH_MARKERS):
            patch_evidence.append(f"{name}: {line}")
    for path in patch_files:
        relative = path.relative_to(app_dir).as_posix()
        patch_evidence.append(f"{relative}: patch file present")
        # 补丁文件不一定与 ARM 有关；只有文件名或内容带架构关键词才计入适配证据。
        if re.search(r"arm|aarch64|armv8", relative, re.IGNORECASE) or re.search(
            r"aarch64|arm64|armv8", _read(path), re.IGNORECASE
        ):
            arm_evidence.append(f"{relative}: patch file present")
    return {
        "arm": {
            "status": "yes" if arm_evidence else "no",
            "evidence": arm_evidence[:10],
        },
        "source_modified": {
            "status": "yes" if patch_evidence else "no",
            "evidence": patch_evidence[:10],
        },
    }


def _parse_github_url(source_url: str) -> tuple[str, str] | None:
    match = re.match(
        r"https?://github\.com/([^/\s]+)/([^/\s#?]+)", source_url or ""
    )
    if not match:
        return None
    repo = match.group(2)
    if repo.endswith(".git"):
        repo = repo[: -len(".git")]
    return match.group(1), repo


def _http_get(url: str, timeout: float) -> tuple[int, str]:
    headers = {
        "User-Agent": "openeuler-docker-autopilot-arm-audit",
        "Accept": "application/vnd.github+json,text/plain,*/*",
    }
    # 有 token 时用认证配额（5000/h），否则匿名配额只有 60/h。
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
    if token and "api.github.com" in url:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        return error.code, ""
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0, ""


def probe_upstream(
    source_url: str,
    *,
    fetch=_http_get,
    timeout: float = 15,
) -> dict:
    """只依赖公开 GitHub 接口探测上游的 ARM 支持，失败时降级为 unknown。"""
    parsed = _parse_github_url(source_url)
    if parsed is None:
        return {
            "status": "unknown",
            "repo": "",
            "evidence": [],
            "warnings": [
                "上游仓库不是 GitHub 地址，未做联网探测"
                if source_url
                else "缺少上游仓库地址"
            ],
        }
    owner, repo = parsed
    slug = f"{owner}/{repo}"
    warnings: list[str] = []
    evidence: list[str] = []

    status, body = fetch(f"https://api.github.com/repos/{slug}", timeout)
    if status != 200:
        return {
            "status": "unknown",
            "repo": slug,
            "evidence": [],
            "warnings": [f"GitHub API 仓库元数据请求失败（HTTP {status}）"],
        }
    try:
        meta = json.loads(body)
    except json.JSONDecodeError:
        meta = {}
    branch = str(meta.get("default_branch") or "main")

    readme_text = ""
    for name in ("README.md", "README.rst", "README"):
        status, body = fetch(
            f"https://raw.githubusercontent.com/{slug}/{branch}/{name}", timeout
        )
        if status == 200 and body:
            readme_text = body
            break
    for line in readme_text.splitlines():
        if _UPSTREAM_ARM_RE.search(line):
            evidence.append(f"README: {line.strip()[:140]}")
            if len(evidence) >= 5:
                break

    status, body = fetch(
        f"https://api.github.com/repos/{slug}/contents/.github/workflows", timeout
    )
    if status == 200:
        try:
            entries = json.loads(body)
        except json.JSONDecodeError:
            entries = []
        for entry in entries if isinstance(entries, list) else []:
            name = str(entry.get("name") or "")
            if re.search(r"arm|aarch64|arm64", name, re.IGNORECASE):
                evidence.append(f".github/workflows/{name}")
    elif status not in (404, 403):
        warnings.append(f"上游 CI 目录探测失败（HTTP {status}）")

    # README / CI 没有证据时，再看最新 release 是否发布了 arm 资产。
    if not evidence:
        status, body = fetch(
            f"https://api.github.com/repos/{slug}/releases/latest", timeout
        )
        if status == 200:
            try:
                release = json.loads(body)
            except json.JSONDecodeError:
                release = {}
            for asset in release.get("assets", []) if isinstance(release, dict) else []:
                name = str(asset.get("name") or "")
                if re.search(r"arm64|aarch64|armv8", name, re.IGNORECASE):
                    evidence.append(f"release asset: {name}")
                    if len(evidence) >= 5:
                        break
        elif status not in (404, 403):
            warnings.append(f"上游 release 探测失败（HTTP {status}）")

    if not readme_text:
        warnings.append("未能读取上游 README")
    return {
        "status": "yes" if evidence else "no",
        "repo": slug,
        "evidence": evidence,
        "warnings": warnings,
    }


def _conclusion(
    build_mode: str, repo_arm: dict, source_modified: dict, upstream: dict
) -> str:
    if build_mode != "source":
        return "非源码构建，跳过 ARM 适配判断"
    if repo_arm["status"] == "yes":
        return "源码构建；本仓已包含 ARM 适配（条件分支或 patch）"
    if source_modified["status"] == "yes":
        return "源码构建；构建时修改了上游源码（需人工确认是否为 ARM 适配）"
    if upstream["status"] == "yes":
        return "源码构建；上游已有 ARM 支持，本仓未改源码"
    if upstream["status"] == "no":
        return "源码构建；上游未见 ARM 适配证据，本仓也未适配（风险）"
    return "源码构建；上游证据不足，无法判断"


def audit_item(repo_dir: Path, item: dict, *, fetch=_http_get) -> dict:
    if item.get("skipped"):
        return {**item, "build_mode": "unknown", "conclusion": item["skipped"]}
    domain = str(item["domain"])
    app = str(item["app"])
    app_dir = repo_dir / domain / app
    dockerfile = _read(repo_dir / str(item["dockerfile_path"]))
    build = classify_build(dockerfile)
    adaptation = inspect_repo_adaptation(
        app_dir,
        dockerfile,
        str(item.get("version") or ""),
        str(item.get("os_version") or ""),
    )
    source_url = _source_url_from_image_info(app_dir) or _source_url_from_dockerfile(
        dockerfile
    )
    upstream = probe_upstream(source_url, fetch=fetch)
    return {
        **item,
        "source_url": source_url,
        "build_mode": build["mode"],
        "build_evidence": build["evidence"],
        "repo_arm": adaptation["arm"],
        "source_modified": adaptation["source_modified"],
        "upstream": upstream,
        "conclusion": _conclusion(
            build["mode"], adaptation["arm"], adaptation["source_modified"], upstream
        ),
    }


def render_summary(results: list[dict]) -> str:
    source_items = [item for item in results if item.get("build_mode") == "source"]
    other_items = [item for item in results if item.get("build_mode") != "source"]
    lines = ["## ARM 可移植性静态审计", ""]
    lines.append(f"- 审计软件: `{len(results)}`")
    lines.append(f"- 源码构建: `{len(source_items)}`")
    lines.append(
        "- 本仓含 ARM 适配: `{}`".format(
            sum(1 for item in source_items if item.get("repo_arm", {}).get("status") == "yes")
        )
    )
    lines.append(
        "- 修改上游源码: `{}`".format(
            sum(
                1
                for item in source_items
                if item.get("source_modified", {}).get("status") == "yes"
            )
        )
    )
    lines.append(
        "- 上游已有 ARM 证据: `{}`；上游无证据: `{}`；证据不足: `{}`".format(
            sum(1 for item in source_items if item.get("upstream", {}).get("status") == "yes"),
            sum(1 for item in source_items if item.get("upstream", {}).get("status") == "no"),
            sum(
                1
                for item in source_items
                if item.get("upstream", {}).get("status") == "unknown"
            ),
        )
    )
    lines.extend(["", "### 源码构建软件", ""])
    if source_items:
        lines.append(
            "| Domain | App | Version | openEuler | 上游 ARM | 本仓 ARM 适配 | 修改上游源码 | 结论 |"
        )
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
        for item in source_items:
            lines.append(
                "| {domain} | {app} | {version} | {os} | {up} | {repo} | {mod} | {conclusion} |".format(
                    domain=item.get("domain", ""),
                    app=item.get("app", ""),
                    version=item.get("version", ""),
                    os=item.get("os_version", ""),
                    up=item.get("upstream", {}).get("status", "unknown"),
                    repo=item.get("repo_arm", {}).get("status", "no"),
                    mod=item.get("source_modified", {}).get("status", "no"),
                    conclusion=str(item.get("conclusion", "")).replace("|", "/"),
                )
            )
    else:
        lines.append("- 无")
    lines.extend(["", "### 非源码构建（跳过）", ""])
    if other_items:
        lines.append(
            "| Domain | App | Version | openEuler | 构建方式 |"
        )
        lines.append("| --- | --- | --- | --- | --- |")
        for item in other_items:
            lines.append(
                "| {domain} | {app} | {version} | {os} | {mode} |".format(
                    domain=item.get("domain", ""),
                    app=item.get("app", ""),
                    version=item.get("version", ""),
                    os=item.get("os_version", ""),
                    mode=item.get("build_mode", "unknown"),
                )
            )
    else:
        lines.append("- 无")
    details = [
        item
        for item in source_items
        if item.get("repo_arm", {}).get("evidence")
        or item.get("source_modified", {}).get("evidence")
        or item.get("upstream", {}).get("evidence")
    ]
    if details:
        lines.extend(["", "### 证据明细", ""])
        for item in details:
            lines.append(f"#### {item['domain']}/{item['app']} {item['version']}")
            lines.append("")
            if item.get("repo_arm", {}).get("evidence"):
                lines.append("- 本仓 ARM 适配证据：")
                lines.extend(f"  - `{line}`" for line in item["repo_arm"]["evidence"])
            if item.get("source_modified", {}).get("evidence"):
                lines.append("- 修改上游源码证据：")
                lines.extend(
                    f"  - `{line}`" for line in item["source_modified"]["evidence"]
                )
            if item.get("upstream", {}).get("evidence"):
                lines.append("- 上游 ARM 证据：")
                lines.extend(
                    f"  - `{line}`" for line in item["upstream"]["evidence"]
                )
            if item.get("upstream", {}).get("warnings"):
                lines.append("- 上游探测提示：")
                lines.extend(
                    f"  - {line}" for line in item["upstream"]["warnings"]
                )
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="枚举最新版本清单")
    scan_parser.add_argument("--repo", required=True)
    scan_parser.add_argument("--domain", required=True)
    scan_parser.add_argument("--apps", default="")
    scan_parser.add_argument("--output", required=True)

    audit_parser = subparsers.add_parser("audit", help="审计单个清单条目")
    audit_parser.add_argument("--repo", required=True)
    audit_parser.add_argument("--item", required=True)
    audit_parser.add_argument("--output", required=True)

    report_parser = subparsers.add_parser("report", help="扫描 + 审计 + 汇总")
    report_parser.add_argument("--repo", required=True)
    report_parser.add_argument("--domain", required=True)
    report_parser.add_argument("--apps", default="")
    report_parser.add_argument("--output", required=True)
    report_parser.add_argument("--summary", required=True)

    args = parser.parse_args(argv)
    repo_dir = Path(args.repo)

    if args.command == "scan":
        items = scan(repo_dir, resolve_domains(repo_dir, args.domain), args.apps)
        Path(args.output).write_text(
            json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps({"count": len(items)}))
        return 0

    if args.command == "audit":
        result = audit_item(repo_dir, json.loads(args.item))
        Path(args.output).write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps({"app": result.get("app"), "conclusion": result.get("conclusion")}))
        return 0

    items = scan(repo_dir, resolve_domains(repo_dir, args.domain), args.apps)
    results = [audit_item(repo_dir, item) for item in items]
    Path(args.output).write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    summary = render_summary(results)
    Path(args.summary).write_text(summary, encoding="utf-8")
    print(
        json.dumps(
            {
                "count": len(results),
                "source_build": sum(
                    1 for item in results if item.get("build_mode") == "source"
                ),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
