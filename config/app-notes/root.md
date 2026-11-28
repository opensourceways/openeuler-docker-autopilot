<!-- oe-app-note:auto:v6-42-00/24.03-lts-sp4 -->
## 自动沉淀：v6-42-00 / 24.03-lts-sp4

v6-42-00 起 SearchInstalledSoftware.cmake 引入 ROOT_FIND_REQUIRED_DEP/MISSING_PACKAGES，缺失的可选依赖(xxHash/TIFF/nlohmann_json/gl2ps/FTGL/OpenGL/civetweb/Vdt/CFITSIO/XRootD/TBB)从自动禁用变为 configure 致命错误，需为这 11 项加 builtin_*=ON 走上游内置源码；基线镜像无 libGL/libGLU，opengl 仍被自动关闭(与 6-40-00 行为一致)，builtin_glu=ON 可满足 OpenGL 硬性要求。aarch64 上 gcc 12.3.1(cmake 3.31.12, C++17)全量构建、install、root -b 与 PyROOT(3.11.6) 均实测通过。
<!-- /oe-app-note:auto -->
