<!-- oe-app-note:auto:7ee75e1/24.03-lts-sp4 -->
## 自动沉淀：7ee75e1 / 24.03-lts-sp4

ncview 是经典 autotools 工程但使用 configure.in（非 configure.ac），在 openEuler 24.03 的 autoconf 2.71 下只会产生 AC_ISC_POSIX/AC_HEADER_STDC/AC_CONFIG_HEADER 弃用告警，仍能正常生成 configure。netCDF 通过 nc-config 检测，需 netcdf-devel 且带 netCDF-4/HDF5 支持（NETCDF_V4=yes，openEuler 为 4.8.1 满足）。运行时版本号硬编码在 src/ncview.defines.h，并非来自 configure.in 的版本宏。liblo 仅在引入 OSC 变数选择功能的较新提交（如 fbf1aec）中才需要，早期提交（如 7ee75e1）的 m4macros 只含 netcdf/png/udunits2，不含 liblo，升级时需按目标提交的 m4macros 判断是否保留 liblo 构建步骤。
<!-- /oe-app-note:auto -->
