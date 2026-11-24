**标题（按格式填写，不要加其它文字）：**

```text
【new-version】upgrade <软件名> to <目标版本> on openEuler <openEuler版本>
```

**上游证据（Upstream Evidence，必填）：**

> 粘贴上游看板返回的证据 JSON。仅 `software` 必填，`software.name`、`software.version`
> 必须与标题一致；其余字段可以省略。字段说明见 `docs/new-version-issue-guide.md`。

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

> `l3_evidence` 只在 docker 仓库已有该版本镜像时填写；有镜像时优先参考它。
> `install_candidates` 是候选安装方式：`type=binary` 表示可直接安装二进制，
> `type=source` 表示按源码构建；最终采用哪种由升级 Agent 根据实际 Dockerfile 决定。
