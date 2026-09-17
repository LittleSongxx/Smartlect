package com.smartlect.controller.internal;

import com.smartlect.api.enums.UserStatusEnum;
import com.smartlect.biz.AdminIdentityService;
import com.smartlect.biz.UserInfoService;
import com.smartlect.component.RedisComponent;
import com.smartlect.controller.ABaseController;
import com.smartlect.entity.dto.AdminPrincipalDTO;
import com.smartlect.entity.dto.TokenUserInfoDTO;
import com.smartlect.constants.TrialIdentities;
import com.smartlect.entity.po.UserInfo;
import com.smartlect.entity.vo.ResponseVO;
import com.smartlect.exception.BusinessException;
import com.smartlect.exception.HttpBusinessException;
import com.smartlect.utils.StringTools;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import org.apache.commons.codec.digest.DigestUtils;
import org.springframework.http.HttpStatus;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/** InternalApiAuthFilter authenticates the service; the cookie identifies its caller. */
@RestController
@RequestMapping("/internal/identity")
public class IdentityInternalController extends ABaseController {

    private final RedisComponent sessions;
    private final UserInfoService users;
    private final AdminIdentityService administrators;

    public IdentityInternalController(
            RedisComponent sessions, UserInfoService users, AdminIdentityService administrators) {
        this.sessions = sessions;
        this.users = users;
        this.administrators = administrators;
    }

    @PostMapping("/introspect")
    public ResponseVO<Map<String, Object>> introspect(
            @RequestBody Map<String, Object> body, HttpServletRequest request) {
        if (body == null || body.size() != 1
                || !(body.get("realm") instanceof String realm)
                || !(realm.equals("user") || realm.equals("merchant"))) {
            throw new HttpBusinessException(400, "realm 必须为 user 或 merchant，且不得提供其他字段");
        }
        String token = requireCookie(request, realm.equals("user") ? "token" : "adminToken");
        String actorId;
        List<String> permissions;
        if (realm.equals("user")) {
            TokenUserInfoDTO session = sessions.getTokenUserInfo(token);
            if (session == null || StringTools.isEmpty(session.getUserId())) {
                throw unauthorized();
            }
            UserInfo user = users.getUserInfoByUserId(session.getUserId());
            if (user == null || !Objects.equals(UserStatusEnum.ENABLE.getStatus(), user.getStatus())) {
                throw unauthorized();
            }
            actorId = session.getUserId();
            if (TrialIdentities.isTrialUser(user.getUserId(), user.getEmail())) {
                permissions = List.of("shopping:read", "orders:read", TrialIdentities.ACCOUNT_TRIAL);
            } else {
                permissions = List.of("shopping:read", "orders:read", "orders:write");
            }
        } else {
            AdminPrincipalDTO session = sessions.getAdminPrincipal(token);
            if (session == null || session.getSessionVersion() == null) {
                throw unauthorized();
            }
            AdminPrincipalDTO principal;
            try {
                principal = administrators.principal(Long.parseLong(session.getAdminId()));
            } catch (BusinessException | NumberFormatException e) {
                throw unauthorized();
            }
            if (principal == null || !Objects.equals(session.getAdminId(), principal.getAdminId())
                    || !Objects.equals(session.getSessionVersion(), principal.getSessionVersion())) {
                throw unauthorized();
            }
            actorId = principal.getAdminId();
            permissions = principal.getPermissions().stream().sorted().toList();
        }
        return getSuccessResponseVO(Map.of(
                "subjectType", realm, "actorId", actorId, "permissions", permissions,
                "sessionId", DigestUtils.sha256Hex(realm + ":" + token)));
    }

    private static String requireCookie(HttpServletRequest request, String name) {
        Cookie[] cookies = request.getCookies();
        List<Cookie> matching = cookies == null ? List.of()
                : Arrays.stream(cookies).filter(cookie -> name.equals(cookie.getName())).toList();
        if (matching.size() != 1) {
            throw unauthorized();
        }
        String token = matching.get(0).getValue();
        if (StringTools.isEmpty(token) || token.length() > 256 || !token.equals(token.trim())) {
            throw unauthorized();
        }
        return token;
    }

    private static HttpBusinessException unauthorized() {
        return new HttpBusinessException(401, "登录会话无效或主体已停用");
    }

    @ExceptionHandler(HttpMessageNotReadableException.class)
    @ResponseStatus(HttpStatus.BAD_REQUEST)
    public ResponseVO<?> invalidBody() {
        return getBusinessErrorResponseVO(new HttpBusinessException(400, "请求体必须是有效的 realm JSON 对象"), null);
    }
}
