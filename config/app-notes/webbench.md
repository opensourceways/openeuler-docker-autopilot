<!-- oe-app-note:auto:b1acf3c01cc914729fe188dfc8ed761858028d4f/24.03-lts-sp4 -->
## 自动沉淀：b1acf3c01cc914729fe188dfc8ed761858028d4f / 24.03-lts-sp4

EZLippi/WebBench 上游 Makefile 默认 PREFIX=/usr/local/webbench，`make install` 会自动建 /usr/local/bin/webbench 软链接与 man/文档目录，无需手动 mkdir 或指定 PREFIX；仅需 gcc make ctags libtirpc-devel，源码仍 #include <rpc/types.h>，必须加 -I/usr/include/tirpc（openEuler 头文件位于 /usr/include/tirpc/rpc/types.h）。无 release tag，用 GitHub archive/<fullsha>.tar.gz 固定提交，解压目录为大写 WebBench-<fullsha>。构建极快（<1s），curl/tar 在基础镜像自带。
<!-- /oe-app-note:auto -->

<!-- oe-app-note:auto:fb32cae86117254cb27c4695e6aa77299724d62d/24.03-lts-sp4 -->
## 自动沉淀：fb32cae86117254cb27c4695e6aa77299724d62d / 24.03-lts-sp4

EZLippi/WebBench 固定提交的 Makefile 默认 PREFIX=/usr/local/webbench，make install 会自动创建 bin/man/doc 目录及 /usr/local/bin/webbench 软链接，无需手动 mkdir 或指定 PREFIX；仅需 gcc make ctags libtirpc-devel，webbench.c 仍 #include <rpc/types.h>，必须加 -I/usr/include/tirpc（openEuler 头文件位于 /usr/include/tirpc/rpc/types.h）。无 release tag，用 archive/<fullsha>.tar.gz 固定，解压目录为大写 WebBench-<fullsha>。构建极快（<1s），curl/tar 基础镜像自带。
<!-- /oe-app-note:auto -->
