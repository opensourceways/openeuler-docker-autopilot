<!-- oe-app-note:auto:26.10.10.3-stable/24.03-lts-sp4 -->
## 自动沉淀：26.10.10.3-stable / 24.03-lts-sp4

ClickHouse stable 发布 tag（如 v26.10.10.3-stable）在镜像版本目录带 -stable 后缀，但 clickhouse-server/--version 只上报数字版本；测试里精确比对版本前必须先剥离 -stable 后缀。官方 GitHub release 同时提供 x86_64 与 aarch64 的 clickhouse-server/clickhouse-common-static/clickhouse-client 三个 RPM，openEuler 24.03-lts-sp4 上直接 yum install 本地 RPM（依赖 sudo、shadow、libsemanage）即可完成安装，无需源码编译。
<!-- /oe-app-note:auto -->
