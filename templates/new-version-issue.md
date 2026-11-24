**标题（按格式填写，不要加其它文字）：**

```text
【new-version】upgrade <软件名> to <目标版本> on openEuler <openEuler版本>
```

**上游证据（Upstream Evidence，必填）：**

> 粘贴上游看板返回的完整证据 JSON。`software.name` 必须与标题软件名一致，
> `version.value` 必须与标题版本一致；字段说明见 `docs/new-version-issue-guide.md`。

```json
{
  "schema_version": "1.1",
  "request_id": "req-<软件名>-<目标版本>",
  "software": {
    "name": "<软件名>",
    "repo_url": "https://github.com/<owner>/<repo>",
    "raw_category": "<看板原始分类>",
    "oss_map_id": "<看板映射 ID>"
  },
  "version": {
    "value": "<目标版本>",
    "type": "watched",
    "display": "v<目标版本>"
  },
  "upstream_evidence": {
    "support_level": "L1",
    "computed_by": "<采集方>",
    "evaluated_at": "<ISO8601 时间>",
    "evidence": {
      "check_id": "kp.l1.arm_ci",
      "result": "supported",
      "artifact": "<命中的制品、文档或 job 名>",
      "source_url": "https://<可点开的证据地址>",
      "checked_at": "<ISO8601 时间>",
      "test_depth": "smoke",
      "ci_workflows": [
        {
          "workflow_path": ".github/workflows/<workflow>.yml",
          "workflow_url": "https://github.com/<owner>/<repo>/blob/<sha>/.github/workflows/<workflow>.yml",
          "test_depth": "smoke"
        }
      ],
      "assessment_id": "<评估编号>"
    }
  },
  "l3_evidence": null,
  "install_candidates": [
    {
      "type": "source",
      "url": "https://github.com/<owner>/<repo>/archive/refs/tags/v<目标版本>.tar.gz",
      "artifact": "<软件名>-<目标版本>.tar.gz",
      "arch": "any"
    }
  ]
}
```
