#!/usr/bin/env python3
"""
CI API 工厂 — 根据仓库 URL 或平台名返回对应 API 模块

支持的平台：
  github   → ci_github_api（默认）
  gitcode  → ci_gitcode_api
"""


def detect_platform(repo: str) -> str:
    """从仓库 URL 或路径推断平台。"""
    if 'gitcode.com' in repo:
        return 'gitcode'
    return 'github'


def normalize_repo(repo: str, platform: str) -> str:
    """将完整 URL 规范化为 'owner/repo' 格式。"""
    repo = repo.rstrip('/')
    if platform == 'gitcode':
        prefix = 'https://gitcode.com/'
        if repo.startswith(prefix):
            repo = repo[len(prefix):]
    elif platform == 'github':
        prefix = 'https://github.com/'
        if repo.startswith(prefix):
            repo = repo[len(prefix):]
    # 只取前两段 owner/repo，去掉多余路径
    parts = repo.split('/')
    return f"{parts[0]}/{parts[1]}"


def get_api(platform: str):
    """返回对应平台的 API 模块（函数签名与 ci_github_api 完全一致）。"""
    if platform == 'gitcode':
        import scripts.lib.ci_gitcode_api as mod
    else:
        import scripts.lib.ci_github_api as mod
    return mod
