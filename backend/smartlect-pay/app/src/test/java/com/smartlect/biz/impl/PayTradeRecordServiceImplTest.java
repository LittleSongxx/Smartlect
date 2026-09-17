package com.smartlect.biz.impl;

import com.smartlect.entity.po.PayTradeRecord;
import com.smartlect.entity.query.PayTradeRecordQuery;
import com.smartlect.mappers.PayTradeRecordMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.dao.DuplicateKeyException;

import java.math.BigDecimal;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class PayTradeRecordServiceImplTest {

    @Mock
    private PayTradeRecordMapper<PayTradeRecord, PayTradeRecordQuery> mapper;
    @InjectMocks
    private PayTradeRecordServiceImpl service;

    @Test
    void duplicatePayOrderIdIsTreatedAsIdempotentCreate() {
        doThrow(new DuplicateKeyException("duplicate pay_order_id"))
                .when(mapper).insert(any(PayTradeRecord.class));
        PayTradeRecord existing = new PayTradeRecord();
        existing.setUserId("u1");
        existing.setOrderId("order-1");
        existing.setPayAmount(new BigDecimal("99.00"));
        when(mapper.selectByPayOrderId("pay-1")).thenReturn(existing);

        assertDoesNotThrow(() -> service.createPending(
                "u1", "pay-1", "order-1", new BigDecimal("99.00"), "ALI_PAY"));
    }

    @Test
    void missingAmountIsRejectedAndDuplicateDifferentAmountConflicts() {
        org.junit.jupiter.api.Assertions.assertThrows(com.smartlect.exception.BusinessException.class,
                () -> service.createPending("u1", "pay-1", "order-1", null, "ALI_PAY"));
        doThrow(new DuplicateKeyException("duplicate pay_order_id"))
                .when(mapper).insert(any(PayTradeRecord.class));
        PayTradeRecord existing = new PayTradeRecord();
        existing.setUserId("u1");
        existing.setOrderId("order-1");
        existing.setPayAmount(new BigDecimal("10.00"));
        when(mapper.selectByPayOrderId("pay-1")).thenReturn(existing);
        org.junit.jupiter.api.Assertions.assertThrows(com.smartlect.exception.BusinessException.class,
                () -> service.createPending("u1", "pay-1", "order-1", new BigDecimal("99.00"), "ALI_PAY"));
    }

    @Test
    void duplicateSuccessCallbackIsIdempotent() {
        when(mapper.updateSuccessIfPending(eq("pay-1"), eq("channel-1"), any()))
                .thenReturn(0);
        PayTradeRecord current = trade(1);
        when(mapper.selectByPayOrderId("pay-1")).thenReturn(current);

        assertDoesNotThrow(() -> service.markSuccess("pay-1", "channel-1"));

        verify(mapper, never()).updateByParam(any(), any());
    }

    @Test
    void lateSuccessCallbackCannotReopenClosedOrRefundedTrade() {
        when(mapper.updateSuccessIfPending(eq("pay-1"), anyString(), any()))
                .thenReturn(0);
        when(mapper.selectByPayOrderId("pay-1"))
                .thenReturn(trade(2), trade(3));

        assertDoesNotThrow(() -> service.markSuccess("pay-1", "late-closed"));
        assertDoesNotThrow(() -> service.markSuccess("pay-1", "late-refunded"));

        verify(mapper, never()).updateByParam(any(), any());
    }

    @Test
    void firstSuccessCallbackUsesCompareAndSetWithoutExtraRead() {
        when(mapper.updateSuccessIfPending(eq("pay-1"), eq("channel-1"), any()))
                .thenReturn(1);

        service.markSuccess("pay-1", "channel-1");

        verify(mapper, never()).selectByPayOrderId("pay-1");
    }

    private static PayTradeRecord trade(int status) {
        PayTradeRecord record = new PayTradeRecord();
        record.setPayOrderId("pay-1");
        record.setTradeStatus(status);
        return record;
    }
}
