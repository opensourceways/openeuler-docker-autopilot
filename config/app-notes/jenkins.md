---
app: jenkins
---
# jenkins 升级注意点

## 构建方式
- 多阶段：builder 下载 Maven，`git clone -b jenkins-${VERSION}` 后
  `mvn spotless:apply && mvn clean install -Dmaven.test.skip=true`；
- 运行阶段只复制 `war/target/jenkins.war`，基于 Java 21 运行。

## 已知坑
- 版本号是 `2.591` 这类 LTS 线，tag 形如 `jenkins-2.591`，不要补 `v`。
- 旧文件运行阶段有 `dnf update -y`；生成时不要保留/新增全量升级。
- Maven 用的是华为云镜像；镜像里没有目标 Maven 版本时不要改 `MAVEN_VERSION`
  去“凑”，优先保持旧文件可用的版本。
- `mvn spotless:apply` 会改写源码，是上游构建必需步骤，不要删。

## 验证
- `java -jar jenkins.war --version`；tests/test.sh 存在时以其为准。

<!-- oe-app-note:auto:2.592/24.03-lts-sp4 -->
## 自动沉淀：2.592 / 24.03-lts-sp4

aarch64 上 `mvn clean install -Dmaven.test.skip=true` 全量构建约 13 分钟（16 核/31GB），`mvn spotless:apply` 约 2.5 分钟；产物为 `/jenkins/war/target/jenkins.war`（约 53MB，最终名即 jenkins.war，无需改名）。运行阶段仅需 `java-21-openjdk`（无 devel）即可 `java -jar ./jenkins.war --version` 输出 2.592。
<!-- /oe-app-note:auto -->
