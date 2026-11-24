---
app: grpc-server
---
# grpc-server 升级注意点

## 构建方式
- 镜像构建的是 **grpc-java**（`https://github.com/grpc/grpc-java`），
  克隆 `v${VERSION}` 后在 `examples` 目录执行 `./gradlew installDist`。

## 已知坑
- 版本线是 grpc-java 的 `1.85.x`，不是 grpc-cpp；tag 形如 `v1.85.1`。
- 旧文件用 Java 8 构建；升级后若上游要求更高 JDK，以该 tag 的 build.gradle 为准。
- Gradle wrapper 首次运行要下载发行包，runner 网络抖动会表现为构建失败；
  不要因此改版本或跳过 `installDist`。
- openEuler `[update-source]` 仓库 404 是环境问题，harness 会统一注入
  `skip_if_unavailable=True`，不要为此改仓库配置。

## 验证
- `./build/install/examples/bin/hello-world-server` 存在并能启动；tests/test.sh 为准。

<!-- oe-app-note:auto:1.85.4/24.03-lts-sp4 -->
## 自动沉淀：1.85.4 / 24.03-lts-sp4

## grpc-java 版本线与 grpc/grpc(C++) 脱钩
- grpc-java（https://github.com/grpc/grpc-java）的 1.85.x 线只有 v1.85.2 之前的 v1.85.0/v1.85.1，之后直接进入 v1.86.0；**不存在 v1.85.2/v1.85.3/v1.85.4**。
- 若升级任务的新版本 source_url 指向 grpc/grpc(C++)，其 patch 版本（如 1.85.4）在 grpc-java 中并不存在，属于仓库/版本误配；升级 grpc-server 时应以 grpc-java `git ls-remote --tags` 的实际 tag 为准，不要套用 grpc-cpp 版本号。

## 构建方式（沿用）
- clone grpc-java `v${VERSION}` → 在 `examples` 目录执行 `./gradlew installDist`；产物 `build/install/examples/bin/hello-world-server` 监听 50051。
- openEuler 用 `java-1.8.0-openjdk` + `git` 即可；Gradle wrapper 首次运行会联网下载发行包。

## 验证
- tests/test.sh 用 EXPECTED_VERSION 比对 `installDist` 产出的 `grpc-core-*.jar` 版本，并跑 hello-world 回环；因此镜像产出的 jar 版本必须与目标 grpc-java tag 严格一致。
<!-- /oe-app-note:auto -->
