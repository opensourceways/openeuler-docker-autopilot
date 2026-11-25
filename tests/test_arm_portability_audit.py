import json
from pathlib import Path

import yaml

from scripts.harness import arm_portability_audit as audit

ROOT = Path(__file__).resolve().parent.parent


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "target"
    _write(
        repo / "Storage" / "demo" / "1.2.0" / "24.03-lts-sp1" / "Dockerfile",
        "FROM openeuler/openeuler:24.03-lts-sp1\nRUN make -j4\n",
    )
    _write(
        repo / "Storage" / "demo" / "1.10.0" / "24.03-lts-sp4" / "Dockerfile",
        (
            "FROM openeuler/openeuler:24.03-lts-sp4 AS build\n"
            "ARG TARGETARCH\n"
            "RUN dnf install -y gcc make && \\\n"
            "    ./configure --prefix=/usr && make -j4\n"
        ),
    )
    _write(
        repo / "Storage" / "demo" / "1.10.0" / "24.03-lts-sp4" / "build.sh",
        "sed -i 's/aarch64/arm64/' src/arch.c\n",
    )
    _write(
        repo / "Storage" / "demo" / "patches" / "arm.patch",
        "--- a/configure\n+++ b/configure\n",
    )
    _write(
        repo / "Storage" / "demo" / "doc" / "image-info.yml",
        "homepage: https://github.com/example/demo\n",
    )
    _write(
        repo / "Storage" / "binary" / "2.0" / "24.03-lts-sp4" / "Dockerfile",
        "FROM openeuler/openeuler:24.03-lts-sp4\nRUN dnf install -y make curl\n",
    )
    return repo


def test_latest_mdu_prefers_highest_version_then_os(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    items = audit.scan(repo, ["Storage"])
    demo = next(item for item in items if item["app"] == "demo")
    assert demo["version"] == "1.10.0"
    assert demo["os_version"] == "24.03-lts-sp4"
    assert demo["dockerfile_path"] == (
        "Storage/demo/1.10.0/24.03-lts-sp4/Dockerfile"
    )


def test_scan_reports_app_without_dockerfile(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "Storage" / "empty" / "1.0").mkdir(parents=True)
    items = audit.scan(repo, ["Storage"])
    empty = next(item for item in items if item["app"] == "empty")
    assert empty["skipped"]


def test_classify_build_ignores_package_install_lines() -> None:
    binary = "RUN dnf install -y make gcc curl\n"
    assert audit.classify_build(binary)["mode"] == "binary"
    source = "RUN ./configure --prefix=/usr && make -j4\n"
    assert audit.classify_build(source)["mode"] == "source"


def test_classify_build_detects_go_and_cmake() -> None:
    assert audit.classify_build("RUN go build ./cmd/app\n")["mode"] == "source"
    assert audit.classify_build("RUN cmake -B build && cmake --build build\n")[
        "mode"
    ] == "source"
    assert audit.classify_build("COPY app /usr/bin/app\n")["mode"] == "unknown"


def test_inspect_repo_adaptation_reports_arm_and_patch(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    app_dir = repo / "Storage" / "demo"
    dockerfile = (
        app_dir / "1.10.0" / "24.03-lts-sp4" / "Dockerfile"
    ).read_text(encoding="utf-8")
    result = audit.inspect_repo_adaptation(
        app_dir, dockerfile, "1.10.0", "24.03-lts-sp4"
    )
    assert result["arm"]["status"] == "yes"
    assert any("TARGETARCH" in line for line in result["arm"]["evidence"])
    assert any("arm.patch" in line for line in result["arm"]["evidence"])
    assert result["source_modified"]["status"] == "yes"
    assert any("sed -i" in line for line in result["source_modified"]["evidence"])


def test_inspect_repo_adaptation_ignores_other_versions(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    app_dir = repo / "Storage" / "demo"
    _write(
        app_dir / "0.9.0" / "24.03-lts-sp1" / "old.patch",
        "--- a/old\n+++ b/old\n",
    )
    dockerfile = "RUN make -j4\n"
    result = audit.inspect_repo_adaptation(app_dir, dockerfile, "1.10.0")
    assert not any("0.9.0" in line for line in result["source_modified"]["evidence"])


def test_latest_mdu_skips_openEuler_like_version_dirs(tmp_path: Path) -> None:
    repo = tmp_path / "target"
    _write(
        repo / "Storage" / "seaweedfs" / "24.03-lts-sp2" / "24.03-lts-sp2" / "Dockerfile",
        "FROM scratch\n",
    )
    _write(
        repo / "Storage" / "seaweedfs" / "4.03" / "24.03-lts-sp4" / "Dockerfile",
        "FROM scratch\n",
    )
    latest = audit.latest_mdu(repo / "Storage" / "seaweedfs")
    assert latest is not None
    assert latest[0] == "4.03"


def _fake_fetch(responses: dict[str, tuple[int, str]]):
    def fetch(url: str, timeout: float) -> tuple[int, str]:
        # 最长匹配优先：contents 路径同时包含 repos/{slug} 前缀。
        for key in sorted(responses, key=len, reverse=True):
            if key in url:
                return responses[key]
        return 404, ""

    return fetch


def test_probe_upstream_collects_readme_and_ci_evidence() -> None:
    fetch = _fake_fetch(
        {
            "api.github.com/repos/example/demo": (
                200,
                json.dumps({"default_branch": "main"}),
            ),
            "README.md": (200, "Demo builds on aarch64 and x86_64.\n"),
            "api.github.com/repos/example/demo/contents/.github/workflows": (
                200,
                json.dumps(
                    [{"name": "build-arm64.yml"}, {"name": "ci.yml"}]
                ),
            ),
        }
    )
    result = audit.probe_upstream("https://github.com/example/demo", fetch=fetch)
    assert result["status"] == "yes"
    assert any("README" in line for line in result["evidence"])
    assert any("build-arm64.yml" in line for line in result["evidence"])


def test_probe_upstream_degrades_to_unknown_without_network() -> None:
    result = audit.probe_upstream(
        "https://github.com/example/demo", fetch=lambda url, timeout: (0, "")
    )
    assert result["status"] == "unknown"
    assert result["warnings"]


def test_conclusion_rules() -> None:
    yes = {"status": "yes"}
    no = {"status": "no"}
    unknown = {"status": "unknown"}
    assert "跳过" in audit._conclusion("binary", yes, yes, yes)
    assert "本仓已包含 ARM 适配" in audit._conclusion("source", yes, no, no)
    assert "修改了上游源码" in audit._conclusion("source", no, yes, no)
    assert "上游已有 ARM 支持" in audit._conclusion("source", no, no, yes)
    assert "风险" in audit._conclusion("source", no, no, no)
    assert "证据不足" in audit._conclusion("source", no, no, unknown)


def test_report_writes_summary_and_json(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    output = tmp_path / "results.json"
    summary = tmp_path / "summary.md"
    assert (
        audit.main(
            [
                "report",
                "--repo",
                str(repo),
                "--domain",
                "Storage",
                "--output",
                str(output),
                "--summary",
                str(summary),
            ]
        )
        == 0
    )
    results = json.loads(output.read_text(encoding="utf-8"))
    assert {item["app"] for item in results} == {"demo", "binary"}
    text = summary.read_text(encoding="utf-8")
    assert "### 源码构建软件" in text
    assert "### 非源码构建（跳过）" in text
    assert "Storage | demo" in text


def test_workflow_is_manual_only() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "audit_arm_portability.yml").read_text(
            encoding="utf-8"
        )
    )
    # YAML 会把裸 "on" 解析成布尔 True。
    triggers = workflow.get("on", workflow.get(True))
    assert triggers == {"workflow_dispatch": triggers["workflow_dispatch"]}
    job = workflow["jobs"]["audit"]
    assert job["runs-on"].startswith("${{ fromJSON(inputs.runner_labels")
    names = [step.get("name", "") for step in job["steps"]]
    assert "Static audit" in names
    assert not any("PR" in name or "push" in name.lower() for name in names)
