#!/usr/bin/env python3
"""应用版本升级的确定性落盘（场景二）。

Dockerfile 不再机械替换版本串：升级目标 Dockerfile 由 AI 结合看板证据包与上游
源码生成（见 ``scripts/harness/upgrade_apply.py``），本模块只做确定性的目录复制、
校验和元数据登记：

1. 复制该应用最新的 ``{old_version}/{os_version}/`` 目录为 ``{new_version}/{os_version}/``；
2. 用 AI 生成的完整 Dockerfile 覆盖新目录中的 Dockerfile，并做最小可用性校验；
3. 在应用根目录的 ``README.md`` / ``doc/image-info.yml`` 版本表里**追加**新版本行，
   旧版本行保留；
4. 往 ``meta.yml`` 追加 ``<new_version>-<oe_tag>: {path: ...}`` 条目。

Fail closed：生成内容为空、缺 ``FROM`` 或没有出现新版本号时直接报错并清理目录，
绝不产出半成品。
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from scripts.lib.task_spec import _os_tag


class UpgradeError(RuntimeError):
    """无法安全地完成升级落盘。"""


@dataclass(frozen=True)
class UpgradePlan:
    old_version: str
    os_version: str
    src_dir: Path


# README / image-info 是应用级文件（应用根目录），与版本目录同级。
# 两者都含版本表，升级时按「追加新行、保留旧行」处理。
_ROOT_VERSION_FILES = ("README.md", "doc/image-info.yml")


def _version_key(name: str) -> tuple:
    key: list[tuple[int, int, str]] = []
    for part in re.split(r"[.-]", name):
        if part.isdigit():
            key.append((1, int(part), ""))
        else:
            key.append((0, 0, part.lower()))
    return tuple(key)


def _numeric_parts(name: str) -> tuple[int, ...] | None:
    """纯数字版本（1.18.2 / 2026.11.16）转成可比较的 key；否则返回 None。"""
    parts = [part for part in re.split(r"[.-]", str(name or "").strip().lstrip("vV")) if part]
    if not parts or not all(part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def plan_upgrade(app_dir: Path, target_version: str = "") -> UpgradePlan:
    """选取复制源：优先同一版本线上、低于目标版本的最高目录。

    一个应用目录里可能同时存在多条版本线（例如 parquet 的 1.18.x 与 2.x
    分别对应不同上游产品）。目标版本是纯数字时，不能直接复制目录里版本号
    更高的另一条线，否则 README / doc 会被错误改写；此时只在严格低于目标
    版本的目录里选最高者。没有可用候选时回退到原来的“最高版本”行为。
    """
    dockerfiles = list(app_dir.glob("*/*/Dockerfile"))
    if not dockerfiles:
        raise UpgradeError(f"{app_dir.name}: 没有 */*/Dockerfile，无法规划升级")

    target = _numeric_parts(target_version) if target_version else None
    if target is not None:
        candidates = [
            dockerfile
            for dockerfile in dockerfiles
            if (parts := _numeric_parts(dockerfile.parts[-3])) is not None
            and parts < target
        ]
        if candidates:
            dockerfiles = candidates

    best = max(
        dockerfiles,
        key=lambda dockerfile: (
            _version_key(dockerfile.parts[-3]),
            _version_key(dockerfile.parts[-2]),
        ),
    )
    return UpgradePlan(
        old_version=best.parts[-3],
        os_version=best.parts[-2],
        src_dir=best.parent,
    )


def _version_pattern(version: str) -> re.Pattern[str]:
    # 整串匹配：左侧不能是字母/数字/点（避免 12.1.0 里的 2.1.0），
    # 右侧既不能接字母数字（避免 2.1.0rc1），也不能接 ".数字"（避免 2.1.0.1）。
    return re.compile(
        rf"(?<![\w.]){re.escape(version)}(?![\w])(?!\.\d)"
    )


def _version_tokens(old_version: str, new_version: str) -> list[tuple[str, str]]:
    """同一版本在 tag 里可能写成 28_25 / 28+25 / 4.0.3 等形态。"""
    pairs = {(old_version, new_version)}
    for separator in (".", "+"):
        if separator in old_version:
            pairs.add(
                (
                    old_version.replace(separator, "_"),
                    new_version.replace(separator, "_"),
                )
            )
    return sorted(pairs, key=lambda pair: len(pair[0]), reverse=True)


def _append_version_row(
    text: str, old_version: str, new_version: str
) -> tuple[str, bool]:
    """在 Markdown 版本表的旧版本行之后追加新版本行；旧行保留。

    只处理表格行（README / image-info 的版本表）；没有匹配表格时原样返回，
    避免对非表格内容做原地改写。
    """
    lines = text.splitlines(keepends=True)
    new_pattern = _version_pattern(new_version)
    if any(
        line.lstrip().startswith("|") and new_pattern.search(line)
        for line in lines
    ):
        return text, False

    old_pattern = _version_pattern(old_version)
    for index, line in enumerate(lines):
        if not line.lstrip().startswith("|") or not old_pattern.search(line):
            continue
        updated = line
        for old_token, new_token in _version_tokens(old_version, new_version):
            updated = _version_pattern(old_token).sub(new_token, updated)
        if updated == line:
            continue
        if not updated.endswith(("\n", "\r")):
            updated += "\n"
        lines.insert(index + 1, updated)
        return "".join(lines), True
    return text, False


# openEuler 官方镜像的 [source] / [update-source] / [debuginfo] 仓库 repodata
# 长期 404（repomd.xml 引用的 primary/filelists/updateinfo 在 repo.openeuler.org、
# de-repo、dl-cdn 等节点均不存在）。仅清缓存不够：重新拉到的还是同一份坏元数据。
# 因此每个构建阶段在 FROM 后先清空 dnf/yum 缓存强制刷新，再把
# skip_if_unavailable=True 写进 dnf.conf，让 dnf 跳过不可用仓库继续安装。
_CACHE_CLEAN_MARKER = "# autopilot: refresh dnf metadata"
_CACHE_CLEAN_RUN = (
    f"{_CACHE_CLEAN_MARKER}\n"
    "RUN rm -rf /var/cache/dnf /var/cache/yum \\\n"
    "    && (dnf clean all 2>/dev/null || yum clean all 2>/dev/null || true) \\\n"
    "    && mkdir -p /etc/dnf \\\n"
    "    && (grep -qxF skip_if_unavailable=True /etc/dnf/dnf.conf 2>/dev/null \\\n"
    "        || echo skip_if_unavailable=True >> /etc/dnf/dnf.conf)"
)


def ensure_repo_cache_cleaned(text: str) -> str:
    """在每个构建阶段的 FROM 后注入清缓存 + 容忍不可用仓库的 RUN。

    openEuler 的 source/update-source 仓库 repodata 404 会让任意 ``dnf install``
    直接失败；这里先清空元数据缓存强制重拉，再写 ``skip_if_unavailable=True``。
    已注入过时原样返回，保证可重复调用；``FROM scratch`` 阶段没有 shell，跳过。
    """
    if not text or _CACHE_CLEAN_MARKER in text:
        return text
    out: list[str] = []
    for line in text.splitlines():
        out.append(line)
        match = re.match(
            r"(?i)^\s*FROM\s+(?:--platform=\S+\s+)?(\S+)", line
        )
        if match and match.group(1).lower() != "scratch":
            out.append(_CACHE_CLEAN_RUN)
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


_SHORT_HASH_RE = re.compile(r"^[0-9a-fA-F]{7,11}$")


def _dockerfile_has_version(text: str, version: str) -> bool:
    pattern = re.compile(
        rf"(?<![0-9A-Za-z])v?{re.escape(version)}(?![0-9A-Za-z])",
        re.IGNORECASE,
    )
    if pattern.search(text) is not None:
        return True
    # 目录/tag 用 7 位短哈希时，Dockerfile 里应保留完整哈希（下载/检出的真实 ref）
    if _SHORT_HASH_RE.fullmatch(version):
        return re.search(
            rf"(?<![0-9a-fA-F]){re.escape(version)}[0-9a-fA-F]{{8,}}", text
        ) is not None
    return False


def check_dockerfile(text: str, new_version: str) -> list[str]:
    """校验 AI 生成的 Dockerfile 是否真的表达新版本；返回可读问题列表。"""
    findings: list[str] = []
    stripped = (text or "").strip()
    if not stripped:
        findings.append("生成的 Dockerfile 为空")
        return findings
    if re.search(r"(?im)^\s*FROM\s+\S+", stripped) is None:
        findings.append("生成的 Dockerfile 缺少 FROM 指令")
    if not _dockerfile_has_version(stripped, new_version):
        findings.append(f"生成的 Dockerfile 没有出现目标版本 {new_version}")
    return findings


def apply_upgrade(
    app_dir: Path,
    plan: UpgradePlan,
    new_version: str,
    dockerfile_text: str,
    *,
    supporting_files: dict[str, str] | None = None,
    match_version: str | None = None,
) -> list[Path]:
    """复制目录、写入 AI 生成的 Dockerfile、更新版本元数据。

    ``new_version`` 是目录与 tag 使用的版本名；``match_version`` 是 Dockerfile
    里应出现的真实版本（默认同 ``new_version``）。两者不同用于提交哈希作为
    版本号的场景：目录/tag 用 7 位短哈希，Dockerfile 保留完整哈希。
    ``supporting_files`` 是审计后需要改写的辅助文件（相对版本目录 -> 新内容），
    例如 ``build-QGIS.sh``；只在从旧版本目录复制出的新目录里落盘。
    """
    if new_version == plan.old_version:
        raise UpgradeError(f"{app_dir.name}: 目标版本与当前版本相同（{new_version}）")

    findings = check_dockerfile(dockerfile_text, match_version or new_version)
    if findings:
        raise UpgradeError(f"{app_dir.name}: " + "；".join(findings))

    dockerfile_text = ensure_repo_cache_cleaned(dockerfile_text)

    dst_dir = app_dir / new_version / plan.os_version
    if dst_dir.exists():
        raise UpgradeError(f"{app_dir.name}: 目标目录已存在 {dst_dir.relative_to(app_dir)}")

    shutil.copytree(plan.src_dir, dst_dir)

    meta = app_dir / "meta.yml"
    if not meta.is_file():
        shutil.rmtree(dst_dir, ignore_errors=True)
        raise UpgradeError(f"{app_dir.name}: 缺少 meta.yml，无法登记新版本")

    changed: list[Path] = []
    originals: dict[Path, str] = {}

    def _rewrite(path: Path, text: str) -> None:
        originals.setdefault(path, path.read_text(encoding="utf-8"))
        path.write_text(text, encoding="utf-8")
        changed.append(path)

    try:
        dockerfile = dst_dir / "Dockerfile"
        dockerfile.write_text(dockerfile_text.rstrip() + "\n", encoding="utf-8")
        changed.append(dockerfile)

        for rel, content in sorted((supporting_files or {}).items()):
            target = (dst_dir / rel).resolve()
            if dst_dir.resolve() not in target.parents:
                raise UpgradeError(f"{app_dir.name}: 辅助文件路径非法 {rel}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            changed.append(target)

        # 应用级文件：README / doc/image-info.yml 位于应用根目录，追加新版本行
        for rel in _ROOT_VERSION_FILES:
            path = app_dir / rel
            if not path.is_file():
                continue
            updated, appended = _append_version_row(
                path.read_text(encoding="utf-8"),
                plan.old_version,
                new_version,
            )
            if appended:
                _rewrite(path, updated)
        entry = _meta_entry_text(
            meta.read_text(encoding="utf-8"), new_version, plan.os_version
        )
        if entry is not None:
            _rewrite(meta, entry)
    except Exception:
        shutil.rmtree(dst_dir, ignore_errors=True)
        for path, text in originals.items():
            path.write_text(text, encoding="utf-8")
        raise
    return changed


def _meta_entry_text(text: str, new_version: str, os_version: str) -> str | None:
    """返回追加新条目后的 meta.yml 内容；条目已存在时返回 None。"""
    key = f"{new_version}-{_os_tag(os_version)}"
    if re.search(rf"^{re.escape(key)}\s*:", text, re.MULTILINE):
        return None
    entry = f"{key}:\n  path: {new_version}/{os_version}/Dockerfile\n"
    if text and not text.endswith("\n"):
        text += "\n"
    return text + entry
