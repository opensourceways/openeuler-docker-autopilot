<!-- oe-app-note:auto:6.1/24.03-lts-sp4 -->
## 自动沉淀：6.1 / 24.03-lts-sp4

nDPI 6.1-qubitowl 的 autogen.sh 新增了对 pkg-config（以及 autoreconf）的强制检查，openEuler 上 pkg-config 由 pkgconf 包提供，yum install pkg-config 即可。默认 make 目标无需 gcc-c++/flex/bison/gettext（示例均为 C 代码）。
<!-- /oe-app-note:auto -->
