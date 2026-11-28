<!-- oe-app-note:auto:5.0.10-tentative/24.03-lts-sp4 -->
## 自动沉淀：5.0.10-tentative / 24.03-lts-sp4

Apache Cassandra 的 `cassandra -v` 通过 egrep 从源码版本串中提取纯版本号（如 5.0.10），不会携带分支/目录名里的 `-tentative` 后缀；因此版本断言必须对比去后缀后的基准版本。构建用 `ant artifacts -Drelease=true -Dant.gen-doc.skip=true -Djavadoc.skip=true -Dcheck.skip=true` 产出 `build/apache-cassandra-5.0.10-bin.tar.gz` 即可用于单机预装分发，无需额外运行时依赖。
<!-- /oe-app-note:auto -->
