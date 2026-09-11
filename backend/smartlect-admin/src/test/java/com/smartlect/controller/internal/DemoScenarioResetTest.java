package com.smartlect.controller.internal;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.smartlect.component.RedisComponent;
import com.smartlect.exception.HttpBusinessException;
import com.smartlect.service.PasswordService;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicLong;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/** SQL-boundary tests; actual cross-schema transactions are verified by the local reset integration. */
class DemoScenarioResetTest {
    private static final ObjectMapper JSON = new ObjectMapper();
    private static final String PASSWORD = "synthetic-demo-reset-password-only";

    @Test
    void reset_retires_every_branch_without_deleting_old_facts_and_exact_replay_reuses_new_resources() throws Exception {
        Fixture fixture = new Fixture();
        assertNull(fixture.controller.resetResult(fixture.inspect()).getData());
        var before = fixture.controller.inspectRun(fixture.inspect()).getData();
        assertTrue(before.ready());
        assertEquals(2, before.branches().size());
        assertEquals(List.of("original-event"), ((Map<?, ?>) ((List<?>) before.watermark().get("outbox")).get(0)).get("eventIds"));
        JsonNode request = fixture.reset(before.watermarkHash());
        var result = fixture.controller.reset(request).getData();
        assertEquals("retire_and_replace", result.mode());
        assertEquals(before.scopeIds(), result.retiredScopeIds());
        assertNotEquals("run", result.replacementRunId());
        assertEquals(2, result.replacementManifests().size());
        for (int index = 0; index < 2; index++) {
            var old = before.branches().get(index); var replacement = result.replacementManifests().get(index);
            assertEquals(old.branchId(), replacement.branchId());
            assertEquals(old.initialStock(), replacement.initialStock());
            assertNotEquals(old.executionScopeId(), replacement.executionScopeId());
            assertTrue(replacement.products().stream().noneMatch(old.products()::contains));
            assertNotEquals(old.users().get(0).userId(), replacement.users().get(0).userId());
        }
        assertEquals("RETIRED", fixture.runs.get("run").get("state"));
        assertTrue(fixture.userStatus.values().stream().allMatch(status -> status == 0));
        assertTrue(fixture.productStatus.values().stream().allMatch(status -> status == 0));
        int resourceWrites = fixture.resourceWrites;
        assertEquals(JSON.writeValueAsString(result), JSON.writeValueAsString(fixture.controller.resetResult(fixture.inspect()).getData()));
        assertEquals(JSON.writeValueAsString(result), JSON.writeValueAsString(fixture.controller.reset(request).getData()));
        assertEquals(resourceWrites, fixture.resourceWrites);
        assertEquals(409, assertThrows(HttpBusinessException.class,
                () -> fixture.controller.reset(fixture.reset("a".repeat(64)))).getHttpStatus());
        assertEquals(410, assertThrows(HttpBusinessException.class,
                () -> fixture.controller.seed(JSON.valueToTree(new DemoScenarioController.Seed("run", "new-branch", 1, 1, 10)))).getHttpStatus());
        assertTrue(fixture.writes.stream().noneMatch(sql -> sql.startsWith("DELETE") || sql.startsWith("TRUNCATE")
                || sql.startsWith("UPDATE smartlect_stock") || sql.startsWith("UPDATE smartlect_order") || sql.startsWith("UPDATE smartlect_pay")));
        assertFalse(JSON.writeValueAsString(fixture.runs).contains(PASSWORD));
    }

    @Test
    void unresolved_business_and_outbox_states_are_reported_and_never_retired() throws Exception {
        Fixture fixture = new Fixture();
        var user = fixture.originals.get(0).users().get(0).userId();
        fixture.orders = List.of(Map.of("order_id", "order", "user_id", user, "order_status", 0, "pay_order_id", "pay"));
        fixture.payments = List.of(Map.of("trade_id", "trade", "order_id", "order", "user_id", user,
                "pay_order_id", "pay", "trade_status", 0, "pay_channel", "mock"));
        fixture.commands = List.of(Map.of("id", 1, "user_id", user, "status", "PROCESSING"));
        fixture.outboxStatus = 1;
        var inspection = fixture.controller.inspectRun(fixture.inspect()).getData();
        assertFalse(inspection.ready());
        assertTrue(inspection.blockers().containsAll(List.of("pending_or_unknown_orders", "pending_or_unknown_payments", "pending_commands", "pending_outbox")));
        assertEquals(409, assertThrows(HttpBusinessException.class,
                () -> fixture.controller.reset(fixture.reset(inspection.watermarkHash()))).getHttpStatus());
        assertEquals(0, fixture.resourceWrites);
        assertTrue(fixture.writes.isEmpty());
    }

    @Test
    void unknown_scope_bad_password_stale_watermark_and_unregistered_resources_are_rejected() throws Exception {
        Fixture fixture = new Fixture();
        assertEquals(401, assertThrows(HttpBusinessException.class, () -> fixture.controller.inspectRun(
                JSON.valueToTree(Map.of("scenarioRunId", "run", "password", "incorrect")))).getHttpStatus());
        assertEquals(404, assertThrows(HttpBusinessException.class, () -> fixture.controller.inspectRun(
                JSON.valueToTree(Map.of("scenarioRunId", "store", "password", PASSWORD)))).getHttpStatus());
        assertEquals(404, assertThrows(HttpBusinessException.class, () -> fixture.controller.inspectRun(
                JSON.valueToTree(Map.of("scenarioRunId", "unknown", "password", PASSWORD)))).getHttpStatus());
        var before = fixture.controller.inspectRun(fixture.inspect()).getData();
        fixture.outboxStatus = 0;
        assertNotEquals(before.watermarkHash(), fixture.controller.inspectRun(fixture.inspect()).getData().watermarkHash());
        fixture.outboxStatus = 2;
        assertEquals(409, assertThrows(HttpBusinessException.class,
                () -> fixture.controller.reset(fixture.reset("0".repeat(64)))).getHttpStatus());
        fixture.registries.values().iterator().next().put("manifest_json", "{}");
        assertEquals(409, assertThrows(HttpBusinessException.class,
                () -> fixture.controller.inspectRun(fixture.inspect())).getHttpStatus());
        assertEquals(0, fixture.resourceWrites);
        assertTrue(fixture.writes.isEmpty());
    }

    private static class Fixture {
        final JdbcTemplate jdbc = mock(JdbcTemplate.class);
        final RedisComponent redis = mock(RedisComponent.class);
        final DemoScenarioController controller;
        final Map<String, Map<String, Object>> runs = new LinkedHashMap<>(), registries = new LinkedHashMap<>();
        final List<DemoScenarioController.Manifest> originals = new ArrayList<>();
        final Map<String, Integer> userStatus = new HashMap<>(), productStatus = new HashMap<>();
        final List<String> writes = new ArrayList<>();
        List<Map<String, Object>> orders = List.of(), payments = List.of(), commands = List.of();
        int outboxStatus = 2, resourceWrites;
        final AtomicLong sequence = new AtomicLong(10);

        Fixture() throws Exception {
            PasswordService passwords = mock(PasswordService.class);
            when(passwords.encode(PASSWORD)).thenReturn("new-synthetic-hash");
            controller = new DemoScenarioController(jdbc, passwords, redis, PASSWORD, "mock");
            runs.put("run", new HashMap<>(Map.of("scenario_run_id", "run", "state", "ACTIVE")));
            for (int i = 1; i <= 2; i++) {
                var seed = new DemoScenarioController.Seed("run", "branch-" + i, 1, 1, 10);
                var manifest = DemoScenarioController.resources(i, seed);
                originals.add(manifest);
                String request = JSON.writeValueAsString(seed);
                registries.put(manifest.executionScopeId(), new HashMap<>(Map.of("scenario_number", (long) i,
                        "execution_scope_id", manifest.executionScopeId(), "scenario_run_id", "run", "branch_id", seed.branchId(),
                        "fingerprint", HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(request.getBytes(StandardCharsets.UTF_8))),
                        "request_json", request, "manifest_json", JSON.writeValueAsString(manifest))));
                manifest.users().forEach(u -> userStatus.put(u.userId(), 1));
                manifest.products().forEach(p -> productStatus.put(p, 1));
            }
            doAnswer(call -> query(call.getArgument(0), Arrays.copyOfRange(call.getArguments(), 1, call.getArguments().length)))
                    .when(jdbc).queryForList(anyString(), any(Object[].class));
            doAnswer(call -> update(call.getArgument(0), Arrays.copyOfRange(call.getArguments(), 1, call.getArguments().length)))
                    .when(jdbc).update(anyString(), any(Object[].class));
        }

        JsonNode inspect() { return JSON.valueToTree(Map.of("scenarioRunId", "run", "password", PASSWORD)); }
        JsonNode reset(String hash) { return JSON.valueToTree(Map.of("scenarioRunId", "run", "resetRequestId", "reset-once",
                "password", PASSWORD, "expectedWatermarkHash", hash)); }

        List<Map<String, Object>> query(String sql, Object[] args) {
            if (sql.startsWith("SELECT * FROM demo_scenario_run WHERE")) return runs.containsKey(args[0]) ? List.of(runs.get(args[0])) : List.of();
            if (sql.startsWith("SELECT scenario_run_id FROM demo_scenario_run WHERE reset_request_id")) return runs.values().stream()
                    .filter(r -> args[0].equals(r.get("reset_request_id"))).toList();
            if (sql.startsWith("SELECT scenario_run_id FROM demo_scenario_run WHERE scenario_run_id")) return runs.containsKey(args[0]) ? List.of(runs.get(args[0])) : List.of();
            if (sql.startsWith("SELECT * FROM demo_scenario_registry WHERE scenario_run_id")) return registries.values().stream()
                    .filter(r -> args[0].equals(r.get("scenario_run_id"))).toList();
            if (sql.startsWith("SELECT * FROM demo_scenario_registry WHERE execution_scope_id")) return List.of(registries.get(args[0]));
            if (sql.startsWith("SELECT user_id,email,CAST(status AS SIGNED) AS status")) return userStatus.entrySet().stream().sorted(Map.Entry.comparingByKey())
                    .map(e -> Map.<String, Object>of("user_id", e.getKey(), "email", e.getKey() + "@demo.smartlect.local", "status", e.getValue())).toList();
            if (sql.startsWith("SELECT address_id,user_id")) return originals.stream().flatMap(m -> m.users().stream())
                    .map(u -> Map.<String, Object>of("address_id", u.addressId(), "user_id", u.userId())).toList();
            if (sql.startsWith("SELECT product_id,CAST(status AS SIGNED) AS status")) return productStatus.entrySet().stream().sorted(Map.Entry.comparingByKey())
                    .map(e -> Map.<String, Object>of("product_id", e.getKey(), "status", e.getValue())).toList();
            if (sql.startsWith("SELECT p.product_id")) return originals.stream().flatMap(m -> m.skus().stream()).map(s -> Map.<String, Object>of(
                    "product_id", s.productId(), "property_value_id_hash", s.propertyValueIdHash(), "property_value_ids", s.propertyValueIds(),
                    "price", BigDecimal.valueOf(s.priceCents(), 2), "stock", 9)).toList();
            if (sql.startsWith("SELECT order_id,user_id")) return orders;
            if (sql.startsWith("SELECT order_item_id") || sql.startsWith("SELECT DISTINCT o.user_id") || sql.startsWith("SELECT refund_request_id")) return List.of();
            if (sql.startsWith("SELECT trade_id")) return payments;
            if (sql.startsWith("SELECT id,user_id,command_type")) return commands;
            if (sql.contains(".local_message_outbox WHERE")) return sql.contains("smartlect_order.") ? List.of(Map.of("id", 7L, "status", outboxStatus,
                    "idempotency_key", "source-outbox", "payload_json", "{\"schema_version\":2,\"events\":[{\"eventId\":\"original-event\"}]}")) : List.of();
            if (sql.startsWith("SELECT category_name")) return List.of(Map.of("category_name", List.of("数码", "家居", "运动", "阅读")
                    .get(Integer.parseInt(args[0].toString().substring(2))), "p_category_id", "0"));
            throw new AssertionError("Unexpected query: " + sql);
        }

        int update(String sql, Object[] args) {
            writes.add(sql);
            if (sql.startsWith("INSERT INTO demo_scenario_run ")) runs.putIfAbsent((String) args[0], new HashMap<>(Map.of("scenario_run_id", args[0], "state", "ACTIVE")));
            else if (sql.startsWith("INSERT INTO demo_scenario_registry")) registries.putIfAbsent((String) args[0], new HashMap<>(Map.of("scenario_number", sequence.incrementAndGet(),
                    "execution_scope_id", args[0], "scenario_run_id", args[1], "branch_id", args[2], "fingerprint", args[3], "request_json", args[4])));
            else if (sql.startsWith("UPDATE demo_scenario_registry SET manifest_json")) registries.get(args[1]).put("manifest_json", args[0]);
            else if (sql.startsWith("UPDATE smartlect_user.user_info")) { assertTrue(userStatus.containsKey(args[0])); userStatus.put((String) args[0], 0); }
            else if (sql.startsWith("UPDATE smartlect_product.product_info")) { assertTrue(productStatus.containsKey(args[0])); productStatus.put((String) args[0], 0); }
            else if (sql.startsWith("UPDATE demo_scenario_run SET state")) runs.get(args[3]).putAll(Map.of("state", "RETIRED", "reset_request_id", args[0], "reset_fingerprint", args[1], "reset_result_json", args[2]));
            else if (sql.startsWith("INSERT INTO smartlect_")) resourceWrites++;
            else throw new AssertionError("Unexpected mutation: " + sql);
            return 1;
        }
    }
}
