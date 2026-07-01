# 修复摘要

## 修复的问题
无需代码修改。CI 失败类型为 `infra-error`，是 CI 基础设施的 appstore 发布规范预检工具错误地将仓库根目录的 `README.md` 和 `README.en.md` 纳入了镜像路径校验范围，导致路径格式校验失败。

## 修改的文件
无。PR 仅修改了 `README.md` 和 `README.en.md`，属于纯文档更新，不涉及任何代码缺陷。

## 修复逻辑
CI 失败分析报告明确指出：
- 失败类型为 `infra-error`（CI 基础设施问题）
- 根因是 `eulerpublisher/update/container/app/update.py:273` 中的 appstore 预检工具对所有变更文件无差别执行路径格式校验，未豁免仓库根目录的非镜像文件（如根级 `README.md`、`README.en.md`）
- PR 变更仅涉及 README 文件的基础镜像 Tags 列表链接更新，与镜像发布无关

此问题需要在 CI 流水线的 appstore 检查步骤中增加对根级非镜像文件的豁免逻辑（修改 `update.py` 或 CI 脚本），但该文件不在当前 PR 的变更范围内，且属于 CI 配置层面的修复，不应在本次 PR 的代码修复中处理。

## 潜在风险
无。未对源码进行任何修改。