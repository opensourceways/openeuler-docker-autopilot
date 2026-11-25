<!-- oe-app-note:auto:1.7.19/24.03-lts-sp4 -->
## 自动沉淀：1.7.19 / 24.03-lts-sp4

openEuler 24.03-LTS-SP4 的 OS/everything 仓库 cjson 最高版本为 1.7.15-11（含 cjson、cjson-devel），无法满足 1.7.19 版本需求，源码构建合理。上游 tag v1.7.19 = commit c859b25，源码 tar.gz sha256 为 7fa616e3046edfa7a28a32d5f9eacfd23f92900fe1f8ccd988c1662f30454562；注意当前 Dockerfile 下载步骤实际未加该校验和，后续需补 sha256sum 固定构建。
<!-- /oe-app-note:auto -->
