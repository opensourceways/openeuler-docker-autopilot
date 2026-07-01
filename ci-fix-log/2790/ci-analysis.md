# CI 失败分析报告

## 基本信息
- PR: #2790 — update readme.md
- 失败类型: infra-error
- 置信度: 中
- 知识库匹配: 模式11
- 新模式标题: (不适用)
- 新模式症状关键词: (不适用)

## 根因分析

### 直接错误
```
2026-06-29 15:21:41,552 - ERROR: There are some specification errors for releasing on appstore in this PR, please check as above.
+--------------+-----------------------------------------------------+--------------+
| Check Items  |                     Description                     | Check Result |
+--------------+-----------------------------------------------------+--------------+
| README.en.md | [Path Error] The expected path should be /README.md |   FAILURE    |
|  README.md   | [Path Error] The expected path should be /README.md |   FAILURE    |
+--------------+-----------------------------------------------------+--------------+
Build step 'Execute shell' marked build as failure
Finished: FAILURE
```

### 根因定位
- 失败位置: `eulerpublisher/update/container/app/update.py:273`
- 失败原因: CI 的 appstore 发布规范预检工具将 PR 中修改的仓库根目录 `README.md` 和 `README.en.md` 纳入了镜像路径校验范围，这些根级文档文件不属于任何镜像目录结构，不适用 appstore 镜像路径规范，但 CI 校验工具未对其做豁免处理，导致路径校验失败。

### 与 PR 变更的关联
PR 仅修改了仓库根目录的两个 README 文件（`README.md` 和 `README.en.md`），更新了基础镜像 Tags 列表中的链接（24.03-lts-sp2 → 24.03-lts-sp3，新增 25.09、24.03-lts-sp2 条目）。这些是纯文档更新，不涉及任何镜像的 Dockerfile 或元数据。CI 失败是因为 appstore 预检工具对所有变更文件无差别执行路径格式校验，将根级文档文件错误地视为镜像发布相关文件。**该失败不是 PR 改动引入的错误**。

## 修复方向

### 方向 1（置信度: 中）
CI 流水线的 appstore 检查步骤应在执行路径校验前过滤掉仓库根目录的非镜像文件（如根级 `README.md`、`README.en.md`、`CONTRIBUTING.md` 等），仅对位于 `{category}/{image}/...` 或 `Base/openeuler/...` 目录结构下的文件执行路径格式校验。需要在 `update.py` 或 CI 脚本中增加对根级文件的豁免逻辑。

### 方向 2（置信度: 低）
若 CI 工具不支持在 checker 侧豁免根级文件，PR 作者可将根级 README 的修改拆分为独立 PR 提交到不触发 appstore 检查的分支，或在 CI 配置中将根级 README 文件加入跳过列表。

## 需要进一步确认的点
1. `update.py` 中的路径校验逻辑是否包含对仓库根目录文件的过滤/豁免规则，如果没有，应该在哪里添加
2. 是否有其他仅修改根级文档的 PR 曾通过 CI（验证是否为本次新增的 CI 行为变更）
3. 确认 CI pipeline 配置中 appstore 检查步骤的触发条件是否可以按文件路径过滤
