---
app: openjdk
---
# openjdk 升级注意点

## 构建方式
- 直接下载 OpenJDK 官方二进制包（当前是 Early Access）：
  `jdk${主版本}/${build}/GPL/openjdk-${主版本}-ea+${build}_linux-${BUILDARCH}_bin.tar.gz`；
- `BUILDARCH` 由 `TARGETARCH` 映射为 `x64` / `aarch64`。

## 已知坑
- 版本号是 `28+24` 形式，URL 要拆成主版本与 build 两段；只替换其中一段会 404。
- Early Access 的旧 build 会从 download.java.net 下线；目标 build 不存在时，
  改用该主版本当前可下载的 EA build，并在 `assumptions` 里说明。
- 下载后只需要 `/usr/local/java`，运行阶段别丢 `JAVA_HOME` / `PATH`。

## 验证
- `java -version`；tests/test.sh 存在时以其为准。

<!-- oe-app-note:auto:28.25/24.03-lts-sp4 -->
## 自动沉淀：28.25 / 24.03-lts-sp4

openjdk 版本目录名用 '.' 分隔（如 28.25），而 java --version 运行时报告 '28-ea+25-xxxx' 解析为 '28+25'；test.sh 比较前须把 EXPECTED_VERSION 的 '.' 替换为 '+'，否则版本校验在两架构都会失败。
<!-- /oe-app-note:auto -->

<!-- oe-app-note:auto:28.26/24.03-lts-sp4 -->
## 自动沉淀：28.26 / 24.03-lts-sp4

## 28.26 新发现（源码构建路线）

- **二进制缺位**：GitHub 已存在 `jdk-28+26` 源码 tag，但 download.java.net 的 EA 二进制 `jdk28/26/GPL/openjdk-28-ea+26_linux-{x64,aarch64}_bin.tar.gz` 尚未发布。这种“源码 tag 已出、官方二进制未出”的版本必须走源码构建，不能沿用二进制下载。
- **boot JDK**：构建 JDK 28 用 N-1 即 JDK 27，取官方 GA 二进制 `jdk27.0.1.1`（源码 `DEFAULT_ACCEPTABLE_BOOT_VERSIONS="27 28"`）。
- **版本字符串坑**：从 GitHub tag tarball（无 git 历史）构建时，configure 默认得到 `28-internal+26-adhoc...`，对不上 test.sh 期望的 `28+26`。必须显式传 `--with-version-build=26 --with-version-pre=ea --without-version-opt` 才能得到 `28-ea+26`。
- **依赖坑**：即便 `--enable-headless-only`，configure 仍强制要求 `cups-devel`；还需 `diffutils`（DIFF 工具）、`m4`；工具链为 gcc/g++/make/autoconf 及 freetype/fontconfig/alsa。
- **产物路径**：`make images` 产物在 `build/<config>/images/jdk`，用 `cp -r .../. /opt/java/` 摊平为 `JAVA_HOME`。
- **构建耗时**：16 核 / 31GB 下 `make images` 约 15–20 分钟；boot JDK 约 224MB、源码 tarball 约 120MB。
<!-- /oe-app-note:auto -->
