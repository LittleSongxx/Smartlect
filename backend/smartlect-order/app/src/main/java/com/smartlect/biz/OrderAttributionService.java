package com.smartlect.biz;

import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.smartlect.entity.po.OrderInfo;
import com.smartlect.utils.JsonUtils;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.Base64;
import java.util.HashSet;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** Local signature verification and immutable order-time context; no Growth HTTP dependency. */
@Service
public class OrderAttributionService {
    private static final ObjectMapper JSON = JsonUtils.mapper().copy()
            .enable(JsonParser.Feature.STRICT_DUPLICATE_DETECTION)
            .enable(DeserializationFeature.FAIL_ON_TRAILING_TOKENS);
    private static final Set<String> FIELDS = Set.of("v", "context_id", "snapshot_version", "snapshot_hash",
            "user_id", "execution_scope_id", "issued_at", "expires_at");
    private final JdbcTemplate jdbc;
    private final byte[] secret;

    public OrderAttributionService(JdbcTemplate jdbc, @Value("${SMARTLECT_ATTRIBUTION_SECRET:}") String secret) {
        this.jdbc = jdbc;
        this.secret = secret.getBytes(StandardCharsets.UTF_8);
    }

    public record Context(String contextId, Integer snapshotVersion, String snapshotHash,
                          String executionScopeId, String status, String reason) { }

    private static Context unknown(String reason) {
        return new Context(null, null, null, "store", "UNKNOWN_CONTEXT", reason);
    }

    public Context verify(String token, String userId, Instant orderCreatedAt) {
        if (token == null || token.isBlank()) return unknown("context_missing");
        if (secret.length < 32) return unknown("independent_key_unavailable");
        try {
            if (token.length() > 4096) return unknown("context_invalid");
            String[] parts = token.split("\\.", -1);
            if (parts.length != 2 || !parts[0].matches("[A-Za-z0-9_-]+") || !parts[1].matches("[0-9a-f]{64}")) {
                return unknown("context_invalid");
            }
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(secret, "HmacSHA256"));
            byte[] expected = mac.doFinal(("smartlect-attribution-v1:" + parts[0]).getBytes(StandardCharsets.UTF_8));
            if (!MessageDigest.isEqual(expected, HexFormat.of().parseHex(parts[1]))) return unknown("signature_invalid");
            JsonNode value = JSON.readTree(Base64.getUrlDecoder().decode(parts[0]));
            Set<String> fields = new HashSet<>();
            if (!value.isObject()) return unknown("context_invalid");
            value.fieldNames().forEachRemaining(fields::add);
            if (!fields.equals(FIELDS) || !integer(value.get("v"), 1) || !integer(value.get("snapshot_version"), 1)
                    || !text(value.get("context_id"), 32).matches("[0-9a-f]{32}")
                    || !text(value.get("snapshot_hash"), 64).matches("[0-9a-f]{64}")
                    || !userId.equals(text(value.get("user_id"), 64))) return unknown("context_invalid");
            String scope = text(value.get("execution_scope_id"), 128);
            JsonNode issued = value.get("issued_at"), expires = value.get("expires_at");
            if (!issued.isIntegralNumber() || !issued.canConvertToLong() || !expires.isIntegralNumber()
                    || !expires.canConvertToLong()) return unknown("context_invalid");
            long start = issued.longValue(), end = expires.longValue(), now = orderCreatedAt.getEpochSecond();
            if (start < 0 || end <= start || end - start > 300 || now < start || now >= end) {
                return unknown("context_expired_or_not_yet_valid");
            }
            return new Context(value.get("context_id").textValue(), 1, value.get("snapshot_hash").textValue(),
                    scope, "VERIFIED", "verified");
        } catch (Exception invalid) {
            // A malformed optional context never fails a valid purchase or leaks its contents.
            return unknown("context_invalid");
        }
    }

    private static boolean integer(JsonNode value, int expected) {
        return value != null && value.isIntegralNumber() && value.canConvertToInt() && value.intValue() == expected;
    }

    private static String text(JsonNode value, int limit) {
        if (value == null || !value.isTextual() || value.textValue().isBlank() || value.textValue().length() > limit
                || value.textValue().chars().anyMatch(c -> c < 32)) throw new IllegalArgumentException("invalid context field");
        return value.textValue();
    }

    /** Called only inside the original order transaction, after idempotency has admitted a new order. */
    public void freeze(String userId, List<OrderInfo> orders, String token) {
        for (OrderInfo order : orders) {
            if (!userId.equals(order.getUserId()) || order.getOrderTime() == null) throw new IllegalStateException("invalid order owner/time");
            Context context = verify(token, userId, order.getOrderTime().toInstant());
            // Plain INSERT and the primary key forbid changing context on replay.
            jdbc.update("""
                    INSERT INTO order_attribution_context(order_id,user_id,order_created_at,context_id,snapshot_version,
                      snapshot_hash,execution_scope_id,context_status,reason) VALUES(?,?,?,?,?,?,?,?,?)
                    """, order.getOrderId(), userId, new Timestamp(order.getOrderTime().getTime()), context.contextId(),
                    context.snapshotVersion(), context.snapshotHash(), context.executionScopeId(), context.status(), context.reason());
        }
    }

    public Map<String, Object> eventAttribution(String orderId) {
        // Match the legacy order primary key even when the database default collation differs.
        List<Map<String, Object>> rows = jdbc.query("""
                SELECT COALESCE(c.order_created_at,o.order_time) AS anchor,c.context_id,c.snapshot_version,
                  c.snapshot_hash,c.execution_scope_id,c.context_status
                FROM order_info o LEFT JOIN order_attribution_context c
                  ON c.order_id COLLATE utf8mb4_general_ci=o.order_id
                WHERE o.order_id=?
                """, (row, number) -> {
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("contextId", row.getString("context_id"));
            result.put("snapshotVersion", row.getObject("snapshot_version"));
            result.put("snapshotHash", row.getString("snapshot_hash"));
            result.put("executionScopeId", row.getString("execution_scope_id") == null ? "store" : row.getString("execution_scope_id"));
            result.put("orderCreatedAt", row.getTimestamp("anchor").toInstant().toString());
            result.put("contextStatus", row.getString("context_status") == null ? "UNKNOWN_CONTEXT" : row.getString("context_status"));
            return result;
        }, orderId);
        if (rows.size() != 1) throw new IllegalStateException("order attribution fact unavailable");
        return rows.get(0);
    }
}
