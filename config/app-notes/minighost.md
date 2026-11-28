<!-- oe-app-note:auto:272b8668b7adffa772a0573e74c0a31cf141906b/24.03-lts-sp4 -->
## 自动沉淀：272b8668b7adffa772a0573e74c0a31cf141906b / 24.03-lts-sp4

miniGhost 无 release tag，镜像固定 git commit 构建，但程序自报版本恒为 MG_VERSION 常量（当前 1.0.0，位于 ref/MG_CONSTANTS.F 的 CHARACTER*7 定义）。harness 传入的 EXPECTED_VERSION 是 commit SHA 而非语义版本，因此 test_version 必须从镜像内编译源码 MG_CONSTANTS.F 解析期望版本号（grep 'MG_VERSION[[:space:]]*=[[:space:]]*"[0-9]+\.[0-9]+(\.[0-9]+)?'），不能直接与 EXPECTED_VERSION 比较。构建期需 -fallow-argument-mismatch -ffree-line-length-none 两个 gfortran 标志（新版 gfortran 默认开启的参数不匹配报错），产物为 /opt/miniGhost/ref/miniGhost.x。
<!-- /oe-app-note:auto -->
