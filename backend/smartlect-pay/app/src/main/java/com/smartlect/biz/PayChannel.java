package com.smartlect.biz;

import com.smartlect.api.dto.PayInfoDTO;
import com.smartlect.api.dto.PayOrderNotifyDTO;
import com.smartlect.api.enums.PayChannelEnum;

import java.math.BigDecimal;
import java.util.Map;

public interface PayChannel {

    PayInfoDTO getPayUrl(PayChannelEnum payChannelEnum, String payOrderId, String subject, BigDecimal amount);

    PayOrderNotifyDTO payNotify(Map<String, String> requestParams, String jsonBody);

    PayOrderNotifyDTO queryOrder(String payOrderId);

    void refund(String sourcePayOrderId, String payOrderId, BigDecimal refundAmount);

    void closeOrder(String payOrderId);
}
