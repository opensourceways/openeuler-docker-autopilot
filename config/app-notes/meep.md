<!-- oe-app-note:auto:v1.36.0/24.03-lts-sp4 -->
## 自动沉淀：v1.36.0 / 24.03-lts-sp4

本次新发现（可复用）：

- conda-forge 的 `pymeep` 版本滞后于上游 release（当前止于 1.35.1）；新版本应优先走 PyPI 的 `pymeep` manylinux wheel，它同时提供 x86_64 与 aarch64 预编译产物（cp310–cp313）。
- `pymeep` 的依赖 `mpich` 也是 PyPI wheel，安装后把 `libmpi.so.12` 放到 `/usr/local/lib`；必须 `ENV LD_LIBRARY_PATH=/usr/local/lib`，否则 `import meep` 报 `cannot load MPI library`。
- PyPI 的 `pymeep` wheel 只含 Python 模块与 `_meep.so`，**没有** `meep` 命令行二进制；功能测试需依赖 `python3 -c "import meep; print(meep.__version__)"` 取版本（输出含 MPI banner，但版本号仍可被解析）。
<!-- /oe-app-note:auto -->
