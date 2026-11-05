"""场景四编排结构回归：一轮 scan → matrix 扇出，一软件一 PR。

把编排形状钉死在测试里：定时触发、scan 产出候选矩阵、generate 按
matrix 并行（fail-fast 关闭）、单软件超时不拖垮整轮、单软件重试
耗尽写 exhausted 标记而非失败。
"""

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

WORKFLOW = ROOT / '.github' / 'workflows' / 'generate_test_scripts.yml'


def _workflow():
    data = yaml.safe_load(WORKFLOW.read_text(encoding='utf-8'))
    assert isinstance(data, dict)
    return data


def _trigger(data):
    return data.get('on', data.get(True))


def _squash(value) -> str:
    return ' '.join(str(value).split())


def test_scheduled_daily_with_manual_override():
    trigger = _trigger(_workflow())
    assert trigger['schedule'] == [{'cron': '0 2 * * *'}]
    assert 'workflow_dispatch' in trigger
    assert set(trigger['workflow_dispatch']['inputs']) >= {
        'app', 'limit', 'runner_labels',
    }


def test_concurrency_group_prevents_overlapping_rounds():
    workflow = _workflow()
    assert workflow['concurrency']['group'].startswith('testgen-')
    assert workflow['concurrency']['cancel-in-progress'] is False


def test_scan_writes_candidate_output_and_clones_target_repo():
    jobs = _workflow()['jobs']
    scan = jobs['scan']
    assert scan['outputs'] == {'candidates': "${{ steps.scan.outputs.candidates }}"}
    text = _squash(scan['steps'])
    assert 'testgen_scan.py' in text
    assert '--format github-output' in text
    # 去重需要查 open PR，状态标记需要 DISPATCH_TOKEN
    assert 'GITCODE_TOKEN' in text
    assert 'DISPATCH_TOKEN' in text


def test_generate_fans_out_one_job_per_app():
    jobs = _workflow()['jobs']
    generate = jobs['generate']
    assert _squash(generate['if']) == (
        "needs.scan.outputs.candidates != '[]' && "
        "needs.scan.outputs.candidates != ''"
    )
    assert generate['needs'] == 'scan'
    strategy = generate['strategy']
    assert strategy['fail-fast'] is False
    assert strategy['matrix'] == {
        'item': '${{ fromJSON(needs.scan.outputs.candidates) }}'
    }
    assert 'max-parallel' in strategy


def test_generate_runs_the_per_app_stage_with_agent_credentials():
    jobs = _workflow()['jobs']
    generate = jobs['generate']
    text = _squash(generate['steps'])
    assert 'testgen_generate.py --item "$TESTGEN_ITEM"' in text
    assert 'DEEPSEEK_API_KEY' in text
    assert 'GITCODE_FORK_REPO' in text
    # 单软件不阻塞整轮：exhausted 走退出码 0，靠 fail-fast=false 隔离
    assert generate['timeout-minutes'] >= 30


def test_scan_respects_manual_limit_and_single_app_debug():
    jobs = _workflow()['jobs']
    scan = _workflow_text()
    assert "inputs.limit || vars.TESTGEN_MAX_PER_ROUND || '10'" in scan
    assert '--app' in scan


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding='utf-8')


def test_runner_labels_resolve_from_inputs_then_vars():
    text = _workflow_text()
    assert text.count("vars.TESTGEN_RUNNER_LABELS ||\n          '[\"ubuntu-latest\"]'") == 2


def test_target_repo_is_pinned_to_gitcode_images():
    text = _workflow_text()
    assert 'TARGET_REPO: openeuler/openeuler-docker-images' in text
    assert 'TARGET_BRANCH: master' in text
