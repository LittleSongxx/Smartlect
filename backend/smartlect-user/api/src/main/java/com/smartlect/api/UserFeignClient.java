package com.smartlect.api;

import com.smartlect.api.dto.UserAddressQueryDTO;
import com.smartlect.api.dto.UserGrowthAddDTO;
import com.smartlect.api.dto.UserIdsDTO;
import com.smartlect.api.dto.UserJoinCountDTO;
import com.smartlect.api.dto.UserNotifyDTO;
import com.smartlect.api.vo.UserAddressVO;
import com.smartlect.api.vo.UserBriefVO;
import com.smartlect.api.fallback.UserFeignFallbackFactory;
import com.smartlect.entity.vo.ResponseVO;
import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;

import java.util.List;

@FeignClient(name = "smartlect-user", contextId = "userFeignClient", path = "/internal/user",
        fallbackFactory = UserFeignFallbackFactory.class)
public interface UserFeignClient {

    @PostMapping("/address/get")
    ResponseVO<UserAddressVO> getAddress(@RequestBody UserAddressQueryDTO dto);

    @PostMapping("/member/addGrowthOnPay")
    ResponseVO<Void> addGrowthOnPay(@RequestBody UserGrowthAddDTO dto);

    @PostMapping("/notify/sendAsync")
    ResponseVO<Void> sendNotifyAsync(@RequestBody UserNotifyDTO dto);

    @PostMapping("/listAllUserIds")
    ResponseVO<List<String>> listAllUserIds();

    @PostMapping("/listBriefByUserIds")
    ResponseVO<List<UserBriefVO>> listBriefByUserIds(@RequestBody UserIdsDTO dto);

    @PostMapping("/countByJoinDate")
    ResponseVO<Integer> countByJoinDate(@RequestBody UserJoinCountDTO dto);
}
