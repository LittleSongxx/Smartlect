package com.smartlect.biz.impl;

import com.smartlect.api.dto.PayOrderMessageDTO;
import com.smartlect.biz.OrderInfoService;
import com.smartlect.biz.OrderLogisticsInfoRecordService;
import com.smartlect.component.OrderNotificationPublisher;
import com.smartlect.constants.RabbitMQConfig;
import com.smartlect.constants.TransactionalMqSender;
import com.smartlect.entity.enums.MessageReliabilityLevelEnum;
import com.smartlect.entity.po.OrderInfo;
import com.smartlect.entity.po.OrderLogisticsInfo;
import com.smartlect.entity.po.OrderLogisticsInfoRecord;
import com.smartlect.entity.query.OrderInfoQuery;
import com.smartlect.entity.query.OrderLogisticsInfoQuery;
import com.smartlect.mappers.OrderLogisticsInfoMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class OrderLogisticsOutboxTest {

    @Mock
    private OrderLogisticsInfoMapper<OrderLogisticsInfo, OrderLogisticsInfoQuery> mapper;
    @Mock
    private OrderLogisticsInfoRecordService recordService;
    @Mock
    private OrderInfoService orderInfoService;
    @Mock
    private com.smartlect.mappers.OrderInfoMapper<com.smartlect.entity.po.OrderInfo,
            com.smartlect.entity.query.OrderInfoQuery> orderInfoMapper;
    @Mock
    private TransactionalMqSender transactionalMqSender;
    @Mock
    private OrderNotificationPublisher orderNotificationPublisher;
    @InjectMocks
    private OrderLogisticsInfoServiceImpl service;

    @org.junit.jupiter.api.BeforeEach
    void wireStateMachine() {
        com.smartlect.state.OrderStateMachine machine = new com.smartlect.state.OrderStateMachine();
        org.springframework.test.util.ReflectionTestUtils.setField(machine, "orderInfoMapper", orderInfoMapper);
        org.springframework.test.util.ReflectionTestUtils.setField(service, "orderStateMachine", machine);
    }

    @Test
    void deliveryRegistersConfirmAndNotificationMessagesInOutbox() {
        OrderLogisticsInfo logistics = new OrderLogisticsInfo();
        logistics.setOrderId("o1");
        logistics.setLogisticsNo("L123");
        logistics.setSenderAddress("上海");
        when(mapper.updateByParam(any(), any())).thenReturn(1);
        when(orderInfoMapper.updateByParam(any(com.smartlect.entity.po.OrderInfo.class),
                any(com.smartlect.entity.query.OrderInfoQuery.class))).thenReturn(1);
        OrderInfo shipped = new OrderInfo();
        shipped.setUserId("u1");
        when(orderInfoService.getOrderInfoByOrderId("o1")).thenReturn(shipped);

        service.delivery(logistics);

        ArgumentCaptor<PayOrderMessageDTO> confirm =
                ArgumentCaptor.forClass(PayOrderMessageDTO.class);
        verify(transactionalMqSender).sendAfterCommit(
                eq(RabbitMQConfig.PAY_EXCHANGE),
                eq(RabbitMQConfig.PAY_CONFIRM_DELAY_KEY),
                confirm.capture(),
                eq("pay:confirm:o1"),
                eq(MessageReliabilityLevelEnum.STANDARD));
        assertEquals("o1", confirm.getValue().getOrderId());
        verify(recordService).add(any(OrderLogisticsInfoRecord.class));
        verify(orderNotificationPublisher).send(
                "u1",
                "订单已发货",
                "您的订单 o1 已发货，物流单号：L123",
                "logistics",
                "o1");
    }
}
