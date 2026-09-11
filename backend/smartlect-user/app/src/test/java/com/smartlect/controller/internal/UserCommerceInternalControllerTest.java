package com.smartlect.controller.internal;

import com.smartlect.entity.po.UserBrowseHistory;
import com.smartlect.entity.po.UserAddress;
import com.smartlect.biz.UserAddressService;
import com.smartlect.entity.query.UserBrowseHistoryQuery;
import com.smartlect.constants.InternalApiHeaders;
import com.smartlect.exception.HttpBusinessException;
import com.smartlect.mappers.UserBrowseHistoryMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

import java.util.List;
import java.util.Map;
import java.util.function.Consumer;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.Mockito.*;

class UserCommerceInternalControllerTest {
    @Test
    void addressIdentifiersAreOwnedAndDoNotDiscloseFullAddressOrPhone() {
        UserCommerceInternalController controller = new UserCommerceInternalController();
        UserAddressService service = mock(UserAddressService.class);
        ReflectionTestUtils.setField(controller, "userAddressService", service);
        assertThrows(HttpBusinessException.class, () -> controller.listAddresses(Map.of()));
        delegateAs("owner");
        assertThrows(HttpBusinessException.class, () -> controller.listAddresses(Map.of("userId", "other")));
        UserAddress address = new UserAddress();
        address.setAddressId("owned-address"); address.setDefaultType(1);
        address.setPhone("synthetic-private"); address.setAddress("private-street");
        when(service.findListByParam(argThat(q -> "owner".equals(q.getUserId())))).thenReturn(List.of(address));
        assertEquals(List.of(Map.of("addressId", "owned-address", "isDefault", true, "label", "收货地址 1")),
                controller.listAddresses(Map.of()).getData());
    }
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
    @SuppressWarnings("unchecked")
    void retainedBrowseFactsUseUserScopeAndDeduplicateBeforeLimiting() {
        UserCommerceInternalController controller = new UserCommerceInternalController();
        UserBrowseHistoryMapper<UserBrowseHistory, UserBrowseHistoryQuery> mapper =
                mock(UserBrowseHistoryMapper.class);
        ReflectionTestUtils.setField(controller, "userBrowseHistoryMapper", mapper);
        UserBrowseHistory first = new UserBrowseHistory();
        first.setProductId("p1");
        UserBrowseHistory second = new UserBrowseHistory();
        second.setProductId("p2");
        when(mapper.selectList(argThat(query -> "user-1".equals(query.getUserId()))))
                .thenReturn(List.of(first, first, second));
        delegateAs("user-1");
        assertEquals(List.of("p1", "p2"), controller.browseHistoryIds(
                Map.of("userId", "user-1", "limit", 2)).getData());
        assertEquals(List.of("p1", "p2"), controller.browseHistoryIds(Map.of()).getData());
        assertEquals(Map.of("productId", "p1"), controller.latestBrowseProductId(Map.of()).getData());
        verify(mapper, times(3)).selectList(argThat(query -> "user-1".equals(query.getUserId())));
    }

    @Test
    void bothBrowseQueriesRejectMissingOrMismatchedDelegationBeforeQuerying() {
        UserCommerceInternalController controller = new UserCommerceInternalController();
        UserBrowseHistoryMapper<?, ?> mapper = mock(UserBrowseHistoryMapper.class);
        ReflectionTestUtils.setField(controller, "userBrowseHistoryMapper", mapper);
        List<Consumer<Map<String, Object>>> queries = List.of(
                controller::latestBrowseProductId, controller::browseHistoryIds);
        for (Consumer<Map<String, Object>> query : queries) {
            RequestContextHolder.resetRequestAttributes();
            assertEquals(401, assertThrows(HttpBusinessException.class,
                    () -> query.accept(Map.of("userId", "user-1"))).getHttpStatus());
            delegateAs("user-1");
            assertEquals(403, assertThrows(HttpBusinessException.class,
                    () -> query.accept(Map.of("userId", "other-user"))).getHttpStatus());
        }
        verifyNoInteractions(mapper);
    }
}
