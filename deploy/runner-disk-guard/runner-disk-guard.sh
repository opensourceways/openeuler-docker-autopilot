#!/usr/bin/env bash
# 从轮询机派发 Runner Disk Guard 工作流（与 oe-issue-poll.sh 共用同一个 token 文件）。
set -euo pipefail

TOKEN_FILE="${TOKEN_FILE:-/etc/oe-issue-poll/token}"
REPO="${REPO:-opensourceways/openeuler-docker-autopilot}"
WORKFLOW="${WORKFLOW:-runner_disk_guard.yml}"
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
