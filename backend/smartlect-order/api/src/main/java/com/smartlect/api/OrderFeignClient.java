package com.smartlect.api;

import com.smartlect.api.dto.CouponRushPayRequestDTO;
import com.smartlect.api.dto.CouponRushPrepareRequestDTO;
import com.smartlect.api.dto.OrderIdDTO;
import com.smartlect.api.dto.OrderStatsRangeDTO;
import com.smartlect.api.dto.UserIdDTO;
import com.smartlect.api.fallback.OrderFeignFallbackFactory;
import com.smartlect.api.vo.OrderBriefVO;
import com.smartlect.api.vo.OrderDailyStatsVO;
import com.smartlect.api.vo.OrderRangeStatsVO;
import com.smartlect.api.dto.CouponRushPrepareDTO;
import com.smartlect.api.dto.PayInfoDTO;
import com.smartlect.api.dto.PayOrderNotifyDTO;
import com.smartlect.entity.vo.ResponseVO;
import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;

import java.util.List;

@FeignClient(name = "smartlect-order", contextId = "orderFeignClient", path = "/internal/order",
        fallbackFactory = OrderFeignFallbackFactory.class)
public interface OrderFeignClient {

    @PostMapping("/get")
    ResponseVO<OrderBriefVO> getOrder(@RequestBody OrderIdDTO dto);

    @PostMapping("/cancelUnpaidForPayTimeout")
    ResponseVO<Boolean> cancelUnpaidForPayTimeout(@RequestBody OrderIdDTO dto);

    @PostMapping("/confirmReceipt")
    ResponseVO<Boolean> confirmReceipt(@RequestBody OrderIdDTO dto);

    @PostMapping("/onConfirmed")
    ResponseVO<Void> onConfirmed(@RequestBody OrderIdDTO dto);

    @PostMapping("/paySuccess")
    ResponseVO<Void> paySuccess(@RequestBody PayOrderNotifyDTO dto);

    @PostMapping("/prepareCouponRush")
    ResponseVO<CouponRushPrepareDTO> prepareCouponRush(
            @RequestBody CouponRushPrepareRequestDTO dto,
            @RequestHeader("Idempotency-Key") String idempotencyKey);

    @PostMapping("/postCouponRushOrder")
    ResponseVO<PayInfoDTO> postCouponRushOrder(
            @RequestBody CouponRushPayRequestDTO dto,
            @RequestHeader("Idempotency-Key") String idempotencyKey);

    @PostMapping("/syncPaidCouponRushUserCoupons")
    ResponseVO<Void> syncPaidCouponRushUserCoupons(@RequestBody UserIdDTO dto);

    @PostMapping("/cancelOrder")
    ResponseVO<Void> cancelOrder(@RequestBody OrderIdDTO dto);

    @PostMapping("/stats/range")
    ResponseVO<OrderRangeStatsVO> aggregateRange(@RequestBody OrderStatsRangeDTO dto);

    @PostMapping("/stats/daily")
    ResponseVO<List<OrderDailyStatsVO>> aggregateDaily(@RequestBody OrderStatsRangeDTO dto);

    @PostMapping("/tool/addAllWaitPayToDelayQueue")
    ResponseVO<Void> addAllWaitPayToDelayQueue();
}
