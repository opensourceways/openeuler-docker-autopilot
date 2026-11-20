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
