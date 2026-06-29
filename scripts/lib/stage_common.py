#!/usr/bin/env python3
"""
stage 脚本公共工具
"""

import os
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


def log_stage(name: str, msg: str) -> None:
    ts = ts_now()[11:19]
    print(f'[{ts}] stage:{name} {msg}', file=sys.stderr)
