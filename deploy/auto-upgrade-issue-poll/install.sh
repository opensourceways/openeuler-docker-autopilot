#!/usr/bin/env bash
# 在轮询机（hwyx86）上安装统一 Issue 监控的 5 分钟定时器。
#
# 用法（root）：
#   ./install.sh
#
# 依赖：与 oe-issue-poll.timer 相同——/etc/oe-issue-poll/token 中已有可用的 GitHub token。
#
# 可用环境变量覆盖：
#   TOKEN_FILE    默认 /etc/oe-issue-poll/token
#   REPO          默认 opensourceways/openeuler-docker-autopilot
#   WORKFLOW      默认 monitor_auto_upgrade_issues.yml
#   REF           默认 main
set -euo pipefail

TOKEN_FILE="${TOKEN_FILE:-/etc/oe-issue-poll/token}"
REPO="${REPO:-opensourceways/openeuler-docker-autopilot}"
WORKFLOW="${WORKFLOW:-monitor_auto_upgrade_issues.yml}"
REF="${REF:-main}"

if [ "$(id -u)" -ne 0 ]; then
  echo "请用 root 运行（sudo $0）" >&2
  exit 1
fi

if [ ! -s "${TOKEN_FILE}" ]; then
  echo "缺少 token 文件：${TOKEN_FILE}" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DISPATCH_SRC="${SCRIPT_DIR}/auto-upgrade-issue-poll.sh"
SERVICE_SRC="${SCRIPT_DIR}/auto-upgrade-issue-poll.service"
TIMER_SRC="${SCRIPT_DIR}/auto-upgrade-issue-poll.timer"
DISPATCH_DST="/usr/local/bin/auto-upgrade-issue-poll.sh"
SERVICE_DST="/etc/systemd/system/auto-upgrade-issue-poll.service"
TIMER_DST="/etc/systemd/system/auto-upgrade-issue-poll.timer"

for file in "${DISPATCH_SRC}" "${SERVICE_SRC}" "${TIMER_SRC}"; do
  if [ ! -f "${file}" ]; then
    echo "缺少文件：${file}" >&2
    exit 1
  fi
done

# 派发脚本里的默认值可由环境变量覆盖；安装时把实际取值固化进去。
sed \
  -e "s|^TOKEN_FILE=.*|TOKEN_FILE=\"${TOKEN_FILE}\"|" \
  -e "s|^REPO=.*|REPO=\"${REPO}\"|" \
  -e "s|^WORKFLOW=.*|WORKFLOW=\"${WORKFLOW}\"|" \
  -e "s|^REF=.*|REF=\"${REF}\"|" \
  "${DISPATCH_SRC}" > "${DISPATCH_DST}"
chmod 0755 "${DISPATCH_DST}"

install -m 0644 "${SERVICE_SRC}" "${SERVICE_DST}"
install -m 0644 "${TIMER_SRC}" "${TIMER_DST}"

systemctl daemon-reload
systemctl enable --now auto-upgrade-issue-poll.timer

echo "已安装："
echo "  ${DISPATCH_DST}"
echo "  ${SERVICE_DST}"
echo "  ${TIMER_DST}"
echo
systemctl list-timers --all auto-upgrade-issue-poll.timer
