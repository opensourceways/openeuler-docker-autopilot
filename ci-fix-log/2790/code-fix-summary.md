# 修复摘要

## 修复的问题
无需代码修改。CI 失败是由 `eulerpublisher/update/container/app/update.py` 工具缺陷导致：该工具错误地将仓库根目录的 `README.md` 和 `README.en.md` 纳入 appstore 发布路径校验，触发了 `[Path Error]`。这是 CI 基础设施/工具层面的 bug，与 PR 内容无关。

## 修改的文件
无（PR 修改的 `README.en.md` 和 `README.md` 内容正确，不存在需要修复的代码问题）

## 修复逻辑
CI 分析报告指出，`update.py` 将所有被修改的文件纳入 appstore 路径校验，但根级 README 文件并非应用镜像 Dockerfile 或元数据文件，不应参与 appstore 路径规范检查。修复方向应为在 `update.py` 中增加文件过滤逻辑，排除根级 README 等非应用镜像文档文件。但该文件 (`eulerpublisher/update/container/app/update.py`) 不在本次 PR 的变更文件列表中，受"仅修改 `pr.changed_files` 列表内文件"的约束，无法进行修复。根级 README 文档的内容本身没有问题，属于正常的镜像 Tags 列表更新。

## 潜在风险
无。README 文件内容变更合法，不会引入任何功能风险。建议由 CI 管理员在 `update.py` 中增加对根级 README 文件的路径豁免逻辑，以彻底解决此类问题。