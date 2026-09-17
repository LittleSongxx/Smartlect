package com.smartlect.api.fallback;

import com.smartlect.api.PayFeignClient;
import com.smartlect.api.dto.PayCloseDTO;
import com.smartlect.api.dto.PayQueryDTO;
import com.smartlect.api.dto.PayRefundDTO;
import com.smartlect.api.dto.PayTradeCreateDTO;
import com.smartlect.api.dto.PayTradeStatusDTO;
import com.smartlect.api.dto.PayUrlRequestDTO;
import com.smartlect.api.support.FeignFallbackResponses;
import com.smartlect.api.dto.PayInfoDTO;
import com.smartlect.api.dto.PayOrderNotifyDTO;
import com.smartlect.entity.vo.ResponseVO;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.cloud.openfeign.FallbackFactory;
import org.springframework.stereotype.Component;

@Component
public class PayFeignFallbackFactory implements FallbackFactory<PayFeignClient> {
    private static final Logger log = LoggerFactory.getLogger(PayFeignFallbackFactory.class);

    @Override
    public PayFeignClient create(Throwable cause) {
        return new PayFeignClient() {
            @Override
            public ResponseVO<java.util.Map<String, Object>> tradeStatus(PayTradeStatusDTO dto, String userId) {
                return FeignFallbackResponses.unavailable(log, "支付服务", cause);
            }

            @Override
            public ResponseVO<Void> assertSettled(PayTradeStatusDTO dto) {
                return FeignFallbackResponses.unavailable(log, "支付服务", cause);
            }

            @Override
            public ResponseVO<Void> createPending(PayTradeCreateDTO dto) {
                return FeignFallbackResponses.unavailable(log, "支付服务", cause);
            }

            @Override
            public ResponseVO<Void> markSuccess(PayTradeStatusDTO dto) {
                return FeignFallbackResponses.unavailable(log, "支付服务", cause);
            }

            @Override
            public ResponseVO<Void> markClosed(PayTradeStatusDTO dto) {
                return FeignFallbackResponses.unavailable(log, "支付服务", cause);
            }

            @Override
            public ResponseVO<Void> markRefunded(PayTradeStatusDTO dto) {
                return FeignFallbackResponses.unavailable(log, "支付服务", cause);
            }

            @Override
            public ResponseVO<PayInfoDTO> getPayUrl(PayUrlRequestDTO dto) {
                return FeignFallbackResponses.unavailable(log, "支付服务", cause);
            }

            @Override
            public ResponseVO<Void> refund(PayRefundDTO dto) {
                return FeignFallbackResponses.unavailable(log, "支付服务", cause);
            }

            @Override
            public ResponseVO<Void> closeOrder(PayCloseDTO dto) {
                return FeignFallbackResponses.unavailable(log, "支付服务", cause);
            }

            @Override
            public ResponseVO<PayOrderNotifyDTO> queryOrder(PayQueryDTO dto) {
                return FeignFallbackResponses.unavailable(log, "支付服务", cause);
            }
        };
    }
}
