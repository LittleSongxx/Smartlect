package com.smartlect.component;

import com.smartlect.constants.Constants;
import com.smartlect.exception.BusinessException;
import com.smartlect.exception.HttpBusinessException;
import com.smartlect.utils.StringTools;
import jakarta.annotation.Resource;
import lombok.extern.slf4j.Slf4j;
import org.redisson.api.RRateLimiter;
import org.redisson.api.RedissonClient;
import org.redisson.api.RateIntervalUnit;
import org.redisson.api.RateType;
import org.springframework.stereotype.Service;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 秒杀链路的分布式限流。Redisson RRateLimiter 取代自研固定窗口 Lua
 * （resources/lua/rate_limit_v1.lua 已随 2026-10 收敛重构退役）：
 * OVERALL 速率语义与原「每 windowSeconds 最多 maxCount 次」一致，
 * 原子性与配额存储由框架承担；限流器实例按参数三元组进程内缓存，trySetRate 幂等。
 */
@Service
@Slf4j
public class CouponRushRateLimitService {

    @Resource
    private RedissonClient redissonClient;

    private final Map<String, RRateLimiter> limiters = new ConcurrentHashMap<>();

    public void checkUserLimit(String userId) {
        checkUserLimit(userId, Constants.RUSH_RATE_USER_MAX_PER_MINUTE, Constants.RUSH_RATE_USER_WINDOW_SECONDS);
    }

    public void checkCouponLimit(String couponId) {
        checkCouponLimit(couponId, Constants.RUSH_RATE_COUPON_MAX_PER_SECOND, Constants.RUSH_RATE_COUPON_WINDOW_SECONDS);
    }

    public void checkUserLimit(String userId, int maxCount, long windowSeconds) {
        if (StringTools.isEmpty(userId)) {
            throw new BusinessException("请先登录");
        }
        String key = Constants.REDIS_KEY_RUSH_RATE_USER + userId;
        if (!tryAcquire(key, windowSeconds, maxCount)) {
            throw new HttpBusinessException(429, "操作过于频繁，请稍后再试");
        }
    }

    public void checkCouponLimit(String couponId, int maxCount, long windowSeconds) {
        if (StringTools.isEmpty(couponId)) {
            return;
        }
        String key = Constants.REDIS_KEY_RUSH_RATE_COUPON + couponId;
        if (!tryAcquire(key, windowSeconds, maxCount)) {
            throw new HttpBusinessException(429, "当前抢购人数过多，请稍后再试");
        }
    }

    public boolean tryAcquire(String key, long windowSeconds, int maxCount) {
        RRateLimiter limiter = limiters.computeIfAbsent(
                key + ":" + windowSeconds + ":" + maxCount,
                ignored -> {
                    RRateLimiter created = redissonClient.getRateLimiter("rrate:" + key);
                    created.trySetRate(RateType.OVERALL, maxCount, windowSeconds, RateIntervalUnit.SECONDS);
                    return created;
                });
        return limiter.tryAcquire();
    }
}
