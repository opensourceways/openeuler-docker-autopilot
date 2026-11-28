<!-- oe-app-note:auto:fe6f9b0/24.03-lts-sp4 -->
## 自动沉淀：fe6f9b0 / 24.03-lts-sp4

构建经验：1) pypi.tuna.tsinghua.edu.cn 在本 runner 环境（host 与容器一致）返回 HTTP 403，pip 安装需改用默认 PyPI 或可用的镜像；2) bazelisk-linux-{amd64,arm64} 均有 release 产物，用 ${TARGETARCH} 即可双架构同源，无需硬编码；3) 该镜像仅为构建环境（bazelisk + python/tf 依赖 + 源码 checkout），不实际执行 bazel 编译 monolith 目标，故 bazelisk latest 拉到的 bazel 9.x 与 WORKSPACE 要求的 bazel>=3.0 的兼容性不在本镜像验证范围内。
<!-- /oe-app-note:auto -->
