package com.smartlect.biz.impl;

import com.smartlect.api.dto.SignRecordMessageDTO;
import com.smartlect.biz.SignCalendarCacheService;
import com.smartlect.biz.SignEventPersistenceService;
import com.smartlect.biz.SignRecordSyncService;
import com.smartlect.biz.SignRewardConfigService;
import com.smartlect.biz.UserNotificationService;
import com.smartlect.api.support.CouponFeignSupport;
import com.smartlect.component.RedisComponent;
import com.smartlect.component.SignRedisComponent;
import com.smartlect.exception.BusinessException;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class SignServiceImplTest {

    @Mock
    private RedisComponent redisComponent;
    @Mock
    private SignRedisComponent signRedisComponent;
    @Mock
    private UserNotificationService userNotificationService;
    @Mock
    private SignRewardConfigService signRewardConfigService;
    @Mock
    private CouponFeignSupport couponFeignSupport;
    @Mock
    private SignRecordSyncService signRecordSyncService;
    @Mock
    private SignCalendarCacheService signCalendarCacheService;
    @Mock
    private SignEventPersistenceService signEventPersistenceService;
    @InjectMocks
    private SignServiceImpl service;

    @Test
    void retryRepairsDatabaseWhenRedisWasAlreadySigned() {
        when(signRedisComponent.isSign(eq("u1"), any(), any(Integer.class))).thenReturn(true);
        when(signRedisComponent.getContinuousDays("u1")).thenReturn(2);
        when(signRedisComponent.totalSignDays("u1")).thenReturn(7);
        when(signRedisComponent.getUsedCount("u1")).thenReturn(0);
        when(signEventPersistenceService.persist(any(), eq(5))).thenReturn(true);

        service.sign("u1");

        verify(signRedisComponent, never()).sign("u1");
        ArgumentCaptor<SignRecordMessageDTO> event =
                ArgumentCaptor.forClass(SignRecordMessageDTO.class);
        verify(signEventPersistenceService).persist(event.capture(), eq(5));
        org.junit.jupiter.api.Assertions.assertEquals("u1", event.getValue().getUserId());
    }

    @Test
    void completedDuplicateStillReturnsAlreadySigned() {
        when(signRedisComponent.isSign(eq("u1"), any(), any(Integer.class))).thenReturn(true);
        when(signRedisComponent.getContinuousDays("u1")).thenReturn(2);
        when(signRedisComponent.totalSignDays("u1")).thenReturn(7);
        when(signRedisComponent.getUsedCount("u1")).thenReturn(0);
        when(signEventPersistenceService.persist(any(), eq(5))).thenReturn(false);

        assertThrows(BusinessException.class, () -> service.sign("u1"));
    }

    @Test
    void supplementRejectsTodayAndFutureDates() {
        assertThrows(BusinessException.class, () -> service.msign("u1", "29990101"));
        verify(signRedisComponent, never()).supplementSign(any(), any(), any(Integer.class));
    }
}
