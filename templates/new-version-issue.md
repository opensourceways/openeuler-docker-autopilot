**标题（按格式填写，不要加其它文字）：**

```text
【new-version】upgrade <软件名> to <目标版本> on openEuler <openEuler版本>
```

> 新格式标题为 `【自动升级需求】upgrade <软件名> to <目标版本> on openEuler <openEuler版本>`，
> 见 `templates/auto-upgrade-issue.md`；旧标题 `【new-version】` 继续兼容。

**上游证据（必填）：**

> 每行一个字段，字段名与值之间用半角冒号加一个空格（`: `）。括号及括号内的英文是旧字段名，
> 仅作对照；实际填写时请删除括号及其内容。`软件名` / `软件版本` 必须与标题一致。
> 上游支持检查点、中游证据、安装候选按需填写，没有就整行删掉。

```text
软件名(software.name): <软件名>
源码仓库(software.repo_url): https://github.com/<owner>/<repo>
软件版本(software.version): <目标版本>
上游支持检查点(upstream_evidence.check_id): kp.l1.arm_ci
上游支持检查点地址(upstream_evidence.source_url): https://<可点开的证据地址>
门禁路径(ci_workflows.workflow_path): .github/workflows/<workflow>.yml
门禁地址(ci_workflows.workflow_url): https://github.com/<owner>/<repo>/blob/<sha>/.github/workflows/<workflow>.yml
门禁运行地址(ci_workflows.workflow_run_url): https://github.com/<owner>/<repo>/actions/runs/<run_id>
测试深度(test_depth): smoke
中游检查点(l3_evidence.check_id): kp.l3.openeuler_image
中游制品(l3_evidence.artifact): <已有镜像版本 / 目录>
中游路径(l3_evidence.source_url): https://gitcode.com/openeuler/openeuler-docker-images/tree/<...>
安装候选(install_candidates.type): source
候选包地址(install_candidates.url): https://github.com/<owner>/<repo>/archive/refs/tags/v<目标版本>.tar.gz
候选包制品(install_candidates.artifact): <软件名>-<目标版本>.tar.gz
```

> `中游检查点` 一组只在 docker 仓库已有该版本镜像时填写；有镜像时优先参考它。
> `安装候选` 填 `source`（按源码构建）或 `binary`（直接安装二进制产物），最终采用哪种
> 由升级 Agent 根据实际 Dockerfile 决定。旧的 JSON 证据块仍可识别，只是不再推荐。
