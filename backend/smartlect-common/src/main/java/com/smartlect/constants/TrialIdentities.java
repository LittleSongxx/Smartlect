package com.smartlect.constants;

import com.smartlect.entity.dto.AdminPrincipalDTO;
import com.smartlect.entity.dto.TokenUserInfoDTO;
import com.smartlect.utils.StringTools;

/**
 * Published portfolio identities. The visitor password is not a secret; that
 * account stays powerless. The shopper password is also published, but it can
 * only mock-shop: identity and profile stay locked.
 */
public final class TrialIdentities {

    public static final String USER_ID = "8800000001";
    public static final String USER_EMAIL = "visitor@smartlect.demo";
    public static final String USER_NICK = "作品集访客";
    public static final String SHOPPER_USER_ID = "8800000002";
    public static final String SHOPPER_EMAIL = "shopper@smartlect.demo";
    public static final String SHOPPER_NICK = "演示买家";
    public static final String SHOPPER_DEFAULT_ADDRESS_ID = "SL8800000002D";
    public static final String SHOPPER_BACKUP_ADDRESS_ID = "SL8800000002B";
    public static final String SHOPPER_PHONE = "13800138002";
    public static final String DEMO_COUPON_ID = "CPDEMOBUYER01";
    public static final String DEMO_USER_COUPON_ID = "DCB8800000002C01";
    public static final String DEMO_COUPON_NAME = "演示专属无门槛券";
    public static final String PLAZA_COUPON_NAME = "默认店体验秒杀券";
    public static final String PLAZA_USER_COUPON_ID = "DCB8800000002PLZ";
    public static final String ADMIN_ACCOUNT = "gallery";
    public static final String ADMIN_DISPLAY_NAME = "作品集展厅";
    public static final String PUBLISHED_PASSWORD = "Visit-Smartlect-2026";
    public static final String ACCOUNT_TRIAL = "account:trial";

    public static final String USER_DENIED =
            "作品集试用账号只能浏览店内商品和导购，不能下单、加购、改密、改资料或注册新号。";
    public static final String SHOPPER_DENIED =
            "演示买家账号不能改密、改资料或注册新号，请使用登录页上的账密购物。";
    public static final String ADMIN_DENIED =
            "作品集展厅账号只能查看经营数据，不能改库存、发知识、发券、管账号或查看用户隐私。";
    public static final String REGISTER_LOCKED = "公开演示已关闭自行注册，请使用登录页上的演示账号。";

    private TrialIdentities() {
    }

    public static boolean isTrialEmail(String email) {
        return email != null && USER_EMAIL.equalsIgnoreCase(email.trim());
    }

    public static boolean isTrialUserId(String userId) {
        return USER_ID.equals(userId);
    }

    public static boolean isShopperEmail(String email) {
        return email != null && SHOPPER_EMAIL.equalsIgnoreCase(email.trim());
    }

    public static boolean isShopperUserId(String userId) {
        return SHOPPER_USER_ID.equals(userId);
    }

    public static boolean isPublishedDemoEmail(String email) {
        return isTrialEmail(email) || isShopperEmail(email);
    }

    public static boolean isPublishedDemoUser(String userId, String email) {
        return isTrialUser(userId, email) || isShopperUserId(userId) || isShopperEmail(email);
    }

    public static boolean isTrialUser(String userId, String email) {
        return isTrialUserId(userId) || isTrialEmail(email);
    }

    public static boolean isTrialUser(TokenUserInfoDTO token) {
        if (token == null) {
            return false;
        }
        if (Boolean.TRUE.equals(token.getTrial())) {
            return true;
        }
        return isTrialUser(token.getUserId(), token.getEmail());
    }

    public static boolean isTrialAdminAccount(String account) {
        return account != null && ADMIN_ACCOUNT.equalsIgnoreCase(account.trim());
    }

    public static boolean skipLoginCaptcha(String emailOrAccount) {
        return isPublishedDemoEmail(emailOrAccount) || isTrialAdminAccount(emailOrAccount);
    }

    public static boolean isTrialAdmin(AdminPrincipalDTO principal) {
        if (principal == null) {
            return false;
        }
        if (isTrialAdminAccount(principal.getAccount())) {
            return true;
        }
        if (principal.hasRole(AdminPermissions.TRIAL_OPERATOR_ROLE)) {
            return true;
        }
        return principal.hasPermission(AdminPermissions.ADMIN_TRIAL)
                && !principal.hasPermission(AdminPermissions.ADMIN_LEGACY)
                && !principal.hasRole(AdminPermissions.SUPER_ADMIN_ROLE);
    }

    public static boolean sameAccount(String left, String right) {
        return !StringTools.isEmpty(left) && !StringTools.isEmpty(right)
                && left.trim().equalsIgnoreCase(right.trim());
    }
}
