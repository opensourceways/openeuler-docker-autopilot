---
app: druid
---
# druid 升级注意点

## 构建方式
- 多阶段：builder 用 wget 下载 apache-druid 发行包，运行阶段基于 openEuler + Java。
- 版本号是 `39.0.0` 这类纯数字，下载 URL 必须与 apache 归档的实际目录一致。

## 已知坑
- 发行包在 archive.apache.org / dlcdn.apache.org 的路径会随版本变化，先确认
  `apache-druid-${VERSION}-bin.tar.gz` 是否存在，再替换下载地址。
- 运行阶段要保留 Java 版本与 `JAVA_HOME`，不要在升级时降级 JDK。

## 验证
- 解压目录与启动脚本存在；tests/test.sh 存在时以其为准。
