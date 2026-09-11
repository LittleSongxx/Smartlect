package com.smartlect.api;

import com.smartlect.api.dto.PayCloseDTO;
import com.smartlect.api.dto.PayQueryDTO;
import com.smartlect.api.dto.PayRefundDTO;
import com.smartlect.api.dto.PayTradeCreateDTO;
import com.smartlect.api.dto.PayTradeStatusDTO;
import com.smartlect.api.dto.PayUrlRequestDTO;
import com.smartlect.api.fallback.PayFeignFallbackFactory;
import com.smartlect.api.dto.PayInfoDTO;
import com.smartlect.api.dto.PayOrderNotifyDTO;
import com.smartlect.entity.vo.ResponseVO;
import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;

@FeignClient(name = "smartlect-pay", contextId = "payFeignClient", path = "/internal/pay",
        fallbackFactory = PayFeignFallbackFactory.class)
public interface PayFeignClient {

    @PostMapping("/trade/status")
    ResponseVO<java.util.Map<String, Object>> tradeStatus(@RequestBody PayTradeStatusDTO dto,
            @org.springframework.web.bind.annotation.RequestHeader("X-Smartlect-User-Id") String userId);

    @PostMapping("/trade/createPending")
    ResponseVO<Void> createPending(@RequestBody PayTradeCreateDTO dto);

    @PostMapping("/trade/markSuccess")
    ResponseVO<Void> markSuccess(@RequestBody PayTradeStatusDTO dto);

    @PostMapping("/trade/markClosed")
    ResponseVO<Void> markClosed(@RequestBody PayTradeStatusDTO dto);

    @PostMapping("/trade/markRefunded")
    ResponseVO<Void> markRefunded(@RequestBody PayTradeStatusDTO dto);

    @PostMapping("/channel/getPayUrl")
    ResponseVO<PayInfoDTO> getPayUrl(@RequestBody PayUrlRequestDTO dto);

    @PostMapping("/channel/refund")
    ResponseVO<Void> refund(@RequestBody PayRefundDTO dto);

    @PostMapping("/channel/closeOrder")
    ResponseVO<Void> closeOrder(@RequestBody PayCloseDTO dto);

    @PostMapping("/channel/queryOrder")
    ResponseVO<PayOrderNotifyDTO> queryOrder(@RequestBody PayQueryDTO dto);
}
