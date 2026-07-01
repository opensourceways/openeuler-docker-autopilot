# CI 失败分析报告

## 基本信息
- PR: #2790 — update readme.md
- 失败类型: infra-error
- 置信度: 高
- 知识库匹配: 新模式
- 新模式标题: 根级文件误触appstore校验
- 新模式症状关键词: Path Error, The expected path should be, README, appstore, update.py

## 根因分析

### 直接错误
```
2026-06-29 15:21:37,042-...INFO: Difference: [
    "README.en.md",
    "README.md"
]
2026-06-29 15:21:41,552-...ERROR: There are some specification errors for releasing on appstore in this PR, please check as above.
+--------------+-----------------------------------------------------+--------------+
| Check Items  |                     Description                     | Check Result |
+--------------+-----------------------------------------------------+--------------+
| README.en.md | [Path Error] The expected path should be /README.md |   FAILURE    |
|  README.md   | [Path Error] The expected path should be /README.md |   FAILURE    |
+--------------+-----------------------------------------------------+--------------+
```

### 根因定位
- 失败位置: `eulerpublisher/update/container/app/update.py:273`
- 失败原因: CI 的 appstore 发布规范校验工具 (`update.py`) 对 PR 中所有变更文件执行路径校验，根级项目文档 `README.en.md` 和 `README.md` 作为合法的项目级文档，不在 appstore 镜像目录路径规范范围内（期望结构为 `{image-version}/{os-version}/README.md`），被误判为路径错误。

### 与 PR 变更的关联
PR 变更仅修改仓库根目录下的 `README.en.md` 和 `README.md`，更新了基础镜像可用 Tags 列表（新增 24.03-lts-sp3、25.09 等条目并将 24.03-lts-sp2 的链接从 SP1 修正为 SP2）。这些改动是合法的项目文档维护，不涉及任何应用镜像的 Dockerfile 或元数据文件。CI 的 appstore 路径校验机制未对根级项目文件做排除处理，导致误报。

## 修复方向

### 方向 1（置信度: 高）
CI 校验工具 `update.py` 需增加对仓库根级文件（如根级 `README.md`、`README.en.md`、`LICENSE` 等）的豁免逻辑，在识别到根级项目文档时不执行 appstore 路径校验。此为 CI 基础设施层面的改进，不涉及 PR 代码修改。

### 方向 2（置信度: 低）
若 CI 工具短期内无法修改，PR 可考虑仅提交 `README.md`（不含 `README.en.md`），或确认 CI 是否对单一文件名有不同处理逻辑。但此方向仅为临时规避，不解决根本问题。

## 需要进一步确认的点
- `update.py` 中 appstore 路径校验逻辑的具体实现（当前仅能通过日志行号 222、273、356 推断其流程），需确认是否有文件豁免白名单或过滤机制。
- 确认该 CI job 的历史运行记录：此前是否曾有过仅修改根级 README 的 PR 通过该检查。
