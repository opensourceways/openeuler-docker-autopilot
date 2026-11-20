---
app: fvcom
---
# fvcom 升级注意点

## 构建方式
- 多阶段 CMake 构建 Fortran 求解器；依赖 openmpi、gfortran、netcdf 等。

## 已知坑
- 4.4.x 不同版本对 MPI / netcdf 的 CMake 选项可能变化；以固定 tag 的
  CMakeLists 与 README 为准。
- 旧文件里用 `yum`，新环境优先用 `dnf`，但不要新增全量 update。
- 运行阶段只需要可执行文件与共享库，复制后确认 `LD_LIBRARY_PATH`。

## 验证
- `fvcom --help`；tests/test.sh 存在时以其为准。
