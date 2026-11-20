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
