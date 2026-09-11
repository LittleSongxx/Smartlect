package com.smartlect.biz;

import com.smartlect.api.dto.OrderGrowthEventDTO;
import com.smartlect.entity.po.UserMemberProfile;
import com.smartlect.entity.vo.MemberCenterVO;

public interface UserMemberProfileService {

    UserMemberProfile getOrInitProfile(String userId);

    MemberCenterVO getMemberCenter(String userId);

    void claimLevelReward(String userId, Integer levelCode);

    void addGrowthOnPay(String userId, java.math.BigDecimal payAmount);

    boolean applyOrderGrowth(OrderGrowthEventDTO event);

    void addGrowth(String userId, int points);
}
