<!-- oe-app-note:auto:29.1.3/24.03-lts-sp4 -->
## 自动沉淀：29.1.3 / 24.03-lts-sp4

Erlang OTP 源码构建在 openEuler 24.03 上依赖 gcc gcc-c++ make flex perl ncurses-devel openssl-devel zlib-devel ca-certificates curl 即可，jinterface/odbc/wx 会因缺少 Java/ODBC/GL 头文件被自动禁用，不影响最小运行时。核验版本时：erlang:system_info(version) 返回的是 ERTS 版本（如 17.1.2）而非 OTP 版本，system_info(otp_release) 只返回主版本号（29），完整版本需读 /usr/local/lib/erlang/releases/<major>/OTP_VERSION。GitHub release 的源码包无稳定可预测的校验和文件，每次升级需重新下载并计算 sha256。构建产物仅 /usr/local（约 83s make+install），多阶段只拷贝 /usr/local 即可运行 erl，基础镜像自带 openssl-libs 满足 crypto/ssl NIF 运行时依赖。
<!-- /oe-app-note:auto -->
