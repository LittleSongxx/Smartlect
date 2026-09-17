package com.smartlect.entity.config;

import com.smartlect.service.PasswordService;
import com.smartlect.utils.StringTools;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.Resource;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

@Component("appConfig")
public class AppConfig {
    private static final Logger logger = LoggerFactory.getLogger(AppConfig.class);

    @Value("${amap.key:}")
    private String amapKey;

    @Value("${project.folder:./data/smartlect/upload/}")
    private String projectFolder;

    @Value("${admin.account:admin}")
    private String adminAccount;

    @Value("${admin.password:admin123456}")
    private String adminPassword;

    @Value("${smartlect.trial.enabled:true}")
    private boolean trialEnabled;

    @Value("${smartlect.trial.password:Visit-Smartlect-2026}")
    private String trialPassword;

    @Value("${smartlect.trial.lock-public-register:true}")
    private boolean trialLockPublicRegister;

    private String adminPasswordHash;

    private String trialPasswordHash;

    @Resource
    private PasswordService passwordService;

    @PostConstruct
    public void initAdminPasswordHash() {
        if (adminPassword != null && adminPassword.startsWith("$2")) {
            adminPasswordHash = adminPassword;
        } else {
            adminPasswordHash = passwordService.encode(adminPassword);
        }
        if (trialPassword != null && trialPassword.startsWith("$2")) {
            trialPasswordHash = trialPassword;
        } else {
            trialPasswordHash = passwordService.encode(trialPassword);
        }
    }

    @Value("${project.domain:}")
    private String projectDomain;

    @Value("${admin.emails:}")
    private String adminEmails;

    //支付宝应用私钥
    @Value("${alipay.appPrivateKey:}")
    private String alipayAppPrivateKey;

    @Value("${alipay.appid:}")
    private String alipayAppid;

    @Value("${alipay.sellerId:}")
    private String alipaySellerId;

    @Value("${alipay.appCertPath:}")
    private String alipayAppCertPath;

    @Value("${alipay.alipayPublicCertPath:}")
    private String alipayPublicCertPath;

    @Value("${alipay.alipayRootCertPath:}")
    private String alipayRootCertPath;

    @Value("${alipay.serverUrl:}")
    private String alipayServerUrl;

    @Value("${alipay.connectTimeoutMs:3000}")
    private Integer alipayConnectTimeoutMs;

    @Value("${alipay.readTimeoutMs:8000}")
    private Integer alipayReadTimeoutMs;

    //订单超时（默认 15 分钟，对齐原 EShop）
    @Value("${order.expire.minute:15}")
    private Integer orderExpireMinute;

    // 自动确认收货
    @Value("${order.confirm.minute:10080}")
    private Integer orderConfirmMinute;

    // 模拟物流每步间隔（秒，默认 1 小时/站）
    @Value("${logistics.simulate.interval-second:3600}")
    private Integer logisticsSimulateIntervalSecond;

    // 模拟物流最大站点数
    @Value("${logistics.simulate.max-stations:5}")
    private Integer logisticsSimulateMaxStations;

    // 秒杀券预占超时（秒）
    @Value("${rush.prepare.expire-second:900}")
    private Integer rushPrepareExpireSecond;

    // 用户位置缓存过期（天）
    @Value("${user.location.expire-day:7}")
    private Integer userLocationExpireDay;

    // 自动校验订单
    @Value("${project.auto-checkpay:false}")
    private Boolean autoCheckpay;

    //限制ai聊天轮数

    @Value("${sign.streak.coupon-id:}")
    private String signStreakCouponId;

    @Value("${member.level2.coupon-id:}")
    private String memberLevel2CouponId;

    @Value("${member.level3.coupon-id:}")
    private String memberLevel3CouponId;

    @Value("${baidu.aip.api-key:}")
    private String baiduAipApiKey;

    @Value("${baidu.aip.secret-key:}")
    private String baiduAipSecretKey;

    @Value("${baidu.aip.enabled:false}")
    private Boolean baiduAipEnabled;

    @Value("${baidu.aip.strategy-id:#{null}}")
    private Integer baiduAipStrategyId;

    public String getProjectFolder() {
        if (!StringTools.isEmpty(projectFolder) && !projectFolder.endsWith("/")) {
            projectFolder = projectFolder + "/";
        }
        return projectFolder;
    }

    public String getAdminEmails() {
        return adminEmails;
    }

    public Integer getOrderExpireMinute() {
        return orderExpireMinute;
    }

    public String getProjectDomain() {
        return projectDomain;
    }

    public String getAlipayAppCertPath() {
        return alipayAppCertPath;
    }

    public String getAlipayPublicCertPath() {
        return alipayPublicCertPath;
    }

    public String getAlipayRootCertPath() {
        return alipayRootCertPath;
    }

    public Boolean getAutoCheckpay() {
        return autoCheckpay;
    }

    public String getAlipayAppPrivateKey() {
        return alipayAppPrivateKey;
    }

    public String getAlipayAppid() {
        return alipayAppid;
    }

    public String getAlipaySellerId() {
        return alipaySellerId;
    }

    public String getAlipayServerUrl() {
        return alipayServerUrl;
    }

    public Integer getAlipayConnectTimeoutMs() {
        return alipayConnectTimeoutMs;
    }

    public Integer getAlipayReadTimeoutMs() {
        return alipayReadTimeoutMs;
    }

    public boolean isAlipayConfigured() {
        return !StringTools.isEmpty(projectDomain)
                && !StringTools.isEmpty(alipayAppid)
                && !StringTools.isEmpty(alipaySellerId)
                && !StringTools.isEmpty(alipayAppPrivateKey)
                && !StringTools.isEmpty(alipayAppCertPath)
                && !StringTools.isEmpty(alipayPublicCertPath)
                && !StringTools.isEmpty(alipayRootCertPath)
                && !StringTools.isEmpty(alipayServerUrl);
    }

    public Integer getOrderConfirmMinute() {
        return orderConfirmMinute;
    }

    public Integer getLogisticsSimulateIntervalSecond() {
        return logisticsSimulateIntervalSecond;
    }

    public Integer getLogisticsSimulateMaxStations() {
        return logisticsSimulateMaxStations;
    }

    public Integer getRushPrepareExpireSecond() {
        return rushPrepareExpireSecond;
    }

    public Integer getUserLocationExpireDay() {
        return userLocationExpireDay;
    }

    public String getAdminAccount() {
        return adminAccount;
    }

    public String getAdminPassword() {
        return adminPassword;
    }

    public String getAdminPasswordHash() {
        return adminPasswordHash;
    }

    public boolean isTrialEnabled() {
        return trialEnabled;
    }

    public String getTrialPassword() {
        return trialPassword;
    }

    public String getTrialPasswordHash() {
        return trialPasswordHash;
    }

    public boolean isTrialLockPublicRegister() {
        return trialLockPublicRegister;
    }


    public String getSignStreakCouponId() {
        return signStreakCouponId;
    }

    public String getMemberLevel2CouponId() {
        return memberLevel2CouponId;
    }

    public String getMemberLevel3CouponId() {
        return memberLevel3CouponId;
    }

    public String getAmapKey() {
        return amapKey;
    }

    public String getBaiduAipApiKey() {
        return baiduAipApiKey;
    }

    public String getBaiduAipSecretKey() {
        return baiduAipSecretKey;
    }

    public Boolean getBaiduAipEnabled() {
        return baiduAipEnabled;
    }

    public Integer getBaiduAipStrategyId() {
        return baiduAipStrategyId;
    }
}
