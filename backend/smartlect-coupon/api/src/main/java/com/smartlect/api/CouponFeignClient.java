package com.smartlect.api;

import com.smartlect.api.dto.CouponIdDTO;
import com.smartlect.api.dto.CouponValidateAndLockDTO;
import com.smartlect.api.dto.UserCouponCreateDTO;
import com.smartlect.api.dto.UserCouponIdDTO;
import com.smartlect.api.dto.UserCouponStatusChangeDTO;
import com.smartlect.api.vo.CouponBriefVO;
import com.smartlect.api.vo.CouponGrantResultVO;
import com.smartlect.api.vo.CouponLockResultVO;
import com.smartlect.api.vo.DiscountCouponVO;
import com.smartlect.api.vo.StockChangeResultVO;
import com.smartlect.api.vo.UserCouponVO;
import com.smartlect.api.fallback.CouponFeignFallbackFactory;
import com.smartlect.entity.vo.ResponseVO;
import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;

@FeignClient(name = "smartlect-coupon", contextId = "couponFeignClient", path = "/internal/coupon",
        fallbackFactory = CouponFeignFallbackFactory.class)
public interface CouponFeignClient {

    @PostMapping("/validateAndLock")
    ResponseVO<CouponLockResultVO> validateAndLock(@RequestBody CouponValidateAndLockDTO dto);

    @PostMapping("/preview")
    ResponseVO<CouponLockResultVO> preview(@RequestBody CouponValidateAndLockDTO dto,
            @org.springframework.web.bind.annotation.RequestHeader("X-Smartlect-User-Id") String userId);

    @PostMapping("/getCoupon")
    ResponseVO<DiscountCouponVO> getCoupon(@RequestBody CouponIdDTO dto);

    @PostMapping("/getCouponBrief")
    ResponseVO<CouponBriefVO> getCouponBrief(@RequestBody CouponIdDTO dto);

    @PostMapping("/getUserCoupon")
    ResponseVO<UserCouponVO> getUserCoupon(@RequestBody UserCouponIdDTO dto);

    @PostMapping("/changeUserCouponStatus")
    ResponseVO<Void> changeUserCouponStatus(@RequestBody UserCouponStatusChangeDTO dto);

    @PostMapping("/createUserCoupon")
    ResponseVO<Void> createUserCoupon(@RequestBody UserCouponCreateDTO dto);

    @PostMapping("/grantCoupon")
    ResponseVO<CouponGrantResultVO> grantCoupon(@RequestBody UserCouponCreateDTO dto);

    @PostMapping("/deductStock")
    ResponseVO<StockChangeResultVO> deductStock(@RequestBody CouponIdDTO dto);

    @PostMapping("/rush/assertNotBlocked")
    ResponseVO<Void> assertRushNotBlocked(@RequestBody com.smartlect.api.dto.CouponRushOpsDTO dto);

    @PostMapping("/rush/hasAvailableStock")
    ResponseVO<Boolean> hasAvailableRushStock(@RequestBody com.smartlect.api.dto.CouponRushOpsDTO dto);

    @PostMapping("/rush/syncFromDbIfRedisZero")
    ResponseVO<Void> syncRushStockFromDbIfRedisZero(@RequestBody com.smartlect.api.dto.CouponRushOpsDTO dto);

    @PostMapping("/rush/releaseRedisReserve")
    ResponseVO<Void> releaseRushRedisReserve(@RequestBody com.smartlect.api.dto.CouponRushOpsDTO dto);

    @PostMapping("/rush/releaseCouponReserve")
    ResponseVO<Void> releaseRushCouponReserve(@RequestBody com.smartlect.api.dto.CouponRushOpsDTO dto);

    @PostMapping("/rush/invalidateCache")
    ResponseVO<Void> invalidateCouponCache(@RequestBody com.smartlect.api.dto.CouponRushOpsDTO dto);
}
