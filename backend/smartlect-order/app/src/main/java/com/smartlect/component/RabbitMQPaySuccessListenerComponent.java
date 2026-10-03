package com.smartlect.component;

import com.smartlect.api.dto.PayOrderNotifyDTO;
import com.smartlect.biz.OrderInternalService;
import com.smartlect.constants.RabbitMQConfig;
import com.smartlect.utils.StringTools;
import com.rabbitmq.client.Channel;
import lombok.extern.slf4j.Slf4j;
import org.springframework.amqp.core.Message;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.stereotype.Component;

import java.io.IOException;

/**
 * 消费 pay 服务发来的支付成功事件（Outbox → smartlect.pay.success.queue）。
 *
 * <p>取代 pay→order 的同步 Feign 回调。paySuccess 的推进本身是条件更新
 * （仅待付款订单可迁移），事件重投或 outbox 重放天然幂等，再叠加消费租约
 * 去重与延迟重试拓扑。</p>
 */
@Slf4j
@Component
public class RabbitMQPaySuccessListenerComponent {

    private final OrderInternalService orderInternalService;
    private final MqListenerHelper mqListenerHelper;

    public RabbitMQPaySuccessListenerComponent(OrderInternalService orderInternalService,
                                               MqListenerHelper mqListenerHelper) {
        this.orderInternalService = orderInternalService;
        this.mqListenerHelper = mqListenerHelper;
    }

    @RabbitListener(queues = RabbitMQConfig.PAY_SUCCESS_QUEUE, ackMode = "MANUAL")
    public void handlePaySuccess(PayOrderNotifyDTO message, Channel channel, Message mqMessage) throws IOException {
        Long deliveryTag = mqMessage.getMessageProperties().getDeliveryTag();
        if (message == null || StringTools.isEmpty(message.getPayOrderId())) {
            log.error("支付成功事件缺少支付单号");
            channel.basicAck(deliveryTag, false);
            return;
        }
        if (!mqListenerHelper.tryBeginConsume(mqMessage, MqListenerHelper.CONSUME_IDEMPOTENCY_TTL_HIGH_SECONDS)) {
            mqListenerHelper.ackCompletedOrDeferBusy(channel, deliveryTag, mqMessage, RabbitMQConfig.PAY_SUCCESS_QUEUE);
            return;
        }
        log.info("支付成功事件收到 payOrderId={}", message.getPayOrderId());
        try {
            orderInternalService.paySuccess(message);
            mqListenerHelper.clearConsumeRetry(RabbitMQConfig.PAY_SUCCESS_QUEUE, mqMessage);
            channel.basicAck(deliveryTag, false);
        } catch (Exception e) {
            log.error("支付成功事件处理失败 payOrderId={}", message.getPayOrderId(), e);
            mqListenerHelper.nackWithRetryOrDlq(channel, deliveryTag, mqMessage,
                    RabbitMQConfig.PAY_SUCCESS_QUEUE, message, e);
        }
    }
}
