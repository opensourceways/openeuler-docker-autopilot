<!-- oe-app-note:auto:1.7.19/24.03-lts-sp4 -->
## 自动沉淀：1.7.19 / 24.03-lts-sp4

cJSON 头文件中的版本字符串通过宏 token-paste 生成（不存在字面量 "1.7.19"），但 CJSON_VERSION_MAJOR/MINOR/PATCH 是字面 #define，可直接 grep 已安装头文件做精确版本校验；ENABLE_CJSON_TEST 默认即 On，开启后 make 会编译 tests/ 下 unity 单测并可 ctest 运行，覆盖 JSON 生成/解析功能，可替代缺失的独立 test.sh 作为双架构构建期自校验。
<!-- /oe-app-note:auto -->
