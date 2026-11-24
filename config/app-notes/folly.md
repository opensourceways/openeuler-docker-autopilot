<!-- oe-app-note:auto:2026.11.23.00/24.03-lts-sp4 -->
## 自动沉淀：2026.11.23.00 / 24.03-lts-sp4

folly 从源码构建为静态库（默认 BUILD_SHARED_LIBS=OFF），会产出 libfolly.a 及数百个细粒度子库，全部安装到 /usr/local/lib。openEuler 24.03-lts-sp4 的 cmake 3.31 与 GCC 12.3 满足构建要求；所有必需依赖（fmt/glog/libevent/boost/gflags/openssl/压缩编解码等）均可由 dnf 提供，cmake 无需 FetchContent 拉取，因此 cmake --install 无额外版本要求。fast_float 未找到时会回退到 std::from_chars（仅性能提示，不影响构建）。liburing 保持不安装，folly 通过 FOLLY_HAS_LIBURING=0 守卫把 io_uring 集成编译掉，仍能完整构建其余全部模块。
<!-- /oe-app-note:auto -->
