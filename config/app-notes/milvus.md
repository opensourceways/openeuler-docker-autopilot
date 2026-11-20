---
app: milvus
build_timeout_minutes: 300
generate_timeout_minutes: 180
---
# milvus 升级注意点

## 构建耗时（重要）
- 从源码全量构建：toolchain 阶段装 Go 1.26 / Rust 1.92 / Conan 2.x / CMake 3.26，
  builder 阶段 `make build-3rdparty` 后用 conan 编译第三方依赖，再 `make install`。
- 2026-11-19 实测：x86_64 原生验证约 2 小时；aarch64 超过 180 分钟仍在校验中被超时终止。
  因此本应用的单架构验证预算设为 **300 分钟**，生成/修复 Agent 预算 **180 分钟**。
  如果再次出现超时，优先调大本文件的这两个值，而不是改 Dockerfile。

## 构建方式
- 三阶段：`toolchain` → `builder` → 运行阶段；`ARG VERSION` 在 builder 阶段，
  `git clone --branch v${VERSION}`。
- `jemalloc` 的 page size 必须按目标架构自动推导（aarch64 64K / x86_64 4K），
  不要写死。
- 第三方依赖构建后删除 conan 的 build/source 目录（约 11GB），否则磁盘会打满。

## 已知坑
- Conan 自带的 OpenSSL 与系统 git/libcurl 冲突：必须保留把 `/usr/bin/git`
  包装成 `unset LD_LIBRARY_PATH` 的那一步。
- 必须保留 `scripts/3rdparty_build.sh` 的补丁（跳过 conan 的 openssl/libcurl），
  否则会链接到错误版本的 OpenSSL。
- MinIO 使用固定的 `MINIO_RELEASE`，通过 `go install` 构建，不要改回 dl.min.io latest。
- 旧文件里的 `make build-3rdparty` 与 `SKIP_3RDPARTY=1` 配合不能拆开。

## 验证
- 运行阶段启动 milvus 并执行 tests/test.sh（首次启动等待时间较长）。
