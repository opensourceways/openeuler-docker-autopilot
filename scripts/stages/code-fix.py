#!/usr/bin/env python3
"""
Stage 2: 代码修复

输入: CI 分析报告 + 源代码仓库（已 checkout 到 fix 分支）
输出: 源代码修改（git commit）+ 修复摘要文件
副作用: 评论 PR
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

from scripts.lib.ai_runner import run_agent
from scripts.lib.stage_common import agent_prompt_file, log_stage, get_conventions_file
from scripts.lib.ci_api import get_api
from scripts.lib import ci_data

WORK_BASE = os.path.join(PROJECT_ROOT, 'ci-fix-log')
SOURCE_REPO_DIR = os.path.join(PROJECT_ROOT, 'source-repo')


def parse_env() -> dict:
    source_repo = os.getenv('SOURCE_REPO', '')
    pr_number = int(os.getenv('PR_NUMBER', '0'))
    if not source_repo or not pr_number:
        raise ValueError('SOURCE_REPO and PR_NUMBER are required')
    owner, repo = source_repo.split('/', 1)
    platform = os.getenv('SOURCE_PLATFORM', 'github')
    token = os.getenv('GITHUB_TOKEN', '')
    if platform == 'gitcode':
        token = os.getenv('GITCODE_TOKEN') or token
    return {
        'source_repo': source_repo,
        'source_platform': platform,
        'owner': owner,
        'repo': repo,
        'pr_number': pr_number,
        'pr_title': os.getenv('PR_TITLE', ''),
        'pr_head_sha': os.getenv('PR_HEAD_SHA', ''),
        'fix_branch': os.getenv('FIX_BRANCH', f'fix/{pr_number}'),
        'pr_base_branch': os.getenv('PR_BASE_BRANCH', 'main'),
        'analysis': os.getenv('ANALYSIS', ''),
        'token': token,
    }


def git(args: list, cwd: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(['git'] + args, cwd=cwd, check=check,
                          capture_output=True, text=True)


def has_changes(cwd: str) -> bool:
    result = git(['diff', '--cached', '--quiet'], cwd=cwd, check=False)
    return result.returncode != 0


def get_pr_file_list(cwd: str, pr_head_sha: str, base_branch: str) -> list:
    """返回原始 PR diff 中涉及的文件列表。"""
    result = git(
        ['diff', '--name-only', f'origin/{base_branch}...{pr_head_sha}'],
        cwd=cwd, check=False
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []
    return [f.strip() for f in result.stdout.strip().splitlines() if f.strip()]


AI_ARTIFACT_DIRS = {'.claude', '.opencode', '__pycache__', '.aider', '.agents'}
AI_ARTIFACT_SUFFIXES = {'.pyc', '.pyo'}


def _is_ai_artifact(filepath: str) -> bool:
    """判断文件路径是否属于 AI 工具产物，应禁止提交。"""
    parts = Path(filepath).parts
    return any(part in AI_ARTIFACT_DIRS for part in parts) or \
           any(filepath.endswith(s) for s in AI_ARTIFACT_SUFFIXES)


def _cleanup_ai_artifacts(repo_dir: str):
    root = Path(repo_dir)
    for name in AI_ARTIFACT_DIRS:
        for p in root.rglob(name):
            if p.is_dir():
                shutil.rmtree(p)
                log_stage('code-fix', f'removed dir: {p.relative_to(root)}')
            elif p.is_file():
                p.unlink()
                log_stage('code-fix', f'removed file: {p.relative_to(root)}')
    for suffix in AI_ARTIFACT_SUFFIXES:
        for p in root.rglob(f'*{suffix}'):
            p.unlink()
            log_stage('code-fix', f'removed file: {p.relative_to(root)}')


def main():
    env = parse_env()
    work_dir = os.path.join(WORK_BASE, str(env['pr_number']))
    Path(work_dir).mkdir(parents=True, exist_ok=True)
    # 摘要文件写在 work_dir（源码库之外），不会被 git commit 进去
    output_file = os.path.join(work_dir, 'code-fix-summary.md')

    log_stage('code-fix', f"repo={env['source_repo']} [{env['source_platform']}] pr=#{env['pr_number']}")

    # 从 ci-data 分支读取完整分析报告（优先），fallback 到 env var
    analysis = ''
    try:
        analysis = ci_data.read_file(ci_data.analysis_path(env['pr_number']))
        if analysis:
            log_stage('code-fix', f'analysis loaded from ci-data ({len(analysis)} chars)')
    except Exception as e:
        log_stage('code-fix', f'⚠️ ci-data read failed: {e}')

    if not analysis:
        analysis = env['analysis']
        log_stage('code-fix', f'analysis fallback to env var ({len(analysis)} chars)')

    if not analysis:
        raise RuntimeError('analysis is empty — ci-log-analysis must run first')

    if not os.path.isdir(SOURCE_REPO_DIR):
        raise RuntimeError(f'source-repo directory not found: {SOURCE_REPO_DIR}')

    pr_files = get_pr_file_list(SOURCE_REPO_DIR, env['pr_head_sha'], env['pr_base_branch'])
    log_stage('code-fix', f'PR touched {len(pr_files)} file(s) [git diff]: {pr_files}')

    # git diff 返回空时，从平台 API 获取文件列表（SHA 未拉取到本地时的 fallback）
    if not pr_files:
        log_stage('code-fix', '⚠️ git diff empty — trying platform API for file list...')
        try:
            api = get_api(env['source_platform'])
            pr_files = api.get_pr_file_names(env['source_repo'], env['pr_number'], env['token'])
            log_stage('code-fix', f'PR touched {len(pr_files)} file(s) [API]: {pr_files}')
        except Exception as e:
            log_stage('code-fix', f'⚠️ API file list fallback failed: {e}')

    context = {
        'pr': {
            'number': env['pr_number'],
            'title': env['pr_title'],
            'changed_files': pr_files,
        },
        'ci_analysis': analysis,
        'fix_branch': env['fix_branch'],
    }

    # AI Agent 在源码仓库目录中运行，直接读写源文件
    run_agent(
        prompt_file=agent_prompt_file('code-fixer'),
        context=context,
        instruction=(
            '根据 CI 失败分析报告，对源代码进行最小化修复。'
            f'只允许修改以下文件（原始 PR 涉及的文件）：{pr_files}。'
            '修复完成后，将修复摘要写入 output_file（不要写入源码仓库内部）。'
        ),
        work_dir=SOURCE_REPO_DIR,
        output_file=output_file,
        label='code-fix',
        conventions_file=get_conventions_file(),
    )

    # 清理 AI 工具产生的文件，不应提交到源码仓库
    _cleanup_ai_artifacts(SOURCE_REPO_DIR)

    # 只暂存原始 PR 涉及的文件，严禁暂存任何其他文件
    if not pr_files:
        # API fallback 也为空——无法确定安全文件列表，以 no_changes 退出
        log_stage('code-fix', 'ℹ️ PR file list empty after all fallbacks — treating as no-change')
        summary = ''
        if os.path.exists(output_file):
            try:
                with open(output_file, 'r', encoding='utf-8') as _f:
                    summary = _f.read().strip()
            except Exception:
                pass
        try:
            ci_data.write_file(
                ci_data.fix_summary_path(env['pr_number']),
                summary or '(no changes: PR file list was empty)',
                f"code-fix: {env['source_repo']} PR #{env['pr_number']} (no changes, empty file list)",
            )
        except Exception as e:
            log_stage('code-fix', f'⚠️ ci-data write failed (non-fatal): {e}')
        gh_output = os.environ.get('GITHUB_OUTPUT', '')
        if gh_output:
            with open(gh_output, 'a') as _f:
                _f.write('no_changes=true\n')
        log_stage('code-fix', '✅ done (no commit, empty file list)')
        return

    log_stage('code-fix', 'staging PR files only...')
    pr_files_set = set(pr_files)
    for f in pr_files:
        git(['add', '--', f], cwd=SOURCE_REPO_DIR, check=False)

    # 兜底校验：暂存区里绝对不能有 pr_files 以外的文件
    staged_result = git(['diff', '--cached', '--name-only'], cwd=SOURCE_REPO_DIR)
    staged_files = [f for f in staged_result.stdout.strip().splitlines() if f.strip()]
    extra = [f for f in staged_files if f not in pr_files_set]
    if extra:
        log_stage('code-fix', f'⚠️ unstaging {len(extra)} unexpected file(s): {extra}')
        for f in extra:
            git(['restore', '--staged', '--', f], cwd=SOURCE_REPO_DIR, check=False)

    with open(output_file, 'r', encoding='utf-8') as f:
        summary = f.read().strip()

    if not has_changes(SOURCE_REPO_DIR):
        # AI 判断无需代码修改（如 infra-error），正常结束，评论原始 PR 说明原因
        log_stage('code-fix', 'ℹ️ no code changes — AI determined fix not needed')
        try:
            ci_data.write_file(
                ci_data.fix_summary_path(env['pr_number']),
                summary,
                f"code-fix: {env['source_repo']} PR #{env['pr_number']} (no changes)",
            )
        except Exception as e:
            log_stage('code-fix', f'⚠️ ci-data write failed (non-fatal): {e}')
        # 通知 workflow 后续步骤（push / create PR）无需执行
        gh_output = os.environ.get('GITHUB_OUTPUT', '')
        if gh_output:
            with open(gh_output, 'a') as _f:
                _f.write('no_changes=true\n')
        log_stage('code-fix', '✅ done (no commit)')
        return

    first_line = summary.split('\n')[0].lstrip('#').strip()[:72]
    commit_msg = (
        f"fix(ci): {first_line}\n\n"
        f"Automated fix for CI failure in PR #{env['pr_number']}\n\n"
        f"🤖 Generated by ci-fix-team"
    )

    git(['commit', '-m', commit_msg], cwd=SOURCE_REPO_DIR)
    log_stage('code-fix', '✅ committed')

    # 写入修复摘要到 ci-fix-log 分支（知识库更新延迟到 fix PR 通过 CI 后进行）
    try:
        ci_data.write_file(
            ci_data.fix_summary_path(env['pr_number']),
            summary,
            f"code-fix: {env['source_repo']} PR #{env['pr_number']}",
        )
        log_stage('code-fix', '✅ fix summary written to ci-fix-log branch')
    except Exception as e:
        log_stage('code-fix', f'⚠️ ci-data write failed (non-fatal): {e}')

    log_stage('code-fix', '✅ done')


if __name__ == '__main__':
    main()
