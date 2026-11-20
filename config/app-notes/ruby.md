---
app: ruby
---
# ruby 升级注意点

## 构建方式
- 多阶段：下载 Ruby 源码，`./configure --disable-install-doc && make && make install`；
  运行阶段复制安装目录并设置 PATH / gem 环境。

## 已知坑
- 4.0.x 对 OpenSSL 3 有要求；依赖 `openssl-devel`、`libyaml-devel`、`zlib-devel`、
  `readline-devel`、`libffi-devel`，缺一个都会在 configure/make 阶段失败。
- 版本号 `4.0.10` 是完整三段，下载 URL 在 cache.ruby-lang.org；
  不要用 `latest` 或 GitHub tag `v4_0_10`（下划线写法是另一套命名）。
- 运行阶段 gem 的默认源与 `GEM_HOME` 保持旧文件设置。

## 验证
- `ruby -v` / `gem -v`；tests/test.sh 存在时以其为准。
