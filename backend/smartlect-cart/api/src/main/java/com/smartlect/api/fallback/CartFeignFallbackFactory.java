package com.smartlect.api.fallback;

import com.smartlect.api.CartFeignClient;
import com.smartlect.api.dto.CartDeleteBatchDTO;
import com.smartlect.api.support.FeignFallbackResponses;
import com.smartlect.entity.vo.ResponseVO;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.cloud.openfeign.FallbackFactory;
import org.springframework.stereotype.Component;

@Component
public class CartFeignFallbackFactory implements FallbackFactory<CartFeignClient> {
    private static final Logger log = LoggerFactory.getLogger(CartFeignFallbackFactory.class);

    @Override
    public CartFeignClient create(Throwable cause) {
        return dto -> {
            log.error("CartFeign deleteBatch fallback", cause);
            return FeignFallbackResponses.unavailable("购物车服务");
        };
    }
}
