"""doc_links 单元测试：gitee → gitcode 文档地址改写（只改本次新增行）。"""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.lib.doc_links import (  # noqa: E402
    is_doc_path,
    rewrite_gitee,
    fix_added_lines,
    fix_changed_docs,
)


# ── rewrite_gitee ─────────────────────────────────────────────────────────────

def test_rewrite_basic():
    new, n = rewrite_gitee('see https://gitee.com/openeuler/x')
    assert new == 'see https://gitcode.com/openeuler/x'
    assert n == 1


def test_rewrite_multiple():
    new, n = rewrite_gitee('https://gitee.com/a and http://gitee.com/b')
    assert new == 'https://gitcode.com/a and http://gitcode.com/b'
    assert n == 2


def test_rewrite_subdomain_kept():
    new, n = rewrite_gitee('http://www.gitee.com/a')
    assert new == 'http://www.gitcode.com/a'
    assert n == 1


@pytest.mark.parametrize("text", [
    'mygitee.com',
    'gitee.com.cn',
    'xgitee.com',
])
def test_rewrite_no_false_positive(text):
    new, n = rewrite_gitee(text)
    assert new == text
    assert n == 0


def test_rewrite_already_gitcode_no_change():
    new, n = rewrite_gitee('https://gitcode.com/openeuler/x')
    assert new == 'https://gitcode.com/openeuler/x'
    assert n == 0


# ── is_doc_path ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", [
    'README.md',
    'README',
    'docs/guide.md',
    'a/b/README.rst',
    'notes.mdx',
])
def test_is_doc_true(path):
    assert is_doc_path(path) is True


@pytest.mark.parametrize("path", [
    'Dockerfile',
    'a/b/Dockerfile',
    'meta.yml',
    'image-list.yml',
    'src/main.py',
])
def test_is_doc_false(path):
    assert is_doc_path(path) is False


# ── 基于临时 git 仓库的行为 ───────────────────────────────────────────────────

def _git(repo, *args):
    return subprocess.run(
        ['git', '-C', str(repo), *args],
        check=True, capture_output=True, text=True,
    )


def _git_out(repo, *args) -> str:
    return _git(repo, *args).stdout.strip()


def _init_repo(tmp_path) -> Path:
    repo = tmp_path / 'repo'
    repo.mkdir()
    _git(repo, 'init', '-q')
    _git(repo, 'config', 'user.email', 't@example.com')
    _git(repo, 'config', 'user.name', 'tester')
    _git(repo, 'config', 'commit.gpgsign', 'false')
    return repo


def test_only_added_lines_are_rewritten(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / 'README.md').write_text('old https://gitee.com/keep-me\n', encoding='utf-8')
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-q', '-m', 'base')
    base = _git_out(repo, 'rev-parse', 'HEAD')

    # 仅追加一行含 gitee 的新内容
    with open(repo / 'README.md', 'a', encoding='utf-8') as f:
        f.write('new https://gitee.com/fix-me\n')

    fixed = fix_changed_docs(repo, base)
    assert fixed == ['README.md']
    text = (repo / 'README.md').read_text(encoding='utf-8')
    assert 'https://gitee.com/keep-me' in text          # 存量行保持不动
    assert 'https://gitcode.com/fix-me' in text          # 新增行已改写
    assert 'https://gitee.com/fix-me' not in text


def test_new_doc_file_whole_content_rewritten(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / 'base.txt').write_text('x\n', encoding='utf-8')
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-q', '-m', 'base')
    base = _git_out(repo, 'rev-parse', 'HEAD')

    (repo / 'README.md').write_text(
        'https://gitee.com/one\nhttps://gitee.com/two\n', encoding='utf-8')

    fixed = fix_changed_docs(repo, base)
    assert 'README.md' in fixed
    text = (repo / 'README.md').read_text(encoding='utf-8')
    assert text.count('gitcode.com') == 2
    assert 'gitee.com' not in text


def test_non_doc_files_untouched(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / 'Dockerfile').write_text('FROM scratch\n', encoding='utf-8')
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-q', '-m', 'base')
    base = _git_out(repo, 'rev-parse', 'HEAD')

    (repo / 'Dockerfile').write_text(
        'FROM scratch\n# see https://gitee.com/x\n', encoding='utf-8')

    assert fix_changed_docs(repo, base) == []
    assert 'gitee.com' in (repo / 'Dockerfile').read_text(encoding='utf-8')


def test_no_change_returns_false(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / 'README.md').write_text('https://gitcode.com/ok\n', encoding='utf-8')
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-q', '-m', 'base')
    base = _git_out(repo, 'rev-parse', 'HEAD')

    with open(repo / 'README.md', 'a', encoding='utf-8') as f:
        f.write('nothing to fix here\n')

    assert fix_added_lines(repo, base, 'README.md') is False