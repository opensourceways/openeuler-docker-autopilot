"""
Tests for scripts/watch/process_pr_events.py

覆盖范围：
- _is_prerelease: PR 标题预发布版本检测
- _is_auto_upgrade: 仅监控标题含【自动升级】的 PR
- fix PR skip logic: title starts with 'fix:'
"""

from unittest.mock import MagicMock, patch

import pytest

from scripts.watch.process_pr_events import (
    _is_prerelease,
    _is_auto_upgrade,
    _active_repair_pr_numbers,
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


# ── 在飞修复守卫（_active_repair_pr_numbers）──────────────────────────────────

def _runs_response(runs):
    m = MagicMock()
    m.ok = True
    m.json.return_value = {'workflow_runs': runs}
    return m


class TestActiveRepairPrNumbers:
    def test_collects_only_queued_and_in_progress(self):
        runs = [
            {'status': 'queued', 'name': 'ci-fix PR#5071 · attempt 1 · openeuler/openeuler-docker-images'},
            {'status': 'in_progress', 'name': 'ci-fix PR#5054 · attempt 1 · x'},
            {'status': 'completed', 'name': 'ci-fix PR#3234 · attempt 1 · x'},
            {'status': 'cancelled', 'name': 'ci-fix PR#9999 · attempt 1 · x'},
        ]
        with patch('scripts.watch.process_pr_events.requests.get',
                   return_value=_runs_response(runs)):
            assert _active_repair_pr_numbers('FdeCad/openeuler-docker-autopilot-main', 'tok') == {5071, 5054}

    def test_ignores_runs_without_pr_number(self):
        runs = [{'status': 'queued', 'name': 'Watch CI failed PRs'}]
        with patch('scripts.watch.process_pr_events.requests.get',
                   return_value=_runs_response(runs)):
            assert _active_repair_pr_numbers('r', 'tok') == set()

    def test_http_error_returns_empty(self):
        m = MagicMock()
        m.ok = False
        m.status_code = 403
        with patch('scripts.watch.process_pr_events.requests.get', return_value=m):
            assert _active_repair_pr_numbers('r', 'tok') == set()

    def test_exception_returns_empty(self):
        with patch('scripts.watch.process_pr_events.requests.get',
                   side_effect=Exception('boom')):
            assert _active_repair_pr_numbers('r', 'tok') == set()
