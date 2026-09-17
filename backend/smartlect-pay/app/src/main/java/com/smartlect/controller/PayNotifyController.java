package com.smartlect.controller;

import com.smartlect.api.support.OrderFeignSupport;
import com.smartlect.component.SpringContext;
import com.smartlect.api.dto.PayOrderNotifyDTO;
import com.smartlect.api.enums.PayChannelEnum;
import com.smartlect.biz.AlipayNotifyValidationService;
import com.smartlect.exception.BusinessException;
import com.smartlect.biz.PayChannel;
import jakarta.annotation.Resource;
import jakarta.servlet.http.HttpServletRequest;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.HashMap;
import java.util.Map;

@Slf4j
@RestController
@RequestMapping("/notify")
public class PayNotifyController {

    @Resource
    private OrderFeignSupport orderFeignSupport;
    @Resource
    private AlipayNotifyValidationService notifyValidationService;
    @Resource
    private com.smartlect.biz.PayTradeRecordService payTradeRecordService;

    @PostMapping("/alipayNotify")
    public String alipayNotify(HttpServletRequest request) {
        Map<String, String> params = new HashMap<>();
        request.getParameterMap().forEach((k, v) -> {
            if (v != null && v.length > 0) {
                params.put(k, v[0]);
            }
        });
        PayChannel payChannel = (PayChannel) SpringContext.getBean(PayChannelEnum.ALIPAY_PC.getBeanName());
        PayOrderNotifyDTO notifyDTO;
        try {
            notifyDTO = payChannel.payNotify(params, null);
            if (notifyDTO != null) {
                notifyValidationService.validate(params);
            }
        } catch (Exception e) {
            log.warn("支付宝回调校验失败: {}", e.getMessage());
            return "failure";
        }
        if (notifyDTO == null || notifyDTO.getPayOrderId() == null) {
            return "failure";
        }
        String payOrderId = notifyDTO.getPayOrderId();
        try {
            payTradeRecordService.markSuccess(payOrderId, notifyDTO.getChannelOrderId());
            orderFeignSupport.paySuccess(notifyDTO);
        } catch (BusinessException e) {
            log.warn("支付宝回调业务处理失败 payOrderId={}, msg={}", payOrderId, e.getMessage());
            return "failure";
        } catch (Exception e) {
            log.error("支付宝回调处理异常 payOrderId={}", payOrderId, e);
            return "failure";
        }
        return "success";
    }
}
