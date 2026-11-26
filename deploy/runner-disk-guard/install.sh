#!/usr/bin/env bash
# 在轮询机（hwyx86）上安装 Runner Disk Guard 定时器。
#
# 用法（root）：
#   REPO=opensourceways/openeuler-docker-autopilot ./install.sh
#
# 可用环境变量覆盖：
#   REPO          默认 opensourceways/openeuler-docker-autopilot
#   WORKFLOW      默认 runner_disk_guard.yml
#   REF           默认 main
#   RUNNER_USER   运行 gh 的账号，默认 $SUDO_USER 或当前用户
#   GH_BIN        gh 路径，默认自动探测
set -euo pipefail

REPO="${REPO:-opensourceways/openeuler-docker-autopilot}"
WORKFLOW="${WORKFLOW:-runner_disk_guard.yml}"
REF="${REF:-main}"
RUNNER_USER="${RUNNER_USER:-${SUDO_USER:-$(id -un)}}"

if [ "$(id -u)" -ne 0 ]; then
  echo "请用 root 运行（sudo $0）" >&2
  exit 1
fi

RUNNER_HOME="$(getent passwd "${RUNNER_USER}" | cut -d: -f6)"
if [ -z "${RUNNER_HOME}" ]; then
  echo "找不到用户 ${RUNNER_USER} 的 home 目录" >&2
  exit 1
fi

GH_BIN="${GH_BIN:-$(command -v gh || true)}"
if [ -z "${GH_BIN}" ]; then
  for candidate in /usr/bin/gh /usr/local/bin/gh /opt/homebrew/bin/gh; do
    if [ -x "${candidate}" ]; then
      GH_BIN="${candidate}"
      break
    fi
  done
fi
if [ -z "${GH_BIN}" ]; then
  echo "找不到 gh，请先安装 GitHub CLI" >&2
  exit 1
fi

if ! sudo -u "${RUNNER_USER}" "${GH_BIN}" auth status >/dev/null 2>&1; then
  echo "用户 ${RUNNER_USER} 尚未登录 gh，请先执行：" >&2
  echo "  sudo -u ${RUNNER_USER} ${GH_BIN} auth login" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_SRC="${SCRIPT_DIR}/runner-disk-guard.service"
TIMER_SRC="${SCRIPT_DIR}/runner-disk-guard.timer"
SERVICE_DST="/etc/systemd/system/runner-disk-guard.service"
TIMER_DST="/etc/systemd/system/runner-disk-guard.timer"

for file in "${SERVICE_SRC}" "${TIMER_SRC}"; do
  if [ ! -f "${file}" ]; then
    echo "缺少文件：${file}" >&2
    exit 1
  fi
done

sed \
  -e "s|__RUNNER_USER__|${RUNNER_USER}|g" \
  -e "s|__RUNNER_HOME__|${RUNNER_HOME}|g" \
  -e "s|__GH_BIN__|${GH_BIN}|g" \
  -e "s|__WORKFLOW__|${WORKFLOW}|g" \
  -e "s|__REPO__|${REPO}|g" \
  -e "s|__REF__|${REF}|g" \
  "${SERVICE_SRC}" > "${SERVICE_DST}"
install -m 0644 "${TIMER_SRC}" "${TIMER_DST}"

systemctl daemon-reload
systemctl enable --now runner-disk-guard.timer

echo "已安装："
echo "  ${SERVICE_DST}"
echo "  ${TIMER_DST}"
echo
systemctl list-timers --all runner-disk-guard.timer
