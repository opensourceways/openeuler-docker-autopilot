<!-- oe-app-note:auto:npu-v0.3.14.post1/24.03-lts-sp4 -->
## 自动沉淀：npu-v0.3.14.post1 / 24.03-lts-sp4

- npu 变体（npu-v0.3.14.post1）起改用 PyPI 发行包 `mooncake-transfer-engine-npu` 安装（binary 模式），不再源码编译三件套；精确版本用 `${VERSION#npu-v}` 从 `npu-v0.3.14.post1` 派生出 `0.3.14.post1`。
- 依赖：`python3-pip`（openEuler 24.03 自带 python3 3.11.6，无 pip）+ 运行时库 `numactl-libs libibverbs`（wheel 内置原生 `transfer_engine_bench` 硬依赖 libnuma.so.1 / libibverbs.so.1）。
- wheel 覆盖 cp39~cp313 且 aarch64/x86_64 双架构，`pip3 install` 会按解释器/架构自动选 wheel，无需 `TARGETARCH` 分支。
- npu wheel 只提供 `transfer_engine_bench`/`mooncake_master`/`mooncake_client`/`mooncake_http_metadata_server`/`mc_store_rest_server`/`transfer_engine_topology_dump` 等入口，**没有** `transfer_engine_validator` 和 `transfer_engine_bench_with_notify`。
- 已知坑：npu wheel 的原生二进制硬依赖 Ascend CANN 的 `libascendcl.so`/`libllm_datadist.so`/`libmetadef.so`，openEuler 基础/EPOL 仓库均无此包；无 Ascend 环境（如 x86_64）时 `transfer_engine_bench` 会因缺这些库加载失败，属 NPU 变体固有硬件依赖，由 Ascend 部署环境提供，镜像本身只负责装好 wheel。
<!-- /oe-app-note:auto -->
