package com.smartlect.task;

import com.smartlect.api.support.PayFeignSupport;
import com.smartlect.component.PayOrderRedisComponent;
import com.smartlect.component.RedisComponent;
import com.smartlect.constants.Constants;
import com.smartlect.entity.config.AppConfig;
import com.smartlect.api.dto.PayOrderNotifyDTO;
import com.smartlect.api.enums.OrderStatusEnum;
import com.smartlect.api.enums.PayChannelEnum;
import com.smartlect.entity.po.OrderInfo;
import com.smartlect.entity.query.OrderInfoQuery;
import com.smartlect.biz.OrderInfoService;
import com.smartlect.utils.StringTools;
import jakarta.annotation.Resource;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.concurrent.TimeUnit;

@Component
@Slf4j
public class PayOrderTask {

    @Resource
    private AppConfig appConfig;

    @Resource
    private OrderInfoService orderInfoService;

    @Resource
    private PayFeignSupport payFeignSupport;

    @Resource
    private PayOrderRedisComponent payOrderRedisComponent;

    @Resource
    private RedisComponent redisComponent;

    @Value("${spring.application.name:unknown}")
    private String applicationName;

    @Scheduled(fixedDelay = 5000)
    public void pollPayOrders() {
        if (!appConfig.getAutoCheckpay()) {
            return;
        }
        // 轮询要打支付渠道查询接口：多副本各自轮一遍等于外部调用量翻 N 倍。
        // 用一把 key 带 applicationName 的短锁（TTL 略短于 5s 间隔）把轮询收敛到单副本；
        // 落库路径本身有单号粒度的 Redisson 锁 + 条件更新，漏掉一轮轮询不影响正确性。
        String lockKey = Constants.REDIS_KEY_ORDER_PAY_POLL_LOCK + applicationName;
        if (!redisComponent.setIfAbsent(lockKey, "1", 4, TimeUnit.SECONDS)) {
            return;
        }
        try {
            OrderInfoQuery query = new OrderInfoQuery();
            query.setOrderStatus(OrderStatusEnum.WAIT_PAYMENT.getStatus());
            List<OrderInfo> orderInfoList = orderInfoService.findListByParam(query);
            for (OrderInfo orderInfo : orderInfoList) {
                String payOrderId = orderInfo.getPayOrderId();
                if (StringTools.isEmpty(payOrderId)) {
                    continue;
                }
                if (!payOrderRedisComponent.isPayTradeInitiated(payOrderId)) {
                    continue;
                }
                PayChannelEnum payChannelEnum = PayChannelEnum.resolve(orderInfo.getPayChannel());
                if (payChannelEnum == null) {
                    continue;
                }
                PayOrderNotifyDTO payOrderNotifyDTO = payFeignSupport.queryOrder(payOrderId, payChannelEnum.getPayScene());
                if (payOrderNotifyDTO == null) {
                    continue;
                }
                orderInfoService.paySuccess(payOrderNotifyDTO);
            }
        } catch (Exception e) {
            log.error("查询支付信息异常", e);
        }
    }
}
