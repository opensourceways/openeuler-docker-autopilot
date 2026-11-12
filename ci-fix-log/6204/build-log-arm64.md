# 构建修复日志

## 修复摘要
Changed the x265 3.4 source download URL from the non-existent GitHub Release asset to the GitHub tag archive, and added a `.hg_archival.txt` file so the built binary reports the correct version `3.4`.

## 构建命令序列

以下命令均在 `arm64` 容器 `ci-fix-6204-arm64`（基于 `openeuler/openeuler:24.03-lts-sp4`）中逐条重放验证：

1. 安装编译依赖（对应 Dockerfile 第 6-8 行，成功）：
   `dnf install -y gcc gcc-c++ make cmake curl tar gzip git && dnf clean all`

2. 复现失败（对应 Dockerfile 第 10-11 行，失败）：
   `curl -fSL ... https://github.com/Multicorewareinc/x265/releases/download/3.4/x265_3.4.tar.gz`
   → 返回 HTTP 404。

   定位根因：通过 GitHub API 查询 `Multicorewareinc/x265` 仓库，确认 tag `3.4` 存在，但**没有**对应的 GitHub Release，故 `releases/download/3.4/x265_3.4.tar.gz` 资产不存在。而 `4.2` 存在 Release 资产 `x265_4.2.tar.gz`（这就是 4.2 能构建成功的原因）。

3. 修复下载源（验证成功）：
   `curl -fSL https://github.com/Multicorewareinc/x265/archive/refs/tags/3.4.tar.gz`
   → 返回 200，为 GitHub tag 归档包，解压后顶层目录为 `x265-3.4/`，`--strip-components=1` 后得到 `source/`、`build/` 等，与 4.2 资产结构一致。

4. 修复版本信息（对应 Dockerfile 第 31-32 行的 `grep -F "HEVC encoder version 3.4"` 检查）：
   GitHub tag 归档包不含 `.hg_archival.txt`/`.hg`/`.git`，`source/cmake/version.cmake` 会回退为 `x265 version 0.0`，导致 `x265 --version` 输出 `0.0` 而非 `3.4`。
   修复命令：`printf 'tag: 3.4\n' > /x265/.hg_archival.txt`，使 `version.cmake` 读到 `tag: 3.4`，构建后版本正确输出 `x265 version 3.4`。

5. 编译安装（成功）：`cmake -S /x265/source -B /x265/build-release ... && cmake --build /x265/build-release -j$(nproc) && cmake --install /x265/build-release`

6. 版本校验（成功）：`x265 --version 2>&1 | grep -F "HEVC encoder version 3.4"` → 输出 `HEVC encoder version 3.4`。

## 修改的 Dockerfile 内容

仅修改第 10-14 行的 `RUN`（下载解压）指令：

- 下载 URL 由
  `https://github.com/Multicorewareinc/x265/releases/download/${VERSION}/x265_${VERSION}.tar.gz`
  改为
  `https://github.com/Multicorewareinc/x265/archive/refs/tags/${VERSION}.tar.gz`
- 在解压后追加一行 `printf 'tag: %s\n' "${VERSION}" > /x265/.hg_archival.txt`，用于让 x265 的 `version.cmake` 识别出正确版本号。

其余指令（`dnf install`、cmake 编译配置、`ldconfig`、`WORKDIR`、`CMD` 等）一律原样保留。

## 验证结果

`docker build -f <derived-dockerfile> -t x265-3.4-test:arm64 <repo-root>` 从零构建成功（arm64），最终 `x265 --version` 输出 `HEVC encoder version 3.4`，全部 6 个阶段通过。
