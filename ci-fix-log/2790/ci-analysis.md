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
2026-06-29 15:21:37,042-INFO: Difference: [
    "README.en.md",
    "README.md"
]
2026-06-29 15:21:41,552-ERROR: There are some specification errors for releasing on appstore in this PR, please check as above.
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
- 失败原因: PR 仅修改了仓库根目录下的 `README.md` 和 `README.en.md`（仓库级文档），但 CI 的 appstore 发布规范校验器（`update.py`）将这些文件当作应用镜像提交进行路径校验。根级 README 文件不是应用镜像的最小目录单元（不在 `Bigdata/`、`AI/` 等场景目录内），不遵循 appstore 镜像发布路径规范，因此被拒绝。

### 与 PR 变更的关联
PR 的变更仅涉及 README 文档中基础镜像 Tags 列表的内容更新（新增 `24.03-lts-sp3`、`25.09`、`24.03-lts-sp2` 等条目），不涉及任何 Dockerfile 或应用镜像构建文件。该变更本身是合法的文档维护操作，但触发了 CI appstore 流水线对变更文件的全面校验，而根级 README 文件不属于 appstore 镜像发布范畴，导致路径校验误报失败。

## 修复方向

### 方向 1（置信度: 中）
CI appstore 校验器（`update.py`）应过滤掉仓库根级文件（如 `/README.md`、`/README.en.md`），仅对位于应用镜像场景目录（`Bigdata/`、`AI/`、`Database/`、`Cloud/`、`Storage/`、`HPC/`、`Distroless/`、`Others/`、`Base/`）内的变更文件执行 appstore 发布规范校验。这属于 CI 流水线配置/校验逻辑调整，与 PR 代码无关。

### 方向 2（可选）
如果 repo 的 CI 策略要求所有 PR 都必须通过 appstore 校验，则该 PR 需要将文档变更拆分为独立的文档 PR 并走不同的 CI 流水线，或确认仓库是否有跳过 appstore 校验的机制（如 PR 标签或特定分支规则）。

## 需要进一步确认的点
1. 确认 `update.py` 中文件路径过滤逻辑的实现方式——是否有白名单/黑名单机制，以及根级文件是否应被纳入或排除。
2. 确认 CI 流水线策略：文档类 PR（仅修改 README、LICENSE 等非镜像构建文件）是否应该绕过 appstore 校验流程。
3. 参考历史案例 PR #2512（模式11），确认是否有通用的"非镜像文件跳过 appstore 校验"的修复已在其他 PR 中落地。
