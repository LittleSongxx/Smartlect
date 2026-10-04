package com.smartlect.component;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.smartlect.constants.Constants;
import com.smartlect.entity.dto.TokenUserInfoDTO;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.Duration;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/** Sa-Token 键布局（token:login:*）裸读契约，格式与 sa-token-redis-jackson 1.39.0 实测输出一致。 */
class RedisComponentSaTokenSessionTest {

    private static final String SESSION_JSON = """
            {"@class":"cn.dev33.satoken.dao.SaSessionForJacksonCustomized",
             "id":"token:login:session:u1","type":"Account-Session","loginType":"login","loginId":"u1",
             "token":null,"createTime":1791106553744,
             "dataMap":{"@class":"java.util.concurrent.ConcurrentHashMap",
               "userInfo":{"@class":"com.smartlect.entity.dto.TokenUserInfoDTO",
                 "userId":"u1","email":"u1@x.test","nickName":"nick","avatar":"a.png","trial":false}},
             "tokenSignList":["java.util.Vector",[
               {"@class":"cn.dev33.satoken.session.TokenSign","value":"token-a","device":"default-device","tag":null},
               {"@class":"cn.dev33.satoken.session.TokenSign","value":"token-b","device":"default-device","tag":null}]]}
            """;

    private final StringRedisTemplate redis = mock(StringRedisTemplate.class);
    private final ValueOperations<String, String> values = mock(ValueOperations.class);
    private final RedisComponent component = new RedisComponent();

    @BeforeEach
    void setUp() {
        when(redis.opsForValue()).thenReturn(values);
        ReflectionTestUtils.setField(component, "stringRedisTemplate", redis);
        ReflectionTestUtils.setField(component, "objectMapper", new ObjectMapper());
    }

    @Test
    void tokenResolvesToLoginIdThenSessionUserInfo() {
        when(values.get(Constants.REDIS_KEY_TOKEN_WEB + "token-a")).thenReturn("u1");
        when(values.get(Constants.REDIS_KEY_TOKEN_WEB_SESSION + "u1")).thenReturn(SESSION_JSON);

        TokenUserInfoDTO dto = component.getTokenUserInfo("token-a");

        assertEquals("u1", dto.getUserId());
        assertEquals("u1@x.test", dto.getEmail());
        assertEquals("nick", dto.getNickName());
        assertEquals("a.png", dto.getAvatar());
        assertEquals(Boolean.FALSE, dto.getTrial());
        assertEquals("token-a", dto.getToken());
    }

    @Test
    void missingTokenKeyOrSessionYieldsNull() {
        when(values.get(Constants.REDIS_KEY_TOKEN_WEB + "unknown")).thenReturn(null);
        assertNull(component.getTokenUserInfo("unknown"));
        assertNull(component.getUserIdByToken("unknown"));
        assertNull(component.getUserIdByToken(null));

        when(values.get(Constants.REDIS_KEY_TOKEN_WEB + "orphan")).thenReturn("u1");
        when(values.get(Constants.REDIS_KEY_TOKEN_WEB_SESSION + "u1")).thenReturn(null);
        assertNull(component.getTokenUserInfo("orphan"));
    }

    @Test
    void brokenSessionJsonYieldsNullInsteadOfThrowing() {
        when(values.get(Constants.REDIS_KEY_TOKEN_WEB + "bad")).thenReturn("u1");
        when(values.get(Constants.REDIS_KEY_TOKEN_WEB_SESSION + "u1")).thenReturn("not-json{");
        assertNull(component.getTokenUserInfo("bad"));
    }

    @Test
    void userIdLookupReadsSessionAndFirstTokenSign() {
        when(values.get(Constants.REDIS_KEY_TOKEN_WEB_SESSION + "u1")).thenReturn(SESSION_JSON);

        TokenUserInfoDTO dto = component.getTokenUserInfoByUserId("u1");

        assertEquals("u1", dto.getUserId());
        assertEquals("token-a", dto.getToken());
    }

    @Test
    void cleanAllTokenRemovesEverySignedTokenAndTheSession() {
        when(values.get(Constants.REDIS_KEY_TOKEN_WEB_SESSION + "u1")).thenReturn(SESSION_JSON);

        component.cleanAllToken("u1");

        verify(redis).delete(Constants.REDIS_KEY_TOKEN_WEB + "token-a");
        verify(redis).delete(Constants.REDIS_KEY_TOKEN_WEB + "token-b");
        verify(redis).delete(Constants.REDIS_KEY_TOKEN_WEB_SESSION + "u1");
    }

    @Test
    void updateUserRenewsTokenAndSessionTtlForOneDay() {
        when(values.get(Constants.REDIS_KEY_TOKEN_WEB_SESSION + "u1")).thenReturn(SESSION_JSON);

        component.updateUser("u1");

        verify(redis).expire(Constants.REDIS_KEY_TOKEN_WEB + "token-a", Duration.ofDays(1));
        verify(redis).expire(Constants.REDIS_KEY_TOKEN_WEB_SESSION + "u1", Duration.ofDays(1));
    }
}
