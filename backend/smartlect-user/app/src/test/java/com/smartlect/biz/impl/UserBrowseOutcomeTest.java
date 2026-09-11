package com.smartlect.biz.impl;

import com.smartlect.entity.po.UserBrowseHistory;
import com.smartlect.entity.query.UserBrowseHistoryQuery;
import com.smartlect.exception.BusinessException;
import com.smartlect.integration.CommerceOutcomeClient;
import com.smartlect.mappers.UserBrowseHistoryMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.time.Instant;
import java.util.Date;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class UserBrowseOutcomeTest {
    @Mock private UserBrowseHistoryMapper<UserBrowseHistory, UserBrowseHistoryQuery> userBrowseHistoryMapper;
    @Mock private CommerceOutcomeClient commerceOutcomeClient;
    @InjectMocks private UserBrowseHistoryServiceImpl service;

    @Test
    void timestampAndIdempotencySurviveRedeliveryAndOutboxFollowsHistoryWrite() {
        long occurred = 1_700_000_000_123L;
        service.recordBrowse("user-1", "product-1", occurred);
        service.recordBrowse("user-1", "product-1", occurred);
        ArgumentCaptor<CommerceOutcomeClient.OutcomeEvent> events = ArgumentCaptor.forClass(CommerceOutcomeClient.OutcomeEvent.class);
        var ordered = inOrder(userBrowseHistoryMapper, commerceOutcomeClient);
        for (int i = 0; i < 2; i++) {
            ordered.verify(userBrowseHistoryMapper).recordLatest("user-1", "product-1", new Date(occurred));
            ordered.verify(commerceOutcomeClient).recordV2AfterCommit(events.capture());
        }
        assertEquals(events.getAllValues().get(0), events.getAllValues().get(1));
        var event = events.getValue();
        assertEquals("VIEW", event.eventType());
        assertEquals(Instant.ofEpochMilli(occurred).toString(), event.occurredAt());
        assertEquals("store", event.payload().get("executionScopeId"));
        assertNull(event.orderId());
        assertFalse(event.payload().containsKey("paidAmount"));
    }

    @Test
    void legacyWithoutTimeDoesNotInventViewAndFutureTimestampIsRejected() {
        service.recordBrowse("user-1", "product-1");
        verify(userBrowseHistoryMapper).recordLatest(eq("user-1"), eq("product-1"), any(Date.class));
        verifyNoInteractions(commerceOutcomeClient);
        assertThrows(BusinessException.class, () -> service.recordBrowse("user-1", "product-1", -1L));
        assertThrows(BusinessException.class, () -> service.recordBrowse("user-1", "product-1", System.currentTimeMillis() + 120_000));
        verifyNoMoreInteractions(userBrowseHistoryMapper);
    }
}
