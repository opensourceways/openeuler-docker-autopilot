<!-- oe-app-note:auto:4.4/24.03-lts-sp4 -->
## 自动沉淀：4.4 / 24.03-lts-sp4

QGIS 4.x 的 `qgis --version` 输出为 `X.Y.Z-<codename>`（如 `4.4.0-Auckland`），而镜像版本目录命名可能只有两位（如 `4.4`）；功能测试的版本匹配需支持轮询 token 与 `EXPECTED_VERSION` 的点分前缀相等（`X.Y.Z` 匹配 `X.Y`）。QGIS 4.4 上游 tag 为 `final-4_4_0`，Qt 6.5.2 / GEOS 3.9.0 / GDAL 3.10.1 环境下 `qgis-qt65.patch` 可干净 apply 并编译通过。
<!-- /oe-app-note:auto -->
