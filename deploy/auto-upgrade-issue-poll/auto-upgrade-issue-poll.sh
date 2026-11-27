#!/usr/bin/env bash
# 从轮询机派发统一 Issue 监控工作流 monitor_auto_upgrade_issues.yml
# （与 oe-issue-poll.sh / runner-disk-guard.sh 共用同一个 token 文件）。
#
# 统一监控负责扫描新标题 【自动升级需求】 的 add / upgrade / upgrade openEuler 三类请求；
# 旧标题 【new-image】 / 【new-version】 / 【oe-upgrade】 仍由各自的旧 monitor 处理。
set -euo pipefail

TOKEN_FILE="${TOKEN_FILE:-/etc/oe-issue-poll/token}"
REPO="${REPO:-opensourceways/openeuler-docker-autopilot}"
WORKFLOW="${WORKFLOW:-monitor_auto_upgrade_issues.yml}"
REF="${REF:-main}"

TOKEN="$(tr -d ' \r\n' < "${TOKEN_FILE}")"
if [ -z "${TOKEN}" ]; then
  echo "token file ${TOKEN_FILE} is empty" >&2
  exit 1
fi

curl -fsS --max-time 30 -X POST \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  "https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches" \
  -d "{\"ref\":\"${REF}\"}"
