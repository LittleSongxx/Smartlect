package com.smartlect.api.fallback;

import com.smartlect.api.UserFeignClient;
import com.smartlect.api.dto.UserAddressQueryDTO;
import com.smartlect.api.dto.UserGrowthAddDTO;
import com.smartlect.api.dto.UserIdsDTO;
import com.smartlect.api.dto.UserJoinCountDTO;
import com.smartlect.api.dto.UserNotifyDTO;
import com.smartlect.api.support.FeignFallbackResponses;
import com.smartlect.api.vo.UserAddressVO;
import com.smartlect.api.vo.UserBriefVO;
import com.smartlect.entity.vo.ResponseVO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.cloud.openfeign.FallbackFactory;
import org.springframework.stereotype.Component;

import java.util.List;

@Slf4j
@Component
public class UserFeignFallbackFactory implements FallbackFactory<UserFeignClient> {

    @Override
    public UserFeignClient create(Throwable cause) {
        log.warn("User Feign fallback: {}", cause == null ? "unknown" : cause.toString());
        return new UserFeignClient() {
            @Override
            public ResponseVO<UserAddressVO> getAddress(UserAddressQueryDTO dto, String userId) {
                return FeignFallbackResponses.unavailable("用户服务");
            }

            @Override
            public ResponseVO<Void> addGrowthOnPay(UserGrowthAddDTO dto, String userId) {
                return FeignFallbackResponses.unavailable("用户服务");
            }

            @Override
            public ResponseVO<Void> sendNotifyAsync(UserNotifyDTO dto) {
                return FeignFallbackResponses.unavailable("用户服务");
            }

            @Override
            public ResponseVO<List<String>> listAllUserIds() {
                return FeignFallbackResponses.unavailable("用户服务");
            }

            @Override
            public ResponseVO<List<UserBriefVO>> listBriefByUserIds(UserIdsDTO dto) {
                return FeignFallbackResponses.unavailable("用户服务");
            }

            @Override
            public ResponseVO<Integer> countByJoinDate(UserJoinCountDTO dto) {
                return FeignFallbackResponses.unavailable("用户服务");
            }
        };
    }
}
