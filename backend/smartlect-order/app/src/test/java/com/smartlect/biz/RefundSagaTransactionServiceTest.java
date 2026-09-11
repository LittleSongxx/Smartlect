package com.smartlect.biz;

import com.smartlect.component.OrderNotificationPublisher;
import com.smartlect.constants.TransactionalMqSender;
import com.smartlect.entity.po.OrderInfo;
import com.smartlect.entity.po.OrderItem;
import com.smartlect.entity.po.RefundRequest;
import com.smartlect.integration.CommerceOutcomeClient;
import com.smartlect.mappers.OrderInfoMapper;
import com.smartlect.mappers.OrderItemMapper;
import com.smartlect.mappers.RefundRequestMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class RefundSagaTransactionServiceTest {

    @Mock
    private RefundRequestMapper refundRequestMapper;
    @Mock
    private OrderInfoMapper<OrderInfo, ?> orderInfoMapper;
    @Mock
    private OrderItemMapper<OrderItem, ?> orderItemMapper;
    @Mock
    private TransactionalMqSender transactionalMqSender;
    @Mock
    private CommerceOutcomeClient commerceOutcomeClient;
    @Mock
    private OrderAttributionService orderAttributionService;
    @Mock
    private OrderNotificationPublisher orderNotificationPublisher;
    @InjectMocks
    private RefundSagaTransactionService service;

    @Test
    void confirmedRefundAmountIsCheckedInsideLockedCreationBeforeInsert() {
        OrderItem item = new OrderItem();
        item.setOrderItemId("i-confirmed");
        item.setOrderId("o-confirmed");
        item.setBuyCount(1);
        item.setOrderItemStatus(com.smartlect.api.enums.OrderItemStatusEnum.NORMAL.getStatus());
        item.setPaidAmount(new java.math.BigDecimal("10.00"));
        item.setRefundedAmount(new java.math.BigDecimal("2.00"));
        OrderInfo order = new OrderInfo();
        order.setOrderId("o-confirmed");
        order.setUserId("u1");
        order.setOrderStatus(com.smartlect.api.enums.OrderStatusEnum.PAID.getStatus());
        order.setPayOrderId("p-confirmed");
        when(orderItemMapper.selectByOrderItemIdForUpdate("i-confirmed")).thenReturn(item);
        when(orderInfoMapper.selectByOrderIdForUpdate("o-confirmed")).thenReturn(order);
        var error = org.junit.jupiter.api.Assertions.assertThrows(com.smartlect.exception.HttpBusinessException.class,
                () -> service.createOrLoadConfirmed("i-confirmed", "u1", 1000));
        org.junit.jupiter.api.Assertions.assertEquals("RECONFIRM_REQUIRED", error.getMessage());
        org.mockito.Mockito.verify(refundRequestMapper, org.mockito.Mockito.never()).insertIgnore(org.mockito.ArgumentMatchers.any());
    }

    @Test
    void completionNotificationUsesDurableOrderOutbox() {
        RefundRequest request = new RefundRequest();
        request.setRefundRequestId("r1");
        request.setOrderId("o1");
        request.setOrderItemId("i1");
        request.setUserId("u1");
        request.setStatus("STOCK_PENDING");
        when(refundRequestMapper.selectById("r1")).thenReturn(request);
        when(orderItemMapper.selectByOrderItemId("i1")).thenReturn(null);

        service.markCompleted("r1");

        verify(refundRequestMapper).markCompleted("r1");
        verify(orderNotificationPublisher).send(
                "u1",
                "退款已完成",
                "订单 o1 的退款已完成，款项将按支付渠道到账。",
                "refund_complete",
                "r1");
    }

    @Test
    void completedRefundUsesOriginalOrderAttributionRatherThanNewClicks() {
        RefundRequest request = new RefundRequest();
        request.setRefundRequestId("r2"); request.setOrderId("o2"); request.setOrderItemId("i2");
        request.setUserId("u1"); request.setSourcePayOrderId("pay2"); request.setStatus("STOCK_PENDING");
        request.setRefundAmount(new java.math.BigDecimal("10.00"));
        OrderItem item = new OrderItem(); item.setOrderItemId("i2"); item.setProductId("p2");
        item.setPropertyValueIdHash("sku2");
        var frozen = java.util.Map.<String,Object>of("contextId", "a".repeat(32), "snapshotVersion", 1,
                "snapshotHash", "b".repeat(64), "executionScopeId", "store", "contextStatus", "VERIFIED",
                "orderCreatedAt", "2026-09-09T00:00:00Z");
        when(refundRequestMapper.selectById("r2")).thenReturn(request);
        when(orderItemMapper.selectByOrderItemId("i2")).thenReturn(item);
        when(orderAttributionService.eventAttribution("o2")).thenReturn(frozen);
        service.markCompleted("r2");
        var emitted = org.mockito.ArgumentCaptor.forClass(CommerceOutcomeClient.OutcomeEvent.class);
        verify(commerceOutcomeClient).recordV2AfterCommit(emitted.capture());
        org.junit.jupiter.api.Assertions.assertEquals(frozen, emitted.getValue().payload().get("attribution"));
        org.junit.jupiter.api.Assertions.assertEquals("COMPLETED", emitted.getValue().payload().get("refundStatus"));
        org.junit.jupiter.api.Assertions.assertEquals(new java.math.BigDecimal("10.00"), emitted.getValue().payload().get("refundAmount"));
    }
}
