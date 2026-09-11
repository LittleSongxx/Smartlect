package com.smartlect.component;

import com.smartlect.api.support.CouponFeignSupport;
import com.smartlect.constants.RabbitMQConfig;
import com.smartlect.api.dto.RushingCouponMessageDTO;
import com.smartlect.entity.po.OrderInfo;
import com.smartlect.entity.query.OrderInfoQuery;
import com.smartlect.mappers.OrderInfoMapper;
import com.rabbitmq.client.Channel;
import jakarta.annotation.Resource;
import lombok.extern.slf4j.Slf4j;
import org.springframework.amqp.core.Message;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.stereotype.Component;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.io.IOException;

@Component
@Slf4j
public class RabbitMQOrderListenerComponent {

    @Resource
    private OrderInfoMapper<OrderInfo, OrderInfoQuery> orderInfoMapper;
    @Resource
    private CouponFeignSupport couponFeignSupport;
    @Resource
    private MqListenerHelper mqListenerHelper;

    @RabbitListener(queues = RabbitMQConfig.RUSHING_ORDER_QUEUE, ackMode = "MANUAL")
    public void handleOrder(RushingCouponMessageDTO message, Channel channel, Message mqMessage) {
        Long deliveryTag = mqMessage.getMessageProperties().getDeliveryTag();
        if (!mqListenerHelper.tryBeginConsume(
                mqMessage, MqListenerHelper.CONSUME_IDEMPOTENCY_TTL_STANDARD_SECONDS)) {
            try {
                mqListenerHelper.ackCompletedOrDeferBusy(
                        channel, deliveryTag, mqMessage, RabbitMQConfig.RUSHING_ORDER_QUEUE);
            } catch (IOException e) {
                log.error("drain leftover rush queue duplicate settle failed", e);
            }
            return;
        }
        String userCouponId = message == null ? null : message.getUserCouponId();
        try {
            if (message == null || message.getOrderId() == null || userCouponId == null) {
                throw new IllegalArgumentException("leftover rush queue message incomplete");
            }
            if (orderInfoMapper.selectByOrderId(message.getOrderId()) != null
                    || couponFeignSupport.getUserCoupon(userCouponId) != null) {
                mqListenerHelper.clearConsumeRetry(RabbitMQConfig.RUSHING_ORDER_QUEUE, mqMessage);
                channel.basicAck(deliveryTag, false);
                return;
            }
            log.warn("drain leftover rush queue, skip order create userCouponId={}", userCouponId);
            mqListenerHelper.clearConsumeRetry(RabbitMQConfig.RUSHING_ORDER_QUEUE, mqMessage);
            channel.basicAck(deliveryTag, false);
        } catch (Exception e) {
            log.error("drain leftover rush queue failed: {}", userCouponId, e);
            try {
                if (!TransactionSynchronizationManager.isSynchronizationActive()) {
                    mqListenerHelper.nackWithRetryOrDlq(
                            channel,
                            deliveryTag,
                            mqMessage,
                            RabbitMQConfig.RUSHING_ORDER_QUEUE,
                            message,
                            e);
                }
            } catch (IOException ex) {
                log.error("兜底NACK失败", ex);
            }
        }
    }
}
