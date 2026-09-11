package com.smartlect.biz;

import com.smartlect.api.enums.OrderItemStatusEnum;
import com.smartlect.api.enums.OrderStatusEnum;
import com.smartlect.entity.enums.RefundSagaStatus;
import com.smartlect.entity.po.OrderComment;
import com.smartlect.entity.po.OrderInfo;
import com.smartlect.entity.po.OrderItem;
import com.smartlect.entity.po.OrderRequestIdempotency;
import com.smartlect.entity.po.RefundRequest;
import com.smartlect.utils.JsonUtils;
import com.smartlect.utils.StringTools;
import jakarta.annotation.Resource;
import org.springframework.stereotype.Service;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Reconciles Growth write commands after an HTTP response is lost.
 *
 * <p>The idempotency ledger is authoritative when it contains a completed
 * response. A non-terminal or legacy request is additionally checked against
 * order domain state so a command that committed just before a process/network
 * failure can still be closed as successful. This is a bounded reconciliation
 * ledger, not an exactly-once guarantee.</p>
 */
@Service
public class CommerceActionStatusService {

    public static final String STATUS_SUCCESS = "SUCCESS";
    public static final String STATUS_FAILED = "FAILED";
    public static final String STATUS_PROCESSING = "PROCESSING";
    public static final String STATUS_INCONCLUSIVE = "INCONCLUSIVE";
    public static final String STATUS_MANUAL_REVIEW = "MANUAL_REVIEW";
    public static final String STATUS_UNKNOWN = "UNKNOWN";

    @Resource
    private OrderRequestIdempotencyService idempotencyService;
    @Resource
    private OrderInfoService orderInfoService;
    @Resource
    private OrderItemService orderItemService;
    @Resource
    private OrderCommentService orderCommentService;
    @Resource
    private RefundSagaTransactionService refundSagaTransactionService;

    @Resource
    private CommerceV2Service businessStatusService;

    public Map<String, Object> resolve(Map<String, Object> body) {
        Map<String, Object> response = resolveCommand(body);
        String legacyStatus = stringValue(response.get("status"));
        response.put("commandStatus", STATUS_SUCCESS.equals(legacyStatus) ? "command_accepted"
                : STATUS_FAILED.equals(legacyStatus) ? "rejected" : "unknown");
        String action = stringValue(body.get("actionType"));
        Map<String, Object> arguments = params(body.get("params"));
        if (STATUS_SUCCESS.equals(legacyStatus) && ("REFUND".equals(action) || "CANCEL_ORDER".equals(action))) {
            try {
                Map<String, Object> business = "REFUND".equals(action)
                        ? businessStatusService.refundStatus(stringValue(body.get("userId")), stringValue(arguments.get("orderItemId")))
                        : businessStatusService.cancellationStatus(stringValue(body.get("userId")), stringValue(arguments.get("orderId")));
                // status is the legacy command receipt; all new consumers use commandStatus.
                business.forEach((key, value) -> {
                    if (!"status".equals(key)) response.put(key, value);
                });
                response.put("businessStatus", business.getOrDefault("status", STATUS_UNKNOWN));
            } catch (com.smartlect.exception.HttpBusinessException rejected) {
                if (rejected.getHttpStatus() == 403) throw rejected;
                response.put("commandStatus", "unknown");
            } catch (RuntimeException unavailable) {
                response.put("commandStatus", "unknown");
            }
        }
        return response;
    }

    private Map<String, Object> resolveCommand(Map<String, Object> body) {
        String userId = stringValue(body.get("userId"));
        String actionType = stringValue(body.get("actionType"));
        String idempotencyKey = stringValue(body.get("idempotencyKey"));
        String commandType = commandType(actionType);
        if (StringTools.isEmpty(userId)
                || StringTools.isEmpty(idempotencyKey)
                || commandType == null) {
            return result(STATUS_UNKNOWN, "无法识别待核对操作");
        }

        OrderRequestIdempotency ledger = idempotencyService.find(
                userId, commandType, idempotencyKey);
        if (ledger != null && "COMPLETED".equals(ledger.getStatus())) {
            return result(STATUS_SUCCESS, successMessage(actionType));
        }
        Map<String, Object> params = params(body.get("params"));
        if (effectObserved(userId, actionType, params)) {
            if (ledger != null && ("PROCESSING".equals(ledger.getStatus())
                    || "FAILED".equals(ledger.getStatus())
                    || "INCONCLUSIVE".equals(ledger.getStatus())
                    || "MANUAL_REVIEW".equals(ledger.getStatus()))) {
                idempotencyService.markReconciled(
                        userId,
                        commandType,
                        idempotencyKey,
                        successMessage(actionType));
            }
            return result(STATUS_SUCCESS, successMessage(actionType));
        }
        if (ledger != null && "FAILED".equals(ledger.getStatus())) {
            return result(STATUS_FAILED, failureMessage(ledger));
        }
        if (ledger != null && "MANUAL_REVIEW".equals(ledger.getStatus())) {
            return result(STATUS_MANUAL_REVIEW, "自动核对已到边界，等待人工复核", ledger);
        }
        if (ledger != null) {
            OrderRequestIdempotency updated = idempotencyService.recordInconclusive(
                    userId,
                    commandType,
                    idempotencyKey,
                    boundedInt(body.get("maxAttempts"), 6, 1, 100),
                    boundedInt(body.get("reconcileWindowSeconds"), 3600, 60, 7 * 24 * 3600),
                    "账本未终结且未观察到领域结果");
            if (updated != null && "MANUAL_REVIEW".equals(updated.getStatus())) {
                return result(STATUS_MANUAL_REVIEW, "自动核对已到边界，等待人工复核", updated);
            }
            return result(STATUS_INCONCLUSIVE, "尚未观察到确定执行结果", updated);
        }
        return result(STATUS_UNKNOWN, "未找到可确认的执行记录");
    }

    public static String commandType(String actionType) {
        return switch (actionType) {
            case "REFUND" -> OrderRequestIdempotencyService.COMMAND_COMMERCE_REFUND;
            case "CANCEL_ORDER" ->
                    OrderRequestIdempotencyService.COMMAND_COMMERCE_CANCEL_ORDER;
            case "CONFIRM_RECEIPT" ->
                    OrderRequestIdempotencyService.COMMAND_COMMERCE_CONFIRM_RECEIPT;
            case "PRODUCT_REVIEW" ->
                    OrderRequestIdempotencyService.COMMAND_COMMERCE_PRODUCT_REVIEW;
            case "RECOMMENT" -> OrderRequestIdempotencyService.COMMAND_COMMERCE_RECOMMENT;
            default -> null;
        };
    }

    private boolean effectObserved(
            String userId, String actionType, Map<String, Object> params) {
        return switch (actionType) {
            case "REFUND" -> refundObserved(userId, stringValue(params.get("orderItemId")));
            case "CANCEL_ORDER" ->
                    cancellationObserved(userId, stringValue(params.get("orderId")));
            case "CONFIRM_RECEIPT" ->
                    receiptObserved(userId, stringValue(params.get("orderId")));
            case "PRODUCT_REVIEW" ->
                    reviewObserved(userId, stringValue(params.get("orderId")), false);
            case "RECOMMENT" ->
                    reviewObserved(userId, stringValue(params.get("orderId")), true);
            default -> false;
        };
    }

    private boolean refundObserved(String userId, String orderItemId) {
        if (StringTools.isEmpty(orderItemId)) {
            return false;
        }
        RefundRequest request = refundSagaTransactionService.findByOrderItemId(orderItemId);
        if (request != null) {
            // REJECTED 是确定终止的终态：动作未生效，Growth 不得转述"已受理/退款成功"，
            // 否则用户会误以为退款已办理。其余状态（含 MANUAL_REVIEW）都属受理中。
            if (RefundSagaStatus.REJECTED.name().equals(request.getStatus())) {
                return false;
            }
            return userId.equals(request.getUserId());
        }
        OrderItem item = orderItemService.getOrderItemByOrderItemId(orderItemId);
        if (item == null
                || !OrderItemStatusEnum.REFUND.getStatus().equals(item.getOrderItemStatus())) {
            return false;
        }
        OrderInfo order = orderInfoService.getOrderInfoByOrderId(item.getOrderId());
        return order != null && userId.equals(order.getUserId());
    }

    private boolean receiptObserved(String userId, String orderId) {
        if (StringTools.isEmpty(orderId)) {
            return false;
        }
        OrderInfo order = orderInfoService.getOrderInfoByOrderId(orderId);
        return order != null
                && userId.equals(order.getUserId())
                && OrderStatusEnum.COMPLETED.getStatus().equals(order.getOrderStatus());
    }

    private boolean cancellationObserved(String userId, String orderId) {
        if (StringTools.isEmpty(orderId)) {
            return false;
        }
        OrderInfo order = orderInfoService.getOrderInfoByOrderId(orderId);
        return order != null
                && userId.equals(order.getUserId())
                && OrderStatusEnum.CANCELLED.getStatus().equals(order.getOrderStatus());
    }

    private boolean reviewObserved(String userId, String orderId, boolean recomment) {
        if (StringTools.isEmpty(orderId)) {
            return false;
        }
        OrderComment comment = orderCommentService.getOrderCommentByOrderId(orderId);
        if (comment == null || !userId.equals(comment.getUserId())) {
            return false;
        }
        String content = recomment
                ? comment.getRecommentContent()
                : comment.getCommentContent();
        return !StringTools.isEmpty(content);
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> params(Object raw) {
        if (!(raw instanceof Map<?, ?> map)) {
            return Collections.emptyMap();
        }
        Map<String, Object> result = new LinkedHashMap<>();
        map.forEach((key, value) -> result.put(String.valueOf(key), value));
        return result;
    }

    private static Map<String, Object> result(String status, String message) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("status", status);
        result.put("resultMessage", message);
        return result;
    }

    private static Map<String, Object> result(
            String status, String message, OrderRequestIdempotency ledger) {
        Map<String, Object> result = result(status, message);
        if (ledger == null) {
            return result;
        }
        result.put("reconcileAttempts", ledger.getReconcileAttempts());
        result.put("reconcileDeadline", ledger.getReconcileDeadline());
        result.put("lastReconcileAt", ledger.getLastReconcileAt());
        result.put("reviewReason", ledger.getReviewReason());
        return result;
    }

    private static String successMessage(String actionType) {
        return switch (actionType) {
            case "REFUND" -> "退款操作已受理";
            case "CANCEL_ORDER" -> "订单已取消";
            case "CONFIRM_RECEIPT" -> "订单已确认收货";
            case "PRODUCT_REVIEW" -> "订单评价已提交";
            case "RECOMMENT" -> "订单追评已提交";
            default -> "操作已完成";
        };
    }

    private static String failureMessage(OrderRequestIdempotency ledger) {
        String response = ledger.getResponseJson();
        if (response != null && !response.isBlank()) {
            try {
                Map<?, ?> payload = JsonUtils.parseObject(response, Map.class);
                Object message = payload == null ? null : payload.get("errorMessage");
                if (message != null && !String.valueOf(message).isBlank()) {
                    return String.valueOf(message);
                }
            } catch (RuntimeException ignored) {
                // Malformed legacy rows should not break the status endpoint.
            }
        }
        return "操作执行失败";
    }

    private static String stringValue(Object value) {
        return value == null ? "" : String.valueOf(value).trim();
    }

    private static int boundedInt(Object raw, int fallback, int minimum, int maximum) {
        int value;
        try {
            value = raw == null ? fallback : Integer.parseInt(String.valueOf(raw));
        } catch (NumberFormatException ignored) {
            value = fallback;
        }
        return Math.max(minimum, Math.min(value, maximum));
    }
}
