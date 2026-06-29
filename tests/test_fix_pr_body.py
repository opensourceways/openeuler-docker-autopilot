"""
Tests for scripts/lib/fix_pr_body.py

覆盖范围：
- extract_section: 从 markdown 中提取指定标题下的内容
- extract_field: 从文本中提取 "字段: 值" 格式的值
- build: fix PR 标题格式（软件名+版本提取）和正文结构
"""

import pytest
from unittest.mock import patch

from scripts.lib.fix_pr_body import extract_section, extract_field, build

# ── extract_section ───────────────────────────────────────────────────────────

SAMPLE_MD = """\
## 根因分析

### 直接错误
make: No rule to make target

### 根因定位
- 失败位置: Dockerfile:15
- 失败原因: git submodule 未初始化

## 修复方向

### 方向 1
使用 git clone --recurse-submodules 替换 tarball 下载
"""


class TestExtractSection:
    def test_extracts_existing_section(self):
        result = extract_section(SAMPLE_MD, '根因定位')
        assert '失败位置' in result
        assert 'git submodule' in result

    def test_stops_at_next_heading(self):
        result = extract_section(SAMPLE_MD, '直接错误')
        assert 'make: No rule' in result
        assert '根因定位' not in result

    def test_returns_empty_for_missing_section(self):
        assert extract_section(SAMPLE_MD, '不存在的标题') == ''

    def test_heading_level_agnostic(self):
        # 不论是 ## 还是 ### 都能匹配
        result = extract_section(SAMPLE_MD, '方向 1')
        assert 'git clone' in result

    def test_empty_text(self):
        assert extract_section('', '任意标题') == ''


# ── extract_field ─────────────────────────────────────────────────────────────

SAMPLE_REPORT = """\
## 基本信息
- PR: #2534 — 【自动升级】etcd
- 失败类型: build-error
- 置信度: 高
- **知识库匹配**: 新模式
"""


class TestExtractField:
    def test_extracts_simple_field(self):
        assert extract_field(SAMPLE_REPORT, '失败类型') == 'build-error'

    def test_strips_leading_asterisks(self):
        # 字段值前有 ** 加粗标记时应剥除
        result = extract_field(SAMPLE_REPORT, '知识库匹配')
        assert result == '新模式'

    def test_returns_empty_for_missing_field(self):
        assert extract_field(SAMPLE_REPORT, '不存在字段') == ''

    def test_empty_text(self):
        assert extract_field('', '失败类型') == ''


# ── build: 标题生成 ────────────────────────────────────────────────────────────

def _mock_read_file(path):
    """返回最小化的分析报告和修复摘要内容。"""
    if 'ci-analysis' in path:
        return "## 基本信息\n- 失败类型: build-error\n### 根因定位\nmake 失败\n"
    if 'fix-summary' in path:
        return "### 修复逻辑\n改用 git clone\n### 修改的文件\nDockerfile\n"
    return ''


@pytest.fixture(autouse=True)
def mock_ci_data(monkeypatch):
    monkeypatch.setattr('scripts.lib.fix_pr_body.ci_data.read_file', _mock_read_file)
    monkeypatch.setattr('scripts.lib.fix_pr_body.ci_data.analysis_path',
                        lambda n: f'ci-analysis/{n}')
    monkeypatch.setattr('scripts.lib.fix_pr_body.ci_data.fix_summary_path',
                        lambda n: f'fix-summary/{n}')


class TestBuildTitle:
    def test_standard_auto_upgrade_title(self):
        result = build(2534, '【自动升级】etcd容器镜像升级至3.6.11版本.')
        assert result['title'] == 'fix: etcd 3.6.11 (fix #2534)'

    def test_without_rong_qi_jing_xiang(self):
        result = build(100, '【自动升级】openssl升级至3.1.0版本.')
        assert result['title'] == 'fix: openssl 3.1.0 (fix #100)'

    def test_prerelease_version_title_still_generates(self):
        # fix PR 本身不做过滤（过滤在上游 process_pr_events），标题仍应正常提取
        result = build(2534, '【自动升级】etcd容器镜像升级至3.8.0-alpha.0版本.')
        assert result['title'] == 'fix: etcd 3.8.0-alpha.0 (fix #2534)'

    def test_beta_version_title(self):
        result = build(200, '【自动升级】kafka升级至3.5.0-beta.1版本.')
        assert result['title'] == 'fix: kafka 3.5.0-beta.1 (fix #200)'

    def test_fallback_title_for_non_matching_format(self):
        result = build(999, 'fix some unrelated issue')
        assert result['title'] == 'fix: fix some unrelated issue (fix #999)'

    def test_title_includes_pr_number(self):
        result = build(1234, '【自动升级】nginx容器镜像升级至1.25.3版本.')
        assert '1234' in result['title']

    def test_version_not_trailing_chinese(self):
        # 版本号不应包含"版本"两个中文字
        result = build(1, '【自动升级】nginx容器镜像升级至1.25.3版本.')
        assert '版本' not in result['title']


class TestBuildBody:
    def test_body_contains_pr_number(self):
        result = build(2534, '【自动升级】etcd容器镜像升级至3.6.11版本.')
        assert '## Fix for #2534' in result['body']

    def test_body_contains_original_pr_reference(self):
        result = build(2534, '【自动升级】etcd容器镜像升级至3.6.11版本.')
        assert 'Original PR: #2534' in result['body']

    def test_body_contains_root_cause_from_analysis(self):
        result = build(2534, '【自动升级】etcd容器镜像升级至3.6.11版本.')
        assert 'make 失败' in result['body']

    def test_body_contains_fix_desc_from_summary(self):
        result = build(2534, '【自动升级】etcd容器镜像升级至3.6.11版本.')
        assert 'git clone' in result['body']

    def test_body_contains_fail_type(self):
        result = build(2534, '【自动升级】etcd容器镜像升级至3.6.11版本.')
        assert 'build-error' in result['body']

    def test_body_fallback_when_no_ci_data(self, monkeypatch):
        monkeypatch.setattr('scripts.lib.fix_pr_body.ci_data.read_file', lambda _: '')
        result = build(1, 'some title')
        assert '(see CI analysis)' in result['body']
        assert '(see fix summary)' in result['body']
        assert '(see commit diff)' in result['body']
