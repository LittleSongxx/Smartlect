package com.smartlect.biz;

import com.smartlect.api.dto.SignRecordMessageDTO;
import com.smartlect.entity.po.UserSignRecord;
import com.smartlect.entity.po.UserSignRecordDetail;
import com.smartlect.entity.query.UserSignRecordDetailQuery;
import com.smartlect.entity.query.UserSignRecordQuery;
import com.smartlect.mappers.SignBitmapMapper;
import com.smartlect.mappers.UserSignRecordDetailMapper;
import com.smartlect.mappers.UserSignRecordMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class SignEventPersistenceServiceTest {

    @Mock
    private UserSignRecordMapper<UserSignRecord, UserSignRecordQuery> userSignRecordMapper;
    @Mock
    private UserSignRecordDetailMapper<UserSignRecordDetail, UserSignRecordDetailQuery>
            userSignRecordDetailMapper;
    @Mock
    private SignBitmapMapper signBitmapMapper;
    @Mock
    private UserMemberProfileService userMemberProfileService;
    @InjectMocks
    private SignEventPersistenceService service;

    @Test
    void newlyInsertedSignDetailGrantsGrowthExactlyOnce() {
        when(signBitmapMapper.insertBitIfAbsent(eq("u1"), eq("202608"), anyInt())).thenReturn(1);
        when(userSignRecordDetailMapper.insertIgnore(any())).thenReturn(1);

        assertTrue(service.persist(message(), 5));

        verify(userSignRecordMapper).insertOrUpdate(any(UserSignRecord.class));
        verify(userMemberProfileService).addGrowth("u1", 5);
    }

    @Test
    void duplicateSignDetailDoesNotGrantGrowthAgain() {
        when(signBitmapMapper.insertBitIfAbsent(anyString(), anyString(), anyInt())).thenReturn(0);
        when(signBitmapMapper.setBitIfMissing(anyString(), anyString(), anyInt())).thenReturn(1);
        when(userSignRecordDetailMapper.insertIgnore(any())).thenReturn(0);

        assertFalse(service.persist(message(), 5));

        verify(userSignRecordMapper, never()).insertOrUpdate(any(UserSignRecord.class));
        verify(userMemberProfileService, never()).addGrowth(any(), any(Integer.class));
    }

    @Test
    void duplicateBitmapClaimIsTheFinalIdempotencyWall() {
        // 首插撞已有行（=0）且位已置（setBitIfMissing=0）：Redis 判断失效时数据库仍然拦得住
        when(signBitmapMapper.insertBitIfAbsent(anyString(), anyString(), anyInt())).thenReturn(0);
        when(signBitmapMapper.setBitIfMissing(anyString(), anyString(), anyInt())).thenReturn(0);

        assertFalse(service.persist(message(), 5));

        verify(userSignRecordDetailMapper, never()).insertIgnore(any());
        verify(userMemberProfileService, never()).addGrowth(any(), any(Integer.class));
    }

    @Test
    void bitMaskCoversDayFifteenOfTheMonth() {
        when(signBitmapMapper.insertBitIfAbsent("u1", "202608", 1 << 14)).thenReturn(1);
        when(userSignRecordDetailMapper.insertIgnore(any())).thenReturn(1);

        assertTrue(service.persist(message(), 5));

        verify(signBitmapMapper).insertBitIfAbsent("u1", "202608", 1 << 14);
    }

    private static SignRecordMessageDTO message() {
        return new SignRecordMessageDTO("u1", 3, 10, 0, "20260815", 0);
    }
}
