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

1. **软件名**：使用目标仓里的目录名/包名。
   - 例：`grpc`、`slurm`、`benchmark`、`opencv`。
   - 不要写中文、空格或产品宣传名。
2. **目标版本**：填上游发布版本号，建议与仓库现有目录保持一致（通常不带 `v` 前缀）。
   - 例：`1.85.4`、`2.16.0`、`9.3.5`。
3. **openEuler 版本**：`24.03-lts-sp4`、`22.03-LTS-SP4` 这类写法均可，大小写不敏感。

> 不确定软件名？先在目标仓里搜一下，Issue 标题里的名字必须能对上，否则流水线无法定位。

---

## 3. Issue 标题（必填）

**新格式（推荐）**：

```text
【自动升级需求】upgrade <软件名> to <目标版本> on openEuler <openEuler版本>
```

示例：

```text
【自动升级需求】upgrade grpc to 1.85.4 on openEuler 24.03-lts-sp4
【自动升级需求】upgrade benchmark to 1.11.0 on openEuler 24.03-LTS-SP4
```

参数全部写在标题里，正文只填上游证据（模板见 [templates/auto-upgrade-issue.md](../templates/auto-upgrade-issue.md)）。

**旧格式（仍永久兼容）**：

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

- 前缀 `【自动升级需求】` / `【new-version】` 必须原样保留（中文方括号）；
- `upgrade`、`to`、`on openEuler` 是固定英文关键字；
- 标题里不要加“请”“麻烦”“版本升级”等额外文字；
- 软件名和版本号之间只隔 `to`，前后各一个空格。

---

## 4. Issue 正文（必填：上游证据）

正文用平铺字段描述上游证据（旧的 JSON 块仍可识别，但不再推荐）。每行一个字段，字段名与值之间是**半角冒号加一个空格**（`: `）；括号及括号内的英文是旧字段名，仅作对照，**实际填写时要删除括号及其内容**。可直接使用模板 [templates/auto-upgrade-issue.md](../templates/auto-upgrade-issue.md)，把示例值替换成真实值。流水线会把它透传给扫描阶段和生成 Agent，不再自行采集证据。

```text
软件名: grpc
源码仓库: https://github.com/grpc/grpc
软件版本: 1.85.4
上游支持检查点: kp.l1.arm_ci
上游支持检查点地址: https://ci.example.com/jobs/1
门禁路径: .github/workflows/ci.yml
门禁地址: https://github.com/grpc/grpc/blob/<sha>/.github/workflows/ci.yml
门禁运行地址: https://github.com/grpc/grpc/actions/runs/1
测试深度: smoke
中游检查点: kp.l3.openeuler_image
中游制品: 1.85.4-oe2403sp4
中游路径: https://gitcode.com/openeuler/openeuler-docker-images/tree/master/Others/grpc
安装候选: source
候选包地址: https://github.com/grpc/grpc/archive/v1.85.4.tar.gz
候选包制品: grpc-1.85.4.tar.gz
```

说明：

- `软件版本` 填上游发布版本；
- `上游支持检查点`、`中游检查点`、`安装候选` 三组都可以整组删掉；
- `门禁路径` / `安装候选` 可以重复多组，每组合成一个列表项；
- `中游检查点` 一组只在 docker 仓库已有该版本镜像时填写，有镜像时优先参考它。

字段约束：

| 字段 | 必填 | 说明 |
|---|---|---|
| `软件名`（`software.name`） | 是 | 必须与标题里的软件名一致 |
| `源码仓库`（`software.repo_url`） | 是 | 必须是 `https://` |
| `软件版本`（`software.version`） | 是 | 必须与标题版本一致（允许 `v` 前缀） |
| `上游支持检查点` / `上游支持检查点地址` | 否 | 对应 `upstream_evidence.evidence.check_id` / `source_url` |
| `门禁路径` / `门禁地址` / `门禁运行地址` / `测试深度` | 否 | 对应 `upstream_evidence.evidence.ci_workflows[]` 的一项 |
| `中游检查点` / `中游制品` / `中游路径` | 否 | 对应 `l3_evidence`；有 docker 镜像时优先 |
| `安装候选` / `候选包地址` / `候选包制品` | 否 | 对应 `install_candidates`（`source` / `binary`）；最终是否二进制直装由升级 Agent 根据实际 Dockerfile 决定 |

> 正文缺少 `软件名` / `源码仓库` / `软件版本`、软件名或版本与标题不一致、或上游地址不是 HTTPS 时，Issue 会被置为「已拒绝」并回帖原因。

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
- **conda 登记前会校验上游渠道产物**：按该包 `package.yml` 的 `channel` 查询 anaconda.org，目标版本缺对应架构产物时跳过登记与建 PR，并在运行日志记录原因。
- **conda 包缺 `tests/cases.yml`** 时自动补一份通用用例（安装版本核对 + 包文件完整性），与版本登记一起提交。
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
| `title must match 【自动升级需求】upgrade ...` | 严格按第 3 节标题格式重写 |
| `invalid app name in title` | 软件名只能包含字母、数字、`.`、`_`、`-`，且以字母或数字开头 |
| `invalid version in title` | 版本号不要带空格/斜杠，例：`1.85.4` |
| `body must contain the upstream evidence JSON object` | 正文按第 4 节补上平铺证据字段，每行 `字段: 值`；旧的 JSON 块也仍然可用 |
| `missing required field: ...` | 补齐第 4 节表格里标为必填的字段 |
| `software.name must match the app in the title` | `软件名` 与标题里的软件名保持一致 |
| `software.version must match the version in the title` | `软件版本` 与标题里的版本保持一致 |
| `software.repo_url must be an HTTPS URL` | 上游地址改成 `https://...` |
| `install_candidates` 相关报错 | 若填写，`type` 只能是 `source` / `binary`，`url` 必须是 HTTPS |
| `软件清单、docker 仓与 conda 仓里都没有这个应用` | 软件名写错，或该软件尚未入库；改提 `【new-image】` |

---

## 8. 完整示例

### 例 1：docker 升级（最常见）

```text
标题：【自动升级需求】upgrade grpc to 1.85.4 on openEuler 24.03-LTS-SP4

正文：第 4 节的平铺证据字段（软件名: grpc，软件版本: 1.85.4）
```

### 例 2：conda 软件升级（如 benchmark）

```text
标题：【自动升级需求】upgrade benchmark to 1.11.0 on openEuler 24.03-lts-sp4

正文：同样的平铺证据字段（软件名: benchmark，软件版本: 1.11.0）
```

结果：只登记 conda 版本，不会触发 docker 构建。

### 例 3：docker 和 conda 都有（如 OpenCV）

```text
标题：【自动升级需求】upgrade OpenCV to 4.12.0 on openEuler 24.03-lts-sp4

正文：完整平铺证据字段（含门禁 / 中游 / 安装候选）
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
