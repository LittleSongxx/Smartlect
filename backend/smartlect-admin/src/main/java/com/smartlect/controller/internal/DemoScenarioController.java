package com.smartlect.controller.internal;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.smartlect.component.RedisComponent;
import com.smartlect.controller.ABaseController;
import com.smartlect.entity.dto.TokenUserInfoDTO;
import com.smartlect.entity.vo.ResponseVO;
import com.smartlect.exception.HttpBusinessException;
import com.smartlect.service.PasswordService;
import com.smartlect.utils.StringTools;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;

/** Owned local scenario resources; the existing fixture and its stock are never reset here. */
@RestController
@RequestMapping("/internal/demo/scenario")
@ConditionalOnProperty(name = "smartlect.demo.enabled", havingValue = "true")
public class DemoScenarioController extends ABaseController {
    private static final ObjectMapper JSON = new ObjectMapper().enable(SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS)
            .enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS);
    private static final String[] CATEGORIES = {"数码", "家居", "运动", "阅读"};
    private final JdbcTemplate jdbc;
    private final PasswordService passwords;
    private final RedisComponent redis;
    private final String password;

    public DemoScenarioController(JdbcTemplate jdbc, PasswordService passwords, RedisComponent redis,
            @Value("${smartlect.demo.password:}") String password,
            @Value("${smartlect.payment.mode:mock}") String paymentMode) {
        if (password.length() < 24 || !"mock".equals(paymentMode)) {
            throw new IllegalStateException("Demo scenarios require a generated password and mock payment mode");
        }
        this.jdbc = jdbc;
        this.passwords = passwords;
        this.redis = redis;
        this.password = password;
    }

    public record Seed(String scenarioRunId, String branchId, int userCount, int productCount, int initialStock) { }
    public record User(String userId, String addressId, int index) { }
    public record Sku(String productId, String propertyValueIdHash, String propertyValueIds,
                      int productIndex, int specIndex, long priceCents, int initialStock) { }
    public record Manifest(String executionScopeId, String scenarioRunId, String branchId, String manifestVersion,
                           int initialStock, List<User> users, List<String> products, List<Sku> skus) { }
    public record RunInspection(String scenarioRunId, String state, List<Manifest> branches, List<String> scopeIds,
                                Map<String, Object> watermark, String watermarkHash, boolean ready, List<String> blockers) { }
    public record ResetResult(String resetRequestId, String retiredRunId, List<String> retiredScopeIds,
                              String replacementRunId, List<Manifest> replacementManifests,
                              Map<String, Object> watermark, String watermarkHash, String mode) { }

    @PostMapping("/seed")
    @Transactional(rollbackFor = Exception.class)
    public ResponseVO<Manifest> seed(@RequestBody JsonNode body) {
        Seed request = parseSeed(body);
        requireActive(lockRun(request.scenarioRunId(), true));
        String scope = scope(request), encoded = encode(request), fingerprint = sha256(encoded);
        // The registry upsert locks this exact scope; all resource writes below are plain INSERTs.
        jdbc.update("INSERT INTO demo_scenario_registry (execution_scope_id,scenario_run_id,branch_id,fingerprint,request_json) "
                + "VALUES (?,?,?,?,?) ON DUPLICATE KEY UPDATE execution_scope_id=execution_scope_id",
                scope, request.scenarioRunId(), request.branchId(), fingerprint, encoded);
        var rows = jdbc.queryForList("SELECT * FROM demo_scenario_registry WHERE execution_scope_id=? FOR UPDATE", scope);
        if (rows.size() != 1) throw new HttpBusinessException(409, "scenario_registry_collision");
        var registry = rows.get(0);
        if (!request.scenarioRunId().equals(registry.get("scenario_run_id"))
                || !request.branchId().equals(registry.get("branch_id")) || !fingerprint.equals(registry.get("fingerprint"))) {
            throw new HttpBusinessException(409, "scenario_configuration_conflict");
        }
        if (registry.get("manifest_json") != null) return getSuccessResponseVO(decode((String) registry.get("manifest_json")));
        Manifest manifest = resources(((Number) registry.get("scenario_number")).longValue(), request);
        try {
            createResources(manifest);
        } catch (DuplicateKeyException collision) {
            throw new HttpBusinessException(409, "scenario_resource_collision");
        }
        jdbc.update("UPDATE demo_scenario_registry SET manifest_json=? WHERE execution_scope_id=?", encode(manifest), scope);
        return getSuccessResponseVO(manifest);
    }

    @PostMapping("/read")
    public ResponseVO<Manifest> read(@RequestBody JsonNode body) {
        fields(body, Set.of("executionScopeId"));
        return getSuccessResponseVO(load(text(body, "executionScopeId", 64)));
    }

    @PostMapping("/session")
    @Transactional(rollbackFor = Exception.class)
    public ResponseVO<Map<String, Object>> session(@RequestBody JsonNode body) {
        fields(body, Set.of("executionScopeId", "userIndex", "password"));
        String scope = text(body, "executionScopeId", 64);
        String supplied = text(body, "password", 256);
        requirePassword(supplied);
        int index = integer(body, "userIndex", 0, 99, -1);
        Manifest manifest = load(scope);
        requireActive(lockRun(manifest.scenarioRunId(), false));
        if (index >= manifest.users().size()) throw new HttpBusinessException(404, "scenario_user_not_found");
        User user = manifest.users().get(index);
        var rows = jdbc.queryForList("SELECT u.user_id,u.password,u.email,u.nick_name FROM smartlect_user.user_info u "
                + "JOIN smartlect_user.user_address a ON a.user_id=u.user_id "
                + "WHERE u.user_id=? AND a.address_id=? AND u.status=1", user.userId(), user.addressId());
        if (rows.size() != 1 || !passwords.matches(supplied, (String) rows.get(0).get("password"))) {
            throw new HttpBusinessException(401, "invalid_demo_credentials");
        }
        var row = rows.get(0);
        TokenUserInfoDTO session = new TokenUserInfoDTO();
        session.setUserId(user.userId());
        session.setEmail((String) row.get("email"));
        session.setNickName((String) row.get("nick_name"));
        return getSuccessResponseVO(Map.of("executionScopeId", scope, "userId", user.userId(),
                "addressId", user.addressId(), "userIndex", index, "token", redis.saveTokenUserInfo(session)));
    }

    @PostMapping("/inspect-run")
    @Transactional(rollbackFor = Exception.class)
    public ResponseVO<RunInspection> inspectRun(@RequestBody JsonNode body) {
        fields(body, Set.of("scenarioRunId", "password"));
        requirePassword(text(body, "password", 256));
        return getSuccessResponseVO(inspectLocked(lockRun(text(body, "scenarioRunId", 64), false)));
    }

    @PostMapping("/reset-result")
    @Transactional(rollbackFor = Exception.class)
    public ResponseVO<ResetResult> resetResult(@RequestBody JsonNode body) {
        fields(body, Set.of("scenarioRunId", "password"));
        requirePassword(text(body, "password", 256));
        Map<String, Object> run = lockRun(text(body, "scenarioRunId", 64), false);
        return getSuccessResponseVO(run.get("reset_result_json") == null ? null : decodeReset((String) run.get("reset_result_json")));
    }

    @PostMapping("/reset")
    @Transactional(rollbackFor = Exception.class)
    public ResponseVO<ResetResult> reset(@RequestBody JsonNode body) {
        fields(body, Set.of("scenarioRunId", "resetRequestId", "password", "expectedWatermarkHash"));
        requirePassword(text(body, "password", 256));
        String runId = text(body, "scenarioRunId", 64), requestId = text(body, "resetRequestId", 64);
        String expected = text(body, "expectedWatermarkHash", 64);
        if (!expected.matches("[0-9a-f]{64}")) throw new HttpBusinessException(422, "invalid_scenario_watermark");
        String fingerprint = sha256(encode(Map.of("scenarioRunId", runId, "resetRequestId", requestId,
                "expectedWatermarkHash", expected)));
        Map<String, Object> run = lockRun(runId, false);
        if (run.get("reset_result_json") != null) {
            if (!requestId.equals(run.get("reset_request_id")) || !fingerprint.equals(run.get("reset_fingerprint"))) {
                throw new HttpBusinessException(409, "scenario_reset_conflict");
            }
            ResetResult result = decodeReset((String) run.get("reset_result_json"));
            clearLatestSessionsAfterCommit(manifests(runId));
            return getSuccessResponseVO(result);
        }
        requireActive(run);
        var reused = jdbc.queryForList("SELECT scenario_run_id FROM demo_scenario_run WHERE reset_request_id=?", requestId);
        if (!reused.isEmpty()) throw new HttpBusinessException(409, "scenario_reset_conflict");
        RunInspection inspected = inspectLocked(run);
        if (!inspected.ready()) throw new HttpBusinessException(409, "scenario_not_quiescent");
        if (!expected.equals(inspected.watermarkHash())) throw new HttpBusinessException(409, "scenario_watermark_conflict");
        String replacementRun = "reset-" + sha256(runId + '\0' + requestId).substring(0, 32);
        if (!jdbc.queryForList("SELECT scenario_run_id FROM demo_scenario_run WHERE scenario_run_id=? FOR UPDATE", replacementRun).isEmpty()) {
            throw new HttpBusinessException(409, "scenario_replacement_already_exists");
        }
        // Growth must fence the old scopes and resolve its in-flight commands before this endpoint.
        // No payment, cancellation, refund, stock refill or historical fact deletion is performed.
        for (Manifest manifest : inspected.branches()) {
            for (User user : manifest.users()) jdbc.update("UPDATE smartlect_user.user_info SET status=0 WHERE user_id=?", user.userId());
            for (String product : manifest.products()) jdbc.update("UPDATE smartlect_product.product_info SET status=0 WHERE product_id=? AND status=1", product);
        }
        List<Manifest> replacements = new ArrayList<>();
        for (Manifest manifest : inspected.branches()) {
            Seed replacement = new Seed(replacementRun, manifest.branchId(), manifest.users().size(),
                    manifest.products().size(), manifest.initialStock());
            replacements.add(seed(JSON.valueToTree(replacement)).getData());
        }
        ResetResult result = new ResetResult(requestId, runId, inspected.scopeIds(), replacementRun, List.copyOf(replacements),
                inspected.watermark(), inspected.watermarkHash(), "retire_and_replace");
        String savedResult = encode(result);
        try {
            jdbc.update("UPDATE demo_scenario_run SET state='RETIRED',reset_request_id=?,reset_fingerprint=?,reset_result_json=?,retired_at=NOW(6) WHERE scenario_run_id=?",
                    requestId, fingerprint, savedResult, runId);
        } catch (DuplicateKeyException collision) {
            throw new HttpBusinessException(409, "scenario_reset_conflict");
        }
        clearLatestSessionsAfterCommit(inspected.branches());
        return getSuccessResponseVO(decodeReset(savedResult));
    }

    private Map<String, Object> lockRun(String runId, boolean create) {
        if ("store".equals(runId)) throw new HttpBusinessException(404, "scenario_run_not_found");
        if (create) jdbc.update("INSERT INTO demo_scenario_run (scenario_run_id) VALUES (?) ON DUPLICATE KEY UPDATE scenario_run_id=scenario_run_id", runId);
        var rows = jdbc.queryForList("SELECT * FROM demo_scenario_run WHERE scenario_run_id=? FOR UPDATE", runId);
        if (rows.size() != 1) throw new HttpBusinessException(404, "scenario_run_not_found");
        return rows.get(0);
    }

    private static void requireActive(Map<String, Object> run) {
        if (!"ACTIVE".equals(run.get("state"))) throw new HttpBusinessException(410, "scenario_run_retired");
    }

    private void requirePassword(String supplied) {
        if (!MessageDigest.isEqual(password.getBytes(StandardCharsets.UTF_8), supplied.getBytes(StandardCharsets.UTF_8))) {
            throw new HttpBusinessException(401, "invalid_demo_credentials");
        }
    }

    private List<Manifest> manifests(String runId) {
        var rows = jdbc.queryForList("SELECT * FROM demo_scenario_registry WHERE scenario_run_id=? ORDER BY branch_id FOR UPDATE", runId);
        if (rows.isEmpty()) throw new HttpBusinessException(404, "scenario_run_not_found");
        // ponytail: local reset inspects at most 32 branches; paginate the ownership audit before raising this ceiling.
        if (rows.size() > 32) throw new HttpBusinessException(409, "scenario_reset_branch_limit");
        List<Manifest> result = new ArrayList<>();
        for (var row : rows) {
            Seed request;
            try { request = JSON.readValue((String) row.get("request_json"), Seed.class); }
            catch (JsonProcessingException invalid) { throw new HttpBusinessException(409, "scenario_ownership_mismatch"); }
            Manifest expected = resources(((Number) row.get("scenario_number")).longValue(), request);
            if (!runId.equals(request.scenarioRunId()) || !expected.executionScopeId().equals(row.get("execution_scope_id"))
                    || !request.branchId().equals(row.get("branch_id")) || !sha256(encode(request)).equals(row.get("fingerprint"))
                    || row.get("manifest_json") == null || !expected.equals(decode((String) row.get("manifest_json")))) {
                throw new HttpBusinessException(409, "scenario_ownership_mismatch");
            }
            result.add(expected);
        }
        return List.copyOf(result);
    }

    private void clearLatestSessionsAfterCommit(List<Manifest> branches) {
        Runnable clean = () -> branches.forEach(manifest -> manifest.users().forEach(user -> redis.cleanAllToken(user.userId())));
        if (TransactionSynchronizationManager.isSynchronizationActive()) {
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                @Override public void afterCommit() { clean.run(); }
            });
        } else clean.run();
    }

    private RunInspection inspectLocked(Map<String, Object> run) {
        String runId = (String) run.get("scenario_run_id");
        List<Manifest> branches = manifests(runId);
        List<String> users = branches.stream().flatMap(m -> m.users().stream()).map(User::userId).sorted().toList();
        List<String> products = branches.stream().flatMap(m -> m.products().stream()).sorted().toList();
        List<User> addresses = branches.stream().flatMap(m -> m.users().stream()).toList();
        List<Sku> skus = branches.stream().flatMap(m -> m.skus().stream()).toList();
        if (new HashSet<>(users).size() != users.size() || new HashSet<>(products).size() != products.size()) {
            throw new HttpBusinessException(409, "scenario_ownership_mismatch");
        }
        var userRows = byIds("SELECT user_id,email,CAST(status AS SIGNED) AS status FROM smartlect_user.user_info WHERE user_id IN (%s) ORDER BY user_id FOR UPDATE", users);
        if (userRows.size() != users.size() || userRows.stream().anyMatch(r -> !users.contains(r.get("user_id"))
                || !(r.get("user_id") + "@demo.smartlect.local").equals(r.get("email"))
                || !(r.get("status") instanceof Number n) || n.intValue() < 0 || n.intValue() > 1)) {
            throw new HttpBusinessException(409, "scenario_ownership_mismatch");
        }
        var addressRows = byIds("SELECT address_id,user_id FROM smartlect_user.user_address WHERE address_id IN (%s) ORDER BY address_id FOR UPDATE",
                addresses.stream().map(User::addressId).sorted().toList());
        if (addressRows.size() != addresses.size() || addressRows.stream().anyMatch(r -> addresses.stream().noneMatch(
                a -> a.addressId().equals(r.get("address_id")) && a.userId().equals(r.get("user_id"))))) {
            throw new HttpBusinessException(409, "scenario_ownership_mismatch");
        }
        var productRows = byIds("SELECT product_id,CAST(status AS SIGNED) AS status FROM smartlect_product.product_info WHERE product_id IN (%s) ORDER BY product_id FOR UPDATE", products);
        var skuRows = byIds("SELECT p.product_id,p.property_value_id_hash,p.property_value_ids,p.price,s.stock FROM smartlect_product.product_sku p "
                + "JOIN smartlect_stock.sku_stock s ON s.product_id=p.product_id AND s.property_value_id_hash=p.property_value_id_hash "
                + "WHERE p.product_id IN (%s) ORDER BY p.product_id,p.property_value_id_hash", products);
        if (productRows.size() != products.size() || skuRows.size() != skus.size() || skuRows.stream().anyMatch(r -> skus.stream().noneMatch(
                s -> s.productId().equals(r.get("product_id")) && s.propertyValueIdHash().equals(r.get("property_value_id_hash"))
                        && s.propertyValueIds().equals(r.get("property_value_ids"))))) {
            throw new HttpBusinessException(409, "scenario_ownership_mismatch");
        }
        var orders = byIds("SELECT order_id,user_id,CAST(order_status AS SIGNED) AS order_status,pay_order_id,amount FROM smartlect_order.order_info WHERE user_id IN (%s) ORDER BY order_id FOR UPDATE", users);
        List<String> orderIds = orders.stream().map(r -> (String) r.get("order_id")).toList();
        var items = byIds("SELECT order_item_id,order_id,product_id,property_value_id_hash,buy_count,paid_amount,refunded_amount,CAST(order_item_status AS SIGNED) AS order_item_status "
                + "FROM smartlect_order.order_item WHERE order_id IN (%s) ORDER BY order_item_id FOR UPDATE", orderIds);
        var buyers = byIds("SELECT DISTINCT o.user_id FROM smartlect_order.order_item i JOIN smartlect_order.order_info o ON o.order_id=i.order_id "
                + "WHERE i.product_id IN (%s) ORDER BY o.user_id", products);
        if (buyers.stream().anyMatch(r -> !users.contains(r.get("user_id"))) || items.stream().anyMatch(r -> skus.stream().noneMatch(
                s -> s.productId().equals(r.get("product_id")) && s.propertyValueIdHash().equals(r.get("property_value_id_hash"))))) {
            throw new HttpBusinessException(409, "scenario_transaction_ownership_mismatch");
        }
        var payments = byIds("SELECT trade_id,order_id,user_id,pay_order_id,CAST(trade_status AS SIGNED) AS trade_status,pay_amount,pay_channel FROM smartlect_pay.pay_trade_record "
                + "WHERE user_id IN (%s) ORDER BY trade_id FOR UPDATE", users);
        var refunds = byIds("SELECT refund_request_id,refund_order_no,order_id,user_id,product_id,property_value_id_hash,status,refund_amount "
                + "FROM smartlect_order.refund_request WHERE user_id IN (%s) ORDER BY refund_request_id FOR UPDATE", users);
        if (payments.stream().anyMatch(r -> !orderIds.contains(r.get("order_id"))) || refunds.stream().anyMatch(r ->
                !orderIds.contains(r.get("order_id")) || skus.stream().noneMatch(s -> s.productId().equals(r.get("product_id"))
                        && s.propertyValueIdHash().equals(r.get("property_value_id_hash"))))) {
            throw new HttpBusinessException(409, "scenario_transaction_ownership_mismatch");
        }
        var commands = byIds("SELECT id,user_id,command_type,idempotency_key,request_hash,status FROM smartlect_order.order_request_idempotency "
                + "WHERE user_id IN (%s) ORDER BY id FOR UPDATE", users);
        Set<String> references = new TreeSet<>(users);
        references.addAll(products); references.addAll(orderIds);
        payments.forEach(r -> references.add((String) r.get("pay_order_id")));
        refunds.forEach(r -> { references.add((String) r.get("refund_request_id")); references.add((String) r.get("refund_order_no")); });
        List<Map<String, Object>> outboxes = outboxes(references);
        List<String> blockers = new ArrayList<>();
        if (!"ACTIVE".equals(run.get("state"))) blockers.add("retired_run");
        if (orders.stream().anyMatch(r -> !(r.get("order_status") instanceof Number n) || n.intValue() == 0 || n.intValue() < -1 || n.intValue() > 8)) blockers.add("pending_or_unknown_orders");
        if (payments.stream().anyMatch(r -> !(r.get("trade_status") instanceof Number n) || n.intValue() < 1 || n.intValue() > 3)) blockers.add("pending_or_unknown_payments");
        if (payments.stream().anyMatch(r -> !"mock".equals(r.get("pay_channel")))) blockers.add("non_mock_payments");
        if (orders.stream().anyMatch(o -> o.get("order_status") instanceof Number n && Set.of(1,2,3,6,7,8).contains(n.intValue())
                && payments.stream().noneMatch(p -> o.get("pay_order_id") != null && o.get("pay_order_id").equals(p.get("pay_order_id"))
                && p.get("trade_status") instanceof Number status && Set.of(1,3).contains(status.intValue())))) blockers.add("payment_state_mismatch");
        if (refunds.stream().anyMatch(r -> !Set.of("COMPLETED", "REJECTED").contains(r.get("status")))) blockers.add("pending_refunds");
        if (commands.stream().anyMatch(r -> !Set.of("COMPLETED", "FAILED").contains(r.get("status")))) blockers.add("pending_commands");
        if (outboxes.stream().anyMatch(r -> !(r.get("status") instanceof Number n) || n.intValue() != 2)) blockers.add("pending_outbox");
        Map<String, Object> watermark = new LinkedHashMap<>();
        watermark.put("manifestHashes", branches.stream().map(m -> Map.of("executionScopeId", m.executionScopeId(), "sha256", sha256(encode(m)))).toList());
        watermark.put("users", userRows.stream().map(r -> Map.of("userId", r.get("user_id"), "status", r.get("status"))).toList());
        watermark.put("products", productRows); watermark.put("skus", skuRows);
        watermark.put("orders", orders); watermark.put("items", items); watermark.put("payments", payments);
        watermark.put("refunds", refunds); watermark.put("commands", commands); watermark.put("outbox", outboxes);
        return new RunInspection(runId, (String) run.get("state"), branches, branches.stream().map(Manifest::executionScopeId).toList(),
                watermark, sha256(encode(watermark)), blockers.isEmpty(), List.copyOf(blockers));
    }

    private List<Map<String, Object>> byIds(String query, List<String> identifiers) {
        if (identifiers.isEmpty()) return List.of();
        return jdbc.queryForList(query.formatted(String.join(",", Collections.nCopies(identifiers.size(), "?"))), identifiers.toArray());
    }

    private List<Map<String, Object>> outboxes(Set<String> references) {
        List<Map<String, Object>> result = new ArrayList<>();
        String matching = String.join(" OR ", Collections.nCopies(references.size(), "JSON_SEARCH(payload_json,'one',?) IS NOT NULL"));
        Object[] parameters = references.stream().map(s -> s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")).toArray();
        // ponytail: exact-ID JSON scans cover this bounded local fixture; index a durable owner column if reset volume grows.
        for (String service : List.of("admin", "user", "product", "cart", "order", "pay")) {
            var rows = jdbc.queryForList("SELECT id,CAST(status AS SIGNED) AS status,idempotency_key,payload_json FROM smartlect_" + service
                    + ".local_message_outbox WHERE " + matching + " ORDER BY id", parameters);
            for (var row : rows) {
                String payload = (String) row.get("payload_json");
                List<String> eventIds = new ArrayList<>();
                try {
                    JsonNode events = JSON.readTree(payload).path("events");
                    for (JsonNode event : events) if (event.path("eventId").isTextual()) eventIds.add(event.path("eventId").textValue());
                } catch (JsonProcessingException invalid) { throw new HttpBusinessException(409, "scenario_outbox_invalid"); }
                result.add(Map.of("service", service, "id", row.get("id"), "status", row.get("status"),
                        "idempotencyKey", row.get("idempotency_key"), "payloadHash", sha256(payload), "eventIds", List.copyOf(eventIds)));
            }
        }
        return List.copyOf(result);
    }

    private void createResources(Manifest manifest) {
        String hash = passwords.encode(password);
        for (User user : manifest.users()) {
            jdbc.update("INSERT INTO smartlect_user.user_info (user_id,nick_name,email,password,sex,join_time,status) "
                    + "VALUES (?,?,?,?,2,NOW(),1)", user.userId(), "场景用户" + user.userId(),
                    user.userId() + "@demo.smartlect.local", hash);
            jdbc.update("INSERT INTO smartlect_user.user_address (address_id,user_id,address,addressee,phone,default_type) "
                    + "VALUES (?,?,?,?,?,1)", user.addressId(), user.userId(), "Smartlect模拟收货地址", "模拟用户", "13800000000");
        }
        // Categories are explicit shared constants, not inventory or per-branch resources.
        for (int index = 0; index < CATEGORIES.length; index++) {
            String category = "S9" + index;
            jdbc.update("INSERT INTO smartlect_product.sys_category (category_id,category_name,p_category_id,sort) "
                    + "VALUES (?,?,'0',?) ON DUPLICATE KEY UPDATE category_id=category_id", category, CATEGORIES[index], index);
            var rows = jdbc.queryForList("SELECT category_name,p_category_id FROM smartlect_product.sys_category WHERE category_id=?", category);
            if (rows.size() != 1 || !CATEGORIES[index].equals(rows.get(0).get("category_name"))
                    || !"0".equals(rows.get(0).get("p_category_id"))) {
                throw new HttpBusinessException(409, "scenario_category_collision");
            }
        }
        for (int index = 0; index < manifest.products().size(); index++) {
            String id = manifest.products().get(index);
            BigDecimal price = BigDecimal.valueOf(1000L + index * 325L, 2);
            jdbc.update("INSERT INTO smartlect_product.product_info "
                    + "(product_id,product_name,product_desc,create_time,category_id,p_category_id,status,min_price,max_price,total_sale,commend_type) "
                    + "VALUES (?,?,?,NOW(),?,'0',1,?,?,0,0)", id, "Smartlect" + CATEGORIES[index % 4] + index,
                    "独立场景合成商品，无预置销量", "S9" + (index % 4), price, price.add(new BigDecimal("1.50")));
        }
        for (Sku sku : manifest.skus()) {
            jdbc.update("INSERT INTO smartlect_product.product_property_value "
                    + "(product_id,property_id,property_name,property_sort,cover_type,property_value_id,property_value,sort) "
                    + "VALUES (?,'9000','规格',0,0,?,?,?)", sku.productId(), sku.propertyValueIds(),
                    sku.specIndex() == 0 ? "标准" : "加大", sku.specIndex());
            jdbc.update("INSERT INTO smartlect_product.product_sku "
                    + "(product_id,property_value_id_hash,property_value_ids,price,sort) VALUES (?,?,?,?,?)",
                    sku.productId(), sku.propertyValueIdHash(), sku.propertyValueIds(), BigDecimal.valueOf(sku.priceCents(), 2), sku.specIndex());
            jdbc.update("INSERT INTO smartlect_stock.sku_stock (product_id,property_value_id_hash,stock) VALUES (?,?,?)",
                    sku.productId(), sku.propertyValueIdHash(), sku.initialStock());
        }
    }

    private Manifest load(String scope) {
        var rows = jdbc.queryForList("SELECT manifest_json FROM demo_scenario_registry WHERE execution_scope_id=?", String.class, scope);
        if (rows.size() != 1 || rows.get(0) == null) throw new HttpBusinessException(404, "scenario_not_found");
        Manifest result = decode(rows.get(0));
        if (!scope.equals(result.executionScopeId())) throw new IllegalStateException("Scenario manifest scope mismatch");
        return result;
    }

    static Seed parseSeed(JsonNode body) {
        if (body == null || !body.isObject()) throw new HttpBusinessException(422, "invalid_scenario_request");
        Set<String> allowed = Set.of("scenarioRunId", "branchId", "userCount", "productCount", "initialStock");
        body.fieldNames().forEachRemaining(field -> {
            if (!allowed.contains(field)) throw new HttpBusinessException(422, "invalid_scenario_request");
        });
        return new Seed(text(body, "scenarioRunId", 64), text(body, "branchId", 32),
                integer(body, "userCount", 1, 100, 100), integer(body, "productCount", 1, 20, 20),
                integer(body, "initialStock", 1, 100, 10));
    }

    static Manifest resources(long number, Seed request) {
        // ponytail: reserved 10-digit user IDs support 7,999,999 scopes; widen the Java schema before increasing this.
        if (number < 1 || number > 7_999_999) throw new HttpBusinessException(409, "scenario_identifier_capacity_reached");
        List<User> users = new ArrayList<>();
        List<String> products = new ArrayList<>();
        List<Sku> skus = new ArrayList<>();
        for (int i = 0; i < request.userCount(); i++) {
            String id = String.valueOf(9_200_000_000L + number * 100 + i);
            users.add(new User(id, "SD" + id, i));
        }
        for (int i = 0; i < request.productCount(); i++) {
            String id = String.valueOf(930_000_000_000_000L + number * 100 + i);
            products.add(id);
            for (int spec = 0; spec < 2; spec++) {
                String valueId = String.valueOf(940_000_000_000_000L + number * 1000 + i * 2L + spec);
                skus.add(new Sku(id, StringTools.encodeByMD5(valueId), valueId, i, spec,
                        1000L + i * 325L + spec * 150L, request.initialStock()));
            }
        }
        return new Manifest(scope(request), request.scenarioRunId(), request.branchId(), "demo-scenario-v1",
                request.initialStock(), users, products, skus);
    }

    private static String scope(Seed request) {
        return "demo-" + sha256(request.scenarioRunId() + '\0' + request.branchId()).substring(0, 32);
    }

    private static void fields(JsonNode body, Set<String> expected) {
        if (body == null || !body.isObject() || body.size() != expected.size()) throw new HttpBusinessException(422, "invalid_scenario_request");
        body.fieldNames().forEachRemaining(field -> {
            if (!expected.contains(field)) throw new HttpBusinessException(422, "invalid_scenario_request");
        });
    }

    private static String text(JsonNode body, String field, int max) {
        JsonNode node = body.path(field);
        if (!node.isTextual() || node.textValue().isBlank() || node.textValue().length() > max || node.textValue().indexOf('\0') >= 0) {
            throw new HttpBusinessException(422, "invalid_scenario_" + field);
        }
        return node.textValue();
    }

    private static int integer(JsonNode body, String field, int min, int max, int fallback) {
        JsonNode node = body.get(field);
        if (node == null && fallback >= min) return fallback;
        if (node == null || !node.isIntegralNumber() || !node.canConvertToInt() || node.intValue() < min || node.intValue() > max) {
            throw new HttpBusinessException(422, "invalid_scenario_" + field);
        }
        return node.intValue();
    }

    private static String sha256(String value) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));
        } catch (java.security.NoSuchAlgorithmException impossible) {
            throw new IllegalStateException(impossible);
        }
    }

    private static String encode(Object value) {
        try {
            return JSON.writeValueAsString(value);
        } catch (JsonProcessingException impossible) {
            throw new IllegalStateException(impossible);
        }
    }

    private static Manifest decode(String value) {
        try {
            return JSON.readValue(value, Manifest.class);
        } catch (JsonProcessingException invalid) {
            throw new IllegalStateException("Invalid persisted scenario manifest", invalid);
        }
    }

    private static ResetResult decodeReset(String value) {
        try { return JSON.readValue(value, ResetResult.class); }
        catch (JsonProcessingException invalid) { throw new IllegalStateException("Invalid persisted scenario reset receipt", invalid); }
    }
}
