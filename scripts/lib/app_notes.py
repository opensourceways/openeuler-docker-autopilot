"""每个应用的升级注意点文档（``config/app-notes/<app>.md``）。

Agent 在生成、修复、审计前读取对应文档，把正文注入提示；文档的 YAML front
matter 还可以覆盖该应用的构建预算。文档是历史经验的人工沉淀，不是门禁：
与固定 tag 的上游源码冲突时，仍以上游源码为准。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
NOTES_DIR = PROJECT_ROOT / "config" / "app-notes"

# 与 workflow 输入默认值保持一致（prepare 240 / validate 180 / agent 90）。
DEFAULT_GENERATE_TIMEOUT_MINUTES = 90
DEFAULT_BUILD_TIMEOUT_MINUTES = 180
DEFAULT_PREPARE_TIMEOUT_MINUTES = 240
MIN_TIMEOUT_MINUTES = 30
MAX_TIMEOUT_MINUTES = 360


@dataclass(frozen=True)
class AppNotes:
    app: str
    path: Path
    body: str
    build_timeout_minutes: int | None = None
    generate_timeout_minutes: int | None = None
    prepare_timeout_minutes: int | None = None


def notes_path(app: str) -> Path:
    return NOTES_DIR / f"{app}.md"


def _timeout(meta: dict, key: str) -> int | None:
    value = meta.get(key)
    if value is None:
        return None
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return None
    return max(MIN_TIMEOUT_MINUTES, min(minutes, MAX_TIMEOUT_MINUTES))


def _split_front_matter(text: str) -> tuple[dict, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    for index in range(1, len(lines)):
        if lines[index].strip() != "---":
            continue
        try:
            meta = yaml.safe_load("\n".join(lines[1:index])) or {}
        except yaml.YAMLError:
            return {}, text
        return (meta if isinstance(meta, dict) else {}), "\n".join(lines[index + 1:])
    return {}, text


def load(app: str) -> AppNotes | None:
    """读取该应用的注意点文档；不存在时返回 None（不影响主流程）。"""
    path = notes_path(app)
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    meta, body = _split_front_matter(text)
    build = _timeout(meta, "build_timeout_minutes")
    generate = _timeout(meta, "generate_timeout_minutes")
    prepare = _timeout(meta, "prepare_timeout_minutes")
    if prepare is None:
        derived = [
            min(minutes + 60, MAX_TIMEOUT_MINUTES)
            for minutes in (build, generate)
            if minutes is not None
        ]
        if derived:
            prepare = max(derived)
    return AppNotes(
        app=app,
        path=path,
        body=body.strip(),
        build_timeout_minutes=build,
        generate_timeout_minutes=generate,
        prepare_timeout_minutes=prepare,
    )


def render_prompt(notes: AppNotes | None) -> str:
    """把文档正文渲染成提示段落；没有文档时返回空串。"""
    if notes is None or not notes.body:
        return ""
    return (
        "\n\n## App upgrade notes\n\n"
        f"来源 `config/app-notes/{notes.app}.md`，是本应用历次升级沉淀的经验"
        "（构建耗时、已知坑、必要步骤）。优先遵守；与固定 tag 的上游源码冲突时"
        "以上游源码为准，并把差异写进 `assumptions`。\n\n"
        + notes.body.rstrip()
        + "\n"
    )


def generate_timeout_seconds(notes: AppNotes | None) -> int:
    minutes = (
        notes.generate_timeout_minutes
        if notes is not None and notes.generate_timeout_minutes
        else DEFAULT_GENERATE_TIMEOUT_MINUTES
    )
    return minutes * 60
