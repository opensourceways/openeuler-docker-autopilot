---
app: openfoam
---
# openfoam 升级注意点

## 构建方式
- 从 sourceforge `v${VERSION}` 目录下载 `OpenFOAM-v${VERSION}.tgz` 与
  `ThirdParty-v${VERSION}.tgz`，`source etc/bashrc` 后 `./Allwmake -j -k -s -q`。

## 已知坑
- 版本号是日期式（`20261113`），sourceforge 的目录层级与文件名可能随发布方式变化；
  先确认两个 tarball 都存在。
- `ThirdParty` 包也带版本号，两个下载地址必须同时更新，少一个会构建失败。
- `Allwmake` 失败会被 `-k` 继续，最后才暴露；容器重放时要看每条 `wmake` 的错误。
- 运行阶段通过 `etc/bashrc` 设置环境，ENTRYPOINT 不能丢。

## 验证
- `foamVersion` / `simpleFoam -help`；tests/test.sh 存在时以其为准。
