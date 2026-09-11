package com.smartlect.api;

import com.smartlect.api.dto.CartDeleteBatchDTO;
import com.smartlect.api.fallback.CartFeignFallbackFactory;
import com.smartlect.entity.vo.ResponseVO;
import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;

@FeignClient(name = "smartlect-cart", contextId = "cartFeignClient", path = "/internal/cart",
        fallbackFactory = CartFeignFallbackFactory.class)
public interface CartFeignClient {

    @PostMapping("/deleteBatch")
    ResponseVO<Void> deleteBatch(@RequestBody CartDeleteBatchDTO dto);
}
