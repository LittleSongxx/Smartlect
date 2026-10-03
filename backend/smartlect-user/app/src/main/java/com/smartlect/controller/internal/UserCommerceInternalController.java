package com.smartlect.controller.internal;

import com.smartlect.controller.ABaseController;
import com.smartlect.entity.po.UserAddress;
import com.smartlect.entity.query.UserAddressQuery;
import com.smartlect.biz.UserAddressService;
import com.smartlect.entity.query.SimplePage;
import com.smartlect.entity.vo.ResponseVO;
import com.smartlect.security.DelegatedUserIdentity;
import jakarta.annotation.Resource;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/internal/user/commerce")
public class UserCommerceInternalController extends ABaseController {

    @Resource
    private UserAddressService userAddressService;

    @PostMapping("/listAddresses")
    public ResponseVO<List<Map<String, Object>>> listAddresses(@RequestBody Map<String, Object> body) {
        String userId = DelegatedUserIdentity.requireAndMatch(body == null ? null : body.get("userId"));
        UserAddressQuery query = new UserAddressQuery();
        query.setUserId(userId);
        query.setSimplePage(new SimplePage(0, 20));
        List<Map<String, Object>> result = new ArrayList<>();
        for (UserAddress address : userAddressService.findListByParam(query)) {
            result.add(Map.of("addressId", address.getAddressId(),
                    "isDefault", Integer.valueOf(1).equals(address.getDefaultType()),
                    "label", "收货地址 " + (result.size() + 1)));
        }
        return getSuccessResponseVO(result);
    }
}
