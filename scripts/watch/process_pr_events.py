#!/usr/bin/env python3
"""
PR 监控 — CI 失败自动修复触发器

轮询 watchlist 中的仓库，检测带有 ci_failed label 的 PR，
仅处理标题含【自动升级】标记的 PR（人工提交的 PR 不在自动修复范围；milvus /
pyrosetta / cloudwego 等软件也跳过），根据 fix/<pr-number> PR 的存在状态决定动作：

  fix PR 不存在                    → dispatch ci-log-analysis（首次修复）
  fix PR open + ci_successful      → 通知原始 PR fix 已通过 CI（一次性，加 fix_notified 标记）
  fix PR open + ci_processing      → CI 运行中，跳过
  fix PR open + ci_failed          → 检查 commit 次数，未超限则 dispatch，超限则关闭 fix PR
  fix PR open + 无状态 label        → CI 尚未开始，跳过
  fix PR closed                    → 重新 dispatch
  fix PR merged                    → 已合并，跳过
  infra-error（该 sha 已评论 /retest）→ 跳过，等待 CI 重跑（见 ci-log-analysis）

重试预算按 **run 计数**，不按 Fix PR 计：run 标题里的 `PR#<n>` 是本仓自己写的，
不依赖 Fix PR 是否存在。旧实现只认 Fix PR（`ci_failed` 标签 + 分支 commit 数），
而 Fix PR 要链路最后一步才生成——于是「修不成功 → 没有 Fix PR → 每次都算第一次」
自我循环，护栏形同不存在（实测 #5164 连续两天各烧一次约 15h，两次 run 标题都还
是 attempt 1）。现在同一 PR 的历史 run 数达到 MAX_RETRIES 即停止自动重试：默认只记
日志与 `exhausted` 标记，Variable `PR_COMMENT_ON_FAILURE` 为真时才在源 PR 上留一次
人工提示。要再自动跑一次，用手动触发 ci_fix_pipeline。
"""

import os
import re
import sys
import json
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, Optional

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

from scripts.lib.ci_api import detect_platform, normalize_repo, get_api
from scripts.lib import ci_data

WATCHLIST_FILE = os.path.join(PROJECT_ROOT, 'config', 'watchlist.json')
MAX_RETRIES = 6

# run 列表分页：Monitor 每天一批，一页 100 条只覆盖约两天，而「同一 PR 一共跑过几次」
# 要跨周期成立，所以多翻几页（5 页 = 500 条 run）。
RUN_LIST_PAGES = 5
# 只认 ci_fix_pipeline.yml 的 run-name（`ci-fix PR#<n> · attempt <k> · <repo>`），
# 避免别的 repository_dispatch 工作流标题里恰好带 PR# 也被算进来。
_RUN_PR_RE = re.compile(r'^ci-fix PR#(\d+)')


_PRERELEASE_RE = re.compile(
    r'[-.](?:alpha|beta|rc\d*|preview|dev|snapshot|nightly)(?![a-zA-Z])',
    re.IGNORECASE,
)


def _is_prerelease(title: str) -> bool:
    """判断 PR 标题是否包含预发布版本标记（alpha/beta/rc 等），是则跳过自动修复。"""
    return bool(_PRERELEASE_RE.search(title))


# 仅监控自动升级类 PR：人工 PR（文档/README 改动等）不属于自动修复链路
_AUTO_UPGRADE_MARKER = '【自动升级】'

# 明确跳过的软件：这些应用的自动升级 PR 不触发修复
SKIPPED_APPS = {'milvus', 'pyrosetta', 'cloudwego'}

# 从自动升级标题里取软件名：'【自动升级】milvus容器镜像升级至3.0.2版本.' → 'milvus'
_AUTO_UPGRADE_APP_RE = re.compile(r'【自动升级】\s*(.+?)\s*(?:容器镜像)?升级至')


def _is_auto_upgrade(title: str) -> bool:
    """判断 PR 标题是否为自动升级类（含【自动升级】标记），否则 Monitor 跳过。"""
    return _AUTO_UPGRADE_MARKER in (title or '')


def _skipped_app(title: str) -> str:
    """返回标题所属、且在跳过列表里的软件名；未命中返回空串。"""
    match = _AUTO_UPGRADE_APP_RE.search(title or '')
    if not match:
        return ''
    app = match.group(1).strip().lower()
    return app if app in SKIPPED_APPS else ''


def log(msg: str):
    ts = datetime.now().strftime('%H:%M:%S')
    print(f"[{ts}] {msg}", flush=True)


def dispatch_ci_fix(repo: str, platform: str, pr: Dict, token: str, target_repo: str,
                    attempt: int = 1, fix_pr_number: int = 0) -> bool:
    """触发一次**完整**修复（ci_fix_pipeline.yml 单 run 跑完全链路）。

    载荷只带定位信息：PR 标题 / head SHA / base 分支由 workflow 的 prepare job
    现查源仓库，不在这里搬运。`attempt` 是第几次修复，会写进 run 标题——Monitor
    最多重试 6 次，逐次可辨靠的就是它。
    """
    payload = {
        'event_type': 'run-ci-fix',
        'client_payload': {
            'source_repo': repo,
            'source_platform': platform,
            'pr_number': pr['number'],
            # 重试时传入 fix PR 编号，让 ci-log-analysis 从 fix PR 评论中查找最新 build URL
            'fix_pr_number': fix_pr_number,
            'attempt': attempt,
        }
    }
    url = f"https://api.github.com/repos/{target_repo}/dispatches"
    headers = {'Authorization': f'token {token}', 'Accept': 'application/vnd.github.v3+json'}
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        if resp.status_code == 204:
            log(f"  ✅ Dispatched ci-fix attempt #{attempt} for PR #{pr['number']}")
            return True
        log(f"  ❌ Dispatch failed HTTP {resp.status_code}: {resp.text}")
        return False
    except Exception as e:
        log(f"  ❌ Dispatch error: {e}")
        return False


def _parse_time(ts: str) -> Optional[datetime]:
    """解析 ISO 8601 时间字符串为 UTC datetime，解析失败返回 None。"""
    if not ts:
        return None
    try:
        # 兼容 '2026-06-05T10:00:00+00:00' 和 '2026-06-05T10:00:00Z'
        ts = ts.replace('Z', '+00:00')
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _within_lookback(pr: Dict, cutoff: datetime) -> bool:
    """判断 PR 是否在 lookback 窗口内（以 updated_at 为准）。"""
    updated_at = _parse_time(pr.get('updated_at', ''))
    if updated_at is None:
        return True  # 解析失败时默认处理
    return updated_at >= cutoff


def _ci_fix_run_stats(target_repo: str, token: str) -> Optional[tuple]:
    """本仓 ci-fix run 的统计：({源 PR 号: 历史 run 次数}, {在飞/排队的源 PR 号})。

    次数只看 run 标题里的 `PR#<n>`（ci_fix_pipeline 的 run-name 自己写的），因此
    不依赖 Fix PR 是否存在——**修不成功、从未生成 Fix PR 的 PR 同样会被数到**，
    这正是旧的「按 Fix PR / 分支 commit 计数」漏掉的情形。

    两个用途：
      「在飞/排队」→ fix PR 生成前的整个窗口里 monitor 都会看到「No fix PR」，
      没有这个守卫就会对同一 PR 连发多条 run（实测 #5071 等被连发两次）。
      「历史次数」→ 跨周期预算：跑满 MAX_RETRIES 次仍没成功就停手转人工。

    查询失败返回 None：调用方据此跳过本轮 dispatch。宁可晚一天跑，也不要在查不到
    历史时对同一条 PR 无限重派——那正是这次要修掉的病。
    """
    counts: Dict[int, int] = {}
    active: set = set()
    url = f"https://api.github.com/repos/{target_repo}/actions/runs"
    headers = {'Authorization': f'token {token}',
               'Accept': 'application/vnd.github.v3+json'}
    try:
        for page in range(1, RUN_LIST_PAGES + 1):
            resp = requests.get(url, headers=headers,
                                params={'event': 'repository_dispatch',
                                        'per_page': 100, 'page': page},
                                timeout=30)
            if not resp.ok:
                log(f"  ⚠️ 查询历史修复 run 失败 HTTP {resp.status_code}")
                return None
            runs = resp.json().get('workflow_runs') or []
            for run in runs:
                m = _RUN_PR_RE.search(run.get('name') or '')
                if not m:
                    continue
                pr_number = int(m.group(1))
                counts[pr_number] = counts.get(pr_number, 0) + 1
                if run.get('status') in ('queued', 'in_progress'):
                    active.add(pr_number)
            if len(runs) < 100:
                break
    except Exception as e:
        log(f"  ⚠️ 查询历史修复 run 异常: {e}")
        return None
    return counts, active


def _escalate_to_human(repo: str, api, pr_number: int, runs_done: int,
                       write_token: str, reason: str) -> None:
    """跑满 run 预算仍未成功：停止自动重试，并按策略决定是否回帖源 PR。

    回帖是 outward-facing 动作、且落在别人的仓库上，沿用 build-fix 的约定：只有
    Variable `PR_COMMENT_ON_FAILURE` 为真才回帖，默认只留日志与 `exhausted` 标记。
    标记只用于「已提示过」去重；**停止重试本身靠 run 计数**，不依赖标记是否写得成。
    """
    if ci_data.is_exhausted(pr_number):
        log(f"    → 已跑满 {runs_done} 次自动修复且已提示过人工，跳过 dispatch")
        return
    if os.getenv('PR_COMMENT_ON_FAILURE', '').strip().lower() not in ('1', 'true', 'yes'):
        log(f"    🛑 连续 {runs_done} 次修复未成功，停止自动重试"
            f"（未回帖：PR_COMMENT_ON_FAILURE 未开启；原因：{reason}）。"
            f"证据见 ci-fix-log 分支 ci-fix-log/{pr_number}/")
        return
    message = (
        f"🤖 自动修复已尝试 {runs_done} 次仍未成功（{reason}），停止自动重试。\n\n"
        f"诊断与构建证据保留在 `ci-fix-log` 分支的 `ci-fix-log/{pr_number}/` 下，"
        "以及历次 run 的日志里，请人工处理。"
    )
    try:
        api.add_pr_comment(repo, pr_number, message, write_token)
    except Exception as e:
        log(f"    ⚠️ 人工提示评论失败（本轮仍不 dispatch，下轮重试）: {e}")
        return
    try:
        ci_data.mark_exhausted(pr_number, runs_done, reason)
    except Exception as e:
        log(f"    ⚠️ 写 exhausted 标记失败（非致命，下轮会重复提示一次）: {e}")
    log(f"    🛑 连续 {runs_done} 次修复未成功，已回帖提示人工（原因：{reason}）")



def process_all():
    with open(WATCHLIST_FILE, 'r', encoding='utf-8') as f:
        watchlist = json.load(f)

    settings = watchlist.get('settings', {})
    poll_interval = settings.get('poll_interval_minutes', 5)
    max_events = settings.get('max_events_per_run', 50)
    lookback_minutes = settings.get('lookback_minutes', 0)

    lookback_cutoff = None
    if lookback_minutes > 0:
        lookback_cutoff = datetime.now(timezone.utc) - timedelta(minutes=lookback_minutes)

    watch_token = os.getenv('DISPATCH_TOKEN', '')
    dispatch_token = watch_token
    target_repo = os.getenv('GITHUB_REPOSITORY', 'FdeCad/openeuler-docker-autopilot-main')

    if not watch_token:
        log("❌ DISPATCH_TOKEN not set")
        sys.exit(1)

    log("🔍 Starting PR monitoring cycle")
    log(f"   target_repo:  {target_repo}")
    log(f"   poll_interval: {poll_interval}m  max_events: {max_events}  lookback: {lookback_minutes}m")

    # 本仓 ci-fix run 的两项统计：历史次数（跨周期预算）+ 在飞/排队集合（防连发）
    run_stats = _ci_fix_run_stats(target_repo, dispatch_token)
    if run_stats is None:
        log("⚠️ 无法统计历史修复 run，本轮不 dispatch（避免重复重派）")
        return
    run_counts, active_repairs = run_stats
    log(f"   在飞/排队的修复 PR 数: {len(active_repairs)}；"
        f"历史 run 覆盖 {len(run_counts)} 个源 PR")

    total_dispatched = 0

    for repo_config in watchlist.get('watched_repos', []):
        if not repo_config.get('enabled', True):
            continue

        raw_repo = repo_config['repo']
        platform = detect_platform(raw_repo)
        repo = normalize_repo(raw_repo, platform)
        api = get_api(platform)
        ci_failed_label = (repo_config.get('trigger_labels') or ['ci_failed'])[0]

        # GitCode: 读操作用 GITCODE_TOKEN，写操作（评论/标签）用 GITCODE_TOKEN
        token = watch_token
        write_token = watch_token
        if platform == 'gitcode':
            token = os.getenv('GITCODE_TOKEN') or watch_token
            write_token = os.getenv('GITCODE_TOKEN') or token

        log(f"\n{'='*60}")
        log(f"📦 {repo} [{platform}] label={ci_failed_label}")

        try:
            prs = api.fetch_prs_with_label(repo, ci_failed_label, token)
        except Exception as e:
            log(f"  ❌ Failed to fetch PRs: {e}")
            continue

        log(f"  Found {len(prs)} PR(s) with '{ci_failed_label}' label")

        for pr in prs:
            if total_dispatched >= max_events:
                log(f"\n  ⚠️ max_events_per_run ({max_events}) reached, stopping")
                break

            pr_number = pr['number']
            pr_base = pr['base']['ref']
            fix_branch = f'fix/{pr_number}'

            pr_title = pr.get('title', '')
            log(f"\n  🔎 PR #{pr_number}: {pr_title[:60]}")

            if not _is_auto_upgrade(pr_title):
                log(f"    → Skipping: 标题不含 {_AUTO_UPGRADE_MARKER}（仅监控自动升级 PR）")
                continue

            skipped_app = _skipped_app(pr_title)
            if skipped_app:
                log(f"    → Skipping: 软件 {skipped_app} 在跳过列表（不自动修复）")
                continue

            if _is_prerelease(pr_title):
                log(f"    → Skipping: pre-release version in title (alpha/beta/rc/etc.)")
                continue

            if pr_title.lstrip().lower().startswith('fix:'):
                log(f"    → Skipping: fix PR (title starts with 'fix:'), handles its own CI retries")
                continue

            fix_pr = api.find_any_pr_by_head_branch(repo, fix_branch, token)
            # fallback: branch search may miss fork-originated PRs on some platforms
            if fix_pr is None:
                fix_pr = api.find_open_ci_successful_fix_pr(repo, pr_number, token)

            # 该 PR 已跑过的 ci-fix run 次数（含在飞/排队）：跨周期预算的唯一依据，
            # 也是 run 标题里 attempt 的来源。修不成功→没有 Fix PR 的循环，靠它兜住。
            runs_done = run_counts.get(pr_number, 0)

            if fix_pr is None or fix_pr['state'] == 'closed':
                # lookback 过滤：首次 dispatch 时检查 PR 是否在时间窗口内
                if lookback_cutoff and not _within_lookback(pr, lookback_cutoff):
                    log(f"    → Skipping: updated_at outside lookback window ({lookback_minutes}m)")
                    continue
                # infra-error 已判过：该 sha 已评论 /retest，等 CI 重跑，别重复 dispatch
                head_sha = (pr.get('head') or {}).get('sha', '')
                if head_sha and ci_data.is_retest_notified(pr_number, head_sha):
                    log("    → Skipping: 该 sha 已评论 /retest（infra-error），等待 CI 重跑")
                    continue
                # 已存在该 PR 的 queued/in_progress 修复 run：等它产出 fix PR，别重复 dispatch
                if fix_pr is None and pr_number in active_repairs:
                    log(f"    → Skipping: PR #{pr_number} 已有在飞/排队的修复 run")
                    continue
                # 预算用尽：不再 dispatch，留一次人工提示就收手
                if runs_done >= MAX_RETRIES:
                    _escalate_to_human(repo, api, pr_number, runs_done, write_token,
                                       'Fix PR 已关闭' if fix_pr else '未生成 Fix PR')
                    continue
                if fix_pr and fix_pr['state'] == 'closed':
                    log(f"    → Fix PR #{fix_pr['number']} was closed, "
                        f"re-dispatching (attempt #{runs_done + 1})")
                else:
                    log(f"    → No fix PR, dispatching attempt #{runs_done + 1}")
                if dispatch_ci_fix(repo, platform, pr, dispatch_token, target_repo,
                                   attempt=runs_done + 1):
                    total_dispatched += 1

            elif fix_pr['state'] == 'open':
                fix_labels = [l['name'] for l in fix_pr.get('labels', [])]
                fix_pr_url = fix_pr.get('html_url') or f"https://gitcode.com/{repo}/pull/{fix_pr['number']}"

                if 'ci_successful' in fix_labels:
                    if not ci_data.is_fix_notified(pr_number):
                        log(f"    → Fix PR #{fix_pr['number']} passed CI! Notifying original PR #{pr_number}")
                        try:
                            api.add_pr_comment(
                                repo, pr_number,
                                f"🎉 AI 修复 PR [#{fix_pr['number']}]({fix_pr_url}) 已通过 CI，请 review 并合并。",
                                write_token,
                            )
                            ci_data.mark_fix_notified(pr_number)
                        except Exception as e:
                            log(f"    ⚠️  Notification failed: {e}")
                        else:
                            # 通知成功后将经过 CI 验证的修复模式写入知识库
                            try:
                                analysis = ci_data.read_file(ci_data.analysis_path(pr_number))
                                fix_summary = ci_data.read_file(ci_data.fix_summary_path(pr_number))
                                if analysis and fix_summary:
                                    ci_data.append_pattern(pr_number, repo, analysis, fix_summary)
                                    log(f"    ✅ knowledge base updated with patterns from PR #{pr_number}")
                                else:
                                    log(f"    ⚠️  knowledge base skipped: ci-fix-log data not found for PR #{pr_number}")
                            except Exception as e:
                                log(f"    ⚠️  knowledge base update failed (non-fatal): {e}")
                    else:
                        log(f"    → Fix PR #{fix_pr['number']} CI passed, already notified, skipping")

                elif 'ci_processing' in fix_labels:
                    log(f"    → Fix PR #{fix_pr['number']} CI running (ci_processing), skipping")

                elif ci_failed_label in fix_labels:
                    count = api.get_branch_commit_count(repo, fix_branch, pr_base, token)
                    log(f"    → Fix PR #{fix_pr['number']} ci_failed, commits={count}")
                    if count >= MAX_RETRIES:
                        log(f"    → Max retries ({MAX_RETRIES}) reached, closing fix PR")
                        try:
                            api.close_pull_request(repo, fix_pr['number'], write_token)
                            api.add_pr_comment(
                                repo, fix_pr['number'],
                                f"🤖 AI 已尝试修复 {MAX_RETRIES} 次，仍未通过 CI，自动关闭。请人工处理。",
                                write_token,
                            )
                        except Exception as e:
                            log(f"    ⚠️  Close/comment failed: {e}")
                    elif runs_done >= MAX_RETRIES:
                        # 分支 commit 数还没到 6，但这个 PR 的 run 总数已经到了：
                        # run 计数是更早、更硬的信号，同样转人工而不是再来一轮
                        _escalate_to_human(repo, api, pr_number, runs_done, write_token,
                                           f'Fix PR #{fix_pr["number"]} CI 仍失败')
                    else:
                        log(f"    → Dispatching retry (attempt #{runs_done + 1})")
                        if dispatch_ci_fix(repo, platform, {'number': pr_number},
                                           dispatch_token, target_repo,
                                           attempt=runs_done + 1,
                                           fix_pr_number=fix_pr['number']):
                            total_dispatched += 1

                else:
                    log(f"    → Fix PR #{fix_pr['number']} CI pending (no status label), skipping")

            else:
                log(f"    → Fix PR #{fix_pr['number']} state={fix_pr['state']}, skipping")

    log(f"\n✅ PR monitoring cycle complete. dispatched={total_dispatched}/{max_events}")


if __name__ == '__main__':
    process_all()
