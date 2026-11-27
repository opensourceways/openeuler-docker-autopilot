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

<!-- oe-app-note:auto:20261113/24.03-lts-sp4 -->
## 自动沉淀：20261113 / 24.03-lts-sp4

GitHub 固定 tag 归档（https://github.com/<org>/<repo>/archive/refs/tags/<tag>.tar.gz）内容稳定，可预先计算 sha256 后用 `echo '<sha>  <file>' | sha256sum -c -` 做内容校验，弥补无 L1 证据包时 tag 重打/传输损坏的可复现性风险；openfoam 双仓归档 sha256：OpenFOAM-dev 20261113 = a75c376b000079f51c511564cf0e85e7a17017565a2aed6ec90f31a596bf5d74，ThirdParty-dev version-14 = 17fbcb55caa161c6c8e327eede8ca79c1b367ee65470b4697ccfddb0c4c76bd9。
<!-- /oe-app-note:auto -->
