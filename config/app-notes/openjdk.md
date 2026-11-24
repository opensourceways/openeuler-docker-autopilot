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

## 版本写法
- 看板按 RPM scheme 会把 `28+25` 规范化为 `28.25`（点号），实际仍对应 OpenJDK 28 EA build 25；下载 URL 必须拆成主版本与 build 两段，拆分符要与 `VERSION` 变量实际分隔符一致：`+` 用 `${VERSION%%+*}`/`${VERSION#*+}`，`.` 用 `${VERSION%%.*}`/`${VERSION#*.}`。
- 产物直链（`early_access/jdk28/25/GPL/openjdk-28-ea+25_linux-{aarch64,x64}_bin.tar.gz`）仍返回 200，但 `download.java.net/java/early_access/jdk28/` 目录列表现在 404（`download.java.net/` 根已重定向到 oracle.com），不要依赖目录列表来探活。
- `TARGETARCH`/`BUILDARCH` 是 BuildKit 自动 ARG；`docker build` 日志里显示的 RUN 行会把 ARG 值（如 `arm64`）烤进显示文本，这只是显示层的替换，运行时 shell 里的 `if ... BUILDARCH="aarch64"` 重赋值仍会生效（实测 echo 输出 `RESOLVED_BUILDARCH=aarch64`，而日志头显示 `arm64`），下载因此拿到正确架构产物。
<!-- /oe-app-note:auto -->
