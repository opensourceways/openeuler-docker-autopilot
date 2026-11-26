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

**软件名（Software）：**

**目标版本（Target Version）：**

**openEuler 版本（openEuler Version）：**

**上游证据（Upstream Evidence，必填）：**

> 粘贴上游证据 JSON（可人工整理）。仅 `software` 必填，`software.name`、
> `software.version` 必须与上面的 Software / Target Version 一致；其余字段可以省略。
> 字段说明见 `docs/new-version-issue-guide.md`。

```json
{
  "software": {
    "name": "<软件名>",
    "repo_url": "https://github.com/<owner>/<repo>",
    "version": "<目标版本>"
  },
  "upstream_evidence": {
    "support_level": "L1",
    "evidence": {
      "check_id": "kp.l1.arm_ci",
      "source_url": "https://<可点开的证据地址>",
      "ci_workflows": [
        {
          "workflow_path": ".github/workflows/<workflow>.yml",
          "workflow_url": "https://github.com/<owner>/<repo>/blob/<sha>/.github/workflows/<workflow>.yml",
          "workflow_run_url": "https://github.com/<owner>/<repo>/actions/runs/<run_id>",
          "test_depth": "smoke"
        }
      ]
    }
  },
  "l3_evidence": {
    "check_id": "kp.l3.openeuler_image",
    "artifact": "<已有镜像版本 / 目录>",
    "source_url": "https://gitcode.com/openeuler/openeuler-docker-images/tree/<...>"
  },
  "install_candidates": [
    {
      "type": "source",
      "url": "https://github.com/<owner>/<repo>/archive/refs/tags/v<目标版本>.tar.gz",
      "artifact": "<软件名>-<目标版本>.tar.gz"
    }
  ]
}
```

---

## C. openEuler 版本升级（Type = oe-upgrade）

**openEuler 目标版本（Target openEuler Version）：**

**Scope：**

> `Scope` 只接受 `AI` / `Bigdata` / `Cloud` / `Database` / `Distroless` / `HPC` /
> `Others` / `Storage`，多个领域用逗号分隔，留空或 `all` 表示全部。
