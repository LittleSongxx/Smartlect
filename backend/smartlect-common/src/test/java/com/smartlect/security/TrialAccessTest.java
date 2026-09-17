package com.smartlect.security;

import com.smartlect.constants.TrialIdentities;
import com.smartlect.entity.dto.AdminPrincipalDTO;
import com.smartlect.entity.dto.TokenUserInfoDTO;
import jakarta.servlet.http.HttpServletRequest;
import org.junit.jupiter.api.Test;

import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class TrialAccessTest {

    @Test
    void publishedVisitorAndGalleryAreRecognizedWithoutGrantingOwnerPower() {
        TokenUserInfoDTO visitor = new TokenUserInfoDTO();
        visitor.setUserId(TrialIdentities.USER_ID);
        visitor.setEmail(TrialIdentities.USER_EMAIL);
        visitor.setTrial(true);
        assertTrue(TrialIdentities.isTrialUser(visitor));
        assertFalse(TrialIdentities.isTrialUser("9100000000", "buyer@demo.smartlect.local"));

        AdminPrincipalDTO gallery = new AdminPrincipalDTO();
        gallery.setAccount(TrialIdentities.ADMIN_ACCOUNT);
        gallery.setRoles(Set.of("TRIAL_OPERATOR"));
        gallery.setPermissions(Set.of("admin:trial"));
        assertTrue(TrialIdentities.isTrialAdmin(gallery));
        assertTrue(TrialIdentities.skipLoginCaptcha(TrialIdentities.USER_EMAIL));
        assertTrue(TrialIdentities.skipLoginCaptcha(TrialIdentities.ADMIN_ACCOUNT));
        assertFalse(TrialIdentities.skipLoginCaptcha("admin"));

        AdminPrincipalDTO owner = new AdminPrincipalDTO();
        owner.setAccount("admin");
        owner.setRoles(Set.of("SUPER_ADMIN"));
        assertFalse(TrialIdentities.isTrialAdmin(owner));
    }

    @Test
    void adminAllowlistCoversDashboardAndBlocksUserPrivacy() {
        assertTrue(TrialAdminAccess.allows(null, request("/admin/home/getTodayData")));
        assertTrue(TrialAdminAccess.allows(null, request("/admin/productInfo/loadProduct")));
        assertFalse(TrialAdminAccess.allows(null, request("/admin/user/loadUser")));
        assertFalse(TrialAdminAccess.allows(null, request("/admin/userAddress/loadDataList")));
        assertFalse(TrialAdminAccess.allows(null, request("/admin/order/getLogistics")));
        assertFalse(TrialAdminAccess.allows(null, request("/admin/orderLogisticsInfo/loadDataList")));
        assertFalse(TrialAdminAccess.allows(null, request("/admin/productInfo/updateProduct")));
    }

    @Test
    void userWritePathsAreBlocked() {
        assertTrue(TrialUserAccess.isBlocked(request("/order/postOrder")));
        assertTrue(TrialUserAccess.isBlocked(request("/api/productCart/add2Cart")));
        assertTrue(TrialUserAccess.isBlocked(request("/account/updatePassword")));
        assertFalse(TrialUserAccess.isBlocked(request("/account/login")));
        assertFalse(TrialUserAccess.isBlocked(request("/product/loadProduct")));
    }

    private static HttpServletRequest request(String path) {
        HttpServletRequest request = mock(HttpServletRequest.class);
        when(request.getServletPath()).thenReturn(path);
        when(request.getRequestURI()).thenReturn(path);
        return request;
    }
}
