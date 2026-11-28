"""Normalized, serializable input contract for one image task."""

from __future__ import annotations

import json
import hashlib
import re
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from typing import Iterable, Mapping
from urllib.parse import urlparse


class TaskSpecError(ValueError):
    """Raised when workflow input cannot form a safe task."""


_DOMAINS = {
    "ai": "AI",
    "base": "Base",
    "bigdata": "Bigdata",
    "cloud": "Cloud",
    "database": "Database",
    "distroless": "Distroless",
    "hpc": "HPC",
    "others": "Others",
    "security": "Security",
    "storage": "Storage",
}
_APP_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
_OS_VERSION_RE = re.compile(r"^\d{2}\.\d{2}(?:-lts)?(?:-sp\d+)?$")
_SCENARIOS = {"new-image", "version-update", "oe-upgrade", "test-script"}
_ARCHITECTURES = {"x86_64", "aarch64"}
_MIGRATED_OPENEULER_GITEE_RE = re.compile(
    r"^(?:www\.)?gitee\.com/(?:openeuler|src-openeuler)(?:/|$)",
    re.IGNORECASE,
)


def _required(raw: Mapping[str, object], field: str) -> str:
    value = str(raw.get(field, "")).strip()
    if not value:
        raise TaskSpecError(f"{field}: value is required")
    return value


def _os_tag(os_version: str) -> str:
    suffix = os_version.replace("-lts-sp", "sp").replace("-lts", "lts")
    return "oe" + suffix.replace(".", "").replace("-", "")


_HASH_VERSION_RE = re.compile(r"^[0-9a-fA-F]{12,}$")
_LEADING_NON_DIGIT_RE = re.compile(r"^[^0-9]+")
_TRAILING_DECORATION_RE = re.compile(r"-[A-Za-z][A-Za-z0-9]*$")
_PRERELEASE_SUFFIX_RE = re.compile(
    r"-(?:a|b|rc|alpha|beta|pre|preview|dev|post|snapshot)\d*$",
    re.IGNORECASE,
)
_VERSION_SHAPE_RE = re.compile(r"\d+")


def _version_shape(name: str) -> str:
    """把版本名里的数字段替换成 ``#``，用于比较既有目录的命名形态。"""

    return _VERSION_SHAPE_RE.sub("#", name)


def _strip_trailing_decoration(name: str) -> str:
    """去掉 ``5.0.10-tentative`` 这类非版本语义的后缀；rc/beta 等预发布标记保留。"""

    match = _TRAILING_DECORATION_RE.search(name)
    if not match or _PRERELEASE_SUFFIX_RE.fullmatch(match.group(0)):
        return name
    return name[: match.start()]


def _matches_existing_shape(name: str, existing: Iterable[str]) -> bool:
    if not name or not name[0].isdigit():
        return False
    shape = _version_shape(name)
    for item in existing:
        candidate = str(item or "").strip()
        if not candidate or not candidate[0].isdigit():
            continue
        if _version_shape(candidate) == shape:
            return True
    return False


def naming_version(version: str, existing: Iterable[str] = ()) -> str:
    """版本目录与镜像 tag 使用的版本名。

    - 上游版本是提交哈希时只取前 7 位，避免把 40 位哈希写进目录名和
      ``<version>-oe<tag>``；
    - 目标仓已有版本目录采用「裸版本号」命名时（如 ``1.35.1``），去掉
      Issue/上游版本的前缀与装饰后缀：``v1.36.0`` → ``1.36.0``、
      ``npu-v0.3.14.post1`` → ``0.3.14.post1``、
      ``5.0.10-tentative`` → ``5.0.10``；形态对不上时保持原样，
      ``rc``/``beta`` 等预发布后缀不剥离。
    """

    text = str(version or "").strip()
    if _HASH_VERSION_RE.fullmatch(text):
        return text[:7]

    stripped = _LEADING_NON_DIGIT_RE.sub("", text)
    candidates = [stripped if stripped != text else text]
    for base in list(candidates):
        without_suffix = _strip_trailing_decoration(base)
        if without_suffix != base:
            candidates.append(without_suffix)
    for name in candidates:
        if _matches_existing_shape(name, existing):
            return name
    return text


@dataclass(frozen=True)
class TaskSpec:
    app: str
    version: str
    os_version: str
    domain: str
    source_url: str
    scenario: str = "new-image"
    schema_version: int = 1
    image_name: str | None = None
    mdu_path: str | None = None
    derive_from: str | None = None
    architectures: tuple[str, ...] = ()
    task_key: str | None = None

    @classmethod
    def from_workflow_dispatch(cls, raw: Mapping[str, object]) -> "TaskSpec":
        try:
            schema_version = int(raw.get("schema_version", 1))
        except (TypeError, ValueError) as error:
            raise TaskSpecError("schema_version: must be an integer") from error
        app = _required(raw, "app").lower()
        version = _required(raw, "version")
        os_version = _required(raw, "os_version").lower()
        domain_input = _required(raw, "domain")
        scenario = str(raw.get("scenario", "new-image")).strip().lower()
        source_url = str(raw.get("source_url", "")).strip()

        if scenario == "oe-upgrade" and schema_version != 2:
            raise TaskSpecError("schema_version: oe-upgrade requires schema v2")
        if scenario != "oe-upgrade" and schema_version != 1:
            raise TaskSpecError("schema_version: only oe-upgrade supports schema v2")

        if not _APP_RE.fullmatch(app):
            raise TaskSpecError("app: use lowercase letters, numbers, dot, dash or underscore")
        if not _VERSION_RE.fullmatch(version):
            raise TaskSpecError("version: contains unsafe characters")
        if not _OS_VERSION_RE.fullmatch(os_version):
            raise TaskSpecError("os_version: unsupported openEuler version format")
        if scenario not in _SCENARIOS:
            raise TaskSpecError(f"scenario: unsupported workflow {scenario!r}")

        domain = _DOMAINS.get(domain_input.lower())
        if domain is None:
            raise TaskSpecError(f"domain: unsupported category {domain_input!r}")

        if scenario == "oe-upgrade":
            if source_url:
                raise TaskSpecError("source_url: oe-upgrade must not change upstream")
        else:
            if not source_url:
                raise TaskSpecError("source_url: value is required")
            parsed_source = urlparse(source_url)
            if parsed_source.scheme != "https" or not parsed_source.netloc:
                raise TaskSpecError("source_url: an absolute HTTPS URL is required")
            source_location = parsed_source.netloc + parsed_source.path
            if _MIGRATED_OPENEULER_GITEE_RE.match(source_location):
                raise TaskSpecError(
                    "source_url: migrated openEuler repositories must use gitcode.com"
                )

        if schema_version == 1:
            return cls(
                app=app,
                version=version,
                os_version=os_version,
                domain=domain,
                source_url=source_url,
                scenario=scenario,
                schema_version=1,
            )

        image_name = _required(raw, "image_name").lower()
        if not _APP_RE.fullmatch(image_name):
            raise TaskSpecError("image_name: contains unsafe characters")
        mdu_path = _safe_posix_path(_required(raw, "mdu_path"), "mdu_path")
        if mdu_path.parts[0] != domain or len(mdu_path.parts) < 2:
            raise TaskSpecError("mdu_path: must be located below the selected domain")
        derive_from = _safe_posix_path(
            _required(raw, "derive_from"), "derive_from"
        )
        if len(derive_from.parts) != 2 or derive_from.parts[0] != version:
            raise TaskSpecError(
                "derive_from: expected <app-version>/<openEuler-version>"
            )
        if not _OS_VERSION_RE.fullmatch(derive_from.parts[1].lower()):
            raise TaskSpecError("derive_from: contains an unsupported openEuler version")
        architectures_raw = raw.get("architectures")
        if not isinstance(architectures_raw, (list, tuple)) or not architectures_raw:
            raise TaskSpecError("architectures: at least one architecture is required")
        architectures = tuple(str(value).strip() for value in architectures_raw)
        if len(set(architectures)) != len(architectures) or any(
            value not in _ARCHITECTURES for value in architectures
        ):
            raise TaskSpecError("architectures: unsupported or duplicate architecture")

        task_key = _task_key(str(mdu_path), version, os_version)
        supplied_task_key = str(raw.get("task_key", "")).strip()
        if supplied_task_key and supplied_task_key != task_key:
            raise TaskSpecError("task_key: does not match the TaskSpec contents")

        return cls(
            app=app,
            version=version,
            os_version=os_version,
            domain=domain,
            source_url=source_url,
            scenario=scenario,
            schema_version=2,
            image_name=image_name,
            mdu_path=str(mdu_path),
            derive_from=str(derive_from),
            architectures=architectures,
            task_key=task_key,
        )

    @property
    def task_id(self) -> str:
        if self.schema_version == 2 and self.task_key:
            return f"oe-upgrade-{self.task_key}"
        return "-".join(
            (
                self.scenario,
                self.domain.lower(),
                self.app,
                self.version,
                self.os_version,
            )
        )

    @property
    def branch(self) -> str:
        if self.schema_version == 2:
            assert self.image_name and self.mdu_path
            path_hash = hashlib.sha256(self.mdu_path.encode()).hexdigest()[:8]
            return (
                f"auto/oe-upgrade/{self.image_name}-{path_hash}/"
                f"{self.version}-{_os_tag(self.os_version)}"
            )
        return (
            f"auto/{self.scenario}/{self.app}/"
            f"{self.version}-{_os_tag(self.os_version)}"
        )

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, payload: str) -> "TaskSpec":
        raw = json.loads(payload)
        if not isinstance(raw, dict):
            raise TaskSpecError("TaskSpec JSON must contain an object")
        return cls.from_workflow_dispatch(raw)


def _safe_posix_path(value: str, field: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        value.startswith("/")
        or "\\" in value
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or str(path) != value
    ):
        raise TaskSpecError(f"{field}: must be a normalized relative POSIX path")
    return path


def _task_key(mdu_path: str, version: str, os_version: str) -> str:
    material = f"oe-upgrade\0{mdu_path}\0{version}\0{os_version}"
    return hashlib.sha256(material.encode()).hexdigest()[:16]
