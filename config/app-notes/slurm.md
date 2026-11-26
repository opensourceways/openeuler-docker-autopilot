<!-- oe-app-note:auto:26.11.0.1/24.03-lts-sp4 -->
## 自动沉淀：26.11.0.1 / 24.03-lts-sp4

Slurm 26.11 客户端命令（srun/scontrol/sinfo 等）在启动时都会调用 slurm_conf_init() 建立配置源：镜像必须内置 /etc/slurm/slurm.conf（哪怕只有 ClusterName 和 SlurmctldHost=localhost 两行），否则会回落到 DNS SRV 查询并报 'Could not establish a configuration source'，连 `srun --version` 与 `scontrol show hostnames/hostlist` 这类纯本地操作都会因此失败。另外 slurm 的 `--version` 只输出 MAJOR.MINOR.MICRO（如 26.11.0），不含打包 release 后缀（unpackaged 版本号 26.11.0.1 的第四段），下游功能性测试做版本比较时必须剥离该后缀。
<!-- /oe-app-note:auto -->
