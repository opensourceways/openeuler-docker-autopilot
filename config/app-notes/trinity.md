<!-- oe-app-note:auto:2.16.3/24.03-lts-sp4 -->
## 自动沉淀：2.16.3 / 24.03-lts-sp4

Trinity 的 patch 升级（如 2.16.1→2.16.3）通常只改两处：`ARG VERSION` 与 FULL 源码包的 sha256 校验值，下载 URL 与产物名模式（trinityrnaseq-v${VERSION}.FULL.tar.gz）不变。新校验值可直接从 GitHub release API 的 `assets[].digest`（`sha256:...`）字段获取，不必手工下载计算。构建命令固定为 `make && make plugins && make install`，完整构建较慢（htslib/Chrysalis/Inchworm 等，x86_64 单线程约 5-10 分钟）。判断是否需改构建步骤时，先看上游发布说明：若变更只涉及 macOS/CMake FindOpenMP 等非 Linux 事项，则 Linux 侧构建步骤无需调整。
<!-- /oe-app-note:auto -->
