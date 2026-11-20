---
app: ansible
---
# ansible 升级注意点

## 构建方式
- 多阶段：builder 阶段从 python.org 下载 CPython 3.12 源码，校验 sha256 后
  `--enable-shared` 编译安装到 `/usr/local/python3.12`；
- `python3.12 -m pip install ansible-core==${VERSION}`，运行阶段只复制 Python 目录。

## 已知坑
- `Python-${PYTHON_VERSION}.tgz` 的 sha256 与 Python 版本绑定；只改 ansible 版本时
  不要动它，改 Python 版本时必须同步更新 sha256。
- 运行阶段要重新写 `/etc/ld.so.conf.d/python3.12.conf` 并 `ldconfig`，否则
  `libpython3.12.so` 找不到。
- `pip install` 必须显式用 `python3.12`，不要依赖 PATH 里的系统 python。

## 验证
- `ansible --version`；tests/test.sh 存在时以其为准。
