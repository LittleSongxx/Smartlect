# Nacos 配置中心收编本地配置（批次四）

日期：2026-10-07 ｜ 状态：已完成，全仓 BUILD SUCCESS

## 需求

对标主流（Nacos 统一注册+配置），九个服务的 application.yml + 公共 smartlect-common.yml 全部推入 Nacos 配置中心。

## 具体变更

1. **`scripts/nacos_config_push.py`**：向 Nacos OpenAPI 推送 dataId（幂等覆盖）；
   公共段 `smartlect-common.yml` + 服务段 `{service}.yml`（group SMARTLECT_GROUP）
2. **全部 9 个 pom** 加 `spring-cloud-starter-alibaba-nacos-config`
3. **全部 9 个 application.yml** 头部插入 `spring.config.import` 双 dataId
   （公共 + 服务自身），Nacos 地址/凭据走环境变量
4. 本地 yml 保留（作为 Nacos 不可达时的 fallback），但运行时优先从 Nacos 读取

## 验证

- `python3 scripts/nacos_config_push.py` 推送 10 个 dataId 全部成功
- 全仓 `mvn test` BUILD SUCCESS
- Nacos 控制台（127.0.0.1:18848）可查看所有配置

## 未完成项

- Nacos 推送脚本尚需集成到 `dev.sh bootstrap` 流程（首次部署自动推送）
- 热刷新验证（改 Nacos 配置 → @RefreshScope Bean 自动更新）未做（当前无 @RefreshScope Bean）
