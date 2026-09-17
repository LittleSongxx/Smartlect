package com.smartlect.utils;

import org.junit.jupiter.api.Test;

import java.math.BigDecimal;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class OrderPayAmountUtilTest {

    @Test
    void zeroAmountStaysZeroAndIsFree() {
        assertTrue(OrderPayAmountUtil.isFreeOrder(BigDecimal.ZERO));
        assertTrue(OrderPayAmountUtil.isFreeOrder(null));
        assertEquals(new BigDecimal("0.00"), OrderPayAmountUtil.normalizeChannelPayAmount(BigDecimal.ZERO));
        assertEquals(new BigDecimal("0.00"), OrderPayAmountUtil.normalizeChannelPayAmount(new BigDecimal("-1")));
        assertEquals("0.00", OrderPayAmountUtil.formatChannelPayAmount(BigDecimal.ZERO));
    }

    @Test
    void positiveAmountKeepsScale() {
        assertEquals(new BigDecimal("19.90"), OrderPayAmountUtil.normalizeChannelPayAmount(new BigDecimal("19.9")));
    }
}
