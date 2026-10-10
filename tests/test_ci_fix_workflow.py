"""场景二编排结构回归：一次修复 = 一个 run，修复轮次显式可见。

回归的是"链路散成隐式 dispatch"这件事：阶段推进若靠阶段脚本自己往外
repository_dispatch，Actions 列表里就只剩互不相干的一堆 run，"修了几次、
现在第几轮、还剩几轮预算"全靠翻日志猜。这里把编排形状钉死在测试里。
"""

import json
import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.watch.resolve_pr import _resolve_platform, resolve_runner_labels  # noqa: E402

PIPELINE = ROOT / '.github' / 'workflows' / 'ci_fix_pipeline.yml'
ROUND = ROOT / '.github' / 'workflows' / '_ci_fix_round.yml'
MONITOR = ROOT / '.github' / 'workflows' / 'monitor_ci_failed_prs.yml'
SYNC = ROOT / '.github' / 'workflows' / 'sync_ci_poll_interval.yml'
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
    # 机器由调用方通过 inputs 指定（默认仍是本仓的 oe-image-* 自托管 Runner）
    assert jobs['arm64-fix']['runs-on'] == '${{ fromJSON(inputs.arm64_runner_labels) }}'
    assert jobs['amd64-fix']['runs-on'] == '${{ fromJSON(inputs.amd64_runner_labels) }}'
    assert jobs['verify-arm']['runs-on'] == '${{ fromJSON(inputs.arm64_runner_labels) }}'
    # 每一轮的收口是 arm64 上的确定性复验，结果回传给调用方
    assert jobs['verify-arm']['outputs']['verify_passed'] == \
        '${{ steps.verify.outputs.verify_passed }}'
    assert jobs['verify-arm']['env']['MODE'] == 'verify'
    assert _trigger(data)['workflow_call']['outputs']['verify_passed']['value'] == \
        '${{ jobs.verify-arm.outputs.verify_passed }}'
    # 第 2/3 轮不再重跑 arm64 首修
    assert jobs['arm64-fix']['if'] == '${{ inputs.include_arm64_fix }}'
    assert "needs.arm64-fix.result == 'skipped'" in _squash(jobs['amd64-fix']['if'])


ENV_READ = re.compile(r"os\.(?:getenv|environ\.get)\(\s*'([A-Z0-9_]+)'")
# 由 runner / GitHub 运行时注入，无需（也无法）在 workflow 里声明
RUNTIME_PROVIDED = {'GITHUB_OUTPUT', 'GITHUB_REPOSITORY', 'XDG_DATA_HOME', 'HOME',
                    'PATH', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT'}
# claude-code（API Key 模式）不在支持矩阵内：只支持 opencode 与
# claude-code-account（凭证走 CLAUDE_CREDENTIALS_JSON 文件）
UNSUPPORTED_BACKEND = {'ANTHROPIC_API_KEY', 'CLAUDE_CODE_BIN'}

# 每个跑阶段脚本的 job 必须把脚本要读的 env 都声明到位
JOB_SCRIPTS = {
    PIPELINE: {
        'prepare': ('scripts/watch/resolve_pr.py',),
        'ci-log-analysis': ('scripts/stages/ci-log-analysis.py',
                            'scripts/lib/ai_runner.py',
                            'scripts/lib/opencode_run.py'),
        'code-fix': ('scripts/stages/code-fix.py',),
    },
    ROUND: {
        'arm64-fix': ('scripts/stages/build-fix.py',
                      'scripts/lib/ai_runner.py',
                      'scripts/lib/opencode_run.py',
                      'scripts/lib/claude_code_run.py'),
        'amd64-fix': ('scripts/stages/build-fix.py',),
        'verify-arm': ('scripts/stages/build-fix.py',),
    },
}


def test_every_job_declares_the_env_its_scripts_read():
    """脚本读的 env 必须在 workflow 里声明：漏了不会报错，只会静默失效。

    两类漏法都要拦住：可复用 workflow **不继承**调用方 env（终止轮的
    PR_COMMENT_ON_FAILURE 就这么丢过一次），以及重构时把 job env 搬丢。
    """
    for wf_path, jobs in JOB_SCRIPTS.items():
        doc = _workflow(wf_path)
        workflow_env = set(doc.get('env') or {})
        for job_id, scripts in jobs.items():
            job = doc['jobs'][job_id]
            declared = workflow_env | set(job.get('env') or {})
            for step in job.get('steps') or []:
                declared |= set(step.get('env') or {})

            needed = set()
            for rel in scripts:
                needed |= set(ENV_READ.findall(
                    (ROOT / rel).read_text(encoding='utf-8')))

            missing = needed - declared - RUNTIME_PROVIDED - UNSUPPORTED_BACKEND
            assert missing == set(), f'{wf_path.name}/{job_id} 未声明 {sorted(missing)}'


def test_infra_error_skips_rounds_and_retests():
    """analyze 判 infra-error → 评论 /retest 并跳过全部修复轮次。"""
    jobs = _workflow(PIPELINE)['jobs']

    analysis = jobs['ci-log-analysis']
    assert 'skip_repair' in analysis['outputs']
    assert 'steps.analysis.outputs.skip_repair' in _squash(
        analysis['outputs']['skip_repair'])
    # 该 output 的来源步骤必须有 id: analysis
    assert 'analysis' in {s.get('id') for s in analysis['steps'] if isinstance(s, dict)}

    # round-1 由 skip_repair 门控 → 后续轮次随 round-1 跳过而自动跳过
    assert _squash(jobs['round-1']['if']) == \
        "${{ needs.ci-log-analysis.outputs.skip_repair != 'true' }}"

    # 监控侧按 (PR, head_sha) 去重：命中 retest 标记则不再 dispatch
    monitor = (ROOT / 'scripts' / 'watch' / 'process_pr_events.py').read_text(encoding='utf-8')
    assert 'is_retest_notified' in monitor


def test_failure_type_is_parsed_and_normalised():
    from scripts.lib import ci_data
    assert ci_data.failure_type('- 失败类型: infra-error') == 'infra-error'
    assert ci_data.failure_type('- 失败类型：Infra-Error') == 'infra-error'
    assert ci_data.failure_type('失败类型: build-error\n') == 'build-error'
    assert ci_data.failure_type('# CI 失败分析报告\n## 基本信息') == ''


def test_monitor_dispatches_one_repair_attempt_per_run():
    assert 'run-ci-fix' in _trigger(_workflow(PIPELINE))['repository_dispatch']['types']

    monitor = (ROOT / 'scripts' / 'watch' / 'process_pr_events.py').read_text(encoding='utf-8')
    assert "'event_type': 'run-ci-fix'" in monitor
    # attempt 写在载荷里 → 出现在 run 标题上，Monitor 的 6 次重试逐次可辨
    assert "'attempt': attempt" in monitor
    assert 'attempt' in _workflow(PIPELINE)['run-name']
    assert _trigger(_workflow(MONITOR))['schedule']


def test_runner_labels_are_configurable_and_stay_arch_safe():
    """机器可换、架构不许换：arm64 的默认标签必须是 arm64，x64 的必须落在 x86。"""
    doc = _workflow(PIPELINE)
    inputs = _trigger(doc)['workflow_dispatch']['inputs']
    defaults = {name: inputs[name]['default'] for name in (
        'x64_runner_labels', 'amd64_runner_labels', 'arm64_runner_labels',
    )}
    for name, raw in defaults.items():
        labels = json.loads(raw)
        assert labels and all(isinstance(label, str) for label in labels), name

    assert 'ARM64' in defaults['arm64_runner_labels']
    for name in ('x64_runner_labels', 'amd64_runner_labels'):
        assert 'ARM64' not in defaults[name]

    # prepare 自己只能读 inputs/vars（最先运行，没有 needs），解析后交给后续 job
    prepare = doc['jobs']['prepare']
    for out in ('x64_runner_labels', 'amd64_runner_labels', 'arm64_runner_labels'):
        assert out in prepare['outputs']
    assert 'inputs.x64_runner_labels' in _squash(prepare['runs-on'])
    assert 'vars.CI_FIX_X64_RUNNER_LABELS' in _squash(prepare['runs-on'])

    assert _squash(doc['jobs']['ci-log-analysis']['runs-on']) == \
        '${{ fromJSON(needs.prepare.outputs.x64_runner_labels) }}'
    assert _squash(doc['jobs']['code-fix']['runs-on']) == \
        '${{ fromJSON(needs.prepare.outputs.x64_runner_labels) }}'
    for job_id in ROUNDS:
        passed = doc['jobs'][job_id]['with']
        assert passed['arm64_runner_labels'] == \
            '${{ needs.prepare.outputs.arm64_runner_labels }}'
        assert passed['amd64_runner_labels'] == \
            '${{ needs.prepare.outputs.amd64_runner_labels }}'

    # 轮询与 cron 同步共用同一个 Variable；监控手动运行可临时覆盖
    for path, job_id in ((MONITOR, 'monitor'), (SYNC, 'sync')):
        runner = _squash(_workflow(path)['jobs'][job_id]['runs-on'])
        assert 'vars.CI_FIX_X64_RUNNER_LABELS' in runner
        assert 'self-hosted' in runner
    assert 'inputs.runner_labels' in _squash(_workflow(MONITOR)['jobs']['monitor']['runs-on'])


def test_toolchain_cache_falls_back_when_opt_is_not_writable():
    """托管 Runner 上 /opt 不可写：缓存根必须自动降级，否则换机器就白换。"""
    action = (ROOT / '.github' / 'actions' / 'phase1-setup' / 'action.yml'
              ).read_text(encoding='utf-8')

    assert '/opt/oe-image-tools' in action
    assert '${RUNNER_TEMP}/oe-image-tools' in action
    assert '--cache-root "${cache_root}"' in action


def test_runner_label_input_is_validated_before_scheduling(monkeypatch):
    """写坏的标签要在 prepare 里得到可读报错，而不是让后续 job 报 invalid expression。"""
    monkeypatch.setenv('X64_RUNNER_LABELS', '["self-hosted","Linux","X64"]')
    monkeypatch.setenv('AMD64_RUNNER_LABELS', '["ubuntu-latest"]')
    monkeypatch.setenv('ARM64_RUNNER_LABELS', '["ubuntu-24.04-arm"]')

    assert resolve_runner_labels()['arm64_runner_labels'] == '["ubuntu-24.04-arm"]'

    monkeypatch.setenv('AMD64_RUNNER_LABELS', 'ubuntu-latest')  # 忘了写 JSON
    with pytest.raises(RuntimeError, match='AMD64_RUNNER_LABELS'):
        resolve_runner_labels()

    monkeypatch.setenv('AMD64_RUNNER_LABELS', '["ubuntu-latest"]')  # 修好后轮到下一项
    monkeypatch.setenv('ARM64_RUNNER_LABELS', '[]')
    with pytest.raises(RuntimeError, match='ARM64_RUNNER_LABELS'):
        resolve_runner_labels()


def test_platform_detection_prefers_the_repo_url():
    assert _resolve_platform('github', 'https://gitcode.com/openeuler/openeuler-docker-images') == \
        'gitcode'
    assert _resolve_platform('gitcode', 'https://github.com/FdeCad/openeuler-docker-autopilot-main') == \
        'github'
    assert _resolve_platform('gitcode', 'openeuler/openeuler-docker-images') == 'gitcode'