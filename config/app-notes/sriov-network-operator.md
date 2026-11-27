<!-- oe-app-note:auto:1.7.0/24.03-lts-sp4 -->
## 自动沉淀：1.7.0 / 24.03-lts-sp4

上游 sriov-network-operator 的 pkg/version/version.go 中版本常量是 2020 年 OpenShift 4.7 时代遗留的硬编码 "4.7.0"，从未随 v1.x tag 更新过（git 历史最后一条为 2020-10-16 "Create manifests for 4.7"）。关键坑：守护进程 `version` 命令用的是 `version.Version`（`semver.Version` 结构体），而 hack/build-go.sh 只能通过 `-ldflags -X pkg/version.Raw=...` 注入字符串变量 `Raw`，无法用 ldflags 覆盖 semver 结构体，因此所有源码构建的输出都会是 `v4.7.0`。升级/修复时必须构建前 `sed -i "s/4\.7\.0/${VERSION}/g" pkg/version/version.go` 把该常量改成与 git tag 一致，否则版本校验会稳定失败（x86_64 与 aarch64 同样失败）。sed 与 tar/curl 均已在 openEuler 基础镜像中可用，无需额外安装。
<!-- /oe-app-note:auto -->
