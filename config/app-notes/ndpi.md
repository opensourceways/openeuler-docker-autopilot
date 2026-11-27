<!-- oe-app-note:auto:6.1/24.03-lts-sp4 -->
## 自动沉淀：6.1 / 24.03-lts-sp4

nDPI 6.1 的看板解析 target 为 6.1，但上游实际 tag 是 6.1-qubitowl（带供应商限定后缀）。git clone -b 6.1-qubitowl 可正常构建（产物 libndpi.so.6.1.0），但 git describe --tags --abbrev=0 返回 6.1-qubitowl 而非纯 6.1。因此 test.sh 的版本校验不能用精确相等，须容忍 "<EXPECTED_VERSION>-*" 后缀，后续升级若再遇到带限定后缀的 tag 可复用该 case 通配写法。构建依赖较稳定：git make gcc autoconf automake libtool pkg-config libpcap-devel，aarch64 全量 make 约 127s。
<!-- /oe-app-note:auto -->
