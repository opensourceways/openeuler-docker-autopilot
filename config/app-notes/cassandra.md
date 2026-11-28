<!-- oe-app-note:auto:5.0.10-tentative/24.03-lts-sp4 -->
## 自动沉淀：5.0.10-tentative / 24.03-lts-sp4

Cassandra 5.0.x 在 openEuler 上必须源码构建（tentative tag 无 release 二进制）。关键点：1) openEuler 的 /usr/bin/ant 经 java-functions 默认选中 JDK8，必须 ENV JAVA_HOME=/usr/lib/jvm/java-11-openjdk 覆盖，否则 ant 报 'Unsupported JDK version used: 1.8'；2) 构建 test 类需要 ant 的 junit 可选模块，需额外 yum install ant-junit，否则 artifacts 阶段失败；3) 构建命令沿用上游 _build-redhat.sh：ant artifacts -Drelease=true -Dant.gen-doc.skip=true -Djavadoc.skip=true -Dcheck.skip=true；4) 运行阶段仅需 java-11-openjdk-headless + util-linux，bin 包同时含 x86_64/aarch64 原生 lib，双架构同源无需分支。
<!-- /oe-app-note:auto -->
