#!/usr/bin/env python3
"""从 upstream-dashboard 拉软件列表，生成场景二的升级清单。

清单登记看板里的全部软件，并为每个软件标明它在哪个目标仓存在：

- ``docker``：``openeuler/openeuler-docker-images`` 的 ``{domain}/{app}`` 目录；
- ``conda``：``openeuler/conda-ecopkgs`` 的 ``packages/<package>`` 目录。

两个仓都存在时两个字段都写；运行时不遍历目标仓，``upgrade_scan.py`` 只读
``config/upgrade-apps.yml``（以及可选的 conda 仓快照）决定升级哪些目标。

用法::

    python scripts/utils/scrape_upgrade_apps.py \\
        --repo /path/to/oe-images \\
        --conda-repo /path/to/conda-ecopkgs \\
        --out config/upgrade-apps.yml

``--repo`` / ``--conda-repo`` 可以是完整克隆，也可以是
``--filter=blob:none --no-checkout`` 的浅克隆（脚本用 ``git ls-tree`` /
目录遍历取目录名，不读文件内容）。已有的 ``version`` / ``source_url`` /
``tag`` / ``build_notes`` / ``allow_downgrade`` 会按软件名保留。
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

import requests
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.lib.task_spec import _DOMAINS  # noqa: E402

DEFAULT_OUT = PROJECT_ROOT / "config" / "upgrade-apps.yml"
DOMAIN_DIRECTORIES = set(_DOMAINS.values())
DEFAULT_BASE = "https://upstream-dashboard.test.osinfra.cn"
PAGE_SIZE = 100
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json",
}
_SPLIT_RE = re.compile(r"[-_.\s]+")
_METADATA_FIELDS = ("version", "tag", "source_url", "build_notes")

# 看板软件名与 docker 仓目录名不一致的映射（键为看板软件名归一化结果）。
DOCKER_ALIASES = {
    "deal-ii": "dealii",
    "apache-http-server": "httpd",
    "udunits": "udunits-2",
    "lance": "lancedb",
    "wavewatch-iii": "wavewatch",
    "node-js": "node",
    "autodock-vina": "autodock",
}

# conda-ecopkgs 的目录名与看板软件名不一致时的映射（键为 conda 包名）。
CONDA_ALIASES = {
    "clang": "llvm",
    "delft3d4": "delft3d",
    "fslpy": "fsl",
    "libfuse": "fuse",
    "libgrpc": "grpc",
    "libprotobuf": "protobuf",
    "mpc": "libmpc",
    "nodejs": "node-js",
    "openmpi": "ompi",
    "pcre2": "pcre",
    "plink2": "plink",
    "psi4": "psi",
    "r-base": "r",
    "rabbitmq-server": "rabbitmq",
    "scala3": "scala",
    "scikit-learn": "sklearn",
    "subread": "featurecounts",
    "vina": "autodock-vina",
    "wise2": "genewise",
}

# 两库都没有、需要先用场景一（Create New Images）新建镜像的软件。
# 键为归一化后的看板名，值为 docker 业务域。
NEW_IMAGE_DOMAINS = {
    "grpc-java": "Others",
}


def normalize(name: str) -> str:
    """ClickHouse / click-house / click_house 统一成 clickhouse。"""
    return _SPLIT_RE.sub("-", str(name or "").strip().lower()).strip("-")


def fetch_software(base: str) -> list[dict]:
    items: list[dict] = []
    page = 1
    total = None
    while total is None or len(items) < total:
        response = requests.get(
            f"{base.rstrip('/')}/api/v1/software",
            params={"page": page, "page_size": PAGE_SIZE},
            headers=_HEADERS,
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        total = int(payload.get("total") or 0)
        batch = payload.get("items") or []
        if not batch:
            break
        items.extend(batch)
        page += 1
    return items


def index_target_repo(repo: Path) -> dict[str, list[tuple[str, str]]]:
    """normalized app -> [(domain, app)]；只依赖 git tree，不读文件。"""
    completed = subprocess.run(
        ["git", "-C", str(repo), "ls-tree", "-r", "--name-only", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(f"git ls-tree 失败: {completed.stderr.strip()[:500]}")

    index: dict[str, list[tuple[str, str]]] = {}
    seen: set[tuple[str, str]] = set()
    for line in completed.stdout.splitlines():
        parts = line.split("/")
        if len(parts) < 5 or parts[0] not in DOMAIN_DIRECTORIES:
            continue
        if parts[4] != "Dockerfile":
            continue
        pair = (parts[0], parts[1])
        if pair in seen:
            continue
        seen.add(pair)
        index.setdefault(normalize(parts[1]), []).append(pair)
    index = {key: sorted(set(value)) for key, value in index.items()}
    # 别名只补充真实目录名不存在的键，避免覆盖精确匹配。
    for alias, target in DOCKER_ALIASES.items():
        if alias in index:
            continue
        matches = index.get(normalize(target))
        if matches:
            index[alias] = list(matches)
    return index


def index_conda_repo(repo: Path) -> dict[str, list[str]]:
    """normalized key -> [package]；目录名优先，别名只补充缺失的键。"""
    packages_dir = repo / "packages"
    if not packages_dir.is_dir():
        raise SystemExit(f"conda 仓没有 packages 目录: {packages_dir}")

    real: dict[str, list[str]] = {}
    for child in sorted(packages_dir.iterdir()):
        if not child.is_dir():
            continue
        if not (child / "supported-versions.yml").is_file():
            continue
        real.setdefault(normalize(child.name), []).append(child.name)
    index = {key: sorted(set(value)) for key, value in real.items()}

    def add_alias(key: str, package: str) -> None:
        if key and key not in index:
            index[key] = [package]

    prefix = "bioconductor-"
    for packages in real.values():
        for package in packages:
            if package.startswith(prefix):
                add_alias(normalize(package[len(prefix) :]), package)
            alias = CONDA_ALIASES.get(package)
            if alias:
                add_alias(normalize(alias), package)
    return index


def _lookup(record: dict, index: dict[str, list]) -> list:
    for key in (record.get("name"), record.get("display_name")):
        if not key:
            continue
        matches = index.get(normalize(key), [])
        if matches:
            return matches
    candidates: set = set()
    for alias in record.get("aliases") or []:
        candidates.update(index.get(normalize(alias), []))
    return sorted(candidates)


def _choose(matches: list, preferred) -> object:
    """多个候选时优先沿用现有清单，否则取排序后的第一个。"""
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]
    if preferred is not None and preferred in matches:
        return preferred
    return sorted(matches)[0]


def _metadata(entry: dict) -> dict:
    metadata = {
        field: entry[field]
        for field in _METADATA_FIELDS
        if entry.get(field) not in (None, "")
    }
    if entry.get("allow_downgrade") is True:
        metadata["allow_downgrade"] = True
    return metadata


def _convert_existing(entry: dict) -> dict:
    """把旧结构（app/domain）或手工条目转成新结构。"""
    converted: dict = {"name": str(entry.get("name") or "")}
    docker = entry.get("docker")
    if isinstance(docker, dict):
        app = str(docker.get("app") or "").strip()
        domain = str(docker.get("domain") or "").strip()
        if app and domain:
            converted["docker"] = {"app": app, "domain": domain}
    else:
        app = str(entry.get("app") or "").strip()
        domain = str(entry.get("domain") or "").strip()
        if app and domain:
            converted["docker"] = {"app": app, "domain": domain}
    conda = entry.get("conda")
    if isinstance(conda, dict):
        package = str(conda.get("package") or "").strip()
    else:
        package = str(conda or "").strip()
    if package:
        converted["conda"] = {"package": package}
    create = entry.get("create")
    if isinstance(create, dict):
        app = str(create.get("app") or "").strip()
        domain = str(create.get("domain") or "").strip()
        if app and domain:
            converted["create"] = {"app": app, "domain": domain}
    converted.update(_metadata(entry))
    return converted


def _existing_indexes(
    entries: list[dict],
) -> tuple[dict[str, dict], dict[tuple[str, str], dict], dict[str, dict]]:
    by_name: dict[str, dict] = {}
    by_docker: dict[tuple[str, str], dict] = {}
    by_conda: dict[str, dict] = {}
    for raw in entries:
        entry = _convert_existing(raw) if "docker" not in raw else raw
        name = normalize(str(entry.get("name") or ""))
        if name and name not in by_name:
            by_name[name] = entry
        docker = entry.get("docker") or {}
        if docker:
            by_docker.setdefault(
                (str(docker.get("domain")), str(docker.get("app"))), entry
            )
        conda = entry.get("conda") or {}
        if conda:
            by_conda.setdefault(str(conda.get("package")), entry)
    return by_name, by_docker, by_conda


def build_entries(
    records: list[dict],
    repo: Path,
    conda_repo: Path | None = None,
    existing: list[dict] | None = None,
) -> tuple[list[dict], list[str], list[str]]:
    docker_index = index_target_repo(repo)
    conda_index = index_conda_repo(conda_repo) if conda_repo else {}
    by_name, by_docker, by_conda = _existing_indexes(existing or [])

    entries_by_name: dict[str, dict] = {}
    missing: list[str] = []
    ambiguous: list[str] = []
    used_docker: set[tuple[str, str]] = set()
    used_conda: set[str] = set()

    for record in sorted(
        records, key=lambda item: str(item.get("name") or "").casefold()
    ):
        if not record.get("is_active", True):
            continue
        raw_name = str(record.get("name") or "")
        name = raw_name
        metadata_source = by_name.get(normalize(raw_name), {})
        docker_matches = _lookup(record, docker_index)
        conda_matches = _lookup(record, conda_index)
        if not docker_matches and not conda_matches:
            new_image_domain = NEW_IMAGE_DOMAINS.get(normalize(raw_name))
            if new_image_domain:
                entry = entries_by_name.setdefault(
                    normalize(name), {"name": name}
                )
                entry["create"] = {
                    "app": raw_name,
                    "domain": new_image_domain,
                }
                repo_url = str(record.get("repo_url") or "").strip()
                if repo_url.startswith("https://"):
                    entry.setdefault("source_url", repo_url)
                entry.update(_metadata(metadata_source))
            else:
                missing.append(raw_name)
            continue

        entry = entries_by_name.setdefault(normalize(name), {"name": name})
        if docker_matches:
            preferred = None
            known = metadata_source.get("docker") or {}
            if known:
                preferred = (known.get("domain"), known.get("app"))
            pair = _choose(docker_matches, preferred)
            if pair is not None:
                if pair not in used_docker:
                    used_docker.add(pair)
                    entry["docker"] = {"app": pair[1], "domain": pair[0]}
                if len(docker_matches) > 1:
                    ambiguous.append(
                        f"{name} docker -> "
                        + ", ".join(f"{d}/{a}" for d, a in docker_matches)
                    )
                metadata_source = metadata_source or by_docker.get(pair, {})
        if conda_matches:
            preferred_package = (metadata_source.get("conda") or {}).get(
                "package"
            )
            package = _choose(conda_matches, preferred_package)
            if package is not None:
                if package not in used_conda:
                    used_conda.add(package)
                    entry["conda"] = {"package": package}
                if len(conda_matches) > 1:
                    ambiguous.append(
                        f"{name} conda -> {', '.join(conda_matches)}"
                    )
                metadata_source = metadata_source or by_conda.get(package, {})
        if "docker" not in entry and "conda" not in entry:
            # 看板里同名重复记录，目标已被前一条占用。
            continue
        entry.update(_metadata(metadata_source))

    entries = [
        entry
        for entry in entries_by_name.values()
        if entry.get("docker") or entry.get("conda") or entry.get("create")
    ]

    entries.sort(
        key=lambda entry: (
            str((entry.get("docker") or {}).get("domain") or "").casefold(),
            str((entry.get("docker") or {}).get("app") or "").casefold(),
            str((entry.get("conda") or {}).get("package") or "").casefold(),
        )
    )
    return entries, missing, ambiguous


def write_yaml(entries: list[dict], out: Path, domain: str = "") -> None:
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
        "# 场景二（应用自动升级）的软件清单，人工维护。\n"
        "# name: 看板软件名（传给 /api/v1/version/resolve）\n"
        "# docker: 在 openeuler-docker-images 的 {app, domain} 目录\n"
        "# conda:  在 openeuler/conda-ecopkgs 的 {package} 目录\n"
        "# create: 两库都没有，先用场景一新建镜像 {app, domain}\n"
        "# docker/conda 两个字段都在 = 两个仓都有；只有一个 = 只升级该仓。\n"
        "# 可选 version / tag / source_url / build_notes / allow_downgrade\n"
        "# 由脚本重新生成时按软件名保留。\n"
        f"# 初始内容由 scripts/utils/scrape_upgrade_apps.py 生成"
        f"{f'（看板 {domain} 域）' if domain else ''}。\n"
    )
    out.write_text(header + body, encoding="utf-8")


def _load_existing(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = data.get("apps") if isinstance(data, dict) else data
    return [entry for entry in entries or [] if isinstance(entry, dict)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="docker 目标仓克隆目录")
    parser.add_argument(
        "--conda-repo",
        default="",
        help="conda-ecopkgs 克隆目录（留空 = 不标记 conda 目标）",
    )
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument(
        "--base",
        default=os.environ.get("UPSTREAM_DASHBOARD_BASE", DEFAULT_BASE),
        help="看板地址",
    )
    parser.add_argument(
        "--domain",
        choices=("kunpeng", "ascend", "all"),
        default="kunpeng",
        help="只保留看板的某个域（默认 kunpeng；all = 全域）",
    )
    args = parser.parse_args()

    repo = Path(args.repo)
    if not repo.is_dir():
        raise SystemExit(f"repo not found: {repo}")
    conda_repo = Path(args.conda_repo) if args.conda_repo else None
    if conda_repo is not None and not conda_repo.is_dir():
        raise SystemExit(f"conda repo not found: {conda_repo}")

    out = Path(args.out)
    existing = _load_existing(out)
    records = fetch_software(args.base)
    if args.domain != "all":
        records = [item for item in records if item.get("domain") == args.domain]
    entries, missing, ambiguous = build_entries(
        records, repo, conda_repo=conda_repo, existing=existing
    )
    write_yaml(
        entries,
        out,
        domain="" if args.domain == "all" else args.domain,
    )

    docker_count = sum(1 for entry in entries if entry.get("docker"))
    conda_count = sum(1 for entry in entries if entry.get("conda"))
    both_count = sum(
        1 for entry in entries if entry.get("docker") and entry.get("conda")
    )
    print(f"看板软件 {len(records)} 个；写入 {len(entries)} 条 -> {out}")
    print(
        f"docker {docker_count} 个；conda {conda_count} 个；两者都有 "
        f"{both_count} 个"
    )
    print(f"两个仓都没有：{len(missing)} 个")
    if missing:
        print("  " + ", ".join(missing[:30]) + (" ..." if len(missing) > 30 else ""))
    if ambiguous:
        print(f"命中多个目录（已按现有清单/排序选择）{len(ambiguous)} 个：")
        for line in ambiguous[:10]:
            print(f"  {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
