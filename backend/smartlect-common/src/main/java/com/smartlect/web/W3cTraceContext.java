package com.smartlect.web;

/**
 * W3C Trace Context. Filter 只从 {@code traceparent} 回填 MDC；
 * 没有该头时的 UUID 只是日志关联，不是 OTEL {@code trace_id}。
 */
public final class W3cTraceContext {

    public static final String TRACEPARENT = "traceparent";

    private W3cTraceContext() {
    }

    /**
     * @return 32 位小写 hex trace-id，非法或不存在时返回 {@code null}
     */
    public static String traceIdFromTraceparent(String header) {
        if (header == null || header.isBlank()) {
            return null;
        }
        String[] parts = header.trim().split("-");
        if (parts.length != 4) {
            return null;
        }
        if (parts[0].length() != 2 || !isHex(parts[0])) {
            return null;
        }
        if (!isHex(parts[1], 32) || isAllZero(parts[1])) {
            return null;
        }
        if (!isHex(parts[2], 16) || isAllZero(parts[2])) {
            return null;
        }
        if (!isHex(parts[3], 2)) {
            return null;
        }
        return parts[1].toLowerCase();
    }

    private static boolean isHex(String value) {
        return isHex(value, value.length());
    }

    private static boolean isHex(String value, int length) {
        if (value == null || value.length() != length) {
            return false;
        }
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            boolean hex = (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F');
            if (!hex) {
                return false;
            }
        }
        return true;
    }

    private static boolean isAllZero(String value) {
        for (int i = 0; i < value.length(); i++) {
            if (value.charAt(i) != '0') {
                return false;
            }
        }
        return true;
    }
}
