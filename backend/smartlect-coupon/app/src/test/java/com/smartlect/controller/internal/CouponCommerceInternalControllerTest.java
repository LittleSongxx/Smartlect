package com.smartlect.controller.internal;

import com.smartlect.constants.InternalApiHeaders;
import com.smartlect.entity.po.UserCoupon;
import com.smartlect.entity.query.UserCouponQuery;
import com.smartlect.exception.HttpBusinessException;
import com.smartlect.mappers.UserCouponMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.jdbc.BadSqlGrammarException;
import org.springframework.jdbc.core.JdbcTemplate;

import java.sql.SQLException;
import java.util.List;
import java.util.Map;
import java.util.function.Consumer;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;

class CouponCommerceInternalControllerTest {
    @AfterEach
    void clearDelegation() {
        RequestContextHolder.resetRequestAttributes();
    }

    private void delegateAs(String userId) {
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.addHeader(InternalApiHeaders.DELEGATED_USER_ID, userId);
        RequestContextHolder.setRequestAttributes(new ServletRequestAttributes(request));
    }

    @Test
    void bothCouponQueriesRequireDelegationEvenForEmptyRequests() {
        CouponCommerceInternalController controller = new CouponCommerceInternalController();
        UserCouponMapper<?, ?> mapper = mock(UserCouponMapper.class);
        ReflectionTestUtils.setField(controller, "userCouponMapper", mapper);
        List<Consumer<Map<String, Object>>> queries = List.of(
                controller::listUserCoupons, controller::estimateSingleSkuOffers);
        for (Consumer<Map<String, Object>> query : queries) {
            RequestContextHolder.resetRequestAttributes();
            assertEquals(401, assertThrows(HttpBusinessException.class,
                    () -> query.accept(Map.of())).getHttpStatus());
            delegateAs("user-1");
            assertEquals(403, assertThrows(HttpBusinessException.class,
                    () -> query.accept(Map.of("userId", "other-user"))).getHttpStatus());
        }
        verifyNoInteractions(mapper);
    }

    @Test
    @SuppressWarnings("unchecked")
    void bothCouponQueriesUseDelegatedOwnerWithoutABodyUserId() {
        CouponCommerceInternalController controller = new CouponCommerceInternalController();
        UserCouponMapper<UserCoupon, UserCouponQuery> mapper = mock(UserCouponMapper.class);
        ReflectionTestUtils.setField(controller, "userCouponMapper", mapper);
        when(mapper.selectList(argThat(query -> "user-1".equals(query.getUserId())))).thenReturn(List.of());
        delegateAs("user-1");
        assertEquals(List.of(), controller.listUserCoupons(Map.of()).getData());
        assertEquals(List.of(Map.of("offerKey", "product-1:sku-1", "status", "NO_COUPON",
                        "estimatedPayable", new java.math.BigDecimal("25.00"),
                        "estimatedDiscount", java.math.BigDecimal.ZERO)),
                controller.estimateSingleSkuOffers(Map.of("items", List.of(Map.of(
                        "productId", "product-1", "skuKey", "sku-1", "basePrice", "25.00")))).getData());
        verify(mapper, times(2)).selectList(argThat(query -> "user-1".equals(query.getUserId())));
    }

    @Test
    void scopeMatchesOnlyTreatsMissingTableAsUnscoped() {
        CouponCommerceInternalController controller = new CouponCommerceInternalController();
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        ReflectionTestUtils.setField(controller, "jdbcTemplate", jdbc);
        when(jdbc.queryForList(anyString(), eq("c1")))
                .thenThrow(new BadSqlGrammarException("query", "SELECT",
                        new SQLException("Table 'smartlect.coupon_scope' doesn't exist")));
        assertTrue((Boolean) ReflectionTestUtils.invokeMethod(controller, "scopeMatches", "c1", "cat", "p", "s"));

        when(jdbc.queryForList(anyString(), eq("c2")))
                .thenThrow(new DataAccessResourceFailureException("connection lost"));
        assertThrows(DataAccessResourceFailureException.class,
                () -> ReflectionTestUtils.invokeMethod(controller, "scopeMatches", "c2", "cat", "p", "s"));
    }
}
