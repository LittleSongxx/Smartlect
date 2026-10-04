# ADR-0011: Sa-Token 迁移方案（已勘察，待实施）

日期：2026-10-04
状态：已批准，待实施（独立提交）

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
