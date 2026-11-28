<!-- oe-app-note:auto:272b8668b7adffa772a0573e74c0a31cf141906b/24.03-lts-sp4 -->
## 自动沉淀：272b8668b7adffa772a0573e74c0a31cf141906b / 24.03-lts-sp4

miniGhost 无 release tag，构建固定到上游 commit。构建方式稳定：ref/makefile.mpi.gnu 需置空 MPI_LOC/MPI_INCLUDE、设 FC/CC/LD 为 mpif90/mpicc/mpif90，并给 FFLAGS 追加 -fallow-argument-mismatch -ffree-line-length-none（GCC 12.3.1 + Open MPI 4.1.5，aarch64 验证通过，产物 ref/miniGhost.x）。新目标提交 272b866 是上游“Import of MiniGhost v1.0 from Mantevo website”的初始导入提交，且为旧提交 c2102b5 的祖先，说明“升级”可能在提交图上往回走；后续升级务必直接比对源码差异而非假设版本号单调递增。编译期出现的 Fortran 实参类型不匹配和 main.c MPI_Abort 参数告警均非致命，可忽略。
<!-- /oe-app-note:auto -->
