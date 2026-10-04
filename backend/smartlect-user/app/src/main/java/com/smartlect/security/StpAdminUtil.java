package com.smartlect.security;

import cn.dev33.satoken.config.SaTokenConfig;
import cn.dev33.satoken.stp.StpLogic;
import jakarta.annotation.PostConstruct;
import org.springframework.stereotype.Component;

/**
 * Sa-Token 管理端多账号体系（ADR-0011 Step 2）。
 *
 * <p>与用户端 {@code StpUtil}（loginType="login"，tokenName="token"）并行：
 * 这里注册 loginType="admin"、tokenName="adminToken" 的独立 StpLogic，
 * Redis 键前缀为 {@code adminToken:login:token:{t}} 与 {@code adminToken:login:session:{adminId}}。
 *
 * <p>单设备约束：{@code isConcurrent=false}——同一管理员新登录自动踢掉旧 token，
 * 取代原 {@code smartlect:token:admin:account:{adminId}} 反向映射手动踢号。</p>
 */
@Component
public class StpAdminUtil {

    public static final String LOGIN_TYPE = "admin";
    public static final StpLogic stpLogic = new StpLogic(LOGIN_TYPE);

    @PostConstruct
    public void init() {
        SaTokenConfig config = new SaTokenConfig();
        config.setTokenName("adminToken");
        config.setTimeout(86400);
        config.setIsConcurrent(false);
        config.setIsShare(false);
        config.setTokenStyle("uuid");
        config.setIsLog(false);
        stpLogic.setConfig(config);
    }
}
