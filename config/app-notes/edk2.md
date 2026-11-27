<!-- oe-app-note:auto:202611/24.03-lts-sp4 -->
## 自动沉淀：202611 / 24.03-lts-sp4

openEuler 24.03-LTS-SP4 中 NASM 包名为 nasm，IASL 编译器由 acpica-tools 提供（/usr/bin/iasl），二者仅位于 everything 仓库（aarch64 与 x86_64 均有），不在 OS/EPOL main 仓库；edk2 构建 X64 目标固件或完整 MdeModulePkg 需补齐这两个依赖。
<!-- /oe-app-note:auto -->
