package com.smartlect.controller.internal;

import com.smartlect.api.dto.PayInfoDTO;
import com.smartlect.biz.CommerceV2Service;
import com.smartlect.biz.OrderInfoService;
import com.smartlect.exception.HttpBusinessException;
import com.smartlect.utils.JsonUtils;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

import java.math.BigDecimal;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class OrderCommerceV2ControllerTest {
    private final OrderInfoService orders = mock(OrderInfoService.class);
    private final CommerceV2Service actions = mock(CommerceV2Service.class);
    private final OrderCommerceV2Controller controller = new OrderCommerceV2Controller(orders, actions);
    private static final String ORDER = """
            {"payMethod":"mock","addressId":"a1","orderFrom":0,
             "orderList":[{"productId":"p1","propertyValueIds":"v1","buyCount":1}]}
            """;

    @AfterEach
    void clearIdentity() { RequestContextHolder.resetRequestAttributes(); }

    @Test
    void quoteRequiresDelegationAndRejectsIdentityOrQuantityFromBody() throws Exception {
        var order = JsonUtils.mapper().readTree(ORDER);
        assertEquals(401, assertThrows(HttpBusinessException.class, () -> controller.quote(order)).getHttpStatus());
        bindUser();
        for (String invalid : new String[]{ORDER.replace("\"orderFrom\":0", "\"orderFrom\":0,\"userId\":\"victim\""),
                ORDER.replace("\"buyCount\":1", "\"buyCount\":true")}) {
            var body = JsonUtils.mapper().readTree(invalid);
            assertThrows(HttpBusinessException.class, () -> controller.quote(body));
        }
        verifyNoInteractions(orders, actions);
        when(orders.quoteOrder(eq("trusted-user"), any())).thenReturn(Map.of("quoteId", "quote"));
        assertNotNull(controller.quote(order));
    }

    @Test
    void confirmationUsesTrustedIdentityExactQuoteAndOriginalKeyWithoutPaying() throws Exception {
        bindUser();
        String quoteId = "a".repeat(32);
        String key = "confirmed-order-key-001";
        var body = JsonUtils.mapper().readTree("{\"quoteId\":\"" + quoteId
                + "\",\"confirmedAmountCents\":1000,\"order\":" + ORDER + "}");
        when(orders.createConfirmed(eq("trusted-user"), any(), eq(quoteId), eq(1000L), eq(key), isNull()))
                .thenReturn(new PayInfoDTO(null, "pay1", new BigDecimal("10.00")));
        var response = controller.createConfirmed(body, key);
        assertEquals("business_completed", response.getData().get("commandStatus"));
        assertEquals("PENDING", response.getData().get("paymentStatus"));
        verifyNoInteractions(actions);
    }

    @Test
    void optionalContextIsOutsidePurchaseAndMalformedContextDoesNotCoerceMoney() throws Exception {
        bindUser();
        when(orders.createConfirmed(eq("trusted-user"), any(), eq("q"), eq(1000L), eq("original-key"), nullable(String.class)))
                .thenReturn(new PayInfoDTO(null, "pay1", new BigDecimal("10.00")));
        for (String token : new String[]{"123", "{}", "null", "\"signed-context\""}) {
            var body = JsonUtils.mapper().readTree("{\"quoteId\":\"q\",\"confirmedAmountCents\":1000,\"order\":" + ORDER
                    + ",\"attributionContextToken\":" + token + "}");
            assertEquals("business_completed", controller.createConfirmed(body, "original-key").getData().get("commandStatus"));
        }
        verify(orders).createConfirmed(eq("trusted-user"), any(), eq("q"), eq(1000L), eq("original-key"), eq("signed-context"));
        var badAmount = JsonUtils.mapper().readTree("{\"quoteId\":\"q\",\"confirmedAmountCents\":\"1000\",\"order\":" + ORDER + "}");
        assertThrows(HttpBusinessException.class, () -> controller.createConfirmed(badAmount, "original-key"));
    }

    private static void bindUser() {
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.addHeader("X-Smartlect-User-Id", "trusted-user");
        RequestContextHolder.setRequestAttributes(new ServletRequestAttributes(request));
    }
}
