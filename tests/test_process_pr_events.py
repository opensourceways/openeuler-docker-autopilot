"""
Tests for scripts/watch/process_pr_events.py

覆盖范围：
- _is_prerelease: PR 标题预发布版本检测
- _is_auto_upgrade: 仅监控标题含【自动升级】的 PR
- _skipped_app: 跳过 milvus / pyrosetta 等指定软件
- fix PR skip logic: title starts with 'fix:'
"""

from unittest.mock import MagicMock, patch

import pytest

from scripts.watch.process_pr_events import (
    _is_prerelease,
    _is_auto_upgrade,
    _skipped_app,
    _ci_fix_run_stats,
    _escalate_to_human,
    MAX_RETRIES,
)


class TestIsPrerelease:

    # ── 应该跳过（预发布版本）─────────────────────────────────────────────────

    @pytest.mark.parametrize("title", [
        '【自动升级】etcd容器镜像升级至3.8.0-alpha.0版本.',
        '【自动升级】etcd容器镜像升级至3.8.0-alpha版本.',
        '【自动升级】kafka升级至3.5.0-beta.1版本.',
        '【自动升级】kafka升级至3.5.0-beta版本.',
        '【自动升级】someapp升级至1.0.0-rc1版本.',
        '【自动升级】someapp升级至2.0.0-rc版本.',
        '【自动升级】nginx升级至1.0.0-preview版本.',
        '【自动升级】tool升级至2.0.0-dev版本.',
        '【自动升级】app升级至1.0-snapshot版本.',
        '【自动升级】app升级至1.0.0-nightly版本.',
        # 大写
        '【自动升级】pkg升级至1.0.0-Alpha.1版本.',
        '【自动升级】pkg升级至1.0.0-BETA版本.',
        '【自动升级】pkg升级至1.0.0-RC2版本.',
        # 点分隔
        '【自动升级】pkg升级至1.0.0.alpha.1版本.',
        '【自动升级】pkg升级至1.0.0.beta版本.',
    ])
    def test_prerelease_titles_are_skipped(self, title):
        assert _is_prerelease(title) is True, f"Expected prerelease: {title}"

    # ── 应该处理（正式版本）──────────────────────────────────────────────────

    @pytest.mark.parametrize("title", [
        '【自动升级】etcd容器镜像升级至3.6.11版本.',
        '【自动升级】nginx容器镜像升级至1.25.3版本.',
        '【自动升级】openssl升级至3.1.0版本.',
        '【自动升级】golang升级至1.23.9版本.',
        '【自动升级】python升级至3.12.0版本.',
        # 较短版本号
        '【自动升级】busybox升级至1.36版本.',
        # 四段版本号
        '【自动升级】somelib升级至1.2.3.4版本.',
    ])
    def test_stable_titles_are_processed(self, title):
        assert _is_prerelease(title) is False, f"Expected stable: {title}"

    # ── 边界：软件名中含预发布关键词时不应误判 ────────────────────────────────

    @pytest.mark.parametrize("title", [
        # 软件名以 dev/preview 开头或包含这些词
        '【自动升级】developer-tool升级至1.0.0版本.',
        '【自动升级】preview-app升级至2.0.0版本.',
        '【自动升级】alphabetical升级至1.0.0版本.',
        '【自动升级】betamax升级至3.0.0版本.',
        # rc 作为普通词缀（非版本标记）
        '【自动升级】rclone升级至1.65.0版本.',
    ])
    def test_software_name_keywords_not_flagged(self, title):
        assert _is_prerelease(title) is False, f"Should not flag as prerelease: {title}"

    # ── 非自动升级 PR 标题 ───────────────────────────────────────────────────

    def test_plain_title_without_version(self):
        assert _is_prerelease('fix some unrelated issue') is False

    def test_empty_title(self):
        assert _is_prerelease('') is False

    def test_title_with_alpha_in_description_not_version(self):
        # alpha 出现在描述中但不是版本标记（没有 -. 前缀）
        assert _is_prerelease('升级 alpha 通道的软件包') is False


# ── 自动升级标题过滤（仅监控含【自动升级】的 PR）──────────────────────────────

class TestIsAutoUpgrade:
    @pytest.mark.parametrize("title", [
        '【自动升级】etcd容器镜像升级至3.6.11版本.',
        '【自动升级】openfoam容器镜像升级至20260907版本.',
        '【自动升级】pkg升级至1.0.0-rc1版本.',  # 预发布与否由此后单独判断
        '【自动升级】[kunpeng-install:source] grpc 1.85.4',
    ])
    def test_auto_upgrade_titles_are_kept(self, title):
        assert _is_auto_upgrade(title) is True, f"Expected auto-upgrade: {title}"

    @pytest.mark.parametrize("title", [
        'docs: add automated new-image request guide',
        'update readme.md',
        '【轻量级 PR】：update: 更新文件 README.md',
        'fix: etcd 3.6.11 (fix #2534)',
        '升级 nginx 容器镜像',
        '',
    ])
    def test_other_titles_are_skipped(self, title):
        assert _is_auto_upgrade(title) is False, f"Should skip: {title}"


# ── 跳过指定软件（milvus / pyrosetta）────────────────────────────────────────

class TestSkippedApp:
    @pytest.mark.parametrize("title,app", [
        ('【自动升级】milvus容器镜像升级至3.0.2版本.', 'milvus'),
        ('【自动升级】pyrosetta容器镜像升级至3.15版本.', 'pyrosetta'),
        ('【自动升级】cloudwego容器镜像升级至0.6.0版本.', 'cloudwego'),
        ('【自动升级】MILVUS容器镜像升级至3.0.2版本.', 'milvus'),  # 大小写不敏感
        ('【自动升级】milvus升级至3.0.2版本.', 'milvus'),  # 无「容器镜像」
        ('【自动升级】[kunpeng-install:binary] milvus 3.0.2', 'milvus'),
        ('【自动升级】[kunpeng-install:source] MILVUS 3.0.2', 'milvus'),
    ])
    def test_skipped_apps_are_detected(self, title, app):
        assert _skipped_app(title) == app

    @pytest.mark.parametrize("title", [
        '【自动升级】openfoam容器镜像升级至20260907版本.',
        '【自动升级】nginx升级至1.0.0版本.',
        '【自动升级】rosetta容器镜像升级至1.0.0版本.',  # 不能因子串误伤
        '【自动升级】[kunpeng-install:source] grpc 1.85.4',
        'docs: update readme',
        '',
    ])
    def test_other_apps_are_not_skipped(self, title):
        assert _skipped_app(title) == ''


# ── fix PR skip（标题以 fix: 开头）────────────────────────────────────────────

def _is_fix_pr_title(title: str) -> bool:
    """复用 process_pr_events.py 中相同的判断逻辑。"""
    return title.lstrip().lower().startswith('fix:')


class TestIsFixPrTitle:
    @pytest.mark.parametrize("title", [
        'fix: etcd 3.6.11 (fix #2534)',
        'fix: libyuv 1948 (fix #2546)',
        'Fix: something capitalized',
        '  fix: leading spaces',
        'FIX: uppercase',
    ])
    def test_fix_titles_are_skipped(self, title):
        assert _is_fix_pr_title(title) is True, f"Expected fix PR: {title}"

    @pytest.mark.parametrize("title", [
        '【自动升级】etcd容器镜像升级至3.6.11版本.',
        'chore: update dependencies',
        'feat: add new feature',
        'fixup some thing',       # 以 fixup 开头，不是 fix:
        'prefix fix: something',  # fix: 不在开头
        '',
    ])
    def test_non_fix_titles_are_not_skipped(self, title):
        assert _is_fix_pr_title(title) is False, f"Should not skip: {title}"


# ── 修复 run 统计（_ci_fix_run_stats：历史次数 + 在飞集合）────────────────────

def _runs_response(runs):
    m = MagicMock()
    m.ok = True
    m.json.return_value = {'workflow_runs': runs}
    return m


class TestCiFixRunStats:
    def test_counts_every_run_and_tracks_only_in_flight(self):
        """次数含已完成（跨周期预算），在飞集合只认 queued/in_progress。"""
        runs = [
            {'status': 'completed', 'name': 'ci-fix PR#5164 · attempt 1 · x'},
            {'status': 'completed', 'name': 'ci-fix PR#5164 · attempt 1 · x'},
            {'status': 'queued', 'name': 'ci-fix PR#5071 · attempt 3 · x'},
            {'status': 'in_progress', 'name': 'ci-fix PR#5054 · attempt 2 · x'},
            {'status': 'cancelled', 'name': 'ci-fix PR#3234 · attempt 1 · x'},
        ]
        with patch('scripts.watch.process_pr_events.requests.get',
                   return_value=_runs_response(runs)):
            counts, active = _ci_fix_run_stats('FdeCad/openeuler-docker-autopilot-main', 'tok')
        assert counts == {5164: 2, 5071: 1, 5054: 1, 3234: 1}
        assert active == {5071, 5054}

    def test_counts_runs_that_never_produced_a_fix_pr(self):
        """这正是旧实现漏掉的：修复不成功 → 没有 Fix PR，但 run 次数照样要数到。"""
        runs = [{'status': 'completed', 'name': 'ci-fix PR#5164 · attempt 1 · x'}
                for _ in range(MAX_RETRIES)]
        with patch('scripts.watch.process_pr_events.requests.get',
                   return_value=_runs_response(runs)):
            counts, _ = _ci_fix_run_stats('r', 'tok')
        assert counts[5164] == MAX_RETRIES

    def test_ignores_runs_without_pr_number(self):
        runs = [{'status': 'queued', 'name': 'Watch CI failed PRs'}]
        with patch('scripts.watch.process_pr_events.requests.get',
                   return_value=_runs_response(runs)):
            counts, active = _ci_fix_run_stats('r', 'tok')
        assert counts == {} and active == set()

    def test_only_counts_runs_named_by_the_ci_fix_pipeline(self):
        """其它工作流的标题里恰好带 PR# 不算数，只认 `ci-fix PR#<n>`。"""
        runs = [
            {'status': 'completed', 'name': 'ci-fix PR#5164 · attempt 1 · x'},
            {'status': 'completed', 'name': 'upgrade PR#5164 · something'},
            {'status': 'completed', 'name': 'new-image PR#5164'},
        ]
        with patch('scripts.watch.process_pr_events.requests.get',
                   return_value=_runs_response(runs)):
            counts, active = _ci_fix_run_stats('r', 'tok')
        assert counts == {5164: 1} and active == set()

    def test_paginates_until_a_short_page(self):
        """一页 100 条 ≈ 两天，跨周期预算必须多翻几页才数得准。"""
        pages = []

        def fake_get(url, headers=None, params=None, timeout=None):
            pages.append(params['page'])
            if params['page'] == 1:
                return _runs_response([
                    {'status': 'completed', 'name': f'ci-fix PR#{9000 + i} · attempt 1 · x'}
                    for i in range(100)
                ])
            return _runs_response([
                {'status': 'completed', 'name': 'ci-fix PR#5164 · attempt 1 · x'},
            ])

        with patch('scripts.watch.process_pr_events.requests.get', side_effect=fake_get):
            counts, _ = _ci_fix_run_stats('r', 'tok')
        assert pages == [1, 2]
        assert counts[5164] == 1

    def test_http_error_returns_none(self):
        """查不到历史就返回 None：调用方据此跳过本轮，绝不因为查不到而无限重派。"""
        m = MagicMock()
        m.ok = False
        m.status_code = 403
        with patch('scripts.watch.process_pr_events.requests.get', return_value=m):
            assert _ci_fix_run_stats('r', 'tok') is None

    def test_exception_returns_none(self):
        with patch('scripts.watch.process_pr_events.requests.get',
                   side_effect=Exception('boom')):
            assert _ci_fix_run_stats('r', 'tok') is None


# ── 跑满预算 → 转人工（_escalate_to_human）────────────────────────────────────

class TestEscalateToHuman:
    def test_comments_once_and_marks_exhausted(self, monkeypatch):
        monkeypatch.setenv('PR_COMMENT_ON_FAILURE', 'true')
        api = MagicMock()
        with patch('scripts.watch.process_pr_events.ci_data') as data:
            data.is_exhausted.return_value = False
            _escalate_to_human('openeuler/openeuler-docker-images', api, 5164,
                               MAX_RETRIES, 'tok', '未生成 Fix PR')
        api.add_pr_comment.assert_called_once()
        repo, pr_number, message, _token = api.add_pr_comment.call_args[0]
        assert pr_number == 5164 and '5164' in message and str(MAX_RETRIES) in message
        data.mark_exhausted.assert_called_once_with(5164, MAX_RETRIES, '未生成 Fix PR')

    def test_does_not_comment_by_default(self, monkeypatch):
        """回帖是 outward-facing 动作，默认关闭：只停手 + 留日志，标记也不写。"""
        monkeypatch.delenv('PR_COMMENT_ON_FAILURE', raising=False)
        api = MagicMock()
        with patch('scripts.watch.process_pr_events.ci_data') as data:
            data.is_exhausted.return_value = False
            _escalate_to_human('r', api, 5164, MAX_RETRIES, 'tok', '未生成 Fix PR')
        api.add_pr_comment.assert_not_called()
        data.mark_exhausted.assert_not_called()

    def test_second_cycle_does_not_comment_again(self, monkeypatch):
        """Monitor 每天轮询一次，标记在就不再重复评论同一条 PR。"""
        monkeypatch.setenv('PR_COMMENT_ON_FAILURE', 'true')
        api = MagicMock()
        with patch('scripts.watch.process_pr_events.ci_data') as data:
            data.is_exhausted.return_value = True
            _escalate_to_human('r', api, 5164, MAX_RETRIES, 'tok', '未生成 Fix PR')
        api.add_pr_comment.assert_not_called()
        data.mark_exhausted.assert_not_called()

    def test_comment_failure_still_blocks_dispatch(self, monkeypatch):
        """评论失败也不 dispatch（下轮会再试评论），且不写标记。"""
        monkeypatch.setenv('PR_COMMENT_ON_FAILURE', 'true')
        api = MagicMock()
        api.add_pr_comment.side_effect = Exception('403')
        with patch('scripts.watch.process_pr_events.ci_data') as data:
            data.is_exhausted.return_value = False
            _escalate_to_human('r', api, 5164, MAX_RETRIES, 'tok', '未生成 Fix PR')
        data.mark_exhausted.assert_not_called()

