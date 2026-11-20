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
