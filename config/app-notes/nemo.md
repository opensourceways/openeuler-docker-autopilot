---
app: nemo
---
# nemo 升级注意点

## 构建方式
- 多阶段 meson/ninja：先编译安装 `cinnamon-desktop` 与 `xapp`，再编译 nemo 本体；
- 依赖大量 GTK3 / gobject-introspection / GNOME 系 -devel 包。

## 已知坑
- 版本号带 `-unstable` 后缀（如 `6.8.4-unstable`），GitHub tag 与目录名必须完全一致。
- 旧文件有 `dnf update -y`；生成时不要新增全量升级。
- `meson setup` 的选项（`-Ddeprecated_warnings=false -Dgtk_doc=false`）来自旧文件，
  新版本若移除某个选项会直接报错，以该 tag 的 meson_options.txt 为准。
- 运行阶段依赖 `/usr/local/lib64` 的 LD_LIBRARY_PATH。

## 验证
- `nemo --help`；tests/test.sh 存在时以其为准。
