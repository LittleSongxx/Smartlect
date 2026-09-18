package com.smartlect.biz;

import com.smartlect.api.enums.UserSexEnum;
import com.smartlect.api.enums.UserStatusEnum;
import com.smartlect.constants.TrialIdentities;
import com.smartlect.entity.config.AppConfig;
import com.smartlect.utils.StringTools;
import jakarta.annotation.PostConstruct;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Map;

@Service
public class TrialAccountService {

    static final String[] SHOPPER_BROWSE_PRODUCTS = {
            "065293686460191",
            "303019597302892",
            "917186661226040",
            "622491960431656"
    };

    private final JdbcTemplate jdbcTemplate;
    private final AppConfig appConfig;

    public TrialAccountService(JdbcTemplate jdbcTemplate, AppConfig appConfig) {
        this.jdbcTemplate = jdbcTemplate;
        this.appConfig = appConfig;
    }

    @PostConstruct
    public void migratePublishedDemoAccounts() {
        if (!appConfig.isTrialEnabled() || StringTools.isEmpty(appConfig.getTrialPasswordHash())) {
            return;
        }
        ensureUser(TrialIdentities.USER_ID, TrialIdentities.USER_EMAIL, TrialIdentities.USER_NICK);
        ensureUser(TrialIdentities.SHOPPER_USER_ID, TrialIdentities.SHOPPER_EMAIL, TrialIdentities.SHOPPER_NICK);
        ensureShopperProfile();
    }

    void ensureShopperProfile() {
        String userId = TrialIdentities.SHOPPER_USER_ID;
        upsertAddress(
                TrialIdentities.SHOPPER_DEFAULT_ADDRESS_ID,
                userId,
                "北京市海淀区中关村大街1号 智选演示收货处",
                TrialIdentities.SHOPPER_NICK,
                TrialIdentities.SHOPPER_PHONE,
                1);
        upsertAddress(
                TrialIdentities.SHOPPER_BACKUP_ADDRESS_ID,
                userId,
                "上海市浦东新区世纪大道88号 备用收货处",
                TrialIdentities.SHOPPER_NICK,
                TrialIdentities.SHOPPER_PHONE,
                0);
        jdbcTemplate.update(
                "UPDATE user_address SET default_type=0 WHERE user_id=? AND address_id<>?",
                userId, TrialIdentities.SHOPPER_DEFAULT_ADDRESS_ID);
        jdbcTemplate.update(
                "UPDATE user_address SET default_type=1 WHERE address_id=? AND user_id=?",
                TrialIdentities.SHOPPER_DEFAULT_ADDRESS_ID, userId);
        for (int i = 0; i < SHOPPER_BROWSE_PRODUCTS.length; i++) {
            jdbcTemplate.update(
                    """
                    INSERT IGNORE INTO user_browse_history (user_id, product_id, browse_time)
                    VALUES (?, ?, DATE_SUB(NOW(), INTERVAL ? HOUR))
                    """,
                    userId, SHOPPER_BROWSE_PRODUCTS[i], i + 1);
        }
        jdbcTemplate.update(
                """
                INSERT IGNORE INTO user_member_profile
                    (user_id, level_code, growth_value, level_name, update_time)
                VALUES (?, 2, 1200, '银卡会员', NOW())
                """,
                userId);
        jdbcTemplate.update(
                """
                INSERT IGNORE INTO user_product_favorite
                    (favorite_id, user_id, product_id, create_time)
                VALUES (?, ?, ?, NOW())
                """,
                "FAV8800000002P01", userId, SHOPPER_BROWSE_PRODUCTS[0]);
        jdbcTemplate.update(
                """
                INSERT IGNORE INTO user_notification
                    (notification_id, user_id, title, content, biz_type, biz_id, read_status, create_time)
                VALUES (?, ?, ?, ?, 'system', 'demo-welcome', 0, NOW())
                """,
                "NTF8800000002WEL1",
                userId,
                "演示资料已就绪",
                "已预置默认收货地址、备用地址、体验券和浏览足迹，可直接让导购帮你下单。");
    }

    private void ensureUser(String userId, String email, String nick) {
        List<Map<String, Object>> existing = jdbcTemplate.queryForList(
                "SELECT user_id, email, nick_name FROM user_info WHERE email = ? OR user_id = ?",
                email, userId);
        if (!existing.isEmpty()) {
            jdbcTemplate.update(
                    """
                    UPDATE user_info
                    SET password = ?, status = ?, nick_name = ?, email = ?
                    WHERE email = ? OR user_id = ?
                    """,
                    appConfig.getTrialPasswordHash(),
                    UserStatusEnum.ENABLE.getStatus(),
                    uniqueNick(existing.get(0), userId, nick),
                    email,
                    email,
                    userId);
            return;
        }
        try {
            jdbcTemplate.update(
                    """
                    INSERT INTO user_info
                        (user_id, nick_name, email, password, sex, join_time, status)
                    VALUES (?, ?, ?, ?, ?, NOW(), ?)
                    """,
                    userId,
                    nick,
                    email,
                    appConfig.getTrialPasswordHash(),
                    UserSexEnum.SECRECY.getType(),
                    UserStatusEnum.ENABLE.getStatus());
        } catch (DuplicateKeyException ignored) {
            jdbcTemplate.update(
                    """
                    UPDATE user_info
                    SET password = ?, status = ?, email = ?
                    WHERE email = ? OR user_id = ?
                    """,
                    appConfig.getTrialPasswordHash(),
                    UserStatusEnum.ENABLE.getStatus(),
                    email,
                    email,
                    userId);
        }
    }

    private void upsertAddress(
            String addressId, String userId, String address, String addressee, String phone, int defaultType) {
        jdbcTemplate.update(
                """
                INSERT INTO user_address
                    (address_id, user_id, address, addressee, phone, default_type)
                VALUES (?, ?, ?, ?, ?, ?) AS incoming
                ON DUPLICATE KEY UPDATE
                    user_id = incoming.user_id,
                    address = incoming.address,
                    addressee = incoming.addressee,
                    phone = incoming.phone,
                    default_type = incoming.default_type
                """,
                addressId, userId, address, addressee, phone, defaultType);
    }

    private String uniqueNick(Map<String, Object> row, String userId, String wanted) {
        Object nick = row.get("nick_name");
        if (nick != null && wanted.equals(String.valueOf(nick))) {
            return wanted;
        }
        Integer taken = jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM user_info WHERE nick_name = ? AND user_id <> ?",
                Integer.class, wanted, userId);
        if (taken != null && taken > 0) {
            return nick == null ? wanted : String.valueOf(nick);
        }
        return wanted;
    }
}
