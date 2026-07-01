# 修复摘要

## 修复的问题
无需修改源代码。CI 失败为 infra-error（基础设施错误），根因是 CI 管道中的 eulerpublisher 工具错误地将仓库根目录的文档文件（`README.md`、`README.en.md`）纳入了 appstore 镜像发布规范检查，与 PR 变更内容无关。

## 修改的文件
无

## 修复逻辑
CI 失败分析报告明确指出失败类型为 `infra-error`，PR #2790 仅涉及 README 文档的内容更新，这些根目录文档文件不属于任何应用镜像构建目录，不应通过 appstore 镜像发布路径校验。问题需要由 CI 运维在 trigger job 或 eulerpublisher 工具层面修复（排除根目录文档文件或修正路径归一化逻辑），而非在 `README.md`/`README.en.md` 中进行任何代码修改。

## 潜在风险
无