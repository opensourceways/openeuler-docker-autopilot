---
app: go
---
# go 升级注意点

## 构建方式
- 从 `https://dl.google.com/go/go${VERSION}.linux-${TARGETARCH}.tar.gz`
  下载官方二进制包，解压到 `/usr/local/go`。
- 旧文件在安装后删除编译工具链（gcc/make 等），并用 `touch -r` 修正文件时间戳。

## 已知坑
- 版本号必须是 `1.27.4` 这种三段格式；`dl.google.com` 的 arch 名是
  `amd64` / `arm64`，直接取 `TARGETARCH` 即可。
- 下载 URL 必须使用目标版本；不要改成 `latest` 或只改 `GOLANG_VERSION` 变量而漏掉 URL。
- 旧文件有 `yum update -y`，生成时不要新增；安装完再删除编译依赖，避免运行镜像变大。

## 验证
- `go version`；tests/test.sh 存在时以其为准。
