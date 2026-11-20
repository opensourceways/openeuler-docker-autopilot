---
app: rabbitmq
---
# rabbitmq 升级注意点

## 构建方式
- 多阶段 builder：源码编译 Erlang/OTP（`otp_src_${ERLANG_VERSION}`）→
  Elixir（`v${ELIXIR_VERSION}`）→ `rabbitmq-server` 的 `v${VERSION}`，
  产出 generic-unix 包；运行阶段只复制 Erlang 与 rabbitmq 目录。

## 已知坑
- 三个版本要一起看：RabbitMQ 版本对 Erlang/Elixir 有最低/最高要求，
  升级 RabbitMQ 时先查官方 compatibility matrix，必要时同步抬 Erlang。
- 编译 OTP 需要 `python3`、`perl`、`autoconf`、`ncurses-devel`、`openssl-devel`；
  旧文件里 `ln -s /usr/bin/python3 /usr/bin/python` 是 OTP 构建必需。
- `mix local.hex` / `local.rebar` 需要网络；失败时不要跳过，否则 `make package` 会失败。
- 运行阶段要保留 `rabbitmq-plugins enable --offline rabbitmq_prometheus` 与配置目录。

## 验证
- `rabbitmq-server` 能启动、`rabbitmqctl status`；tests/test.sh 存在时以其为准。
