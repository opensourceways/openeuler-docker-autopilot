---
app: mysql
build_timeout_minutes: 240
---
# mysql 升级注意点

## 构建耗时
- 从 `mysql/mysql-server` 源码 CMake + `make -j` 全量编译，属于重型构建，
  单架构验证预算已提高到 240 分钟。

## 构建方式
- 下载 `mysql-${VERSION}.tar.gz`，`cmake` 配置后 `make -j && make install`；
- `-DDOWNLOAD_BOOST=1 -DWITH_BOOST=/tmp/boost` 会在构建期下载 Boost。
- 运行阶段保留 `config/` 与 `entrypoint.sh`，创建 mysql 用户并初始化数据目录。

## 已知坑
- tag 形如 `mysql-9.7.0`，与 `ARG VERSION` 拼接前确认。
- gosu 二进制按 `TARGETARCH`（amd64/arm64）下载，架构名不能写死。
- 旧文件有 `yum update -y`；生成时不要新增全量升级。
- 构建完成后会卸载 g++/make/wget，不要把运行阶段需要的包一起删掉。

## 验证
- `mysqld --version`；tests/test.sh 存在时以其为准。

<!-- oe-app-note:auto:26.10.0.1/24.03-lts-sp4 -->
## 自动沉淀：26.10.0.1 / 24.03-lts-sp4

MySQL 26.x 起不再依赖 Boost：cmake 的 -DDOWNLOAD_BOOST/-DWITH_BOOST 会被忽略并提示 unused（保留旧参数不影响构建）。26.x 的 update 版本（如 26.10.0.1）里 mysqld --version 只输出三位版本 26.10.0（MYSQL_SERVER_VERSION），第 4 段 update 号仅出现在 MYSQL_SERVER_VERSION_WITH_UPDATE 与包版本号中，属上游预期行为，非构建缺失。
<!-- /oe-app-note:auto -->
