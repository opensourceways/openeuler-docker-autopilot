# 主题
设计 openEuler 容器镜像自动创建、更新、维护的系统

# 背景和目标

## 背景

openEuler 社区官方维护了一批应用容器镜像的 Dockerfile 和相关的文档，在**上游应用版本更新时**、**需要增加一个全新的应用镜像时**、**openEuler新版本发布**时均需要自动更新或创建对应的镜像

### 容器镜像分类
openEuler社区有如下两种分类：
- 基础容器镜像：上文中提到的官方发布到 https://repo.openeuler.org/openEuler-{VERSION}/docker_img/ 的容器镜像均为基础镜像，基础镜像仅包含少量的基础软件。
- 应用容器镜像：在基础镜像之上，安装特定场景应用软件的镜像，例如nginx，或AI软件栈的容器镜像等。

### 系统部署约束
这个 openEuler 容器镜像系统必须通过 Github Action 部署，这意味着：
- 整体的运行是通过 workflow 来承载
- 软件版本的更新或者 openEuler 版本的更新，通常会带来大批量应用镜像的更新，需要考虑并行执行
- 硬件资源能给到的是多组 self-hosted 的云上虚拟机，包含 x86 和 ARM64 架构

  > Runner 预装 Docker 与 buildx。构建须在对应架构的原生 Runner 上执行，不使用跨架构模拟——模拟会掩盖架构差异，使双架构验证失去意义。Runner 能力由 Job 启动时的自检把关，缺失即失败，不做临时安装。
  > 同一 Runner 上存在并发 Job，镜像 tag 与容器名须携带唯一标识，避免互相覆盖。

## 目标

1. 用户可以根据Issue描述需求，新增应用镜像，我希望能够自动提交一个PR来完成，创建一个新的镜像目录，并且符合仓库README.md约束的规范存放、生成所有要求的文档等
2. 当某个应用已存在应用容器镜像，且应用上游发布了新的版本，我希望你能提交 PR 来完成应用新版本的镜像发布，同上，也需要符合仓库规范，只能按规则新增一个目录，而不是修改已有镜像目录文件
3. 当 openEuler 发布新版本时，我希望你能够基于新的 openEuler 版本更新所有已有的应用容器镜像，你只能按规则新增一个目录，而不是修改已有镜像目录文件

## 补充目标：PR CI 失败自动修复（场景二）

在上述三个目标之外，还有一类高频重复劳动：**已经提出的版本升级 PR 因构建环境、依赖、编译参数变化导致 CI 失败**，需要维护者人工翻日志、定位根因、修改 Dockerfile 再重提，单条 PR 平均 15–30 分钟。

该能力不新增镜像目录，而是修复已经存在的 PR，因此作为**场景二**纳入本系统，原有目标二、三在文档中顺延为场景三、四：

1. 目标仓 PR 被打上 `ci_failed` 标签后，自动抓取**实际失败架构**的 CI 日志与 PR diff，由 AI 产出结构化诊断报告（日志与状态矛盾时标记"证据不足"，不猜根因）；
2. 修复不依赖文本盲改：在自托管 Runner 的容器内逐条执行 Dockerfile 指令、失败即修，跑通后反推 Dockerfile 并用 `docker build` 验证；
3. 反推出的 Dockerfile 回到 arm64 做确定性复验，再以最小 diff 落回源码，提交或复用 Fix PR；
4. Fix PR 的 CI 若再次失败，自动追加 commit 重试（最多 6 次），超限关闭 Fix PR 并通知人工介入；
5. 每次修复通过 CI 后，把失败模式沉淀进知识库（`docs/ci-failure-patterns.md`），供后续诊断参考。

实现移植自 [docker-images-workflow](https://github.com/FdeCad/docker-images-workflow)，仅适配本仓的 Runner 标签、锁定工具链与凭据约定。默认**不启用**（`config/watchlist.json` 的 `enabled: false`），需显式开启后才会对目标仓 PR 动手。

## 实施阶段

目标一至三共享同一套底层能力（编排、生成、构建、测试、门禁、PR 产出），差异只在触发输入与调度方式，因此按目标分阶段交付：先完成目标一，再依次是目标二、目标三。补充目标（场景二）是独立链路，与上述能力不重叠，已完成集成。

第一阶段的写入目标限定为测试仓；生产仓需显式配置开启，配置缺失或错误时一律解析为测试仓。

## 要求

1. 所有目标的达成不需要人工介入，因此要求：

- 不确定性的内容可通过agent处理，可能存在 creator, fixer 等互相协作或对抗的 agent 角色
- 确定性的内容尽量使用代码实现，保证 harness，如构建、测试等环节
- 系统的主流程必须要确定性代码来承载

2. 在新增一个应用镜像的时候，必须提供基础的功能测试用例，这个测试用例必须具备公众可信性，至于每个镜像的所有版本共享一组测试用例还是每个版本独有一组测试，需要你深度研究下

   > **结论：每个应用共享一组测试用例，放在 `<app>/tests/`。** 一处修复所有版本受益，按版本复制则 N 份需同步；同一套标准便于横向比较，版本特化的用例难以自证公允；新增版本无需新增测试代码。
   >
   > 两条前提：共享用例必须支持版本参数注入，不得硬编码版本号，否则会退化为"每版本独有"；修改共享用例会影响该应用所有历史版本，须在 PR 中声明受影响的版本范围。

3. 无论是新增还是更新镜像的场景，提交 PR 前必须保证 Dockerfile 是可以构建出镜像，而且必须通过基础的功能测试并在 PR 内包含测试结果，测试结果的归档可参考：https://gitcode.com/openeuler/openeuler-docker-images/tree/master/tests/rust ， 但是我认为这种测试用例以及Dockerfile的归档目录不是很建议，你可以深度研究下给出合理的方案

   > **结论：用例与结果都收进应用目录，不再使用顶层 `tests/`。**
   >
   > ```
   > <domain>/<app>/
   > ├── tests/                        # 应用级共享用例
   > │   ├── test.sh                   # 唯一应用功能测试入口
   > │   └── test_helpers.sh           # 可选辅助函数
   > ├── results/<app-ver>/<oe-ver>/   # 结果，双层归档，只增不改
   > └── <app-ver>/<oe-ver>/
   >     └── Dockerfile
   > ```
   >
   > 相比顶层 `tests/<app>/`：用例与被测对象同属一个目录树，进入应用目录即可看到；结果按应用版本 + openEuler 版本双层归档，与每个 Dockerfile 一一对应，而顶层方案只按应用版本归档、无法区分 openEuler 版本。
   >
   > 目标仓只归档双架构 JUnit 与 `version_info.json`；schema v1 的聚合 `results.json` 和完整构建日志只进入生产 candidate/artifact，避免仓库体积随构建次数增长。
   >
   > 该布局超出目标仓 README 当前定义的最小目录单元，需与仓库 maintainer 确认后再批量产出。
   > 场景一运行时由生产侧 Harness 在最长 120 秒内观察默认容器终止事件；有有效 `HEALTHCHECK` 时等待 `healthy`，没有时完整观察 120 秒。随后自动选择原容器或同一 image ID 的一次性测试容器，并只执行一次共享 `test.sh`。`EXPOSE` 端口不参与就绪调度，脚本的真实功能断言才是测试结论的核心依据。

# 参考信息

1. openEuler 官方镜像仓库：https://gitcode.com/openeuler/openeuler-docker-images

2. 一个完整的镜像目录参考：https://gitcode.com/openeuler/openeuler-docker-images/tree/master/Bigdata/kylin

3. 一些实验过的 agent 角色：

- Image Creator : https://github.com/opensourceways/openeuler-docker-autopilot/blob/main/.github/agents/image-creator.md
- Dockerfile Fixer : https://github.com/opensourceways/openeuler-docker-autopilot/blob/main/.github/agents/code-fixer.md
- Failure Analyst : https://github.com/opensourceways/openeuler-docker-autopilot/blob/main/.github/agents/ci-failure-analyst.md
- 测试用例生成器：https://github.com/Tian-Fantasea/OPENEULER-DOCKER-AUTOPILOT/blob/main/.github/agents/image-tester.md

4. Gitcode API 文档：https://docs.gitcode.com/docs/apis/

5. openEuler 应用容器镜像升级：https://github.com/opensourceways/easysoftware-autoupgrade/tree/release/bugfix-appupdate

6. openEuler 应用的上游版本监控：https://easysoftware-monitoring.test.osinfra.cn/ ， 以及源码实现：https://github.com/opensourceways/anitya ， 其中 easysoftware-autoupgrade 的版本监控调的就是这个服务

7. PR CI 失败自动修复工作流（场景二来源）：https://github.com/FdeCad/docker-images-workflow
