---
app: lz4
---
# lz4 升级注意点

## 构建方式
- 多阶段：源码 `make && make install DESTDIR=...`，运行阶段只复制二进制与库。

## 已知坑
- 版本号是 `1.11.1` 三段格式；tarball 在 GitHub release 与 lz4/lz4 tag 都可能存在，
  确认 URL 可用后再替换。
- 运行阶段不要依赖 builder 的工具链；`lz4`/`lz4c` 与 `liblz4.so` 都要复制。

## 验证
- `lz4 --version`；tests/test.sh 存在时以其为准。
