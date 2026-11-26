<!-- oe-app-note:auto:2.16.3/24.03-lts-sp4 -->
## 自动沉淀：2.16.3 / 24.03-lts-sp4

Trinity v2.16.3 起 Inchworm/Chrysalis 改用 CMake FindOpenMP，要求 CMake>=3.9（openEuler 24.03 自带 3.31.12 已满足，无需额外处理）。上游 release 的 FULL.tar.gz 已含全部子模块，`make && make plugins && make install` 即可完整构建（make plugins 会编译 bamsifter/htslib 与 collectl，耗时较长）。Trinity --version 会额外提示“最新版本为 2.16.5”但不影响版本固定。jellyfish/bowtie2/salmon 为独立运行时依赖，其版本不随 Trinity 版本联动，升级时无需改动（salmon 在 aarch64 下无官方二进制，走源码分支）。
<!-- /oe-app-note:auto -->
