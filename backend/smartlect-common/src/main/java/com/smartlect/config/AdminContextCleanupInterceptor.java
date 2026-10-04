package com.smartlect.config;

import com.smartlect.security.AdminSecurityContext;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.lang.NonNull;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;

/**
 * 请求结束后清理 AdminSecurityContext ThreadLocal。
 * 原 AppInterceptor.afterCompletion 的职责，随 AppInterceptor 退役迁移至此。
 */
@Component
public class AdminContextCleanupInterceptor implements HandlerInterceptor {
    @Override
    public void afterCompletion(@NonNull HttpServletRequest request,
                               @NonNull HttpServletResponse response,
                               @NonNull Object handler, Exception ex) {
        AdminSecurityContext.clear();
    }
}
