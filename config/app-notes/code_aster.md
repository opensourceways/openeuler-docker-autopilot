<!-- oe-app-note:auto:832565d/24.03-lts-sp4 -->
## 自动沉淀：832565d / 24.03-lts-sp4

832565d 相对旧版仅改动 bibfor Fortran 源码，构建流程不变，升级只需同步 VERSION 与 hg 伪脚本中的哈希串即可。构建要点：openEuler 中 blas-devel 为虚拟包（由 lapack-devel 提供），dnf 可自动解析；waf build install -p 约 2.5 分钟完成编译并安装出 /usr/local/bin/aster（约 27MB aarch64 ELF）；安装后的 catalog 预热步骤（E_SUPERV.py）稳定返回 -6 并以 || true 兜底，`aster --version` 正常。
<!-- /oe-app-note:auto -->
