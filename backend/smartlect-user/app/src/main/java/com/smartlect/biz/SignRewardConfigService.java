package com.smartlect.biz;

import com.smartlect.entity.dto.SignRewardConfigDTO;

public interface SignRewardConfigService {

    SignRewardConfigDTO getConfig();

    void saveConfig(SignRewardConfigDTO config);

    SignRewardConfigDTO resolveActiveConfig();
}
