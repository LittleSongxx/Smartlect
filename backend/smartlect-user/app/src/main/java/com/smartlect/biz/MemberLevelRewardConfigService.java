package com.smartlect.biz;

import com.smartlect.entity.dto.MemberLevelRewardConfigDTO;

public interface MemberLevelRewardConfigService {

    MemberLevelRewardConfigDTO getConfig();

    void saveConfig(MemberLevelRewardConfigDTO config);

    String resolveLevelCouponId(int levelCode);
}
