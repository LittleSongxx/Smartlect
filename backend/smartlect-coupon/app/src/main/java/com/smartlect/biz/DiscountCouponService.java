package com.smartlect.biz;

import java.util.List;

import com.smartlect.api.dto.CouponRushPrepareDTO;
import com.smartlect.api.dto.DiscountCouponDTO;
import com.smartlect.api.dto.PayInfoDTO;
import com.smartlect.entity.query.DiscountCouponQuery;
import com.smartlect.entity.po.DiscountCoupon;
import com.smartlect.entity.vo.PaginationResultVO;
import jakarta.validation.constraints.NotEmpty;

public interface DiscountCouponService {

	List<DiscountCoupon> findListByParam(DiscountCouponQuery param);

	Integer findCountByParam(DiscountCouponQuery param);

	PaginationResultVO<DiscountCoupon> findListByPage(DiscountCouponQuery param);

	Integer add(DiscountCoupon bean);

	Integer addBatch(List<DiscountCoupon> listBean);

	Integer addOrUpdateBatch(List<DiscountCoupon> listBean);

	Integer updateByParam(DiscountCoupon bean,DiscountCouponQuery param);

	Integer deleteByParam(DiscountCouponQuery param);

	DiscountCoupon getDiscountCouponByCouponId(String couponId);

	Integer updateDiscountCouponByCouponId(DiscountCoupon bean,String couponId);

	Integer deleteDiscountCouponByCouponId(String couponId);

	PaginationResultVO loadDiscountCoupon(Integer pageNo, Integer pageSize, @NotEmpty String status, String keyword);

	void fillHasBoughtForPlaza(String userId, java.util.List<com.smartlect.entity.po.DiscountCoupon> list);

	void saveDiscountCoupon(DiscountCouponDTO discountCoupon);

	PaginationResultVO loadDiscountCoupon4Admin(Integer pageNo, Integer pageSize, String couponNameFuzzy, Integer couponType, Integer status);

	CouponRushPrepareDTO rushCoupon(
			@NotEmpty String userId,
			@NotEmpty String couponId,
			@NotEmpty String idempotencyKey);

	PayInfoDTO buyDiscountCoupon(
			@NotEmpty String userId,
			@NotEmpty String couponId,
			@NotEmpty String payMethod,
			@NotEmpty String idempotencyKey);

	void releaseRushRedisReserve(String couponId, String userId);

	void releaseRushCouponReserve(String couponId, String userId);

	java.math.BigDecimal calcDiscountAmount(com.smartlect.entity.po.DiscountCoupon coupon, java.math.BigDecimal orderAmount);
}
