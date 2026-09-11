package com.smartlect.controller.admin;

import com.smartlect.entity.dto.MemberLevelRewardConfigDTO;
import com.smartlect.entity.vo.ResponseVO;
import com.smartlect.biz.MemberLevelRewardConfigService;
import jakarta.annotation.Resource;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;

@RequestMapping("/admin/memberLevelRewardConfig")
@RestController
public class MemberLevelRewardConfigController extends com.smartlect.controller.admin.ABaseController {

    @Resource
    private MemberLevelRewardConfigService memberLevelRewardConfigService;

    @PostMapping("/getConfig")
    public ResponseVO getConfig() {
        return getSuccessResponseVO(memberLevelRewardConfigService.getConfig());
    }

    @PostMapping("/saveConfig")
    public ResponseVO saveConfig(MemberLevelRewardConfigDTO config) {
        memberLevelRewardConfigService.saveConfig(config);
        return getSuccessResponseVO(null);
    }
}
