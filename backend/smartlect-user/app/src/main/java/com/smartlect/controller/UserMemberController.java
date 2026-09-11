package com.smartlect.controller;

import com.smartlect.annotation.GlobalInterceptor;
import com.smartlect.entity.dto.TokenUserInfoDTO;
import com.smartlect.entity.po.UserMemberProfile;
import com.smartlect.entity.vo.ResponseVO;
import com.smartlect.exception.BusinessException;
import com.smartlect.biz.UserMemberProfileService;
import com.smartlect.utils.StringTools;
import jakarta.annotation.Resource;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.HashMap;
import java.util.Map;

@RequestMapping("/userMember")
@RestController
public class UserMemberController extends ABaseController {

    @Resource
    private UserMemberProfileService userMemberProfileService;

    private String getCurrentUserId() {
        TokenUserInfoDTO tokenUserInfo = getTokenUserInfo();
        if (tokenUserInfo == null || StringTools.isEmpty(tokenUserInfo.getUserId())) {
            throw new BusinessException("登录超时");
        }
        return tokenUserInfo.getUserId();
    }

    private boolean isCenterRequest(String center) {
        return center != null && ("true".equalsIgnoreCase(center) || "1".equals(center));
    }

    @GetMapping("/getProfile")
    @GlobalInterceptor(checkLogin = true)
    public ResponseVO getProfile(@RequestParam(required = false) String center) {
        String userId = getCurrentUserId();
        if (isCenterRequest(center)) {
            return getSuccessResponseVO(userMemberProfileService.getMemberCenter(userId));
        }
        return getSuccessResponseVO(userMemberProfileService.getOrInitProfile(userId));
    }

    @GetMapping("/getMemberCenter")
    @GlobalInterceptor(checkLogin = true)
    public ResponseVO getMemberCenter() {
        return getSuccessResponseVO(userMemberProfileService.getMemberCenter(getCurrentUserId()));
    }

    @GetMapping("/loadMemberCenter")
    @GlobalInterceptor(checkLogin = true)
    public ResponseVO loadMemberCenter() {
        return getSuccessResponseVO(userMemberProfileService.getMemberCenter(getCurrentUserId()));
    }

    @PostMapping("/claimLevelReward")
    @GlobalInterceptor(checkLogin = true)
    public ResponseVO claimLevelReward(Integer levelCode) {
        String userId = getCurrentUserId();
        userMemberProfileService.claimLevelReward(userId, levelCode);
        return getSuccessResponseVO(userMemberProfileService.getMemberCenter(userId));
    }

    @GetMapping("/getLevelBadge")
    public ResponseVO getLevelBadge(@RequestParam String userId) {
        if (StringTools.isEmpty(userId)) {
            throw new BusinessException("参数错误");
        }
        UserMemberProfile profile = userMemberProfileService.getOrInitProfile(userId);
        Map<String, Object> result = new HashMap<>();
        result.put("userId", userId);
        result.put("levelCode", profile.getLevelCode());
        result.put("levelName", profile.getLevelName());
        return getSuccessResponseVO(result);
    }
}
