package com.smartlect.security;

import jakarta.servlet.http.HttpServletRequest;

import java.util.Set;

public final class TrialUserAccess {

    private static final Set<String> BLOCKED_PATHS = Set.of(
            "/account/register",
            "/account/updateUserInfo",
            "/account/updatePassword",
            "/account/forgetPassword",
            "/account/getEmailCode",
            "/productCart/add2Cart",
            "/productCart/deleteCart",
            "/order/postOrder",
            "/order/cancelOrder",
            "/order/deleteOrder",
            "/order/confirmOrder",
            "/order/refundOrder",
            "/order/comment/postComment",
            "/order/comment/postReComment",
            "/order/comment/delMyComment",
            "/commentReport/submitReport",
            "/discountCoupon/rushCoupon",
            "/discountCoupon/buyDiscountCoupon",
            "/file/uploadImage",
            "/userMember/claimLevelReward",
            "/sign/sign",
            "/sign/msign",
            "/userFavorite/toggleFavorite",
            "/userFavorite/removeFavorite",
            "/userBrowse/clearBrowse",
            "/userBrowse/removeBrowse",
            "/browseHistory/clearBrowse",
            "/browseHistory/removeBrowse",
            "/userNotification/deleteNotification",
            "/userNotification/clearAll",
            "/userNotification/clearPopupNotification",
            "/userAddress/addAddress",
            "/userAddress/updateAddress",
            "/userAddress/updateDefault",
            "/userAddress/delAddress");

    private TrialUserAccess() {
    }

    public static boolean isBlocked(HttpServletRequest request) {
        return BLOCKED_PATHS.contains(normalize(request));
    }

    static String normalize(HttpServletRequest request) {
        if (request == null) {
            return "";
        }
        String path = request.getServletPath();
        if (path == null || path.isEmpty()) {
            path = request.getRequestURI();
        }
        if (path == null) {
            return "";
        }
        int query = path.indexOf('?');
        if (query >= 0) {
            path = path.substring(0, query);
        }
        if (path.startsWith("/api/")) {
            path = path.substring(4);
        }
        if (path.length() > 1 && path.endsWith("/")) {
            path = path.substring(0, path.length() - 1);
        }
        return path;
    }
}
