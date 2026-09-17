package com.smartlect.interceptor;

import com.smartlect.component.RedisComponent;
import com.smartlect.constants.TrialIdentities;
import com.smartlect.entity.dto.TokenUserInfoDTO;
import com.smartlect.entity.enums.ResponseCodeEnum;
import com.smartlect.security.TrialUserAccess;
import com.smartlect.utils.AuthCookieHelper;
import com.smartlect.utils.StringTools;
import jakarta.annotation.Resource;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.nio.charset.StandardCharsets;

@Component
@Order(Ordered.HIGHEST_PRECEDENCE + 40)
public class TrialUserWriteFilter extends OncePerRequestFilter {

    @Resource
    private RedisComponent redisComponent;

    @Resource
    private AuthCookieHelper authCookieHelper;

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        String uri = request.getRequestURI();
        if (uri == null
                || uri.contains("/admin/")
                || uri.contains("/admin-api/")
                || uri.contains("/internal/")
                || uri.contains("/actuator/")
                || uri.contains("/notify/")) {
            return true;
        }
        return !TrialUserAccess.isBlocked(request);
    }

    @Override
    protected void doFilterInternal(
            HttpServletRequest request, HttpServletResponse response, FilterChain filterChain)
            throws ServletException, IOException {
        String token = authCookieHelper.resolveWebToken(request);
        if (!StringTools.isEmpty(token)) {
            TokenUserInfoDTO session = redisComponent.getTokenUserInfo(token);
            if (TrialIdentities.isTrialUser(session)) {
                deny(response);
                return;
            }
        }
        filterChain.doFilter(request, response);
    }

    private static void deny(HttpServletResponse response) throws IOException {
        response.setStatus(HttpServletResponse.SC_FORBIDDEN);
        response.setCharacterEncoding(StandardCharsets.UTF_8.name());
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        response.getWriter().write("{\"status\":\"error\",\"code\":"
                + ResponseCodeEnum.CODE_403.getCode()
                + ",\"info\":\"" + TrialIdentities.USER_DENIED + "\",\"data\":null}");
    }
}
