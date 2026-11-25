<!-- oe-app-note:auto:26.10.10.3-stable/24.03-lts-sp4 -->
## 自动沉淀：26.10.10.3-stable / 24.03-lts-sp4

## aarch64 CPU 兼容性（新发现，重要）
ClickHouse 官方 aarch64 release 二进制按 ARMv8.3-A 编译：gdb 复现首个 SIGILL 指令为 `ldaprb`（ARMv8.3 RCpc load-acquire），位于 `__xray_init`（启动期 ctor 即执行）。Kunpeng 920（HiSilicon implementer 0x48 / part 0xd01，ARMv8.2-A，/proc/cpuinfo 无 rcpc/lse/sve）上执行 `clickhouse-server`/`clickhouse-client --version` 即 `Illegal instruction`(exit 132)，RPM 的 `%post`（`clickhouse install`）同样崩溃导致 `clickhouse` 用户未创建（后续报 `id: 'clickhouse': no such user`）。该问题在 26.10.4.207 同样存在，属上游二进制与硬件的固有冲突，非本次升级引入。openEuler dnf（OS/EPOL/everything）无 clickhouse 包；上游源码构建强制 Clang 21（cmake/tools.cmake）且需数小时。aarch64 落地需改用针对 ARMv8.2 的源码构建或非官方 ARMv8.2 制品。

## test.sh 版本比较
镜像目录名为 `<ver>-stable`，但二进制 `--version`/`SELECT version()` 输出纯版本号 `<ver>`（不带 `-stable`）。test.sh 必须用 `${EXPECTED_VERSION%-stable}` 归一化后再比较，否则稳定版镜像的版本校验必失败。
<!-- /oe-app-note:auto -->
