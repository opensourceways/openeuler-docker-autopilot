# 修复摘要

## 修复的问题
无需代码修改。CI 失败为基础设施误报：appstore 校验工具 (`update.py`) 对根级项目文档 (`README.md`, `README.en.md`) 执行了不应执行的路径校验。

## 修改的文件
无

## 修复逻辑
根据 CI 失败分析报告，本次失败类型为 **infra-error**。PR #2790 仅修改了仓库根级 `README.en.md` 和 `README.md`，内容为更新基础镜像可用 Tags 列表，属于合法的项目文档维护，不涉及任何应用镜像的 Dockerfile 或元数据文件。

CI 的 appstore 发布规范校验工具 (`eulerpublisher/update/container/app/update.py:273`) 对所有变更文件执行路径校验，期望路径格式为 `{image-version}/{os-version}/README.md`，而根级项目文档不在此规范范围内，被误判为路径错误。这是 CI 基础设施层面的缺陷，需由 CI 工具本身增加对根级文件的豁免逻辑来解决，不属于 PR 代码层面可修复的问题。

## 潜在风险
无