#!/usr/bin/env python3
"""确定性应用版本升级（场景二）。

社区 easysoftware-autoupgrade 的做法是「机械替换版本串 + 提 PR」，本模块把这步
做成确定性代码，不做 AI 生成：

1. 复制该应用最新的 ``{old_version}/{os_version}/`` 目录为 ``{new_version}/{os_version}/``；
2. 新目录里的 ``Dockerfile``、应用根目录的 ``README.md`` / ``doc/image-info.yml`` 中把旧版本整串替换成新版本
   （README 与 doc 在目标仓里位于应用根目录，与版本目录同级，不随版本复制）；
3. 往 ``meta.yml`` 追加 ``<new_version>-<oe_tag>: {path: ...}`` 条目。

Fail closed：Dockerfile 里找不到旧版本串说明是特化写法（不是简单版本号拼接），
直接报错交人工，绝不产出半成品目录。
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from scripts.lib.task_spec import _os_tag


class UpgradeError(RuntimeError):
    """无法安全地做确定性升级。"""


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


def apply_upgrade(app_dir: Path, plan: UpgradePlan, new_version: str) -> list[Path]:
    """执行复制 + 版本串替换 + meta.yml 追加，返回被改动的文件列表。"""
    if new_version == plan.old_version:
        raise UpgradeError(f"{app_dir.name}: 目标版本与当前版本相同（{new_version}）")

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
        # 版本目录内：Dockerfile 随目录复制，在新目录里替换
        dockerfile = dst_dir / "Dockerfile"
        hits = 0
        if dockerfile.is_file():
            text = dockerfile.read_text(encoding="utf-8")
            updated, hits = _replace_version(text, plan.old_version, new_version)
            if hits:
                dockerfile.write_text(updated, encoding="utf-8")
                changed.append(dockerfile)
        if hits == 0:
            raise UpgradeError(
                f"{app_dir.name}: Dockerfile 中没有出现旧版本串 {plan.old_version}，"
                "无法确定性升级（需要人工处理）"
            )
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
