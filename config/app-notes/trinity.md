<!-- oe-app-note:auto:2.16.3/24.03-lts-sp4 -->
## 自动沉淀：2.16.3 / 24.03-lts-sp4

Trinity 2.16.3 FULL 包下载 URL 为 https://github.com/trinityrnaseq/trinityrnaseq/releases/download/Trinity-v${VERSION}/trinityrnaseq-v${VERSION}.FULL.tar.gz（sha256=4d6db75052bbedf1cc01967ba4418f37fd5a895bfb4145d747bc396b1ac951d3）。该版本构建核心无 Linux 变更（改动仅 macOS 的 FindOpenMP），需 CMake>=3.9。trinity-plugins 的 bamsifter 已内置 htslib-1.22.1.tar.bz2（build_htslib.sh 静态编译，configure 关闭 libcurl/gcs/s3/plugins/libdeflate），无需网络也无需系统 htslib，仅依赖 zlib/bzip2/xz-devel（builder 已装）。外部依赖 jellyfish 2.3.1 / bowtie2 2.5.5（x86_64 与 aarch64 校验值如 Dockerfile）/ salmon 1.10.0（x86_64 二进制、aarch64 源码）与 Trinity 版本无绑定，可长期沿用。x86_64 全程构建+运行时验证通过。
<!-- /oe-app-note:auto -->
