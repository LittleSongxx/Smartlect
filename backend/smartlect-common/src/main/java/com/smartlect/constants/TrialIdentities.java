package com.smartlect.constants;

import com.smartlect.entity.dto.AdminPrincipalDTO;
import com.smartlect.entity.dto.TokenUserInfoDTO;
import com.smartlect.utils.StringTools;

/**
 * Published portfolio identities. The password is not a secret; powerlessness is.
 */
public final class TrialIdentities {

    public static final String USER_ID = "8800000001";
    public static final String USER_EMAIL = "visitor@smartlect.demo";
    public static final String USER_NICK = "作品集访客";
    public static final String ADMIN_ACCOUNT = "gallery";
    public static final String ADMIN_DISPLAY_NAME = "作品集展厅";
    public static final String PUBLISHED_PASSWORD = "Visit-Smartlect-2026";
    public static final String ACCOUNT_TRIAL = "account:trial";

    public static final String USER_DENIED =
            "作品集试用账号只能浏览店内商品和导购，不能下单、加购、改密、改资料或注册新号。";
    public static final String ADMIN_DENIED =
            "作品集展厅账号只能查看经营数据，不能改库存、发知识、发券、管账号或查看用户隐私。";
    public static final String REGISTER_LOCKED = "公开演示已关闭自行注册，请使用登录页上的试用账号。";

    private TrialIdentities() {
    }

    public static boolean isTrialEmail(String email) {
        return email != null && USER_EMAIL.equalsIgnoreCase(email.trim());
    }

    public static boolean isTrialUserId(String userId) {
        return USER_ID.equals(userId);
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
        return isTrialEmail(emailOrAccount) || isTrialAdminAccount(emailOrAccount);
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
