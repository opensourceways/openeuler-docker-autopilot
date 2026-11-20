---
app: fbthrift
---
# fbthrift 升级注意点

## 构建方式
- 从 `facebook/fbthrift` 的固定 tag 源码 CMake 构建，依赖 folly/wangle 等
  Facebook C++ 组件；编译时间长，首次构建通常要几十分钟。

## 已知坑
- 版本号是日期格式（`2026.11.16.00`），tag 与版本号完全一致，不要补 `v` 前缀。
- 上游子模块/依赖版本跟随 tag 变化；克隆时要拿到该 tag 对应的 submodule 版本，
  不要复用旧版本的依赖提交。
- 编译内存占用高，`make -j` 并行度不宜盲目拉满。

## 验证
- 构建产物（thrift1 / libthrift）存在；tests/test.sh 存在时以其为准。
