"""Parse a GitCode Issue body to extract new image request parameters."""

import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Mapping
from datetime import datetime
from urllib.parse import quote, urlparse


class IssueParseError(ValueError):
    """Raised when a new-image Issue cannot form a complete request."""


_FIELD_PATTERNS = {
    "package_name": (
        r"Package Name",
        r"软件包名称\s*[（(]\s*Package Name\s*[）)]",
    ),
    "source_repo_url": (
        r"Upstream Repository",
        r"Source Repository",
        r"源码仓库\s*[（(]\s*Source Repository\s*[）)]",
    ),
    "domain": (
        r"Domain",
        r"所属领域\s*[（(]\s*Domain\s*[）)]",
    ),
    "os_version": (
        r"openEuler\s*版本\s*[（(]\s*openEuler Version\s*[）)]",
        r"openEuler Version",
    ),
    "app_version": (
        r"应用版本\s*[（(]\s*App Version\s*[）)]",
        r"App Version",
    ),
}

# 统一 Issue 的上游证据用「中文标签(旧字段名): 值」的平铺格式，等价的 JSON 结构为
# software / upstream_evidence.evidence / l3_evidence / install_candidates。
_FLAT_EVIDENCE_LABELS = {
    "软件名": "software.name",
    "源码仓库": "software.repo_url",
    "软件版本": "software.version",
    "上游支持检查点": "upstream_evidence.check_id",
    "上游支持检查点地址": "upstream_evidence.source_url",
    "门禁路径": "ci_workflows.workflow_path",
    "门禁地址": "ci_workflows.workflow_url",
    "门禁运行地址": "ci_workflows.workflow_run_url",
    "测试深度": "ci_workflows.test_depth",
    "中游检查点": "l3_evidence.check_id",
    "中游制品": "l3_evidence.artifact",
    "中游路径": "l3_evidence.source_url",
    "安装候选": "install_candidates.type",
    "候选包地址": "install_candidates.url",
    "候选包制品": "install_candidates.artifact",
}
_FLAT_EVIDENCE_KEYS = {
    **_FLAT_EVIDENCE_LABELS,
    **{path: path for path in _FLAT_EVIDENCE_LABELS.values()},
}
_FLAT_LINE_RE = re.compile(r"^\s*(?P<label>[^:：]{1,80}?)\s*[:：]\s*(?P<value>.*?)\s*$")
_LABEL_LEGACY_RE = re.compile(
    r"^(?P<name>.+?)\s*[（(]\s*(?P<legacy>[^（）()]+?)\s*[）)]\s*$"
)

_TITLE_RE = re.compile(
    r"^\s*【new-image】\s*add\s+(?P<request>.+?)\s+docker\s+image\s+"
    r"on\s+openEuler\s+(?P<os_version>\d{2}\.\d{2}"
    r"(?:-lts)?(?:-sp\d+)?)\s*$",
    re.IGNORECASE,
)
_UPGRADE_TITLE_RE = re.compile(
    r"^\s*(?:【自动升级需求】|【new-version】)\s*upgrade\s+"
    r"(?P<app>\S+)\s+to\s+(?P<version>\S+)\s+"
    r"on\s+openEuler\s+(?P<os_version>\d{2}\.\d{2}"
    r"(?:-lts)?(?:-sp\d+)?)\s*$",
    re.IGNORECASE,
)
_FENCED_JSON_RE = re.compile(
    r"```(?:json)?\s*(?P<payload>.*?)\s*```",
    re.IGNORECASE | re.DOTALL,
)
_APP_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
_TAG_VERSION_RE = re.compile(
    r"(?<!\d)(\d+(?:\.\d+)+(?:[A-Za-z][A-Za-z0-9]*)?"
    r"(?:[-+._][A-Za-z0-9]+(?:\.[A-Za-z0-9]+)*)*)"
)


def parse_issue_body(body: str) -> dict:
    """Extract structured fields from a new-image issue body.

    Expected format (from issue template):
        **Package Name**: nginx
        **Upstream Repository**: https://github.com/nginx/nginx
        **Domain**: Cloud
        **openEuler Version**: 24.03-lts
        **App Version**: 1.27.2
    """
    fields = {}

    for key, labels in _FIELD_PATTERNS.items():
        label_pattern = "|".join(f"(?:{label})" for label in labels)
        pattern = (
            rf"^\s*\*\*(?:{label_pattern})\s*[：:]?\*\*"
            rf"\s*[：:]?\s*(.+?)\s*$"
        )
        match = re.search(pattern, body, re.IGNORECASE | re.MULTILINE)
        if match and match.group(1).strip():
            fields[key] = match.group(1).strip()

    # Derive domain from domain name to directory
    domain_map = {
        "ai": "AI", "bigdata": "Bigdata", "big data": "Bigdata",
        "storage": "Storage", "database": "Database", "cloud": "Cloud",
        "distroless": "Distroless", "hpc": "HPC", "others": "Others",
        "人工智能": "AI", "大数据": "Bigdata", "存储": "Storage",
        "数据库": "Database", "云计算": "Cloud", "高性能计算": "HPC",
        "其他": "Others", "虚拟化": "Cloud", "云原生": "Cloud",
        "网络": "Cloud", "机器学习": "AI", "安全": "Security",
        "virtualization": "Cloud", "cloudnative": "Cloud",
        "network": "Cloud", "ml": "AI", "db": "Database",
        "security": "Security",
    }
    if "domain" in fields:
        fields["domain"] = domain_map.get(
            fields["domain"].lower().strip(), fields["domain"]
        )

    # Derive OS tag
    if "os_version" in fields:
        tag = fields["os_version"].lower().replace(".", "").replace("-", "")
        if not tag.startswith("oe"):
            tag = "oe" + tag
        fields["os_tag"] = tag

    return fields


def validate(fields: dict) -> list[str]:
    """Validate required fields, return list of missing fields."""
    required = ["package_name", "source_repo_url", "domain"]
    return [f for f in required if f not in fields]


def _version_from_tag(tag: str) -> str | None:
    versions = _TAG_VERSION_RE.findall(tag)
    if not versions:
        return None
    return versions[0]


def _version_from_source_url(source_url: str) -> str | None:
    path = [part for part in urlparse(source_url).path.split("/") if part]
    for marker in ("tree", "tag"):
        if marker not in path:
            continue
        index = path.index(marker)
        if index + 1 < len(path):
            return _version_from_tag(path[index + 1])
    return None


def _github_repository(source_url: str) -> tuple[str, str]:
    parsed = urlparse(source_url)
    parts = [part for part in parsed.path.split("/") if part]
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or len(parts) < 2
    ):
        raise IssueParseError(
            "automatic latest release lookup requires a GitHub repository URL"
        )
    owner = parts[0]
    repo = parts[1].removesuffix(".git")
    if not owner or not repo:
        raise IssueParseError(
            "automatic latest release lookup requires a GitHub repository URL"
        )
    return owner, repo


def _github_api_json(
    url: str,
    *,
    payload: Mapping[str, object] | None = None,
) -> object:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "openeuler-autopilot/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    github_token = os.environ.get("GITHUB_TOKEN", "").strip()
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode()
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise IssueParseError(f"GitHub API lookup failed: {error}") from error
    except (OSError, ValueError, urllib.error.URLError) as error:
        raise IssueParseError(f"GitHub API lookup failed: {error}") from error


_LATEST_TAG_QUERY = """
query LatestVersionTag($owner: String!, $repo: String!) {
  repository(owner: $owner, name: $repo) {
    refs(
      refPrefix: "refs/tags/"
      first: 100
      orderBy: {field: TAG_COMMIT_DATE, direction: DESC}
    ) {
      nodes {
        name
        target {
          ... on Commit {
            committedDate
          }
          ... on Tag {
            tagger {
              date
            }
            target {
              ... on Commit {
                committedDate
              }
            }
          }
        }
      }
    }
  }
}
"""


def _tag_timestamp(target: object) -> str:
    if not isinstance(target, Mapping):
        return ""
    tagger = target.get("tagger")
    if isinstance(tagger, Mapping) and tagger.get("date"):
        return str(tagger["date"])
    if target.get("committedDate"):
        return str(target["committedDate"])
    nested_target = target.get("target")
    if isinstance(nested_target, Mapping) and nested_target.get("committedDate"):
        return str(nested_target["committedDate"])
    return ""


def _latest_github_tag(owner: str, repo: str) -> tuple[str, str] | None:
    payload = _github_api_json(
        "https://api.github.com/graphql",
        payload={
            "query": _LATEST_TAG_QUERY,
            "variables": {"owner": owner, "repo": repo},
        },
    )
    if not isinstance(payload, Mapping) or payload.get("errors"):
        raise IssueParseError("GitHub latest tag lookup returned an error")
    data = payload.get("data")
    repository = data.get("repository") if isinstance(data, Mapping) else None
    refs = repository.get("refs") if isinstance(repository, Mapping) else None
    nodes = refs.get("nodes") if isinstance(refs, Mapping) else None
    if not isinstance(nodes, list):
        raise IssueParseError("GitHub latest tag lookup returned invalid data")
    tags = [
        (str(node.get("name", "")).strip(), _tag_timestamp(node.get("target")))
        for node in nodes
        if isinstance(node, Mapping) and str(node.get("name", "")).strip()
    ]
    if not tags:
        return None
    return next(
        (candidate for candidate in tags if _version_from_tag(candidate[0])),
        tags[0],
    )


def _timestamp_key(timestamp: str) -> float:
    if not timestamp:
        return float("-inf")
    try:
        return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return float("-inf")


def _latest_github_release_or_tag(source_url: str) -> tuple[str, str]:
    owner, repo = _github_repository(source_url)
    release_payload = _github_api_json(
        f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    )
    candidates = []
    if isinstance(release_payload, Mapping):
        release_tag = str(release_payload.get("tag_name", "")).strip()
        if release_tag:
            candidates.append(
                (
                    release_tag,
                    str(
                        release_payload.get("published_at")
                        or release_payload.get("created_at")
                        or ""
                    ),
                )
            )
    latest_tag = _latest_github_tag(owner, repo)
    if latest_tag is not None:
        candidates.append(latest_tag)
    if not candidates:
        raise IssueParseError("GitHub repository has no release or tag")
    tag, _timestamp = max(
        candidates,
        key=lambda candidate: _timestamp_key(candidate[1]),
    )
    version = _version_from_tag(tag) or tag
    pinned_url = (
        f"https://github.com/{owner}/{repo}/tree/{quote(tag, safe='')}"
    )
    return version, pinned_url


def parse_issue_request(title: str, body: str) -> dict[str, str]:
    """Parse the target repository's minimal new-image Issue format."""

    fields = parse_issue_body(body)
    missing = validate(fields)
    if missing:
        raise IssueParseError(
            f"missing required fields: {', '.join(missing)}"
        )

    match = _TITLE_RE.fullmatch(title)
    if match is None:
        raise IssueParseError(
            "title must match 【new-image】add <app> [version] docker image "
            "on openEuler <version>"
        )
    request_parts = match.group("request").split()
    if len(request_parts) not in {1, 2}:
        raise IssueParseError("title package or version is ambiguous")
    title_package = request_parts[0]
    if title_package.lower() != fields["package_name"].lower():
        raise IssueParseError("package in title and body must match")

    if len(request_parts) == 2:
        app_version = request_parts[1]
    else:
        app_version = _version_from_source_url(fields["source_repo_url"])
        if app_version is None:
            app_version, fields["source_repo_url"] = _latest_github_release_or_tag(
                fields["source_repo_url"]
            )
    return {
        "package_name": fields["package_name"],
        "source_repo_url": fields["source_repo_url"],
        "domain": fields["domain"],
        "os_version": match.group("os_version"),
        "app_version": app_version,
    }


def _upgrade_payload(body: str) -> Mapping[str, object] | None:
    """提取上游证据：优先旧的 JSON 块，其次统一格式的平铺字段。"""

    payload = _json_evidence(body)
    if payload is not None:
        return payload
    return _flat_evidence(body)


def _json_evidence(body: str) -> Mapping[str, object] | None:
    """尽量从正文提取 JSON 对象；没有或非法时返回 None。"""

    candidates: list[str] = []
    match = _FENCED_JSON_RE.search(body)
    if match is not None:
        candidates.append(match.group("payload"))
    start = body.find("{")
    end = body.rfind("}")
    if start >= 0 and end > start:
        candidates.append(body[start : end + 1])
    for raw in candidates:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, Mapping):
            return payload
    return None


def _flat_evidence_label(label: str) -> str | None:
    """把「软件名(software.name)」「软件名」「software.name」都归一到字段路径。"""

    text = label.strip().strip("*").strip()
    if not text:
        return None
    match = _LABEL_LEGACY_RE.match(text)
    names = [text]
    if match is not None:
        names = [match.group("name").strip(), match.group("legacy").strip()]
    for name in names:
        canonical = _FLAT_EVIDENCE_KEYS.get(name)
        if canonical is not None:
            return canonical
    return None


def _flat_evidence_value(value: str) -> str:
    return value.strip().strip("`").strip()


def _flat_evidence(body: str) -> dict[str, object] | None:
    """解析统一 Issue 的平铺证据块，组装成与旧 JSON 等价的结构。

    支持的字段形如 ``软件名: grpc`` 或 ``软件名(software.name): grpc``；同一段正文里
    可以重复出现 ``门禁路径`` / ``安装候选``，每组字段合成一个列表项。
    """

    values: dict[str, str] = {}
    ci_entries: list[dict[str, str]] = []
    ci_entry: dict[str, str] | None = None
    candidates: list[dict[str, str]] = []
    candidate: dict[str, str] | None = None
    matched = False

    for line in body.splitlines():
        match = _FLAT_LINE_RE.match(line)
        if match is None:
            continue
        canonical = _flat_evidence_label(match.group("label"))
        if canonical is None:
            continue
        value = _flat_evidence_value(match.group("value"))
        if not value:
            continue
        matched = True
        if canonical == "ci_workflows.workflow_path":
            ci_entry = {"workflow_path": value}
            ci_entries.append(ci_entry)
        elif canonical.startswith("ci_workflows."):
            if ci_entry is None:
                ci_entry = {}
                ci_entries.append(ci_entry)
            ci_entry[canonical.split(".", 1)[1]] = value
        elif canonical == "install_candidates.type":
            candidate = {"type": value}
            candidates.append(candidate)
        elif canonical.startswith("install_candidates."):
            if candidate is None:
                candidate = {}
                candidates.append(candidate)
            candidate[canonical.split(".", 1)[1]] = value
        else:
            values[canonical] = value

    if not matched:
        return None

    payload: dict[str, object] = {}
    software = {
        key.split(".", 1)[1]: value
        for key, value in values.items()
        if key.startswith("software.")
    }
    if software:
        payload["software"] = software
    evidence: dict[str, object] = {}
    for key in ("check_id", "source_url"):
        value = values.get(f"upstream_evidence.{key}")
        if value:
            evidence[key] = value
    if ci_entries:
        evidence["ci_workflows"] = ci_entries
    if evidence:
        payload["upstream_evidence"] = {"evidence": evidence}
    l3 = {
        key.split(".", 1)[1]: value
        for key, value in values.items()
        if key.startswith("l3_evidence.")
    }
    if l3:
        payload["l3_evidence"] = l3
    if candidates:
        payload["install_candidates"] = candidates
    if "software" not in payload:
        return None
    return payload


_UPGRADE_REQUIRED_FIELDS = ("software",)
_CANDIDATE_TYPES = {"source", "binary"}


def _mapping(value: object, field: str) -> Mapping:
    if not isinstance(value, Mapping):
        raise IssueParseError(f"{field} must be a JSON object")
    return value


def _required_text(mapping: Mapping, key: str, field: str) -> str:
    value = mapping.get(key)
    text = str(value).strip() if isinstance(value, (str, int, float)) else ""
    if not text:
        raise IssueParseError(f"{field}.{key} is required")
    return text


def _validate_upgrade_payload(payload: Mapping) -> None:
    """校验 Issue 正文里的上游证据 JSON。

    只有 ``software`` 必填；``upstream_evidence``、``l3_evidence`` 与
    ``install_candidates`` 可以省略或为空，存在时按结构校验。
    """

    for field in _UPGRADE_REQUIRED_FIELDS:
        if field not in payload:
            raise IssueParseError(f"missing required field: {field}")

    software = _mapping(payload["software"], "software")
    _required_text(software, "name", "software")
    _required_text(software, "version", "software")
    repo_url = _required_text(software, "repo_url", "software")
    if urlparse(repo_url).scheme != "https":
        raise IssueParseError("software.repo_url must be an HTTPS URL")

    upstream = payload.get("upstream_evidence")
    if upstream is not None:
        upstream = _mapping(upstream, "upstream_evidence")
        evidence = upstream.get("evidence")
        if evidence is not None:
            evidence = _mapping(
                evidence, "upstream_evidence.evidence"
            )
            workflows = evidence.get("ci_workflows")
            if workflows is not None:
                if not isinstance(workflows, list):
                    raise IssueParseError(
                        "upstream_evidence.evidence.ci_workflows must be a list"
                    )
                for index, workflow in enumerate(workflows):
                    _mapping(
                        workflow,
                        f"upstream_evidence.evidence.ci_workflows[{index}]",
                    )

    l3 = payload.get("l3_evidence")
    if l3 is not None:
        _mapping(l3, "l3_evidence")

    candidates = payload.get("install_candidates")
    if candidates is not None:
        if not isinstance(candidates, list):
            raise IssueParseError("install_candidates must be a list")
        for index, candidate in enumerate(candidates):
            field = f"install_candidates[{index}]"
            item = _mapping(candidate, field)
            kind = _required_text(item, "type", field)
            if kind not in _CANDIDATE_TYPES:
                raise IssueParseError(
                    f"{field}.type must be source or binary"
                )
            url = _required_text(item, "url", field)
            if urlparse(url).scheme != "https":
                raise IssueParseError(f"{field}.url must be an HTTPS URL")


def _normalize_version(value: str) -> str:
    return str(value or "").strip().lstrip("vV").lower()


def parse_upgrade_issue_request(title: str, body: str) -> dict[str, object]:
    """Parse one scenario-two Issue.

    Title format:
        【自动升级需求】upgrade <app> to <version> on openEuler <os_version>

    旧的 ``【new-version】upgrade ...`` 标题同样接受。正文用平铺字段给出上游
    证据（``软件名`` / ``源码仓库`` / ``软件版本`` 必填），JSON 证据块仍可识别；
    ``software.name`` / ``software.version`` 必须与标题一致。
    """

    match = _UPGRADE_TITLE_RE.fullmatch(title)
    if match is None:
        raise IssueParseError(
            "title must match 【自动升级需求】upgrade <app> to <version> "
            "on openEuler <version>"
        )
    app = match.group("app").strip()
    version = match.group("version").strip()
    os_version = match.group("os_version").strip()
    if not _APP_NAME_RE.fullmatch(app):
        raise IssueParseError(f"invalid app name in title: {app!r}")
    if not _VERSION_RE.fullmatch(version):
        raise IssueParseError(f"invalid version in title: {version!r}")

    payload = _upgrade_payload(body)
    if payload is None:
        raise IssueParseError(
            "body must contain the upstream evidence JSON object"
        )
    _validate_upgrade_payload(payload)

    software = _mapping(payload["software"], "software")
    if str(software["name"]).strip().lower() != app.lower():
        raise IssueParseError(
            "software.name must match the app in the title"
        )
    if _normalize_version(str(software["version"])) != _normalize_version(
        version
    ):
        raise IssueParseError(
            "software.version must match the version in the title"
        )

    return {
        "app": app,
        "version": version,
        "os_version": os_version,
        "source_url": str(software["repo_url"]).strip(),
        "evidence": payload,
    }


def main() -> None:
    if len(sys.argv) < 2:
        # Try reading from GITHUB_EVENT_PATH
        event_path = os.environ.get("GITHUB_EVENT_PATH")
        if event_path:
            with open(event_path) as f:
                event = json.load(f)
            body = event.get("issue", {}).get("body", "")
        else:
            body = sys.stdin.read()
    else:
        body = sys.argv[1]

    fields = parse_issue_body(body)
    missing = validate(fields)

    if missing:
        print(f"::error::Missing required fields: {', '.join(missing)}")
        sys.exit(1)

    # Output as GitHub Actions output format
    for key, value in fields.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
