package com.smartlect.security;

import cn.dev33.satoken.config.SaTokenConfig;
import cn.dev33.satoken.stp.StpLogic;
import jakarta.annotation.PostConstruct;
import org.springframework.stereotype.Component;

/**
 * 管理端 StpLogic（loginType="admin"，tokenName="adminToken"）。
 * 注册在 common，使所有业务服务的 admin 路径都能走同一 StpLogic 做 Sa-Token 校验。
 */
@Component
public class StpAdminLogic {

    public static final String LOGIN_TYPE = "admin";
    public static final StpLogic LOGIC = new StpLogic(LOGIN_TYPE);

    @PostConstruct
    public void init() {
        SaTokenConfig config = new SaTokenConfig();
        config.setTokenName("adminToken");
        config.setTimeout(86400);
        config.setIsConcurrent(false);
        config.setIsShare(false);
        config.setTokenStyle("uuid");
        config.setIsLog(false);
        LOGIC.setConfig(config);
    }
}
