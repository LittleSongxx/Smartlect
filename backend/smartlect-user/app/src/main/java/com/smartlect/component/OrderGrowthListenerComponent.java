package com.smartlect.component;

import com.smartlect.api.dto.OrderGrowthEventDTO;
import com.smartlect.biz.UserMemberProfileService;
import com.smartlect.constants.RabbitMQConfig;
import com.rabbitmq.client.Channel;
import jakarta.annotation.Resource;
import lombok.extern.slf4j.Slf4j;
import org.springframework.amqp.core.Message;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.stereotype.Component;

import java.io.IOException;

@Component
@Slf4j
public class OrderGrowthListenerComponent {

    @Resource
    private UserMemberProfileService userMemberProfileService;
    @Resource
    private MqListenerHelper mqListenerHelper;

    @RabbitListener(queues = RabbitMQConfig.USER_MEMBER_QUEUE, ackMode = "MANUAL")
    public void handle(OrderGrowthEventDTO event, Channel channel, Message message)
            throws IOException {
        long deliveryTag = message.getMessageProperties().getDeliveryTag();
        try {
            boolean applied = userMemberProfileService.applyOrderGrowth(event);
            mqListenerHelper.clearConsumeRetry(RabbitMQConfig.USER_MEMBER_QUEUE, message);
            channel.basicAck(deliveryTag, false);
            log.info("订单成长值事件已处理 orderId={}, applied={}",
                    event == null ? null : event.getOrderId(), applied);
        } catch (Exception error) {
            log.error("订单成长值事件处理失败 orderId={}",
                    event == null ? null : event.getOrderId(), error);
            // 不使用 Redis 的 tryBeginConsume 抢占锁：进程在抢占后、数据库提交前
            // 崩溃会让重投消息被误判为重复。user_order_growth 唯一键才是最终幂等屏障。
            mqListenerHelper.nackWithRetryOrDlq(
                    channel,
                    deliveryTag,
                    message,
                    RabbitMQConfig.USER_MEMBER_QUEUE,
                    event,
                    error);
        }
    }
}
