package com.smartlect.controller.internal;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.smartlect.biz.CommerceV2Service;
import com.smartlect.biz.OrderInfoService;
import com.smartlect.biz.OrderQuoteService;
import com.smartlect.controller.ABaseController;
import com.smartlect.entity.vo.ResponseVO;
import com.smartlect.security.DelegatedUserIdentity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

@RestController
@RequestMapping("/internal/order/commerce/v2")
public class OrderCommerceV2Controller extends ABaseController {
    private final OrderInfoService orders;
    private final CommerceV2Service actions;

    public OrderCommerceV2Controller(OrderInfoService orders, CommerceV2Service actions) {
        this.orders = orders;
        this.actions = actions;
    }

    @PostMapping("/quote")
    public ResponseVO<Map<String, Object>> quote(@RequestBody JsonNode body) {
        String userId = DelegatedUserIdentity.require();
        return getSuccessResponseVO(orders.quoteOrder(userId,
                OrderQuoteService.normalize(OrderQuoteService.parse(body, OrderQuoteService.Input.class))));
    }

    @PostMapping("/createConfirmed")
    public ResponseVO<Map<String, Object>> createConfirmed(@RequestBody JsonNode body,
            @RequestHeader("Idempotency-Key") String key) {
        String userId = DelegatedUserIdentity.require();
        JsonNode rawContext = body == null ? null : body.get("attributionContextToken");
        JsonNode purchase = body;
        if (body != null && body.isObject()) {
            ObjectNode copy = body.deepCopy();
            copy.remove("attributionContextToken");
            purchase = copy;
        }
        // Invalid optional context must not weaken purchase validation or fail an otherwise valid purchase.
        String context = rawContext != null && rawContext.isTextual() ? rawContext.textValue() : null;
        OrderQuoteService.Confirmed request = OrderQuoteService.parse(purchase, OrderQuoteService.Confirmed.class);
        return getSuccessResponseVO(CommerceV2Service.created(orders.createConfirmed(userId,
                OrderQuoteService.normalize(request.order()), request.quoteId(), request.confirmedAmountCents(), key,
                context)));
    }

    @PostMapping("/executeAction")
    public ResponseVO<Map<String, Object>> execute(@RequestBody JsonNode body,
            @RequestHeader("Idempotency-Key") String key) {
        String userId = DelegatedUserIdentity.require();
        return getSuccessResponseVO(actions.execute(userId,
                OrderQuoteService.parse(body, CommerceV2Service.Action.class), key));
    }

    @PostMapping("/actionStatus")
    public ResponseVO<Map<String, Object>> status(@RequestBody JsonNode body) {
        String userId = DelegatedUserIdentity.require();
        return getSuccessResponseVO(actions.status(userId,
                OrderQuoteService.parse(body, CommerceV2Service.Status.class)));
    }
}
