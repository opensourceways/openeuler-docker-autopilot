#!/usr/bin/env python3
"""
文档地址检查（gitee → gitcode）

自动化在提交 PR 前，把「本次 PR 新增/追加的文档行」里的 gitee.com 地址改写为
gitcode.com（目标仓库 openeuler/openeuler-docker-images 托管在 gitcode）。

只改新增行、不动存量行，因此不破坏场景一「README 只能末尾追加」的约束
（见 scripts/harness/gate_diff.py）。各流程在 commit/push 前调用
fix_changed_docs()；也提供 CLI：

    python scripts/lib/doc_links.py --repo <dir> --base <ref>
"""

import argparse
import os
import re
import subprocess

OLD_HOST = 'gitee.com'
NEW_HOST = 'gitcode.com'

# 只命中独立的 gitee.com 主机名：不误伤 mygitee.com / gitee.com.cn。
_GITEE_RE = re.compile(r'(?<![0-9A-Za-z-])gitee\.com(?![0-9A-Za-z.-])', re.IGNORECASE)

# 文档后缀：README*（无后缀也算）以及常见文档扩展名
_DOC_SUFFIXES = ('.md', '.mdx', '.rst')

_HUNK_RE = re.compile(r'^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@')


def is_doc_path(path: str) -> bool:
    """是否为需要检查地址的文档：README* 或 .md/.mdx/.rst。"""
    name = os.path.basename(path)
    if name.lower().startswith('readme'):
        return True
    return name.lower().endswith(_DOC_SUFFIXES)


def rewrite_gitee(text: str) -> tuple:
    """把 text 里的 gitee.com 改写成 gitcode.com，返回 (新文本, 命中次数)。"""
    return _GITEE_RE.subn(NEW_HOST, text)


def _git(repo_dir, *args) -> subprocess.CompletedProcess:
    return subprocess.run(
        ['git', '-C', str(repo_dir), *args],
        capture_output=True, text=True,
    )


def _git_stdout(repo_dir, *args) -> str:
    result = _git(repo_dir, *args)
    return result.stdout if result.returncode == 0 else ''


def _exists_in_base(repo_dir, base_ref: str, rel_path: str) -> bool:
    result = _git(repo_dir, 'cat-file', '-e', f'{base_ref}:{rel_path}')
    return result.returncode == 0


def _changed_files(repo_dir, base_ref: str) -> list:
    """相对 base_ref 改动或新增的文件列表（含未跟踪的新文件）。"""
    tracked = _git_stdout(repo_dir, 'diff', '--name-only', base_ref)
    untracked = _git_stdout(repo_dir, 'ls-files', '--others', '--exclude-standard')
    files = [f for f in tracked.splitlines() if f.strip()]
    files += [f for f in untracked.splitlines() if f.strip()]
    # 去重且保序
    seen = set()
    result = []
    for f in files:
        if f not in seen:
            seen.add(f)
            result.append(f)
    return result


def _added_line_numbers(repo_dir, base_ref: str, rel_path: str):
    """返回新文件中属于「本次新增」的行号集合（1-based）。

    文件在 base 中不存在（新文件）时返回 None，表示全文都是新增。
    """
    if not _exists_in_base(repo_dir, base_ref, rel_path):
        return None
    result = _git(repo_dir, 'diff', '-U0', base_ref, '--', rel_path)
    if result.returncode != 0:
        return set()

    numbers = set()
    new_ln = None
    for line in result.stdout.splitlines():
        match = _HUNK_RE.match(line)
        if match:
            new_ln = int(match.group(1))
            continue
        if new_ln is None:
            continue
        if line.startswith('+'):
            numbers.add(new_ln)
            new_ln += 1
        elif line.startswith(' '):
            new_ln += 1
    return numbers


def fix_added_lines(repo_dir, base_ref: str, rel_path: str) -> bool:
    """只改写该文件「本次新增行」里的 gitee 地址。返回是否有改动。"""
    path = os.path.join(str(repo_dir), rel_path)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except OSError:
        return False

    added = _added_line_numbers(repo_dir, base_ref, rel_path)
    if added is None:
        new_content, count = rewrite_gitee(content)
    else:
        if not added:
            return False
        lines = content.splitlines(keepends=True)
        new_content = content
        count = 0
        for ln in sorted(added):
            idx = ln - 1
            if 0 <= idx < len(lines):
                rewritten, n = rewrite_gitee(lines[idx])
                if n:
                    lines[idx] = rewritten
                    count += n
        if count:
            new_content = ''.join(lines)

    if not count or new_content == content:
        return False
    with open(path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    return True


def fix_changed_docs(repo_dir, base_ref: str) -> list:
    """改写本次改动的文档（新增行）里的 gitee 地址，返回被改动的文件列表。"""
    fixed = []
    for rel_path in _changed_files(repo_dir, base_ref):
        if not is_doc_path(rel_path):
            continue
        if fix_added_lines(repo_dir, base_ref, rel_path):
            fixed.append(rel_path)
    return fixed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description='改写本次新增文档行里的 gitee.com 为 gitcode.com',
    )
    parser.add_argument('--repo', required=True, help='目标仓库工作区目录')
    parser.add_argument('--base', required=True, help='对比基准（ref 或 sha）')
    args = parser.parse_args(argv)

    fixed = fix_changed_docs(args.repo, args.base)
    if fixed:
        for rel_path in fixed:
            print(f'fixed: {rel_path}')
    else:
        print('no gitee links in changed docs')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())