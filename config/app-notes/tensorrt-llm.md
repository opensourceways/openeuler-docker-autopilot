<!-- oe-app-note:auto:v1.3.0/24.03-lts-sp4 -->
## 自动沉淀：v1.3.0 / 24.03-lts-sp4

## 上游 wheel 平台标签变化（1.2.1 → 1.3.0）
- 旧版 1.2.1 的 aarch64 wheel 为 `tensorrt_llm-1.2.1-cp312-cp312-linux_aarch64.whl`（`linux_aarch64` 无 glibc 下限）；新版 1.3.0 的 aarch64 stable wheel 变为 `tensorrt_llm-1.3.0-cp312-cp312-manylinux_2_39_aarch64.whl`（要求 glibc >= 2.39）。
- openEuler 24.03-lts-sp4 的 glibc 为 2.38，无法满足 `manylinux_2_39`，pip 会回退到 pypi.org 上的 sdist 源码构建；该构建依赖 nvidia-smi / CUDA 驱动，无 GPU 容器会 `metadata-generation-failed`。x86_64 的 stable wheel 为 `manylinux_2_28_x86_64`，不受影响。

## 依赖元数据变化
- `tensorrt_llm` 1.3.0 的元数据声明 `torch<=2.14.0,>=2.14.0a0`（并 pin `triton==3.8.0`、`transformers==5.5.4`、`nvidia-nccl-cu13` 等），与既有 `torch==2.9.1 (cu130)` pin 冲突；pip 安装 1.3.0 时可能触发 torch 大版本升级，升级前应确认 cu130 索引下目标 torch 的可用性。

## 构建经验
- 该镜像需先源码构建 Python 3.12.6（aarch64 只有 cp312 wheel），再按 torch → cuda-toolkit → tensorrt_llm 顺序 pip 安装，整体下载与磁盘占用量极大，完整自检需预留充足磁盘（>50GB）与时间。
<!-- /oe-app-note:auto -->
