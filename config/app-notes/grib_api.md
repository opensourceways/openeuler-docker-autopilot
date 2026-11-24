<!-- oe-app-note:auto:1.21.0/24.03-lts-sp4 -->
## 自动沉淀：1.21.0 / 24.03-lts-sp4

上游 weathersource/grib_api 仅保留 v1.21.0、v1.19.0 两个 tag；grib_ls 没有 -h 帮助选项（README 中的 grib_ls -h 会被 getopt 当作未知选项而走 usage() 并以退出码 1 退出），版本查询应使用 grib_ls -V（打印 grib_api Version、退出码 0），无参数时打印 usage 并退出码 1——image-info.yml 的 usage 已据此采用 grib_ls -V，无需改动。
<!-- /oe-app-note:auto -->
