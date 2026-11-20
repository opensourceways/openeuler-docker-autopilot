---
app: gradle
---
# gradle 升级注意点

## 构建方式
- 多阶段：builder 下载 `gradle-${VERSION}-bin.zip`，用官方 `.sha256` 校验后
  解压到 `/opt/gradle`；运行阶段装 `java-21-openjdk-headless` 并复制目录。

## 已知坑
- **每次升级都必须更新 sha256**：下载
  `https://services.gradle.org/distributions/gradle-${VERSION}-bin.zip.sha256`
  的最新值，旧哈希会让构建在 `sha256sum -c` 处失败（2026-11-20 的 9.9.1 升级
  就是在容器重放时当场发现并修正的）。
- 两个阶段都有 `ARG VERSION`，必须同时改。
- 不要用 `latest` 或仅改目录名。

## 验证
- `gradle --version`；tests/test.sh 存在时以其为准。
