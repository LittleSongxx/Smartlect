package com.smartlect.controller.internal;

import com.smartlect.biz.AdminIdentityService;
import com.smartlect.biz.UserInfoService;
import com.smartlect.component.RedisComponent;
import com.smartlect.controller.AGlobalExceptionHandlerController;
import com.smartlect.entity.dto.AdminPrincipalDTO;
import com.smartlect.entity.dto.TokenUserInfoDTO;
import com.smartlect.entity.po.UserInfo;
import com.smartlect.exception.BusinessException;
import com.smartlect.web.InternalApiAuthFilter;
import jakarta.servlet.http.Cookie;
import org.apache.commons.codec.digest.DigestUtils;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.List;

import static org.hamcrest.Matchers.aMapWithSize;
import static org.hamcrest.Matchers.contains;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class IdentityInternalControllerTest {
    private final RedisComponent sessions = mock(RedisComponent.class);
    private final UserInfoService users = mock(UserInfoService.class);
    private final AdminIdentityService administrators = mock(AdminIdentityService.class);
    private MockMvc mvc;

    @BeforeEach
    void setUp() {
        InternalApiAuthFilter auth = new InternalApiAuthFilter();
        ReflectionTestUtils.setField(auth, "authEnabled", true);
        ReflectionTestUtils.setField(auth, "expectedToken", "service-secret");
        mvc = MockMvcBuilders.standaloneSetup(new IdentityInternalController(sessions, users, administrators))
                .setControllerAdvice(new AGlobalExceptionHandlerController()).addFilters(auth).build();
    }

    private MockHttpServletRequestBuilder request(String json) {
        return post("/internal/identity/introspect").header("X-Internal-Token", "service-secret")
                .contentType(MediaType.APPLICATION_JSON).content(json);
    }

    @Test
    void serviceTokenAndAnUnambiguousRealmCookieAreBothRequired() throws Exception {
        mvc.perform(post("/internal/identity/introspect").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"realm\":\"user\"}").cookie(new Cookie("token", "user-session")))
                .andExpect(status().isUnauthorized());
        mvc.perform(request("{\"realm\":\"user\"}").header("token", "header-only"))
                .andExpect(status().isUnauthorized());
        mvc.perform(request("{\"realm\":\"merchant\"}").cookie(new Cookie("token", "user-session")))
                .andExpect(status().isUnauthorized());
        mvc.perform(request("{\"realm\":\"user\"}")
                        .cookie(new Cookie("token", "first"), new Cookie("token", "second")))
                .andExpect(status().isUnauthorized());
        verifyNoInteractions(sessions, users, administrators);
    }

    @Test
    void clientCannotSelectAnActorOrSupplyAnUnrecognizedRealm() throws Exception {
        for (String json : List.of("", "{", "[]", "null", "{}", "{\"realm\":\"admin\"}", "{\"realm\":1}",
                "{\"realm\":\"user\",\"actorId\":\"someone-else\"}")) {
            mvc.perform(request(json).cookie(new Cookie("token", "user-session")))
                    .andExpect(status().isBadRequest());
        }
        verifyNoInteractions(sessions, users, administrators);
    }

    @Test
    void activeUserReturnsOnlyServerIdentityCapabilitiesAndSessionDigest() throws Exception {
        TokenUserInfoDTO session = new TokenUserInfoDTO();
        session.setUserId("user-1");
        session.setToken("user-session");
        session.setEmail("private@example.test");
        UserInfo user = new UserInfo();
        user.setUserId("user-1");
        user.setStatus(1);
        when(sessions.getTokenUserInfo("user-session")).thenReturn(session);
        when(users.getUserInfoByUserId("user-1")).thenReturn(user);

        mvc.perform(request("{\"realm\":\"user\"}").cookie(new Cookie("token", "user-session"))
                        .header("X-Smartlect-User-Id", "forged").header("X-Admin-Roles", "SUPER_ADMIN"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.status").value("success"))
                .andExpect(jsonPath("$.data", aMapWithSize(4)))
                .andExpect(jsonPath("$.data.subjectType").value("user"))
                .andExpect(jsonPath("$.data.actorId").value("user-1"))
                .andExpect(jsonPath("$.data.permissions").isArray())
                .andExpect(jsonPath("$.data.permissions").value(contains("shopping:read", "orders:read", "orders:write")))
                .andExpect(jsonPath("$.data.sessionId").value(DigestUtils.sha256Hex("user:user-session")))
                .andExpect(header().doesNotExist("Set-Cookie"));
        verify(sessions, never()).saveTokenUserInfo(any());
        verifyNoInteractions(administrators);
    }

    @Test
    void expiredMissingAndDisabledUsersCannotBeDowngradedIntoValidActors() throws Exception {
        mvc.perform(request("{\"realm\":\"user\"}").cookie(new Cookie("token", "expired")))
                .andExpect(status().isUnauthorized());
        TokenUserInfoDTO session = new TokenUserInfoDTO();
        session.setUserId("user-1");
        when(sessions.getTokenUserInfo("user-session")).thenReturn(session);
        mvc.perform(request("{\"realm\":\"user\"}").cookie(new Cookie("token", "user-session")))
                .andExpect(status().isUnauthorized());
        UserInfo disabled = new UserInfo();
        disabled.setStatus(0);
        when(users.getUserInfoByUserId("user-1")).thenReturn(disabled);
        mvc.perform(request("{\"realm\":\"user\"}").cookie(new Cookie("token", "user-session")))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void merchantUsesCurrentPermissionsAndRejectsExpiredVersionsOrDisabledAccounts() throws Exception {
        mvc.perform(request("{\"realm\":\"merchant\"}").cookie(new Cookie("adminToken", "expired")))
                .andExpect(status().isUnauthorized());
        AdminPrincipalDTO session = new AdminPrincipalDTO();
        session.setAdminId("7");
        session.setSessionVersion(2L);
        session.setPermissions(List.of("admin:manage"));
        AdminPrincipalDTO current = new AdminPrincipalDTO();
        current.setAdminId("7");
        current.setSessionVersion(2L);
        current.setPermissions(List.of("analytics:read", "analytics:export"));
        when(sessions.getAdminPrincipal("admin-session")).thenReturn(session);
        when(administrators.principal(7)).thenReturn(current);

        mvc.perform(request("{\"realm\":\"merchant\"}").cookie(new Cookie("adminToken", "admin-session")))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data", aMapWithSize(4)))
                .andExpect(jsonPath("$.data.subjectType").value("merchant"))
                .andExpect(jsonPath("$.data.actorId").value("7"))
                .andExpect(jsonPath("$.data.permissions").isArray())
                .andExpect(jsonPath("$.data.permissions").value(contains("analytics:export", "analytics:read")))
                .andExpect(jsonPath("$.data.sessionId").value(DigestUtils.sha256Hex("merchant:admin-session")))
                .andExpect(header().doesNotExist("Set-Cookie"));
        current.setSessionVersion(3L);
        mvc.perform(request("{\"realm\":\"merchant\"}").cookie(new Cookie("adminToken", "admin-session")))
                .andExpect(status().isUnauthorized());
        when(administrators.principal(7)).thenThrow(new BusinessException("管理员已停用"));
        mvc.perform(request("{\"realm\":\"merchant\"}").cookie(new Cookie("adminToken", "admin-session")))
                .andExpect(status().isUnauthorized());
        verifyNoInteractions(users);
    }
}
