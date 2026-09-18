package com.smartlect.biz;

import com.smartlect.constants.TrialIdentities;
import com.smartlect.entity.config.AppConfig;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class TrialCouponSeedServiceTest {

    @Test
    void grantsDedicatedAndPlazaCouponsToThePublishedShopper() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        AppConfig config = mock(AppConfig.class);
        when(config.isTrialEnabled()).thenReturn(true);
        when(config.getTrialPasswordHash()).thenReturn("$2a$10$demo");

        new TrialCouponSeedService(jdbc, config).seedPublishedShopperCoupons();

        verify(jdbc).update(contains("INSERT INTO discount_coupon"),
                eq(TrialIdentities.DEMO_COUPON_ID), eq(TrialIdentities.DEMO_COUPON_NAME));
        verify(jdbc).update(contains("INSERT IGNORE INTO user_coupon"),
                eq(TrialIdentities.DEMO_USER_COUPON_ID),
                eq(TrialIdentities.SHOPPER_USER_ID),
                eq(TrialIdentities.DEMO_COUPON_ID));
        verify(jdbc).update(contains("coupon_name = ?"),
                eq(TrialIdentities.PLAZA_USER_COUPON_ID),
                eq(TrialIdentities.SHOPPER_USER_ID),
                eq(TrialIdentities.PLAZA_COUPON_NAME));
    }

    @Test
    void skipsWhenTrialIsDisabled() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        AppConfig config = mock(AppConfig.class);
        when(config.isTrialEnabled()).thenReturn(false);
        new TrialCouponSeedService(jdbc, config).seedPublishedShopperCoupons();
        verify(jdbc, never()).update(anyString(), any(), any());
    }
}
