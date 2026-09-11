package com.aishop.biz.impl;

import com.aishop.api.enums.OrderItemStatusEnum;
import com.aishop.api.enums.OrderStatusEnum;
import com.aishop.biz.RefundSagaTransactionService;
import com.aishop.entity.po.OrderInfo;
import com.aishop.entity.po.OrderItem;
import com.aishop.entity.po.RefundRequest;
import com.aishop.entity.query.OrderInfoQuery;
import com.aishop.entity.query.OrderItemQuery;
import com.aishop.integration.CommerceOutcomeClient;
import com.aishop.mappers.OrderInfoMapper;
import com.aishop.mappers.OrderItemMapper;
import com.aishop.mappers.RefundRequestMapper;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.test.util.ReflectionTestUtils;

import java.math.BigDecimal;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

/** Copy into an isolated AI_Shop order module test directory to reproduce the review findings. */
@SuppressWarnings("unchecked")
class ShopMoneyContractProbeTest {
    @Test
    void equalPriceSkuLinesReceiveEqualPaidAmounts() {
        var service = new OrderInfoServiceImpl();
        OrderItemMapper<OrderItem, OrderItemQuery> items = mock(OrderItemMapper.class);
        var outcomes = mock(CommerceOutcomeClient.class);
        ReflectionTestUtils.setField(service, "orderItemMapper", items);
        ReflectionTestUtils.setField(service, "commerceOutcomeClient", outcomes);
        when(items.selectList(any(OrderItemQuery.class))).thenReturn(List.of(item("1"), item("2"), item("3")));

        ReflectionTestUtils.invokeMethod(service, "recordPaymentOutcomes", List.of(order("300.00")), "pay-1");

        var emitted = ArgumentCaptor.forClass(CommerceOutcomeClient.OutcomeEvent.class);
        verify(outcomes, times(3)).recordAfterCommit(emitted.capture());
        List<Object> amounts = emitted.getAllValues().stream().map(e -> e.payload().get("paidAmount")).toList();
        assertEquals(List.of(new BigDecimal("100.00"), new BigDecimal("100.00"), new BigDecimal("100.00")), amounts);
    }

    @Test
    void discountedSingleLineRefundCannotExceedPaidAmount() {
        var service = new RefundSagaTransactionService();
        var requests = mock(RefundRequestMapper.class);
        OrderItemMapper<OrderItem, ?> items = mock(OrderItemMapper.class);
        OrderInfoMapper<OrderInfo, ?> orders = mock(OrderInfoMapper.class);
        ReflectionTestUtils.setField(service, "refundRequestMapper", requests);
        ReflectionTestUtils.setField(service, "orderItemMapper", items);
        ReflectionTestUtils.setField(service, "orderInfoMapper", orders);
        var stored = new AtomicReference<RefundRequest>();
        when(requests.selectByOrderItemId("item-1")).thenAnswer(call -> stored.get());
        when(requests.insertIgnore(any(RefundRequest.class))).thenAnswer(call -> {
            stored.set(call.getArgument(0));
            return 1;
        });
        when(items.selectByOrderItemIdForUpdate("item-1")).thenReturn(item("1"));
        when(orders.selectByOrderIdForUpdate("order-1")).thenReturn(order("90.00"));

        RefundRequest result = service.createOrLoad("item-1", "user-1");

        assertEquals(new BigDecimal("90.00"), result.getRefundAmount());
    }

    private static OrderInfo order(String paidAmount) {
        var order = new OrderInfo();
        order.setOrderId("order-1");
        order.setPayOrderId("pay-1");
        order.setUserId("user-1");
        order.setOrderStatus(OrderStatusEnum.PAID.getStatus());
        order.setPayChannel("alipay_pc");
        order.setAmount(new BigDecimal(paidAmount));
        return order;
    }

    private static OrderItem item(String suffix) {
        var item = new OrderItem();
        item.setOrderItemId("item-" + suffix);
        item.setOrderId("order-1");
        item.setProductId("product-1");
        item.setPropertyValueIdHash("sku-" + suffix);
        item.setBuyCount(1);
        item.setItemAmount(new BigDecimal("100.00"));
        item.setOrderItemStatus(OrderItemStatusEnum.NORMAL.getStatus());
        return item;
    }
}
