#!/usr/bin/env python3
"""
读取 watchlist.json 中的 poll_interval_minutes，
同步更新 monitor_ci_failed_prs.yml 的 cron 表达式。
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
WATCHLIST = ROOT / 'config' / 'watchlist.json'
WORKFLOW = ROOT / '.github' / 'workflows' / 'monitor_ci_failed_prs.yml'


def interval_to_cron(minutes: int) -> str:
    if minutes <= 0:
        raise ValueError(f"poll_interval_minutes must be > 0, got {minutes}")
    if minutes >= 1440:
        return '0 0 * * *'       # 每天 UTC 0:00（北京时间 8:00）触发一次
    if minutes >= 60:
        return '0 * * * *'       # 整点触发
    return f'*/{minutes} * * * *'


def main():
    with open(WATCHLIST, encoding='utf-8') as f:
        config = json.load(f)

    interval = config.get('settings', {}).get('poll_interval_minutes', 5)
    cron = interval_to_cron(interval)

    content = WORKFLOW.read_text(encoding='utf-8')
    updated = re.sub(r"(cron:\s*')[^']+(')", rf"\g<1>{cron}\g<2>", content)

    if updated == content:
        print(f"✅ cron already up-to-date: '{cron}' (poll_interval_minutes={interval})")
        return

    WORKFLOW.write_text(updated, encoding='utf-8')
    print(f"✅ cron updated to '{cron}' (poll_interval_minutes={interval})")


if __name__ == '__main__':
    main()
