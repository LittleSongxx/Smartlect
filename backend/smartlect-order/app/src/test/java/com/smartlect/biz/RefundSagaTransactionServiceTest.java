package com.smartlect.biz;

import com.smartlect.constants.TransactionalMqSender;
import com.smartlect.entity.po.OrderInfo;
import com.smartlect.entity.po.OrderItem;
import com.smartlect.entity.po.RefundRequest;
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

}
