<!-- oe-app-note:auto:2026.11.23.00/24.03-lts-sp4 -->
## 自动沉淀：2026.11.23.00 / 24.03-lts-sp4

folly 的顶层 CMakeLists.txt 用 if (NOT DEFINED PACKAGE_VERSION) 回退到 0.58.0-dev，且不读取 folly/VERSION（该文件内容仅为 ABI 版本号）也不执行 git describe，因此源码构建必须显式传 -DPACKAGE_VERSION=<tag 版本号> 才能让 /usr/local/lib/pkgconfig/libfolly.pc 的 Version 字段与镜像版本一致。全部依赖可从 openEuler 24.03-LTS-SP4 dnf 仓库装齐（boost/gflags/glog/fmt/libevent/openssl/zlib/bzip2/xz/lz4/zstd/snappy/libsodium/libunwind/libdwarf/libaio 等 -devel 包），无需 liburing-devel（仓库 2.4 过旧，缺 ZCRX/io_uring_register_ifq API，folly 会以 FOLLY_HAS_LIBURING=0 编译剔除 io_uring 集成）。16 核下 cmake 配置约 7s、编译几个~十几分钟、libfolly.a 约 382MB。
<!-- /oe-app-note:auto -->
