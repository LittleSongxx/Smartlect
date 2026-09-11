package com.smartlect.component;

import com.smartlect.api.dto.NotificationMessageDTO;
import com.smartlect.constants.RabbitMQConfig;
import com.smartlect.constants.TransactionalMqSender;
import com.smartlect.entity.enums.MessageReliabilityLevelEnum;
import com.smartlect.support.MqIdempotencyKeys;
import com.smartlect.utils.StringTools;
import jakarta.annotation.Resource;
import org.springframework.stereotype.Component;

@Component
public class OrderNotificationPublisher {

    @Resource
    private TransactionalMqSender transactionalMqSender;

    public void send(String userId, String title, String content, String bizType, String bizId) {
        if (StringTools.isEmpty(userId) || StringTools.isEmpty(title)) {
            return;
        }
        transactionalMqSender.sendAfterCommit(
                RabbitMQConfig.NOTIFY_EXCHANGE,
                RabbitMQConfig.NOTIFY_KEY,
                new NotificationMessageDTO(userId, title, content, bizType, bizId),
                MqIdempotencyKeys.notification(userId, bizType, bizId),
                MessageReliabilityLevelEnum.HIGH);
    }
}
