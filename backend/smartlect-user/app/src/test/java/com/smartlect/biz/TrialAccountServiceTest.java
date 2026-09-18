package com.smartlect.biz;

import com.smartlect.constants.TrialIdentities;
import com.smartlect.entity.config.AppConfig;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;

import java.util.List;
import java.util.Map;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class TrialAccountServiceTest {

    @Test
    void seedsShopperAddressAndProfileWhenTrialIsEnabled() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        AppConfig config = mock(AppConfig.class);
        when(config.isTrialEnabled()).thenReturn(true);
        when(config.getTrialPasswordHash()).thenReturn("$2a$10$demo");
        when(jdbc.queryForList(anyString(), eq(TrialIdentities.USER_EMAIL), eq(TrialIdentities.USER_ID)))
                .thenReturn(List.of());
        when(jdbc.queryForList(anyString(), eq(TrialIdentities.SHOPPER_EMAIL), eq(TrialIdentities.SHOPPER_USER_ID)))
                .thenReturn(List.of());

        TrialAccountService service = new TrialAccountService(jdbc, config);
        service.migratePublishedDemoAccounts();

        verify(jdbc).update(contains("INSERT INTO user_address"),
                eq(TrialIdentities.SHOPPER_DEFAULT_ADDRESS_ID),
                eq(TrialIdentities.SHOPPER_USER_ID),
                eq("北京市海淀区中关村大街1号 智选演示收货处"),
                eq(TrialIdentities.SHOPPER_NICK),
                eq(TrialIdentities.SHOPPER_PHONE),
                eq(1));
        verify(jdbc).update(contains("INSERT INTO user_address"),
                eq(TrialIdentities.SHOPPER_BACKUP_ADDRESS_ID),
                eq(TrialIdentities.SHOPPER_USER_ID),
                eq("上海市浦东新区世纪大道88号 备用收货处"),
                eq(TrialIdentities.SHOPPER_NICK),
                eq(TrialIdentities.SHOPPER_PHONE),
                eq(0));
        verify(jdbc).update(contains("user_browse_history"),
                eq(TrialIdentities.SHOPPER_USER_ID),
                eq("917186661226040"),
                eq(3));
        verify(jdbc).update(contains("user_member_profile"), eq(TrialIdentities.SHOPPER_USER_ID));
    }

    @Test
    void doesNotSeedWhenTrialIsDisabled() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        AppConfig config = mock(AppConfig.class);
        when(config.isTrialEnabled()).thenReturn(false);
        new TrialAccountService(jdbc, config).migratePublishedDemoAccounts();
        verify(jdbc, never()).update(anyString(), any(), any(), any(), any(), any(), any());
    }

    @Test
    void existingShopperStillReceivesAddressRepair() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        AppConfig config = mock(AppConfig.class);
        when(config.isTrialEnabled()).thenReturn(true);
        when(config.getTrialPasswordHash()).thenReturn("$2a$10$demo");
        when(jdbc.queryForList(anyString(), eq(TrialIdentities.USER_EMAIL), eq(TrialIdentities.USER_ID)))
                .thenReturn(List.of());
        when(jdbc.queryForList(anyString(), eq(TrialIdentities.SHOPPER_EMAIL), eq(TrialIdentities.SHOPPER_USER_ID)))
                .thenReturn(List.of(Map.of(
                        "user_id", TrialIdentities.SHOPPER_USER_ID,
                        "email", TrialIdentities.SHOPPER_EMAIL,
                        "nick_name", TrialIdentities.SHOPPER_NICK)));

        new TrialAccountService(jdbc, config).migratePublishedDemoAccounts();

        verify(jdbc).update(contains("INSERT INTO user_address"),
                eq(TrialIdentities.SHOPPER_DEFAULT_ADDRESS_ID),
                eq(TrialIdentities.SHOPPER_USER_ID),
                eq("北京市海淀区中关村大街1号 智选演示收货处"),
                eq(TrialIdentities.SHOPPER_NICK),
                eq(TrialIdentities.SHOPPER_PHONE),
                eq(1));
    }
}
