<!-- oe-app-note:auto:1.7.0/24.03-lts-sp4 -->
## 自动沉淀：1.7.0 / 24.03-lts-sp4

1.7.0 的 go.mod `go` 指令跳升到 1.26.5（1.6.0 为 1.23.0+toolchain 1.23.4），升级时必须同步抬高 GO_VERSION 到 ≥1.26.5，否则 go build 直接报 requires go。构建布局未变：manager 用根目录 main.go，config-daemon/webhook/config-cleanup 仍在 cmd/ 下；Makefile 的 MAIN_PKG=cmd/manager/main.go 是遗留字段，实际 hack/build-go.sh 对 manager 编译的是根 main.go。纯 Go CGO_ENABLED=0 构建、无新增系统依赖，但首次构建需联网拉取大量 k8s/controller-runtime 依赖，耗时较长。
<!-- /oe-app-note:auto -->
