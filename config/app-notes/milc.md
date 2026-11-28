<!-- oe-app-note:auto:6bd16fc/24.03-lts-sp4 -->
## 自动沉淀：6bd16fc / 24.03-lts-sp4

milc_qcd 的目标 commit（含 PR head，如 #101 的 6bd16fc）通常都是 develop 分支的祖先提交，用全量 git clone + git checkout <sha> 即可到达，无需显式 fetch refs/pull/*；commit 级固定版本必须用全量 clone（--depth 1 会缺非分支 SHA 导致 checkout 失败）。构建只需 dnf 的 gcc gcc-c++ cmake openmpi-devel make git，编译约 1-2 分钟，无 QUDA/GPU 依赖；su3_rhmd_hisq 目标与 -DMPP=ON -DOMP=ON -DSUBDIR=ks_imp_rhmc -DPRECISION=2 参数跨版本稳定。
<!-- /oe-app-note:auto -->
