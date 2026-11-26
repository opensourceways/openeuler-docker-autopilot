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

MySQL 从 26.x 起采用日历版本号（major=年份、minor=月份，如 26.10.0），并在 tag 上追加第四位 update 组件（如 mysql-26.10.0.1）。源码中 MYSQL_VERSION_UPDATE 只进入 MYSQL_SERVER_VERSION_WITH_UPDATE，而 `mysqld --version` 打印的 MYSQL_SERVER_VERSION 仍是三位（26.10.0）。因此功能测试对这类带第四位的版本必须做三位基版本匹配，不能要求四位完全相等。
<!-- /oe-app-note:auto -->
