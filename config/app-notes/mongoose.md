---
app: mongoose
---
# mongoose 升级注意点

## 构建方式
- 多阶段：下载 mongoose 单文件合并版（`mongoose.c` / `mongoose.h`），
  运行阶段基于 openEuler 直接提供头文件与库。

## 已知坑
- 版本号是 `7.24` 两段格式，下载 URL 里的 tag 与目录名必须一致。
- 旧文件用 `yum`；升级时优先沿用旧文件命令，不要新增 `yum update`。
- 单文件库没有安装步骤，确认 `COPY` 的目标路径与头文件位置没变。

## 验证
- 头文件/库存在，能编译最小示例；tests/test.sh 存在时以其为准。
