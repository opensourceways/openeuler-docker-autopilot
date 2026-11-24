<!-- oe-app-note:auto:2026.11.23.00/24.03-lts-sp4 -->
## 自动沉淀：2026.11.23.00 / 24.03-lts-sp4

folly 的 BUILD_TESTS/BUILD_BENCHMARKS 是 cmake 默认值即 OFF 的 option，升级时无需显式改动；在 openEuler 24.03-lts-sp4 上源码全量编译约需数十分钟，产物仅 /usr/local/lib/libfolly.a（静态，BUILD_SHARED_LIBS 默认 OFF），下游应通过 find_package(folly CONFIG) 或 PKG_CONFIG_PATH=/usr/local/lib/pkgconfig 的 libfolly.pc 链接。
<!-- /oe-app-note:auto -->
