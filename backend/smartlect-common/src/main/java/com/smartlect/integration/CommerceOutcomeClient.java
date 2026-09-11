package com.smartlect.integration;

import com.smartlect.constants.RabbitMQConfig;
import com.smartlect.constants.TransactionalMqSender;
import com.smartlect.entity.dto.RecommendationAttributionCarrier;
import com.smartlect.entity.enums.MessageReliabilityLevelEnum;
import com.fasterxml.jackson.annotation.JsonProperty;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.Collections;
import java.util.Date;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Reliable projection of committed commerce facts into the Growth outcome ledger.
 * The local business transaction owns the Outbox row; Growth availability is not on
 * the checkout path, and immutable event identifiers make redelivery harmless.
 */
@Component
public class CommerceOutcomeClient {

    private static final int MAX_BATCH_SIZE = 100;

    private final TransactionalMqSender transactionalMqSender;
    private final boolean enabled;

    public CommerceOutcomeClient(
            TransactionalMqSender transactionalMqSender,
            @Value("${smartlect.growth.outcome-enabled:true}") boolean enabled) {
        this.transactionalMqSender = transactionalMqSender;
        this.enabled = enabled;
    }

    public void recordAfterCommit(OutcomeEvent event) {
        if (event != null) {
            recordBatchAfterCommit(List.of(event));
        }
    }

    public void recordBatchAfterCommit(List<OutcomeEvent> events) {
        if (!enabled || events == null || events.isEmpty()) {
            return;
        }
        List<OutcomeEvent> snapshot = List.copyOf(events);
        sendInBatches(snapshot, 1);
    }

    public void recordV2AfterCommit(OutcomeEvent event) {
        if (enabled && event != null) sendInBatches(List.of(event), 2);
    }

    private void sendInBatches(List<OutcomeEvent> events, int schemaVersion) {
        for (int start = 0; start < events.size(); start += MAX_BATCH_SIZE) {
            int end = Math.min(events.size(), start + MAX_BATCH_SIZE);
            List<OutcomeEvent> batch = List.copyOf(events.subList(start, end));
            transactionalMqSender.sendAfterCommit(
                    RabbitMQConfig.COMMERCE_OUTCOME_EXCHANGE,
                    RabbitMQConfig.COMMERCE_OUTCOME_KEY,
                    new OutcomeBatch(schemaVersion, batch),
                    outcomeBatchIdempotencyKey(batch, schemaVersion),
                    MessageReliabilityLevelEnum.STANDARD);
        }
    }

    private String outcomeBatchIdempotencyKey(List<OutcomeEvent> events, int schemaVersion) {
        Object[] facts = events.stream()
                .map(OutcomeEvent::idempotencyKey)
                .toArray();
        return stableIdentifier("commerce-outbox", "v" + schemaVersion, facts);
    }

    public static OutcomeEvent fromVerifiedCarrier(
            String eventId,
            String source,
            String idempotencyKey,
            String eventType,
            String userId,
            RecommendationAttributionCarrier carrier,
            String skuKey,
            String orderId,
            Map<String, Object> payload,
            Date occurredAt) {
        String requestId = trim(carrier == null ? null : carrier.getRecommendationRequestId());
        Integer position = carrier == null ? null : carrier.getRecommendationPosition();
        if (requestId == null || position == null || position < 1 || position > 20) {
            requestId = null;
            position = null;
        }
        return new OutcomeEvent(
                eventId,
                source,
                idempotencyKey,
                eventType,
                userId,
                requestId,
                carrier == null ? null : trim(carrier.getProductId()),
                trim(skuKey),
                trim(orderId),
                position,
                payload,
                (occurredAt == null ? Instant.now() : occurredAt.toInstant()).toString());
    }

    public static String stableEventId(String namespace, Object... facts) {
        return stableIdentifier("outcome", namespace, facts);
    }

    public static String stableIdempotencyKey(String namespace, Object... facts) {
        return stableIdentifier("business", namespace, facts);
    }

    private static String stableIdentifier(String prefix, String namespace, Object... facts) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            digest.update(String.valueOf(namespace).getBytes(StandardCharsets.UTF_8));
            for (Object fact : facts) {
                digest.update((byte) 0);
                digest.update(String.valueOf(fact).getBytes(StandardCharsets.UTF_8));
            }
            return prefix + "_" + HexFormat.of().formatHex(digest.digest(), 0, 24);
        } catch (Exception impossible) {
            throw new IllegalStateException("SHA-256 unavailable", impossible);
        }
    }

    private static String trim(String value) {
        if (value == null || value.trim().isEmpty()) {
            return null;
        }
        return value.trim();
    }

    public record OutcomeEvent(
            String eventId,
            String source,
            String idempotencyKey,
            String eventType,
            String userId,
            String requestId,
            String productId,
            String skuKey,
            String orderId,
            Integer position,
            Map<String, Object> payload,
            String occurredAt) {

        public OutcomeEvent {
            Map<String, Object> copy = payload == null
                    ? Map.of()
                    : new LinkedHashMap<>(payload);
            payload = Collections.unmodifiableMap(copy);
        }
    }

    public record OutcomeBatch(@JsonProperty("schema_version") int schemaVersion, List<OutcomeEvent> events) {
        public OutcomeBatch(List<OutcomeEvent> events) {
            this(1, events);
        }

        public OutcomeBatch {
            events = List.copyOf(events);
        }
    }
}
