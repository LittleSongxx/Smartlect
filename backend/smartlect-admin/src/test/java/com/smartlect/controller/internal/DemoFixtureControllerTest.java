package com.smartlect.controller.internal;

import cn.dev33.satoken.stp.StpUtil;
import com.smartlect.component.RedisComponent;
import com.smartlect.entity.dto.TokenUserInfoDTO;
import com.smartlect.exception.BusinessException;
import com.smartlect.service.PasswordService;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class DemoFixtureControllerTest {
    @Test
    void onlyActiveFixtureUsersWithTheGeneratedPasswordReceiveSessions() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        PasswordService passwords = mock(PasswordService.class);
        RedisComponent redis = mock(RedisComponent.class);
        String secret = "local-demo-password-for-test-only";
        DemoFixtureController controller = new DemoFixtureController(jdbc, passwords, redis, secret, "mock");
        when(jdbc.queryForList(contains("AND status=1"), eq(String.class), eq("9100000000")))
                .thenReturn(List.of("stored-hash"));
        when(passwords.matches(secret, "stored-hash")).thenReturn(true);
        assertEquals("success", controller.session(0, secret).getStatus());
        // 会话改由 StpUtil.createLoginSession 写入（内存 dao 即可验证），不再走 RedisComponent
        @SuppressWarnings("unchecked")
        Map<String, Object> data = (Map<String, Object>) controller.session(0, secret).getData();
        String token = (String) data.get("token");
        assertEquals("9100000000", StpUtil.getLoginIdByToken(token));
        TokenUserInfoDTO stored = (TokenUserInfoDTO) StpUtil.getSessionByLoginId("9100000000").get("userInfo");
        assertEquals("9100000000", stored.getUserId());
        assertThrows(BusinessException.class, () -> controller.session(0, "wrong"));
        assertThrows(BusinessException.class, () -> controller.session(100, secret));
        assertThrows(IllegalStateException.class,
                () -> new DemoFixtureController(jdbc, passwords, redis, secret, "live"));
    }
}
