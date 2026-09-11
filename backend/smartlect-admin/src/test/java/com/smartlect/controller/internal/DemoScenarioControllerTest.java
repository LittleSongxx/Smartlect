package com.smartlect.controller.internal;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.smartlect.component.RedisComponent;
import com.smartlect.controller.AGlobalExceptionHandlerController;
import com.smartlect.exception.HttpBusinessException;
import com.smartlect.service.PasswordService;
import com.smartlect.web.InternalApiAuthFilter;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class DemoScenarioControllerTest {
    private static final ObjectMapper JSON = new ObjectMapper();
    private static final String PASSWORD = "synthetic-demo-password-for-tests-only";

    @Test
    void scopes_have_disjoint_real_identifier_ranges_and_identical_template_features() throws Exception {
        var request = DemoScenarioController.parseSeed(JSON.readTree("{\"scenarioRunId\":\"run\",\"branchId\":\"rule\"}"));
        assertEquals(100, request.userCount());
        assertEquals(20, request.productCount());
        var first = DemoScenarioController.resources(1, request);
        var other = DemoScenarioController.resources(2, new DemoScenarioController.Seed("run", "joint", 100, 20, 10));
        assertEquals(first, DemoScenarioController.resources(1, request));
        assertNotEquals(first.executionScopeId(), other.executionScopeId());
        assertEquals(40, first.skus().size());
        var users = new HashSet<>(first.users().stream().map(DemoScenarioController.User::userId).toList());
        assertTrue(other.users().stream().noneMatch(user -> users.contains(user.userId())));
        assertTrue(other.products().stream().noneMatch(first.products()::contains));
        assertTrue(first.users().stream().allMatch(user -> user.userId().matches("[0-9]{10}") && user.addressId().length() <= 15));
        assertTrue(first.products().stream().allMatch(id -> id.matches("[0-9]{15}")));
        for (int i = 0; i < 40; i++) {
            assertEquals(first.skus().get(i).priceCents(), other.skus().get(i).priceCents());
            assertEquals(first.skus().get(i).initialStock(), other.skus().get(i).initialStock());
            assertNotEquals(first.skus().get(i).propertyValueIdHash(), other.skus().get(i).propertyValueIdHash());
            assertTrue(first.skus().get(i).propertyValueIdHash().matches("[0-9a-f]{32}"));
        }
        assertEquals("9999999999", DemoScenarioController.resources(7_999_999, request).users().get(99).userId());
        assertThrows(HttpBusinessException.class, () -> DemoScenarioController.resources(8_000_000, request));
    }

    @Test
    void replay_never_inserts_resources_or_refills_and_config_change_conflicts() throws Exception {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        var controller = new DemoScenarioController(jdbc, mock(PasswordService.class), mock(RedisComponent.class), PASSWORD, "mock");
        JsonNode body = JSON.readTree("{\"scenarioRunId\":\"run\",\"branchId\":\"rule\",\"userCount\":1,\"productCount\":1}");
        var manifest = DemoScenarioController.resources(1, DemoScenarioController.parseSeed(body));
        Map<String, Object> registry = new HashMap<>();
        registry.put("scenario_run_id", "run");
        registry.put("branch_id", "rule");
        registry.put("manifest_json", JSON.writeValueAsString(manifest));
        doAnswer(call -> {
            registry.putIfAbsent("fingerprint", call.getArgument(4));
            return 1;
        }).when(jdbc).update(startsWith("INSERT INTO demo_scenario_registry"), any(), any(), any(), any(), any());
        when(jdbc.queryForList(startsWith("SELECT * FROM demo_scenario_registry"), anyString())).thenReturn(List.of(registry));
        activeRun(jdbc);
        assertEquals(manifest, controller.seed(body).getData());
        assertEquals(manifest, controller.seed(body).getData());
        JsonNode changed = JSON.readTree("{\"scenarioRunId\":\"run\",\"branchId\":\"rule\",\"userCount\":2,\"productCount\":1}");
        assertEquals(409, assertThrows(HttpBusinessException.class, () -> controller.seed(changed)).getHttpStatus());
        verify(jdbc, never()).update(contains("smartlect_stock"), any(Object[].class));
        verify(jdbc, never()).update(contains("smartlect_user"), any(Object[].class));
    }

    @Test
    void session_uses_only_registered_active_user_and_current_demo_password() throws Exception {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        PasswordService passwords = mock(PasswordService.class);
        RedisComponent redis = mock(RedisComponent.class);
        var controller = new DemoScenarioController(jdbc, passwords, redis, PASSWORD, "mock");
        var manifest = DemoScenarioController.resources(3, new DemoScenarioController.Seed("run", "content", 1, 1, 3));
        var user = manifest.users().get(0);
        activeRun(jdbc);
        when(jdbc.queryForList(startsWith("SELECT manifest_json"), eq(String.class), eq(manifest.executionScopeId())))
                .thenReturn(List.of(JSON.writeValueAsString(manifest)));
        when(jdbc.queryForList(startsWith("SELECT u.user_id"), eq(user.userId()), eq(user.addressId())))
                .thenReturn(List.of(Map.of("user_id", user.userId(), "password", "stored-hash", "email", "synthetic@example.test", "nick_name", "synthetic-user")));
        when(passwords.matches(PASSWORD, "stored-hash")).thenReturn(true);
        when(redis.saveTokenUserInfo(any())).thenReturn("real-redis-session-api-result");
        JsonNode body = JSON.valueToTree(Map.of("executionScopeId", manifest.executionScopeId(), "userIndex", 0, "password", PASSWORD));
        assertEquals(user.userId(), controller.session(body).getData().get("userId"));
        verify(redis).saveTokenUserInfo(argThat(value -> user.userId().equals(value.getUserId())
                && "synthetic@example.test".equals(value.getEmail())));
        JsonNode wrong = JSON.valueToTree(Map.of("executionScopeId", manifest.executionScopeId(), "userIndex", 0, "password", "wrong"));
        assertEquals(401, assertThrows(HttpBusinessException.class, () -> controller.session(wrong)).getHttpStatus());
        JsonNode missing = JSON.valueToTree(Map.of("executionScopeId", manifest.executionScopeId(), "userIndex", 1, "password", PASSWORD));
        assertEquals(404, assertThrows(HttpBusinessException.class, () -> controller.session(missing)).getHttpStatus());
        verify(redis, times(1)).saveTokenUserInfo(any());
        assertThrows(IllegalStateException.class, () -> new DemoScenarioController(jdbc, passwords, redis, PASSWORD, "live"));
    }

    @Test
    void existing_resource_collision_is_rejected_instead_of_ignoring_ownership() throws Exception {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        PasswordService passwords = mock(PasswordService.class);
        when(passwords.encode(PASSWORD)).thenReturn("new-user-hash");
        var controller = new DemoScenarioController(jdbc, passwords, mock(RedisComponent.class), PASSWORD, "mock");
        var registry = new HashMap<String, Object>();
        registry.put("scenario_run_id", "run");
        registry.put("branch_id", "collision");
        registry.put("scenario_number", 4L);
        doAnswer(call -> {
            registry.put("fingerprint", call.getArgument(4));
            return 1;
        }).when(jdbc).update(startsWith("INSERT INTO demo_scenario_registry"), any(), any(), any(), any(), any());
        when(jdbc.queryForList(startsWith("SELECT * FROM demo_scenario_registry"), anyString())).thenReturn(List.of(registry));
        activeRun(jdbc);
        doThrow(new DuplicateKeyException("synthetic existing user collision"))
                .when(jdbc).update(startsWith("INSERT INTO smartlect_user.user_info"), any(), any(), any(), any());
        JsonNode body = JSON.readTree("{\"scenarioRunId\":\"run\",\"branchId\":\"collision\",\"userCount\":1,\"productCount\":1}");
        assertEquals(409, assertThrows(HttpBusinessException.class, () -> controller.seed(body)).getHttpStatus());
        verify(jdbc, never()).update(contains("SET manifest_json"), any(), any());
        verify(jdbc, never()).update(contains("smartlect_stock"), any(Object[].class));
    }

    @Test
    void trust_boundary_rejects_missing_internal_token_and_coerced_or_extra_fields() throws Exception {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        var controller = new DemoScenarioController(jdbc, mock(PasswordService.class), mock(RedisComponent.class), PASSWORD, "mock");
        InternalApiAuthFilter filter = new InternalApiAuthFilter();
        ReflectionTestUtils.setField(filter, "expectedToken", "synthetic-internal");
        ReflectionTestUtils.setField(filter, "authEnabled", true);
        var mvc = MockMvcBuilders.standaloneSetup(controller).addFilters(filter)
                .setControllerAdvice(new AGlobalExceptionHandlerController()).build();
        mvc.perform(post("/internal/demo/scenario/seed").contentType(MediaType.APPLICATION_JSON)
                .content("{\"scenarioRunId\":\"run\",\"branchId\":\"rule\"}")).andExpect(status().isUnauthorized());
        mvc.perform(post("/internal/demo/scenario/reset").contentType(MediaType.APPLICATION_JSON)
                .content("{}")).andExpect(status().isUnauthorized());
        for (String extra : List.of("\"userCount\":true", "\"userCount\":1.0", "\"userCount\":\"1\"",
                "\"userCount\":0", "\"productCount\":21", "\"initialStock\":101", "\"executionScopeId\":\"store\"", "\"refill\":true")) {
            mvc.perform(post("/internal/demo/scenario/seed").header("X-Internal-Token", "synthetic-internal")
                    .contentType(MediaType.APPLICATION_JSON).content("{\"scenarioRunId\":\"run\",\"branchId\":\"rule\"," + extra + "}"))
                    .andExpect(status().isUnprocessableEntity());
        }
        verifyNoInteractions(jdbc);
    }

    private static void activeRun(JdbcTemplate jdbc) {
        when(jdbc.queryForList(startsWith("SELECT * FROM demo_scenario_run WHERE"), eq("run")))
                .thenReturn(List.of(Map.of("scenario_run_id", "run", "state", "ACTIVE")));
    }
}
