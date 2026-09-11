# Smartlect 用户端

独立 Vue 用户界面：导购与知识客服、商品 SKU、交易确认、本人订单、模拟付款和本人购物偏好。来源与裁剪记录见 [SOURCES.md](SOURCES.md)。

在本目录执行：

```bash
npm ci --ignore-scripts
npm run test
npm run build
```

Vite 服务由项目根运行管理器监督；本端不自动启动任何 Java/Python/数据库进程。根任务可使用以下入口：

```bash
SMARTLECT_WEB_USER_PORT=18180 SMARTLECT_GATEWAY_URL=http://127.0.0.1:18082 npm run dev
# 或使用已构建输出
SMARTLECT_WEB_USER_PORT=18180 SMARTLECT_GATEWAY_URL=http://127.0.0.1:18082 npm run preview
```

只监听 `127.0.0.1`，严格占用所分配端口，冲突会退出。`/api` 代理到本项目 Gateway；后端 `SMARTLECT_ALLOWED_ORIGINS` 需包含实际 UI Origin。环境变量仅在 Vite 配置中使用，禁止把内部凭证或模型 key 放入 `VITE_*`。

入口 `/assistant`、`/catalog`、`/orders`、`/preferences`、`/login`；普通登录使用 Java 邮箱/密码/图片验证码和 HttpOnly cookie。不会注册公开无密码演示登录，演示浏览器会话由根验收脚本通过受保护的 Java 合成数据接口准备。

当前单元测试使用模拟 HTTP 验证浏览器边界，不代表真实模型通过；真实模型和业务端到端证据由根阶段验收记录。
