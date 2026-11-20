---
app: pwdft
---
# pwdft 升级注意点

## 构建方式
- 上游 `ebylaska/PWDFT` 只发 commit，清单里的“版本”是 7 位短 SHA；
- `git clone` 后 checkout 该 SHA，CMake + make 构建。

## 已知坑
- 目录名是短 SHA，但 Dockerfile 里通常写完整 SHA 或 tag；两者必须对应同一个提交。
- 上游没有 release/tag，不要试图拼 `v${VERSION}` 的 tag URL。
- 依赖 MPI / BLAS / LAPACK 等，升级后以仓库 README 的依赖表为准。

## 验证
- 可执行文件能启动；tests/test.sh 存在时以其为准。
