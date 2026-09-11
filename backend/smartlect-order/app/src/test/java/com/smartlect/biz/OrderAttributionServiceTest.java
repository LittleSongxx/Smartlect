package com.smartlect.biz;

import com.smartlect.entity.po.OrderInfo;
import com.smartlect.utils.JsonUtils;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.sql.ResultSet;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.Base64;
import java.util.Date;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class OrderAttributionServiceTest {
    private static final String SECRET = "synthetic-attribution-secret-only-for-test";
    private static final Instant NOW = Instant.parse("2026-09-09T01:00:00Z");

    static String token(Map<String, Object> fields) throws Exception {
        return sign(JsonUtils.toJson(fields), SECRET);
    }

    private static String sign(String json, String secret) throws Exception {
        String encoded = Base64.getUrlEncoder().withoutPadding().encodeToString(json.getBytes(StandardCharsets.UTF_8));
        Mac mac = Mac.getInstance("HmacSHA256");
        mac.init(new SecretKeySpec(secret.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
        return encoded + "." + HexFormat.of().formatHex(mac.doFinal(("smartlect-attribution-v1:" + encoded).getBytes(StandardCharsets.UTF_8)));
    }

    private static Map<String, Object> fields() {
        Map<String, Object> value = new LinkedHashMap<>();
        value.put("v", 1);
        value.put("context_id", "a".repeat(32));
        value.put("snapshot_version", 1);
        value.put("snapshot_hash", "b".repeat(64));
        value.put("user_id", "user-1");
        value.put("execution_scope_id", "f3-branch-a");
        value.put("issued_at", NOW.getEpochSecond() - 10);
        value.put("expires_at", NOW.getEpochSecond() + 290);
        return value;
    }

    @Test
    void exactSignedActorAndTimeVerifyWhileInvalidContextNeverGrantsScope() throws Exception {
        var service = new OrderAttributionService(mock(JdbcTemplate.class), SECRET);
        var verified = service.verify(token(fields()), "user-1", NOW);
        assertEquals("VERIFIED", verified.status());
        assertEquals("a".repeat(32), verified.contextId());
        assertEquals("b".repeat(64), verified.snapshotHash());
        assertEquals("f3-branch-a", verified.executionScopeId());
        assertEquals("UNKNOWN_CONTEXT", service.verify(token(fields()), "other", NOW).status());
        assertEquals("UNKNOWN_CONTEXT", service.verify(token(fields()), "user-1", NOW.plusSeconds(290)).status());
        assertEquals("UNKNOWN_CONTEXT", service.verify(token(fields()), "user-1", NOW.minusSeconds(11)).status());
        assertEquals("UNKNOWN_CONTEXT", new OrderAttributionService(mock(JdbcTemplate.class), "")
                .verify(token(fields()), "user-1", NOW).status());
        for (Map.Entry<String, Object> replacement : Map.<String, Object>of(
                "v", "1", "snapshot_version", 2, "snapshot_hash", "bad", "context_id", "not-an-id",
                "issued_at", NOW.getEpochSecond() - 11, "expires_at", NOW.getEpochSecond() + 301,
                "execution_scope_id", " ").entrySet()) {
            Map<String, Object> changed = fields();
            changed.put(replacement.getKey(), replacement.getValue());
            var rejected = service.verify(token(changed), "user-1", NOW);
            assertEquals("UNKNOWN_CONTEXT", rejected.status(), replacement.getKey());
            assertEquals("store", rejected.executionScopeId());
            assertNull(rejected.contextId());
        }
        String json = JsonUtils.toJson(fields());
        for (String invalid : List.of(sign(json, SECRET + "other"),
                sign(json.substring(0, json.length() - 1) + ",\"user_id\":\"user-1\"}", SECRET),
                sign(json + " {}", SECRET), sign(json.substring(0, json.length() - 1) + ",\"extra\":true}", SECRET),
                "bad", "x".repeat(4097))) {
            assertEquals("UNKNOWN_CONTEXT", service.verify(invalid, "user-1", NOW).status());
        }
    }

    @Test
    void freezeUsesOriginalOrderTimeAndDoesNotUpsertContext() throws Exception {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        var service = new OrderAttributionService(jdbc, SECRET);
        OrderInfo order = new OrderInfo();
        order.setOrderId("order-1");
        order.setUserId("user-1");
        order.setOrderTime(Date.from(NOW));
        service.freeze("user-1", List.of(order), token(fields()));
        ArgumentCaptor<String> sql = ArgumentCaptor.forClass(String.class);
        verify(jdbc).update(sql.capture(), eq("order-1"), eq("user-1"), eq(Timestamp.from(NOW)),
                eq("a".repeat(32)), eq(1), eq("b".repeat(64)), eq("f3-branch-a"), eq("VERIFIED"), eq("verified"));
        assertFalse(sql.getValue().contains("UPDATE"));
        assertThrows(IllegalStateException.class, () -> service.freeze("other", List.of(order), null));
    }

    @Test
    @SuppressWarnings("unchecked")
    void eventsUseFrozenOrderAnchorAndMissingHistoricalContextStaysUnknown() throws Exception {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        ResultSet row = mock(ResultSet.class);
        when(row.getTimestamp("anchor")).thenReturn(Timestamp.from(NOW));
        when(jdbc.query(anyString(), any(RowMapper.class), eq("order-1"))).thenAnswer(call ->
                List.of(((RowMapper<Map<String, Object>>) call.getArgument(1)).mapRow(row, 0)));
        var service = new OrderAttributionService(jdbc, SECRET);
        Map<String, Object> unknown = service.eventAttribution("order-1");
        assertEquals("UNKNOWN_CONTEXT", unknown.get("contextStatus"));
        assertEquals("store", unknown.get("executionScopeId"));
        assertNull(unknown.get("contextId"));
        assertEquals(NOW.toString(), unknown.get("orderCreatedAt"));
        when(row.getString("context_id")).thenReturn("a".repeat(32));
        when(row.getString("context_status")).thenReturn("VERIFIED");
        when(row.getString("execution_scope_id")).thenReturn("f3-branch-a");
        when(row.getString("snapshot_hash")).thenReturn("b".repeat(64));
        when(row.getObject("snapshot_version")).thenReturn(1);
        Map<String, Object> frozen = service.eventAttribution("order-1");
        assertEquals("VERIFIED", frozen.get("contextStatus"));
        assertEquals("a".repeat(32), frozen.get("contextId"));
        assertEquals(NOW.toString(), frozen.get("orderCreatedAt"));
        assertEquals(6, frozen.size());
    }
}
