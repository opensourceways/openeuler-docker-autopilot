---
app: snort3
---
# snort3 升级注意点

## 构建方式
- 先编译安装 `snort3/libdaq`（固定 `v3.0.21` 分支），再
  `git clone -b ${VERSION}` snort3，`./configure_cmake.sh --prefix=/usr/local` 后
  `make -j install`。

## 已知坑
- snort3 依赖 libdaq 的 ABI；升级 snort3 时如果上游要求新的 libdaq，
  要同步调整 libdaq 分支，不能只改 snort3 版本。
- 旧的 `libdaq` 分支写死 `v3.0.21`；以 snort3 该版本的 README/CI 为准。
- 依赖 `luajit-devel`、`hwloc-devel`、`libpcap-devel`、`pcre2-devel`；
  openEuler SP1 与 SP4 的包名可能不同。
- `LD_LIBRARY_PATH` 要包含 `/usr/local/lib/daq`。

## 验证
- `snort -V`；tests/test.sh 存在时以其为准。
