<!-- oe-app-note:auto:5.1.0/24.03-lts-sp4 -->
## 自动沉淀：5.1.0 / 24.03-lts-sp4

纯 OpenCV 5.1.0 源码构建要点：openEuler 24.03-lts-sp4 默认 python3 为 3.11.6，numpy 用 dnf 的 python3-numpy(1.24.3)；5.1.0 中 BUILD_opencv_python_bindings_generator 已非顶层选项，仅需 BUILD_opencv_python3=ON；安装前缀 /usr/local 时库落到 /usr/local/lib64，需写入 ld.so.conf 并用 lib64 路径，cv2 默认落在 /usr/local/lib/python3.11/site-packages（在 sys.path 内，无需 .pth）。configure 会自动下载 Intel IPP，构建约 6 分钟（16 核 --parallel $(nproc)）。
<!-- /oe-app-note:auto -->
