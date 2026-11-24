"""辅助脚本审计：Dockerfile 引用的同目录文件必须逐个给出修复/保留结论。

场景二只审 Dockerfile 会漏掉真正承载构建逻辑的脚本。QGIS 4.4 的失败就是
``build-QGIS.sh`` 里的 cmake 参数没有关掉测试套件，而 Dockerfile 本身完全
正常；升级 Agent 看不到这个文件，自然不会改。

本模块做三件事：

1. ``collect``：按 Dockerfile 的 COPY/ADD/RUN 引用，枚举版本目录里的辅助文件；
2. ``deterministic_findings``：确定性审计（``bash -n``、写死的旧版本号）；
3. ``validate``：要求 Agent 对每个辅助文件返回
   ``{"path", "verdict": unchanged|updated, "content", "reason"}``，
   缺一个就判失败，只允许改已枚举的文件。
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

# 单个文件内联进提示的上限；超过时只给指纹，不允许 Agent 重写（避免截断落盘）。
MAX_INLINE_CHARS = 20000
_TOKEN_RE = re.compile(r"[^\s\"'\\]+")
_SCRIPT_SUFFIXES = (".sh", ".bash")

VERDICTS = ("unchanged", "updated")


@dataclass(frozen=True)
class SupportingFile:
    path: str
    sha256: str
    content: str
    truncated: bool = False

    @property
    def is_script(self) -> bool:
        return self.path.endswith(_SCRIPT_SUFFIXES)

    @property
    def updatable(self) -> bool:
        return not self.truncated


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def collect(version_dir: Path, dockerfile_text: str) -> list[SupportingFile]:
    """枚举 Dockerfile 明确引用到的同目录文件。

    ``COPY . /opt`` 这种整目录复制会把目录里所有文件都算进来。Dockerfile
    本身不是辅助脚本，排除。
    """
    root = Path(version_dir)
    if not root.is_dir():
        return []
    tokens = set(_TOKEN_RE.findall(dockerfile_text or ""))
    include_all = "." in tokens
    files: list[SupportingFile] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel == "Dockerfile":
            continue
        if not include_all and rel not in tokens and path.name not in tokens:
            continue
        text = _read(path)
        files.append(
            SupportingFile(
                path=rel,
                sha256=_digest(text),
                content=text[:MAX_INLINE_CHARS],
                truncated=len(text) > MAX_INLINE_CHARS,
            )
        )
    return files


def render_prompt(files: list[SupportingFile]) -> str:
    """把辅助文件与审计要求写进 Agent 提示。"""
    if not files:
        return ""
    paths = ", ".join(f"`{item.path}`" for item in files)
    parts = [
        "\n## Supporting build scripts (mandatory audit)\n\n"
        "Dockerfile 里 COPY/ADD 或直接执行的同目录文件（本次："
        + paths
        + "）同样是构建的一部分，升级必须逐个审计，不能只看 Dockerfile。\n"
        "- 检查写死的旧版本号、tag、下载地址；\n"
        "- 检查编译/测试开关：如果新版本会在当前 openEuler 上编译测试套件而缺依赖，"
        "必须在脚本里关闭（例如 cmake 的 `-DBUILD_TESTING=OFF`），不能留给构建期报错；\n"
        "- 检查语法与直接执行权限相关的问题。\n\n"
        "最终响应必须为**每个**文件返回一条 `supporting_files` 记录：\n"
        '`{"path": "<相对版本目录>", "verdict": "unchanged"|"updated", '
        '"content": null 或完整新文本, "reason": "结论与依据"}`\n'
        "缺任何一条、或返回清单外的路径，都会被确定性校验判为未完成审计。\n"
    ]
    for item in files:
        note = (
            f"\n\n（文件超过 {MAX_INLINE_CHARS} 字符，只给指纹；不返回 content，"
            "verdict 只能为 unchanged）"
            if item.truncated
            else ""
        )
        parts.append(
            f"\n### {item.path} (sha256={item.sha256})\n"
            + ("```bash\n" if item.is_script else "```text\n")
            + item.content.rstrip()
            + "\n```"
            + note
            + "\n"
        )
    return "".join(parts)


def _bash_syntax_findings(path: str, content: str) -> list[str]:
    bash = shutil.which("bash")
    if not bash:
        return []
    try:
        completed = subprocess.run(
            [bash, "-n"],
            input=content,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError:
        # 当前环境没有可用的 bash；语法检查交给构建期。
        return []
    if completed.returncode in (0, 127):
        return []
    detail = (completed.stderr or completed.stdout or "").strip()
    if not detail:
        # bash 存在但跑不动（如 Windows 上的 WSL shim）：无从判断语法。
        return []
    return [f"{path}: 不是合法 Bash：{detail[:300]}"]


def _mentions_version(text: str, version: str) -> bool:
    if not version:
        return False
    pattern = re.compile(
        rf"(?<![0-9A-Za-z])v?{re.escape(version)}(?![0-9A-Za-z])",
        re.IGNORECASE,
    )
    return pattern.search(text) is not None


def deterministic_findings(
    files: list[SupportingFile],
    *,
    old_version: str = "",
    new_version: str = "",
) -> list[str]:
    """不依赖 Agent 的审计结论；脚本必须能过 ``bash -n`` 且不留旧版本号。"""
    findings: list[str] = []
    for item in files:
        if not item.is_script or item.truncated:
            continue
        findings.extend(_bash_syntax_findings(item.path, item.content))
        if (
            old_version
            and old_version != new_version
            and _mentions_version(item.content, old_version)
            and not _mentions_version(item.content, new_version)
        ):
            findings.append(
                f"{item.path}: 仍写死旧版本 {old_version}，需要更新或改为参数化"
            )
    return findings


def _safe_path(root: Path, rel: str) -> Path | None:
    candidate = Path(rel)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    resolved = (Path(root) / candidate).resolve()
    try:
        resolved.relative_to(Path(root).resolve())
    except ValueError:
        return None
    return resolved


def validate(
    files: list[SupportingFile], payload: dict
) -> tuple[list[str], dict[str, str]]:
    """校验 Agent 的 supporting_files 审计结论；返回 (问题, 需要写回的内容)。"""
    if not files:
        return [], {}
    entries = payload.get("supporting_files")
    if not isinstance(entries, list):
        return ["缺少 supporting_files：必须逐个审计 Dockerfile 引用的辅助文件"], {}

    remaining = {item.path for item in files}
    updates: dict[str, str] = {}
    findings: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            findings.append("supporting_files 条目必须是对象")
            continue
        path = str(entry.get("path") or "").strip()
        if path not in remaining:
            findings.append(f"supporting_files 返回了清单外的路径：{path or '(空)'}")
            continue
        remaining.discard(path)
        verdict = str(entry.get("verdict") or "").strip().lower()
        if verdict not in VERDICTS:
            findings.append(f"{path}: verdict 必须是 unchanged 或 updated")
            continue
        if verdict == "unchanged":
            continue
        item = next(candidate for candidate in files if candidate.path == path)
        if not item.updatable:
            findings.append(f"{path}: 文件过大不允许重写")
            continue
        content = entry.get("content")
        if not isinstance(content, str) or not content.strip():
            findings.append(f"{path}: verdict=updated 时必须返回完整 content")
            continue
        if _digest(content) == item.sha256:
            findings.append(f"{path}: 标记 updated 但内容没有变化")
            continue
        if item.is_script:
            findings.extend(_bash_syntax_findings(path, content))
        updates[path] = content

    for path in sorted(remaining):
        findings.append(f"{path}: 缺少审计结论（supporting_files）")
    return findings, updates


def apply_updates(root: Path, updates: dict[str, str]) -> list[Path]:
    """把审计通过的新内容写回版本目录；返回实际写入的文件。"""
    changed: list[Path] = []
    for rel, content in sorted(updates.items()):
        target = _safe_path(Path(root), rel)
        if target is None:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        changed.append(target)
    return changed
