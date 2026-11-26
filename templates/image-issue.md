**标题（按格式填写，不要加其它文字）：**

```text
【镜像任务】<一句话描述>
```

例如：`【镜像任务】新增 kvrocks 24.03-LTS-SP4 镜像`、`【镜像任务】升级 grpc 至 1.85.4`。

**任务类型（Type）：** new-image

> 填 `new-image`（新增镜像）/ `upgrade-version`（应用版本升级）/ `oe-upgrade`（openEuler 版本升级）三选一。
> 只需填写所选类型对应的字段，其它段落的字段留空即可。

---

## A. 新增镜像（Type = new-image）

**软件包名称（Package Name）：**

**源码仓库（Source Repository）：**

**所属领域（Domain）：**

**openEuler 版本（openEuler Version）：**

**应用版本（App Version）：**（可留空，留空时按源码仓库的 tag / release 推导）

---

## B. 应用版本升级（Type = upgrade-version）

**openEuler 版本（openEuler Version）：**（可选，仅用于 conda 仓登记）

**上游证据（必填）：**

> 每行一个字段，字段名与值之间用半角冒号加一个空格（`: `）。
> 括号及括号内的英文是旧字段名，仅作对照；实际填写时请删除括号及其内容。
> 上游支持检查点、中游证据、安装候选按需填写，没有就整行删掉。
> 门禁路径 / 安装候选可以重复多组，每组单独占一段连续行。

```text
软件名(software.name): grpc
源码仓库(software.repo_url): https://github.com/grpc/grpc
软件版本(software.version): 1.85.4
上游支持检查点(upstream_evidence.check_id): kp.l1.arm_ci
上游支持检查点地址(upstream_evidence.source_url): https://ci.example.com/jobs/1
门禁路径(ci_workflows.workflow_path): .github/workflows/ci.yml
门禁地址(ci_workflows.workflow_url): https://github.com/grpc/grpc/blob/<sha>/.github/workflows/ci.yml
门禁运行地址(ci_workflows.workflow_run_url): https://github.com/grpc/grpc/actions/runs/1
测试深度(test_depth): smoke
中游检查点(l3_evidence.check_id): kp.l3.openeuler_image
中游制品(l3_evidence.artifact): 1.85.4-oe2403sp4
中游路径(l3_evidence.source_url): https://gitcode.com/openeuler/openeuler-docker-images/tree/master/Others/grpc
安装候选(install_candidates.type): source
候选包地址(install_candidates.url): https://github.com/grpc/grpc/archive/v1.85.4.tar.gz
候选包制品(install_candidates.artifact): grpc-1.85.4.tar.gz
```

> `安装候选` 填 `source`（源码构建）或 `binary`（直接安装产物）；最终采用哪种由升级 Agent
> 根据实际 Dockerfile 决定。旧的 JSON 证据块仍可识别，只是不再推荐。

---

## C. openEuler 版本升级（Type = oe-upgrade）

**openEuler 目标版本（Target openEuler Version）：**

**Scope：**

> `Scope` 只接受 `AI` / `Bigdata` / `Cloud` / `Database` / `Distroless` / `HPC` /
> `Others` / `Storage`，多个领域用逗号分隔，留空或 `all` 表示全部。
