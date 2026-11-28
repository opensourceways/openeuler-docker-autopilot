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
  has_test_script}]``，交给 ``upgrade_audit.py`` 做 AI 审计；
- ``conda_updates``：需要在 ``openeuler/conda-ecopkgs`` 登记的版本
  ``[{name, package, version, os_version, arches}]``。

规则：
- 软件清单来自 ``config/upgrade-apps.yml``（人工维护，可用 ``--apps-file``
  指向子集），每个软件用 ``docker`` / ``conda`` 子对象标明目标仓；
- 同一个软件两个仓都有时，docker 与 conda 各产出一条升级项；
- docker 目标要求 ``version``（目标版本）与 ``source_url``（上游仓库 HTTPS
  地址；缺省时从目标仓 ``doc/image-info.yml`` 读取），缺失则跳过并记录原因；
- conda 目标要求 ``version``；``--os-version`` 指定登记到哪个 openEuler 段
  （缺省用该包最新的已有段），架构沿用该包最近一条版本记录；
- 清单项可选 ``tag``（上游 tag，如 ``slurm-26-05-6-1``）；不填则跳过 tag 校验；
- 手动 ``--app`` 可不在清单里：按两个目标仓的目录反查，必须同时给
  ``--version``；
- 目标版本低于仓库现有版本（仅纯数字版本比较）或为 ``Undefined`` / ``latest``
  等占位值 → 跳过，避免降级 PR；
- 最新版本目录已存在 → **不跳过**，产出 audit；
- 目标分支已有 open PR → 跳过（已有升级在途）；
- os 目录沿用该应用最新的一个（不补齐所有 os 版本）；
- 证据只保留手动提供的信息（``source=manual``），不再抓看板采集项。

输入: --repo <docker 仓克隆>，可选 --conda-repo / --app / --version / --tag /
      --source-url / --os-version / --apps-file / --limit / --audit-limit
输出: --format github-output → GITHUB_OUTPUT 写 updates/audits/conda_updates/
      skipped；--format json → stdout
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
from scripts.lib import app_notes  # noqa: E402
from scripts.lib.stage_common import log_stage  # noqa: E402
from scripts.lib.task_spec import _os_tag, naming_version  # noqa: E402
from scripts.lib.version_upgrade import existing_version_dirs  # noqa: E402

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


def _normalize_entry(entry: dict) -> dict:
    """把新结构或旧的 app/domain 结构统一成 docker/conda 目标。"""
    name = str(entry.get("name") or "").strip()

    docker = entry.get("docker")
    if isinstance(docker, dict):
        docker_app = str(docker.get("app") or "").strip()
        docker_domain = str(docker.get("domain") or "").strip()
    else:
        docker_app = str(entry.get("app") or "").strip()
        docker_domain = str(entry.get("domain") or "").strip()

    conda = entry.get("conda")
    if isinstance(conda, dict):
        conda_package = str(conda.get("package") or "").strip()
    else:
        conda_package = str(conda or "").strip()

    create = entry.get("create")
    if isinstance(create, dict):
        create_app = str(create.get("app") or "").strip()
        create_domain = str(create.get("domain") or "").strip()
    else:
        create_app = ""
        create_domain = ""

    if not docker_app and not conda_package and not create_app:
        raise SystemExit(f"需要 docker、conda 或 create 目标（{entry!r}）")
    if docker_app and not docker_domain:
        raise SystemExit(f"docker.domain 不能为空（{entry!r}）")
    if create_app and not create_domain:
        raise SystemExit(f"create.domain 不能为空（{entry!r}）")

    record = {"name": name or docker_app or conda_package or create_app}
    if docker_app:
        record["docker"] = {"app": docker_app, "domain": docker_domain}
    if conda_package:
        record["conda"] = {"package": conda_package}
    if create_app:
        record["create"] = {"app": create_app, "domain": create_domain}
    for field in ("version", "tag", "source_url", "build_notes"):
        value = str(entry.get(field) or "").strip()
        if value:
            record[field] = value
    if entry.get("allow_downgrade") is True:
        record["allow_downgrade"] = True
    return record


def load_apps(path: str | Path | None = None) -> list[dict]:
    """读取人工维护的软件清单；格式错误直接失败，避免静默少扫。

    新结构用 ``docker`` / ``conda`` 子对象标明目标仓；旧的 ``app`` /
    ``domain`` 顶层字段仍然兼容。至少要有其中一个目标。
    """
    apps_file = Path(path or DEFAULT_APPS_FILE)
    if not apps_file.is_file():
        raise SystemExit(f"apps file not found: {apps_file}")
    data = yaml.safe_load(apps_file.read_text(encoding="utf-8")) or {}
    entries = data.get("apps") if isinstance(data, dict) else data
    if not isinstance(entries, list) or not entries:
        raise SystemExit(f"{apps_file}: 需要非空的 apps 列表")

    apps: list[dict] = []
    seen: set[tuple[str, str, str, str]] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise SystemExit(f"{apps_file}: apps 里的每一项必须是对象")
        try:
            record = _normalize_entry(entry)
        except SystemExit as error:
            raise SystemExit(f"{apps_file}: {error}") from error
        key = (
            (record.get("docker") or {}).get("domain", ""),
            (record.get("docker") or {}).get("app", ""),
            (record.get("conda") or {}).get("package", ""),
            (record.get("create") or {}).get("app", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        apps.append(record)
    return apps


def _select_apps(apps: list[dict], app_filter: str) -> list[dict]:
    """按名称筛选；支持逗号分隔一次重跑多个应用。"""
    if not app_filter:
        return apps
    keys = {
        testgen_scan.normalize_name(part)
        for part in app_filter.split(",")
        if part.strip()
    }
    selected: list[dict] = []
    for entry in apps:
        names = {
            testgen_scan.normalize_name(entry["name"]),
            testgen_scan.normalize_name(
                (entry.get("docker") or {}).get("app", "")
            ),
            testgen_scan.normalize_name(
                (entry.get("conda") or {}).get("package", "")
            ),
            testgen_scan.normalize_name(
                (entry.get("create") or {}).get("app", "")
            ),
        }
        names.discard("")
        if keys & names:
            selected.append(entry)
    return selected


def _find_repo_app(repo_dir: Path, app_filter: str) -> dict | None:
    """清单外的应用：只在目标仓里反查 domain。"""
    key = testgen_scan.normalize_name(app_filter)
    matches = [
        {"name": app_filter, "app": child.name, "domain": parent.name}
        for parent in sorted(repo_dir.iterdir())
        if parent.is_dir()
        for child in sorted(parent.iterdir())
        if child.is_dir() and testgen_scan.normalize_name(child.name) == key
    ]
    if len(matches) > 1:
        raise SystemExit(
            f"{app_filter}: 软件清单里没有，且目标仓命中多个目录 "
            f"{[(m['domain'], m['app']) for m in matches]}"
        )
    return matches[0] if matches else None


def _find_conda_package(conda_repo: Path, app_filter: str) -> str | None:
    """清单外的应用：只在 conda 仓里反查 packages/<name>。"""
    packages_dir = conda_repo / "packages"
    if not packages_dir.is_dir():
        return None
    key = testgen_scan.normalize_name(app_filter)
    matches = sorted(
        child.name
        for child in packages_dir.iterdir()
        if child.is_dir()
        and (child / "supported-versions.yml").is_file()
        and testgen_scan.normalize_name(child.name) == key
    )
    if len(matches) > 1:
        raise SystemExit(
            f"{app_filter}: conda 仓命中多个包目录 {matches}"
        )
    return matches[0] if matches else None


def _canonical_os(value: str) -> str:
    match = re.fullmatch(
        r"\s*(\d+\.\d+)(?:-lts)?(?:-sp(\d+))?\s*", value, re.IGNORECASE
    )
    if match is None:
        return value.strip()
    suffix = f"-SP{match.group(2)}" if match.group(2) else ""
    return f"{match.group(1)}-LTS{suffix}"


def _os_sort_key(value: str) -> tuple[int, int, int]:
    match = re.match(
        r"\s*(\d+)\.(\d+)(?:-lts)?(?:-sp(\d+))?", str(value), re.IGNORECASE
    )
    if match is None:
        return (0, 0, 0)
    return (
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3) or 0),
    )


def _conda_target_os(versions: dict, forced_os: str) -> tuple[str | None, str]:
    """返回 (文件里已有的 os key, 要写入的 os key)。"""
    if forced_os:
        wanted = forced_os.strip()
        for key in versions:
            if str(key).casefold() == wanted.casefold():
                return str(key), str(key)
        return None, _canonical_os(wanted)
    if not versions:
        return None, ""
    key = max(versions, key=lambda item: _os_sort_key(str(item)))
    return str(key), str(key)


def _conda_arches(versions: dict, os_key: str | None) -> list[str]:
    def last_arches(section: object) -> list[str]:
        if not isinstance(section, dict) or not section:
            return []
        arches = section[next(reversed(section))]
        return [str(arch) for arch in arches] if isinstance(arches, list) else []

    if os_key is not None:
        arches = last_arches(versions.get(os_key))
        if arches:
            return arches
    for key in sorted(
        versions, key=lambda item: _os_sort_key(str(item)), reverse=True
    ):
        arches = last_arches(versions.get(key))
        if arches:
            return arches
    return ["x86_64", "aarch64"]


def find_conda_updates(
    *,
    conda_repo: Path,
    entries: list[dict],
    forced_version: str = "",
    forced_os: str = "",
    skipped: list[dict],
) -> list[dict]:
    """对比 conda-ecopkgs 的 supported-versions.yml，产出需登记的版本。"""
    updates: list[dict] = []
    for entry in entries:
        target = entry.get("conda")
        if not target:
            continue
        package = target["package"]
        name = entry["name"]
        version = (forced_version or str(entry.get("version") or "")).strip()
        if not version:
            skipped.append(
                {
                    "app": name,
                    "target": "conda",
                    "reason": "清单未提供 version",
                }
            )
            continue
        if version.lower() in _PLACEHOLDER_VERSIONS:
            skipped.append(
                {
                    "app": name,
                    "target": "conda",
                    "reason": f"版本号无效（{version}）",
                }
            )
            continue

        yml_path = conda_repo / "packages" / package / "supported-versions.yml"
        if not yml_path.is_file():
            skipped.append(
                {
                    "app": name,
                    "target": "conda",
                    "reason": f"conda 仓没有 packages/{package}",
                }
            )
            continue
        try:
            versions = yaml.safe_load(yml_path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            skipped.append(
                {
                    "app": name,
                    "target": "conda",
                    "reason": f"无法解析 packages/{package}/supported-versions.yml",
                }
            )
            continue
        if not isinstance(versions, dict):
            skipped.append(
                {
                    "app": name,
                    "target": "conda",
                    "reason": f"packages/{package}/supported-versions.yml 不是映射",
                }
            )
            continue

        os_key, write_os = _conda_target_os(versions, forced_os)
        if not write_os:
            skipped.append(
                {
                    "app": name,
                    "target": "conda",
                    "reason": "conda 仓没有可用的 openEuler 版本段",
                }
            )
            continue
        section = versions.get(os_key) if os_key is not None else None
        existing = (
            {
                _normalize_version(item)
                for item in section
            }
            if isinstance(section, dict)
            else set()
        )
        if _normalize_version(version) in existing:
            skipped.append(
                {
                    "app": name,
                    "target": "conda",
                    "reason": f"{write_os} 已登记 {version}",
                }
            )
            continue

        updates.append(
            {
                "name": name,
                "package": package,
                "version": version,
                "os_version": write_os,
                "arches": _conda_arches(versions, os_key),
            }
        )
    return updates


def _source_url_from_image_info(app_dir: Path) -> str:
    """没有手动 source_url 时，从目标仓 doc/image-info.yml 取上游地址。"""
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


def _timeout_fields(app: str) -> dict:
    """把注意点文档里的预算带进矩阵，供 workflow 的 job timeout 使用。"""
    notes = app_notes.load(app)
    if notes is None:
        return {}
    fields: dict[str, int] = {}
    if notes.build_timeout_minutes:
        fields["build_timeout_minutes"] = notes.build_timeout_minutes
    if notes.prepare_timeout_minutes:
        fields["prepare_timeout_minutes"] = notes.prepare_timeout_minutes
    return fields


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


def _issue_evidence_for(
    issue_evidence: dict | None, *candidates: str
) -> dict | None:
    """只把触发 Issue 的证据交给它自己的应用，其它条目仍用 manual 证据。

    清单里的 ``name`` 与目标仓目录名可能不同（如 ``grpc-java`` →
    ``grpc-server``），两者任意命中都算同一个应用。
    """
    if not issue_evidence:
        return None
    name = str(issue_evidence.get("name") or "").strip()
    if not name:
        return issue_evidence
    normalized = name.lower()
    for candidate in candidates:
        if candidate and normalized == str(candidate).strip().lower():
            return issue_evidence
    return None


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
    conda_repo: Path | None = None,
    forced_os: str = "",
    issue_evidence: dict | None = None,
) -> dict:
    app_filter = app_filter.strip()
    source = apps if apps is not None else load_apps(apps_file)
    entries = _select_apps([_normalize_entry(entry) for entry in source], app_filter)

    # 手动指定但不在清单里的应用：在两个目标仓里各自反查。
    ad_hoc = bool(app_filter) and not entries
    if ad_hoc:
        if "," in app_filter:
            raise SystemExit(
                "逗号分隔多应用只支持软件清单里的应用；清单外的应用请单独指定"
            )
        if not forced_version:
            raise SystemExit(
                f"{app_filter}: 不在软件清单里，手动升级必须同时指定 --version"
            )
        entry: dict = {"name": app_filter}
        docker = _find_repo_app(repo_dir, app_filter)
        if docker is not None:
            entry["docker"] = {"app": docker["app"], "domain": docker["domain"]}
        if conda_repo is not None:
            package = _find_conda_package(conda_repo, app_filter)
            if package:
                entry["conda"] = {"package": package}
        if "docker" not in entry and "conda" not in entry:
            raise SystemExit(
                f"{app_filter}: 软件清单、docker 仓与 conda 仓里都没有这个应用"
            )
        entries = [entry]

    source_url = source_url.strip()
    skipped: list[dict] = []
    updates: list[dict] = []
    audits: list[dict] = []

    # Issue / 手动指定单个应用时，以两个目标仓的实际目录为准补齐清单没写的
    # 目标：清单可能落后于仓库，两边都有就两边都升。
    if app_filter:
        for entry in entries:
            if "docker" not in entry:
                docker = _find_repo_app(repo_dir, entry["name"])
                if docker is not None:
                    entry["docker"] = {
                        "app": docker["app"],
                        "domain": docker["domain"],
                    }
            if "conda" not in entry and conda_repo is not None:
                package = _find_conda_package(conda_repo, entry["name"])
                if package:
                    entry["conda"] = {"package": package}

    for entry in entries:
        target = entry.get("docker")
        if not target:
            continue
        app = target["app"]
        domain = target["domain"]
        app_dir = repo_dir / domain / app
        if not app_dir.is_dir():
            skipped.append(
                {
                    "app": app,
                    "target": "docker",
                    "reason": (
                        f"目标仓没有 {domain}/{app}"
                        "（尚未入库，待场景一新建镜像）"
                    ),
                }
            )
            continue

        version = (forced_version or str(entry.get("version") or "")).strip()
        if not version:
            skipped.append(
                {
                    "app": app,
                    "target": "docker",
                    "reason": (
                        "清单未提供 version（自动升级只用手动提供的版本，"
                        "不查询看板）"
                    ),
                }
            )
            continue
        if version.lower() in _PLACEHOLDER_VERSIONS:
            skipped.append(
                {
                    "app": app,
                    "target": "docker",
                    "reason": f"版本号无效（{version}）",
                }
            )
            continue

        # 目录/tag 沿用目标仓既有命名：哈希取前 7 位，v / npu-v 前缀和
        # -tentative 这类装饰后缀按已有裸版本目录剥离；证据里保留完整版本。
        release_version = version
        version = naming_version(version, existing_version_dirs(app_dir))

        entry_source = (
            source_url
            or str(entry.get("source_url") or "").strip()
            or _source_url_from_image_info(app_dir)
        )
        if not entry_source:
            skipped.append(
                {
                    "app": app,
                    "target": "docker",
                    "reason": (
                        "未提供 source_url（清单、Issue 与 doc/image-info.yml "
                        "都没有上游仓库 HTTPS 地址）"
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
            skipped.append(
                {
                    "app": app,
                    "target": "docker",
                    "reason": "应用目录下没有 */*/Dockerfile",
                }
            )
            continue

        # 清单由人工维护时也可能填错方向；只判断「版本目录是否存在」会把降级
        # 当成升级，纯数字版本先做一次大小保护。镜像实际构建的上游与仓库现有
        # 目录版本线不一致时（如 drbd 的 9.31.0 实际是 drbd-utils），清单可显式
        # 设 allow_downgrade: true 跳过该保护。
        current_version = dockerfile.parts[-3]
        new_key = _numeric_version_key(version)
        current_key = _numeric_version_key(current_version)
        if (
            not forced_version
            and not entry.get("allow_downgrade")
            and new_key is not None
            and current_key is not None
            and new_key < current_key
        ):
            skipped.append(
                {
                    "app": app,
                    "target": "docker",
                    "reason": (
                        f"目标版本 {version} 低于仓库现有版本 "
                        f"{current_version}，跳过"
                    ),
                }
            )
            continue

        evidence = _issue_evidence_for(issue_evidence, entry["name"], app)
        if evidence is None:
            evidence = _manual_evidence(
                name=entry["name"],
                version=release_version,
                tag=tag,
                source_url=entry_source,
            )

        if _normalize_version(version) in existing_versions(app_dir):
            if audit_limit and len(audits) >= audit_limit:
                skipped.append(
                    {
                        "app": app,
                        "target": "docker",
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
                    **_timeout_fields(app),
                }
            )
            continue

        os_version = dockerfile.parts[-2]
        branch = f"auto/version-update/{app}/{version}-{_os_tag(os_version)}"
        if pr_exists is not None and token:
            if pr_exists(target_repo, branch, token):
                skipped.append(
                    {
                        "app": app,
                        "target": "docker",
                        "reason": f"已有 open PR（{branch}）",
                    }
                )
                continue

        updates.append(
            {
                "app": app,
                "domain": domain,
                "version": version,
                "os_version": os_version,
                "source_url": entry_source,
                "evidence": evidence,
                **(
                    {"build_notes": entry["build_notes"]}
                    if entry.get("build_notes")
                    else {}
                ),
                **_timeout_fields(app),
            }
        )
        if limit and len(updates) >= limit:
            break

    conda_updates: list[dict] = []
    if conda_repo is not None:
        conda_updates = find_conda_updates(
            conda_repo=conda_repo,
            entries=entries,
            forced_version=forced_version,
            forced_os=forced_os,
            skipped=skipped,
        )

    new_images: list[dict] = []
    for entry in entries:
        if entry.get("docker") or entry.get("conda"):
            continue
        target = entry.get("create")
        if not target:
            continue
        version = (forced_version or str(entry.get("version") or "")).strip()
        if not version:
            skipped.append(
                {
                    "app": entry["name"],
                    "target": "new-image",
                    "reason": "清单未提供 version",
                }
            )
            continue
        if version.lower() in _PLACEHOLDER_VERSIONS:
            skipped.append(
                {
                    "app": entry["name"],
                    "target": "new-image",
                    "reason": f"版本号无效（{version}）",
                }
            )
            continue
        version = naming_version(version)
        os_version = forced_os.strip()
        if not os_version:
            skipped.append(
                {
                    "app": entry["name"],
                    "target": "new-image",
                    "reason": "新建镜像需要 --os-version",
                }
            )
            continue
        entry_source = source_url or str(entry.get("source_url") or "").strip()
        if not entry_source:
            skipped.append(
                {
                    "app": entry["name"],
                    "target": "new-image",
                    "reason": "新建镜像需要上游仓库 HTTPS 地址",
                }
            )
            continue
        new_images.append(
            {
                "name": entry["name"],
                "app": target["app"],
                "domain": target["domain"],
                "version": version,
                "os_version": os_version,
                "source_url": entry_source,
            }
        )

    return {
        "updates": updates,
        "audits": audits,
        "conda_updates": conda_updates,
        "new_images": new_images,
        "skipped": skipped,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("SOURCE_REPO_DIR", ""))
    parser.add_argument(
        "--app",
        default="",
        help=(
            "只处理这些应用（逗号分隔可一次指定多个）；"
            "不在清单里时必须配合 --version 且只能指定一个"
        ),
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
    parser.add_argument(
        "--conda-repo",
        default=os.environ.get("CONDA_REPO_DIR", ""),
        help="conda-ecopkgs 克隆目录（留空 = 不扫描 conda 目标）",
    )
    parser.add_argument(
        "--os-version",
        default="",
        help=(
            "限制 conda 登记到指定 openEuler 版本（如 24.03-LTS-SP4）；"
            "留空则用该包最新的已有版本段"
        ),
    )
    parser.add_argument("--limit", type=int, default=0, help="最多产出几个升级（0=不限）")
    parser.add_argument(
        "--audit-limit",
        type=int,
        default=0,
        help="最多产出几个「已存在版本目录」的 AI 审计（0=不限）",
    )
    parser.add_argument(
        "--evidence",
        default=os.environ.get("UPGRADE_ISSUE_EVIDENCE", ""),
        help=(
            "触发 Issue 提供的上游证据 JSON；只作用于同名应用，"
            "缺失时回落到 manual 证据"
        ),
    )
    parser.add_argument("--format", choices=("json", "github-output"), default="json")
    args = parser.parse_args()

    repo_dir = Path(args.repo or os.path.join(PROJECT_ROOT, "source-repo"))
    if not repo_dir.is_dir():
        raise SystemExit(f"target repo clone not found: {repo_dir}")
    conda_repo = Path(args.conda_repo) if args.conda_repo else None
    if conda_repo is not None and not conda_repo.is_dir():
        raise SystemExit(f"conda repo clone not found: {conda_repo}")

    from scripts.lib.ci_gitcode_api import find_any_pr_by_head_branch

    issue_evidence = None
    if args.evidence.strip():
        try:
            issue_evidence = json.loads(args.evidence)
        except json.JSONDecodeError as error:
            raise SystemExit(f"--evidence is not valid JSON: {error}") from error
        if not isinstance(issue_evidence, dict):
            raise SystemExit("--evidence must be a JSON object")

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
        conda_repo=conda_repo,
        forced_os=args.os_version,
        issue_evidence=issue_evidence,
    )
    log_stage(
        "upgrade-scan",
        "updates={} audits={} conda={} create={} skipped={}".format(
            len(result["updates"]),
            len(result["audits"]),
            len(result["conda_updates"]),
            len(result["new_images"]),
            len(result["skipped"]),
        ),
    )

    if args.format == "github-output":
        github_output = os.environ.get("GITHUB_OUTPUT", "")
        if not github_output:
            raise SystemExit("GITHUB_OUTPUT is not set (not running in Actions)")
        with open(github_output, "a", encoding="utf-8") as handle:
            handle.write(f"updates={json.dumps(result['updates'], ensure_ascii=False)}\n")
            handle.write(f"audits={json.dumps(result['audits'], ensure_ascii=False)}\n")
            handle.write(
                f"conda_updates={json.dumps(result['conda_updates'], ensure_ascii=False)}\n"
            )
            handle.write(
                f"new_images={json.dumps(result['new_images'], ensure_ascii=False)}\n"
            )
            handle.write(f"skipped={json.dumps(result['skipped'], ensure_ascii=False)}\n")
        print(json.dumps(result["skipped"], ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
