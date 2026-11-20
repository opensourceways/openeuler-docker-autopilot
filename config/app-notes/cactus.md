---
app: cactus
---
# cactus 升级注意点

## 构建方式
- `git clone --branch v${VERSION} --depth 1` 后
  `git submodule update --init --recursive --depth 1`；
- 建 virtualenv，`pip install -U .` 与 `toil-requirement.txt`。

## 已知坑
- 子模块很多，submodule 初始化是主要耗时；`--depth 1` 必须保留，否则克隆会非常慢。
- pip 源写死 `https://pypi.org/simple`，国内 runner 可能慢；不要为此改版本相关逻辑。
- 版本 tag 形如 `v4.0.0`，与 `ARG VERSION` 拼接前确认上游确实有这个 tag。

## 验证
- `cactus --help`；tests/test.sh 存在时以其为准。
