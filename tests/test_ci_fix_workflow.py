"""场景二编排结构回归：一次修复 = 一个 run，修复轮次显式可见。

回归的是"链路散成隐式 dispatch"这件事：阶段推进若靠阶段脚本自己往外
repository_dispatch，Actions 列表里就只剩互不相干的一堆 run，"修了几次、
现在第几轮、还剩几轮预算"全靠翻日志猜。这里把编排形状钉死在测试里。
"""

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.watch.resolve_pr import _resolve_platform  # noqa: E402

PIPELINE = ROOT / '.github' / 'workflows' / 'ci_fix_pipeline.yml'
ROUND = ROOT / '.github' / 'workflows' / '_ci_fix_round.yml'
MONITOR = ROOT / '.github' / 'workflows' / 'monitor_ci_failed_prs.yml'
ROUNDS = ('round-1', 'round-2', 'round-3')


def _workflow(path):
    data = yaml.safe_load(path.read_text(encoding='utf-8'))
    assert isinstance(data, dict)
    return data


def _trigger(data):
    return data.get('on', data.get(True))


def _squash(text: str) -> str:
    """折行写法（>-）会把一句话拆成多行，比对前先压平空白。"""
    return ' '.join(text.split())


def _names(value) -> set:
    """`needs:` 写单个 job 时是字符串，写多个时是列表。"""
    return {value} if isinstance(value, str) else set(value)


def test_one_run_covers_the_whole_repair_chain():
    jobs = _workflow(PIPELINE)['jobs']

    assert list(jobs) == [
        'prepare', 'ci-log-analysis', 'round-1', 'round-2', 'round-3', 'code-fix',
    ]
    # 链路内部不再有第二处 dispatch：阶段推进全部走 job 依赖
    body = PIPELINE.read_text(encoding='utf-8').split('jobs:')[1]
    assert 'repository_dispatch' not in body
    assert 'dispatches' not in body


def test_entry_resolves_pr_metadata_before_analysis():
    jobs = _workflow(PIPELINE)['jobs']
    prepare = jobs['prepare']

    assert 'resolve_pr.py' in _squash(str(prepare['steps']))
    assert _names(jobs['ci-log-analysis']['needs']) == {'prepare'}
    # PR 标题 / head SHA / base 分支由 prepare 现查，不由入口载荷搬运
    assert set(prepare['outputs']) >= {
        'source_repo', 'source_platform', 'pr_number', 'pr_title',
        'head_sha', 'fix_branch', 'pr_base_branch', 'fix_pr_number', 'attempt',
    }


def test_repair_rounds_are_visible_and_gated_on_the_previous_verify():
    jobs = _workflow(PIPELINE)['jobs']

    for number, job_id in enumerate(ROUNDS, start=1):
        assert jobs[job_id]['name'] == f'Round {number}: fix and verify'
        assert jobs[job_id]['uses'] == './.github/workflows/_ci_fix_round.yml'

    assert "needs.round-1.outputs.verify_passed == 'false'" in \
        _squash(jobs['round-2']['if'])
    assert "needs.round-2.outputs.verify_passed == 'false'" in \
        _squash(jobs['round-3']['if'])


def test_round_one_fixes_arm64_first_and_later_rounds_only_refix_amd64():
    jobs = _workflow(PIPELINE)['jobs']

    assert jobs['round-1']['with']['include_arm64_fix'] is True
    assert jobs['round-2']['with']['include_arm64_fix'] is False
    assert jobs['round-3']['with']['include_arm64_fix'] is False
    assert [jobs[r]['with']['verify_count'] for r in ROUNDS] == ['0', '1', '2']


def test_code_fix_runs_only_after_a_passing_verify():
    job = _workflow(PIPELINE)['jobs']['code-fix']
    condition = _squash(job['if'])

    for job_id in ROUNDS:
        assert f"needs.{job_id}.outputs.verify_passed == 'true'" in condition


def test_round_component_fixes_both_arches_and_reports_the_round_result():
    data = _workflow(ROUND)
    jobs = data['jobs']

    assert list(jobs) == ['arm64-fix', 'amd64-fix', 'verify-arm']
    assert jobs['arm64-fix']['runs-on'] == ['self-hosted', 'Linux', 'ARM64', 'oe-image-arm64']
    assert jobs['amd64-fix']['runs-on'] == ['self-hosted', 'Linux', 'X64', 'oe-image-x86']
    assert jobs['verify-arm']['runs-on'] == ['self-hosted', 'Linux', 'ARM64', 'oe-image-arm64']
    # 每一轮的收口是 arm64 上的确定性复验，结果回传给调用方
    assert jobs['verify-arm']['outputs']['verify_passed'] == \
        '${{ steps.verify.outputs.verify_passed }}'
    assert jobs['verify-arm']['env']['MODE'] == 'verify'
    assert _trigger(data)['workflow_call']['outputs']['verify_passed']['value'] == \
        '${{ jobs.verify-arm.outputs.verify_passed }}'
    # 第 2/3 轮不再重跑 arm64 首修
    assert jobs['arm64-fix']['if'] == '${{ inputs.include_arm64_fix }}'
    assert "needs.arm64-fix.result == 'skipped'" in _squash(jobs['amd64-fix']['if'])


def test_monitor_dispatches_one_repair_attempt_per_run():
    assert 'run-ci-fix' in _trigger(_workflow(PIPELINE))['repository_dispatch']['types']

    monitor = (ROOT / 'scripts' / 'watch' / 'process_pr_events.py').read_text(encoding='utf-8')
    assert "'event_type': 'run-ci-fix'" in monitor
    # attempt 写在载荷里 → 出现在 run 标题上，Monitor 的 6 次重试逐次可辨
    assert "'attempt': attempt" in monitor
    assert 'attempt' in _workflow(PIPELINE)['run-name']
    assert _trigger(_workflow(MONITOR))['schedule']


def test_platform_detection_prefers_the_repo_url():
    assert _resolve_platform('github', 'https://gitcode.com/openeuler/openeuler-docker-images') == \
        'gitcode'
    assert _resolve_platform('gitcode', 'https://github.com/FdeCad/openeuler-docker-autopilot-main') == \
        'github'
    assert _resolve_platform('gitcode', 'openeuler/openeuler-docker-images') == 'gitcode'