---
app: libconfig
---
# libconfig 升级注意点

## 构建方式
- 多阶段 autotools：`./configure && make && make install`，运行阶段复制库与头文件。

## 已知坑
- 小版本升级通常只改 `ARG VERSION` 和下载 URL；保持 `--prefix` 与运行阶段路径一致。
- 上游发行包命名可能带 `v` 前缀，先确认 tarball 名再拼接。
- 不要额外引入发行版自带的 libconfig 包，否则版本会与镜像声明不一致。

## 验证
- `pkg-config --modversion libconfig` 或编译一个最小读取示例；tests/test.sh 为准。
