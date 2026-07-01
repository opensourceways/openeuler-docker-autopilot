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
2026-06-29 15:21:37,042-...-INFO: Difference: [
    "README.en.md",
    "README.md"
]
2026-06-29 15:21:41,552-...-ERROR: There are some specification errors for releasing on appstore in this PR, please check as above.
+--------------+-----------------------------------------------------+--------------+
| Check Items  |                     Description                     | Check Result |
+--------------+-----------------------------------------------------+--------------+
| README.en.md | [Path Error] The expected path should be /README.md |   FAILURE    |
|  README.md   | [Path Error] The expected path should be /README.md |   FAILURE    |
+--------------+-----------------------------------------------------+--------------+
```

### 根因定位
- 失败位置: `eulerpublisher/update/container/app/update.py:273`
- 失败原因: CI 的 appstore 发布规范预检工具 (`update.py`) 扫描了 PR 中所有变更文件（`README.md` 和 `README.en.md`），对两个根级项目文档文件也执行了应用镜像路径校验。这两个文件位于仓库根目录，而非任何应用镜像子目录（如 `AI/xxx/`、`Bigdata/xxx/`），不符合 appstore 对应用镜像 README 的路径预期，因此被判定为 `[Path Error]`。该失败是 CI 检查工具覆盖范围过宽导致的误报，与 PR 改动内容本身无关。

### 与 PR 变更的关联
**与 PR 改动无关。** PR #2790 仅修改了仓库根目录下的 `README.md` 和 `README.en.md`，更新了基础镜像支持的 Tags 列表（新增 24.03-lts-sp3、25.09 等条目）。这些是纯文档变更，不涉及任何应用镜像的 Dockerfile 或元数据文件。CI 的 appstore 预检工具对根级文档文件执行了本应只针对应用镜像目录的路径校验，导致误报。PR 变更内容本身合法有效。

## 修复方向

### 方向 1（置信度: 中）
CI 的 appstore 预检工具 (`eulerpublisher/update/container/app/update.py`) 的文件扫描逻辑应排除仓库根目录下的项目文档文件（如根级 `README.md`、`README.en.md`、`CONTRIBUTING.md` 等），或仅在变更涉及应用镜像子目录时触发路径校验。需检查 `update.py` 中 `check` 或 `Difference` 相关逻辑，添加根级文档文件的白名单过滤。

### 方向 2（置信度: 低）
如果 CI 预检工具的意图是验证 PR 中提到的应用镜像名称是否与仓库目录一致（即解析 README 中的 Tag 链接，检查对应版本目录是否存在），则此次新增的 `24.03-lts-sp3` 和 `25.09` 标签需要仓库中存在对应的应用镜像目录结构。但日志中错误为 `[Path Error]` 而非版本缺失错误，此方向可能性较低。

## 需要进一步确认的点
1. 读取 `eulerpublisher/update/container/app/update.py` 第 222 行和第 273 行附近代码，确认 `check` 函数的文件遍历范围和路径校验逻辑。
2. 确认 CI 预检工具的预期行为：是否对所有变更文件执行路径校验，还是仅对特定目录模式下的文件执行。
3. 确认根级 `README.md` 和 `README.en.md` 是否在 CI 工具的预期白名单中（如果存在白名单机制）。

## 修复验证要求
若修复涉及修改 `eulerpublisher/update/container/app/update.py` 中的路径扫描逻辑，code-fixer 必须在提交前确认：修改后的脚本对"仅包含根级文档变更"的 PR 不再报 `[Path Error]`，同时对正常应用镜像 PR 的路径校验功能不受影响。
