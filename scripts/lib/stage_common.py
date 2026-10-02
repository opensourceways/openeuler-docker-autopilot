#!/usr/bin/env python3
"""
stage 脚本公共工具
"""

import os
import re
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)


def get_project_root() -> str:
    return PROJECT_ROOT


def agent_prompt_file(name: str) -> str:
    return os.path.join(PROJECT_ROOT, '.github', 'agents', f'{name}.md')


def get_conventions_file() -> Optional[str]:
    conventions_path = os.path.join(PROJECT_ROOT, 'source-conventions.md')
    if os.path.exists(conventions_path):
        return conventions_path
    return None


def ts_now() -> str:
    return datetime.now().isoformat()


def normalize_repo(repo: str) -> str:
    """把各种写法的仓库标识归一为 `owner/repo`。

    兼容 `owner/repo`、`https://gitcode.com/owner/repo(.git)`、`git@gitcode.com:owner/repo.git`。

    **Why:** Variable `GITCODE_FORK_REPO` 实际被填成完整 URL，而所有消费方都按
    `owner/repo` 拼接：`git remote add fork ...@gitcode.com/${FORK_REPO}.git` 会拼出
    `gitcode.com/https://gitcode.com/m0_....git`，`f"{fork_repo.split('/')[0]}:{branch}"`
    会拼出 `https::fix/4723`。与其要求配置方记住格式，不如在消费侧归一。
    """
    s = (repo or '').strip()
    if not s:
        return ''
    s = re.sub(r'^[a-zA-Z][a-zA-Z0-9+.-]*://', '', s)  # 去 scheme
    s = re.sub(r'^[^/@]+@', '', s)                     # 去 user@
    s = s.replace(':', '/')                            # scp 写法 host:owner → host/owner
    s = re.sub(r'\.git$', '', s)
    parts = [p for p in s.split('/') if p]
    return '/'.join(parts[-2:]) if len(parts) >= 2 else s


def log_stage(name: str, msg: str) -> None:
    ts = ts_now()[11:19]
    print(f'[{ts}] stage:{name} {msg}', file=sys.stderr)



