<!-- oe-app-note:auto:1.21.0/24.03-lts-sp4 -->
## 自动沉淀：1.21.0 / 24.03-lts-sp4

grib_api v1.21.0 的完整 commit 为 24e3bb60800b6488103c0b85293f4fe9b3be77c4；版本号由根目录 VERSION.cmake 硬编码（1.21.0），不依赖 git describe，因此固定 commit 检出后 cmake 仍识别正确版本。grib_ls -V 输出 `grib_api Version <ver>` 到 stdout 并以 0 退出（tools/grib_options.c 中 `-V` 走 grib_print_api_version），可用作构建期版本校验；grib_ls 无参数会进入 usage() 并以退出码 1 退出。libgrib_api.so 安装到 /usr/local/lib，运行 tools 需要 LD_LIBRARY_PATH=/usr/local/lib（Dockerfile 已通过 ENV 设置，构建期校验需内联 LD_LIBRARY_PATH）。
<!-- /oe-app-note:auto -->
