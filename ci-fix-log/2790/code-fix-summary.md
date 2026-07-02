# 修复摘要

## 修复的问题
无需代码修改。CI 失败属于基础设施错误 (infra-error)：PR #2790 为纯文档更新（仅修改根目录 `README.md` 和 `README.en.md` 中的 Tags 链接），但 CI 管线错误地将其路由到了 appstore 发布预检 job，导致路径校验将两个 README 文件标记为 `[Path Error]`。

## 修改的文件
无

## 修复逻辑
此 PR 为纯文档变更，不涉及任何镜像 Dockerfile 或应用相关代码。CI 失败的根因是 trigger 层将纯文档 PR 路由到了镜像构建/校验 job（appstore 预检），而非文档专用校验流程。这属于 CI 管线编排层面的问题（trigger 分流逻辑），不在 PR 变更文件范围内，也不应由源代码修复来解决。

需要在 CI 层面确认：trigger job 是否缺少根据 diff 文件类型/路径分流不同 job 的逻辑——当 PR 仅包含根目录文档变更时，应跳过 appstore 预检 job。

## 潜在风险
无