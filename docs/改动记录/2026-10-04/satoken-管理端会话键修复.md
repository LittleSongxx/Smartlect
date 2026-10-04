# Sa-Token 管理端会话键前缀修复（adminToken:login:* → adminToken:admin:*）

## 需求

ADR-0011 Sa-Token 迁移后，common 与 gateway 对管理端会话键的拼写在两个文件里误写为 `adminToken:login:*`。Sa-Token 1.39 中 `StpAdminLogic.LOGIN_TYPE="admin"`、tokenName=adminToken，实际键为 `adminToken:admin:token:{token}` / `adminToken:admin:session:{adminId}`。旧前缀导致：Python assistant 经 Java `/internal/identity/introspect` 的 merchant 内省永远 401；网关对管理端路由的会话校验永远不命中。

## 具体变更

- `backend/smartlect-common/src/main/java/com/smartlect/component/RedisComponent.java`：
  - `SA_TOKEN_ADMIN_TOKEN_PREFIX` / `SA_TOKEN_ADMIN_SESSION_PREFIX` 改为 `adminToken:admin:token:` / `adminToken:admin:session:`；
  - session 读取从 `redisTemplate`（按 @class 反序列化成 SaSession 对象）改为 `stringRedisTemplate` 取原始 JSON 后 `JsonUtils.mapper()` 解析——sa-token-redis-jackson 写入的是带 @class 的纯 JSON 字符串，原方式 `instanceof Map` 永假。
- `backend/smartlect-gateway/.../AuthGlobalFilter.java`：`REDIS_KEY_TOKEN_ADMIN` 同步改为 `adminToken:admin:token:`（网关仅 hasKey，不解析值）。
- `backend/smartlect-coupon/.../DiscountCouponServiceImpl.java`：删除 `findListByParam` 上悬空的 `@Resource`（会被 CommonAnnotationBeanPostProcessor 当注入方法处理，存在启动期误注入风险）。

## 测试护栏（本次新增）

- `RedisComponentSaTokenSessionTest`（6→8 用例）：
  - `adminTokenResolvesViaAdminLoginTypeKeysAndRawSessionJson`：锁 `adminToken:admin:token:`/`adminToken:admin:session:` 前缀 + 原始 JSON 解析路径 + roles/permissions 解析；
  - `adminSessionVersionMismatchDeletesTokenAndYieldsNull`：锁版本不匹配踢人路径（删 token 键）。
- `AuthGlobalFilterTest`（8→9 用例）：`adminRoutesCheckAdminLoginTypeKeyPrefix` 锁网关 `adminToken:admin:token:` hasKey 前缀与失效 401。

## 验证

- 回归：`mvn test -pl smartlect-common,smartlect-gateway,smartlect-coupon -am` → BUILD SUCCESS，SaTokenSessionTest 8/8、AuthGlobalFilterTest 9/9。
- 真实 Redis 链路（线上内省恢复 401→200）属生产效果验收：未执行（本机未起全栈），标记未知，待部署后验证。

## 回滚

单提交 revert 即可；revert 后管理端内省回到永远 401 的已知坏状态。

## 关联版本

基于 `da76f8e`；修复代码为作者 2026-10-04 工作区改动，本次补测试并独立成提交（原混在 answer-feedback 批次中）。
