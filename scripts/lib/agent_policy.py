"""所有生成/修复 Dockerfile 的 Agent 共用的硬性交付策略。

这些条款会拼接到每个 Agent 的不可变契约里。它不是某个应用的知识，
而是镜像必须满足的底线要求，避免 Agent 为了让构建“看起来通过”而砍掉
另一个架构的编译、安装或测试。
"""

from __future__ import annotations

ARCHITECTURE_PARITY_POLICY = """## Architecture parity policy（硬性要求）

- Dockerfile 必须在 x86_64 与 aarch64 两个目标架构上各自完成真正的构建、
  安装和运行，不能只让其中一个架构干活。
- 禁止用 `TARGETARCH`、`uname -m` 等条件把编译、安装或测试整体挡在单架构
  后面，例如 `if [ "$TARGETARCH" = "amd64" ]; then cmake --build ...; fi`
  让 aarch64 只做 configure 就产出“能构建”的镜像。这种镜像不算成功。
- 允许架构分支的唯一前提是：两个分支都产出功能等价的可用产物，差别只限于
  包名、产物名、下载地址、编译器或依赖守卫等实现细节。
- 确实无法支持某个架构时，必须报告失败并给出证据（缺依赖、缺上游产物等），
  不能通过跳过编译、跳过安装或跳过测试来伪造成功。
"""


RUNTIME_PACKAGE_POLICY = """## Runtime package policy（硬性要求）

- Python、R 这类通用编程语言运行时必须用 dnf 安装 openEuler 仓库已有的包
  （如 `python3`、`python3-devel`、`R`、`R-devel`），禁止从源码编译解释器。
- 任何软件只要 openEuler 的 dnf 仓库（含 EPOL）能装到可用版本，就必须用 dnf
  安装，不要为了对齐上游版本号去源码编译。
- 只有 dnf 仓库确实没有该软件、或仓库版本无法满足镜像运行需求时，才允许源码
  构建，并在交付说明里写清证据（查过的仓库、缺失的包名）。
- 用 dnf 安装后仍要在两个架构上验证实际版本与功能，不能 `dnf install` 完就
  宣称成功。
"""


def build_policy() -> str:
    """返回所有生成/修复 Dockerfile 的 Agent 共用的完整构建策略。"""
    return f"{ARCHITECTURE_PARITY_POLICY}\n{RUNTIME_PACKAGE_POLICY}"
