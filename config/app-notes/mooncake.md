# mooncake

## 镜像内容与版本来源

- 上游 Issue 的安装候选是 wheel：`mooncake_transfer_engine_npu-<version>-cp3xx-...-<arch>.whl`，发行包名是 `mooncake-transfer-engine-npu`。镜像应通过 `pip install` 该 wheel 安装（需要 `python3-pip`），这样运行时能用发行包元数据校验版本。
- 历史镜像（0.3.14 及更早）是源码编译，只把三个二进制装到 `/usr/local/bin`，镜像里没有 Python 包；如果继续用源码编译，必须在构建期把版本写进镜像（如 `/opt/mooncake/VERSION`，内容取 `ARG VERSION`），测试读取该文件，不要退回用 `DOCKER_TAG`。
- 三个原生工具 `transfer_engine_bench` / `transfer_engine_bench_with_notify` / `transfer_engine_validator` **没有实现 `--version`**：上游示例代码没有调用 `gflags::SetVersionString`，`--version` 只能得到 gflags 的 unknown version，不能作为版本断言。
- 不要用 CI 注入的 `DOCKER_TAG` 解析版本再和 `EXPECTED_VERSION` 比较，那是镜像 tag 自证，静态契约会以 `kunpeng.expected_version_from_ci_tag` 拒绝。
- wheel 安装时精确版本从发行包元数据读取：
  - `python3 -c 'from importlib.metadata import version; print(version("mooncake-transfer-engine-npu"))'`
  - 或 `pip show mooncake-transfer-engine-npu`

## test.sh 版本断言要点

- 镜像版本目录 / `EXPECTED_VERSION` 可能是 `npu-v0.3.14.post1`，wheel 元数据是 `0.3.14.post1`，比较前需要去掉 `npu-v` 前缀。
- 推荐写法：

```bash
test_version() {
    local actual
    actual="$(python3 -c 'from importlib.metadata import version; print(version("mooncake-transfer-engine-npu"))' 2>/dev/null || true)"
    if [ "${actual}" = "${EXPECTED_VERSION#npu-v}" ]; then
        echo "PASS: mooncake wheel version ${actual}"
        return 0
    fi
    echo "FAIL: expected ${EXPECTED_VERSION#npu-v}, got '${actual}'"
    return 1
}
```

- 功能断言仍需覆盖真实二进制行为，例如三个工具的 `--help` 参数表，以及 `--mode=bogus` 时上游固定的 `Unsupported mode: must be 'initiator' or 'target'` 报错路径。
- 若镜像是源码编译而不是 wheel 安装，版本读取改为构建期写入的文件：

```bash
actual="$(cat /opt/mooncake/VERSION 2>/dev/null || true)"
```
