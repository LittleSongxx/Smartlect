package com.smartlect.controller.internal;

import com.smartlect.entity.po.UserAddress;
import com.smartlect.biz.UserAddressService;
import com.smartlect.constants.InternalApiHeaders;
import com.smartlect.exception.HttpBusinessException;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

import java.util.List;
import java.util.Map;

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
}
