from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "runner_disk_guard.yml"
SERVICE = ROOT / "deploy" / "runner-disk-guard" / "runner-disk-guard.service"
TIMER = ROOT / "deploy" / "runner-disk-guard" / "runner-disk-guard.timer"
INSTALL = ROOT / "deploy" / "runner-disk-guard" / "install.sh"
DISPATCH = ROOT / "deploy" / "runner-disk-guard" / "runner-disk-guard.sh"


def _load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _on(data):
    return data.get("on", data.get(True))


def test_workflow_has_schedule_and_manual_threshold_inputs():
    data = _load(WORKFLOW)
    trigger = _on(data)

    assert set(trigger) == {"schedule", "workflow_dispatch"}
    assert trigger["schedule"][0]["cron"] == "17 * * * *"
    inputs = trigger["workflow_dispatch"]["inputs"]
    assert inputs["min_free_gib"]["default"] == "70"
    assert inputs["dry_run"]["type"] == "boolean"


def test_matrix_covers_each_primary_runner_once():
    data = _load(WORKFLOW)
    job = data["jobs"]["guard"]

    assert job["strategy"]["max-parallel"] == 5
    assert job["timeout-minutes"] == 20
    matrix = job["strategy"]["matrix"]["include"]
    labels = " ".join(item["labels"] for item in matrix)
    for runner in (
        "oe-issue-poll",
        "oe-fix-amd64",
        "oe-image-x86",
        "oe-fix-arm64",
        "oe-image-arm64",
    ):
        assert runner in labels
    assert job["runs-on"] == "${{ fromJSON(matrix.labels) }}"


def test_below_threshold_cleans_cache_images_and_workdirs():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "MIN_FREE_GIB" in text
    assert "vars.RUNNER_DISK_MIN_FREE_GIB" in text
    assert "docker buildx prune -af" in text
    assert "docker builder prune -af" in text
    assert "docker image prune -af" in text
    assert "docker container prune -f" in text
    assert "-mtime +7" in text
    assert "_diag" in text
    # 同机另一个实例构建中时，跳过全量缓存清理。
    assert "running containers detected" in text


def test_units_and_installer_are_present():
    service = SERVICE.read_text(encoding="utf-8")
    timer = TIMER.read_text(encoding="utf-8")
    installer = INSTALL.read_text(encoding="utf-8")
    dispatcher = DISPATCH.read_text(encoding="utf-8")

    assert "ExecStart=/usr/local/bin/runner-disk-guard.sh" in service
    assert "OnCalendar=*:0/30" in timer
    assert "runner_disk_guard.yml" in dispatcher
    assert "dispatches" in dispatcher
    assert "systemctl enable --now runner-disk-guard.timer" in installer
    assert "/etc/oe-issue-poll/token" in installer
