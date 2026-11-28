<!-- oe-app-note:auto:v1.36.0/24.03-lts-sp4 -->
## 自动沉淀：v1.36.0 / 24.03-lts-sp4

meep 的 pymeep 轮子不安装 `meep` CLI 二进制，版本探测必须依赖 `python3 -c "import meep; print(meep.__version__)"`；且 `import meep` 会触发 MPICH 初始化并向 stdout 打印 `Using MPI version ...` 横幅，`meep.__version__` 输出不含 `v` 前缀。因此版本断言需同时规范化 EXPECTED_VERSION 与上报 token（都去除 v/V 前缀）。
<!-- /oe-app-note:auto -->
