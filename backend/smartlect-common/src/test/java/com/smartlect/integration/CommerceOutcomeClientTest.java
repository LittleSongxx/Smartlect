package com.smartlect.integration;

import com.smartlect.constants.RabbitMQConfig;
import com.smartlect.constants.TransactionalMqSender;
import com.smartlect.entity.enums.MessageReliabilityLevelEnum;
import com.smartlect.entity.po.ProductItem;
import com.smartlect.utils.JsonUtils;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.Date;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;

@ExtendWith(MockitoExtension.class)
class CommerceOutcomeClientTest {

    @Mock
    private TransactionalMqSender transactionalMqSender;

    @Test
    void persistsCanonicalOutcomeThroughTransactionalOutbox() {
        ProductItem item = new ProductItem();
        item.setProductId("p1");
        item.setRecommendationRequestId("request-1");
        item.setRecommendationPosition(2);
        CommerceOutcomeClient.OutcomeEvent event = CommerceOutcomeClient.fromVerifiedCarrier(
                "event-1", "CART", "cart-1", "ADD_TO_CART", "u1", item,
                "sku-1", null, Map.of("quantity", 2), new Date());

        new CommerceOutcomeClient(transactionalMqSender, true).recordAfterCommit(event);

        ArgumentCaptor<CommerceOutcomeClient.OutcomeBatch> batchCaptor =
                ArgumentCaptor.forClass(CommerceOutcomeClient.OutcomeBatch.class);
        ArgumentCaptor<String> keyCaptor = ArgumentCaptor.forClass(String.class);
        verify(transactionalMqSender).sendAfterCommit(
                org.mockito.ArgumentMatchers.eq(RabbitMQConfig.COMMERCE_OUTCOME_EXCHANGE),
                org.mockito.ArgumentMatchers.eq(RabbitMQConfig.COMMERCE_OUTCOME_KEY),
                batchCaptor.capture(),
                keyCaptor.capture(),
                org.mockito.ArgumentMatchers.eq(MessageReliabilityLevelEnum.STANDARD));
        assertEquals(1, batchCaptor.getValue().events().size());
        assertEquals(1, JsonUtils.mapper().valueToTree(batchCaptor.getValue()).path("schema_version").asInt());
        assertEquals("ADD_TO_CART", batchCaptor.getValue().events().get(0).eventType());
        assertEquals("request-1", batchCaptor.getValue().events().get(0).requestId());
        assertEquals(2, batchCaptor.getValue().events().get(0).payload().get("quantity"));
        assertTrue(keyCaptor.getValue().startsWith("commerce-outbox_"));
    }

    @Test
    void incompleteTouchpointIsReportedAsUnattributed() {
        ProductItem item = new ProductItem();
        item.setProductId("p1");
        item.setRecommendationRequestId("request-1");

        CommerceOutcomeClient.OutcomeEvent event = CommerceOutcomeClient.fromVerifiedCarrier(
                "event-1", "CART", "cart-1", "ADD_TO_CART", "u1", item,
                "sku-1", null, Map.of(), new Date());

        assertNull(event.requestId());
        assertNull(event.position());
        assertFalse(event.payload().containsKey("address"));
    }

    @Test
    void disabledProjectionDoesNotCreateOutboxRows() {
        CommerceOutcomeClient client = new CommerceOutcomeClient(transactionalMqSender, false);

        client.recordAfterCommit(new CommerceOutcomeClient.OutcomeEvent(
                "event-1", "CART", "cart-1", "ADD_TO_CART", "u1", null,
                "p1", "sku-1", null, null, Map.of("quantity", 1),
                java.time.Instant.now().toString()));

        verify(transactionalMqSender, never()).sendAfterCommit(any(), any(), any(), any(), any());
    }

    @Test
    void v2ProjectionIsExplicitAndDoesNotChangeLegacyBatchSerialization() {
        var event = new CommerceOutcomeClient.OutcomeEvent("view1", "PRODUCT_BROWSE", "view-key", "VIEW", "u1",
                null, "p1", null, null, null, Map.of("executionScopeId", "store"), "2026-09-09T00:00:00Z");
        var client = new CommerceOutcomeClient(transactionalMqSender, true);
        client.recordV2AfterCommit(event);
        var batch = ArgumentCaptor.forClass(CommerceOutcomeClient.OutcomeBatch.class);
        verify(transactionalMqSender).sendAfterCommit(any(), any(), batch.capture(), any(), any());
        assertEquals(2, batch.getValue().schemaVersion());
        assertEquals(event, batch.getValue().events().get(0));
        assertEquals(1, JsonUtils.mapper().valueToTree(new CommerceOutcomeClient.OutcomeBatch(java.util.List.of(event)))
                .path("schema_version").asInt());
    }
}
