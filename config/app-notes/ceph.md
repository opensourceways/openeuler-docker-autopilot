---
app: ceph
build_timeout_minutes: 240
---
# ceph 升级注意点

## 构建方式
- 多阶段 builder：先源码编译 libnbd，再 `git clone --recursive` ceph，
  用 `./do_cmake.sh` 生成 build 目录后 `ninja` 全量编译；
- 依赖非常多（ocaml、rust/cargo、rdma-core、librdkafka、grpc、lua、lmdb 等），
  编译时间长，单架构验证预算已提高到 240 分钟。

## 已知坑
- 旧 Dockerfile 里有 `dnf update -y`；生成新版本时不要新增这类全量升级。
- `sed -i 's/set(_HAVE_ABSEIL OFF)/set(_HAVE_ABSEIL ON)/' src/CMakeLists.txt`
  是上游构建必需补丁；升级后若该行不存在，需要重新确认。
- 运行阶段依赖 `/usr/local/lib64` 的 LD_LIBRARY_PATH，复制产物后别丢。
- 需要 `nodeenv<1.10` 的 pip 约束，删掉会导致构建失败。

## 验证
- `ceph --version`；tests/test.sh 存在时以其为准。
