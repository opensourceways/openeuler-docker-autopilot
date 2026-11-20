---
app: maven
---
# maven 升级注意点

## 构建方式
- 现有镜像通过 `yum install -y maven` 安装发行版包，再加 `entrypoint.sh`；
  镜像里的版本由 openEuler 仓库决定，**不受 ARG 控制**。

## 已知坑
- 想真正固定到清单版本（如 3.10.1）时，需要改成从 apache 归档下载
  `apache-maven-${VERSION}-bin.tar.gz` 并解压，而不是继续 `yum install maven`；
  否则目录名/`meta.yml` 声明 3.10.1，镜像里却还是仓库自带版本。
- 旧文件有 `yum update -y`，生成时不要新增全量升级。
- `entrypoint.sh` 是应用级文件，升级时保持原样复制。

## 验证
- `mvn -version` 的输出必须与目录版本一致；tests/test.sh 存在时以其为准。
