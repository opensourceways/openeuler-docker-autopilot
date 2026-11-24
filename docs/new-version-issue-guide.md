# 自动升级 Issue 提交指导

面向需要发起「应用版本升级」的外部同学。按本文填写 Issue 即可，不需要接触流水线仓库。

相关入口：GitCode → `openeuler/openeuler-docker-images` → Issues → 新建 Issue。

---

## 1. 什么情况提这个 Issue

| 你的诉求 | 是否用本文 |
|---|---|
| 某个软件要升级到新版本（docker 镜像和/或 conda 包） | 是 |
| 某个软件在 openEuler 镜像仓/conda 仓里还没有，想新增 | 否，请提交 `【new-image】` 新建镜像 Issue |
| 只想改 Dockerfile 里的构建参数，不升级版本 | 否，请直接提 PR 或联系维护者 |

自动升级覆盖两个目标仓，**同一个 Issue 会自动判断升级哪里**：

- `openeuler/openeuler-docker-images`：生成/更新 Dockerfile，双架构构建 + 功能测试，提 PR；
- `openeuler/conda-ecopkgs`：在 `packages/<包名>/supported-versions.yml` 登记新版本，提 PR。

两个仓都有该软件时两边都会执行；只有一边有就只执行那一边。

---

## 2. 提交前请确认三件事

1. **软件名**：使用目标仓里的目录名/包名，或看板软件名。
   - 例：`grpc`、`slurm`、`benchmark`、`opencv`。
   - 不要写中文、空格或产品宣传名。
2. **目标版本**：填上游发布版本号，建议与仓库现有目录保持一致（通常不带 `v` 前缀）。
   - 例：`1.85.4`、`2.16.0`、`9.3.5`。
3. **openEuler 版本**：`24.03-lts-sp4`、`22.03-LTS-SP4` 这类写法均可，大小写不敏感。

> 不确定软件名？先在看板或目标仓里搜一下，Issue 标题里的名字必须能对上，否则流水线无法定位。

---

## 3. Issue 标题（必填）

格式固定：

```text
【new-version】upgrade <软件名> to <目标版本> on openEuler <openEuler版本>
```

示例：

```text
【new-version】upgrade grpc to 1.85.4 on openEuler 24.03-lts-sp4
【new-version】upgrade benchmark to 1.11.0 on openEuler 24.03-LTS-SP4
【new-version】upgrade slurm to 26.05.6 on openEuler 24.03-lts-sp4
```

注意：

- `【new-version】` 必须原样保留（中文方括号）；
- `upgrade`、`to`、`on openEuler` 是固定英文关键字；
- 标题里不要加“请”“麻烦”“版本升级”等额外文字；
- 软件名和版本号之间只隔 `to`，前后各一个空格。

---

## 4. Issue 正文（必填：上游证据 JSON）

正文必须粘贴上游看板返回的完整证据 JSON。可直接使用模板 [templates/new-version-issue.md](../templates/new-version-issue.md)，把占位值替换成真实值。流水线会把它原样透传给扫描阶段和生成 Agent，不再自行采集证据。

```json
{
  "schema_version": "1.1",
  "request_id": "req-grpc-1.85.4",
  "software": {
    "name": "grpc",
    "repo_url": "https://github.com/grpc/grpc",
    "raw_category": "rpc",
    "oss_map_id": "oss-grpc"
  },
  "version": {
    "value": "1.85.4",
    "type": "latest_release",
    "display": "v1.85.4"
  },
  "upstream_evidence": {
    "support_level": "L1",
    "computed_by": "kunpeng-evidence",
    "evaluated_at": "2026-11-20T00:00:00Z",
    "evidence": {
      "check_id": "kp.l1.arm_ci",
      "result": "supported",
      "artifact": "grpc-arm64",
      "source_url": "https://ci.example.com/jobs/1",
      "checked_at": "2026-11-20T00:00:00Z",
      "test_depth": "smoke",
      "ci_workflows": [
        {
          "workflow_path": ".github/workflows/ci.yml",
          "workflow_url": "https://github.com/grpc/grpc/blob/<sha>/.github/workflows/ci.yml",
          "test_depth": "smoke"
        }
      ],
      "assessment_id": "assess-grpc"
    }
  },
  "l3_evidence": null,
  "install_candidates": [
    {
      "type": "source",
      "url": "https://github.com/grpc/grpc/archive/v1.85.4.tar.gz",
      "artifact": "grpc-1.85.4.tar.gz",
      "arch": "any"
    }
  ]
}
```

字段约束：

| 字段 | 必填 | 说明 |
|---|---|---|
| `schema_version` | 是 | 如 `1.1` |
| `request_id` | 是 | 幂等键，一次实测一个 |
| `software.name` / `software.repo_url` | 是 | `name` 必须与标题里的软件名一致；`repo_url` 必须是 `https://` |
| `version.value` / `version.type` | 是 | `value` 必须与标题版本一致（允许 `v` 前缀）；`type` 只能是 `latest_release` 或 `watched` |
| `upstream_evidence` | 是 | `support_level`、`computed_by`、`evaluated_at`、`evidence` |
| `upstream_evidence.evidence` | 是 | `check_id`、`result`（`supported` / `not_found` / `blocked`）；`artifact`、`source_url`、`checked_at`、`test_depth`、`ci_workflows`、`assessment_id` 建议填写 |
| `l3_evidence` | 否 | L3 openEuler 镜像证据；`result = supported` 表示该版本已在 docker 仓库存在，无则填 `null` |
| `install_candidates` | 是 | 至少一条；每项含 `type`（`source` / `binary`）、`url`（必须 `https://`）、`artifact`、`arch` |

> 正文缺少上述必填字段、软件名/版本与标题不一致、或上游地址不是 HTTPS 时，Issue 会被置为「已拒绝」并回帖原因。

---

## 5. 提交后会发生什么

```text
新建（你提交）
  │  监控工作流扫描到
  ▼
已接纳（流水线已触发，回帖确认）
  │
  ├─ 成功 → 已完成（Issue 自动关闭，回帖 PR / 运行链接）
  └─ 失败 → 已挂起（Issue 保持打开，回帖失败摘要和运行链接，等待人工处理）
```

特殊情况：

- **格式不对 / 上游地址非法** → 直接回帖「自动处理未启动：<原因>」，状态置为 **已拒绝**，Issue 保持打开。改好标题/正文后重新提交即可。
- **同一个软件已有「已接纳」的 Issue** → 新 Issue 保持「新建」排队，等前一个完成后的下一轮扫描再自动接纳。不会并行跑同一个软件。
- **两个仓都有该软件** → 同一次运行里 docker 升级和 conda 登记都会执行，分别出结果。
- **两库都没有该软件** → 目前只有已登记为「待新建」的软件（如 `grpc-java`）会自动调用场景一新建镜像；其它软件会挂起，建议改提 `【new-image】` Issue。
- **成功后会生成两类 PR**：镜像升级 PR 是主产物；另有按应用单独提交的 app-notes PR（Agent 总结的构建经验，写入 `config/app-notes/<app>.md`），评审合并与否不影响本次升级。

---

## 6. 状态说明

| 状态 | 含义 | 你需要做什么 |
|---|---|---|
| 新建 | 已提交，等待流水线认领 | 无需操作；同软件排队时耐心等待 |
| 已接纳 | 已触发升级，执行中 | 可点回帖里的运行链接看进度 |
| 已完成 | 已生成 PR 或已完成登记，Issue 自动关闭 | 去评审 PR |
| 已挂起 | 自动流程失败或需要人工判断 | 看回帖的失败摘要和运行链接；修好后可重新提 Issue |
| 已拒绝 | 标题/正文不满足格式 | 按回帖原因修正后重新提交 |

---

## 7. 常见拒绝原因

| 回帖原因 | 修正方式 |
|---|---|
| `title must match 【new-version】upgrade ...` | 严格按第 3 节标题格式重写 |
| `invalid app name in title` | 软件名只能包含字母、数字、`.`、`_`、`-`，且以字母或数字开头 |
| `invalid version in title` | 版本号不要带空格/斜杠，例：`1.85.4` |
| `body must contain the upstream evidence JSON object` | 正文粘贴第 4 节的完整证据 JSON，不要只写文字说明 |
| `missing required field: ...` | 补齐第 4 节表格里标为必填的字段 |
| `software.name must match the app in the title` | 正文 `software.name` 与标题软件名保持一致 |
| `version.value must match the version in the title` | 正文 `version.value` 与标题版本保持一致 |
| `software.repo_url must be an HTTPS URL` | 上游地址改成 `https://...` |
| `version.type must be latest_release or watched` | 把 `version.type` 改成 `latest_release` 或 `watched` |
| `upstream_evidence.evidence.result must be supported, not_found or blocked` | 按看板结果填写 `result` |
| `install_candidates` 相关报错 | 至少提供一条候选，`type` 只能是 `source` / `binary`，`url` 必须是 HTTPS |
| `软件清单、docker 仓与 conda 仓里都没有这个应用` | 软件名写错，或该软件尚未入库；改提 `【new-image】` |

---

## 8. 完整示例

### 例 1：docker 升级（最常见）

```text
标题：【new-version】upgrade grpc to 1.85.4 on openEuler 24.03-LTS-SP4

正文：粘贴第 4 节的完整证据 JSON（software.name=grpc，version.value=1.85.4）
```

### 例 2：conda 软件升级（如 benchmark）

```text
标题：【new-version】upgrade benchmark to 1.11.0 on openEuler 24.03-lts-sp4

正文：同样粘贴完整证据 JSON（software.name=benchmark，version.value=1.11.0）
```

结果：只登记 conda 版本，不会触发 docker 构建。

### 例 3：docker 和 conda 都有（如 OpenCV）

```text
标题：【new-version】upgrade OpenCV to 4.12.0 on openEuler 24.03-lts-sp4

正文：完整证据 JSON
```

结果：docker 仓生成新版本镜像 PR；conda 仓在 `packages/opencv/supported-versions.yml` 登记 `4.12.0` 并开 PR。

---

## 9. FAQ

**Q：版本号写错了能改吗？**
A：Issue 还在「新建」时可以直接编辑；已「已接纳」后请等本次结束，再重新提一个正确的 Issue。

**Q：会同时升级 docker 和 conda 吗？**
A：该软件在两个仓都存在时都会升级；只有一边存在时只升级那一边。

**Q：conda 登记到哪个 openEuler 段？**
A：优先用标题里的 openEuler 版本；该段不存在时会新建。架构沿用该包最近一条版本记录（如 `noarch`、`x86_64/aarch64`）。

**Q：多久能看到结果？**
A：取决于排队和构建时长。docker 升级包含双架构构建与功能测试，通常比 conda 登记慢。

**Q：失败了怎么办？**
A：看「已挂起」回帖里的运行链接和失败摘要；修好上游/版本信息后重新提 Issue。需要人工介入时会保留完整证据。

**Q：app-notes PR 是什么？**
A：升级/审计/修复 Agent 会把本次构建经验（耗时、必要依赖、已知坑）总结成 `app_note`，流水线写入本仓 `config/app-notes/<app>.md` 的自动沉淀章节，并按应用单独开一个 notes PR。它只更新自动章节，不会改人工内容；即使不合并也不影响镜像升级 PR。

**Q：我可以直接提 PR 吗？**
A：可以。自动流程只是把「生成 + 验证 + 提 PR」串起来；人工 PR 同样欢迎。
