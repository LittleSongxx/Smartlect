package com.smartlect.controller.internal;

import com.smartlect.api.dto.CouponIdDTO;
import com.smartlect.api.dto.CouponRushOpsDTO;
import com.smartlect.api.dto.CouponValidateAndLockDTO;
import com.smartlect.api.dto.UserCouponCreateDTO;
import com.smartlect.api.dto.UserCouponIdDTO;
import com.smartlect.api.dto.UserCouponStatusChangeDTO;
import com.smartlect.api.vo.CouponBriefVO;
import com.smartlect.api.vo.CouponLockResultVO;
import com.smartlect.api.vo.DiscountCouponVO;
import com.smartlect.api.vo.StockChangeResultVO;
import com.smartlect.api.vo.UserCouponVO;
import com.smartlect.biz.CouponInternalService;
import com.smartlect.controller.ABaseController;
import com.smartlect.entity.vo.ResponseVO;
import jakarta.annotation.Resource;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/internal/coupon")
public class CouponInternalController extends ABaseController {

    @Resource
    private CouponInternalService couponInternalService;

    @PostMapping("/validateAndLock")
    public ResponseVO<CouponLockResultVO> validateAndLock(@Valid @RequestBody CouponValidateAndLockDTO dto) {
        com.smartlect.security.DelegatedUserIdentity.requireAndMatch(dto.getUserId());
        return getSuccessResponseVO(couponInternalService.validateAndLock(dto));
    }

    @PostMapping("/preview")
    public ResponseVO<CouponLockResultVO> preview(@Valid @RequestBody CouponValidateAndLockDTO dto) {
        com.smartlect.security.DelegatedUserIdentity.requireAndMatch(dto.getUserId());
        return getSuccessResponseVO(couponInternalService.preview(dto));
    }

    @PostMapping("/getCoupon")
    public ResponseVO<DiscountCouponVO> getCoupon(@Valid @RequestBody CouponIdDTO dto) {
        return getSuccessResponseVO(couponInternalService.getCoupon(dto.getCouponId()));
    }

    @PostMapping("/getCouponBrief")
    public ResponseVO<CouponBriefVO> getCouponBrief(@Valid @RequestBody CouponIdDTO dto) {
        return getSuccessResponseVO(couponInternalService.getCouponBrief(dto.getCouponId()));
    }

    @PostMapping("/getUserCoupon")
    public ResponseVO<UserCouponVO> getUserCoupon(@Valid @RequestBody UserCouponIdDTO dto) {
        return getSuccessResponseVO(couponInternalService.getUserCoupon(dto.getUserCouponId()));
    }

    @PostMapping("/changeUserCouponStatus")
    public ResponseVO<Void> changeUserCouponStatus(@Valid @RequestBody UserCouponStatusChangeDTO dto) {
        com.smartlect.security.DelegatedUserIdentity.requireAndMatch(dto.getUserId());
        couponInternalService.changeUserCouponStatus(dto);
        return getSuccessResponseVO(null);
    }

    @PostMapping("/createUserCoupon")
    public ResponseVO<Void> createUserCoupon(@Valid @RequestBody UserCouponCreateDTO dto) {
        com.smartlect.security.DelegatedUserIdentity.requireAndMatch(dto.getUserId());
        couponInternalService.createUserCoupon(dto);
        return getSuccessResponseVO(null);
    }

    @PostMapping("/grantCoupon")
    public ResponseVO<com.smartlect.api.vo.CouponGrantResultVO> grantCoupon(
            @Valid @RequestBody UserCouponCreateDTO dto) {
        com.smartlect.security.DelegatedUserIdentity.requireAndMatch(dto.getUserId());
        return getSuccessResponseVO(couponInternalService.grantCoupon(dto));
    }

    @PostMapping("/deductStock")
    public ResponseVO<StockChangeResultVO> deductStock(@Valid @RequestBody CouponIdDTO dto) {
        com.smartlect.security.DelegatedUserIdentity.require();
        return getSuccessResponseVO(new StockChangeResultVO(couponInternalService.deductStock(dto.getCouponId())));
    }

    @PostMapping("/rush/assertNotBlocked")
    public ResponseVO<Void> assertRushNotBlocked(@RequestBody CouponRushOpsDTO dto) {
        couponInternalService.assertRushNotBlocked(dto.getCouponId());
        return getSuccessResponseVO(null);
    }

    @PostMapping("/rush/hasAvailableStock")
    public ResponseVO<Boolean> hasAvailableRushStock(@RequestBody CouponRushOpsDTO dto) {
        return getSuccessResponseVO(couponInternalService.hasAvailableRushStock(dto.getCouponId()));
    }

    @PostMapping("/rush/syncFromDbIfRedisZero")
    public ResponseVO<Void> syncRushStockFromDbIfRedisZero(@RequestBody CouponRushOpsDTO dto) {
        couponInternalService.syncRushStockFromDbIfRedisZero(dto.getCouponId());
        return getSuccessResponseVO(null);
    }

    @PostMapping("/rush/releaseRedisReserve")
    public ResponseVO<Void> releaseRushRedisReserve(@RequestBody CouponRushOpsDTO dto) {
        couponInternalService.releaseRushRedisReserve(dto.getCouponId(), dto.getUserId());
        return getSuccessResponseVO(null);
    }

    @PostMapping("/rush/releaseCouponReserve")
    public ResponseVO<Void> releaseRushCouponReserve(@RequestBody CouponRushOpsDTO dto) {
        couponInternalService.releaseRushCouponReserve(dto.getCouponId(), dto.getUserId());
        return getSuccessResponseVO(null);
    }

    @PostMapping("/rush/invalidateCache")
    public ResponseVO<Void> invalidateCouponCache(@RequestBody CouponRushOpsDTO dto) {
        couponInternalService.invalidateCouponCache(dto.getCouponId());
        return getSuccessResponseVO(null);
    }
}
