"""场景四编排结构回归：手动指定一个软件 → 解析 → 生成 PR。

把编排形状钉死在测试里：只允许手动触发（看板巡检已下线）、单个 job
串行完成解析与生成、应用名是必填输入、runner 默认走自托管 X64。
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


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding='utf-8')


def test_manual_dispatch_only():
    trigger = _trigger(_workflow())
    assert 'schedule' not in trigger
    dispatch = trigger['workflow_dispatch']['inputs']
    assert dispatch['app']['required'] is True
    assert set(dispatch) >= {'app', 'domain', 'source_url', 'runner_labels'}


def test_single_generate_job_with_app_scoped_concurrency():
    workflow = _workflow()
    assert list(workflow['jobs']) == ['generate']
    assert workflow['concurrency']['group'] == 'testgen-${{ inputs.app }}'
    assert workflow['concurrency']['cancel-in-progress'] is False


def test_generate_clones_target_and_resolves_requested_app():
    steps = _workflow()['jobs']['generate']['steps']
    text = _squash(steps)
    assert 'github.com' not in text
    assert 'gitcode.com/${TARGET_REPO}.git' in text
    assert 'testgen_scan.py' in text
    assert '--app "${{ inputs.app }}"' in text
    assert '--domain' in text
    assert '--format github-output' in text


def test_generate_runs_the_per_app_stage_with_agent_credentials():
    job = _workflow()['jobs']['generate']
    text = _squash(job['steps'])
    assert 'testgen_generate.py --item "$TESTGEN_ITEM"' in text
    assert 'steps.resolve.outputs.item' in text
    assert 'AI_API_KEY' in text
    assert 'GITCODE_FORK_REPO' in text
    assert job['timeout-minutes'] >= 30


def test_scan_respects_manual_inputs():
    text = _workflow_text()
    assert 'inputs.source_url' in text
    assert 'inputs.limit' not in text


def test_runner_labels_resolve_from_inputs_then_vars():
    text = _workflow_text()
    # GitHub 托管 Runner 在本账号不可用（额度），默认走自托管 X64
    assert text.count(
        "vars.TESTGEN_RUNNER_LABELS ||\n"
        '          \'["self-hosted","Linux","X64","oe-image-x86"]\''
    ) == 1


def test_target_repo_is_pinned_to_gitcode_images():
    text = _workflow_text()
    assert 'TARGET_REPO: openeuler/openeuler-docker-images' in text
    assert 'TARGET_BRANCH: master' in text
