package com.smartlect.component;

import com.smartlect.api.dto.BrowseHistoryMessageDTO;
import com.smartlect.biz.UserBrowseHistoryService;
import com.smartlect.constants.RabbitMQConfig;
import com.rabbitmq.client.Channel;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.amqp.core.Message;
import org.springframework.amqp.core.MessageProperties;

import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class RabbitMQBrowseListenerComponentTest {
    @Mock private UserBrowseHistoryService userBrowseHistoryService;
    @Mock private MqListenerHelper mqListenerHelper;
    @Mock private Channel channel;
    @InjectMocks private RabbitMQBrowseListenerComponent listener;

    @Test
    void forwardsOriginalTimeAndAcknowledgesOnlyAfterHistoryAndOutboxTransaction() throws Exception {
        var payload = payload();
        var message = message();
        when(mqListenerHelper.tryBeginConsume(message, MqListenerHelper.CONSUME_IDEMPOTENCY_TTL_HIGH_SECONDS)).thenReturn(true);
        listener.handleBrowseRecord(payload, channel, message);
        var ordered = inOrder(userBrowseHistoryService, channel);
        ordered.verify(userBrowseHistoryService).recordBrowse("u1", "p1", payload.getBrowseTime());
        ordered.verify(channel).basicAck(19L, false);
    }

    @Test
    void failedTransactionRetriesWithoutAcknowledging() throws Exception {
        var payload = payload();
        var message = message();
        when(mqListenerHelper.tryBeginConsume(message, MqListenerHelper.CONSUME_IDEMPOTENCY_TTL_HIGH_SECONDS)).thenReturn(true);
        var failure = new IllegalStateException("synthetic transaction failure");
        doThrow(failure).when(userBrowseHistoryService).recordBrowse("u1", "p1", payload.getBrowseTime());
        listener.handleBrowseRecord(payload, channel, message);
        verify(channel, never()).basicAck(19L, false);
        verify(mqListenerHelper).nackWithRetryOrDlq(channel, 19L, message, RabbitMQConfig.BROWSE_RECORD_QUEUE, payload, failure);
    }

    private static BrowseHistoryMessageDTO payload() {
        var value = new BrowseHistoryMessageDTO();
        value.setUserId("u1"); value.setProductId("p1"); value.setBrowseTime(1_700_000_000_123L);
        return value;
    }

    private static Message message() {
        var properties = new MessageProperties(); properties.setDeliveryTag(19L);
        return new Message(new byte[0], properties);
    }
}
