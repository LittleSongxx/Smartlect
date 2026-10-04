package com.smartlect.component;

import com.smartlect.constants.Constants;
import com.smartlect.entity.config.AppConfig;
import com.smartlect.entity.dto.*;
import com.smartlect.exception.BusinessException;
import com.smartlect.redis.RedisUtils;
import com.smartlect.utils.DateUtil;
import com.smartlect.utils.JsonUtils;
import com.smartlect.utils.StringTools;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.annotation.Resource;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.*;
import java.util.concurrent.TimeUnit;

@Component("redisComponent")
@Slf4j
public class RedisComponent {

    @Resource
    private RedisTemplate redisTemplate;
    @Resource
    private RedisUtils redisUtils;
    @Resource
    private StringRedisTemplate stringRedisTemplate;
    @Resource
    private AppConfig appConfig;

    @Resource
    private ObjectMapper objectMapper;

    public void saveCategory2Redis(List<?> list) {
        redisUtils.set(Constants.REDIS_KEY_CATEGORY_LIST, list);
    }

    public String saveCheckCode(String code){
        // 1.对code生成UUID
        String codeKey = UUID.randomUUID().toString();
        // 2.将code和UUID保存到Redis中，设置5分钟过期时间
        redisUtils.setex(Constants.REDIS_KEY_CHECK_CODE + codeKey, code, Constants.LENGTH_5 * 60);
        // 3.返回UUID
        return codeKey;
    }

    public String getCheckCode(@NotEmpty String checkCodeKey) {
        return (String) redisTemplate.opsForValue().get(Constants.REDIS_KEY_CHECK_CODE + checkCodeKey);
    }

    public String saveToken4Admin(@NotNull AdminPrincipalDTO principal) {
        if (StringTools.isEmpty(principal.getAdminId()) || principal.getSessionVersion() == null) {
            throw new IllegalArgumentException("管理员主体缺少ID或会话版本");
        }
        String accountKey = Constants.REDIS_KEY_TOKEN_ADMIN_ACCOUNT + principal.getAdminId();
        Object oldToken = redisUtils.get(accountKey);
        if (oldToken != null && !StringTools.isEmpty(String.valueOf(oldToken))) {
            redisTemplate.delete(Constants.REDIS_KEY_TOKEN_ADMIN + oldToken);
        }
        String token = UUID.randomUUID().toString().replace("-", "");
        stringRedisTemplate.opsForValue().set(
                Constants.REDIS_KEY_ADMIN_SESSION_VERSION + principal.getAdminId(),
                String.valueOf(principal.getSessionVersion()));
        redisUtils.setex(Constants.REDIS_KEY_TOKEN_ADMIN + token, principal, Constants.REDIS_KEY_EXPIRES_DAY);
        redisUtils.setex(accountKey, token, Constants.REDIS_KEY_EXPIRES_DAY);
        return token;
    }

    public void cleanCheckCode(@NotEmpty String checkCodeKey) {
        redisTemplate.delete(Constants.REDIS_KEY_CHECK_CODE + checkCodeKey);
    }

    public void cleanToken4Admin(String token) {
        if (StringTools.isEmpty(token)) {
            return;
        }
        AdminPrincipalDTO principal = parseAdminPrincipal(
                redisTemplate.opsForValue().get(Constants.REDIS_KEY_TOKEN_ADMIN + token));
        if (principal != null && !StringTools.isEmpty(principal.getAdminId())) {
            Object mappedToken = redisUtils.get(
                    Constants.REDIS_KEY_TOKEN_ADMIN_ACCOUNT + principal.getAdminId());
            if (token.equals(String.valueOf(mappedToken))) {
                redisUtils.delete(Constants.REDIS_KEY_TOKEN_ADMIN_ACCOUNT + principal.getAdminId());
            }
        }
        redisTemplate.delete(Constants.REDIS_KEY_TOKEN_ADMIN + token);
    }

    public AdminPrincipalDTO getAdminPrincipal(String token) {
        if (StringTools.isEmpty(token)) {
            return null;
        }
        AdminPrincipalDTO principal = parseAdminPrincipal(
                redisTemplate.opsForValue().get(Constants.REDIS_KEY_TOKEN_ADMIN + token));
        if (principal == null || StringTools.isEmpty(principal.getAdminId())
                || principal.getSessionVersion() == null) {
            return null;
        }
        String currentVersion = stringRedisTemplate.opsForValue().get(
                Constants.REDIS_KEY_ADMIN_SESSION_VERSION + principal.getAdminId());
        if (!String.valueOf(principal.getSessionVersion()).equals(currentVersion)) {
            redisTemplate.delete(Constants.REDIS_KEY_TOKEN_ADMIN + token);
            return null;
        }
        return principal;
    }

    public Object getLoginInfo4Admin(String token) {
        return getAdminPrincipal(token);
    }

    public void invalidateAdminSessions(String adminId, long sessionVersion) {
        if (StringTools.isEmpty(adminId)) {
            return;
        }
        String accountKey = Constants.REDIS_KEY_TOKEN_ADMIN_ACCOUNT + adminId;
        Object token = redisUtils.get(accountKey);
        if (token != null && !StringTools.isEmpty(String.valueOf(token))) {
            redisTemplate.delete(Constants.REDIS_KEY_TOKEN_ADMIN + token);
        }
        redisUtils.delete(accountKey);
        stringRedisTemplate.opsForValue().set(
                Constants.REDIS_KEY_ADMIN_SESSION_VERSION + adminId,
                String.valueOf(sessionVersion));
    }

    private AdminPrincipalDTO parseAdminPrincipal(Object value) {
        if (value instanceof AdminPrincipalDTO principal) {
            return principal;
        }
        if (!(value instanceof Map<?, ?> map)) {
            // String-only sessions are deliberately rejected after the RBAC migration.
            return null;
        }
        Object adminId = map.get("adminId");
        Object account = map.get("account");
        Object displayName = map.get("displayName");
        Object version = map.get("sessionVersion");
        if (adminId == null || version == null) {
            return null;
        }
        AdminPrincipalDTO principal = new AdminPrincipalDTO();
        principal.setAdminId(String.valueOf(adminId));
        principal.setAccount(account == null ? null : String.valueOf(account));
        principal.setDisplayName(displayName == null ? null : String.valueOf(displayName));
        try {
            principal.setSessionVersion(Long.parseLong(String.valueOf(version)));
        } catch (NumberFormatException e) {
            return null;
        }
        principal.setRoles(toStringSet(map.get("roles")));
        principal.setPermissions(toStringSet(map.get("permissions")));
        return principal;
    }

    private Set<String> toStringSet(Object value) {
        if (!(value instanceof Collection<?> collection)) {
            return Collections.emptySet();
        }
        Set<String> values = new LinkedHashSet<>();
        for (Object item : collection) {
            if (item != null && !StringTools.isEmpty(String.valueOf(item))) {
                values.add(String.valueOf(item));
            }
        }
        return values;
    }

    @SuppressWarnings("unchecked")
    public List<?> getCategoryList() {
        List<?> list = (List<?>) redisUtils.get(Constants.REDIS_KEY_CATEGORY_LIST);
        return list == null ? null : list;
    }

    // ===== 用户端 web 会话（Sa-Token 键布局，ADR-0011 Step 1）=====
    // 登录态由 user 服务 StpUtil 写入；common 不依赖 Sa-Token SDK，按下述格式裸读写：
    //   token:login:token:{token}     -> loginId 裸字符串
    //   token:login:session:{loginId} -> Account-Session JSON，dataMap.userInfo 即 TokenUserInfoDTO

    // 根据token获取TokenUserInfoDTO
    public TokenUserInfoDTO getTokenUserInfo(String token) {
        String loginId = getUserIdByToken(token);
        if (loginId == null) {
            return null;
        }
        String sessionJson = stringRedisTemplate.opsForValue()
                .get(Constants.REDIS_KEY_TOKEN_WEB_SESSION + loginId);
        TokenUserInfoDTO tokenUserInfoDTO = parseSessionUserInfo(sessionJson);
        if (tokenUserInfoDTO == null) {
            return null;
        }
        tokenUserInfoDTO.setToken(token);
        return tokenUserInfoDTO;
    }

    // 根据userId获取TokenUserInfoDTO（取账号会话里登记的任一有效token）
    public TokenUserInfoDTO getTokenUserInfoByUserId(String userId) {
        String sessionJson = stringRedisTemplate.opsForValue()
                .get(Constants.REDIS_KEY_TOKEN_WEB_SESSION + userId);
        TokenUserInfoDTO tokenUserInfoDTO = parseSessionUserInfo(sessionJson);
        if (tokenUserInfoDTO != null) {
            tokenUserInfoDTO.setToken(parseFirstTokenSign(sessionJson));
        }
        return tokenUserInfoDTO;
    }

    public String getUserIdByToken(String token) {
        if (StringTools.isEmpty(token)) {
            return null;
        }
        String loginId = stringRedisTemplate.opsForValue().get(Constants.REDIS_KEY_TOKEN_WEB + token);
        return StringTools.isEmpty(loginId) ? null : loginId;
    }

    // 修改个人资料后无需重新登录：资料字段以库为准（autoLogin 每次用库值覆盖会话），
    // 这里只把 token 与账号会话续期一天，等价旧实现的"改资料不掉线"。
    public void updateUser(String userId) {
        TokenUserInfoDTO tokenUserInfoDTO = getTokenUserInfoByUserId(userId);
        if (tokenUserInfoDTO == null || StringTools.isEmpty(tokenUserInfoDTO.getToken())) {
            return;
        }
        stringRedisTemplate.expire(Constants.REDIS_KEY_TOKEN_WEB + tokenUserInfoDTO.getToken(),
                Duration.ofSeconds(Constants.REDIS_KEY_EXPIRES_DAY));
        stringRedisTemplate.expire(Constants.REDIS_KEY_TOKEN_WEB_SESSION + userId,
                Duration.ofSeconds(Constants.REDIS_KEY_EXPIRES_DAY));
    }

    // 踢掉 userId 的全部登录设备（Sa-Token 账号会话的 tokenSignList 覆盖所有在线 token）
    public void cleanAllToken(@NotNull String userId) {
        String sessionKey = Constants.REDIS_KEY_TOKEN_WEB_SESSION + userId;
        String sessionJson = stringRedisTemplate.opsForValue().get(sessionKey);
        if (StringTools.isEmpty(sessionJson)) {
            return;
        }
        for (String token : parseAllTokenSigns(sessionJson)) {
            stringRedisTemplate.delete(Constants.REDIS_KEY_TOKEN_WEB + token);
        }
        stringRedisTemplate.delete(sessionKey);
    }

    private TokenUserInfoDTO parseSessionUserInfo(String sessionJson) {
        if (StringTools.isEmpty(sessionJson)) {
            return null;
        }
        try {
            JsonNode userInfo = objectMapper.readTree(sessionJson).path("dataMap").path("userInfo");
            if (!userInfo.isObject() || StringTools.isEmpty(userInfo.path("userId").asText(null))) {
                return null;
            }
            TokenUserInfoDTO dto = new TokenUserInfoDTO();
            dto.setUserId(userInfo.path("userId").asText());
            dto.setEmail(textOrNull(userInfo, "email"));
            dto.setNickName(textOrNull(userInfo, "nickName"));
            dto.setAvatar(textOrNull(userInfo, "avatar"));
            JsonNode trial = userInfo.path("trial");
            dto.setTrial(trial.isBoolean() ? trial.asBoolean() : null);
            return dto;
        } catch (Exception e) {
            log.warn("解析 Sa-Token 账号会话失败：{}", e.getMessage());
            return null;
        }
    }

    private String parseFirstTokenSign(String sessionJson) {
        JsonNode signs = tokenSignArray(sessionJson);
        return signs == null || signs.isEmpty() ? null : signs.get(0).path("value").asText(null);
    }

    private List<String> parseAllTokenSigns(String sessionJson) {
        JsonNode signs = tokenSignArray(sessionJson);
        if (signs == null) {
            return Collections.emptyList();
        }
        List<String> tokens = new ArrayList<>();
        for (JsonNode sign : signs) {
            String token = sign.path("value").asText(null);
            if (!StringTools.isEmpty(token)) {
                tokens.add(token);
            }
        }
        return tokens;
    }

    // tokenSignList 由 GenericJackson2JsonRedisSerializer 序列化为 ["java.util.Vector",[{...}]]
    private JsonNode tokenSignArray(String sessionJson) {
        if (StringTools.isEmpty(sessionJson)) {
            return null;
        }
        try {
            JsonNode list = objectMapper.readTree(sessionJson).path("tokenSignList");
            if (list.isArray() && list.size() == 2 && list.get(0).isTextual()) {
                list = list.get(1);
            }
            return list.isArray() ? list : null;
        } catch (Exception e) {
            return null;
        }
    }

    private String textOrNull(JsonNode node, String field) {
        JsonNode value = node.get(field);
        return value == null || value.isNull() ? null : value.asText();
    }

    // 添加到延时队列
    public void addOrder2DelayQueue(String queueName,Integer delayMinute,String orderId){
        // zset,以当前时间毫秒+delayMinute转毫秒为score
        long expireTime = System.currentTimeMillis() + delayMinute * 60 * 1000;
        redisUtils.zsetAdd(queueName, orderId, expireTime);
    }

    // 获取超时订单
    public Set<String> getTimeOutOrder(String queueName){
        // 从score为0开始到当前时间顺序取出
        return redisUtils.zsetRangeByScore(queueName, 0, System.currentTimeMillis());
    }

    // 移除超时订单
    public long removeTimeOutOrder(String queueName,String orderId){
        return redisUtils.zsetAddRemove(queueName, orderId);
    }

    public void saveLogistics(LogisticsSendDTO logisticsSendDTO) {
        redisUtils.set(Constants.REDIS_KEY_SETTING_LOGISTICS, logisticsSendDTO);
    }

    public LogisticsSendDTO getLogistics(String senderName) {
        return (LogisticsSendDTO) redisUtils.get(Constants.REDIS_KEY_SETTING_LOGISTICS + senderName);
    }

    public void addOrder2DeliverQueue(String redisKeyOrderDelayQueue, Integer delaySecond, String orderId) {
        redisUtils.zsetAdd(redisKeyOrderDelayQueue, orderId, System.currentTimeMillis() + delaySecond * 1000);
    }

    public LogisticsSendDTO getLogisticsInfo() {
        LogisticsSendDTO current = (LogisticsSendDTO) redisUtils.get(Constants.REDIS_KEY_SETTING_LOGISTICS);
        if (current != null && !StringTools.isEmpty(current.getSenderName())) {
            return current;
        }
        LogisticsSendDTO seeded = new LogisticsSendDTO();
        seeded.setSenderName("智选商城");
        seeded.setSenderPhone("400-000-0000");
        seeded.setSenderAddress("演示仓（作品集默认发货地址）");
        redisUtils.set(Constants.REDIS_KEY_SETTING_LOGISTICS, seeded);
        return seeded;
    }

    public void saveUserLocationCoords(String userId, UserLocationCoordsDTO coords) {
        if (StringTools.isEmpty(userId) || coords == null) {
            return;
        }
        redisUtils.setex(Constants.REDIS_KEY_USER_LOCATION + userId, coords, appConfig.getUserLocationExpireDay() * 24L * 3600);
    }

    public UserLocationCoordsDTO getUserLocationCoords(String userId) {
        if (StringTools.isEmpty(userId)) {
            return null;
        }
        return (UserLocationCoordsDTO) redisUtils.get(Constants.REDIS_KEY_USER_LOCATION + userId);
    }

    // 支付单生命周期的锁与一次性标记搬到 PayOrderRedisComponent。
    // 抢购预占（库存计数 + 参与者 SET + 预占 hash 的联动 Lua）搬到 CouponRushRedisComponent。

    public void deleteCacheKey(String key) {
        if (StringTools.isEmpty(key)) {
            return;
        }
        redisUtils.delete(key);
    }

    public boolean setIfAbsent(String key, String value, long timeout, TimeUnit unit) {
        Boolean ok = stringRedisTemplate.opsForValue().setIfAbsent(key, value, timeout, unit);
        return Boolean.TRUE.equals(ok);
    }

    private static final String MEMBER_LEVEL_CLAIM_PREFIX = "smartlect:member:level:claim:";

    public java.util.Set<Integer> getMemberLevelClaimed(String userId) {
        String raw = stringRedisTemplate.opsForValue().get(MEMBER_LEVEL_CLAIM_PREFIX + userId);
        java.util.Set<Integer> set = new java.util.HashSet<>();
        if (StringTools.isEmpty(raw)) {
            return set;
        }
        for (String part : raw.split(",")) {
            if (StringTools.isEmpty(part)) {
                continue;
            }
            try {
                set.add(Integer.parseInt(part.trim()));
            } catch (NumberFormatException ignored) {
            }
        }
        return set;
    }

    public void addMemberLevelClaimed(String userId, int levelCode) {
        java.util.Set<Integer> set = getMemberLevelClaimed(userId);
        set.add(levelCode);
        StringBuilder sb = new StringBuilder();
        for (Integer code : set) {
            if (sb.length() > 0) {
                sb.append(',');
            }
            sb.append(code);
        }
        stringRedisTemplate.opsForValue().set(MEMBER_LEVEL_CLAIM_PREFIX + userId, sb.toString());
    }

    public long incr(String key) {
        return stringRedisTemplate.opsForValue().increment(key);
    }

    public long decr(String key) {
        return stringRedisTemplate.opsForValue().decrement(key);
    }

    public long getCounter(String key) {
        String value = stringRedisTemplate.opsForValue().get(key);
        return value == null ? 0 : Long.parseLong(value);
    }

    public void setCounter(String key, long value) {
        stringRedisTemplate.opsForValue().set(key, String.valueOf(value));
    }

    public void deleteCounter(String key) {
        stringRedisTemplate.delete(key);
    }

    // 邮件验证码
    public void saveEmailCode(String email, String code){
        // 将email和code保存到Redis中，设置5分钟过期时间
        redisUtils.setex(Constants.REDIS_KEY_EMAIL_CODE + email, code, Constants.LENGTH_5 * 60);
    }

    // 获取邮件验证码
    public String getEmailCode(@NotEmpty String email) {
        return (String) redisTemplate.opsForValue().get(Constants.REDIS_KEY_EMAIL_CODE + email);
    }

    // 清理邮件验证码
    public void cleanEmailCode(@NotEmpty String email) {
        redisTemplate.delete(Constants.REDIS_KEY_EMAIL_CODE + email);
    }
}
