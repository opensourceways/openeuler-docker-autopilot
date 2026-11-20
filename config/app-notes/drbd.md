---
app: drbd
---
# drbd 升级注意点

## 构建方式
- 镜像的核心产物是 **DRBD 内核模块**，来自 `https://github.com/LINBIT/drbd`
  的 `v${VERSION}`（清单里是 9.3.5）；
- 需要 `kernel-devel` / `kernel-headers` / `elfutils-libelf-devel`，
  按 `make -j` + `make install` 构建安装。

## 已知坑
- 仓库现有的 `9.31.0` 实际构建的是 **drbd-utils**（用户态工具，另一条版本线），
  没有 v9.3.5 tag；清单用 `allow_downgrade: true` 跳过了降级保护。
- 不要只构建 LINBIT/drbd-utils 就算完成；如还需要 `drbdadm`，可以额外安装
  drbd-utils，但内核模块必须来自 `LINBIT/drbd` 的固定 tag。
- 容器内没有运行内核头对应版本的模块树时，`make` 会在 KDIR 上失败；
  KDIR 指向容器内 kernel-devel 的源码目录。

## 验证
- `modinfo drbd` 能读出模块；`drbdadm --version`；tests/test.sh 存在时以其为准。
