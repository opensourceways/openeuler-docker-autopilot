<!-- oe-app-note:auto:4.0.4/24.03-lts-sp4 -->
## 自动沉淀：4.0.4 / 24.03-lts-sp4

wannier90 4.x 用 CMake 源码构建：依赖 cmake(>3.25)、gcc-gfortran、BLAS/LAPACK（openEuler 上 openblas-devel/lapack-devel，cmake 自动 FindBLAS/FindLAPACK 命中 libopenblas）。运行阶段只需 libgfortran+openblas+lapack。注意：主程序 wannier90.x/postw90.x 及共享库 libwannier90.so 安装在 /usr/local（可执行文件在 bin、共享库在 lib64），运行必须设 LD_LIBRARY_PATH=/usr/local/lib64:/usr/local/lib 才能找到 libwannier90.so.4；自 4.0.4 起 w90chk2chk.x/w90spn2spn.x 亦默认构建并安装。openEuler 24.03-lts-sp4 的更新仓库 update-source 元数据偶发 checksum 不匹配/超时，dnf 前先 dnf clean all 并写 skip_if_unavailable=True 可规避。
<!-- /oe-app-note:auto -->
