<!-- oe-app-note:auto:26.11.0.1/24.03-lts-sp4 -->
## 自动沉淀：26.11.0.1 / 24.03-lts-sp4

slurm 版本号是 RPM 式四段 (Version.Release)，但上游 tag 形如 slurm-26-11-0-1 而 `srun --version` 只报告三段 26.11.0（META 的 Version=26.11.0, Release=1）。升级时务必将 TAG 对齐到目标版本的 tag，不能沿用旧文件里的旧 tag（历史版本 26.05.5.1/26.05.6.1 的 Dockerfile 都错误地写成了 slurm-26-05-4-1）。构建仍为 autotools 流程：configure+make+make install，git tag 自带预生成 configure，可直接 `./configure`；全量 make -j16 约 250s。26.11 新增的 auth/jwt(libjwt) 与 serializer/yaml(libyaml) 均为可选插件，configure 探测不到只告警不禁用核心功能。注意：srun/scontrol 等命令在无 slurm.conf 时会因 configless 的 DNS SRV 查找失败而报 `Could not establish a configuration source`，这是 slurm 一贯行为（旧版同样在 slurm_init 阶段先建立配置源），验证 --version/hostnames/hostlist 需先写一个最小 slurm.conf。
<!-- /oe-app-note:auto -->
