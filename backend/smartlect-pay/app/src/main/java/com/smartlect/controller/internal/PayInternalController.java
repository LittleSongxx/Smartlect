package com.smartlect.controller.internal;

import com.smartlect.api.dto.PayCloseDTO;
import com.smartlect.api.dto.PayQueryDTO;
import com.smartlect.api.dto.PayRefundDTO;
import com.smartlect.api.dto.PayTradeCreateDTO;
import com.smartlect.api.dto.PayTradeStatusDTO;
import com.smartlect.api.dto.PayUrlRequestDTO;
import com.smartlect.biz.PayInternalService;
import com.smartlect.controller.ABaseController;
import com.smartlect.api.dto.PayInfoDTO;
import com.smartlect.api.dto.PayOrderNotifyDTO;
import com.smartlect.entity.vo.ResponseVO;
import jakarta.annotation.Resource;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/internal/pay")
public class PayInternalController extends ABaseController {

    @Resource
    private PayInternalService payInternalService;

    @PostMapping("/trade/status")
    public ResponseVO<java.util.Map<String, Object>> tradeStatus(@RequestBody PayTradeStatusDTO dto) {
        String userId = com.smartlect.security.DelegatedUserIdentity.require();
        if (dto == null || dto.getPayOrderId() == null || dto.getPayOrderId().isBlank()) {
            throw new com.smartlect.exception.HttpBusinessException(400, "payOrderId required");
        }
        return getSuccessResponseVO(payInternalService.tradeStatus(userId, dto.getPayOrderId()));
    }

    @PostMapping("/trade/createPending")
    public ResponseVO<Void> createPending(@RequestBody PayTradeCreateDTO dto) {
        payInternalService.createPending(dto);
        return getSuccessResponseVO(null);
    }

    @PostMapping("/trade/markSuccess")
    public ResponseVO<Void> markSuccess(@RequestBody PayTradeStatusDTO dto) {
        payInternalService.markSuccess(dto);
        return getSuccessResponseVO(null);
    }

    @PostMapping("/trade/markClosed")
    public ResponseVO<Void> markClosed(@RequestBody PayTradeStatusDTO dto) {
        payInternalService.markClosed(dto);
        return getSuccessResponseVO(null);
    }

    @PostMapping("/trade/markRefunded")
    public ResponseVO<Void> markRefunded(@RequestBody PayTradeStatusDTO dto) {
        payInternalService.markRefunded(dto);
        return getSuccessResponseVO(null);
    }

    @PostMapping("/channel/getPayUrl")
    public ResponseVO<PayInfoDTO> getPayUrl(@RequestBody PayUrlRequestDTO dto) {
        return getSuccessResponseVO(payInternalService.getPayUrl(dto));
    }

    @PostMapping("/channel/refund")
    public ResponseVO<Void> refund(@RequestBody PayRefundDTO dto) {
        payInternalService.refund(dto);
        return getSuccessResponseVO(null);
    }

    @PostMapping("/channel/closeOrder")
    public ResponseVO<Void> closeOrder(@RequestBody PayCloseDTO dto) {
        payInternalService.closeOrder(dto);
        return getSuccessResponseVO(null);
    }

    @PostMapping("/channel/queryOrder")
    public ResponseVO<PayOrderNotifyDTO> queryOrder(@RequestBody PayQueryDTO dto) {
        return getSuccessResponseVO(payInternalService.queryOrder(dto));
    }
}
