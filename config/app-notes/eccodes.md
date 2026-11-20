---
app: eccodes
---
# eccodes 升级注意点

## 构建方式
- 多阶段：builder 用 CMake 编译，运行阶段复制安装产物并设置环境。

## 已知坑
- 2.x 不同小版本的 CMake 选项/依赖可能有增减（如 gfortran、netcdf、jpeg）；
  升级时以该 tag 下的 CMakeLists 为准，不要机械沿用旧选项。
- 安装前缀与运行阶段的环境变量（`ECCODES_DIR`、`LD_LIBRARY_PATH`）要一致。

## 验证
- `grib_ls` / `codes_info` 可用；tests/test.sh 存在时以其为准。
