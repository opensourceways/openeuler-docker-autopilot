<!-- oe-app-note:auto:df38c01/24.03-lts-sp4 -->
## 自动沉淀：df38c01 / 24.03-lts-sp4

pfordelta 上游仓库 github.com/diegocaro/compression 已归档（2021-06 起只读），无 git tag，唯一 ref 为 master 分支且当前即 commit df38c01（df38c01dbfe111cfbb4e66d96d4ff14190da90bb），因此版本识别只能基于 commit SHA、无法按 tag 判定。上游 Makefile 默认 CFLAGS=-Wall -O9（-O9 非合法优化级别），Dockerfile 用 CFLAGS="-Wall -O3" 覆盖即可稳定编译；实测 `make` 不带目标即可构建出默认目标 howtouse（首行 `debug:` 仅为 target-specific 变量赋值，不会抢占默认目标），随后 `cp howtouse /usr/local/bin/howtouse` 可行。构建仅依赖 dnf 仓库的 git/gcc/make，无 TARGETARCH 条件分支，x86_64 与 aarch64 通用，符合架构对等与运行时包策略。
<!-- /oe-app-note:auto -->
