<!-- oe-app-note:auto:b1acf3c01cc914729fe188dfc8ed761858028d4f/24.03-lts-sp4 -->
## 自动沉淀：b1acf3c01cc914729fe188dfc8ed761858028d4f / 24.03-lts-sp4

EZLippi/WebBench 的 Makefile 与 baiguo/webbench-1.5 安装路径不同：默认 PREFIX=/usr/local/webbench，install 时写入 /usr/local/webbench/bin 并用 ln -sf 建立 /usr/local/bin/webbench 软链接，man 页软链到 /usr/local/man/man1；源码仍 #include <rpc/types.h>，必须 dnf 装 libtirpc-devel 并加 -I/usr/include/tirpc 才能编译（openEuler 上 rpc/types.h 位于 /usr/include/tirpc/rpc/types.h）。上游未发布 release tag，用 GitHub archive/<fullsha>.tar.gz 固定提交即可，解压目录为 WebBench-<fullsha>。
<!-- /oe-app-note:auto -->
