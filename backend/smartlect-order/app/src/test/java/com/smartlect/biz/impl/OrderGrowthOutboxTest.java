package com.smartlect.biz.impl;

import com.smartlect.api.dto.OrderGrowthEventDTO;
import com.smartlect.api.enums.OrderStatusEnum;
import com.smartlect.api.support.UserFeignSupport;
import com.smartlect.component.OrderNotificationPublisher;
import com.smartlect.constants.RabbitMQConfig;
import com.smartlect.constants.TransactionalMqSender;
import com.smartlect.entity.enums.MessageReliabilityLevelEnum;
import com.smartlect.entity.po.OrderInfo;
import com.smartlect.entity.po.OrderItem;
import com.smartlect.entity.query.OrderInfoQuery;
import com.smartlect.entity.query.OrderItemQuery;
import com.smartlect.mappers.OrderInfoMapper;
import com.smartlect.mappers.OrderItemMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class OrderGrowthOutboxTest {

    @Mock
    private OrderInfoMapper<OrderInfo, OrderInfoQuery> orderInfoMapper;
    @Mock
    private OrderItemMapper<OrderItem, OrderItemQuery> orderItemMapper;
    @Mock
    private TransactionalMqSender transactionalMqSender;
    @Mock
    private UserFeignSupport userFeignSupport;
    @Mock
    private OrderNotificationPublisher orderNotificationPublisher;
    @InjectMocks
    private OrderInfoServiceImpl service;

    @Test
    void successfulConfirmationQueuesGrowthEventWithOrderBusinessKey() {
        OrderInfo order = shippedOrder();
        when(orderInfoMapper.selectByOrderId("order-1")).thenReturn(order);
        when(orderInfoMapper.updateByParam(any(OrderInfo.class), any(OrderInfoQuery.class)))
                .thenReturn(1);
        when(orderItemMapper.selectList(any(OrderItemQuery.class))).thenReturn(List.of());

        assertTrue(service.confirmOrderReceipt("user-1", "order-1"));

        ArgumentCaptor<OrderGrowthEventDTO> eventCaptor =
                ArgumentCaptor.forClass(OrderGrowthEventDTO.class);
        verify(transactionalMqSender).sendAfterCommit(
                eq(RabbitMQConfig.USER_MEMBER_EXCHANGE),
                eq(RabbitMQConfig.USER_MEMBER_KEY),
                eventCaptor.capture(),
                eq("order:growth:order-1"),
                eq(MessageReliabilityLevelEnum.STANDARD));
        OrderGrowthEventDTO event = eventCaptor.getValue();
        assertEquals("order-1", event.getOrderId());
        assertEquals("user-1", event.getUserId());
        assertEquals(0, new BigDecimal("268.00").compareTo(event.getPayAmount()));
    }

    @Test
    void failedStatusCasDoesNotQueueGrowthEvent() {
        when(orderInfoMapper.selectByOrderId("order-1")).thenReturn(shippedOrder());
        when(orderInfoMapper.updateByParam(any(OrderInfo.class), any(OrderInfoQuery.class)))
                .thenReturn(0);

        assertEquals(false, service.confirmOrderReceipt("user-1", "order-1"));

        verify(transactionalMqSender, never())
                .sendAfterCommit(any(), any(), any(), any(), any());
    }

    @Test
    void postCommitNotificationPathNoLongerCallsSynchronousGrowthApi() {
        when(orderInfoMapper.selectByOrderId("order-1")).thenReturn(shippedOrder());

        service.onOrderConfirmed("user-1", "order-1");

        verify(userFeignSupport, never()).addGrowthOnPay(any(), any());
        verify(orderNotificationPublisher).send(
                eq("user-1"), eq("确认收货成功"), any(), eq("order"), eq("order-1"));
    }

    @Test
    void confirmationAndOutboxRegistrationShareTheTransactionalMethod() throws Exception {
        Transactional annotation = OrderInfoServiceImpl.class
                .getMethod("confirmOrderReceipt", String.class, String.class)
                .getAnnotation(Transactional.class);
        assertNotNull(annotation);
    }

    private static OrderInfo shippedOrder() {
        OrderInfo order = new OrderInfo();
        order.setOrderId("order-1");
        order.setUserId("user-1");
        order.setAmount(new BigDecimal("268.00"));
        order.setOrderStatus(OrderStatusEnum.SHIPPED.getStatus());
        return order;
    }
}
