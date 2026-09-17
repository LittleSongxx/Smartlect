package com.smartlect.security;

import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.method.HandlerMethod;

import java.util.Set;

public final class TrialAdminAccess {

    private static final Set<String> READABLE_PATHS = Set.of(
            "/admin/account/logout",
            "/admin/account/me",
            "/admin/home/getTodayData",
            "/admin/home/loadWeeklyStatisticsData",
            "/admin/home/loadLessStockProduct",
            "/admin/productInfo/loadDataList",
            "/admin/productInfo/loadProduct",
            "/admin/productInfo/getProductInfo",
            "/admin/sysCategory/loadCategory",
            "/admin/sysCategory/getSysCategoryByCategoryId",
            "/admin/sysProductProperty/loadDataList",
            "/admin/sysProductProperty/getSysProductPropertyByPropertyId",
            "/admin/productSku/loadDataList",
            "/admin/productSku/getProductSkuByProductIdAndPropertyValueIdHash",
            "/admin/productPropertyValue/loadDataList",
            "/admin/productPropertyValue/getProductPropertyValueByProductIdAndPropertyValueId",
            "/admin/order/loadOrder",
            "/admin/order/loadOrderStatus",
            "/admin/order/loadComment",
            "/admin/order/getComment",
            "/admin/orderInfo/loadDataList",
            "/admin/orderInfo/getOrderInfoByOrderId",
            "/admin/orderItem/loadDataList",
            "/admin/orderItem/getOrderItemByOrderItemId",
            "/admin/orderComment/loadDataList",
            "/admin/orderComment/getOrderCommentByOrderId",
            "/admin/discountCoupon/loadDiscountCoupon",
            "/admin/discountCoupon/getDiscountCouponInfo",
            "/admin/refundReview/loadDataList",
            "/admin/commentReport/loadDataList",
            "/admin/commentReport/getCommentReportByReportId",
            "/admin/statisticsInfo/loadDataList",
            "/admin/setting/getLogistics",
            "/admin/memberLevelRewardConfig/getConfig",
            "/admin/signRewardConfig/getConfig",
            "/admin/mqCompensationLog/loadDataList",
            "/admin/mqCompensationLog/getByLogId",
            "/admin/tool/statistics");

    private TrialAdminAccess() {
    }

    public static boolean allows(HandlerMethod handler, HttpServletRequest request) {
        if (handler != null) {
            if (handler.getMethodAnnotation(TrialReadable.class) != null
                    || handler.getBeanType().getAnnotation(TrialReadable.class) != null) {
                return true;
            }
        }
        return READABLE_PATHS.contains(normalize(request));
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
        if (path.startsWith("/admin-api/")) {
            path = "/admin/" + path.substring("/admin-api/".length());
        }
        if (path.length() > 1 && path.endsWith("/")) {
            path = path.substring(0, path.length() - 1);
        }
        return path;
    }
}
