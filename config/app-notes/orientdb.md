<!-- oe-app-note:auto:3.2.59/24.03-lts-sp4 -->
## 自动沉淀：3.2.59 / 24.03-lts-sp4

## OrientDB 3.2.59 源码构建要点

- **3.2.59 无二进制制品**：Maven Central 上 `orientdb-community` 与 `orientdb-studio` 的版本列表均截至 3.2.58，3.2.59 只有 GitHub 源码 tag，必须先源码构建。
- **必须用自带 Maven wrapper**：openEuler 的 dnf `maven` 是 3.6.3，而 3.2.59 的 dependabot 把 `buildnumber-maven-plugin` 升到 3.4.0，要求 Maven >= 3.9.0，会直接报 `requires Maven version 3.9.0`。改用仓库内 `./mvnw`（下载 Maven 3.10.0）即可。
- **构建命令**：`./mvnw -B clean install -pl distribution -am -DskipTests`。`-pl distribution -am` 只构建发行版所需 12 个模块，跳过无关的 `tests` / `distribution-tp2`，产出 `distribution/target/orientdb-community-3.2.59.tar.gz`。
- **orientdb-studio 依赖坑**：社区发行版的 assembly 把 `com.orientechnologies:orientdb-studio:<ver>:zip`（`*:zip:*`）打进 plugins/，但 3.2.59 该 zip 未发布。已核实 orientdb-studio 3.2.58..3.2.59 只有 `pom.xml` 版本号变更（`plugin.json` 完全一致），故下载 3.2.58 zip 后 `install:install-file -Dversion=3.2.59 -Dpackaging=zip` 装进本地仓库即可，功能等价。
- **JDK**：构建用 `java-1.8.0-openjdk-devel`（javac），运行用 `java-1.8.0-openjdk`；源码 `maven.compiler.source/target=8`。
- **运行注意**：首次启动若不设 `ORIENTDB_ROOT_PASSWORD`，`server.sh` 会交互式询问 root 密码并在非交互环境以 null 密码创建 root 失败（3.2.58 同样如此，非本次升级引入）；运行验证时需 `-e ORIENTDB_ROOT_PASSWORD=...`。
<!-- /oe-app-note:auto -->
