package com.smartlect.controller.internal;

import com.smartlect.component.RedisComponent;
import com.smartlect.exception.BusinessException;
import com.smartlect.service.PasswordService;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;

import java.util.List;

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
        when(redis.saveTokenUserInfo(any())).thenReturn("issued-token");
        assertEquals("success", controller.session(0, secret).getStatus());
        assertThrows(BusinessException.class, () -> controller.session(0, "wrong"));
        assertThrows(BusinessException.class, () -> controller.session(100, secret));
        verify(redis, times(1)).saveTokenUserInfo(argThat(user -> "9100000000".equals(user.getUserId())));
        assertThrows(IllegalStateException.class,
                () -> new DemoFixtureController(jdbc, passwords, redis, secret, "live"));
    }
}
