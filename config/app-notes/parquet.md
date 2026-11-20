---
app: parquet
---
# parquet 升级注意点

## 构建方式
- 镜像内容很轻：下载 `apache-parquet-format-${VERSION}` 源码包，解压到
  `/usr/local/parquet`，把 `bin` 加进 PATH。版本线是 **parquet-format**，不是 parquet-mr。

## 已知坑
- 2026-11-19 的运行在运行期校验失败：`Bigdata/parquet/tests/test.sh` 缺失，
  验证阶段直接判定 runtime_test 不可执行。新版本必须带可执行的 `tests/test.sh`，
  内容围绕 `/usr/local/parquet` 的产物（目录/文件存在性、`EXPECTED_VERSION`）。
- parquet-format 的归档地址在 archive.apache.org；目标版本不存在时不要伪造 URL。
- 该应用通常“版本已存在 → 走审计”，审计修复时同样要检查 test.sh。

## 验证
- `tests/test.sh` 通过；`/usr/local/parquet` 下能看到该版本内容。
