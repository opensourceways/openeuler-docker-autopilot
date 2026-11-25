<!-- oe-app-note:auto:5.1.0/24.03-lts-sp4 -->
## 自动沉淀：5.1.0 / 24.03-lts-sp4

纯 OpenCV(非 CANN)变体与 CANN 变体共用同一套源码构建骨架，仅需：基础镜像用 openeuler/openeuler:24.03-lts-sp4、去掉 opencv_contrib/WITH_CANN/整段 CANN 补丁、BUILD_LIST 用 core,imgproc,imgcodecs,videoio,dnn,python3(不带 cannops)、编译库落 /usr/local/lib64(ld.so.conf)而 cv2 落 /usr/local/lib/python3.11/site-packages(该目录一旦存在便自动进入 sys.path，无需 .pth)。buildkit 会对 GIT_CONFIG_KEY_* 的 ENV 报 'SecretsUsedInArgOrEnv' 误报警告，可忽略。完整云上构建(含 IPP 下载)约 10 分钟(16 核 --parallel $(nproc))。
<!-- /oe-app-note:auto -->
