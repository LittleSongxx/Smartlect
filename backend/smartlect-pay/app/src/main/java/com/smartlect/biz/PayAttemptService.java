package com.smartlect.biz;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.smartlect.exception.HttpBusinessException;
import com.smartlect.integration.CommerceOutcomeClient;
import com.smartlect.security.DelegatedUserIdentity;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.Map;

/** Java mock provider owns these attempt outcomes; no payment/stock/financial state is changed. */
@Service
@ConditionalOnProperty(name = "smartlect.payment.mode", havingValue = "mock", matchIfMissing = true)
public class PayAttemptService {
    private static final ObjectMapper JSON = new ObjectMapper();
    private final JdbcTemplate jdbc;
    private final CommerceOutcomeClient outcomes;

    public PayAttemptService(JdbcTemplate jdbc, CommerceOutcomeClient outcomes) {
        this.jdbc = jdbc;
        this.outcomes = outcomes;
    }

    public record Request(String attemptId, String payOrderId) { }
    public record Attempt(String attemptId, String payOrderId, String orderId, String userId,
                          String payChannel, String attemptStatus, String reasonCode, String paymentMode,
                          long attemptedAmountCents, String currency, String occurredAt, String eventId) { }

    public static Request parse(JsonNode body) {
        if (body == null || !body.isObject() || body.size() != 2
                || !body.path("attemptId").isTextual() || !body.path("payOrderId").isTextual()) {
            throw new HttpBusinessException(422, "invalid_payment_attempt_request");
        }
        return new Request(text(body.get("attemptId").textValue(), 64),
                text(body.get("payOrderId").textValue(), 32));
    }

    @Transactional(rollbackFor = Exception.class)
    public Attempt decline(String userId, Request request) {
        validate(userId, request);
        var intents = jdbc.queryForList("SELECT pay_order_id,order_id,user_id,pay_channel,pay_amount,CAST(trade_status AS SIGNED) AS trade_status "
                + "FROM pay_trade_record WHERE pay_order_id=? FOR UPDATE", request.payOrderId());
        if (intents.isEmpty()) throw new HttpBusinessException(404, "payment_intent_not_found");
        Map<String, Object> intent = intents.get(0);
        DelegatedUserIdentity.requireOwner(userId, (String) intent.get("user_id"));
        if (!request.payOrderId().equals(intent.get("pay_order_id"))) {
            throw new HttpBusinessException(409, "payment_intent_identifier_mismatch");
        }
        String fingerprint = fingerprint(userId, request);
        Attempt previous = saved(userId, request, fingerprint, false);
        if (previous != null) return previous;
        if (!"mock".equals(intent.get("pay_channel"))) {
            throw new HttpBusinessException(403, "mock_payment_intent_required");
        }
        if (!(intent.get("trade_status") instanceof Number status) || status.intValue() != 0) {
            throw new HttpBusinessException(409, "pending_payment_intent_required");
        }
        long amount;
        try {
            amount = ((BigDecimal) intent.get("pay_amount")).movePointRight(2).longValueExact();
        } catch (ArithmeticException | ClassCastException | NullPointerException invalid) {
            throw new HttpBusinessException(409, "invalid_payment_intent_amount");
        }
        if (amount <= 0) throw new HttpBusinessException(409, "invalid_payment_intent_amount");
        long occurred = Instant.now().toEpochMilli();
        Attempt result = new Attempt(request.attemptId(), request.payOrderId(),
                text((String) intent.get("order_id"), 32), userId, "mock", "DECLINED",
                "MOCK_CHANNEL_DECLINED", "mock", amount, "CNY", Instant.ofEpochMilli(occurred).toString(),
                CommerceOutcomeClient.stableEventId("payment-attempt", request.attemptId()));
        try {
            jdbc.update("INSERT INTO pay_payment_attempt (attempt_id,pay_order_id,order_id,user_id,attempt_status,"
                            + "reason_code,payment_mode,attempted_amount_cents,occurred_at_epoch_ms,fingerprint,result_json) "
                            + "VALUES (?,?,?,?,?,?,?,?,?,?,?)", result.attemptId(), result.payOrderId(), result.orderId(),
                    userId, result.attemptStatus(), result.reasonCode(), result.paymentMode(), amount, occurred,
                    fingerprint, encode(result));
        } catch (DuplicateKeyException duplicate) {
            // The same globally unique attempt can race from two different payment intents.
            Attempt winner = saved(userId, request, fingerprint, true);
            if (winner == null) throw new HttpBusinessException(409, "payment_attempt_conflict");
            return winner;
        }
        // Both first response and event use the durable result, never a newly generated timestamp.
        result = saved(userId, request, fingerprint, true);
        publish(result);
        return result;
    }

    public Attempt get(String userId, Request request) {
        validate(userId, request);
        Attempt result = saved(userId, request, fingerprint(userId, request), false);
        if (result == null) throw new HttpBusinessException(404, "payment_attempt_not_found");
        return result;
    }

    private Attempt saved(String userId, Request request, String fingerprint, boolean lock) {
        var rows = jdbc.queryForList("SELECT user_id,pay_order_id,fingerprint,result_json FROM pay_payment_attempt "
                + "WHERE attempt_id=?" + (lock ? " FOR UPDATE" : ""), request.attemptId());
        if (rows.isEmpty()) return null;
        var row = rows.get(0);
        DelegatedUserIdentity.requireOwner(userId, (String) row.get("user_id"));
        if (!request.payOrderId().equals(row.get("pay_order_id")) || !fingerprint.equals(row.get("fingerprint"))) {
            throw new HttpBusinessException(409, "payment_attempt_conflict");
        }
        try {
            return JSON.readValue((String) row.get("result_json"), Attempt.class);
        } catch (JsonProcessingException invalid) {
            throw new IllegalStateException("Invalid persisted payment attempt", invalid);
        }
    }

    private void publish(Attempt attempt) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("attemptId", attempt.attemptId());
        payload.put("payOrderId", attempt.payOrderId());
        payload.put("attemptStatus", attempt.attemptStatus());
        payload.put("reasonCode", attempt.reasonCode());
        payload.put("paymentMode", attempt.paymentMode());
        payload.put("attemptedAmountCents", attempt.attemptedAmountCents());
        payload.put("currency", attempt.currency());
        outcomes.recordV2AfterCommit(new CommerceOutcomeClient.OutcomeEvent(attempt.eventId(), "PAYMENT_PROVIDER",
                CommerceOutcomeClient.stableIdempotencyKey("payment-attempt", attempt.attemptId()),
                "PAYMENT_ATTEMPT", attempt.userId(), null, null, null, attempt.orderId(), null, payload, attempt.occurredAt()));
    }

    private static void validate(String userId, Request request) {
        text(userId, 64);
        if (request == null) throw new HttpBusinessException(422, "invalid_payment_attempt_request");
        text(request.attemptId(), 64);
        text(request.payOrderId(), 32);
    }

    private static String text(String value, int limit) {
        if (value == null || value.isBlank() || value.length() > limit || value.indexOf('\0') >= 0) {
            throw new HttpBusinessException(422, "invalid_payment_attempt_identifier");
        }
        return value;
    }

    private static String fingerprint(String userId, Request request) {
        try {
            byte[] bytes = (userId + '\0' + request.payOrderId() + '\0' + request.attemptId()
                    + "\0MOCK_CHANNEL_DECLINED").getBytes(StandardCharsets.UTF_8);
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
        } catch (java.security.NoSuchAlgorithmException impossible) {
            throw new IllegalStateException(impossible);
        }
    }

    private static String encode(Attempt attempt) {
        try {
            return JSON.writeValueAsString(attempt);
        } catch (JsonProcessingException impossible) {
            throw new IllegalStateException(impossible);
        }
    }
}
