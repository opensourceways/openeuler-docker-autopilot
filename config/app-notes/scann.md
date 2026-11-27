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

scann 1.4.2 在 PyPI 同时提供 cp39-cp39-manylinux_2_27 的 x86_64 与 aarch64 轮子；清华 PyPI 镜像可能对本 runner 网段返回 403 导致 pip 报 'from versions: none'，构建时优先用官方 https://pypi.org/simple 作为索引。
<!-- /oe-app-note:auto -->
