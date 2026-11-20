---
app: lustre
build_timeout_minutes: 240
---
# lustre 升级注意点

## 构建方式
- 从 `lustre/lustre-release` 的 `${VERSION}` tag 源码
  `./autogen.sh && ./configure && make && make install`；
- 会同时编译内核模块与用户态工具，依赖 `kernel-devel` / `kernel-headers` /
  `elfutils-libelf-devel`。内核模块编译较慢，单架构验证预算已提高到 240 分钟。

## 已知坑
- `make KCFLAGS="-Wno-error=unused-label"` 是旧文件为了绕过新内核告警的补丁；
  升级后若仍在新内核上编译，保留它。
- 版本号是 `2.17.61` 这类三段数字，tag 与版本号一致（无 `v` 前缀）。
- `make install` 后要 `ldconfig`，否则运行阶段找不到库。

## 验证
- `lfs --version`；tests/test.sh 存在时以其为准。
