# ADR-0011: Sa-Token 迁移方案（已勘察，待实施）

日期：2026-10-04
状态：已批准，待实施（独立提交）；Step 1 已实施（见文末实施记录）

## 勘察结论

| 项 | 现状 | 迁移后 |
|---|---|---|
| 版本 | — | **1.39.0**（本地 .m2 全套 jar 已就位：spring-boot3-starter + redis-jackson + core + jakarta-servlet） |
| 网关 | 自研 AuthGlobalFilter（WebFlux GlobalFilter + ReactiveStringRedisTemplate 读 `smartlect:token:web:` 键） | 保留 AuthGlobalFilter 骨架，Redis 键前缀改为 Sa-Token 默认 `satoken:login:token:`；值是 loginId 字符串，extractUserId 改为直接读值。**无需 reactor starter**——网关只做 hasKey/get，不依赖 Sa-Token SDK |
| 用户端登录 | AccountController 手写 token 生成 + Redis `smartlect:token:web:{token}` 存 session JSON | `StpUtil.login(userId)` + `StpUtil.getSession().set("userInfo", tokenUserInfoDTO)`；登出 `StpUtil.logout()`；autoLogin `StpUtil.getLoginIdAsLong()` |
| 管理端登录 | AdminLoginController + `smartlect:token:admin:{token}` | Sa-Token 多账号模式：注册 `StpLogic("admin")` 实例 `StpAdminUtil.login(adminId)`；网关读 `satoken:admin:login:token:{token}` |
| 服务端登录校验 | GlobalOperationAspect + @GlobalInterceptor（29 处） | `SaInterceptor` + `@SaCheckLogin`（批量替换 @GlobalInterceptor → @SaCheckLogin） |
| 管理端 RBAC | AppInterceptor + @RequireAdminPermission（5 处） | `StpInterface.getPermissionList()` 从 admin_role_permission 加载 + `@SaCheckPermission("analytics:read")` |
| Assistant IdentityBridge | 直接读 Redis `smartlect:token:web/admin:` 键 | 改调 Java `/internal/identity/introspect` 内部端点读取 Sa-Token session（该端点自身改为 StpUtil.getSession()） |

## 迁移步骤（4 个独立提交）

### Step 1：用户端 token 格式切换
- user 服务 AccountController：StpUtil.login / logout / autoLogin
- common TokenConstants 键前缀改 `satoken:login:token:`
- 网关 AuthGlobalFilter 同步改键格式
- assistant IdentityBridge 改读新键
- 测试：登录/登出/autoLogin/网关过滤器

### Step 2：管理端多账号
- 注册 StpLogic("admin")，AdminLoginController 用 StpAdminUtil
- 网关 admin-api 分支改读 `satoken:admin:login:token:`
- AdminIdentityService 改用 StpAdminUtil.getSession()

### Step 3：服务端注解鉴权
- common 引入 sa-token-spring-boot3-starter + sa-token-redis-jackson
- 注册 SaInterceptor（excludePath 为网关白名单子集）
- 29 处 @GlobalInterceptor → @SaCheckLogin
- 5 处 @RequireAdminPermission → @SaCheckPermission
- 实现 StpInterface（从 RBAC 表加载权限码）
- 删除 GlobalOperationAspect + @GlobalInterceptor + AppInterceptor

### Step 4：清理
- 删 TokenConstants 旧键
- 删 GatewayTokenResolver（Sa-Token cookie/header 名可配）
- 更新全部受影响测试

## 风险

- Redis 键格式变更 = 已登录用户全部掉线（可接受：演示系统 + 发布窗口）
- Sa-Token 的 cookie 名默认 `satoken`——需配置 `sa-token.token-name=token`（与现有 cookie 名一致）
- admin 与 user 同 cookie 名双 token 并存——Sa-Token 多账号模式下 StpLogic("admin") 用独立 cookie 名 `adminToken`（`sa-token.admin.token-name`）

## Step 1 实施记录（2026-10-04）

**关键偏差：键前缀不是 `satoken:`，而是 `token:`。** Sa-Token 1.39.0 的
`StpLogic.splicingKey*` 用 `tokenName` 同时充当 Redis 键前缀与 Cookie/header 名
（1.45.0 亦然，实测反编译确认）。二者无法分别配置，而 cookie 名必须保持 `token`
（前端契约），因此实际键布局为：

- `token:login:token:{token}` → loginId 裸字符串（StringRedisTemplate 直写，无 JSON 包装）
- `token:login:session:{loginId}` → Account-Session JSON（GenericJackson2JsonRedisSerializer，
  含 `@class` 类型标记；`dataMap.userInfo` 即 TokenUserInfoDTO，`tokenSignList` 为
  `["java.util.Vector",[...]]` 包装数组）——以上格式均经 sa-token-redis-jackson 1.39.0 实测确认

Step 2 的 admin 键相应为 `adminToken:admin:token:`（StpLogic("admin") 配独立 tokenName）。

**落地清单（相对勘察计划的增补）：**

- user 服务引入 starter + redis-jackson；`sa-token.token-name=token`、timeout=86400、
  is-concurrent=true、is-share=false（等价旧"多端共存、每次登录新 token"语义）；
  Cookie 由 Sa-Token 下发（HttpOnly + SameSite=Lax + Path=/ + Max-Age=86400）
- AccountController：login → `StpUtil.login + getSession().set("userInfo")`；
  logout → `StpUtil.logoutByTokenValue(token)`（注意 `StpUtil.logout(Object)` 是按
  loginId 登出，勿混用）；autoLogin → `StpUtil.isLogin()` + session 覆盖 + Cookie 续期；
  TTL 续期由 autoRenew 自动完成（实测访问后 token 与 session 双键均续满）
- common 不引 Sa-Token SDK：RedisComponent 的 getTokenUserInfo / getTokenUserInfoByUserId /
  getUserIdByToken / updateUser / cleanAllToken 按上述键布局裸读写（Jackson tree 解析）；
  删除 saveTokenUserInfo / cleanTokenUserInfo / slideTokenTtl / REDIS_KEY_TOKEN_USERID_WEB；
  cleanAllToken 升级为按 tokenSignList 踢全部设备（旧实现只踢最新 token）
- 网关 web 分支读 `token:login:token:{token}` 裸值即 X-User-Id；admin 分支暂不动
- admin 服务两个 demo 端点（DemoFixtureController / DemoScenarioController 的 /session）
  改 `StpUtil.createLoginSession + getSessionByLoginId().set()`（无 HTTP 上下文依赖，
  单测用内存 dao 即可验证）；admin 服务因此提前引入 sa-token 依赖（Step 2 反正需要）
- assistant IdentityBridge 无需改动：勘察后已先行迁移到 `/internal/identity/introspect`，
  该端点经 RedisComponent 自动适配新键
- 测试：AccountControllerSaTokenTest（login/autoLogin/logout 全链路，内存 dao）、
  RedisComponentSaTokenSessionTest（裸读契约）、AuthGlobalFilterTest 更新键格式、
  两个 demo 控制器测试改断言 StpUtil 会话
