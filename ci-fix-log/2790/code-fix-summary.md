# 修复摘要

## 修复的问题
无需代码修改 — CI 失败为基础设施错误（infra-error）。PR 仅更新了 `README.md` 和 `README.en.md` 中的文档内容，但 CI 流水线的 appstore 发布规范校验工具（`update.py`）错误地将文档文件纳入应用镜像路径校验，导致路径格式不匹配而失败。

## 修改的文件
无（infra-error，无需修改 PR 代码）

## 修复逻辑
分析报告明确结论为 infra-error：CI 的 `eulerpublisher/update/container/app/update.py` 对所有 PR diff 中的文件执行 appstore 路径校验，未区分"纯文档 PR"与"应用镜像 PR"。校验工具要求文件路径符合 `{image-version}/{os-version}/` 格式，而 README 文件位于仓库根目录，必然不满足此要求。

该问题需要修改 CI 配置/校验逻辑（在 trigger 或 `update.py` 中增加对根目录文档文件的过滤/白名单），而非修改 PR 中的 README 内容。由于规范约束仅允许修改 PR 变更文件（`README.en.md`、`README.md`），而问题根源在 CI 基础设施代码中，本次不改动任何代码。

## 潜在风险
无（未做任何代码修改）