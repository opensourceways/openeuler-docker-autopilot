---
app: scann
---
# scann 升级注意点

## 构建方式
- 镜像里先源码编译 Python 3.9 到 `/opt/python39`，再
  `pip install scann==${VERSION}`（pip 包版本，当前 ARG 是 `1.4.2`）。

## 已知坑
- **目录名/清单版本是上游 7 位短 SHA（如 `7117df5`），与 Dockerfile 里的
  `ARG VERSION`（pip 包版本）是两套版本线**。按 SHA 升级时，
  必须同时确认 pip 上 scann 的最新版本是否需要更新，不能只改目录名。
- Python 3.9 是从源码编译的；升级 pip 包前先确认 scann 支持的 Python 版本，
  必要时同步升级 Python 源码版本（下载 URL 与 sha256 一起改）。
- pip 使用清华镜像，换源不影响版本语义，但不要写死 latest。

## 验证
- `python -c "import scann; print(scann.__version__)"`；tests/test.sh 为准。

<!-- oe-app-note:auto:4a7bc8ab0bc770e71a259b7966c500496b99010a/24.03-lts-sp4 -->
## 自动沉淀：4a7bc8ab0bc770e71a259b7966c500496b99010a / 24.03-lts-sp4

- scann 1.4.2 的 aarch64 wheel 内 `scann_pybind` 扩展实际按 Python 3.9 编译（连 cp311 wheel 也会报 "module was compiled for Python 3.9"），因此 aarch64 上必须继续用源码编译到 /opt/python39 的 Python 3.9 运行 scann，不能改用 dnf 的 python3.11。
- google-research 仓库的 commit SHA 常只改动无关目录（如 cogentic_research_papers），此时 scann/pyproject.toml 与 PyPI 版本均不变，升级仅体现为 ARG COMMIT + OCI revision 标签，pip 包版本保持 1.4.2。
- dnf 的 `update` 仓库 gpgkey 配置指向 OS 的 key，直接 `dnf install python3` 升级会 GPG 失败；本镜像只安装 gcc 等构建工具，不触发 python3 升级，不受影响。
<!-- /oe-app-note:auto -->
