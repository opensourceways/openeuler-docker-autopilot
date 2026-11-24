<!-- oe-app-note:auto:4.4/24.03-lts-sp4 -->
## 自动沉淀：4.4 / 24.03-lts-sp4

QGIS 4.4 在 openEuler 24.03-LTS-SP4（Qt 6.5.2 / GEOS 3.9.0 / GDAL 3.10.1 / PROJ 9.8.1 / Python 3.11）上源码构建要点：
- 仍需 Qt 6.5/GEOS 3.9 兼容补丁，且 4.4 新增多处上游仅按 Qt>=6.6 / GEOS>=3.13 编写的代码：QWebEnginePage 新的 permissionRequested(QWebEnginePermission) 信号在 6.5 下为 featurePermissionRequested(url,Feature)+setFeaturePermission；QImage::Format_CMYK8888 需 QT_VERSION>=6.8 守卫；GEOS_CIRCULARSTRING 需 GEOS>=3.15 守卫；QtFuture::makeReadyValueFuture 需改回 makeReadyFuture（Qt 6.9 才引入）。
- 4.4 新增 WITH_WAYLAND 默认 ON（需 qt6-qtwayland，openEuler 未打包），必须 -DWITH_WAYLAND=OFF。
- 与上游发布镜像 .docker/qgis.dockerfile 一致，加 -DENABLE_TESTS=OFF 以避免构建约 49 个单测可执行文件。
- MDAL/poly2tri/nlohmann-json/spatialindex/Qwt 走内嵌副本，无需额外 dnf 依赖；odbccpp 仅 WITH_HANA=ON 时需要。
- 构建耗时约 25-30 分钟（16 核），源码安装到 /usr/local，qgis/qgis_process 均可运行。
- 注意：qgis --version 输出 4.4.0-Auckland，而镜像版本目录为 4.4，tests/test.sh 的精确版本断言可能需兼容 4.4.0 前缀。
<!-- /oe-app-note:auto -->
