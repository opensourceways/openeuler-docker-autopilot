<!-- oe-app-note:auto:5.1.0/24.03-lts-sp4 -->
## 自动沉淀：5.1.0 / 24.03-lts-sp4

opencv 目录同时存在 CANN 变体（5.1.0-cann9.1.0-python3.12）与纯源码变体（5.1.0），二者共享 AI/opencv/tests/test.sh；纯源码变体的测试不能硬编码 /usr/local/opencv-cann 或 CANN 断言，应以 /usr/local/bin/opencv_version + cv2.__version__ + cv2.dnn 为准。纯源码构建在 openEuler 24.03-lts-sp4 上依赖 dnf 的 python3-devel 与 python3-numpy（3.11.6 / 1.24.3）即可，cmake 需显式传 PYTHON_INCLUDE_DIR=/usr/include/python3.11、PYTHON_LIBRARY=/usr/lib64/libpython3.11.so；16 核全量 install 约 4~5 分钟。
<!-- /oe-app-note:auto -->
