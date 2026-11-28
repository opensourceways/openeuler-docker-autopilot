<!-- oe-app-note:auto:v1.3.0/24.03-lts-sp4 -->
## 自动沉淀：v1.3.0 / 24.03-lts-sp4

tensorrt-llm v1.3.0 pip wheel installs a version.py reporting '__version__ = "1.3.0"' (no 'v' prefix), while the image version dir is 'v1.3.0'; version checks must strip the 'v'/'V' prefix from BOTH sides. The NVIDIA 'cuda-toolkit' PyPI meta-package is not served reliably by the Tsinghua mirror; use --extra-index-url https://pypi.nvidia.com/. The standalone cuda-toolkit meta-package is a no-op without extras (tensorrt_llm pulls its own nvidia-* deps).
<!-- /oe-app-note:auto -->
