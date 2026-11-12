# 构建修复日志

## 修复摘要
Fixed the x265 3.4 source download URL by switching from the non-existent GitHub release asset (`releases/download/3.4/x265_3.4.tar.gz`, HTTP 404) to the GitHub tag archive (`archive/refs/tags/3.4.tar.gz`) and added a synthetic `.hg_archival.txt` so CMake resolves the encoder version to `3.4` instead of `unknown`.

## 构建命令序列

1. `docker pull openeuler/openeuler:24.03-lts-sp4` — 基础镜像就绪（arch=x86_64）。
2. `docker run -d --name ci-fix-6204-amd64 openeuler/openeuler:24.03-lts-sp4 sleep infinity`
3. 重放 Dockerfile 第 6-8 行（依赖安装）：
   `dnf install -y gcc gcc-c++ make cmake curl tar gzip git` → 成功。
   `dnf install -y nasm`（x86_64 架构守卫内）→ 成功，`nasm-2.16.01`。
   `dnf clean all` → 成功。
4. 验证下载地址（关键诊断）：
   - `https://github.com/Multicorewareinc/x265/releases/download/3.4/x265_3.4.tar.gz` → **HTTP 404**（原始 Dockerfile 的 URL，即 ci_analysis 报告的失败点）。
   - `https://github.com/Multicorewareinc/x265/archive/refs/tags/3.4.tar.gz` → **HTTP 200**（当前修复后的 URL）。
   结论：x265 3.4 未在 GitHub Releases 发布制品，但 git tag `3.4` 存在，故改用 archive 归档地址。
5. 重放下载+解压+版本标记（第 10-15 行）：
   `curl -fSL ... archive/refs/tags/3.4.tar.gz && tar -xzf ... --strip-components=1 && printf 'tag: 3.4\n' > /x265/.hg_archival.txt` → 成功。
   说明：GitHub tag 归档不含 `.git`，x265 的 `source/cmake/version.cmake` 会退化为 `X265_VERSION=unknown`。写入 `tag: 3.4` 使版本检测命中 `hg_tag` 分支，正确得到 `3.4`。
6. 重放 cmake 配置（第 17-30 行）→ 成功，日志输出 `-- x265 version 3.4`。
7. 重放 `cmake --build -j$(nproc)` → 成功，`libx265.so.192`、`x265`、`TestBench` 全部编译链接通过。
8. 重放 `cmake --install` → 成功。
9. 重放 ldconfig + 版本校验（第 32-33 行）→ `x265 [info]: HEVC encoder version 3.4`，grep 命中。
10. `docker build -f Others/x265/3.4/24.03-lts-sp4/Dockerfile -t x265:3.4-test .` → **成功**（从零构建，镜像 sha256:5d208cf1...）。

## 修改的 Dockerfile 内容

相对 git HEAD（提交 05424a306 的原始版本），最终 Dockerfile 改动如下：

1. 下载源（第 11 行）：
   - 改前：`https://github.com/Multicorewareinc/x265/releases/download/${VERSION}/x265_${VERSION}.tar.gz`
   - 改后：`https://github.com/Multicorewareinc/x265/archive/refs/tags/${VERSION}.tar.gz`
2. 下载解压后追加版本标记（第 15 行，新增）：
   `printf 'tag: %s\n' "${VERSION}" > /x265/.hg_archival.txt`
3. 恢复文件末尾换行（原始提交末尾无换行，非功能性改动）。

其余指令（依赖安装、nasm 架构守卫、cmake 参数、install、ldconfig、WORKDIR、CMD）均保持不变。

架构中立性：改动均不依赖 CPU 架构，`archive/refs/tags` 与 `.hg_archival.txt` 在 amd64 与 arm64 上行为一致；nasm 的 `if [ "$(uname -m)" = "x86_64" ]` 守卫保持原样，不破坏 arm64。

## 验证结果

`docker build` 从零自检 **成功**：6 个阶段全部完成，镜像成功导出，`x265 --version` 输出 `HEVC encoder version 3.4`，最终 `grep -F "HEVC encoder version 3.4"` 命中。
