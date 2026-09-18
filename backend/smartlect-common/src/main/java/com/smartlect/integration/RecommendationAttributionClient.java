package com.smartlect.integration;

import com.smartlect.constants.InternalApiHeaders;
import com.smartlect.entity.dto.RecommendationAttributionCarrier;
import com.smartlect.entity.vo.ResponseVO;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

import java.time.Duration;
import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Date;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Best-effort, read-only validation of recommendation touchpoints.
 *
 * This client intentionally has a dedicated short timeout and no retry. A slow or
 * unavailable Growth must only remove optional attribution, never delay or fail a
 * cart/order transaction.
 */
@Component
public class RecommendationAttributionClient {

    private static final Logger log = LoggerFactory.getLogger(RecommendationAttributionClient.class);

    private final RestClient client;
    private final String internalToken;

    public RecommendationAttributionClient(
            RestClient.Builder builder,
            @Value("${smartlect.assistant.base-url:http://127.0.0.1:18000}") String growthBaseUrl,
            @Value("${smartlect.internal.token:}") String internalToken,
            @Value("${smartlect.assistant.attribution-connect-timeout-ms:200}") int connectTimeoutMs,
            @Value("${smartlect.assistant.attribution-read-timeout-ms:500}") int readTimeoutMs) {
        SimpleClientHttpRequestFactory requestFactory = new SimpleClientHttpRequestFactory();
        requestFactory.setConnectTimeout(Duration.ofMillis(Math.max(connectTimeoutMs, 50)));
        requestFactory.setReadTimeout(Duration.ofMillis(Math.max(readTimeoutMs, 50)));
        this.client = builder.clone()
                .baseUrl(growthBaseUrl.replaceAll("/+$", ""))
                .requestFactory(requestFactory)
                .build();
        this.internalToken = internalToken;
    }

    public void validateAndApply(
            String userId,
            List<? extends RecommendationAttributionCarrier> carriers) {
        if (carriers == null || carriers.isEmpty()) {
            return;
        }

        Map<AttributionItem, List<RecommendationAttributionCarrier>> requested = new LinkedHashMap<>();
        for (RecommendationAttributionCarrier carrier : carriers) {
            if (carrier == null) {
                continue;
            }
            String requestId = trim(carrier.getRecommendationRequestId());
            String productId = trim(carrier.getProductId());
            String skuKey = trim(carrier.getPropertyValueIdHash());
            Integer position = carrier.getRecommendationPosition();
            carrier.clearRecommendationAttribution();
            if (requestId == null || requestId.length() > 128
                    || productId == null || productId.length() > 64
                    || skuKey == null || skuKey.length() > 128
                    || position == null || position < 1 || position > 20) {
                continue;
            }
            AttributionItem item = new AttributionItem(requestId, productId, skuKey, position);
            requested.computeIfAbsent(item, ignored -> new ArrayList<>()).add(carrier);
        }
        if (trim(userId) == null || requested.isEmpty()) {
            return;
        }

        List<ValidatedAttribution> validated = validateBatch(userId, new ArrayList<>(requested.keySet()));
        for (ValidatedAttribution attribution : validated) {
            if (attribution == null) continue;
            List<RecommendationAttributionCarrier> matching = requested.get(new AttributionItem(
                    attribution.requestId(), attribution.productId(), attribution.skuKey(), attribution.position()));
            Date occurredAt = parseOccurredAt(attribution.occurredAt());
            String source = trim(attribution.source());
            if (matching == null || occurredAt == null || source == null || source.length() > 40) {
                continue;
            }
            for (RecommendationAttributionCarrier carrier : matching) {
                carrier.setRecommendationRequestId(attribution.requestId());
                carrier.setRecommendationPosition(attribution.position());
                carrier.setRecommendationSource(source);
                carrier.setRecommendationAttributedAt(occurredAt);
            }
        }
    }

    private List<ValidatedAttribution> validateBatch(String userId, List<AttributionItem> items) {
        try {
            Map<String, Object> body = new HashMap<>();
            body.put("userId", userId);
            body.put("items", items);
            ResponseVO<List<ValidatedAttribution>> response = client.post()
                    .uri("/internal/attribution/validateBatch")
                    .contentType(MediaType.APPLICATION_JSON)
                    .header(InternalApiHeaders.INTERNAL_TOKEN, internalToken)
                    .body(body)
                    .retrieve()
                    .body(new ParameterizedTypeReference<ResponseVO<List<ValidatedAttribution>>>() {});
            if (response == null || !"success".equalsIgnoreCase(response.getStatus())
                    || response.getData() == null) {
                return Collections.emptyList();
            }
            return response.getData();
        } catch (Exception ex) {
            log.warn("Recommendation attribution validation unavailable; dropping {} candidate(s)",
                    items.size());
            return Collections.emptyList();
        }
    }

    private static Date parseOccurredAt(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        try {
            return Date.from(OffsetDateTime.parse(value).toInstant());
        } catch (Exception ignored) {
            try {
                return Date.from(LocalDateTime.parse(value)
                        .atZone(ZoneId.systemDefault()).toInstant());
            } catch (Exception invalid) {
                return null;
            }
        }
    }

    private static String trim(String value) {
        if (value == null || value.trim().isEmpty()) {
            return null;
        }
        return value.trim();
    }

    private record AttributionItem(String requestId, String productId, String skuKey, Integer position) {
    }

    private record ValidatedAttribution(
            String requestId,
            String productId,
            String skuKey,
            Integer position,
            String source,
            String occurredAt) {
    }
}
