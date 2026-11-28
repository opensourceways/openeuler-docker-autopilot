<!-- oe-app-note:auto:npu-v0.3.14.post1/24.03-lts-sp4 -->
## 自动沉淀：npu-v0.3.14.post1 / 24.03-lts-sp4

npu 版 wheel (`mooncake-transfer-engine-npu`) 是统一 manylinux 包，其原生二进制 (transfer_engine_bench、mooncake_client 等) 与 `mooncake._store` 扩展都链接 Ascend CANN 运行时 (`libascendcl.so`/`libllm_datadist.so`/`libmetadef.so`)，这些库既未打包进 wheel，openEuler dnf 仓库也没有。因此 CPU 容器里无法执行这些原生二进制（`--help`/`--version`/`--mode` 均报 libascendcl 缺失），功能测试只能校验：发行包元数据版本、pip 安装的控制台脚本(transfer_engine_bench/mooncake_client/mooncake_master 等)、`mooncake._launcher.locate()` 返回的内置二进制存在、以及 `import mooncake` 的懒加载包初始化。注意 `import mooncake` 成功，但 `from mooncake import BufferPool` 会因导入 `mooncake._store` 而失败。该 wheel 仅提供 `transfer_engine_bench`，不包含 `transfer_engine_validator` 与 `transfer_engine_bench_with_notify`。
<!-- /oe-app-note:auto -->
