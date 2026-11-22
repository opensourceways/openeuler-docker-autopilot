---
app: o3de
build_timeout_minutes: 360
generate_timeout_minutes: 300
---
# o3de 升级注意点

## 构建方式
- 单个 `RUN` 完成 `git clone`、`python/get_python.sh`、CMake configure 和
  `cmake --build --target Editor`；构建图约 2186 个 target。
- 第三方依赖（Qt、pyside、OpenSSL、OpenEXR 等）由 O3DE 自己的 3rdParty
  包系统在 configure 阶段下载到 `/opt/o3de-packages/packages/`，不要换成
  发行版 Qt；O3DE 按包名 + sha256 固定版本，系统 Qt 不在它的索引里。

## 已知坑

### 不能只编译单架构
- 2605.0 的 Dockerfile 结尾是：
  `if [ "$TARGETARCH" = "amd64" ]; then cmake --build build/linux --target Editor --config release -j2; fi`
- 结果 aarch64 只做了 `cmake` configure，镜像里没有任何可执行文件，
  但验证仍然“通过”。这是假成功，升级时不要让这种守卫原样保留。
- 两个架构都要真正执行 `cmake --build`；架构分支只允许用于包名、下载地址
  这类实现差异。

### x86_64 与 aarch64 的 Qt 版本不同
- x86_64：`qt-6.10.2-rev8-linux` + `pyside6-6.10.2-py3.10`
- aarch64：`qt-5.15.2-rev9-linux-aarch64` + `pyside2-5.15.2.1-py3.10`
- aarch64 需要 Qt5 适配（参考 2605.0 Dockerfile 里的 arm64 分支）：
  `pyside6` → `pyside2`、
  `3rdParty::Qt::SvgWidgets` → `3rdParty::Qt::Svg`、
  `3rdParty::Qt::OpenGLWidgets` → `3rdParty::Qt::OpenGL`，
  并回退 `cmake/LYWrappers.cmake` 的一个上游改动（反向 `git apply`）。
  这些补丁只改 CMake 引用，不需要自己编译 Qt。

### 链接缺 harfbuzz
- `/opt/o3de-packages` 的 `libQt6Gui.so` 依赖 `libharfbuzz.so.0`；构建镜像
  没装 harfbuzz 时，`AssetBuilder`/`Editor` 链接失败，表现为
  `undefined reference to hb_face_set_upem` 等。
- 构建阶段需要安装 `harfbuzz`/`harfbuzz-devel`，或把 harfbuzz 的 lib 目录
  加入 rpath-link。aarch64 的 Qt5 包同样依赖系统的 harfbuzz/fontconfig。

### 构建很慢
- 实测 `-j2` 在 16 核、25 GB 可用内存的机器上，1890/2186 用了约 64 分钟，
  且最后 Editor 链接仍可能失败。
- 用 `-j8` 左右；不要用 `-j$(nproc)`，Editor/Atom 链接阶段的峰值内存高，
  16 路并行有 OOM 风险。

## 验证
- 只跑 `--version` 不足以证明构建成功；至少确认 `Editor`、`AssetBuilder`
  等二进制存在并能启动。
- 两个架构分别验证，不要拿 configure 通过当成构建通过。
