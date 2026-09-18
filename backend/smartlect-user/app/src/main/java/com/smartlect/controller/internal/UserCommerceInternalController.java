package com.smartlect.controller.internal;

import com.smartlect.controller.ABaseController;
import com.smartlect.entity.po.UserBrowseHistory;
import com.smartlect.entity.po.UserAddress;
import com.smartlect.entity.query.UserAddressQuery;
import com.smartlect.biz.UserAddressService;
import com.smartlect.entity.query.SimplePage;
import com.smartlect.entity.query.UserBrowseHistoryQuery;
import com.smartlect.entity.vo.ResponseVO;
import com.smartlect.mappers.UserBrowseHistoryMapper;
import com.smartlect.security.DelegatedUserIdentity;
import com.smartlect.utils.StringTools;
import jakarta.annotation.Resource;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/internal/user/commerce")
public class UserCommerceInternalController extends ABaseController {

    @Resource
    private UserBrowseHistoryMapper<UserBrowseHistory, UserBrowseHistoryQuery> userBrowseHistoryMapper;

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

    @PostMapping("/latestBrowseProductId")
    public ResponseVO<Map<String, String>> latestBrowseProductId(@RequestBody Map<String, Object> body) {
        String userId = DelegatedUserIdentity.requireAndMatch(body == null ? null : body.get("userId"));
        UserBrowseHistoryQuery q = new UserBrowseHistoryQuery();
        q.setUserId(userId);
        q.setOrderBy(com.smartlect.entity.query.SafeSort.of("u.browse_time desc"));
        q.setSimplePage(new SimplePage(0, 1));
        List<UserBrowseHistory> list = userBrowseHistoryMapper.selectList(q);
        if (list == null || list.isEmpty() || StringTools.isEmpty(list.get(0).getProductId())) {
            return getSuccessResponseVO(null);
        }
        Map<String, String> data = new HashMap<>();
        data.put("productId", list.get(0).getProductId());
        return getSuccessResponseVO(data);
    }

    /**
     * Distinct recently-browsed product IDs, newest first.
     *
     * <p>The assistant service votes on the category of these products to pick a
     * recommendation shelf, so duplicates are collapsed here: five views of the
     * same phone should count once, not carry the whole vote. Rows are
     * over-fetched because de-duplication happens after the query.
     */
    @PostMapping("/browseHistoryIds")
    public ResponseVO<List<String>> browseHistoryIds(@RequestBody Map<String, Object> body) {
        String userId = DelegatedUserIdentity.requireAndMatch(body == null ? null : body.get("userId"));
        int limit = 5;
        Object rawLimit = body == null ? null : body.get("limit");
        if (rawLimit != null) {
            try {
                limit = Integer.parseInt(String.valueOf(rawLimit));
            } catch (NumberFormatException ignored) {
                limit = 5;
            }
        }
        limit = Math.max(1, Math.min(limit, 20));

        UserBrowseHistoryQuery q = new UserBrowseHistoryQuery();
        q.setUserId(userId);
        q.setOrderBy(com.smartlect.entity.query.SafeSort.of("u.browse_time desc"));
        q.setSimplePage(new SimplePage(0, Math.min(limit * 4, 80)));
        List<UserBrowseHistory> list = userBrowseHistoryMapper.selectList(q);
        if (list == null || list.isEmpty()) {
            return getSuccessResponseVO(Collections.emptyList());
        }
        List<String> ids = new ArrayList<>();
        for (UserBrowseHistory row : list) {
            String productId = row.getProductId();
            if (!StringTools.isEmpty(productId) && !ids.contains(productId)) {
                ids.add(productId);
                if (ids.size() >= limit) {
                    break;
                }
            }
        }
        return getSuccessResponseVO(ids);
    }
}
