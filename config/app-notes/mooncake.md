<!-- oe-app-note:auto:npu-v0.3.14.post1/24.03-lts-sp4 -->
## 自动沉淀：npu-v0.3.14.post1 / 24.03-lts-sp4

- npu-v0.3.14.post1 改用 `ASIO_SEPARATE_COMPILATION ASIO_DYN_LINK` 编译 asio，产出 `mooncake-common/libasio.so`，`transfer_engine_bench` 运行期依赖它，须 `install` 到 `/usr/lib64` 并 `ldconfig`（旧版静态链接无需此步）。
- 该版本的官方产物仅 `mooncake_transfer_engine_npu-*.whl`，其捆绑的 C++ 二进制运行期依赖 Ascend/CANN 运行库（libascendcl.so、libllm_datadist.so、libmetadef.so），openEuler 仓库无此包；因此选择源码构建（Ascend 相关开关关闭），产出与历史镜像一致的 CPU 侧 CLI，可独立运行。
- npu 系列 tag 命名是 `npu-vX.Y.Z.postN`（区别于历史 `vX.Y.Z.postN`），clone 分支需直接引用完整 tag。
<!-- /oe-app-note:auto -->
