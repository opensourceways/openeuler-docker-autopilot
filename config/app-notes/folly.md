<!-- oe-app-note:auto:2026.11.23.00/24.03-lts-sp4 -->
## 自动沉淀：2026.11.23.00 / 24.03-lts-sp4

folly 升级经验（新增）：

- **PACKAGE_VERSION 不从 git tag 派生**：folly `CMakeLists.txt` 硬编码默认 `0.58.0-dev`（`if (NOT DEFINED PACKAGE_VERSION)`），导致 `libfolly.pc` 的 `Version:` 与 tag 不符。构建时务必加 `-DPACKAGE_VERSION=${VERSION}`，否则版本校验失败。
- **pkg-config 静态链接缺库**：folly 生成的 `libfolly.pc` 的 `Libs.private` 只包含路径型依赖（ssl/event/z/...），其 CMake-target 依赖（fmt、glog、gflags、Threads）只进 cflags 不进 `-l`。静态链接必须手动补 `-lfmt -lglog -lgflags -lpthread`（与 README 的 `-lfolly -lglog -lgflags -lfmt -lpthread` 一致）。
- **2026.11.23.00 API 变更**：`folly::json::serialize(const dynamic&)` / `folly::json::parse()` 已移除，改为需传 `serialization_opts` 的两参版本；命名空间 `folly` 下新增便捷函数 `folly::toJson(const dynamic&)` 与 `folly::parseJson(StringPiece)`，探测程序应改用后者。
<!-- /oe-app-note:auto -->
