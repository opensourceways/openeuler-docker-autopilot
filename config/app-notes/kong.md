<!-- oe-app-note:auto:3.9.5/24.03-lts-sp4 -->
## 自动沉淀：3.9.5 / 24.03-lts-sp4

Kong 官方 RPM 下载源已实测可用（x86_64 与 aarch64 均 HTTP 200）：https://packages.konghq.com/public/gateway-39/rpm/el/9/<x86_64|aarch64>/kong-3.9.5.el9.<arch>.rpm；Dockerfile 中 KONG_REPO 由 VERSION 去掉末位补丁再去点得到（3.9.5 -> 3.9 -> 39），TARGETARCH 需把 amd64/arm64 映射为 x86_64/aarch64。openEuler 24.03-lts-sp4 基础镜像仅有 libcrypt.so.1，Kong 的 OpenResty/Nginx 二进制依赖 libcrypt.so.2，需 ln -sf 兼容链接。
<!-- /oe-app-note:auto -->
