# CI 失败分析报告

## 基本信息
- PR: #2790 — update readme.md
- 失败类型: infra-error
- 置信度: 中
- 知识库匹配: 新模式
- 新模式标题: 根目录文件触发路径校验
- 新模式症状关键词: Path Error, The expected path should be, appstore, README.md, update.py

## 根因分析

### 直接错误
```
2026-06-29 15:21:41,552-ERROR: There are some specification errors for releasing on appstore in this PR, please check as above.
+--------------+-----------------------------------------------------+--------------+
| Check Items  |                     Description                     | Check Result |
+--------------+-----------------------------------------------------+--------------+
| README.en.md | [Path Error] The expected path should be /README.md |   FAILURE    |
|  README.md   | [Path Error] The expected path should be /README.md |   FAILURE    |
+--------------+-----------------------------------------------------+--------------+
```

### 根因定位
- 失败位置: `eulerpublisher/update/container/app/update.py:273`
- 失败原因: CI 的 appstore 发布规范检查器（eulerpublisher 工具）扫描 PR 变更文件时，对仓库根目录下的 `README.md` 和 `README.en.md` 执行了路径校验，这些根目录文档文件不满足 appstore 镜像目录的路径规范（期望格式为 `{image-version}/{os-version}/...`），导致两个文件均报 `[Path Error]`。此外，`README.md` 本身路径（无前导 `/`）与预期路径（`/README.md`，带前导 `/`）之间存在路径归一化不一致，即使路径语义相同也判定失败。

### 与 PR 变更的关联
PR 变更仅涉及仓库根目录 `README.md` 和 `README.en.md` 的内容更新（新增 24.03-lts-sp3、25.09、24.03-lts-sp2 标签信息），不涉及任何镜像构建目录下的 Dockerfile 或配置文件。CI 失败与 PR 的具体改动内容无关，根因在于 CI 管道将根目录下的文档文件纳入了 appstore 镜像发布规范检查范围，而该检查器的路径验证逻辑不适合验证根目录文件。

## 修复方向

### 方向 1（置信度: 中）
CI 流水线配置（trigger job 或 eulerpublisher 工具调用层）在检测到 PR 仅修改根目录文档文件（`README.md`、`README.en.md`、`README.*.md` 等）时，应跳过 appstore 发布规范检查（`update.py` 路径校验），因为根目录文档不属于任何应用镜像构建目录，无需通过镜像发布规范验证。

### 方向 2（置信度: 低）
如果 CI 设计意图是对所有 PR 文件均做路径校验，则 eulerpublisher 工具中的路径比较逻辑需要修正前导 `/` 的归一化问题（`README.md` vs `/README.md` 应视为等价），同时需为根目录文档文件（如 `README.md`、`README.en.md`）配置合法的预期路径白名单。

## 需要进一步确认的点
1. CI trigger job 层是否有文件过滤逻辑——当前是否按文件路径过滤了 appstore 检查的范围，若已过滤则需排查过滤规则为何未排除根目录 README 文件。
2. `eulerpublisher/update/container/app/update.py` 中路径校验的具体实现（特别是前导 `/` 的来源及比较方式），以确定路径归一化不一致是否为导致 `README.md` 也失败的直接原因。
3. 确认同类 PR（仅修改根目录文档的 PR，如之前的 README 变更）是否同样会触发此检查失败，以判断这是本次 PR 特有的偶发现象还是持续性问题。
