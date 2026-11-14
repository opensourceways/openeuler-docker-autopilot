#!/usr/bin/env python3
"""
入口解析（prepare）：把两种入口统一成一份 PR 元数据。

  repository_dispatch  ← Monitor 轮询发现 ci_failed PR 后触发
  workflow_dispatch    ← 人工指定 source_repo / pr_number 手动触发一次完整修复

两个入口都只提供仓库与 PR 号，PR 标题、head SHA、base 分支一律**现查源仓库**
（单一事实来源，避免把过期字段沿链路传递）。解析结果写进 $GITHUB_OUTPUT，
由 ci_fix_pipeline.yml 的后续 job 读取。

输入（环境变量）:
  SOURCE_REPO / PR_NUMBER / SOURCE_PLATFORM  必备
  FIX_PR_NUMBER                              重试时为 Fix PR 编号，首次为 0
  ATTEMPT                                    本次修复是第几次（用于 run 标题）
  X64/AMD64/ARM64_RUNNER_LABELS              三类 job 的 runner 标签（JSON 数组）
"""

import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

from scripts.lib.ci_api import get_api, normalize_repo
from scripts.lib.stage_common import log_stage


def _resolve_platform(source_platform: str, repo: str) -> str:
    """优先从仓库 URL 识别平台，其次用输入值，最后退回 github。"""
    if 'gitcode.com' in repo:
        return 'gitcode'
    if 'github.com' in repo:
        return 'github'
    return source_platform or 'github'


def resolve() -> dict:
    source_repo = os.getenv('SOURCE_REPO', '')
    pr_number = os.getenv('PR_NUMBER', '')
    if not source_repo or not pr_number:
        raise ValueError('SOURCE_REPO and PR_NUMBER are required')

    platform = _resolve_platform(os.getenv('SOURCE_PLATFORM', ''), source_repo)
    repo = normalize_repo(source_repo, platform)
    token = os.getenv('GITHUB_TOKEN', '')
    if platform == 'gitcode':
        token = os.getenv('GITCODE_TOKEN') or token

    pr = get_api(platform).get_pr_detail(repo, int(pr_number), token)
    if not pr:
        raise RuntimeError(f'PR #{pr_number} not found in {repo}')

    head_sha = (pr.get('head') or {}).get('sha', '')
    if not head_sha:
        # 报错要能自证：把实际拿到的字段名带上，否则下次只能靠猜
        # （`get_pr_detail` 有列表端点兜底，走到这里说明兜底也没捞到）。
        raise RuntimeError(
            f"PR #{pr_number} has no head.sha — 无法继续"
            f"（拿到 keys={list(pr)[:10]}）")

    return {
        'source_repo': repo,
        'source_platform': platform,
        'pr_number': str(pr_number),
        'pr_title': pr.get('title', ''),
        'head_sha': head_sha,
        'fix_branch': f'fix/{pr_number}',
        'pr_base_branch': (pr.get('base') or {}).get('ref', 'main'),
        'fix_pr_number': os.getenv('FIX_PR_NUMBER', '0') or '0',
        'attempt': os.getenv('ATTEMPT', '1') or '1',
    }


def resolve_runner_labels() -> dict:
    """解析三类 job 的 runner 标签（JSON 数组）并挡住写坏的输入。

    prepare 是最早运行的 job，它的 runs-on 只能直接读 inputs/vars（还没有 needs
    上下文），所以这里再解析一次并校验：写坏的值应当得到一句可读的报错，而不是让
    后续 job 在调度阶段报一句难以定位的 invalid expression。
    """
    resolved: dict = {}
    for env_name, output_name in (
        ('X64_RUNNER_LABELS', 'x64_runner_labels'),
        ('AMD64_RUNNER_LABELS', 'amd64_runner_labels'),
        ('ARM64_RUNNER_LABELS', 'arm64_runner_labels'),
    ):
        raw = (os.getenv(env_name) or '').strip()
        if not raw:
            raise RuntimeError(f'{env_name} 为空——runner 标签必须由 workflow 传入')
        try:
            labels = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f'{env_name} 不是合法 JSON 数组（{exc}）：{raw}') from exc
        if not isinstance(labels, list) or not labels or \
                not all(isinstance(x, str) and x.strip() for x in labels):
            raise RuntimeError(f'{env_name} 必须是非空字符串数组：{raw}')
        labels = [x.strip() for x in labels]
        resolved[output_name] = json.dumps(labels)
        log_stage('prepare', f'{output_name} = {labels}')
    return resolved


def emit_outputs(values: dict) -> None:
    """把解析结果写进 $GITHUB_OUTPUT。"""
    gh_output = os.environ.get('GITHUB_OUTPUT', '')
    if not gh_output:
        return
    with open(gh_output, 'a', encoding='utf-8') as f:
        for key, value in values.items():
            f.write(f'{key}={value}\n')


def main():
    values = resolve()
    log_stage(
        'prepare',
        f"repo={values['source_repo']} [{values['source_platform']}] "
        f"pr=#{values['pr_number']} attempt={values['attempt']} "
        f"sha={values['head_sha'][:8]} base={values['pr_base_branch']}",
    )
    values.update(resolve_runner_labels())
    emit_outputs(values)
    log_stage('prepare', '✅ PR metadata resolved')


if __name__ == '__main__':
    main()