# 修复摘要

## 修复的问题
无需代码修改。CI 失败类型为 **infra-error**，是 CI 基础设施（appstore 预检工具 `eulerpublisher/update/container/app/update.py`）的误报，与 PR 改动内容无关。

## 修改的文件
- 无

## 修复逻辑
PR #2790 仅修改了仓库根目录下的 `README.md` 和 `README.en.md`，更新了基础镜像支持的 Tags 列表（新增 24.03-lts-sp3、25.09 等条目）。CI 的 appstore 预检工具对根级项目文档文件执行了本应只针对应用镜像子目录的路径校验，导致 `[Path Error]` 误报。

根据分析报告判定，此失败为 **infra-error**，根因在 CI 工具的扫描逻辑过于宽泛（`eulerpublisher/update/container/app/update.py:273`），需要 CI 工具侧修正文件过滤逻辑，而非修改 PR 中的源代码。PR 变更内容本身合法有效，无需任何代码修改。

## 潜在风险
无。未对任何源代码做修改，不存在引入新问题的风险。