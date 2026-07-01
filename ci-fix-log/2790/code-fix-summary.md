# 修复摘要

## 修复的问题
无需代码修改 — 属于 CI 基础设施误报（infra-error）。

## 修改的文件
无。PR 变更的 `README.md` 和 `README.en.md` 内容合法（文档维护，更新基础镜像 Tag 列表），不存在代码缺陷。

## 修复逻辑
CI 失败分析报告将此问题归类为 **infra-error**。CI 的 appstore 发布规范校验器（`eulerpublisher/update/container/app/update.py:273`）将仓库根目录下的 `README.md` 和 `README.en.md` 当作应用镜像构建文件进行路径校验，而这两个文件是仓库级文档，不属于任何应用镜像场景目录（`Bigdata/`、`AI/`、`Database/` 等），不适用 appstore 镜像发布路径规范。

修复方向应在 CI 基础设施层面：校验器需要增加对仓库根级文件的过滤逻辑，或文档类 PR 应有机制绕过 appstore 校验流程。这些修改涉及 CI 流水线配置/校验脚本（不在 `pr.changed_files` 范围内），不属于本次代码修复范畴。

根据任务规范，infra-error 不应对源代码进行强行修改。

## 潜在风险
无（未进行代码变更）。