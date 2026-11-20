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
