# CI 失败分析报告

## 基本信息
- PR: #2790 — update readme.md
- 失败类型: infra-error
- 置信度: 高
- 知识库匹配: 模式11
- 新模式标题: (不适用)
- 新模式症状关键词: (不适用)

## 根因分析

### 直接错误
```
2026-06-29 15:21:41,552-.../eulerpublisher/update/container/app/update.py[line:273]-ERROR: There are some specification errors for releasing on appstore in this PR, please check as above.
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
- 失败原因: CI 的 appstore 发布规范预检（路径校验）认为 PR 变更的根目录 `README.md` 和 `README.en.md` 不符合预期的文件路径规范，两个文件均被标记为 `[Path Error]`。此 PR 为纯文档更新（仅修改 Tags 链接），不涉及任何镜像 Dockerfile 或应用相关代码，但 CI 管线的 appstore 预检步骤仍然对它执行了路径校验并判定失败。

### 与 PR 变更的关联
PR #2790 的改动仅限于 `README.md` 和 `README.en.md` 中的 Tags 版本链接更新（将 `24.03-lts-sp2` → `24.03-lts-sp3`，并新增 `25.09`、`24.03-lts-sp2` 条目），变更文件全部位于仓库根目录。这些文件不属于任何镜像子目录（`AI/`、`Bigdata/` 等），也非 appstore 发布所需的镜像元数据文件，因此被 CI appstore 路径校验规则拒绝。

## 修复方向

### 方向 1（置信度: 中）
根目录的 `README.md` / `README.en.md` 不应通过需要 appstore 发布预检的 CI job 进行验证。此 PR 为纯文档更新，应走独立的文档校验流程而非镜像发布流程。从 CI 编排层面看，可能是 trigger job 将此类纯文档 PR 路由到了镜像构建/校验 job 而非文档专用 job，需确认 CI trigger 是否有针对纯文档变更的分流逻辑。

### 方向 2（置信度: 低）
如果 CI 规范确实要求根目录 README 的修改也需通过 appstore 预检，则需要更新 `eulerpublisher/update/container/app/update.py` 中的路径白名单规则，将 `/README.md` 和 `/README.en.md` 加入合法路径列表。

## 需要进一步确认的点
- 此 PR 的 CI trigger 是否将纯文档变更路由到了 appstore 预检 job（mirror job），而非直接走文档校验流程。需确认 trigger 层是否有根据 diff 文件类型/路径分流不同 job 的逻辑。
- `eulerpublisher/update/container/app/update.py` 中的路径校验规则具体是怎样的——是否白名单模式？根目录 README 变更是否预期被提交到此 job 进行校验？
