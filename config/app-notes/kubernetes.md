<!-- oe-app-note:auto:1.37.3/24.03-lts-sp4 -->
## 自动沉淀：1.37.3 / 24.03-lts-sp4

tests/test.sh 通过 find_bin 及通配路径 /usr/local/kubernetes-*/_output/bin/kubeadm 定位二进制，WORKDIR 必须严格等于 kubernetes-${VERSION}；kubelet 版本探测带 `|| true` 兜底，kubeadm 才是版本断言的硬依赖。构建用 `make -j$(nproc)` 即可双架构限并发、避免 OOM，同时产出 kubeadm/kubelet。
<!-- /oe-app-note:auto -->
