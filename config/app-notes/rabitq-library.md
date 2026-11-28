<!-- oe-app-note:auto:0.9.0/24.03-lts-sp4 -->
## 自动沉淀：0.9.0 / 24.03-lts-sp4

RaBitQ-Library 是 C++ 头文件库（核心/FastScan 等为 header-only，位于 include/rabitqlib/），旧 Dockerfile 的交付物就是 `git clone + checkout v${VERSION} + cp -r include /usr/local/include/rabitq`，v0.7.x→v0.9.0 头文件目录结构未变，升级只需改版本号；`install_candidates` 里的 cp311 manylinux wheel 是 Python 绑定（rabitqlib），不提供 C++ 头文件，故 C++ 头文件交付需走源码 clone 而非 wheel。构建时 openEuler 的 `[update-source]` 仓库元数据 404 会导致 dnf 卡住，需 `skip_if_unavailable=True`（harness 已注入，勿在 Dockerfile 里改仓库配置）。
<!-- /oe-app-note:auto -->
