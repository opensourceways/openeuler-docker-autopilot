#!/usr/bin/env python3
"""应用版本升级的确定性落盘（场景二）。

Dockerfile 不再机械替换版本串：升级目标 Dockerfile 由 AI 结合看板证据包与上游
源码生成（见 ``scripts/harness/upgrade_apply.py``），本模块只做确定性的目录复制、
校验和元数据登记：

1. 复制该应用最新的 ``{old_version}/{os_version}/`` 目录为 ``{new_version}/{os_version}/``；
2. 用 AI 生成的完整 Dockerfile 覆盖新目录中的 Dockerfile，并做最小可用性校验；
3. 应用根目录的 ``README.md`` / ``doc/image-info.yml`` 中把旧版本整串替换成新版本；
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


# README / image-info 是应用级文件（应用根目录），与版本目录同级，原地更新。
_ROOT_VERSION_FILES = ("README.md", "doc/image-info.yml")


def _version_key(name: str) -> tuple:
    key: list[tuple[int, int, str]] = []
    for part in re.split(r"[.-]", name):
        if part.isdigit():
            key.append((1, int(part), ""))
        else:
            key.append((0, 0, part.lower()))
    return tuple(key)


def plan_upgrade(app_dir: Path) -> UpgradePlan:
    """取该应用版本号最高、os 也最高的镜像目录作为复制源。"""
    best: Path | None = None
    best_key: tuple | None = None
    for dockerfile in app_dir.glob("*/*/Dockerfile"):
        key = (_version_key(dockerfile.parts[-3]), _version_key(dockerfile.parts[-2]))
        if best is None or key > best_key:
            best, best_key = dockerfile, key
    if best is None:
        raise UpgradeError(f"{app_dir.name}: 没有 */*/Dockerfile，无法规划升级")
    return UpgradePlan(
        old_version=best.parts[-3],
        os_version=best.parts[-2],
        src_dir=best.parent,
    )


def _replace_version(text: str, old_version: str, new_version: str) -> tuple[str, int]:
    # 整串替换：左侧不能是字母/数字/点（避免 12.1.0 里的 2.1.0），
    # 右侧既不能接字母数字（避免 2.1.0rc1），也不能接 ".数字"（避免 2.1.0.1）。
    pattern = re.compile(
        rf"(?<![\w.]){re.escape(old_version)}(?![\w])(?!\.\d)"
    )
    return pattern.subn(new_version, text)


# openEuler 24.03 基础镜像的 openEuler.repo 里，[update] / [update-source] /
# [source] / [debuginfo] 近期返回 404 或校验和不匹配，任何 dnf/yum 元数据刷新
# 都会失败；这些仓库只提供源码/调试包/更新包，镜像构建用不到，直接在 FROM 后禁用。
_BROKEN_REPO_RUN = (
    "RUN for f in /etc/yum.repos.d/*.repo; do [ -f \"$f\" ] || continue; "
    "awk 'BEGIN{broken=0} /^\\[/"
    "{broken=($0 ~ /^\\[(debuginfo|source|update|update-source)\\]$/)} "
    "{if(broken && $0==\"enabled=1\") print \"enabled=0\"; else print}' "
    "\"$f\" > \"$f.new\" && mv \"$f.new\" \"$f\"; done"
)


def ensure_broken_repos_disabled(text: str) -> str:
    """在每个构建阶段的 FROM 后注入禁用损坏仓库的 RUN。

    已注入过（含 ``/etc/yum.repos.d/*.repo``）时原样返回，保证可重复调用；
    ``FROM scratch`` 阶段没有 shell/awk，跳过注入。
    """
    if not text or "/etc/yum.repos.d/*.repo" in text:
        return text
    out: list[str] = []
    for line in text.splitlines():
        out.append(line)
        match = re.match(
            r"(?i)^\s*FROM\s+(?:--platform=\S+\s+)?(\S+)", line
        )
        if match and match.group(1).lower() != "scratch":
            out.append(_BROKEN_REPO_RUN)
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


def check_dockerfile(text: str, new_version: str) -> list[str]:
    """校验 AI 生成的 Dockerfile 是否真的表达新版本；返回可读问题列表。"""
    findings: list[str] = []
    stripped = (text or "").strip()
    if not stripped:
        findings.append("生成的 Dockerfile 为空")
        return findings
    if re.search(r"(?im)^\s*FROM\s+\S+", stripped) is None:
        findings.append("生成的 Dockerfile 缺少 FROM 指令")
    pattern = re.compile(
        rf"(?<![0-9A-Za-z])v?{re.escape(new_version)}(?![0-9A-Za-z])",
        re.IGNORECASE,
    )
    if pattern.search(stripped) is None:
        findings.append(f"生成的 Dockerfile 没有出现目标版本 {new_version}")
    return findings


def apply_upgrade(
    app_dir: Path,
    plan: UpgradePlan,
    new_version: str,
    dockerfile_text: str,
) -> list[Path]:
    """复制目录、写入 AI 生成的 Dockerfile、更新版本元数据。"""
    if new_version == plan.old_version:
        raise UpgradeError(f"{app_dir.name}: 目标版本与当前版本相同（{new_version}）")

    findings = check_dockerfile(dockerfile_text, new_version)
    if findings:
        raise UpgradeError(f"{app_dir.name}: " + "；".join(findings))

    dockerfile_text = ensure_broken_repos_disabled(dockerfile_text)

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

        # 应用级文件：README / doc/image-info.yml 位于应用根目录，原地更新
        for rel in _ROOT_VERSION_FILES:
            path = app_dir / rel
            if not path.is_file():
                continue
            updated, count = _replace_version(
                path.read_text(encoding="utf-8"), plan.old_version, new_version
            )
            if count:
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
