package com.smartlect.biz.impl;

import com.smartlect.api.dto.PayUrlRequestDTO;
import com.smartlect.api.enums.PayChannelEnum;
import com.smartlect.api.support.OrderFeignSupport;
import com.smartlect.biz.PayInternalService;
import com.smartlect.biz.PayTradeRecordService;
import com.smartlect.controller.internal.MockPaymentController;
import com.smartlect.entity.po.PayTradeRecord;
import com.smartlect.exception.BusinessException;
import com.smartlect.web.InternalApiAuthFilter;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.math.BigDecimal;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@ExtendWith(MockitoExtension.class)
class PayChannel4MockTest {
    @Mock PayTradeRecordService trades;
    @Mock OrderFeignSupport orders;
    @Mock JdbcTemplate jdbc;
    PayChannel4Mock channel;

    @BeforeEach
    void setUp() {
        channel = new PayChannel4Mock(trades, orders, jdbc);
    }

    @Test
    void payInformationUsesStoredAmountInsteadOfSuppliedAmount() {
        when(trades.findByPayOrderId("pay-1")).thenReturn(trade(0));
        var result = channel.getPayUrl(PayChannelEnum.MOCK, "pay-1", "untrusted", new BigDecimal("99999"));
        assertEquals(new BigDecimal("90.00"), result.getAmount());
        assertEquals("order-1", result.getOrderId());
        assertEquals("smartlect-mock:pay-1", result.getPayInfo());
        verifyNoInteractions(orders);
    }

    @Test
    void successfulChargeUsesStableIdAndReplaysOnlyNotification() {
        PayTradeRecord record = trade(0);
        when(trades.findByPayOrderId("pay-1")).thenReturn(record);
        doAnswer(call -> {
            record.setTradeStatus(1);
            record.setChannelOrderId(call.getArgument(1));
            return null;
        }).when(trades).markSuccess("pay-1", "smartlect-mock-pay-1");
        var first = channel.completePayment("pay-1");
        var replay = channel.completePayment("pay-1");
        assertEquals(first, replay);
        assertEquals("owner-1", first.userId());
        assertEquals(new BigDecimal("90.00"), first.amount());
        verify(trades, times(1)).markSuccess(anyString(), anyString());
        verify(orders, times(2)).paySuccess(argThat(dto ->
                "pay-1".equals(dto.getPayOrderId()) && "smartlect-mock-pay-1".equals(dto.getChannelOrderId())));
    }

    @Test
    void lostOrderNotificationCanBeReplayedWithoutAnotherCharge() {
        when(trades.findByPayOrderId("pay-1")).thenReturn(trade(1));
        doThrow(new BusinessException("temporary order failure")).doNothing().when(orders).paySuccess(any());
        assertThrows(BusinessException.class, () -> channel.completePayment("pay-1"));
        assertEquals(1, channel.completePayment("pay-1").tradeStatus());
        verify(trades, never()).markSuccess(anyString(), anyString());
    }

    @Test
    void closedAndRealChannelIntentsCannotBeChargedByMock() {
        PayTradeRecord real = trade(0);
        real.setPayChannel("alipay_pc");
        when(trades.findByPayOrderId("pay-1")).thenReturn(trade(2), real, null);
        for (int i = 0; i < 3; i++) {
            assertThrows(BusinessException.class, () -> channel.completePayment("pay-1"));
        }
        verify(trades, never()).markSuccess(anyString(), anyString());
        verifyNoInteractions(orders);
        assertThrows(BusinessException.class, () -> channel.payNotify(Map.of("amount", "1"), null));
    }

    @Test
    void refundedPaymentDoesNotReopenOrderAndPendingQueryDoesNotClaimPayment() {
        when(trades.findByPayOrderId("pay-1")).thenReturn(trade(3), trade(0));
        assertEquals(3, channel.completePayment("pay-1").tradeStatus());
        assertNull(channel.queryOrder("pay-1"));
        verifyNoInteractions(orders);
    }

    @Test
    void authenticatedTriggerIgnoresCallerUserAndAmount() throws Exception {
        InternalApiAuthFilter filter = new InternalApiAuthFilter();
        ReflectionTestUtils.setField(filter, "expectedToken", "smartlect-test-internal");
        ReflectionTestUtils.setField(filter, "authEnabled", true);
        var mvc = MockMvcBuilders.standaloneSetup(new MockPaymentController(channel)).addFilters(filter).build();
        mvc.perform(post("/internal/pay/mock/complete").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"payOrderId\":\"pay-1\"}"))
                .andExpect(status().isUnauthorized());
        verifyNoInteractions(trades, orders);
        when(trades.findByPayOrderId("pay-1")).thenReturn(trade(1));
        mvc.perform(post("/internal/pay/mock/complete").header("X-Internal-Token", "smartlect-test-internal")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"payOrderId\":\"pay-1\",\"userId\":\"attacker\",\"amount\":99999}"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.userId").value("owner-1"))
                .andExpect(jsonPath("$.data.amount").value(90.00));
    }

    @Test
    void mockModeRejectsLiveProviderBeforeBeanOrNetworkAccess() {
        PayInternalService service = new PayInternalService();
        ReflectionTestUtils.setField(service, "paymentMode", "mock");
        assertThrows(BusinessException.class, () -> service.getPayUrl(
                new PayUrlRequestDTO("alipay_pc", "pay-1", "subject", BigDecimal.ONE)));
    }

    static PayTradeRecord trade(int status) {
        PayTradeRecord record = new PayTradeRecord();
        record.setPayOrderId("pay-1");
        record.setOrderId("order-1");
        record.setUserId("owner-1");
        record.setPayChannel("mock");
        record.setPayAmount(new BigDecimal("90.00"));
        record.setTradeStatus(status);
        record.setChannelOrderId(status == 1 || status == 3 ? "smartlect-mock-pay-1" : null);
        return record;
    }
}
