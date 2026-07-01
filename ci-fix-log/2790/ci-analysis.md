# CI 失败分析报告

## 基本信息
- PR: #2790 — update readme.md
- 失败类型: infra-error
- 置信度: 中
- 知识库匹配: 新模式
- 新模式标题: 文档类PR误触发appstore校验
- 新模式症状关键词: Path Error, expected path, README, appstore, update.py

## 根因分析

### 直接错误
```
| README.en.md | [Path Error] The expected path should be /README.md |   FAILURE    |
|  README.md   | [Path Error] The expected path should be /README.md |   FAILURE    |
```

```
2026-06-29 15:21:37,042-.../eulerpublisher/update/container/app/update.py[line:356]-INFO: Difference: [
    "README.en.md",
    "README.md"
]
2026-06-29 15:21:41,552-.../eulerpublisher/update/container/app/update.py[line:273]-ERROR: There are some specification errors for releasing on appstore in this PR, please check as above.
```

### 根因定位
- 失败位置: `eulerpublisher/update/container/app/update.py:273`
- 失败原因: CI 的 appstore 发布规范校验工具（`update.py`）对所有 PR diff 中出现的文件执行路径校验，PR 仅修改了根目录下的 `README.md` 和 `README.en.md`（文档更新），校验工具将这些文件识别为待发布的应用镜像文件，但其路径不符合 appstore 要求的 `{image-version}/{os-version}/` 目录结构，因此被标记为 FAILURE。

### 与 PR 变更的关联
PR 仅更新了 `README.md` 和 `README.en.md` 中的镜像 Tags 列表（添加 `24.03-lts-sp3`、`25.09`、`24.03-lts-sp2` 等新版本链接），未涉及任何 Dockerfile、应用镜像、meta.yml 或 image-info.yml 的修改。该失败并非 PR 改动本身有误，而是 CI 流水线的校验逻辑未区分"纯文档 PR"与"应用镜像 PR"，将文档文件纳入了 appstore 路径校验范围。

## 修复方向

### 方向 1（置信度: 中）
CI 配置/校验逻辑需要增加过滤：当 PR diff 中仅包含根目录 `README.md` 或 `README.en.md`（及其他非应用镜像目录文件）时，跳过 `update.py` 的 appstore 路径校验步骤。这与历史案例中 `.claude/agents/README.md` 路径不符合规范被拒（模式11）属于同类 CI 校验逻辑过于严格的问题。

### 方向 2（置信度: 低）
如果 CI 流水线不对单个 PR 做 diff 过滤，而是依赖 PR 触发时的元数据来判断是否需要运行 appstore 校验，则需要检查 trigger job 层是否有机制根据 PR 内容筛选下游 job。当前日志显示 `multiarch/openeuler/trigger/openeuler-docker-images` 无条件触发了 `x86-64` 构建 job，可能是 trigger 层缺少过滤。

## 需要进一步确认的点
1. 确认 `eulerpublisher/update/container/app/update.py` 的路径校验逻辑是否可配置白名单忽略根目录文档文件
2. 确认 trigger job（`multiarch/openeuler/trigger/openeuler-docker-images`）是否支持根据 PR diff 内容决定是否触发下游 x86-64/aarch64 构建 job
3. 该 PR 仅修改 README 文档，原本是否应被视为"无需 CI"的纯文档变更——如果仓库有此策略，建议在 trigger 层实现
