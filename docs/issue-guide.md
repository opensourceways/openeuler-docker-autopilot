# Issue 提交指南（新增镜像 / 应用升级 / openEuler 升级）

面向需要向 [openeuler-docker-images](https://gitcode.com/openeuler/openeuler-docker-images) 提需求的社区用户。三个场景的 Issue 格式都写在本文件，按场景照抄即可，不需要接触流水线仓库。

入口：GitCode → `openeuler/openeuler-docker-images` → Issues → 新建 Issue。

---

## 1. 三个场景怎么选

| 你的诉求 | 场景 | 标题后缀 |
|---|---|---|
| 仓库里还没有这个软件的镜像，想新增 | ① 新增镜像 | `add <软件包> <应用版本> docker image on openEuler <openEuler版本>` |
| 已有镜像要升级到上游新版本（docker 镜像和/或 conda 包） | ② 应用版本升级 | `upgrade <软件名> to <目标版本> on openEuler <openEuler版本>` |
| openEuler 发布了新版本，存量应用要补齐新版本镜像 | ③ openEuler 版本升级 | `upgrade openEuler to <目标版本>` |
| 只想改 Dockerfile 里的构建参数，不升级版本 | 不提 Issue | 直接提 PR 或联系维护者 |

三个场景的标题**统一以 `【自动升级需求】` 开头**，后面用不同后缀区分。

---

## 2. 标题规则

### 2.1 三种标题

```text
① 【自动升级需求】add <软件包> <应用版本> docker image on openEuler <openEuler版本>
② 【自动升级需求】upgrade <软件名> to <目标版本> on openEuler <openEuler版本>
③ 【自动升级需求】upgrade openEuler to <目标版本>
```

示例：

```text
① 【自动升级需求】add kvrocks 2.16.0 docker image on openEuler 24.03-LTS-SP4
② 【自动升级需求】upgrade grpc to 1.85.4 on openEuler 24.03-lts-sp4
③ 【自动升级需求】upgrade openEuler to 24.03-LTS-SP4
```

### 2.2 通用注意

- 前缀 `【自动升级需求】` 必须原样保留（中文方括号）；
- `add` / `upgrade` / `to` / `on openEuler` 是固定英文关键字，前后各一个空格；
- 标题里不要加“请”“麻烦”“版本升级”等额外文字；
- 软件名只能是目标仓里的目录名/包名，不要写中文、空格或产品宣传名；
- 版本号不要带空格或斜杠，例：`1.85.4`、`2.16.0`；
- openEuler 版本 `24.03-lts-sp4`、`24.03-LTS-SP4` 均可，大小写不敏感。

### 2.3 旧标题已下线

`【new-image】` / `【new-version】` / `【oe-upgrade】` 三种旧标题**不再支持**，对应旧监控工作流已移除；沿用旧标题提交的 Issue 会被识别为无效并回帖说明。请统一使用第 2.1 节的三种标题。

---

## 3. 场景一：新增镜像

### 3.1 标题

```text
【自动升级需求】add <软件包> <应用版本> docker image on openEuler <openEuler版本>
```

例如：

```text
【自动升级需求】add kvrocks 2.16.0 docker image on openEuler 24.03-LTS-SP4
```

### 3.2 正文（必填三个字段）

```markdown
**软件包名称（Package Name）：** kvrocks
**源码仓库（Source Repository）：** https://github.com/apache/kvrocks/tree/v2.16.0
**所属领域（Domain）：** 数据库
```

- **软件包名称**：发布后的镜像名，也是目标仓目录名，必须与标题里的软件包一致；
- **源码仓库**：必须是 `https://`，建议指向**具体 tag 或 release**，避免生成过程中上游漂移；
- **所属领域**：决定目标目录，中英文均可识别。

领域 → 目标目录映射：

| 领域关键词 | 目标目录 |
|---|---|
| 人工智能、AI、机器学习、ML | `AI/` |
| 大数据、bigdata | `Bigdata/` |
| 数据库、db、database | `Database/` |
| 云计算、云原生、虚拟化、网络、cloud | `Cloud/` |
| 高性能计算、HPC | `HPC/` |
| 存储、storage | `Storage/` |
| 安全、security | `Security/` |
| distroless | `Distroless/` |
| 其他、others | `Others/` |

### 3.3 提交后会发生什么

1. 监控工作流扫描到后认领，并回写 Issue 状态；
2. 生成 Dockerfile、`meta.yml`、README、`doc/image-info.yml` 与 `tests/test.sh`；
3. 门禁 + x86_64 / aarch64 双架构原生构建与功能测试，失败自动修复（有界轮次）；
4. 通过后提交 PR 并回复链接；无法收敛时附带诊断证据交维护者判断。

---

## 4. 场景二：应用版本升级

自动升级覆盖两个目标仓，**同一个 Issue 会自动判断升级哪里**：

- `openeuler/openeuler-docker-images`：生成/更新 Dockerfile，双架构构建 + 功能测试，提 PR；
- `openeuler/conda-ecopkgs`：在 `packages/<包名>/supported-versions.yml` 登记新版本，提 PR。

两个仓都有该软件时两边都会执行；只有一边有就只执行那一边。

### 4.1 标题

```text
【自动升级需求】upgrade <软件名> to <目标版本> on openEuler <openEuler版本>
```

示例：

```text
【自动升级需求】upgrade grpc to 1.85.4 on openEuler 24.03-lts-sp4
【自动升级需求】upgrade benchmark to 1.11.0 on openEuler 24.03-LTS-SP4
```

### 4.2 正文（上游证据）

参数全部写在标题里，正文只填上游证据。推荐直接用 Issue 模板生成的两列表格（`字段` / `值`），可选字段留空写 `（空）`：

```text
| 字段 | 值 |
| :--- | :--- |
| **软件名** | grpc |
| **源码仓库** | https://github.com/grpc/grpc |
| **软件版本** | 1.85.4 |
| **上游支持检查点** | kp.l1.arm_ci |
| **上游支持检查点地址** | https://ci.example.com/jobs/1 |
| **门禁路径** | .github/workflows/ci.yml |
| **门禁地址** | https://github.com/grpc/grpc/blob/<sha>/.github/workflows/ci.yml |
| **门禁运行地址** | https://github.com/grpc/grpc/actions/runs/1 |
| **测试深度** | smoke |
| **中游检查点** | kp.l3.openeuler_image |
| **中游制品** | 1.85.4-oe2403sp4 |
| **中游路径** | https://gitcode.com/openeuler/openeuler-docker-images/tree/master/Others/grpc |
| **安装候选** | source |
| **候选包地址** | https://github.com/grpc/grpc/archive/v1.85.4.tar.gz |
| **候选包制品** | grpc-1.85.4.tar.gz |
```

平铺行格式仍兼容：每行一个字段，字段名与值之间是半角冒号加一个空格（`: `）：

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

- `软件名` / `软件版本` 必须与标题一致（版本允许 `v` 前缀）；
- `上游支持检查点`、`中游检查点`、`安装候选` 三组都可以整组删掉，表格里留 `（空）` 等价于未填；
- `门禁路径` / `安装候选` 可以重复多组，每组连续若干行，合成列表项；
- `中游检查点` 一组只在 docker 仓库已有该版本镜像时填写，有镜像时优先参考它；
- 旧的 JSON 证据块仍可识别，但不再推荐；括号里的英文（如 `software.name`）是旧 JSON 字段名，只作对照，**实际填写时不要写括号**。

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

### 4.3 提交后会发生什么

- **docker 升级**：缺目标版本目录时补 `tests/test.sh` + AI 依证据生成 Dockerfile + 元数据落盘 + 双架构原生验证，通过后开 PR；目标版本目录已存在时不跳过，AI 审计后由修复 Agent 更新 Dockerfile 与 `doc/image-info.yml`，同样先过双架构校验再开 PR；
- **conda 登记**：按该包 `package.yml` 的 `channel` 查询 anaconda.org，目标版本缺对应架构产物时跳过登记与建 PR，并在运行日志记录原因；缺 `tests/cases.yml` 时自动补一份通用用例；
- **两库都没有该软件**：只有已登记为「待新建」的软件（如 `grpc-java`）会自动调用场景一新建镜像；其它软件会挂起，建议改提场景一 Issue；
- **app-notes PR**：Agent 会把本次构建经验写入 `config/app-notes/<app>.md` 并单独开一个 notes PR，评审合并与否不影响本次升级。

---

## 5. 场景三：openEuler 版本升级

### 5.1 标题

```text
【自动升级需求】upgrade openEuler to <目标版本>
```

例如：

```text
【自动升级需求】upgrade openEuler to 24.03-LTS-SP4
```

### 5.2 正文（目标版本与作用域）

```markdown
**openEuler 目标版本（Target openEuler Version）：** 24.03-lts-sp4
**Scope：** HPC
```

- `Target openEuler Version` 与标题里的版本必须一致，否则 Issue 被拒绝并回帖原因；
- `Scope` 只接受 `AI` / `Bigdata` / `Cloud` / `Database` / `Distroless` / `HPC` / `Others` / `Storage`，多个领域用逗号分隔，留空或 `all` 表示全部。

### 5.3 提交后会发生什么

控制器按 Issue 固化请求（固定 `base_sha` 与 `request_key`），按 Scope 扫描目标仓并生成任务清单；同一活动同一时刻只派发一个任务，每个任务完成 prepare → 4 轮双架构校验 → 封存 → PR，并持续回写 Issue 活动汇总。

---

## 6. 状态说明

```text
新建（你提交）
  │  监控工作流扫描到
  ▼
已接纳（流水线已触发，回帖确认）
  │
  ├─ 成功 → 已完成（Issue 自动关闭，回帖 PR / 运行链接）
  └─ 失败 → 已挂起（Issue 保持打开，回帖失败摘要和运行链接，等待人工处理）
```

| 状态 | 含义 | 你需要做什么 |
|---|---|---|
| 新建 | 已提交，等待流水线认领 | 无需操作；同软件排队时耐心等待 |
| 已接纳 | 已触发，执行中 | 可点回帖里的运行链接看进度 |
| 已完成 | 已生成 PR 或已完成登记，Issue 自动关闭 | 去评审 PR |
| 已挂起 | 自动流程失败或需要人工判断 | 看回帖的失败摘要和运行链接；修好后可重新提 Issue |
| 已拒绝 | 标题/正文不满足格式 | 按回帖原因修正后重新提交 |

同一个软件已有「已接纳」的 Issue 时，新 Issue 会保持「新建」排队，等前一个完成后的下一轮扫描再自动接纳，不会并行跑同一个软件。

---

## 7. 常见拒绝原因

| 回帖原因 | 修正方式 |
|---|---|
| `title must match 【自动升级需求】add ...` | 严格按第 3.1 节格式重写标题 |
| `title must match 【自动升级需求】upgrade ...` | 严格按第 4.1 节格式重写标题 |
| `title must match 【自动升级需求】upgrade openEuler to ...` | 严格按第 5.1 节格式重写标题（旧 `【oe-upgrade】` 不再支持） |
| `invalid app name in title` | 软件名只能包含字母、数字、`.`、`_`、`-`，且以字母或数字开头 |
| `invalid version in title` | 版本号不要带空格/斜杠，例：`1.85.4` |
| `missing required field: ...` / `missing required fields: ...` | 补齐第 3.2 / 4.2 节标为必填的字段 |
| `body must contain the upstream evidence JSON object` | 正文按第 4.2 节补上平铺证据字段，每行 `字段: 值` |
| `software.name must match the app in the title` | `软件名` 与标题里的软件名保持一致 |
| `software.version must match the version in the title` | `软件版本` 与标题里的版本保持一致 |
| `software.repo_url must be an HTTPS URL` | 上游地址改成 `https://...` |
| `install_candidates` 相关报错 | 若填写，`type` 只能是 `source` / `binary`，`url` 必须是 HTTPS |
| `body: Target openEuler Version is required` | 场景三正文补上 `**openEuler 目标版本（Target openEuler Version）：**` |
| `title and body openEuler versions do not match` | 场景三标题与正文的 openEuler 版本改成一致 |
| `scope: unsupported domain ...` | `Scope` 只能填第 5.2 节列出的领域 |

---

## 8. FAQ

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

**Q：提了 Issue 但一直没有反应，怎么排查？**
A：① 标题是否以 `【自动升级需求】` 开头且后缀正确；② 必填字段是否齐全；③ 单次扫描默认最多认领 3 个新 Issue，高峰期可能排队；④ 查看 **Watch 【自动升级需求】 GitCode Issues** 工作流的运行日志。

**Q：我可以直接提 PR 吗？**
A：可以。自动流程只是把「生成 + 验证 + 提 PR」串起来；人工 PR 同样欢迎。
