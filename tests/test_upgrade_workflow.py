"""场景二（应用自动升级）编排结构回归。"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
UPGRADE = ROOT / '.github' / 'workflows' / 'upgrade_upstream_versions.yml'
APP = ROOT / '.github' / 'workflows' / '_upgrade_app.yml'


def _workflow(path: Path):
    data = yaml.safe_load(path.read_text(encoding='utf-8'))
    assert isinstance(data, dict)
    return data


def _trigger(data):
    return data.get('on', data.get(True))


def _squash(value) -> str:
    return ' '.join(str(value).split())


def test_daily_schedule_plus_manual_app_and_version():
    trigger = _trigger(_workflow(UPGRADE))
    assert trigger['schedule'] == [{'cron': '0 1 * * *'}]
    inputs = trigger['workflow_dispatch']['inputs']
    assert set(inputs) >= {'app', 'version', 'limit', 'runner_labels'}


def test_discover_scans_the_dashboard_and_feeds_the_matrix():
    jobs = _workflow(UPGRADE)['jobs']
    assert list(jobs) == ['discover', 'upgrade', 'summary']

    scan_text = _squash(jobs['discover']['steps'])
    assert 'upgrade_scan.py' in scan_text
    assert '--format github-output' in scan_text
    assert 'gitcode.com' in scan_text
    # 看板地址可覆盖，且默认值写在 workflow 级 env
    assert 'UPSTREAM_DASHBOARD_BASE' in UPGRADE.read_text(encoding='utf-8')

    upgrade = jobs['upgrade']
    assert upgrade['needs'] == 'discover'
    assert upgrade['uses'] == './.github/workflows/_upgrade_app.yml'
    assert upgrade['strategy']['matrix']['item'] == \
        '${{ fromJSON(needs.discover.outputs.updates) }}'
    assert upgrade['with']['item'] == '${{ toJSON(matrix.item) }}'


def test_each_app_runs_prepare_dual_arch_validation_then_pr():
    jobs = _workflow(APP)['jobs']
    assert list(jobs) == ['prepare', 'validate-x86_64', 'validate-aarch64', 'open-pr']
    assert _squash(jobs['validate-x86_64']['runs-on']) == '${{ fromJSON(inputs.x64_runner_labels) }}'
    assert _squash(jobs['validate-aarch64']['runs-on']) == '${{ fromJSON(inputs.arm64_runner_labels) }}'
    # arm64 的机器只能换机器，不能换架构
    arm64_labels = _trigger(_workflow(APP))['workflow_call']['inputs']['arm64_runner_labels']['default']
    assert 'ARM64' in arm64_labels

    for name in ('validate-x86_64', 'validate-aarch64'):
        text = _squash(jobs[name]['steps'])
        assert 'phase1-native-validate' in text
        assert 'task-spec' in text
        # 验证失败不开 PR，但证据要保留
        assert 'always()' in _squash(jobs[name])
    assert 'success()' in _squash(jobs['open-pr']['if'])
    assert 'upgrade_open_pr.py' in _squash(jobs['open-pr']['steps'])


def test_prepare_generates_tests_and_applies_the_deterministic_bump():
    prepare = _workflow(APP)['jobs']['prepare']
    text = _squash(prepare['steps'])
    assert 'upgrade_apply.py' in text
    assert 'git clone' in text
    # 必须完整克隆：浅克隆推不到 GitCode
    assert '--depth' not in text
    assert set(prepare['outputs']) >= {'branch', 'test_status', 'push_repo'}


def test_no_legacy_runner_or_legacy_scripts_are_referenced():
    for path in (UPGRADE, APP):
        text = path.read_text(encoding='utf-8')
        assert 'scripts/harness/run.py' not in text
        assert 'anitya' not in text
        # 字面 runs-on: ubuntu-latest 会被新镜像结构测试拒绝
        assert 'runs-on: ubuntu-latest' not in text
