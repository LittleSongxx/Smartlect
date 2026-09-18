package com.smartlect.biz;

import com.smartlect.constants.TrialIdentities;
import com.smartlect.entity.config.AppConfig;
import com.smartlect.utils.StringTools;
import jakarta.annotation.PostConstruct;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

@Service
public class TrialCouponSeedService {

    private final JdbcTemplate jdbcTemplate;
    private final AppConfig appConfig;

    public TrialCouponSeedService(JdbcTemplate jdbcTemplate, AppConfig appConfig) {
        this.jdbcTemplate = jdbcTemplate;
        this.appConfig = appConfig;
    }

    @PostConstruct
    public void seedPublishedShopperCoupons() {
        if (!appConfig.isTrialEnabled() || StringTools.isEmpty(appConfig.getTrialPasswordHash())) {
            return;
        }
        jdbcTemplate.update(
                """
                INSERT INTO discount_coupon
                    (coupon_id, coupon_name, coupon_type, threshold_amount, discount_amount, discount_rate,
                     total_count, remain_count, valid_start_time, valid_end_time, status, rushingStatus,
                     create_time, update_time)
                VALUES (?, ?, 3, 0.00, 5.00, NULL, 0, 0,
                        DATE_SUB(NOW(), INTERVAL 1 DAY), DATE_ADD(NOW(), INTERVAL 365 DAY),
                        1, 0, NOW(), NOW()) AS incoming
                ON DUPLICATE KEY UPDATE
                    coupon_name = incoming.coupon_name,
                    coupon_type = incoming.coupon_type,
                    threshold_amount = incoming.threshold_amount,
                    discount_amount = incoming.discount_amount,
                    status = 1,
                    valid_start_time = incoming.valid_start_time,
                    valid_end_time = incoming.valid_end_time,
                    update_time = NOW()
                """,
                TrialIdentities.DEMO_COUPON_ID, TrialIdentities.DEMO_COUPON_NAME);
        grantIfUnused(TrialIdentities.DEMO_USER_COUPON_ID, TrialIdentities.DEMO_COUPON_ID);
        jdbcTemplate.update(
                """
                INSERT IGNORE INTO user_coupon (user_coupon_id, user_id, coupon_id, receive_time, status)
                SELECT ?, ?, coupon_id, NOW(), 0
                FROM discount_coupon
                WHERE coupon_name = ? AND status = 1
                ORDER BY coupon_id
                LIMIT 1
                """,
                TrialIdentities.PLAZA_USER_COUPON_ID,
                TrialIdentities.SHOPPER_USER_ID,
                TrialIdentities.PLAZA_COUPON_NAME);
    }

    private void grantIfUnused(String userCouponId, String couponId) {
        jdbcTemplate.update(
                """
                INSERT IGNORE INTO user_coupon (user_coupon_id, user_id, coupon_id, receive_time, status)
                VALUES (?, ?, ?, NOW(), 0)
                """,
                userCouponId, TrialIdentities.SHOPPER_USER_ID, couponId);
    }
}
