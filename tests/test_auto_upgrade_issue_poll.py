from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy" / "auto-upgrade-issue-poll"
SERVICE = DEPLOY / "auto-upgrade-issue-poll.service"
TIMER = DEPLOY / "auto-upgrade-issue-poll.timer"
INSTALL = DEPLOY / "install.sh"
DISPATCH = DEPLOY / "auto-upgrade-issue-poll.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "monitor_auto_upgrade_issues.yml"


def test_dispatch_script_targets_unified_monitor():
    dispatcher = DISPATCH.read_text(encoding="utf-8")
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "monitor_auto_upgrade_issues.yml" in dispatcher
    assert "dispatches" in dispatcher
    assert "/etc/oe-issue-poll/token" in dispatcher
    # 派发的 workflow 必须存在，避免改名后 timer 静默失效。
    assert "name: Watch 【自动升级需求】 GitCode Issues" in workflow


def test_timer_runs_every_five_minutes():
    timer = TIMER.read_text(encoding="utf-8")

    assert "OnCalendar=*:0/5" in timer
    assert "Unit=auto-upgrade-issue-poll.service" in timer


def test_units_and_installer_are_present():
    service = SERVICE.read_text(encoding="utf-8")
    installer = INSTALL.read_text(encoding="utf-8")

    assert "ExecStart=/usr/local/bin/auto-upgrade-issue-poll.sh" in service
    assert "systemctl enable --now auto-upgrade-issue-poll.timer" in installer
    assert "/etc/oe-issue-poll/token" in installer
