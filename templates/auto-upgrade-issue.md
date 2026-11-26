**标题（按格式填写，不要加其它文字）：**

```text
【自动升级需求】upgrade <软件名> to <目标版本> on openEuler <openEuler版本>
```

例如：`【自动升级需求】upgrade grpc to 1.85.4 on openEuler 24.03-LTS-SP4`

**上游证据（必填）：**

> 每行一个字段，字段名与值之间用半角冒号加一个空格（`: `）。
> 上游支持检查点、中游证据、安装候选按需填写，没有就整行删掉。
> 门禁路径 / 安装候选可以重复多组，每组单独占一段连续行。
> 每个字段对应的旧 JSON 键见 `docs/new-version-issue-guide.md` 第 4 节。

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

> `软件名` 与 `软件版本` 必须与标题一致。
> `安装候选` 填 `source`（源码构建）或 `binary`（直接安装产物）；最终采用哪种由升级 Agent
> 根据实际 Dockerfile 决定。旧的 JSON 证据块仍可识别，只是不再推荐。
