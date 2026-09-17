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

    private final JdbcTemplate jdbcTemplate;
    private final AppConfig appConfig;

    public TrialAccountService(JdbcTemplate jdbcTemplate, AppConfig appConfig) {
        this.jdbcTemplate = jdbcTemplate;
        this.appConfig = appConfig;
    }

    @PostConstruct
    public void migrateTrialVisitor() {
        if (!appConfig.isTrialEnabled() || StringTools.isEmpty(appConfig.getTrialPasswordHash())) {
            return;
        }
        List<Map<String, Object>> existing = jdbcTemplate.queryForList(
                "SELECT user_id, email, nick_name FROM user_info WHERE email = ? OR user_id = ?",
                TrialIdentities.USER_EMAIL, TrialIdentities.USER_ID);
        if (!existing.isEmpty()) {
            jdbcTemplate.update(
                    """
                    UPDATE user_info
                    SET password = ?, status = ?, nick_name = ?
                    WHERE email = ? OR user_id = ?
                    """,
                    appConfig.getTrialPasswordHash(),
                    UserStatusEnum.ENABLE.getStatus(),
                    uniqueNick(existing.get(0)),
                    TrialIdentities.USER_EMAIL,
                    TrialIdentities.USER_ID);
            return;
        }
        try {
            jdbcTemplate.update(
                    """
                    INSERT INTO user_info
                        (user_id, nick_name, email, password, sex, join_time, status)
                    VALUES (?, ?, ?, ?, ?, NOW(), ?)
                    """,
                    TrialIdentities.USER_ID,
                    TrialIdentities.USER_NICK,
                    TrialIdentities.USER_EMAIL,
                    appConfig.getTrialPasswordHash(),
                    UserSexEnum.SECRECY.getType(),
                    UserStatusEnum.ENABLE.getStatus());
        } catch (DuplicateKeyException ignored) {
            jdbcTemplate.update(
                    """
                    UPDATE user_info
                    SET password = ?, status = ?
                    WHERE email = ? OR user_id = ?
                    """,
                    appConfig.getTrialPasswordHash(),
                    UserStatusEnum.ENABLE.getStatus(),
                    TrialIdentities.USER_EMAIL,
                    TrialIdentities.USER_ID);
        }
    }

    private String uniqueNick(Map<String, Object> row) {
        Object nick = row.get("nick_name");
        if (nick != null && TrialIdentities.USER_NICK.equals(String.valueOf(nick))) {
            return TrialIdentities.USER_NICK;
        }
        Integer taken = jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM user_info WHERE nick_name = ? AND user_id <> ?",
                Integer.class, TrialIdentities.USER_NICK, String.valueOf(row.get("user_id")));
        if (taken != null && taken > 0) {
            return nick == null ? TrialIdentities.USER_NICK : String.valueOf(nick);
        }
        return TrialIdentities.USER_NICK;
    }
}
