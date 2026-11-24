<!-- oe-app-note:auto:26.10.10.3-stable/24.03-lts-sp4 -->
## 自动沉淀：26.10.10.3-stable / 24.03-lts-sp4

ClickHouse 的 "-stable" release 标签为 `v<ver>-stable`，但 release 里的 RPM 产物版本号不带 `-stable` 后缀（如 `clickhouse-server-26.10.10.3.x86_64.rpm`）。当 new_version 带 `-stable` 时，下载 URL 应写 `release/download/v${VERSION}/`，产物名用 `${VERSION%-stable}` 还原纯版本号，不要沿用 `v${VERSION}-stable` 构造。官方 RPM 安装依赖仅 `sudo`、`shadow`（openEuler yum 均可提供），common-static 包约 280MB，构建耗时约 40s，双架构产物均在 GitHub release 中提供（x86_64 与 aarch64）。
<!-- /oe-app-note:auto -->
