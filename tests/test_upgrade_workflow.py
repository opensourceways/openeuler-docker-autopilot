"""场景二（应用自动升级）编排结构回归。"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
UPGRADE = ROOT / '.github' / 'workflows' / 'upgrade_upstream_versions.yml'
APP = ROOT / '.github' / 'workflows' / '_upgrade_app.yml'
AUDIT = ROOT / '.github' / 'workflows' / '_audit_app.yml'
REPAIR = ROOT / '.github' / 'workflows' / 'repair_upgrade.yml'


def _workflow(path: Path):
    data = yaml.safe_load(path.read_text(encoding='utf-8'))
    assert isinstance(data, dict)
    return data


def _trigger(data):
    return data.get('on', data.get(True))


def _squash(value) -> str:
    return ' '.join(str(value).split())


def test_manual_dispatch_only_app_and_version():
    trigger = _trigger(_workflow(UPGRADE))
    assert 'schedule' not in trigger
    inputs = trigger['workflow_dispatch']['inputs']
    assert set(inputs) >= {
        'app', 'version', 'apps_file', 'limit', 'audit_limit', 'runner_labels',
        'x64_runner_labels', 'arm64_runner_labels', 'max_parallel', 'evidence',
    }


def test_discover_uses_manual_versions_and_feeds_the_matrix():
    jobs = _workflow(UPGRADE)['jobs']
    assert list(jobs) == [
        'discover', 'upgrade', 'conda-upgrade', 'create-image', 'plan-repairs',
        'repair', 'audit', 'summary', 'finalize-issue',
    ]

    scan_text = _squash(jobs['discover']['steps'])
    assert 'upgrade_scan.py' in scan_text
    assert '--format github-output' in scan_text
    assert '--apps-file' in scan_text
    assert '--audit-limit' in scan_text
    assert '--evidence' in scan_text
    assert 'gitcode.com' in scan_text
    # 自动升级不再查询看板，版本由清单手动提供
    assert 'UPSTREAM_DASHBOARD_BASE' not in UPGRADE.read_text(encoding='utf-8')
    assert 'upstream_dashboard' not in scan_text

    upgrade = jobs['upgrade']
    assert upgrade['needs'] == 'discover'
    assert upgrade['uses'] == './.github/workflows/_upgrade_app.yml'
    assert upgrade['strategy']['matrix']['item'] == \
        '${{ fromJSON(needs.discover.outputs.updates) }}'
    assert upgrade['with']['item'] == '${{ toJSON(matrix.item) }}'
    # 并发与机器标签可由 dispatch 输入覆盖，默认用到全部 X64 / ARM64
    assert 'inputs.max_parallel' in upgrade['strategy']['max-parallel']
    assert 'inputs.x64_runner_labels' in upgrade['with']['x64_runner_labels']
    assert 'inputs.arm64_runner_labels' in upgrade['with']['arm64_runner_labels']

    audit = jobs['audit']
    assert audit['needs'] == 'discover'
    assert audit['uses'] == './.github/workflows/_audit_app.yml'
    assert audit['strategy']['matrix']['item'] == \
        '${{ fromJSON(needs.discover.outputs.audits) }}'
    assert audit['with']['item'] == '${{ toJSON(matrix.item) }}'
    # 审计链路同样按 config/app-notes 的预算跑修复与双架构校验
    assert audit['with']['build_timeout_minutes'] == \
        "${{ matrix.item.build_timeout_minutes || '180' }}"
    assert audit['with']['prepare_timeout_minutes'] == \
        "${{ matrix.item.prepare_timeout_minutes || '240' }}"


def test_finalize_job_writes_back_only_when_dispatched_from_an_issue():
    data = _workflow(UPGRADE)
    inputs = _trigger(data)['workflow_dispatch']['inputs']
    assert 'source_issue' in inputs
    assert inputs['source_issue']['required'] is False

    job = data['jobs']['finalize-issue']
    finalize_if = _squash(job['if'])
    assert 'always()' in finalize_if
    assert "inputs.source_issue != ''" in finalize_if
    text = _squash(job['steps'])
    assert 'upgrade-issue-finalize' in text
    assert '--issue-number' in text
    assert 'GITCODE_TOKEN' in text
    # 任一本轮 job 失败或取消都回写为 failure，Issue 保持打开
    assert 'failure|cancelled' in text
    # 失败时把各失败 job 的关键日志一并贴进评论
    assert 'collect_failed_logs.py' in text
    assert '--failure-summary' in text


def test_conda_updates_are_registered_through_the_reusable_workflow():
    data = _workflow(UPGRADE)
    discover = data['jobs']['discover']
    assert 'conda_updates' in discover['outputs']
    scan_text = _squash(discover['steps'])
    assert 'conda-ecopkgs' in scan_text
    assert '--conda-repo' in scan_text
    assert '--os-version' in scan_text
    inputs = _trigger(data)['workflow_dispatch']['inputs']
    assert 'os_version' in inputs

    job = data['jobs']['conda-upgrade']
    assert job['needs'] == 'discover'
    assert job['uses'] == './.github/workflows/conda_ecopkgs_pr.yml'
    assert 'conda_updates' in _squash(job['if'])
    assert job['with']['items'] == '${{ needs.discover.outputs.conda_updates }}'
    assert job['with']['runner_arch'] == 'any'

    conda = _workflow(ROOT / '.github' / 'workflows' / 'conda_ecopkgs_pr.yml')
    trigger = _trigger(conda)
    assert 'workflow_call' in trigger
    assert trigger['workflow_call']['inputs']['items']['required'] is True
    assert trigger['workflow_call']['inputs']['runner_arch']['default'] == 'any'


def test_missing_apps_dispatch_create_new_images():
    data = _workflow(UPGRADE)
    discover = data['jobs']['discover']
    assert 'new_images' in discover['outputs']

    job = data['jobs']['create-image']
    assert job['needs'] == 'discover'
    assert 'new_images' in _squash(job['if'])
    assert job['strategy']['matrix']['item'] == \
        '${{ fromJSON(needs.discover.outputs.new_images) }}'
    text = _squash(job['steps'])
    assert 'gh workflow run create_new_images.yml' in text
    assert 'operation=scenario_one' in text
    assert 'permissions' in data
    assert data['permissions']['actions'] == 'write'


def test_arch_neutral_jobs_use_the_shared_oe_any_label():
    upgrade = _workflow(UPGRADE)['jobs']
    for name in ('discover', 'summary', 'finalize-issue', 'plan-repairs'):
        labels = _squash(upgrade[name]['runs-on'])
        assert 'oe-any' in labels, name
        assert 'UPGRADE_NEUTRAL_RUNNER_LABELS' in labels, name
    # create-image 依赖 x64 runner 上的 gh，保持 x64
    assert 'oe-image-x86' in _squash(upgrade['create-image']['runs-on'])

    app = _workflow(APP)
    jobs = app['jobs']
    for name in ('prepare', 'open-pr'):
        assert _squash(jobs[name]['runs-on']) == \
            '${{ fromJSON(inputs.neutral_runner_labels) }}'
    assert _trigger(app)['workflow_call']['inputs']['neutral_runner_labels']['default'] == \
        '["self-hosted","Linux","oe-any"]'
    # 生成阶段的工具链与容器重放跟随 runner 的真实架构
    prepare_text = _squash(jobs['prepare']['steps'])
    assert "runner.arch == 'ARM64'" in prepare_text
    assert 'OE_RUNNER_ARCH' in prepare_text
    # 架构相关 job 不跟着漂移
    assert _squash(jobs['validate-x86_64']['runs-on']) == \
        '${{ fromJSON(inputs.x64_runner_labels) }}'
    assert _squash(jobs['validate-aarch64']['runs-on']) == \
        '${{ fromJSON(inputs.arm64_runner_labels) }}'

    audit = _workflow(AUDIT)['jobs']
    for name in ('fix', 'deliver'):
        assert _squash(audit[name]['runs-on']) == \
            '${{ fromJSON(inputs.runner_labels) }}'
    assert "runner.arch == 'ARM64'" in _squash(audit['fix']['steps'])
    assert _squash(audit['validate-x86_64']['runs-on']) == \
        '${{ fromJSON(inputs.x64_runner_labels) }}'
    assert _squash(audit['validate-aarch64']['runs-on']) == \
        '${{ fromJSON(inputs.arm64_runner_labels) }}'


def test_each_app_runs_prepare_dual_arch_validation_then_pr():
    jobs = _workflow(APP)['jobs']
    assert list(jobs) == [
        'prepare', 'replay-aarch64', 'validate-x86_64', 'validate-aarch64', 'open-pr'
    ]
    assert _squash(jobs['validate-x86_64']['runs-on']) == '${{ fromJSON(inputs.x64_runner_labels) }}'
    assert _squash(jobs['validate-aarch64']['runs-on']) == '${{ fromJSON(inputs.arm64_runner_labels) }}'
    # arm64 的机器只能换机器，不能换架构
    arm64_labels = _trigger(_workflow(APP))['workflow_call']['inputs']['arm64_runner_labels']['default']
    assert 'ARM64' in arm64_labels

    # 生成阶段的容器重放必须在两个架构上都跑：x64 prepare 之后再到 arm64 重放
    replay = jobs['replay-aarch64']
    assert replay['needs'] == 'prepare'
    assert _squash(replay['runs-on']) == '${{ fromJSON(inputs.arm64_runner_labels) }}'
    replay_text = _squash(replay['steps'])
    assert 'upgrade_repair.py' in replay_text
    assert '--mode replay' in replay_text
    assert '--arch aarch64' in replay_text
    # 重放可能推分支，必须完整克隆
    assert '--depth' not in replay_text
    for name in ('validate-x86_64', 'validate-aarch64'):
        assert jobs[name]['needs'] == ['prepare', 'replay-aarch64']

    for name in ('validate-x86_64', 'validate-aarch64'):
        text = _squash(jobs[name]['steps'])
        assert 'phase1-native-validate' in text
        assert 'task-spec' in text
        # 验证失败不开 PR，但证据要保留
        assert 'always()' in _squash(jobs[name])
        # continue-on-error 之后必须有显式断言，否则 open-pr 仍会执行
        assert 'Assert native validation passed' in text
    assert jobs['open-pr']['needs'] == [
        'prepare', 'replay-aarch64', 'validate-x86_64', 'validate-aarch64'
    ]
    assert 'success()' in _squash(jobs['open-pr']['if'])
    assert 'upgrade_open_pr.py' in _squash(jobs['open-pr']['steps'])


def test_prepare_generates_tests_and_applies_the_upgrade():
    prepare = _workflow(APP)['jobs']['prepare']
    text = _squash(prepare['steps'])
    assert 'upgrade_apply.py' in text
    # 克隆统一走带重试的 action，且必须完整克隆：浅克隆推不到 GitCode
    assert './.github/actions/clone-retry' in text
    assert '--depth' not in text
    assert set(prepare['outputs']) >= {'branch', 'test_status', 'push_repo'}


def test_workflow_clones_retry_transient_network_failures():
    for path in (UPGRADE, APP, AUDIT):
        text = path.read_text(encoding='utf-8')
        assert 'git clone' not in text
        assert './.github/actions/clone-retry' in text


def test_no_legacy_runner_or_legacy_scripts_are_referenced():
    for path in (UPGRADE, APP):
        text = path.read_text(encoding='utf-8')
        assert 'scripts/harness/run.py' not in text
        assert 'anitya' not in text
        # 字面 runs-on: ubuntu-latest 会被新镜像结构测试拒绝
        assert 'runs-on: ubuntu-latest' not in text


def test_repair_reuses_the_pipeline_without_regenerating_the_branch():
    data = _workflow(REPAIR)
    inputs = _trigger(data)['workflow_dispatch']['inputs']
    assert set(inputs) >= {'source_run_id', 'app', 'instructions'}

    jobs = data['jobs']
    assert list(jobs) == ['repair']
    repair = jobs['repair']
    assert repair['uses'] == './.github/workflows/_upgrade_app.yml'
    assert repair['with']['repair_run_id'] == '${{ inputs.source_run_id }}'
    assert repair['with']['repair_instructions'] == '${{ inputs.instructions }}'

    prepare = _workflow(APP)['jobs']['prepare']
    text = _squash(prepare['steps'])
    # repair 走已有分支上的修复脚本；首次生成只在非 repair 模式运行
    assert 'upgrade_repair.py' in text
    assert 'upgrade_apply.py' in text
    assert "inputs.repair_run_id == ''" in text
    # 失败运行的 task spec 与双架构 evidence 是 repair 的输入
    assert 'upgrade-task-${{ inputs.app }}-${{ inputs.repair_run_id }}' in text
    assert 'upgrade-evidence-${{ inputs.app }}-x86_64' in text
    assert 'upgrade-evidence-${{ inputs.app }}-aarch64' in text
    assert "'run-id': '${{ inputs.repair_run_id }}'" in text


def test_validation_failure_triggers_one_automatic_repair_round():
    jobs = _workflow(UPGRADE)['jobs']

    plan = jobs['plan-repairs']
    assert plan['needs'] == ['discover', 'upgrade']
    assert 'always()' in _squash(plan['if'])
    assert "needs.upgrade.result == 'failure'" in _squash(plan['if'])
    assert set(plan['outputs']) >= {'count', 'matrix'}
    assert 'upgrade_plan_repairs.py' in _squash(plan['steps'])
    # 读 jobs API 需要 actions 权限；create-image 还需要 write 才能派发场景一
    assert 'actions: write' in UPGRADE.read_text(encoding='utf-8')

    repair = jobs['repair']
    assert repair['needs'] == ['upgrade', 'plan-repairs']
    assert repair['uses'] == './.github/workflows/_upgrade_app.yml'
    assert 'always()' in _squash(repair['if'])
    # 修复复用失败运行的分支与 evidence，不再生成新分支
    assert repair['with']['repair_run_id'] == '${{ github.run_id }}'
    assert repair['with']['repair_instructions'] == '${{ matrix.instructions }}'
    # 只修一轮：plan-repairs 不依赖 repair，修复失败不会再次触发
    assert 'repair' not in plan['needs']


def test_audit_app_validates_both_arches_before_the_fix_pr():
    data = _workflow(AUDIT)
    jobs = data['jobs']
    assert list(jobs) == ['fix', 'validate-x86_64', 'validate-aarch64', 'deliver']

    fix_text = _squash(jobs['fix']['steps'])
    assert 'upgrade_audit.py' in fix_text
    assert '--prepare' in fix_text
    # PR 走 deliver，fix 阶段只推分支
    assert '--deliver' not in fix_text
    # 修复要推分支，必须完整克隆
    assert '--depth' not in fix_text
    assert 'upload-artifact' in fix_text
    assert set(jobs['fix']['outputs']) >= {'has_changes', 'branch', 'push_repo'}
    # 长构建应用的预算来自 config/app-notes，经矩阵从上游 workflow 传入
    assert jobs['fix']['timeout-minutes'] == \
        '${{ fromJSON(inputs.prepare_timeout_minutes) }}'

    for name in ('validate-x86_64', 'validate-aarch64'):
        assert jobs[name]['needs'] == 'fix'
        assert jobs[name]['timeout-minutes'] == \
            '${{ fromJSON(inputs.build_timeout_minutes) }}'
        # 只要审计改动了 Dockerfile / image-info / 补了 test.sh，就必须跑双架构校验
        assert "needs.fix.outputs.has_changes == 'true'" in _squash(jobs[name]['if'])
        text = _squash(jobs[name]['steps'])
        assert 'phase1-native-validate' in text
        assert 'task-spec' in text
        # 校验步骤是 continue-on-error，必须有显式断言让 job 失败
        assert 'Assert native validation passed' in text
        assert 'always()' in _squash(jobs[name])
    arm64_labels = _trigger(data)['workflow_call']['inputs']['arm64_runner_labels']['default']
    assert 'ARM64' in arm64_labels

    deliver = jobs['deliver']
    # 两个架构都成功、且确实有改动，才允许开 PR
    assert deliver['needs'] == ['fix', 'validate-x86_64', 'validate-aarch64']
    deliver_if = _squash(deliver['if'])
    assert 'success()' in deliver_if
    assert "needs.fix.outputs.has_changes == 'true'" in deliver_if
    assert '--open-pr' in _squash(deliver['steps'])
    assert '--delivery' in _squash(deliver['steps'])
