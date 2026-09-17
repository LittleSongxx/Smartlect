package com.smartlect.api.fallback;

import com.smartlect.api.CouponFeignClient;
import com.smartlect.api.dto.CouponIdDTO;
import com.smartlect.api.dto.CouponRushOpsDTO;
import com.smartlect.api.dto.CouponValidateAndLockDTO;
import com.smartlect.api.dto.UserCouponCreateDTO;
import com.smartlect.api.dto.UserCouponIdDTO;
import com.smartlect.api.dto.UserCouponStatusChangeDTO;
import com.smartlect.api.support.FeignFallbackResponses;
import com.smartlect.api.vo.CouponBriefVO;
import com.smartlect.api.vo.CouponLockResultVO;
import com.smartlect.api.vo.DiscountCouponVO;
import com.smartlect.api.vo.StockChangeResultVO;
import com.smartlect.api.vo.UserCouponVO;
import com.smartlect.entity.vo.ResponseVO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.cloud.openfeign.FallbackFactory;
import org.springframework.stereotype.Component;

@Slf4j
@Component
public class CouponFeignFallbackFactory implements FallbackFactory<CouponFeignClient> {

    @Override
    public CouponFeignClient create(Throwable cause) {
        log.warn("Coupon Feign fallback: {}", cause == null ? "unknown" : cause.toString());
        return new CouponFeignClient() {
            @Override
            public ResponseVO<CouponLockResultVO> validateAndLock(CouponValidateAndLockDTO dto, String userId) {
                return FeignFallbackResponses.unavailable("优惠券服务");
            }

            @Override
            public ResponseVO<CouponLockResultVO> preview(CouponValidateAndLockDTO dto, String userId) {
                return FeignFallbackResponses.unavailable("优惠券服务");
            }

            @Override
            public ResponseVO<DiscountCouponVO> getCoupon(CouponIdDTO dto) {
                return FeignFallbackResponses.unavailable("优惠券服务");
            }

            @Override
            public ResponseVO<CouponBriefVO> getCouponBrief(CouponIdDTO dto) {
                return FeignFallbackResponses.unavailable("优惠券服务");
            }

            @Override
            public ResponseVO<UserCouponVO> getUserCoupon(UserCouponIdDTO dto) {
                return FeignFallbackResponses.unavailable("优惠券服务");
            }

            @Override
            public ResponseVO<Void> changeUserCouponStatus(UserCouponStatusChangeDTO dto, String userId) {
                return FeignFallbackResponses.unavailable("优惠券服务");
            }

            @Override
            public ResponseVO<Void> createUserCoupon(UserCouponCreateDTO dto, String userId) {
                return FeignFallbackResponses.unavailable("优惠券服务");
            }

            @Override
            public ResponseVO<com.smartlect.api.vo.CouponGrantResultVO> grantCoupon(
                    UserCouponCreateDTO dto, String userId) {
                return FeignFallbackResponses.unavailable("优惠券服务");
            }

            @Override
            public ResponseVO<StockChangeResultVO> deductStock(CouponIdDTO dto, String userId) {
                return FeignFallbackResponses.unavailable("优惠券服务");
            }

            @Override
            public ResponseVO<Void> assertRushNotBlocked(CouponRushOpsDTO dto) {
                return FeignFallbackResponses.unavailable("优惠券服务");
            }

            @Override
            public ResponseVO<Boolean> hasAvailableRushStock(CouponRushOpsDTO dto) {
                return FeignFallbackResponses.unavailable("优惠券服务");
            }

            @Override
            public ResponseVO<Void> syncRushStockFromDbIfRedisZero(CouponRushOpsDTO dto) {
                return FeignFallbackResponses.unavailable("优惠券服务");
            }

            @Override
            public ResponseVO<Void> releaseRushRedisReserve(CouponRushOpsDTO dto) {
                return FeignFallbackResponses.unavailable("优惠券服务");
            }

            @Override
            public ResponseVO<Void> releaseRushCouponReserve(CouponRushOpsDTO dto) {
                return FeignFallbackResponses.unavailable("优惠券服务");
            }

            @Override
            public ResponseVO<Void> invalidateCouponCache(CouponRushOpsDTO dto) {
                return FeignFallbackResponses.unavailable("优惠券服务");
            }
        };
    }
}
