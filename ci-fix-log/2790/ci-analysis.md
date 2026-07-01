# CI 失败分析报告

## 基本信息
- PR: #2790 — update readme.md
- 失败类型: lint-error
- 置信度: 高
- 知识库匹配: 模式11
- 新模式标题: (不适用)
- 新模式症状关键词: (不适用)

## 根因分析

### 直接错误
```
2026-06-29 15:21:41,552-/home/jenkins/agent-working-dir/workspace/multiarch/***/x86-64/***-docker-images/eulerpublisher/update/container/app/update.py[line:273]-ERROR: There are some specification errors for releasing on appstore in this PR, please check as above.
+--------------+-----------------------------------------------------+--------------+
| Check Items  |                     Description                     | Check Result |
+--------------+-----------------------------------------------------+--------------+
| README.en.md | [Path Error] The expected path should be /README.md |   FAILURE    |
|  README.md   | [Path Error] The expected path should be /README.md |   FAILURE    |
+--------------+-----------------------------------------------------+--------------+
```

### 根因定位
- 失败位置: `eulerpublisher/update/container/app/update.py:273`
- 失败原因: PR 修改了仓库根目录的 `README.md` 和 `README.en.md`（项目级文档），CI 的 appstore 发布规范检查工具 (`update.py`) 将所有变更文件纳入应用镜像路径校验，这两个根级 README 文件不满足 appstore 要求的 `{category}/{app}/{version}/{os-version}/` 层级路径规范，触发 `[Path Error]`。

### 与 PR 变更的关联
PR 仅修改了仓库根目录 `README.md` 和 `README.en.md` 中的镜像 Tags 列表（新增 24.03-lts-sp3、25.09 条目，调整链接），属于纯文档内容更新。这些文件不是任何应用镜像的 Dockerfile 或元数据文件，不存在于 appstore 要求的目录路径下。CI 工具错误地将根级文档纳入 appstore 路径校验范围，导致校验失败。**该失败与 PR 内容变更无关，任何修改根级 README 文件的 PR 都会触发同样的问题。**

## 修复方向

### 方向 1（置信度: 高）
CI 的 appstore 校验工具 (`eulerpublisher/update/container/app/update.py`) 需要增加文件过滤逻辑：在检测到被修改文件后，在校验路径前，排除仓库根目录下的 `README.md`、`README.en.md` 等非应用镜像文档文件，不将其纳入 appstore 发布规范检查。或者在校验逻辑中增加对根级文件的路径豁免。

### 方向 2（置信度: 低）
如果 CI 无法在短期内修改，PR 可考虑拆分：将 README 变更与带有应用镜像变更的 PR 分开提交，仅 README 变更的 PR 通过其他方式（如管理员手动合并）绕过 appstore 校验。

## 需要进一步确认的点
- 确认 CI 的 `update.py` 中是否有文件过滤白名单机制，以及是否可以通过配置跳过根级文件的 appstore 校验。
- 确认这是否是本仓库首次出现"仅修改根 README 文件的 PR 触发 appstore 校验失败"的问题，以判断是回归还是长期存在的缺陷。
